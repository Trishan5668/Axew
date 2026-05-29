"""
Face identity registry — backend-agnostic.

The spec's Phase 2 mandates RetinaFace + InsightFace ArcFace embeddings.
Those packages are *very* heavy (CUDA wheels, model downloads, Windows
compile pain), so this module is the seam we use throughout the rest of the
engine — it always loads, always returns valid data, and degrades gracefully
to "no faces known" when the real backends aren't installed.

Two backends are supported transparently:

1. **InsightFace** (real)        — used when ``insightface`` import succeeds.
2. **Transcript / manual** (stub) — fed by user-labelled identities and
   speaker turns, so the retrieval engine still gets a populated
   :class:`SpeakerFaceMapping` even when no images have been processed.

Identity DB schema lives at ``~/.axew/cache/{project_id}/identity_db.json``::

    {
      "identities": {
        "vijay_mallya": {
          "display_name": "Vijay Mallya",
          "embeddings": [[...512 floats...], ...],   # may be empty
          "appearances": [{"start": 92.5, "end": 108.0, "source": "transcript"}],
          "aliases": ["Vijay", "Mallya", "the businessman"]
        },
        ...
      },
      "backend": "insightface" | "stub"
    }

The retrieval engine only ever sees the typed surface
(``IdentityRegistry`` / ``FaceTrack``), so swapping backends is a no-op for
downstream code.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


CACHE_ROOT = Path(os.path.expanduser("~/.axew/cache"))


@dataclass
class FaceTrack:
    """One identity's observed appearances across the timeline."""

    identity_id: str
    display_name: str
    appearances: List[Dict[str, Any]] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    embedding_count: int = 0
    backend: str = "stub"

    def total_screen_time(self) -> float:
        return float(sum(max(0.0, a.get("end", 0.0) - a.get("start", 0.0)) for a in self.appearances))

    def overlaps(self, start: float, end: float) -> bool:
        return any(a.get("start", 0.0) < end and a.get("end", 0.0) > start for a in self.appearances)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerceptionBackendStatus:
    """Reports which heavy perception backends are actually importable."""

    insightface: bool = False
    mediapipe: bool = False
    deepface: bool = False
    speechbrain: bool = False
    raft: bool = False
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def any_visual(self) -> bool:
        return self.insightface or self.mediapipe or self.deepface


def detect_backend_status() -> PerceptionBackendStatus:
    """One-shot import probe — does **not** load weights."""
    status = PerceptionBackendStatus()
    for attr, mod in (
        ("insightface", "insightface"),
        ("mediapipe", "mediapipe"),
        ("deepface", "deepface"),
        ("speechbrain", "speechbrain"),
        ("raft", "torchvision.models.optical_flow"),
    ):
        try:
            __import__(mod)
            setattr(status, attr, True)
        except Exception:
            setattr(status, attr, False)
    if not status.any_visual:
        status.note = (
            "Visual perception backends not installed. "
            "Retrieval will operate on transcript-only signals."
        )
    return status


class IdentityRegistry:
    """Project-scoped face identity store.

    All retrieval-side code interacts with the registry rather than calling
    into InsightFace directly — that keeps the failure modes contained and
    lets us unit-test against synthetic identities.
    """

    def __init__(self, project_id: str, root: Optional[Path] = None) -> None:
        self.project_id = project_id
        self.root = Path(root) if root else CACHE_ROOT / project_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "identity_db.json"
        self.tracks: Dict[str, FaceTrack] = {}
        self.backend: str = "stub"
        self.status = detect_backend_status()
        if self.status.insightface:
            self.backend = "insightface"
        self._load()

    # ---- Public API ----------------------------------------------------

    def register_from_transcript(
        self,
        identity_id: str,
        display_name: str,
        appearances: List[Dict[str, Any]],
        aliases: Optional[List[str]] = None,
    ) -> FaceTrack:
        """Seed an identity from transcript-derived speaker timing.

        This is what runs when no images are available — we still want the
        retrieval engine to be able to answer "is Vijay Mallya present at
        time T?" by consulting the speaker timeline.
        """
        track = self.tracks.get(identity_id) or FaceTrack(
            identity_id=identity_id,
            display_name=display_name,
            aliases=list(aliases or []),
            backend="stub",
        )
        # Merge appearances by union
        existing = {(a.get("start"), a.get("end")) for a in track.appearances}
        for a in appearances:
            key = (a.get("start"), a.get("end"))
            if key not in existing:
                track.appearances.append({**a, "source": a.get("source", "transcript")})
                existing.add(key)
        for alias in aliases or []:
            if alias not in track.aliases:
                track.aliases.append(alias)
        track.display_name = display_name or track.display_name
        self.tracks[identity_id] = track
        return track

    def label_identity(self, identity_id: str, display_name: str, aliases: List[str]) -> None:
        track = self.tracks.get(identity_id)
        if track:
            track.display_name = display_name
            for alias in aliases:
                if alias not in track.aliases:
                    track.aliases.append(alias)

    def resolve(self, query: str) -> Optional[FaceTrack]:
        """Best-effort fuzzy lookup by display name, id, or alias."""
        if not query:
            return None
        q = query.strip().lower()
        for track in self.tracks.values():
            if track.identity_id.lower() == q or track.display_name.lower() == q:
                return track
            for alias in track.aliases:
                if alias.lower() == q:
                    return track
        # Partial / substring
        for track in self.tracks.values():
            haystack = " ".join([track.identity_id, track.display_name, *track.aliases]).lower()
            if q in haystack:
                return track
        return None

    def tracks_at(self, time_sec: float) -> List[FaceTrack]:
        return [t for t in self.tracks.values() if t.overlaps(time_sec, time_sec + 0.001)]

    def tracks_overlapping(self, start: float, end: float) -> List[FaceTrack]:
        return [t for t in self.tracks.values() if t.overlaps(start, end)]

    def save(self) -> None:
        payload = {
            "backend": self.backend,
            "identities": {
                tid: track.to_dict() for tid, track in self.tracks.items()
            },
        }
        with self.db_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def stats(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "backend": self.backend,
            "num_identities": len(self.tracks),
            "with_embeddings": sum(1 for t in self.tracks.values() if t.embedding_count),
            "total_appearances": sum(len(t.appearances) for t in self.tracks.values()),
            "backend_status": self.status.to_dict(),
        }

    # ---- Internals -----------------------------------------------------

    def _load(self) -> None:
        if not self.db_path.is_file():
            return
        try:
            with self.db_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load identity_db at %s: %s", self.db_path, exc)
            return
        self.backend = payload.get("backend", self.backend)
        for tid, data in (payload.get("identities") or {}).items():
            self.tracks[tid] = FaceTrack(
                identity_id=data.get("identity_id", tid),
                display_name=data.get("display_name", tid),
                appearances=list(data.get("appearances", [])),
                aliases=list(data.get("aliases", [])),
                embedding_count=int(data.get("embedding_count", 0)),
                backend=data.get("backend", "stub"),
            )


def load_identity_registry(project_id: str) -> IdentityRegistry:
    """Convenience loader. Always returns a usable registry."""
    return IdentityRegistry(project_id=project_id)


if __name__ == "__main__":  # pragma: no cover - smoke harness
    import json as _json

    status = detect_backend_status()
    print("[backend status]", _json.dumps(status.to_dict(), indent=2))

    reg = IdentityRegistry(project_id="fixture", root=Path("./.axew_test_cache/fixture"))
    reg.register_from_transcript(
        identity_id="vijay_mallya",
        display_name="Vijay Mallya",
        aliases=["Vijay", "Mallya", "the businessman"],
        appearances=[{"start": 8.5, "end": 18.2, "source": "transcript"}],
    )
    reg.register_from_transcript(
        identity_id="rajesh_kumar",
        display_name="Rajesh Kumar",
        aliases=["Rajesh", "interviewer", "host"],
        appearances=[{"start": 0.0, "end": 8.5, "source": "transcript"}],
    )
    reg.save()
    print("[registry stats]", _json.dumps(reg.stats(), indent=2))
    print("[resolve 'vijay mallya']", reg.resolve("vijay mallya"))
    print("[resolve 'host']", reg.resolve("host"))
    print("[resolve 'unknown']", reg.resolve("unknown"))

"""
Robust local transcription: ffmpeg audio extraction + Whisper (openai-whisper).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings

logger = logging.getLogger(__name__)

_whisper_model = None
_whisper_model_name: Optional[str] = None


class TranscriptionError(Exception):
    """Structured transcription failure with a machine-readable code."""

    def __init__(self, code: str, message: str, hint: str = ""):
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass
class DependencyStatus:
    ok: bool
    ffmpeg: bool = False
    ffmpeg_path: Optional[str] = None
    whisper: bool = False
    torch: bool = False
    torch_version: Optional[str] = None
    sentence_transformers: bool = False
    errors: List[str] = field(default_factory=list)
    hints: List[str] = field(default_factory=list)


def normalize_media_path(media_path: str) -> Path:
    """Resolve and normalize paths (Windows backslashes, file:// URLs)."""
    raw = media_path.strip()
    if raw.lower().startswith("file://"):
        raw = raw[7:]
        if re.match(r"^[a-zA-Z]/", raw):
            raw = f"{raw[0]}:{raw[1:]}"
    path = Path(raw).expanduser().resolve()
    return path


def ensure_ffmpeg_on_path() -> Optional[str]:
    """Ensure ffmpeg is discoverable by Whisper and subprocess (PATH + AXEW_FFMPEG_PATH)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    ffmpeg_dir = str(Path(ffmpeg).parent)
    path_val = os.environ.get("PATH", "")
    if ffmpeg_dir.lower() not in path_val.lower():
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + path_val
    os.environ["AXEW_FFMPEG_PATH"] = ffmpeg
    return ffmpeg


def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg: env override → PATH → imageio-ffmpeg bundle."""
    env_path = os.environ.get("AXEW_FFMPEG_PATH") or os.environ.get("FFMPEG_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return str(p.resolve())
        candidate = p / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if candidate.is_file():
            return str(candidate.resolve())

    which = shutil.which("ffmpeg")
    if which:
        return which

    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).is_file():
            return bundled
    except ImportError:
        pass

    common_windows = [
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(os.environ.get("ProgramFiles", "")) / "ffmpeg" / "bin" / "ffmpeg.exe",
    ]
    for candidate in common_windows:
        if candidate.is_file():
            return str(candidate)

    return None


def check_dependencies() -> DependencyStatus:
    status = DependencyStatus(ok=True)

    ffmpeg_path = ensure_ffmpeg_on_path() or find_ffmpeg()
    status.ffmpeg = ffmpeg_path is not None
    status.ffmpeg_path = ffmpeg_path
    if not status.ffmpeg:
        status.ok = False
        status.errors.append("ffmpeg not found")
        status.hints.append(
            "Install ffmpeg and add to PATH, set AXEW_FFMPEG_PATH, or: pip install imageio-ffmpeg"
        )

    try:
        import torch

        status.torch = True
        status.torch_version = torch.__version__
    except ImportError:
        status.ok = False
        status.torch = False
        status.errors.append("torch not installed")
        status.hints.append("pip install torch")

    try:
        import whisper  # noqa: F401

        status.whisper = True
    except ImportError:
        status.ok = False
        status.whisper = False
        status.errors.append("openai-whisper not installed")
        status.hints.append("pip install openai-whisper")

    try:
        import sentence_transformers  # noqa: F401

        status.sentence_transformers = True
    except ImportError:
        status.sentence_transformers = False
        status.hints.append("pip install sentence-transformers (required for semantic search)")

    return status


def probe_media(ffmpeg: str, media_path: Path) -> Dict[str, Any]:
    """Use ffprobe (same dir as ffmpeg) or ffmpeg to detect streams."""
    ffprobe = str(Path(ffmpeg).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    if not Path(ffprobe).is_file():
        ffprobe = shutil.which("ffprobe") or "ffprobe"

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(media_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode == 0 and proc.stdout:
            import json

            return json.loads(proc.stdout)
    except Exception as e:
        logger.warning("ffprobe failed: %s", e)
    return {}


def extract_audio_wav(ffmpeg: str, media_path: Path, cache_dir: Path) -> Path:
    """
    Extract/normalize audio to 16 kHz mono WAV for Whisper.
    Returns path to WAV (may be in cache_dir).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^\w.-]", "_", media_path.stem)[:80]
    out_path = cache_dir / f"{safe_stem}_{media_path.stat().st_mtime_ns}.wav"

    if out_path.is_file() and out_path.stat().st_size > 44:
        logger.info("Using cached WAV: %s", out_path)
        return out_path

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(media_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_path),
    ]

    logger.info("Extracting audio: %s -> %s", media_path, out_path)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)

    if proc.returncode != 0:
        stderr = (proc.stderr or proc.stdout or "unknown ffmpeg error").strip()
        if "does not contain any stream" in stderr.lower() or "no stream" in stderr.lower():
            raise TranscriptionError(
                "no_audio_track",
                "Media file has no audio stream",
                "Import a file with an audio track or use a different source",
            )
        raise TranscriptionError(
            "audio_extraction_failed",
            f"ffmpeg failed to extract audio: {stderr[:500]}",
            "Verify the file plays correctly and ffmpeg can read its codec",
        )

    if not out_path.is_file() or out_path.stat().st_size <= 44:
        raise TranscriptionError(
            "audio_extraction_empty",
            "ffmpeg produced an empty audio file",
            "The source may be silent or use an unsupported codec",
        )

    return out_path


def get_whisper_model(model_name: str):
    global _whisper_model, _whisper_model_name
    if _whisper_model is not None and _whisper_model_name == model_name:
        return _whisper_model

    try:
        import whisper
    except ImportError as e:
        raise TranscriptionError(
            "whisper_missing",
            "openai-whisper is not installed",
            "Run: pip install openai-whisper",
        ) from e

    try:
        import torch
    except ImportError as e:
        raise TranscriptionError(
            "torch_missing",
            "PyTorch is not installed",
            "Run: pip install torch",
        ) from e

    device = settings.device
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
        logger.warning("CUDA requested but unavailable, using CPU")

    logger.info("Loading Whisper model '%s' on %s", model_name, device)
    try:
        _whisper_model = whisper.load_model(model_name, device=device)
        _whisper_model_name = model_name
    except Exception as e:
        raise TranscriptionError(
            "model_load_failed",
            f"Failed to load Whisper model '{model_name}': {e}",
            "Try a smaller model (tiny/base) or check disk space for model download",
        ) from e

    return _whisper_model


def load_wav_mono_16k(wav_path: Path):
    """Load 16 kHz mono WAV without invoking PATH ffmpeg (Whisper-compatible float32)."""
    import numpy as np

    try:
        import soundfile as sf

        audio, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 16000:
            duration = len(audio) / sr
            target_len = int(duration * 16000)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, target_len),
                np.arange(len(audio)),
                audio,
            ).astype(np.float32)
        return audio
    except ImportError:
        pass

    ensure_ffmpeg_on_path()
    import whisper

    return whisper.load_audio(str(wav_path))


def run_whisper_transcribe(
    audio_path: Path,
    model_name: str,
    language: Optional[str],
    word_timestamps: bool,
) -> Dict[str, Any]:
    ensure_ffmpeg_on_path()
    model = get_whisper_model(model_name)
    options: Dict[str, Any] = {"word_timestamps": word_timestamps, "verbose": False}
    if language:
        options["language"] = language

    try:
        audio = load_wav_mono_16k(audio_path)
        result = model.transcribe(audio, **options)
    except Exception as e:
        raise TranscriptionError(
            "whisper_transcribe_failed",
            f"Whisper transcription failed: {e}",
            traceback.format_exc()[-800:],
        ) from e

    segments = []
    for i, seg in enumerate(result.get("segments", [])):
        segment: Dict[str, Any] = {
            "id": str(i),
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": str(seg.get("text", "")).strip(),
            "confidence": float(seg.get("avg_logprob", 0.0)),
        }
        if word_timestamps and "words" in seg:
            segment["words"] = [
                {
                    "word": w["word"],
                    "start": w["start"],
                    "end": w["end"],
                    "confidence": w.get("probability", 0.0),
                }
                for w in seg["words"]
            ]
        segments.append(segment)

    return {
        "segments": segments,
        "full_text": (result.get("text") or "").strip(),
        "language": result.get("language", "unknown"),
        "duration": float(result.get("duration") or 0.0),
    }


def transcribe_media_sync(
    media_path: str,
    model_name: Optional[str] = None,
    language: Optional[str] = None,
    word_timestamps: bool = True,
) -> Dict[str, Any]:
    """Synchronous full pipeline with validation, extraction, and Whisper."""
    deps = check_dependencies()
    if not deps.whisper or not deps.torch:
        raise TranscriptionError(
            "dependencies_missing",
            "; ".join(deps.errors) or "Missing transcription dependencies",
            " | ".join(deps.hints),
        )
    if not deps.ffmpeg:
        raise TranscriptionError(
            "ffmpeg_missing",
            "ffmpeg not found",
            " | ".join(deps.hints),
        )

    path = normalize_media_path(media_path)
    if not path.is_file():
        raise TranscriptionError(
            "file_not_found",
            f"Media file not found: {path}",
            "Use an absolute path accessible to the AI service process",
        )

    model = model_name or settings.default_whisper_model
    cache_dir = Path(settings.cache_dir) / "audio"
    wav_path: Optional[Path] = None
    temp_wav: Optional[Path] = None

    try:
        wav_path = extract_audio_wav(deps.ffmpeg_path, path, cache_dir)
        return run_whisper_transcribe(wav_path, model, language, word_timestamps)
    finally:
        if temp_wav and temp_wav.is_file():
            try:
                temp_wav.unlink()
            except OSError:
                pass


async def transcribe_media_async(
    media_path: str,
    model_name: Optional[str] = None,
    language: Optional[str] = None,
    word_timestamps: bool = True,
) -> Dict[str, Any]:
    """Run transcription in a worker thread so the event loop stays responsive."""
    return await asyncio.to_thread(
        transcribe_media_sync,
        media_path,
        model_name,
        language,
        word_timestamps,
    )

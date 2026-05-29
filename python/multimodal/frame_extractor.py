"""
Frame extraction via ffmpeg.

Stores frames at ~/.axew/frames/{video_id}/{timestamp_ms}.jpg
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

FRAMES_DIR = Path(os.path.expanduser("~/.axew/frames"))


@dataclass
class FrameRecord:
    timestamp_sec: float
    frame_path: str
    is_key_frame: bool = False


class FrameIndex:
    def __init__(self, video_id: str) -> None:
        self.video_id = video_id
        self.frames: List[FrameRecord] = []

    def add(self, record: FrameRecord) -> None:
        self.frames.append(record)

    def sorted(self) -> List[FrameRecord]:
        return sorted(self.frames, key=lambda f: f.timestamp_sec)


def _find_ffmpeg() -> Optional[str]:
    import shutil

    env = os.environ.get("AXEW_FFMPEG_PATH") or os.environ.get("FFMPEG_PATH")
    if env and Path(env).is_file():
        return env
    return shutil.which("ffmpeg")


def extract_frames(
    media_path: str,
    video_id: str,
    fps: float = 1.0,
    jpeg_quality: int = 5,
) -> FrameIndex:
    """
    Extract frames at `fps` for full video.
    jpeg_quality: 2-31 lower = better quality (ffmpeg -q:v).
    """
    index = FrameIndex(video_id)
    out_dir = FRAMES_DIR / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        logger.warning("ffmpeg not found; skipping frame extraction")
        return index

    pattern = str(out_dir / "%06d.jpg")
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        media_path,
        "-vf",
        f"fps={fps}",
        "-q:v",
        str(jpeg_quality),
        pattern,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=3600)
    except Exception as e:
        logger.warning("Frame extraction failed: %s", e)
        return index

    for i, path in enumerate(sorted(out_dir.glob("*.jpg"))):
        ts = i / fps
        index.add(FrameRecord(timestamp_sec=ts, frame_path=str(path), is_key_frame=False))

    return index


def extract_key_frames(
    media_path: str,
    video_id: str,
    speaker_change_times: List[float],
    energy_spike_times: List[float],
    duration_sec: float,
) -> List[FrameRecord]:
    """Extract additional key frames at speaker changes, energy spikes, hook/end regions."""
    key_records: List[FrameRecord] = []
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return key_records

    out_dir = FRAMES_DIR / video_id / "key"
    out_dir.mkdir(parents=True, exist_ok=True)

    times = set(speaker_change_times)
    times.update(energy_spike_times)
    # First and last minute hooks
    for t in list(range(0, 61, 5)) + list(range(max(0, int(duration_sec) - 60), int(duration_sec) + 1, 5)):
        if 0 <= t <= duration_sec:
            times.add(float(t))

    for t in sorted(times):
        out_path = out_dir / f"key_{int(t * 1000)}.jpg"
        if out_path.is_file():
            key_records.append(FrameRecord(timestamp_sec=t, frame_path=str(out_path), is_key_frame=True))
            continue
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(t),
            "-i",
            media_path,
            "-frames:v",
            "1",
            "-q:v",
            "5",
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            if out_path.is_file():
                key_records.append(FrameRecord(timestamp_sec=t, frame_path=str(out_path), is_key_frame=True))
        except Exception:
            pass

    return key_records

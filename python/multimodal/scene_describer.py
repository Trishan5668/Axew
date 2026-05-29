"""
Scene description generation for key frames via Ollama multimodal models.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import httpx

from python.multimodal.frame_extractor import FrameRecord

logger = logging.getLogger(__name__)

OLLAMA_TIMEOUT_SEC = 30.0
SCENE_PROMPT = (
    "Describe what is happening in this video frame. Be specific about: "
    "people present, their actions, any objects being held or exchanged, "
    "facial expressions, and any text visible on screen. Be concise (2-3 sentences)."
)


@dataclass
class SceneDescription:
    timestamp_sec: float
    frame_path: str
    description: str


async def describe_frame_ollama(
    frame_path: str,
    ollama_host: str = "http://localhost:11434",
    model: str = "llava-phi3",
) -> Optional[str]:
    path = Path(frame_path)
    if not path.is_file():
        return None

    try:
        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return None

    payload = {
        "model": model,
        "prompt": SCENE_PROMPT,
        "images": [image_b64],
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SEC) as client:
            resp = await client.post(f"{ollama_host}/api/generate", json=payload)
            if resp.status_code == 200:
                return (resp.json().get("response") or "").strip()
    except Exception as e:
        logger.warning("Ollama scene description failed: %s", e)
    return None


async def describe_key_frames(
    key_frames: List[FrameRecord],
    ollama_host: str = "http://localhost:11434",
    model: str = "llava-phi3",
    max_frames: int = 20,
) -> List[SceneDescription]:
    results: List[SceneDescription] = []
    for rec in key_frames[:max_frames]:
        if not rec.is_key_frame:
            continue
        desc = await describe_frame_ollama(rec.frame_path, ollama_host, model)
        if desc:
            results.append(
                SceneDescription(
                    timestamp_sec=rec.timestamp_sec,
                    frame_path=rec.frame_path,
                    description=desc,
                )
            )
    return results

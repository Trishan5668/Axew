import asyncio
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_embed_model = None


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Loaded embedding model all-MiniLM-L6-v2")
    return _embed_model


def cosine_similarity(a, b) -> float:
    import numpy as np

    return float(np.dot(a, b))


class SilenceDetectionRequest(BaseModel):
    media_path: str
    threshold_db: float = -40.0
    min_silence_duration: float = 0.5
    min_content_duration: float = 0.3


class SilenceRegion(BaseModel):
    start: float
    end: float
    duration: float
    average_db: float


class TranscribeRequest(BaseModel):
    media_path: str
    model: str = "base"
    language: Optional[str] = None
    word_timestamps: bool = True


class SceneDetectionRequest(BaseModel):
    media_path: str
    threshold: float = 0.4


async def detect_silence_ffmpeg(
    media_path: str, threshold_db: float, min_duration: float
) -> List[SilenceRegion]:
    from transcription import find_ffmpeg

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ffmpeg_missing",
                "message": "ffmpeg not found",
                "hint": "pip install imageio-ffmpeg or install ffmpeg and add to PATH",
            },
        )

    cmd = [
        ffmpeg,
        "-i",
        media_path,
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f",
        "null",
        "-",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    stderr_text = stderr.decode("utf-8", errors="replace")

    silences = []
    current_start = None

    for line in stderr_text.split("\n"):
        if "silence_start:" in line:
            try:
                current_start = float(line.split("silence_start:")[-1].strip())
            except ValueError:
                pass
        elif "silence_end:" in line and current_start is not None:
            try:
                parts = line.split("|")
                end = float(parts[0].split("silence_end:")[-1].strip())
                duration = end - current_start
                silences.append(
                    SilenceRegion(
                        start=current_start,
                        end=end,
                        duration=duration,
                        average_db=threshold_db,
                    )
                )
                current_start = None
            except (ValueError, IndexError):
                pass

    return silences


@router.post("/silence")
async def detect_silence(request: SilenceDetectionRequest):
    if not os.path.exists(request.media_path):
        raise HTTPException(status_code=404, detail=f"File not found: {request.media_path}")

    try:
        silences = await detect_silence_ffmpeg(
            request.media_path,
            request.threshold_db,
            request.min_silence_duration,
        )
        return {
            "silences": [s.model_dump() for s in silences],
            "count": len(silences),
            "total_silence_duration": sum(s.duration for s in silences),
        }
    except Exception as e:
        logger.error("Silence detection failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/diagnostics")
async def transcription_diagnostics():
    """Report transcription dependency status for setup/debugging."""
    from transcription import check_dependencies, find_ffmpeg

    deps = check_dependencies()
    return {
        "ready": deps.ok,
        "ffmpeg": deps.ffmpeg,
        "ffmpeg_path": deps.ffmpeg_path,
        "whisper": deps.whisper,
        "torch": deps.torch,
        "torch_version": deps.torch_version,
        "sentence_transformers": deps.sentence_transformers,
        "errors": deps.errors,
        "hints": deps.hints,
        "cache_dir": settings.cache_dir,
        "default_whisper_model": settings.default_whisper_model,
        "ffmpeg_discovered": find_ffmpeg(),
    }


@router.post("/transcribe")
async def transcribe_media(request: TranscribeRequest):
    from transcription import TranscriptionError, normalize_media_path, transcribe_media_async

    try:
        path = normalize_media_path(request.media_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid media path: {e}") from e

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "file_not_found",
                "message": f"File not found: {path}",
                "hint": "Ensure the path is absolute and readable by the AI service",
                "path": str(path),
            },
        )

    try:
        result = await transcribe_media_async(
            str(path),
            model_name=request.model,
            language=request.language,
            word_timestamps=request.word_timestamps,
        )
        return result
    except TranscriptionError as e:
        logger.error("Transcription failed [%s]: %s", e.code, e.message)
        status = 503 if e.code in ("dependencies_missing", "whisper_missing", "torch_missing", "ffmpeg_missing") else 500
        raise HTTPException(status_code=status, detail=e.to_dict()) from e
    except Exception as e:
        logger.exception("Transcription failed unexpectedly")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "transcription_error",
                "message": str(e),
                "hint": "Check AI service logs for the full traceback",
            },
        ) from e


@router.post("/scenes")
async def detect_scenes(request: SceneDetectionRequest):
    if not os.path.exists(request.media_path):
        raise HTTPException(status_code=404, detail=f"File not found: {request.media_path}")

    from transcription import find_ffmpeg

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="ffmpeg not found")

    try:
        cmd = [
            ffmpeg,
            "-i",
            request.media_path,
            "-vf",
            f"select='gt(scene,{request.threshold})',showinfo",
            "-vsync",
            "vfr",
            "-f",
            "null",
            "-",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        stderr_text = stderr.decode("utf-8", errors="replace")

        boundaries = []
        for line in stderr_text.split("\n"):
            if "pts_time:" in line and "Parsed_showinfo" in line:
                try:
                    pts_part = [p for p in line.split() if "pts_time:" in p][0]
                    time = float(pts_part.split("pts_time:")[-1])
                    boundaries.append(
                        {"time": time, "score": request.threshold, "type": "cut"}
                    )
                except (ValueError, IndexError):
                    pass

        return {"scenes": boundaries, "count": len(boundaries)}
    except Exception as e:
        logger.error("Scene detection failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/embed")
async def embed_text(payload: dict):
    text = payload.get("text", "")
    try:
        model = get_embed_model()
        embedding = model.encode(text, normalize_embeddings=True).tolist()
        return {"embedding": embedding, "dimensions": len(embedding)}
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail="sentence-transformers not installed",
        ) from e


class IndexVideoRequest(BaseModel):
    video_id: str
    segments: List[dict]
    media_path: Optional[str] = None


@router.post("/index-video")
async def index_video(request: IndexVideoRequest):
    """Enqueue background intelligence indexing (Phase 9)."""
    try:
        import sys
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[3]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from python.processing.queue import get_processing_queue

        job = await get_processing_queue().enqueue(
            request.video_id,
            request.segments,
            media_path=request.media_path,
        )
        return {"video_id": job.video_id, "status": job.status.value}
    except Exception as e:
        logger.error("Index enqueue failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/index-status/{video_id}")
async def index_status(video_id: str):
    try:
        import sys
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[3]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from python.processing.queue import get_processing_queue

        job = get_processing_queue().get_status(video_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"video_id": video_id, "status": job.status.value, "error": job.error}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

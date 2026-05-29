import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/ollama")
async def list_ollama_models():
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{settings.ollama_host}/api/tags")
            if response.status_code != 200:
                raise HTTPException(status_code=502, detail="Ollama request failed")
            data = response.json()
            return {"models": data.get("models", []), "status": "connected"}
        except httpx.ConnectError:
            return {
                "models": [],
                "status": "disconnected",
                "error": "Cannot connect to Ollama",
            }


class PullModelRequest(BaseModel):
    model: str


@router.post("/ollama/pull")
async def pull_ollama_model(request: PullModelRequest):
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            await client.post(
                f"{settings.ollama_host}/api/pull",
                json={"name": request.model},
            )
            return {"status": "started", "model": request.model}
        except httpx.ConnectError as e:
            raise HTTPException(status_code=503, detail="Cannot connect to Ollama") from e


@router.get("/status")
async def models_status():
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_host}/api/tags")
            ollama_ok = resp.status_code == 200
    except Exception:
        pass

    return {
        "ollama": {"connected": ollama_ok, "host": settings.ollama_host},
        "default_llm": settings.default_llm_model,
        "default_whisper": settings.default_whisper_model,
        "device": settings.device,
    }

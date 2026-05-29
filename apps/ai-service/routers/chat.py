import json
import logging
from typing import AsyncGenerator, Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    system: Optional[str] = None
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 1024


async def stream_ollama(request: ChatRequest) -> AsyncGenerator[bytes, None]:
    model = request.model or settings.default_llm_model
    messages = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.append({"role": "user", "content": request.message})

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": request.temperature,
            "num_predict": request.max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream(
                "POST",
                f"{settings.ollama_host}/api/chat",
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    yield f"data: {json.dumps({'error': error_text.decode()})}\n\n".encode()
                    return

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if content := data.get("message", {}).get("content"):
                            yield f"data: {json.dumps({'content': content})}\n\n".encode()
                        if data.get("done"):
                            yield f"data: {json.dumps({'done': True})}\n\n".encode()
                            break
                    except json.JSONDecodeError:
                        continue
        except httpx.ConnectError:
            yield (
                f"data: {json.dumps({'error': 'Cannot connect to Ollama. Run: ollama serve'})}\n\n"
            ).encode()
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    return StreamingResponse(
        stream_ollama(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/")
async def chat(request: ChatRequest):
    model = request.model or settings.default_llm_model
    messages = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    messages.append({"role": "user", "content": request.message})

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{settings.ollama_host}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
            )
            if response.status_code != 200:
                return {"content": "", "error": "Ollama request failed"}
            data = response.json()
            return {"content": data.get("message", {}).get("content", "")}
        except httpx.ConnectError:
            return {"content": "", "error": "Ollama not available"}

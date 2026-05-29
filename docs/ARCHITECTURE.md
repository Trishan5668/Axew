# AXEW Architecture

## Overview

AXEW is a monorepo-structured AI-native NLE built on three runtime layers:

### Layer 1: Frontend (Electron + React)

- `apps/desktop/` — Electron shell + React UI
- State: Zustand stores (project, timeline, playback, UI, AI, export)
- Styling: TailwindCSS with cinematic dark theme
- IPC: Electron contextBridge (secure, no nodeIntegration)

### Layer 2: Backend (Rust)

- `crates/axew-core/` — Axum HTTP server on port 7001
- Media probing via ffprobe
- Thumbnail generation via ffmpeg
- Export pipeline via ffmpeg
- SQLite caching via tokio-rusqlite

### Layer 3: AI Service (Python)

- `apps/ai-service/` — FastAPI on port 7002
- Streaming chat via Ollama
- Silence detection via FFmpeg silencedetect filter
- Transcription via OpenAI Whisper (optional install)
- Scene detection via FFmpeg scene filter
- Embeddings via sentence-transformers (optional install)

## Data Flow

```
User Action → Zustand Store → React Component
                    ↓
         Rust API (7001) / AI Service (7002) / Ollama (11434)
```

## Timeline Data Model

Non-destructive editing: clips reference source media by time range.

`Timeline → Tracks → Clips → (mediaId, startTime, duration, inPoint, outPoint)`

## AI Integration Points

1. Chat: Ollama streaming via AI service proxy
2. Silence Detection: FFmpeg-based, applied via edit orchestrator
3. Transcription: Whisper segments mapped to subtitle tracks
4. Scene Detection: FFmpeg scene filter creates markers
5. Semantic search: Embedding endpoint (sentence-transformers)

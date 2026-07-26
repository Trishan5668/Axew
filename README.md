# AXEW

AI-native non-linear video editor — local-first cinematic editing platform.

## Stack

- **Monorepo:** pnpm workspaces + Turborepo
- **Desktop:** Electron 30 + React 18 + TypeScript + Vite + Tailwind CSS
- **Engine:** Rust (`axew-core`) — media probe, thumbnails, FFmpeg export
- **AI:** Python FastAPI + Ollama — chat, silence detection, transcription, scenes

## Prerequisites

- Node.js 20+
- pnpm 9+
- Rust toolchain (for `axew-core`)
- Python 3.10+ (for AI service)
- FFmpeg / ffprobe on PATH
- [Ollama](https://ollama.com) (optional, for local LLM)

## Quick start

```bash
pnpm install
cd crates/axew-core && cargo build
cd ../../apps/ai-service && pip install -r requirements.txt
cd ../..
pnpm dev
```

Copy `.env.example` to `.env` and adjust paths as needed.

## Workspace layout

```
axew/
├── apps/
│   ├── desktop/       # Electron + React frontend
│   └── ai-service/    # Python FastAPI AI runtime
├── crates/
│   └── axew-core/     # Rust backend engine
├── packages/
│   └── shared-types/  # Shared TypeScript types
├── docs/
└── scripts/
```

## Features (current)

- Real timeline engine (tracks, clips, trim, split, zoom, snap)
- Media import with ffprobe probing and thumbnails
- Preview playback synced to playhead
- FFmpeg export via Rust service
- AI panel with Ollama chat and quick-edit prompts
- Silence detection, scene markers, subtitle/transcript pipeline
- **Local-first by default** — no cloud dependency. Optional cloud features
  (Supabase auth, Razorpay billing, OpusClip post-processing) are opt-in
  behind a single feature flag. See [docs/CLOUD_INTEGRATION.md](docs/CLOUD_INTEGRATION.md).

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system design.

## Packaging (Windows)

```bash
pnpm install
pnpm make-installer
```

Produces `apps/desktop/release/AxewSetup-<version>.exe`. End users do not
need Node / Python / Rust / FFmpeg installed. Whisper models download on
first launch into `%APPDATA%/Axew/models/`. Full details in
[docs/CLOUD_INTEGRATION.md](docs/CLOUD_INTEGRATION.md).

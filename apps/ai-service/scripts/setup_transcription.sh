#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Installing AI service dependencies..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo ""
echo "Verifying installation..."
python3 -c "
from transcription import check_dependencies
d = check_dependencies()
print('ffmpeg:', d.ffmpeg, d.ffmpeg_path)
print('whisper:', d.whisper)
print('torch:', d.torch, d.torch_version)
print('ready:', d.ok)
if d.errors:
    print('errors:', d.errors)
if d.hints:
    print('hints:', d.hints)
"

echo "Done. Restart the AI service (uvicorn on port 7002)."

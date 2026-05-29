# Install AXEW AI transcription dependencies (Windows)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Installing AI service dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host ""
Write-Host "Verifying installation..."
python -c @"
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
"@

if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "Done. Restart the AI service (uvicorn on port 7002)."

#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3.11}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.11 bulunamadi. Dagitiminizdan python3.11 + venv kurun."
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y ffmpeg
  else
    echo "FFmpeg bulunamadi; paket yoneticinizle kurup PATH'e ekleyin."
  fi
fi

"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel uv
if [ -x .venv/bin/uv ]; then
  .venv/bin/uv pip install --python .venv/bin/python torch torchaudio torchcodec --torch-backend=auto
fi
.venv/bin/python -m pip install -e ".[gui]"
.venv/bin/python -m pip install "voxcpm==2.0.3" "coqui-tts==0.27.5" "transformers>=4.57,<5" "soundfile>=0.13,<1" "nvidia-ml-py>=12,<14"
.venv/bin/python -c "import torch, torchaudio, transformers; from TTS.api import TTS; print('XTTS import OK | torch=' + torch.__version__ + ' | transformers=' + transformers.__version__)"
echo "Kurulum tamamlandi. Calistir: .venv/bin/python -m epub2m4b.app"

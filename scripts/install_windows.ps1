$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Venv = Join-Path $Root ".venv"

function Find-Python311 {
    try {
        $cmd = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $cmd) { return $cmd.Trim() }
    } catch {}
    try {
        $cmd = & python -c "import sys; print(sys.executable if sys.version_info[:2] == (3,11) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $cmd) { return $cmd.Trim() }
    } catch {}
    return $null
}

$Python = Find-Python311
if (-not $Python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Python 3.11 bulunamadi; winget ile kuruluyor..."
        winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
        $Python = Find-Python311
    }
}
if (-not $Python) { throw "Python 3.11 bulunamadi. Python 3.11 kurup betigi yeniden calistirin." }

Write-Host "Python: $Python"
if (-not (Test-Path $Venv)) {
    & $Python -m venv $Venv
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel uv

$Uv = Join-Path $Venv "Scripts\uv.exe"
if (Test-Path $Uv) {
    Write-Host "Donanima uygun PyTorch backend seciliyor..."
    & $Uv pip install --python $VenvPython torch torchaudio torchcodec --torch-backend=auto
}

Push-Location $Root
try {
    & $VenvPython -m pip install -e ".[gui]"
    & $VenvPython -m pip install "voxcpm==2.0.3" "coqui-tts==0.27.5" "transformers>=4.57,<5" "soundfile>=0.13,<1" "nvidia-ml-py>=12,<14"
    Write-Host "XTTS calisma zamani import testi..."
    & $VenvPython -c "import torch, torchaudio, transformers; from TTS.api import TTS; print('XTTS import OK | torch=' + torch.__version__ + ' | transformers=' + transformers.__version__)"
    if ($LASTEXITCODE -ne 0) { throw "XTTS runtime import testi basarisiz. Yukaridaki Python hatasini kontrol edin." }
} finally {
    Pop-Location
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "FFmpeg bulunamadi; winget ile kuruluyor..."
        winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        Write-Host "FFmpeg PATH degisikligi icin yeni terminal/oturum gerekebilir."
    } else {
        Write-Warning "FFmpeg bulunamadi ve winget yok. FFmpeg'i manuel kurup PATH'e ekleyin."
    }
}

Write-Host "Kurulum tamamlandi. Model agirliklari ilk kullanimda indirilecektir."

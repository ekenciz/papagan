from __future__ import annotations

import importlib.util
from importlib import metadata
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEEPSPEED_VERSION = "0.19.6"
DEEPSPEED_REQUIREMENT = f"deepspeed=={DEEPSPEED_VERSION}"


@dataclass(frozen=True, slots=True)
class EngineDependency:
    modules: tuple[str, ...]
    packages: tuple[str, ...]


ENGINE_DEPENDENCIES: dict[str, EngineDependency] = {
    "trendyol": EngineDependency(("voxcpm", "soundfile", "torch"), ("voxcpm==2.0.3", "soundfile>=0.13,<1")),
    "xtts": EngineDependency(
        ("TTS", "soundfile", "torch", "torchaudio", "transformers"),
        (
            "torch>=2.5",
            "torchaudio>=2.5",
            "coqui-tts==0.27.5",
            "transformers>=4.57,<5",
            "soundfile>=0.13,<1",
            "nvidia-ml-py>=12,<14",
        ),
    ),
    "mms": EngineDependency(
        ("transformers", "torch", "soundfile"),
        ("transformers>=4.57,<5", "torch>=2.5", "soundfile>=0.13,<1"),
    ),
}


def missing_modules(engine_id: str) -> list[str]:
    importlib.invalidate_caches()
    spec = ENGINE_DEPENDENCIES[engine_id]
    return [module for module in spec.modules if importlib.util.find_spec(module) is None]


def _major(version: str) -> int | None:
    try:
        return int(version.split(".", 1)[0])
    except (TypeError, ValueError):
        return None


def _major_minor(version: str) -> tuple[int, int] | None:
    try:
        pieces = version.split("+", 1)[0].split(".")
        return int(pieces[0]), int(pieces[1])
    except (IndexError, TypeError, ValueError):
        return None


def dependency_issues(engine_id: str) -> list[str]:
    """Return actionable dependency problems without importing heavyweight ML stacks."""

    issues = [f"eksik modül: {module}" for module in missing_modules(engine_id)]
    if engine_id == "xtts":
        try:
            coqui_version = metadata.version("coqui-tts")
        except metadata.PackageNotFoundError:
            issues.append("coqui-tts paketi bulunamadı")
        else:
            if coqui_version != "0.27.5":
                issues.append(f"coqui-tts {coqui_version} yüklü; 0.27.5 öneriliyor")

        try:
            transformers_version = metadata.version("transformers")
        except metadata.PackageNotFoundError:
            transformers_version = ""
        if transformers_version and (_major(transformers_version) or 0) >= 5:
            issues.append(
                f"transformers {transformers_version} XTTS ile uyumsuz olabilir; 4.57.x (<5) kullanılmalı"
            )

        try:
            torch_version = metadata.version("torch")
        except metadata.PackageNotFoundError:
            torch_version = ""
        torch_mm = _major_minor(torch_version) if torch_version else None
        if torch_mm is not None and torch_mm >= (2, 9) and importlib.util.find_spec("torchcodec") is None:
            issues.append(f"PyTorch {torch_version} için torchcodec eksik")
    return issues



def windows_vsdevcmd() -> Path | None:
    """Locate a VS2022 Developer Command Prompt bootstrap script on Windows."""

    if platform.system().lower() != "windows":
        return None
    candidates: list[Path] = []
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / (
        "Microsoft Visual Studio/Installer/vswhere.exe"
    )
    if vswhere.is_file():
        try:
            probe = subprocess.run(
                [
                    str(vswhere),
                    "-latest",
                    "-products",
                    "*",
                    "-requires",
                    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                    "-property",
                    "installationPath",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            install = probe.stdout.strip().splitlines()[-1].strip() if probe.stdout.strip() else ""
            if install:
                candidates.append(Path(install) / "Common7/Tools/VsDevCmd.bat")
        except Exception:
            pass

    roots = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/2022",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Visual Studio/2022",
    ]
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob("*/Common7/Tools/VsDevCmd.bat"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def windows_vctools_available() -> bool:
    if platform.system().lower() != "windows":
        return True
    if shutil.which("cl.exe") or shutil.which("cl"):
        return True
    return windows_vsdevcmd() is not None


def install_windows_vctools(log=print) -> None:
    """Install VS2022 C++ Build Tools through winget when the user opted in."""

    if platform.system().lower() != "windows":
        return
    if windows_vctools_available():
        log("Visual C++ Build Tools zaten hazir.")
        return
    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("winget bulunamadi; Visual Studio 2022 Build Tools elle kurulmalidir.")
    log("Visual Studio 2022 C++ Build Tools winget ile kuruluyor. Bu islem birkac GB indirebilir...")
    _stream_process(
        [
            winget,
            "install",
            "--id",
            "Microsoft.VisualStudio.2022.BuildTools",
            "-e",
            "--source",
            "winget",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--override",
            "--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended",
        ],
        log,
    )
    if not windows_vctools_available():
        raise RuntimeError("Visual C++ Build Tools kuruldu ancak VsDevCmd.bat bulunamadi; Windows yeniden baslatma gerekebilir.")


def _stream_cmd_script(command: str, log) -> None:
    proc = subprocess.Popen(
        ["cmd.exe", "/d", "/s", "/c", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"Windows build komutu basarisiz (cikis kodu {code}).")


def _install_deepspeed_windows(log) -> None:
    """Build the pinned DeepSpeed release using upstream's Windows path.

    DeepSpeed publishes source distributions on PyPI for Windows rather than a
    generic prebuilt wheel.  Upstream documents ``build_win.bat`` as the
    supported Windows installation path, so avoid a noisy plain ``pip install``
    attempt first and build the wheel directly inside a VS2022 developer
    environment.
    """

    vsdevcmd = windows_vsdevcmd()
    if vsdevcmd is None:
        raise RuntimeError(
            "Visual C++ Build Tools bulunamadi. GUI'de otomatik Build Tools kurulumunu onaylayin "
            "veya VS2022 Desktop development with C++ / VCTools kurun."
        )

    with tempfile.TemporaryDirectory(prefix="epub2m4b_deepspeed_") as temp_dir:
        temp = Path(temp_dir)
        log(f"DeepSpeed {DEEPSPEED_VERSION} kaynak paketi indiriliyor...")
        _stream_process(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--no-binary=:all:",
                DEEPSPEED_REQUIREMENT,
                "-d",
                str(temp),
            ],
            log,
        )
        archives = sorted(temp.glob("deepspeed-*.tar.gz")) + sorted(temp.glob("deepspeed-*.zip"))
        if not archives:
            raise RuntimeError("DeepSpeed kaynak arsivi indirilemedi.")
        archive = archives[-1]
        source_parent = temp / "src"
        source_parent.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(str(archive), str(source_parent))
        roots = [path for path in source_parent.iterdir() if path.is_dir()]
        if not roots:
            raise RuntimeError("DeepSpeed kaynak arsivi acilamadi.")
        source = roots[0]
        build_win = source / "build_win.bat"
        if not build_win.is_file():
            raise RuntimeError("DeepSpeed kaynak paketinde build_win.bat bulunamadi.")

        log("DeepSpeed wheel, VS2022 x64 Developer ortaminda upstream build_win.bat ile derleniyor...")
        command = (
            f'call "{vsdevcmd}" -arch=x64 -host_arch=x64 && '
            'set DS_BUILD_AIO=0 && set DS_BUILD_SPARSE_ATTN=0 && '
            f'cd /d "{source}" && call "{build_win}"'
        )
        _stream_cmd_script(command, log)
        wheels = sorted((source / "dist").glob("deepspeed-*.whl"))
        if not wheels:
            raise RuntimeError("DeepSpeed build_win.bat wheel uretmedi.")
        wheel = wheels[-1]
        log(f"Olusturulan DeepSpeed wheel kuruluyor: {wheel.name}")
        _stream_process(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(wheel)],
            log,
        )


def ffmpeg_installed() -> bool:
    return shutil.which("ffmpeg") is not None


def deepspeed_available() -> bool:
    """Return True only when the optional DeepSpeed module can actually import."""

    if importlib.util.find_spec("deepspeed") is None:
        return False
    try:
        probe = subprocess.run(
            [sys.executable, "-c", "import deepspeed; print(deepspeed.__version__)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return probe.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _stream_process(cmd: list[str], log) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"Komut basarisiz (cikis kodu {code}): {' '.join(cmd)}")


def _uv_executable() -> str | None:
    uv = shutil.which("uv")
    if uv:
        return uv
    sibling = Path(sys.executable).with_name("uv.exe" if os.name == "nt" else "uv")
    return str(sibling) if sibling.exists() else None


def _ensure_torch_backend(log) -> None:
    torch_present = importlib.util.find_spec("torch") is not None
    torchaudio_present = importlib.util.find_spec("torchaudio") is not None
    torchcodec_needed = False
    try:
        torch_version = metadata.version("torch")
    except metadata.PackageNotFoundError:
        torch_version = ""
    torch_mm = _major_minor(torch_version) if torch_version else None
    if torch_mm is not None and torch_mm >= (2, 9):
        torchcodec_needed = importlib.util.find_spec("torchcodec") is None

    runtime_ok = False
    if torch_present and torchaudio_present:
        try:
            probe = subprocess.run(
                [sys.executable, "-c", "import torch, torchaudio"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            runtime_ok = probe.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            # A broken CUDA/runtime installation can hang or fail before Python
            # produces a useful ImportError. Treat that as a repair condition.
            runtime_ok = False

    if torch_present and torchaudio_present and runtime_ok and not torchcodec_needed:
        return
    try:
        uv = _uv_executable()
        if not uv:
            log("PyTorch backend secimi icin uv kuruluyor...")
            _stream_process([sys.executable, "-m", "pip", "install", "uv"], log)
            uv = _uv_executable()
        if uv:
            log("Donanima uygun PyTorch/torchaudio backend'i uv ile kuruluyor...")
            cmd = [uv, "pip", "install", "--python", sys.executable]
            if torch_present and torchaudio_present and not runtime_ok:
                log("Mevcut PyTorch import edilemiyor; torch stack yeniden kurulacak...")
                cmd.append("--reinstall")
            cmd.extend(["torch", "torchaudio", "torchcodec", "--torch-backend=auto"])
            _stream_process(cmd, log)
    except Exception as exc:
        log(f"uv ile otomatik PyTorch secimi basarisiz; pip fallback kullanilacak: {exc}")


def install_ffmpeg(log=print) -> None:
    if ffmpeg_installed():
        return
    system = platform.system().lower()
    if system == "windows" and shutil.which("winget"):
        log("FFmpeg winget ile kuruluyor...")
        _stream_process(
            [
                "winget",
                "install",
                "-e",
                "--id",
                "Gyan.FFmpeg",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            log,
        )
        log("FFmpeg kuruldu. PATH yenilenmesi icin uygulamayi yeniden baslatmak gerekebilir.")
        return
    if system == "darwin" and shutil.which("brew"):
        log("FFmpeg Homebrew ile kuruluyor...")
        _stream_process(["brew", "install", "ffmpeg"], log)
        return
    if system == "linux" and shutil.which("apt-get"):
        prefix = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
        if prefix and not shutil.which("sudo"):
            raise RuntimeError("FFmpeg icin root yetkisi gerekiyor; 'sudo apt-get install ffmpeg' komutunu calistirin.")
        log("FFmpeg apt ile kuruluyor...")
        _stream_process([*prefix, "apt-get", "update"], log)
        _stream_process([*prefix, "apt-get", "install", "-y", "ffmpeg"], log)
        return
    raise RuntimeError("FFmpeg otomatik kurulamadı. Sistem paket yoneticinizle FFmpeg kurup PATH'e ekleyin.")


def _runtime_smoke_test(engine_id: str, log=print) -> None:
    snippets = {
        "xtts": (
            "import warnings; "
            "warnings.filterwarnings('ignore', message=r'`torch\\.jit\\.script` is deprecated\\..*', "
            "category=FutureWarning, module=r'torch\\.jit\\._script'); "
            "import torch, torchaudio, transformers; "
            "from TTS.api import TTS; "
            "print('XTTS import OK | torch=' + torch.__version__ + "
            "' | transformers=' + transformers.__version__)"
        ),
        "trendyol": "import torch, soundfile, voxcpm; print('Trendyol import OK | torch=' + torch.__version__)",
        "mms": "import torch, soundfile, transformers; print('MMS import OK | transformers=' + transformers.__version__)",
    }
    snippet = snippets.get(engine_id)
    if not snippet:
        return
    log("Çalışma zamanı import testi yapılıyor...")
    _stream_process([sys.executable, "-c", snippet], log)


def install_xtts_deepspeed(log=print, install_build_tools: bool = False) -> None:
    """Install optional DeepSpeed without silently damaging the working XTTS stack."""

    if deepspeed_available():
        try:
            version = metadata.version("deepspeed")
        except metadata.PackageNotFoundError:
            version = "?"
        log(f"DeepSpeed zaten hazir: {version}")
        return

    log("XTTS icin opsiyonel DeepSpeed kurulumu deneniyor...")
    if platform.system().lower() == "windows":
        if not windows_vctools_available():
            if install_build_tools:
                install_windows_vctools(log)
            else:
                raise RuntimeError(
                    "DeepSpeed Windows build'i icin Visual Studio 2022 C++ Build Tools gerekiyor. "
                    "GUI otomatik kurulum secenegini sunabilir; normal XTTS Optimize modu etkilenmez."
                )
        _install_deepspeed_windows(log)
    else:
        _stream_process([sys.executable, "-m", "pip", "install", DEEPSPEED_REQUIREMENT], log)

    if not deepspeed_available():
        raise RuntimeError(
            "DeepSpeed kurulumu tamamlandi ancak import testi gecmedi. Normal XTTS Optimize modu kullanilabilir."
        )
    _stream_process(
        [sys.executable, "-c", "import deepspeed; print('DeepSpeed OK', deepspeed.__version__)"],
        log,
    )


def install_engine_dependencies(engine_id: str, log=print, install_system: bool = True) -> None:
    dep = ENGINE_DEPENDENCIES[engine_id]
    if "torch" in dep.modules:
        _ensure_torch_backend(log)
    log(f"Paketler kuruluyor: {' '.join(dep.packages)}")
    # Exact/ranged requirements repair incompatible packages (for example
    # transformers 5.x -> 4.57.x) without unnecessarily replacing a working
    # hardware-specific PyTorch build selected by uv.
    _stream_process([sys.executable, "-m", "pip", "install", *dep.packages], log)
    _runtime_smoke_test(engine_id, log)
    if install_system and not ffmpeg_installed():
        install_ffmpeg(log)

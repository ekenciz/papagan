from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import ModuleType


def is_windows_symlink_privilege_error(exc: BaseException) -> bool:
    """Return True when an exception chain contains Windows WinError 1314."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "winerror", None) == 1314 or "WinError 1314" in str(current):
            return True
        current = current.__cause__ or current.__context__
    return False


def _copy_instead_of_symlink(src: str, dst: str, new_blob: bool) -> None:
    """Materialize a Hugging Face cache pointer as a real file."""

    dst_path = Path(dst)
    src_path = Path(src)
    if not src_path.is_absolute():
        src_path = (dst_path.parent / src_path).resolve()

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst_path.unlink()
    except FileNotFoundError:
        pass

    if new_blob:
        shutil.move(str(src_path), str(dst_path))
    else:
        shutil.copy2(str(src_path), str(dst_path))


def install_windows_hf_symlink_fallback(
    file_download_module: ModuleType | object | None = None,
    *,
    force: bool = False,
) -> bool:
    """Patch old huggingface_hub versions to survive WinError 1314.

    New huggingface_hub releases support ``HF_HUB_DISABLE_SYMLINKS=1``. Some
    older releases used by Transformers 4.x/Coqui can still attempt a symlink
    after their capability probe succeeds, and Windows may then reject the
    actual link with WinError 1314. This narrow wrapper keeps the upstream
    behavior and only falls back to copying when that exact privilege error is
    raised.
    """

    if os.name != "nt" and not force:
        return False

    if file_download_module is None:
        try:
            import huggingface_hub.file_download as file_download_module
        except ImportError:
            return False

    original = getattr(file_download_module, "_create_symlink", None)
    if not callable(original):
        return False
    if getattr(original, "__epub2m4b_win1314_fallback__", False):
        return True

    def safe_create_symlink(src: str, dst: str, new_blob: bool = False) -> None:
        try:
            original(src=src, dst=dst, new_blob=new_blob)
        except OSError as exc:
            if not is_windows_symlink_privilege_error(exc):
                raise
            _copy_instead_of_symlink(src, dst, new_blob)

    safe_create_symlink.__epub2m4b_win1314_fallback__ = True  # type: ignore[attr-defined]
    safe_create_symlink.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(file_download_module, "_create_symlink", safe_create_symlink)
    return True

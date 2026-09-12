from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from epub2m4b.hf_compat import install_windows_hf_symlink_fallback, is_windows_symlink_privilege_error


class Win1314(OSError):
    winerror = 1314


def test_detects_winerror_1314_in_exception_chain():
    outer = RuntimeError("wrapped")
    outer.__cause__ = Win1314("A required privilege is not held by the client")
    assert is_windows_symlink_privilege_error(outer)


def test_hf_symlink_fallback_copies_blob(tmp_path: Path):
    src = tmp_path / "blobs" / "abc"
    dst = tmp_path / "snapshots" / "rev" / "config.json"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"payload")

    def failing_symlink(*, src: str, dst: str, new_blob: bool = False):
        raise Win1314("[WinError 1314] A required privilege is not held by the client")

    fake_module = SimpleNamespace(_create_symlink=failing_symlink)
    assert install_windows_hf_symlink_fallback(fake_module, force=True)

    fake_module._create_symlink(str(src), str(dst), False)
    assert dst.read_bytes() == b"payload"
    assert src.read_bytes() == b"payload"


def test_hf_symlink_fallback_does_not_swallow_other_errors(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.write_bytes(b"x")

    def failing_symlink(*, src: str, dst: str, new_blob: bool = False):
        raise OSError("different failure")

    fake_module = SimpleNamespace(_create_symlink=failing_symlink)
    install_windows_hf_symlink_fallback(fake_module, force=True)

    try:
        fake_module._create_symlink(str(src), str(dst), False)
    except OSError as exc:
        assert "different failure" in str(exc)
    else:
        raise AssertionError("non-1314 OSError must propagate")

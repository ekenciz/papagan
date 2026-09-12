"""EPUB to M4B package."""

from __future__ import annotations

import os

# Hugging Face uses symlinks in its default cache. On Windows, creating those
# links may fail with WinError 1314 unless Developer Mode/admin privileges are
# enabled. huggingface_hub >= 1.9 understands this flag; older compatible hub
# releases simply ignore it. A runtime fallback for older releases lives in
# ``epub2m4b.hf_compat``.
if os.name == "nt":
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

__version__ = "0.1.10"

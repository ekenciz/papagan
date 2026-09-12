from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_public_lazy_imports_still_work():
    from epub2m4b.core import ConversionPipeline, PipelineOptions, QUALITY_PRESETS, parse_epub
    from epub2m4b.tts import create_engine, engine_infos

    assert callable(parse_epub)
    assert ConversionPipeline.__name__ == "ConversionPipeline"
    assert PipelineOptions.__name__ == "PipelineOptions"
    assert isinstance(QUALITY_PRESETS, dict)
    assert callable(create_engine)
    assert callable(engine_infos)


def test_xtts_worker_module_bootstraps_without_circular_import():
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "epub2m4b.tts.xtts_worker_process"],
        input="",
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )
    # No init message is intentionally supplied. A healthy worker reaches main()
    # and exits with 2. v0.1.7 instead crashed during module import with code 1.
    assert proc.returncode == 2, proc.stderr
    assert "partially initialized module" not in proc.stderr
    assert "circular import" not in proc.stderr.lower()

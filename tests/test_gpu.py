from types import SimpleNamespace


def test_nvidia_smi_fallback_parses_device_wide_vram(monkeypatch):
    from epub2m4b.core import gpu

    monkeypatch.setattr(
        gpu.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="NVIDIA GeForce RTX 3090, 57, 221.5, 11236, 24576\n",
            returncode=0,
        ),
    )
    result = gpu._nvidia_smi_stats(0)
    assert result["gpu_name"] == "NVIDIA GeForce RTX 3090"
    assert result["gpu_util_percent"] == 57
    assert result["power_w"] == 222
    assert result["vram_device_used_gb"] == 10.97
    assert result["vram_device_total_gb"] == 24.0
    assert result["telemetry_source"] == "nvidia-smi"

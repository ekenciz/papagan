import epub2m4b.core.dependencies as deps


def test_xtts_dependency_issues_flags_transformers_5(monkeypatch):
    monkeypatch.setattr(deps, "missing_modules", lambda _engine: [])

    def fake_version(name):
        return {"coqui-tts": "0.27.5", "transformers": "5.1.0", "torch": "2.8.0"}[name]

    monkeypatch.setattr(deps.metadata, "version", fake_version)
    issues = deps.dependency_issues("xtts")
    assert any("transformers 5.1.0" in issue for issue in issues)


def test_xtts_dependency_issues_accepts_pinned_stack(monkeypatch):
    monkeypatch.setattr(deps, "missing_modules", lambda _engine: [])

    def fake_version(name):
        return {"coqui-tts": "0.27.5", "transformers": "4.57.6", "torch": "2.8.0"}[name]

    monkeypatch.setattr(deps.metadata, "version", fake_version)
    assert deps.dependency_issues("xtts") == []


def test_xtts_installer_pins_transformers_below_5():
    packages = deps.ENGINE_DEPENDENCIES["xtts"].packages
    assert "transformers>=4.57,<5" in packages


def test_xtts_dependency_issues_requires_torchcodec_for_torch_29(monkeypatch):
    monkeypatch.setattr(deps, "missing_modules", lambda _engine: [])

    def fake_version(name):
        return {"coqui-tts": "0.27.5", "transformers": "4.57.6", "torch": "2.9.0"}[name]

    original_find_spec = deps.importlib.util.find_spec
    monkeypatch.setattr(deps.metadata, "version", fake_version)
    monkeypatch.setattr(
        deps.importlib.util,
        "find_spec",
        lambda name: None if name == "torchcodec" else original_find_spec(name),
    )
    issues = deps.dependency_issues("xtts")
    assert any("torchcodec eksik" in issue for issue in issues)


def test_deepspeed_release_is_pinned_for_reproducible_windows_build():
    assert deps.DEEPSPEED_VERSION == "0.19.6"
    assert deps.DEEPSPEED_REQUIREMENT == "deepspeed==0.19.6"

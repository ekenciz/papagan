from epub2m4b.tts.registry import ENGINE_CLASSES, engine_infos


def test_required_engines_registered():
    assert {"trendyol", "xtts", "mms"}.issubset(ENGINE_CLASSES)
    infos = {info.id: info for info in engine_infos()}
    assert infos["trendyol"].commercial_use is True
    assert infos["xtts"].requires_license_ack is True
    assert infos["xtts"].supports_builtin_speakers is True
    assert infos["xtts"].supports_reference_audio is True
    assert infos["xtts"].supports_speed_control is True
    assert infos["mms"].commercial_use is False

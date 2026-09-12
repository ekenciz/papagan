# Contributing

## Kurulum

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[gui,dev]"
```

## Kontroller

```bash
pytest -q
ruff check src tests
```

## Yeni TTS motoru ekleme

1. `src/epub2m4b/tts/` altında `TTSEngine` subclass oluşturun.
2. `EngineInfo` içine lisans, ticari kullanım, chunk limiti ve reference voice gereksinimini açıkça yazın.
3. Motoru `tts/registry.py` içine kaydedin.
4. Bağımlılıklarını `core/dependencies.py` ve `pyproject.toml` içine ekleyin.
5. `THIRD_PARTY_NOTICES.md` ve `DEVELOPMENT_LOG.md` dosyalarını güncelleyin.
6. Ağır model gerektirmeyen unit test ekleyin.

Model ağırlıklarını Git'e commit etmeyin.

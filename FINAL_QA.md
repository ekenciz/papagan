# Final QA - 2026-09-12 - v0.1.8

## Gercek Windows bulgusu

v0.1.7 logunda iki XTTS subprocess de model yuklemeden once `ImportError: cannot import name create_engine from partially initialized module epub2m4b.tts.registry` ile cikti. Bu nedenle secili 2 worker hic aktif olamadi ve pipeline tek-worker fallback ile ~0.97x realtime tamamlandi.

## v0.1.8 duzeltmeleri

- `epub2m4b.core.__init__` ve `epub2m4b.tts.__init__` eager importlari lazy public API'ye cevrildi.
- Gercek `python -m epub2m4b.tts.xtts_worker_process` bootstrap yolu test edildi; circular import yok.
- Public import uyumlulugu (`ConversionPipeline`, `PipelineOptions`, `parse_epub`, `create_engine`, `engine_infos`) regresyon testi ile korunuyor.
- DeepSpeed Windows kurulumu upstream `build_win.bat` source-build yoluna alindi ve `deepspeed==0.19.6` pinlendi.
- DeepSpeed kurulum hatasi GUI'yi Optimize moda aliyor; coklu-worker secimi kaybolmuyor.

## Otomatik testler

- `pytest -q`: **46 passed**
- `python -m compileall -q src tests`: PASS
- `PYTHONPATH=src python -m epub2m4b.cli --help`: PASS
- Worker bootstrap smoke: `python -m epub2m4b.tts.xtts_worker_process` bos stdin ile beklenen exit code 2; import crash yok.
- Onceki EPUB/TOC/chunker/pipeline/cache/XTTS/parallel scheduler/GPU parser testleri gecmeye devam ediyor.

## Bu ortamda dogrulanamayanlar

Container Windows + RTX 3090 icermedigi icin iki gercek XTTS model instance'inin ayni GPU'da throughput'u burada olculemedi. DeepSpeed VS2022 Windows wheel build'i de burada calistirilamadi. Bu nedenle 2/3/4 worker ve DeepSpeed'in gercek x-realtime sonucu kullanicinin Windows/RTX 3090 ortaminda benchmark edilmelidir.

Gercek sistemde beklenen kritik log:

```text
XTTS subprocess pool baslatiliyor: istenen worker=2.
XTTS worker 1 hazir: PID=...; mod=optimized
XTTS worker 2 hazir: PID=...; mod=optimized
XTTS paralel havuz hazir: 2/2 worker aktif.
```

Bu satirlar gorulmeden coklu-worker performansi basarili sayilmaz.

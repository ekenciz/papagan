# Final QA - 2026-09-12 - v0.1.11

## v0.1.11 TOC/source regressionlari

- EPUB3 nav ile spine dokumani eslesmesi: PASS
- TOC'de temsil edilen chapter `toc_listed=True` ve varsayilan secili: PASS
- Spine'da olup TOC'de olmayan chapter gorunur + varsayilan kapali: PASS
- Manifest-only XHTML chapter listesine alinmiyor: PASS
- TOC bulunmayan EPUB'da tum spine metni geriye uyumlu secili: PASS
- Pipeline explicit secim yokken TOC-oncelikli varsayilani kullaniyor: PASS
- CLI model lisansi varsayilani `True`, `--no-accept-model-license` opt-out: PASS
- README upstream kaynak/repo link tablosu: eklendi
- Voice-clone yetki onayi: explicit kaldi

## v0.1.11 test sonucu

```text
python -m compileall -q src tests  PASS
pytest -q                           59 passed
```


## v0.1.10 ek regresyonlar

- `enforce_chunk_limit()` 246 karakterlik sentetik parcayi <=220 alt parcalara ayiriyor: PASS
- Parent pipeline'a bilerek 150 karakterlik hatali chunker cikisi verildiginde engine limitinin altina yeniden boluyor: PASS
- XTTS worker 246 karakterlik IPC task'ini pool error vermeden iki alt senteze ayirip tek WAV uretiyor: PASS
- Tum test paketi: **55/55 PASS**
- `compileall`: PASS

Gercek Windows/RTX testindeki hedef log: `2/2 worker aktif` sonrasinda `XTTS Turkce metin parcasi guvenli siniri asti` nedeniyle tek-worker fallback gorulmemeli.

## Degisiklik kapsami

- XTTS AutoTune worker secimi (`0 = auto`)
- VRAM-aware 1-4 worker tavan hesaplama
- Ayni yuklu modellerle 1..N throughput benchmark ve 4.00x hedef secimi
- Longest-processing-time-first chunk scheduler
- Multi-worker CPU thread oversubscription azaltma
- Worker bazli realtime telemetrisi
- GUI/CLI AutoTune entegrasyonu

## Otomatik testler

- `pytest -q`: **55 passed**
- `python -m compileall -q src tests`: PASS
- CLI help/import smoke: PASS
- Worker bootstrap smoke/regresyon testleri: PASS
- LPT scheduler, worker subset, AutoTune secim ve `--xtts-workers auto` testleri: PASS

## Bu ortamda dogrulanamayanlar

Bu container RTX 3090/Windows CUDA ortami icermedigi icin 1/2/3/4 worker gercek XTTS throughput olcumu burada yapilamadi. AutoTune algoritmasi ve scheduler fake-worker regresyon testleriyle dogrulandi; gercek x-realtime kazanci kullanicinin Windows/RTX 3090 sisteminde olculecek. 4.00x realtime bir hedef olup garanti degildir.

## Gercek sistemde beklenen kritik log

```text
XTTS paralel mod: AutoTune 1-4 bagimsiz subprocess worker; aygit=cuda; mod=optimized.
XTTS AutoTune: 1 worker = ...x realtime
XTTS AutoTune: 2 worker = ...x realtime
XTTS AutoTune: 3 worker = ...x realtime
XTTS AutoTune: 4 worker = ...x realtime
XTTS AutoTune sonucu: ... -> secilen=N worker
XTTS worker verimleri: PID ...: ...x/... parca | ...
```

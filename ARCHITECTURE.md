# Architecture

## Tasarım hedefleri

- Yeni TTS motoru eklemek çekirdek pipeline'ı değiştirmemeli.
- EPUB ayrıştırma, metin hazırlama, TTS ve audio muxing birbirinden bağımsız olmalı.
- Uzun kitaplarda hata sonrası yeniden başlatma maliyeti düşük olmalı.
- Model ağırlıkları repoda tutulmamalı.
- Lisans/onay gerektiren motorlar uygulama seviyesinde açıkça işaretlenmeli.

## Katmanlar

### 1. Ingestion

`core/epub.py`

EPUB aslında ZIP kapsayıcısıdır. Parser:

1. `META-INF/container.xml` dosyasından OPF yolunu bulur.
2. OPF metadata içinden title/creator/language okur.
3. Manifest ve spine sırasını çıkarır.
4. Spine'daki XHTML/HTML belgelerini BeautifulSoup ile temizler.
5. Başlıkları ve paragraf metinlerini `Chapter` nesnelerine dönüştürür.
6. OPF `cover` veya EPUB3 `cover-image` bilgisinden kapağı çıkarır.
7. EPUB3 `nav.xhtml` veya EPUB2 NCX içindekiler ağacını `TocEntry` nesnelerine dönüştürür.
8. TOC hedeflerini canonical EPUB-internal href üzerinden spine `Chapter.index` değerleriyle eşleştirir.

TOC'de yer almayan fakat spine içinde seslendirilebilir olan belgeler kaybolmaz; GUI'de `TOC dışındaki içerik` altında fallback girdileri olarak gösterilir. Aynı XHTML dosyasındaki farklı anchor'lara işaret eden TOC girdileri v0.1.3'te aynı seslendirme birimine eşlenir; anchor-seviyesinde metin dilimleme sonraki aşamadır.

### 2. NLP / Chunker

`core/chunker.py`

Model bağımsız chunker, motorun `recommended_max_chars` değerini alır. Önce paragraf sınırlarını korur; uzun paragrafları cümlelere, aşırı uzun cümleleri noktalama/boşluk sınırlarına böler.

XTTS v2 özelinde upstream tokenizer Türkçe (`tr`) için 226 karakterlik giriş sınırı tanımlar. `XTTSEngine` bu nedenle `recommended_max_chars=220` kullanır. Altı karakterlik marj, pipeline'ın hiçbir normal chunk'ı sınırın üstüne göndermemesini sağlar. Ayrıca `XTTSEngine.synthesize()` 220 karakter üzerindeki doğrudan çağrıları reddederek gelecekteki başka kod yollarının sessiz kırpılmış ses üretmesini önler.

İleride buraya Türkçe sayı/tarih/kısaltma normalizasyonu ve kullanıcı telaffuz sözlüğü eklenecek.

### 3. TTS Strategy / Plugin

`tts/base.py`

Her motor `TTSEngine` sözleşmesini uygular:

- `info`: ad, lisans, referans ses ve speaker/hız kabiliyetleri, önerilen chunk boyutu
- `reference_audio_required()`: seçili motor ayarına göre referans sesin gerçekten zorunlu olup olmadığını bildirir
- `load()`: modeli bir kez yükler
- `synthesize()`: tek chunk -> WAV
- `close()`: gerekirse kaynakları serbest bırakır

Kayıt: `tts/registry.py`

v0.1 motorları:

- `TrendyolVoxCPMEngine`
- `XTTSEngine`
- `MMSTurkishEngine`

#### XTTS v2 ses katmanı

`XTTSEngine` iki çalışma modu taşır:

1. `builtin`: XTTS modelinin hazır speaker listesi dinamik okunur ve `speaker=` ile sentez yapılır. Varsayılan öneri `Chandra MacFarland`'dır.
2. `clone`: kullanıcı tarafından izinli bir referans ses `speaker_wav=` ile kullanılır. Bu modda referans dosyası ve açık ses kullanım onayı zorunludur.

Konuşma hızı `0.70x-1.60x` aralığında motor seçeneğidir. `voice_mode`, `speaker` ve `speed` değerleri `engine_options` içinde taşındığından chunk cache hash'ine otomatik olarak katılır. Böylece farklı speaker veya hız ayarında daha önce üretilmiş yanlış WAV parçaları tekrar kullanılmaz.

Coqui'nin PyTorch içindeki eski JIT yolunu tetiklemesi güncel PyTorch sürümlerinde `torch.jit.script is deprecated` FutureWarning üretebilir. Uygulama yalnız bu tam internal warning desenini XTTS yükleme/smoke-test yolunda filtreler; genel warning sistemi kapatılmaz.

Coqui sürümleri speaker listesini farklı attribute'larda açabildiği için adapter hem `tts.speakers` hem de model içindeki `speaker_manager` kaynaklarını okuyup de-duplicate eder. Bu yaklaşım MIT lisanslı `muhammedsaban/coqui-xtts-v2-turkish-local` projesindeki yerel Türkçe XTTS kullanımından teknik referans almıştır; uzun ses birleştirme mimarisi ise bu projeye kopyalanmamış, epub-to-m4b'nin disk cache + FFmpeg yaklaşımı korunmuştur.

### 4. Orchestrator

`core/pipeline.py`

Akış:

1. FFmpeg kontrolü
2. EPUB parse
3. GUI/CLI tarafından verilen TOC/bölüm filtresini spine bölümlerine uygulama
4. motor oluşturma ve dinamik referans-ses/lisans/voice-consent doğrulama
5. yalnız seçili chapter -> chunk listeleri
6. deterministic run cache dizini
7. her chunk için TTS veya mevcut WAV cache kullanımı
8. chunk sürelerinden yalnız seçili chapter zamanlarının hesaplanması
9. M4B assembly
10. başarılı işlemde isteğe göre work/cache temizleme

`PipelineOptions.selected_chapter_indices=None` tüm spine içeriğini ifade eder. GUI ise analizden sonra açıkça tüm chapter indexlerini seçili geçirir; kullanıcı checkbox kaldırdıkça liste daralır.

### 5. Audio assembly / Muxer

`core/audio.py`

- WAV parçaları FFmpeg concat demuxer ile birleştirilir.
- Tek geçişte AAC kodlanır.
- `FFMETADATA1` chapter girişleri eklenir.
- EPUB kapağı varsa attached picture olarak MP4/M4B içine map edilir.
- `+faststart` kullanılır.

### 6. GUI

PySide6 arayüz ana thread'de kalır. Model yükleme, TTS ve pip kurulumu `QThread` worker'larında yürür. Böylece uzun sentez sırasında pencere donmaz.

XTTS için GUI ayrıca:

- hazır speaker / voice-clone mod seçimi,
- dinamik speaker listeleme,
- hız kontrolü,
- yaklaşık 10 saniyelik kısa önizleme üretimi,
- PySide6 multimedia ile önizleme oynatma

sağlar. Speaker listeleme ve önizleme de ayrı worker thread'lerinde çalışır; ana pencere model yüklenirken bloklanmaz.

GUI ayrıca EPUB analizinden sonra checkable bir TOC ağacı gösterir. Bütün girdiler ilk açılışta seçilidir. Parent seçimleri children'a yayılır; gerçek seslendirme filtresi TOC girdisinin bağlı olduğu `Chapter.index` üzerinden oluşturulur.

### Bağımlılık doğrulama/onarım

`core/dependencies.py` iki ayrı seviyede kontrol yapar:

1. Hafif GUI durum kontrolü: gerekli modüller ve bilinen sürüm uyumsuzlukları (özellikle XTTS + Transformers 5.x).
2. Kur/Onar sonunda gerçek import smoke testi: ayrı Python sürecinde motorun kritik import zinciri yüklenir.

Bu ayrım önemlidir; `importlib.find_spec("TTS")` bir paket klasörünün varlığını gösterebilir fakat `from TTS.api import TTS` alt bağımlılık sürüm çakışması yüzünden yine başarısız olabilir. v0.1.3 bu yanlış "Hazır" durumunu özellikle ele alır.

## Cache / resume yaklaşımı

Run dizini platform cache alanında EPUB path/size/mtime, motor ve referans ses kimliğinden türetilir. Her chunk ayrıca metin + motor ayarlarından hash alır. Aynı iş yarıda kesildiğinde üretilmiş WAV dosyaları yeniden kullanılabilir.

v0.4'te bu yapı JSON manifest ve engine-version fingerprint ile daha katı hale getirilecektir.

## Neden subprocess engine isolation sonraya bırakıldı?

VoxCPM2 ve XTTS ağır Python/PyTorch stack'leri kullanır. Uzun vadede her motorun ayrı sanal ortam/subprocess içinde çalışması bağımlılık çakışmalarını ve GPU memory lifecycle sorunlarını azaltır. v0.1'de geliştirme hızını korumak için aynı venv içinde plugin yüklenir; interface ileride RPC/subprocess adaptörüne dönüştürülebilecek kadar dar tutulmuştur.

## M4B chapter hesabı

TTS motoru her WAV için duration döndürür. Chapter başlangıcı önceki chapter chunk sürelerinin toplamıdır. Bu değer milisaniyeye çevrilerek FFmpeg chapter metadata'ya yazılır. Böylece metin uzunluğundan süre tahmini yapılmaz; gerçek üretilmiş ses kullanılır.

## Güvenlik ve kullanım

- DRM kaldırma kapsam dışıdır.
- XTTS yalnızca voice-clone modu seçildiğinde referans ses ve kullanıcı izin onayı zorunludur; hazır speaker modunda kullanıcı sesi işlenmez.
- XTTS ve MMS non-commercial lisans koşulları GUI'de görünür ve onaysız model yüklenmez.
- Uygulama model lisanslarını değiştirmez; ağırlıkları dağıtmaz.


## v0.1.6 XTTS performance path

`XTTSEngine` now exposes three execution paths. `optimized` calls the underlying XTTS model `inference()` method directly. It resolves built-in speaker conditioning once, or computes clone conditioning once from the reference clip, then reuses those tensors for all subsequent audiobook chunks. `deepspeed` rebuilds the XTTS GPT inference wrapper with `use_deepspeed=True` when the optional dependency is available; initialization failure falls back to `optimized`. `compatibility` keeps the previous `TTS.api.tts_to_file()` route as a fallback/troubleshooting path.

On CUDA, the optimized path enables inference mode and TF32-compatible matmul settings. FP16/autocast remains disabled because XTTS reports include numerical instability on some runtimes. Parallel synthesis is implemented with **separate spawned processes**, not concurrent threads sharing one XTTS object. Each process owns a model instance and CUDA context, avoiding the known shared-model thread-safety risk. v0.1.6 limits the GUI/CLI to one or two workers; 2-worker failure automatically falls back to the parent process's single-worker engine after reusing any atomically published WAVs.

Parallel workers synthesize into per-PID `.part.<pid>.wav` files and only publish the final cache filename via atomic `os.replace()` after a successful chunk. Completion order is decoupled from output order: jobs carry a monotonic sequence number and chapter/chunk coordinates, and final M4B concatenation uses that original sequence.

`ConversionPipeline` measures generated audio, processed characters, aggregate wall-clock throughput and summed worker synthesis time. ETA is suppressed for the first 10 uncached chunks, then estimated from aggregate x-realtime and observed audio-per-character. The GUI therefore avoids the v0.1.5 startup behavior where one or two chunks could produce wildly wrong multi-hour ETAs.

`XTTSEngine.runtime_stats()` reports process-local PyTorch allocation. `core/gpu.py` additionally queries NVML from the parent process to report **device-wide used VRAM**, GPU utilization and board power. In 2-worker mode the latest per-worker PyTorch allocations are summed separately. This distinction fixes the confusing case where the GUI showed ~1.8 GB while `nvidia-smi` reported much higher total board usage.

### Optional DeepSpeed

DeepSpeed is deliberately not part of the mandatory XTTS dependency set. On Windows its inference extensions may require Visual C++ Build Tools / Developer Command Prompt setup. The GUI exposes a separate install/repair action. Coqui's XTTS model path ultimately calls `gpt.init_gpt_for_inference(..., use_deepspeed=True)` from `load_checkpoint`; because the high-level TTS wrapper has already loaded the checkpoint, v0.1.6 rebuilds only that inference wrapper. If the optional package or kernel injection is unavailable, the engine logs the reason and continues in `optimized` mode.

### Benchmark

The GUI benchmark uses fixed Turkish text fixtures. Model loading and warm-up chunks are excluded from the measured interval. For two workers it uses the same spawned-process task implementation as the real book pipeline. The benchmark reports aggregate x-realtime, effective worker count/mode and worker VRAM allocation, and compares the result with the user-facing 4.00x target. The target is diagnostic, not a guaranteed performance claim.

## v0.1.7 Windows-safe XTTS subprocess pool

v0.1.6 used `ProcessPoolExecutor` with the Windows `spawn` multiprocessing context. Conversion itself runs in a Qt `QThread`; on the real Windows GUI this combination could fail worker bootstrap and trigger the single-worker fallback even though the UI requested two workers. v0.1.7 removes Python multiprocessing from the XTTS hot path.

Each XTTS worker is now an explicit `sys.executable -u -m epub2m4b.tts.xtts_worker_process` child. Stdout is reserved for a JSON-lines request/response protocol while ordinary Coqui/torch output is redirected to stderr. A persistent worker loads one XTTS model, speaker conditioning and CUDA context once, then processes many chunk tasks. The parent uses one lightweight scheduling thread per child, so free workers pull the next chunk dynamically. Final chapter/audio ordering remains sequence-driven and independent of completion order.

The pool supports 1-4 workers. Partial startup is explicit: if 4 were requested and only 3 loaded, telemetry reports `3/4` rather than silently claiming four. Task/process failure still preserves atomically published WAVs and allows the pipeline's single-worker recovery path.

Device-wide GPU telemetry prefers NVML and falls back to `nvidia-smi --query-gpu`. PyTorch `memory_allocated()` remains process-local and is labelled separately. Because launching `nvidia-smi` is comparatively expensive, that fallback is sampled no faster than once per second.

On Windows, DeepSpeed installation is treated as a build workflow, not a normal pure-Python pip dependency. The GUI can install VS2022 Build Tools/VCTools through winget after explicit user confirmation, then invokes pip from `VsDevCmd.bat`; if necessary it downloads the source distribution and runs upstream `build_win.bat` to produce a wheel. Failure leaves the normal XTTS optimized subprocess path untouched.

## v0.1.8 import-boundary hardening

The real Windows v0.1.7 run exposed a Python package bootstrap cycle before any XTTS model was loaded. Running `python -m epub2m4b.tts.xtts_worker_process` first imports the parent package `epub2m4b.tts`. The old `tts/__init__.py` eagerly imported `registry`; `registry` imported `base`; `base` imported `epub2m4b.core.models`; importing that submodule executed `core/__init__.py`, which eagerly imported `pipeline`; and `pipeline` imported `tts.registry` again while it was only partially initialized.

v0.1.8 removes eager public-API imports from both package initializers. `epub2m4b.core` and `epub2m4b.tts` expose their historical names through module-level lazy `__getattr__`. Subprocess workers can therefore import `core.models` and `tts.xtts` without pulling the conversion pipeline or registry into their bootstrap path. A regression test launches the actual module with `python -m`; reaching worker `main()` and exiting with the expected no-init code proves the import graph is acyclic before heavy model dependencies are touched.

DeepSpeed Windows installation is also aligned with upstream's source-build path: pin one release, download its sdist, enter the VS2022 x64 Developer environment and run `build_win.bat`, then install the generated wheel. This remains optional; normal optimized multi-worker inference is independent of DeepSpeed.

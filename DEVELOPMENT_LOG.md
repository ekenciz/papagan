# Development Log

## 2026-09-09 — v0.1.0 başlangıç implementasyonu

### 1. Gereksinim değerlendirmesi

- Nihai format M4B olarak sabitlendi.
- İlk sürüm girdisi EPUB olarak daraltıldı.
- TTS mimarisi Strategy/Plugin yapısına ayrıldı.
- Zorunlu ilk motorlar: Trendyol-TTS (VoxCPM2), Coqui XTTS v2, Facebook MMS Turkish.
- Yerel model kullanımı ve model ağırlıklarının repoya dahil edilmemesi kararlaştırıldı.

### 2. Lisans doğrulaması

- Trendyol/Trendyol-TTS model kartı: MIT metadata; temel model openbmb/VoxCPM2.
- VoxCPM2: Apache-2.0.
- Coqui XTTS v2: CPML, non-commercial.
- facebook/mms-tts-tur: CC-BY-NC-4.0.
- PySide6: LGPLv3/GPLv3 community seçenekleri.
- EbookLib: AGPL-3.0 olduğu için çekirdekten çıkarıldı; EPUB doğrudan ZIP/OPF ile işleniyor.

### 3. Repo iskeleti

- `pyproject.toml`
- `src/epub2m4b/`
- `tests/`
- `scripts/`
- `.gitignore`
- README / architecture / third-party notices

### 4. EPUB ingestion

- container.xml -> OPF çözümleme
- Dublin Core title/creator/language
- OPF manifest/spine sırası
- HTML/XHTML temizleme
- h1/h2/h3/title başlık algılama
- cover / cover-image çıkarma

### 5. Metin bölümleme

- whitespace normalizasyonu
- paragraf sınırı koruma
- temel Türkçe kısaltma koruması
- cümle sınırında bölme
- aşırı uzun cümlelerde güvenli hard split

### 6. TTS motorları

- Ortak `TTSEngine` interface
- Trendyol-TTS: `voxcpm==2.0.3`, `Trendyol/Trendyol-TTS`, önerilen cfg=2.0 / 16 timestep
- XTTS v2: `coqui-tts==0.27.5`, Türkçe `tr`, reference WAV
- MMS Turkish: Transformers VITS inference
- Engine lisans metadata ve chunk limitleri

### 7. Pipeline

- deterministic run fingerprint
- chunk bazlı disk cache
- model bir kez load, çok chunk synthesize
- gerçek WAV duration ile chapter zaman hesabı
- cancel event
- work/cache temizleme seçeneği

### 8. M4B

- FFmpeg availability check
- concat list
- FFMETADATA chapter üretimi
- AAC quality preset
- EPUB cover mapping
- faststart

### 9. GUI

- PySide6 main window
- EPUB/output seçimleri
- EPUB metadata analizi
- TTS model/lisans bilgisi
- model dependency check/install
- device seçimi
- XTTS reference voice + consent
- kalite profili
- conversion worker thread
- progress/log/cancel

### 10. Kurulum

- Windows tek tık PowerShell/BAT akışı
- Linux kurulum betiği
- sanal ortam
- uv ile donanıma uygun PyTorch backend kurmayı deneme
- FFmpeg otomatik kurulum denemesi

### 11. Testler

- chunker sınır testleri
- sentetik EPUB parser testi
- ffmetadata chapter testi
- registry testi

## Sonraki teknik işler

- EPUB nav/NCX TOC başlıklarını spine ile eşlemek
- Türkçe sayı/tarih/ölçü normalizer
- telaffuz sözlüğü
- model subprocess isolation
- daha kalıcı job manifest/resume
- Calibre MOBI/AZW3 adapter
- ASR tabanlı kalite/telaffuz denetimi

### 12. İlk doğrulama turu

- Python compileall geçti.
- Unit testler: 6/6 geçti.
- Gerçek FFmpeg smoke testi ile iki WAV parçası M4B'ye dönüştürüldü.
- `ffprobe` ile iki chapter'ın (0-500 ms, 500-1000 ms), title ve artist metadata'nın doğru yazıldığı doğrulandı.
- Başarısız/iptal edilmiş işlerde cache'in yanlışlıkla silinmemesi için cleanup yalnız başarılı run sonrasına alındı.
- FFmpeg GUI bağımlılık kurucusuna da eklendi; Windows winget, Linux apt ve macOS brew yolları desteklendi.

### 13. Dayanıklılık iyileştirmeleri

- GUI dependency installer, PyTorch yoksa `uv --torch-backend=auto` ile CPU/CUDA backend seçimini deniyor; başarısızsa normal pip kurulumuna düşüyor.
- TTS chunk'ları önce `.part.wav` olarak yazılıp başarıdan sonra atomik biçimde cache dosyasına taşınıyor; yarım WAV cache'e giremiyor.
- Mevcut cache WAV süresi doğrulanıyor; bozuk cache yeniden üretiliyor.
- Kapak görseli M4B içine her zaman MJPEG'e dönüştürülerek yazılıyor; EPUB3 WebP/PNG gibi kapaklarda MP4 uyumluluğu artırıldı.
- Düşük kalite profili kullanıcı gereksinimine uygun olarak 32 kbps AAC yapıldı.

### 14. Pipeline regression testleri

- Fake TTS engine ile model indirmeden uçtan uca pipeline testi eklendi.
- Başarılı işlemde workspace temizliği test ediliyor.
- Mux hatasında tamamlanmış WAV cache'in korunduğu ve `.part.wav` kalmadığı test ediliyor.

### 15. Repo/CI son rötuşları

- Git line-ending politikası (`.gitattributes`) ve editor ayarları eklendi.
- GitHub Actions üzerinde Python 3.10/3.11/3.12 test + Ruff matrisi eklendi.
- `CHANGELOG.md` ve `python -m epub2m4b` entry point eklendi.
- TTS motorları işlem sonunda model referanslarını bırakıp CUDA cache temizliği yapıyor.

### 16. Final QA

- Final test seti 8/8 geçti.
- PNG cover -> MJPEG attached picture M4B smoke testi tekrar geçti.
- Apostrof içeren dosya yolunda FFmpeg concat doğrulandı.
- TOML parse, Bash installer syntax ve CLI help doğrulandı.
- GUI/model inference testlerinin bu çalışma ortamındaki bağımlılık/ağırlık eksikleri nedeniyle yapılmadığı `FINAL_QA.md` içinde açıkça kaydedildi.

## 2026-09-10 - v0.1.1 Windows Hugging Face symlink duzeltmesi

Gercek Windows denemesinde Trendyol-TTS ilk model yuklemesinde Hugging Face cache snapshot'i olusturulurken `OSError: [WinError 1314] A required privilege is not held by the client` hatasi goruldu. Hata modelin kendisinden veya CUDA'dan degil, Windows'un normal kullanici hesabina sembolik bag olusturma yetkisi vermemesinden kaynaklaniyordu.

Duzeltme iki katmanli yapildi. Hugging Face Hub 1.9 ve sonrasinin destekledigi `HF_HUB_DISABLE_SYMLINKS=1` Windows'ta uygulama daha alt modulleri import etmeden ayarlaniyor. XTTS/Transformers 4.x ile birlikte kullanilabilen daha eski Hugging Face Hub surumlerinde ise upstream `_create_symlink` davranisi korunuyor; yalnizca WinError 1314 gercekten olusursa ayni blob snapshot hedefine normal dosya olarak kopyalaniyor. Bu sayede daha once indirilmis 5+ GB Trendyol model blob'lari yeniden indirilmek zorunda kalmiyor.

Ayni koruma Hugging Face kullanan MMS motoruna da eklendi. Farkli OSError turleri yutulmuyor; sadece WinError 1314 fallback'e giriyor. Regresyon testleri, dosyanin kopyalanmasini, kaynak blob'un korunmasini ve diger hatalarin aynen yukariya tasinmasini dogruluyor.

## 2026-09-11 - v0.1.2 XTTS hazır speaker / voice-clone entegrasyonu

1. `muhammedsaban/coqui-xtts-v2-turkish-local` deposunun README ve `app.py` yapısı incelendi.
2. Ayrı bir dördüncü TTS motoru eklemek yerine mevcut `XTTSEngine` genişletildi; böylece aynı model/bağımlılık iki kez yönetilmiyor.
3. XTTS motoruna iki çalışma modu eklendi:
   - `builtin`: modelin kendi speaker listesinden hazır ses,
   - `clone`: izinli referans WAV ile voice cloning.
4. Coqui sürümleri arasındaki speaker API farklarına karşı hem `tts.speakers` hem de `speaker_manager` kaynaklarını okuyup tekilleştiren `extract_speakers()` eklendi.
5. Upstream projede önerilen `Chandra MacFarland` hazır speaker varsayılanı olarak eklendi; modelde bulunmazsa güvenli fallback davranışı tanımlandı.
6. XTTS `speed` parametresi uygulama ayarı haline getirildi ve `0.70x-1.60x` aralığı doğrulanıyor.
7. `EngineInfo` kabiliyet metadata'sı `supports_builtin_speakers`, `supports_reference_audio`, `supports_speed_control` alanlarıyla genişletildi.
8. Pipeline referans WAV gereksinimini artık yalnız statik `EngineInfo` üzerinden değil, motorun `reference_audio_required()` metodundan dinamik olarak kontrol ediyor.
9. XTTS `voice_mode`, `speaker` ve `speed` değerleri `engine_options` içine taşındı. Mevcut cache hash mekanizması bu alanları zaten kullandığı için farklı ses/hız ayarlarının cache'i ayrıştırıldı.
10. PySide6 GUI'ye XTTS için:
    - ses yöntemi dropdown,
    - hazır speaker dropdown,
    - `Sesleri Yükle/Yenile` düğmesi,
    - hız kontrolü,
    - `~10 sn Örnek Ses Üret` düğmesi,
    - `Tekrar Oynat` düğmesi
    eklendi.
11. Speaker listeleme ve kısa ses önizleme model yüklemesinin ana GUI thread'ini kilitlememesi için ayrı `QThread` worker'larına alındı.
12. Önizleme WAV'ı platform cache alanındaki `previews/` dizinine yazılıyor ve PySide6 `QMediaPlayer` ile otomatik oynatılıyor.
13. Built-in speaker modunda referans WAV ve voice-consent zorunluluğu kaldırıldı; clone modunda önceki lisans ve ses kullanım izni güvenlik kontrolleri aynen korundu.
14. CLI'ya `--xtts-voice-mode`, `--xtts-speaker`, `--xtts-speed` seçenekleri eklendi.
15. README, mimari, yol haritası, third-party notice ve changelog v0.1.2 için güncellendi.
16. Yeni speaker discovery/mod testleri eklendi. Son çekirdek test sonucu: `15 passed`.
17. `python -m compileall -q src tests` başarılı. Bu çalışma ortamında PySide6 kurulu olmadığı için canlı GUI/multimedia smoke testi yapılamadı.

## 2026-09-11 - v0.1.3 XTTS dependency repair + TOC seçim ekranı

1. Gerçek Windows test ekranında XTTS seçili iken GUI'nin `Kurulum: Hazır ✓` göstermesine rağmen önizlemenin `RuntimeError: XTTS motoru için PyTorch ve 'coqui-tts' paketleri kurulu değil` mesajıyla durduğu incelendi.
2. Hata mesajının kökü ayrıştırıldı: v0.1.2 `find_spec()` ile yalnız modül klasörünün varlığını kontrol ediyor, `from TTS.api import TTS` içindeki alt import hatalarını da tek bir `ImportError` mesajına dönüştürüyordu.
3. Maintained `coqui-tts` 0.27.5 stack'i için `transformers>=4.57,<5` sabitlendi. Aynı venv'i paylaşan MMS aralığı da `<5` ile uyumlu hale getirildi.
4. `dependency_issues()` eklendi. XTTS için coqui dağıtım sürümü ve Transformers major sürümü modül varlığından ayrı kontrol ediliyor.
5. GUI'deki dependency düğmesi `Bağımlılıkları Kur/Onar` olarak değiştirildi ve durum `Hazır` olsa bile kullanıcıya açık tutuldu.
6. Kur/Onar sonunda ayrı Python sürecinde `torch`, `torchaudio`, `transformers` ve `from TTS.api import TTS` import smoke testi eklendi. Böylece bozuk runtime kurulumu başarı olarak raporlanmıyor.
7. `XTTSEngine.load()` import exception handling iki aşamaya ayrıldı. PyTorch hatası ile `TTS.api`/alt bağımlılık hatası artık asıl exception türü ve metniyle raporlanıyor.
8. Windows ve Linux tek tık kurulum betikleri aynı Transformers pinini ve XTTS import smoke testini kullanacak şekilde güncellendi.
9. `TocEntry` veri modeli eklendi. EPUB3 `nav.xhtml` ve EPUB2 NCX hiyerarşisini okuyup href hedeflerini spine chapter indexlerine eşleyen parser eklendi.
10. TOC'de bulunmayan spine belgeleri `TOC dışındaki içerik` fallback grubunda korunuyor.
11. PySide6 GUI'ye `İçindekiler / Seslendirilecek Bölümler` checkable tree eklendi. Analiz sonrası bütün gerçek chapter'lar varsayılan seçili geliyor; `Tümünü Seç` ve `Tümünü Kaldır` kısayolları eklendi.
12. Parent checkbox değişiklikleri children'a yayılıyor. Aynı XHTML dosyasının farklı anchor/alias TOC girdileri aynı chapter indexine bağlı olduğu için birlikte seçilip kaldırılıyor.
13. GUI seçili bölüm sayısını ve toplam karakter sayısını canlı gösteriyor; sıfır bölüm seçili iken dönüştürme başlatılmıyor.
14. `PipelineOptions.selected_chapter_indices` eklendi ve pipeline chunking/TTS/M4B chapter üretimini yalnız seçili bölümlere uyguluyor.
15. CLI'ya `--chapters 1,3-5,9` filtresi eklendi.
16. EPUB3 nested TOC, TOC fallback, seçili bölüm pipeline, dependency pin/uyumsuzluk ve CLI bölüm aralığı regresyon testleri eklendi.
17. Son çekirdek test sonucu: `24 passed`; `python -m compileall -q src tests` başarılı.
18. Bu yürütme ortamında PySide6 kurulu olmadığı için TOC widget'ı ve gerçek XTTS Windows/NVIDIA inference akışı canlı çalıştırılamadı; kullanıcı Windows makinesinde v0.1.3 ile doğrulama gerekecek.
19. PyTorch/torchaudio alt süreç import kontrolüne 30 saniyelik timeout/failure fallback eklendi; bozuk CUDA/runtime importu kilitlenirse kurulum akışı artık onarım moduna geçiyor.
20. Final paket öncesi patch temiz v0.1.2 üzerine uygulanıp yeni testler dahil **24/24** test tekrar geçirildi.

## 2026-09-11 - v0.1.4 XTTS Türkçe chunk sınırı düzeltmesi

1. Kullanıcı Windows/XTTS gerçek çalışma ortamından `The text length exceeds the character limit of 226 for language 'tr'` uyarılarını ve PyTorch `torch.jit.script is deprecated` FutureWarning mesajlarını paylaştı.
2. v0.1.3 `XTTSEngine.info.recommended_max_chars` değerinin 240 olduğu doğrulandı; pipeline bu değeri doğrudan `chunk_text()` sınırı olarak kullandığı için 227-240 karakter arası Türkçe parçalar XTTS'ye gönderilebiliyordu.
3. XTTS v2 tokenizer upstream kaynağında Türkçe `char_limits['tr'] = 226` olduğu doğrulandı.
4. XTTS güvenli chunk hedefi 220 karaktere indirildi. Genel chunker mimarisi değiştirilmedi; yalnız XTTS motorunun verdiği motor-özel sınır düzeltildi.
5. `XTTSEngine.synthesize()` girişine 220 karakter üstü parçaları model yüklenmeden önce reddeden savunmacı kontrol eklendi. Böylece gelecekte pipeline dışında doğrudan çağrı yapılırsa olası kırpılmış ses sessizce üretilmeyecek.
6. Coqui tarafından PyTorch içindeki eski JIT yolundan tetiklenen `torch.jit.script is deprecated` FutureWarning için yalnız tam mesaj + `torch.jit._script` modülünü hedefleyen dar kapsamlı warning filtresi eklendi. Diğer FutureWarning mesajları korunuyor.
7. Aynı warning filtresi XTTS dependency runtime smoke testine de eklendi.
8. XTTS 226/220 sınır ilişkisi, motor metadata sınırı ve oversized doğrudan sentez guard'ı için testler eklendi.
9. Uzun Türkçe paragrafın 220 karakteri aşmayan parçalara ayrıldığını doğrulayan chunker regresyon testi eklendi.
10. v0.1.3 TOC seçim özelliği korunarak README, Architecture, Roadmap, Changelog ve Final QA dokümanları v0.1.4 için güncellendi.


## 2026-09-11 - v0.1.5 XTTS performance pass

1. User-provided `nvidia-smi` capture confirmed RTX 3090 CUDA inference was active, with substantial VRAM use and roughly mid-range GPU utilization rather than a CPU fallback.
2. Reviewed current Coqui XTTS low-level API: `inference()` accepts cached `gpt_cond_latent` and `speaker_embedding`; built-in speaker tensors are available through `speaker_manager`; clone conditioning can be computed once with `get_conditioning_latents()`.
3. Added optimized XTTS path with one-time conditioning cache for both built-in and clone modes.
4. Added explicit compatibility path using the previous `tts_to_file()` API.
5. Enabled `torch.inference_mode()` and CUDA TF32-compatible settings; did not enable FP16 or concurrent inference because upstream/community reports include instability/thread-safety failures.
6. Added pipeline performance counters: realtime factor, ETA, generated audio duration, cache hits and elapsed synthesis time.
7. Added optional NVML telemetry and GUI performance display.
8. Added CLI performance-mode switch and dependency/install support for `nvidia-ml-py`.
9. Added regression tests for conditioning cache and stats emission.

## 2026-09-12 - v0.1.6 XTTS parallel / DeepSpeed performance pass

1. User benchmark on RTX 3090 stabilized around **0.93x realtime** even after the v0.1.5 low-level inference path. The GUI also showed only ~1.8 GB PyTorch allocation while prior `nvidia-smi` captures showed much higher device-wide memory use, so the telemetry semantics were corrected instead of treating 1.8 GB as total board VRAM use.
2. Added `core/gpu.py` for parent-process NVML telemetry: device-wide used/total VRAM, GPU utilization and board power are now distinct from process-local `torch.cuda.memory_allocated()`.
3. Added `tts/xtts_parallel.py`. CUDA parallelism uses `multiprocessing`/`ProcessPoolExecutor` with **spawn** and one independent `XTTSEngine` model per process. No XTTS model object is shared between threads/processes.
4. Added a 2-worker pipeline path. Chunks are scheduled concurrently, written to PID-specific temporary WAVs and atomically renamed into the shared cache. Final M4B ordering is rebuilt from stable sequence/chapter/chunk coordinates rather than future completion order.
5. Added deterministic per-chunk RNG seed derived from task id + text so audio behavior is independent from worker assignment.
6. Added automatic single-worker fallback when 2-worker initialization/inference fails. Already published worker WAVs are validated/reused rather than discarded.
7. `worker_count` was explicitly excluded from the audio cache key because scheduling does not change the requested voice/speed/model parameters.
8. Added optional `deepspeed` performance mode. After the standard XTTS checkpoint is loaded, the GPT inference wrapper is rebuilt with `init_gpt_for_inference(..., use_deepspeed=True)`. Missing/failed DeepSpeed initialization logs the reason and falls back to `optimized`.
9. Kept DeepSpeed out of the mandatory XTTS dependency set. Added a separate GUI install/repair action and best-effort `deepspeed>=0.19,<0.20` installer. Windows failure messaging explains the possible Visual C++ Build Tools requirement.
10. Added GUI worker selection (1/2), defaulting to 2 for the target RTX 3090 workflow, plus a fixed-text **Hız Testi** that excludes model load/warmup and reports aggregate x-realtime vs the 4.00x target.
11. Replaced the noisy early ETA behavior with a 10-uncached-chunk warmup. Aggregate throughput is measured after the first completed chunk; ETA is emitted only after warmup.
12. Added separate aggregate realtime factor, worker-average realtime factor and model-load-included factor for diagnostics.
13. Added `if __name__ == "__main__"` guard to `epub2m4b.__main__` so Windows `spawn` children do not recursively launch the GUI.
14. Added regression coverage for DeepSpeed inference-wrapper init, DeepSpeed low-level synthesis path, deterministic parallel seeds, worker-count-neutral cache keys, warmup ETA, 2-worker branch selection and 2-worker -> single-worker fallback.
15. Final local regression result in the container: **40 passed**. Real RTX 3090 / Windows dual-model throughput and DeepSpeed kernel availability still require validation on the user's machine.

## 2026-09-12 - v0.1.7 Windows worker bootstrap + throughput pass

1. User screenshots showed `2 worker` selected but live conversion status reported `Worker: 1`; v0.1.6 was therefore silently falling back after the Windows multiprocessing worker path failed.
2. Replaced `ProcessPoolExecutor(spawn)` with persistent explicit Python child processes launched using `python -m epub2m4b.tts.xtts_worker_process`. This avoids Qt-QThread + Windows-spawn bootstrap fragility.
3. Added a JSON-lines IPC protocol with stdout reserved for protocol frames and library/model output redirected to stderr.
4. Added dynamic chunk scheduling across persistent workers; each worker loads XTTS, CUDA and conditioning only once.
5. Raised selectable worker count to 1/2/3/4; 2 remains the safe default and 3/4 are marked experimental for 24 GB VRAM GPUs.
6. Added explicit active/requested worker telemetry and detailed worker startup/task tracebacks. Partial startup no longer masquerades as the requested worker count.
7. Moved the benchmark to the exact same subprocess pool used by real book conversion.
8. Corrected VRAM semantics: NVML remains preferred, but missing Python NVML now falls back to device-wide `nvidia-smi --query-gpu`; PyTorch allocation is labelled separately.
9. Rate-limited `nvidia-smi` fallback to 1 Hz to avoid telemetry becoming a CPU/scheduler bottleneck.
10. Reworked optional Windows DeepSpeed install: detect VS2022 VCTools, ask the GUI user before multi-GB winget installation, invoke pip under `VsDevCmd.bat`, then fall back to source `build_win.bat` wheel creation.
11. Added regression tests for four-worker scheduling, partial startup fallback and nvidia-smi parsing.
12. Final local result: **43 passed** plus compileall success. Real RTX 3090 2/3/4-worker and DeepSpeed throughput still requires the user's Windows validation.

## 2026-09-12 - v0.1.8 Windows circular import fix

1. Gercek Windows logu incelendi: her iki XTTS subprocess `epub2m4b.tts.registry` partially-initialized circular import hatasi ile model yuklemeden once cikiyordu.
2. Import zinciri izole edildi: `tts.__init__ -> registry -> base -> core.models -> core.__init__ -> pipeline -> tts.registry`.
3. `core/__init__.py` ve `tts/__init__.py` eager importlardan arindirildi; public API PEP 562 lazy `__getattr__` ile geriye uyumlu tutuldu.
4. Gercek `python -m epub2m4b.tts.xtts_worker_process` bootstrap regresyon testi eklendi. Bos stdin testinde worker `main()` seviyesine ulasip beklenen kod 2 ile cikiyor; v0.1.7 bug'i kod 1 ile importta cokuyordu.
5. DeepSpeed'in Windows'ta source distribution yayinladigi ve upstream Windows yolunun `build_win.bat` oldugu dikkate alinarak kurulum akisi sadeleştirildi. DeepSpeed `0.19.6`'ya sabitlendi ve Windows'ta dogrudan sdist -> build_win.bat -> wheel install yolu kullaniliyor.
6. DeepSpeed kurulum hatasinda GUI `Optimize` moda otomatik donuyor, fakat 2/3/4 worker secimi korunuyor.
7. `pytest -q`: 46/46 PASS. `compileall`: PASS. CLI help smoke: PASS. Worker module bootstrap smoke: PASS.


## 2026-09-12 - v0.1.9 AutoTune scheduler ve 4x hedefi

1. v0.1.8'de manuel 1/2/3/4 worker seciminin kullanici tarafindan tek tek denenmesi gerektigi belirlendi.
2. `AUTO_WORKERS=0` semantigi eklendi; GUI/CLI varsayilani AutoTune yapildi.
3. GPU cihaz VRAM'ine gore 1-4 arasinda guvenli worker tavanini hesaplayan on-kontrol eklendi; Auto modunda workerlar sirali yuklenip her modelden sonra VRAM tekrar kontrol ediliyor.
4. Ayni yuklenmis subprocess pool icinde 1..N worker subset benchmark'i eklendi; model tekrar yuklenmiyor.
5. 4.00x hedefini gecen ilk worker sayisi seciliyor; hedef yoksa en hizli sonuc, %3 yakinlikta daha dusuk worker sayisi seciliyor.
6. Book-task dispatch FIFO'dan longest-processing-time-first'e alindi; final M4B sirasi sequence ile korunuyor.
7. Child process CPU thread havuzlari kisitlandi ve CUDA expandable allocator acildi.
8. Worker PID bazli audio/wall/chunk istatistikleri ve GUI worker throughput araligi eklendi.
9. CLI `--xtts-workers auto` destegi ve GUI AutoTune benchmark sonucu kazanan worker'i otomatik secme eklendi.
10. Yeni scheduler/AutoTune testleriyle `pytest -q`: 52/52 PASS.


## 2026-09-12 - v0.1.10 oversized XTTS task fault containment

1. Gercek RTX 3090 logunda iki subprocess'in basariyla `2/2` hazir oldugu, ancak LPT ile ilk giden gorevlerin 246 ve 232 karakter oldugu icin worker `XTTS_SAFE_MAX_CHARS=220` kontrolunde dustugu goruldu.
2. Parent pipeline'a `enforce_chunk_limit()` eklendi; worker job'lari olusmadan once tum chunk'lar ikinci kez sinirlanir.
3. Hazirlama loguna `gercek maks` parcasi eklendi.
4. Worker prosesine son-emniyet re-chunk yolu eklendi. IPC'den oversized metin gelirse alt parcalar ayni model instance'inda sentezlenip tek WAV'a birlestirilir; task_error uretilmez.
5. Parent onarimi ve worker-local onarim icin regresyon testleri eklendi.
6. `pytest -q`: 55/55 PASS.

## 2026-09-12 - v0.1.11 TOC-first content policy + source attribution

1. Kullanici istegiyle bundan sonraki README surumlerinde yararlanilan upstream repo/model/teknik kaynak linklerinin tutulmasi kural haline getirildi; mevcut kaynaklar README tablosuna eklendi.
2. `Chapter.toc_listed`, `TocEntry.source`, `TocEntry.default_selected` ve `ParsedBook.has_navigation_toc` metadata alanlari eklendi.
3. EPUB3 nav / EPUB2 NCX ile gercek spine dokumani eslesen bolumler varsayilan seslendirme kumesi yapildi.
4. Spine'da olup TOC'de olmayan okunabilir dokumanlar `TOC disindaki icerik` grubunda gorunur tutuldu fakat varsayilan isaretleri kapatildi.
5. Manifest'te olup spine'da olmayan XHTML'in chapter listesine girmedigi regresyon testiyle sabitlendi.
6. Navigasyon TOC'si hic yoksa veya hicbir spine dokumanina eslenemiyorsa tum parse edilen spine metnini secen geriye-uyumlu fallback korundu.
7. GUI'ye `Kaynak / statu` sutunu ve `TOC Icerigini Sec` dugmesi eklendi.
8. Pipeline explicit chapter secimi yokken `ParsedBook.default_selected_chapter_indices()` politikasini kullanacak sekilde degistirildi; CLI ve GUI ayni davranisa getirildi.
9. Model lisansi varsayilani GUI/CLI/PipelineOptions/XTTS/MMS icin kabul edildi; CLI'da `--no-accept-model-license` opt-out eklendi. Referans ses `voice_consent` onayi otomatiklestirilmedi.
10. Testler: `pytest -q` 59/59 PASS; `compileall` PASS.

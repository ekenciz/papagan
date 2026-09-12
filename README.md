# EPUB to M4B

Python tabanlı, grafik arayüzlü bir **EPUB -> Türkçe sesli kitap (M4B)** dönüştürücü.

İlk sürümün amacı tek bir uçtan uca hattı güvenilir hale getirmektir:

`EPUB -> spine/metadata/cover -> bölüm metinleri -> TTS chunk'ları -> WAV -> chapter zamanları -> AAC/M4B`

## v0.1.8 ile gelenler

- EPUB2/EPUB3 ZIP/OPF/spine okuma
- EPUB3 `nav` ve EPUB2 NCX içindekiler (TOC) okuma
- GUI'de TOC ağacı üzerinden seslendirilecek bölümleri seçme; varsayılan olarak tümü seçili
- Kitap adı, yazar, dil ve kapak çıkarma
- Paragraf/cümle temelli Türkçe chunking
- Plugin tabanlı TTS motorları
  - **Trendyol/Trendyol-TTS (VoxCPM2)**
  - **Coqui XTTS v2**
  - **facebook/mms-tts-tur**
- XTTS v2 için iki ses yöntemi:
  - model içindeki hazır speaker'lar
  - izinli referans sesten voice cloning
- XTTS speaker listesini modelden dinamik yükleme; önerilen varsayılan: **Chandra MacFarland**
- XTTS konuşma hızı: **0.70x-1.60x**
- XTTS **Optimize** modu: low-level inference + speaker/clone conditioning cache + CUDA TF32
- XTTS icin **1-4 bagimsiz subprocess worker**; 2 worker guvenli varsayilan, 3/4 worker 24 GB VRAM kartlarda deneysel
- Opsiyonel **DeepSpeed** inference modu; Windows'ta VS2022 C++ Build Tools otomatik kurulum secenegi + Developer Command Prompt build akisi
- GUI icinde **Hiz Testi**: secili worker/mode ayarinin gercek x-realtime performansini isinma sonrasinda olcer
- Canli performans telemetrisi: GPU/VRAM/guc, realtime factor, uretilen ses ve ETA
- VRAM telemetrisi **cihaz toplam kullanimi** ile worker PyTorch allocation degerlerini ayri gosterir; NVML yoksa `nvidia-smi` fallback kullanir
- ETA ilk 10 uncached parca boyunca "isiniyor" durumunda tutulur; erken ve anlamsiz saatler/dakikalar tahmini gosterilmez
- XTTS Türkçe için güvenli **220 karakter** chunk sınırı; upstream tokenizer sınırı olan 226 karakterin altında kalır
- GUI içinden yaklaşık 10 saniyelik XTTS ses önizleme ve tekrar oynatma
- PySide6 grafik arayüz
- Model/bağımlılık denetleme, **Kur/Onar** ve gerçek runtime import testi
- XTTS için `coqui-tts==0.27.5` + `transformers>=4.57,<5` uyumluluk sabitlemesi
- Kesilen işlerde aynı chunk'ların tekrar üretilmesini azaltan disk önbelleği
- FFmpeg ile AAC kodlama, M4B chapter metadata ve EPUB kapağı gömme
- CLI ile EPUB analizi ve dönüştürme



### v0.1.8 Windows worker bootstrap duzeltmesi

v0.1.7 gercek Windows testinde worker sureci `python -m epub2m4b.tts.xtts_worker_process` ile baslarken Python once `epub2m4b.tts.__init__` dosyasini yukluyordu. Bu dosyanin registry'yi eager import etmesi; registry -> base -> `core.models` -> `core.__init__` -> pipeline -> registry zinciriyle circular import uretiyordu. Sonuc: GUI'de 2 worker secili olsa bile iki child process de kod 1 ile cikiyor ve pipeline tek-worker fallback'e dusuyordu.

v0.1.8'de `core` ve `tts` public package API'leri lazy import edildi. Worker modulu artik agir pipeline/registry importlarini bootstrap sirasinda tetiklemeden aciliyor. Bu duzeltme, 2/3/4 worker seciminin gercekten child process baslatabilmesi icin kritik.

Beklenen log:

```text
XTTS subprocess pool baslatiliyor: istenen worker=2.
XTTS worker 1 hazir: PID=...; mod=optimized
XTTS worker 2 hazir: PID=...; mod=optimized
XTTS paralel havuz hazir: 2/2 worker aktif.
```

`partially initialized module 'epub2m4b.tts.registry'` gorulmemelidir. DeepSpeed kurulu olmasa bile **Optimize + 2/3/4 worker** calisabilir.

DeepSpeed Windows tarafinda PyPI'da yalniz kaynak dagitimi oldugu icin v0.1.8, sabit `deepspeed==0.19.6` kaynagini indirip VS2022 Developer ortaminda upstream `build_win.bat` ile wheel olusturmayi dener. Build Tools yoksa GUI yine kullanici onayi ister. Kurulum basarisizsa calisma modu otomatik `Optimize`'a doner; worker sayisi korunur.

### XTTS performans modu (v0.1.7)

XTTS icin varsayilan calisma yolu artik **Optimize** modudur. Bu yol, Coqui high-level `tts_to_file()` katmanina her parcada tekrar girmek yerine modelin low-level `inference()` API'sini kullanir. Hazir speaker conditioning tensorleri bir kez okunur; voice-clone modunda referans sesten `gpt_cond_latent` ve `speaker_embedding` yalnizca bir kez hesaplanir ve kitap boyunca bellekte tutulur. CUDA'da `torch.inference_mode()` ve TF32 matmul optimizasyonu etkinlestirilir.

GUI, donusum sirasinda destekleniyorsa GPU adi, GPU kullanim yuzdesi, guc, VRAM, realtime factor, uretilen ses suresi ve tahmini kalan sureyi gosterir. NVIDIA telemetrisi icin `nvidia-ml-py` kullanilir; bu paket yoksa donusum devam eder ve yalniz ilgili telemetri alanlari bos kalir.

v0.1.7, Windows/Qt tarafinda v0.1.6'daki `ProcessPoolExecutor(spawn)` yolunu kaldirir. Donusum zaten bir `QThread` icinde calistigi icin Windows spawn bootstrap'i bazen 2-worker secimine ragmen worker havuzunu dusurup tek-worker fallback'e geciyordu. Yeni yol her XTTS worker'i `python -m epub2m4b.tts.xtts_worker_process` ile **kalici ayri subprocess** olarak baslatir ve JSON-lines IPC kullanir. Model her worker'da bir kez yuklenir; parcalar bosalan worker'a dinamik dagitilir. GUI artik gercek aktif/istenen worker sayisini (`2/4`, `1/2 fallback`) acikca gosterir.

Worker secenekleri 1, 2, 3 ve 4'tur. 2 worker RTX 3090 icin guvenli baslangic, 3/4 worker ise 24 GB VRAM kartlarda deneysel throughput secenekleridir. 4x realtime bir hedeftir; worker sayisini 4 yapmak tek basina 4x garanti etmez.

**DeepSpeed (deneysel / hizli)** secenegi Coqui XTTS'nin GPT inference wrapper'ini `use_deepspeed=True` ile yeniden kurmayi dener. DeepSpeed Windows'ta ek C++ build araclari gerektirebildigi icin normal XTTS kurulumunun zorunlu parcasi degildir; GUI'de ayri **DeepSpeed Kur/Onar** dugmesi vardir. DeepSpeed import/initialization basarisiz olursa kitap donusumu durmaz, motor otomatik olarak `optimized` moda geri doner.

GUI'deki **Hiz Testi** model yukleme ve ilk isinma parcalarini olcum disinda birakir. Sonuc `2.35x realtime` gibi verilir ve 4.00x hedefinin ne kadarina ulasildigini gosterir. 4x bir hedef/benchmark'tir; tek bir RTX 3090 üzerinde garanti edilmez. Gercek hiz kitap metni, speaker, XTTS sampling davranisi, CUDA/PyTorch/DeepSpeed surumleri ve ayni GPU'yu kullanan diger uygulamalara baglidir.

Sorunlu bir Coqui surumu/ortami icin **Uyumluluk / klasik TTS.api** modu korunur. Bu mod kalite karsilastirmasi ve geriye donuk hata ayiklama icindir.

## Lisanslar ve kullanım sınırları

Uygulama kodu MIT lisanslıdır. Model ağırlıkları repoya dahil edilmez; ilk kullanımda ilgili sağlayıcıdan indirilir.

| Motor | Model lisansı | Ticari kullanım |
|---|---|---|
| Trendyol-TTS | Model kartı MIT; temel VoxCPM2 Apache-2.0 | Model kartı/upstream açısından mümkün; veri ve kullanım koşullarını ayrıca kontrol edin |
| Coqui XTTS v2 | Coqui Public Model License (CPML) | **Hayır** |
| Facebook MMS Turkish | CC-BY-NC-4.0 | **Hayır** |

XTTS ve MMS seçildiğinde GUI açık lisans onayı ister. XTTS yalnızca "Referans sesten klonlama" modu seçildiğinde referans ses dosyası ve ses kullanım/klonlama izni ister. "Hazır XTTS sesi" modunda referans WAV gerekmez.

Ayrıntılar: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## Sistem gereksinimleri

- **Python 3.11 önerilir**. Proje Python `>=3.10,<3.13` hedefler; bu aralık VoxCPM2 çalışma zamanı ile uyumludur.
- **FFmpeg** ve tercihen `ffprobe`
- Trendyol-TTS / VoxCPM2 için NVIDIA CUDA sistemi kuvvetle önerilir.
- XTTS GPU ile çok daha kullanışlıdır; CPU çalışması yavaş olabilir.
- MMS Türkçe en hafif seçenektir ve CPU senaryosu için uygundur.

> Model dosyaları büyüktür. Trendyol-TTS Hub deposu yaklaşık 5 GB sınıfındadır; ayrıca Python/PyTorch ortamı için disk alanı gerekir.

## Windows: tek tık kurulum

1. Repoyu indirin/klonlayın.
2. `scripts/install_windows.bat` dosyasını çift tıklayın.
3. Kurulum bitince `scripts/run_windows.bat` dosyasını çalıştırın.

Kurucu şunları yapar:

- Python 3.11'i bulmaya çalışır; yoksa `winget` varsa kurmayı dener.
- `.venv` oluşturur.
- GUI ve bütün TTS runtime bağımlılıklarını kurar.
- `uv` kullanarak uygun PyTorch backend'ini seçmeye çalışır.
- XTTS için `transformers` 4.57.x serisini (<5) kullanır ve `TTS.api` import smoke testi yapar.
- FFmpeg yoksa `winget` üzerinden kurmayı dener.

DeepSpeed normal kurulumun parcasi degildir. XTTS ekraninda `DeepSpeed (deneysel / hizli)` secildikten sonra **DeepSpeed Kur/Onar** ile ayrica denenebilir. v0.1.7 Windows'ta gerekli VS2022 C++ Build Tools bulunmuyorsa `winget` ile otomatik kurulum icin onay ister; ardindan VS Developer ortaminda kurulum dener ve gerekirse upstream `build_win.bat` wheel yoluna geri duser. DeepSpeed yine de kurulamazsa normal Optimize ve 1-4 subprocess worker yolu kullanilabilir.

Model ağırlıkları kurulum sırasında indirilmez; seçili motor ilk kez çalıştırıldığında indirilir.

## Manuel kurulum

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[gui]"
```

Sonra ihtiyacınız olan motoru kurun:

```bash
pip install -e ".[trendyol]"
pip install -e ".[xtts]"
pip install -e ".[mms]"
```

PyTorch CUDA/CPU varyantı donanıma göre ayrıca seçilmelidir. `coqui-tts` 0.27.4+ PyTorch'u varsayılan bağımlılık olarak getirmediği için tek tık betiği bu adımı ayrıca yönetir.

### GUI'de bölüm/TOC seçimi

EPUB seçilip analiz edildiğinde **İçindekiler / Seslendirilecek Bölümler** ağacı otomatik doldurulur. İlk durumda bütün bölümler işaretlidir. Seslendirilmesini istemediğiniz önsöz, teşekkür, kaynakça, dizin veya başka bir bölümün işaretini kaldırmanız yeterlidir. Yalnız işaretli EPUB spine bölümleri TTS pipeline'ına gönderilir ve M4B chapter listesine eklenir.

EPUB3 `nav.xhtml` ve EPUB2 NCX hiyerarşisi korunur. Bazı EPUB'larda birden fazla TOC alt başlığı aynı XHTML dosyasındaki farklı anchor'lara işaret eder; v0.1.3 seslendirme birimini spine/XHTML dosyası olarak tuttuğu için bu tür alias başlıklar birlikte seçilip kaldırılır.

## Çalıştırma

GUI:

```bash
epub2m4b
```

EPUB analizi:

```bash
epub2m4b-cli analyze kitap.epub
```

Trendyol ile dönüştürme:

```bash
epub2m4b-cli convert kitap.epub kitap.m4b --engine trendyol --device cuda
```

XTTS hazır speaker ile dönüştürme:

```bash
epub2m4b-cli convert kitap.epub kitap.m4b \
  --engine xtts \
  --xtts-voice-mode builtin \
  --xtts-speaker "Chandra MacFarland" \
  --xtts-speed 1.0 \
  --xtts-performance-mode optimized \
  --xtts-workers 2 \
  --accept-model-license
```

XTTS 2 worker + DeepSpeed denemesi:

```bash
epub2m4b-cli convert kitap.epub kitap.m4b \
  --engine xtts \
  --device cuda \
  --xtts-voice-mode builtin \
  --xtts-speaker "Chandra MacFarland" \
  --xtts-performance-mode deepspeed \
  --xtts-workers 2 \
  --accept-model-license
```

XTTS referans sesten klonlama ile dönüştürme:

```bash
epub2m4b-cli convert kitap.epub kitap.m4b \
  --engine xtts \
  --xtts-voice-mode clone \
  --xtts-speed 1.0 \
  --xtts-performance-mode optimized \
  --reference-wav sesim.wav \
  --accept-model-license \
  --voice-consent
```

GUI'de XTTS seçildiğinde "Ses yöntemi" alanından hazır speaker veya voice cloning modu seçilir. Hazır speaker modunda **Sesleri Yükle/Yenile** düğmesi gerçek speaker listesini modelden okur. Hız alanı ve **~10 sn Örnek Ses Üret** düğmesi nihai kitap dönüştürmesini başlatmadan ayarı dinlemenizi sağlar. İlk speaker/önizleme işleminde XTTS model dosyaları indirilebilir.

### XTTS `226 karakter` uyarısı

XTTS v2 tokenizer'ı Türkçe için 226 karakterlik bir giriş uyarı sınırı tanımlar. v0.1.3'te motor hedefi yanlışlıkla 240 karakter olduğu için uzun parçalarda `The text length exceeds the character limit of 226 for language 'tr'` uyarısı görülebiliyor ve ses kırpılma riski oluşabiliyordu. v0.1.4 motor hedefini **220 karaktere** indirir ve her TTS çağrısından önce savunmacı uzunluk kontrolü uygular. Böylece uzun EPUB paragrafları cümle/boşluk sınırlarından güvenli parçalara ayrılır.

PyTorch'un Coqui içinden tetiklenen `torch.jit.script is deprecated` mesajı uygulamanın işleyişini bozmaz. v0.1.4 yalnız bu bilinen internal FutureWarning desenini filtreler; diğer uyarılar görünür kalır.

### XTTS "kurulu değil" / import hatası

v0.1.2'de yalnız modül dosyasının bulunması bağımlılığı "Hazır" gösterebiliyordu; `TTS.api` içindeki bir alt bağımlılık hata verdiğinde mesaj yanlışlıkla "PyTorch ve coqui-tts kurulu değil" diyordu. v0.1.3 bu denetimi düzeltir: bilinen uyumsuz `transformers` 5.x kurulumu algılanır, **Bağımlılıkları Kur/Onar** düğmesi her zaman erişilebilir tutulur ve kurulum sonunda gerçek `from TTS.api import TTS` testi çalıştırılır.

## Kalite profilleri

- Düşük: 32 kbps AAC / 22.05 kHz
- Standart: 64 kbps AAC / 44.1 kHz
- Yüksek: 128 kbps AAC / 48 kHz

Kaynak modelin örnekleme hızı daha düşükse daha yüksek M4B örnekleme hızına çevirmek yeni ses ayrıntısı yaratmaz; kalite profili esas olarak oynatıcı uyumluluğu ve bitrate seçimini yönetir.

## Mimari

Detaylı tasarım için [ARCHITECTURE.md](ARCHITECTURE.md) dosyasına bakın.

Özet:

- `core/epub.py`: EPUB container/OPF/spine/cover + EPUB3 nav/EPUB2 NCX TOC
- `core/chunker.py`: metin normalizasyonu ve chunking
- `tts/base.py`: TTS Strategy/Plugin sözleşmesi
- `tts/registry.py`: motor kayıt sistemi
- `tts/xtts.py`: built-in speaker discovery, clone/builtin modları, conditioning cache, low-level inference, CUDA/VRAM telemetrisi ve hız kontrolü
- `tts/xtts_parallel.py`: process-isolated XTTS worker pool tasklari, atomic WAV publish ve deterministic per-chunk seed
- `core/gpu.py`: device-wide NVML GPU/VRAM/guc telemetrisi
- `core/pipeline.py`: orchestration, cache, iki-worker scheduling, fallback, chapter süreleri, stabilize realtime factor ve ETA
- `core/audio.py`: FFmpeg concat + ffmetadata + M4B
- `gui/`: PySide6 masaüstü arayüz ve worker thread'leri

## Neden EbookLib kullanılmıyor?

EbookLib güncel olarak AGPL-3.0 lisanslıdır. v0.1.0 için gereken EPUB okuma işlevi standart `zipfile`, XML parser ve MIT lisanslı BeautifulSoup ile yeterince kapsanabildiğinden, uygulama çekirdeğine gereksiz AGPL copyleft bağımlılığı alınmamıştır.

## Geliştirme

```bash
pip install -e ".[gui,dev]"
pytest -q
ruff check src tests
```

Yapılan işlemlerin kronolojik kaydı: [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)

## Sınırlamalar / v0.1.x dışı

- MOBI/AZW/AZW3 -> Calibre dönüştürme henüz eklenmedi.
- Çift dilli otomatik TR/EN yönlendirme henüz yok; v0.1.x Türkçe sesli kitap odaklıdır.
- DRM korumalı kitaplar desteklenmez.
- Model indirme ilerlemesi sağlayıcının kendi çıktısından gelir; ortak bir model download manager henüz yoktur.
- Uzun kitaplarda kalite kontrol/ASR ile otomatik telaffuz doğrulaması sonraki fazdadır.

## Yol haritası

1. v0.1 — EPUB + Trendyol/XTTS/MMS + GUI + chapter'lı M4B
2. v0.1.2 — XTTS hazır speaker/voice-clone modu, hız kontrolü ve GUI ses önizleme
3. v0.1.3 — EPUB nav/NCX TOC bölüm seçimi ve XTTS bağımlılık onarım/doğrulama akışı
4. v0.1.4 — XTTS Türkçe 226 karakter limitine güvenli chunking ve PyTorch JIT warning temizliği
5. v0.1.5 — XTTS low-level inference, conditioning cache, TF32 ve canlı GPU/RTF/ETA telemetrisi
6. v0.1.6 — XTTS 2-process worker, opsiyonel DeepSpeed, benchmark, duzeltilmis VRAM/ETA telemetrisi
7. v0.1.7 — Windows-safe kalici XTTS subprocess havuzu, 1-4 worker, DeepSpeed Build Tools otomasyonu, `nvidia-smi` VRAM fallback
8. v0.1.8 — Windows circular-import worker bootstrap fix, lazy package API, DeepSpeed 0.19.6 upstream build_win yolu
7. v0.2 — Calibre üzerinden MOBI/AZW3 ingestion ve anchor-seviyesinde alt bölüm ayırma
8. v0.3 — Türkçe metin normalizasyonu (sayı, tarih, kısaltma), telaffuz sözlüğü
9. v0.4 — Engine subprocess/izole environment desteği, daha güçlü resume/checkpoint
10. v0.5 — Bilingual segment routing ve çoklu karakter/ses profilleri
11. v1.0 — Paketlenmiş Windows uygulaması, otomatik güncelleme ve regression kalite testleri

### Windows: `WinError 1314` / Hugging Face symlink hatasi

v0.1.1 ile uygulama bu durumu otomatik yonetir. Windows Developer Mode acik veya uygulama yonetici olarak calisiyor olmak zorunda degildir. Trendyol-TTS ya da MMS modeli indirilirken Hugging Face cache'i sembolik bag olusturamiyorsa uygulama gercek dosya kopyasi kullanir. Daha once indirilmis model blob'lari varsa bunlar yeniden kullanilir.

v0.1.0'dan guncelliyorsaniz yeni surumu ayni sanal ortamda yeniden kurduktan sonra uygulamayi tamamen kapatip acin. Eski yarim cache'i elle silmek normalde gerekmez.

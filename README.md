# EPUB to M4B

Python tabanlı, grafik arayüzlü bir **EPUB -> Türkçe sesli kitap (M4B)** dönüştürücü.

İlk sürümün amacı tek bir uçtan uca hattı güvenilir hale getirmektir:

`EPUB -> spine/metadata/cover -> bölüm metinleri -> TTS chunk'ları -> WAV -> chapter zamanları -> AAC/M4B`

## v0.1.11 ile gelenler

- EPUB2/EPUB3 ZIP/OPF/spine okuma
- EPUB3 `nav` ve EPUB2 NCX içindekiler (TOC) okuma
- GUI'de TOC ağacı üzerinden seslendirilecek bölümleri seçme; **TOC'de görünen içerik varsayılan seçili**, spine'da olup TOC'de görünmeyen ek içerik varsayılan kapalı
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
- XTTS icin **AutoTune veya 1-4 bagimsiz subprocess worker**; AutoTune GPU/VRAM ve gercek inference olcumune gore en hizli worker sayisini secer
- Opsiyonel **DeepSpeed** inference modu; Windows'ta VS2022 C++ Build Tools otomatik kurulum secenegi + Developer Command Prompt build akisi
- GUI icinde **Hiz Testi**: AutoTune seciliyken 1-4 worker'i ayni yuklu modellerle karsilastirir; manuel secimde secili worker/mode ayarini olcer
- Canli performans telemetrisi: GPU/VRAM/guc, realtime factor, uretilen ses ve ETA
- VRAM telemetrisi **cihaz toplam kullanimi** ile worker PyTorch allocation degerlerini ayri gosterir; NVML yoksa `nvidia-smi` fallback kullanir
- ETA ilk 10 uncached parca boyunca "isiniyor" durumunda tutulur; erken ve anlamsiz saatler/dakikalar tahmini gosterilmez
- XTTS Türkçe için güvenli **220 karakter** chunk sınırı; upstream tokenizer sınırı olan 226 karakterin altında kalır
- v0.1.10 parent + worker chunk-boundary koruması: limit-ustu tek gorev coklu-worker havuzunu artik tek-worker fallback'e dusurmez
- GUI içinden yaklaşık 10 saniyelik XTTS ses önizleme ve tekrar oynatma
- PySide6 grafik arayüz
- Model/bağımlılık denetleme, **Kur/Onar** ve gerçek runtime import testi
- XTTS için `coqui-tts==0.27.5` + `transformers>=4.57,<5` uyumluluk sabitlemesi
- Kesilen işlerde aynı chunk'ların tekrar üretilmesini azaltan disk önbelleği
- FFmpeg ile AAC kodlama, M4B chapter metadata ve EPUB kapağı gömme
- CLI ile EPUB analizi ve dönüştürme




### v0.1.11 TOC-oncelikli varsayilan secim

EPUB analizinde artik `manifest -> spine -> TOC` iliskisi ayri tutulur:

- **TOC'de bulunan + spine'da bulunan XHTML/HTML**: ana sesli-kitap icerigi kabul edilir ve varsayilan olarak secilir.
- **Spine'da bulunan fakat TOC'de gorunmeyen XHTML/HTML**: GUI'de `Spine / TOC disi` olarak listelenir fakat varsayilan olarak isaretlenmez. Kullanici isterse elle acabilir.
- **Manifest'te olup spine'da olmayan kaynaklar**: normal okuma akisi olmadiklari icin seslendirme listesine alinmaz. CSS, font, resim vb. kaynaklar zaten metin bolumu degildir.
- EPUB'da kullanilabilir bir EPUB3 `nav` / EPUB2 NCX TOC yoksa uygulama kitabi bos birakmamak icin eski davranisa doner ve parse edilen spine metinlerinin tumunu varsayilan secer.

GUI'ye **Kaynak / statu** sutunu ve **TOC Icerigini Sec** dugmesi eklendi. `Tumunu Sec` ile TOC disi spine metinleri de elle dahil edilebilir. CLI'da `--chapters` verilmezse kullanilabilir TOC bulunan kitaplarda ayni TOC-oncelikli varsayilan uygulanir. `epub2m4b-cli analyze` her bolumu `[TOC; secili]`, `[Spine/TOC disi; atlanir]` veya `[Spine (TOC yok); secili]` olarak raporlar.

### Lisans varsayilani

Model lisansi onay kutulari artik **varsayilan olarak isaretli** gelir ve `PipelineOptions.accept_model_license` / CLI varsayilani `True`'dur. CLI'da gerekirse `--no-accept-model-license` ile kapatilabilir. Bu degisiklik yalnız model lisansi onayinin varsayilanini etkiler; **referans ses kullanma/klonlama yetkisi** kullaniciya ozel bir beyan oldugu icin otomatik kabul edilmez.

### v0.1.10 XTTS chunk-boundary guvenligi

Gercek Windows coklu-worker testinde LPT scheduler en uzun iki gorevi ilk siraya aldiginda 232 ve 246 karakterlik iki metin worker seviyesindeki 220-karakter korumasina takilip tum pool'u tek-worker fallback'e dusurdu. v0.1.10 bu hata sinifini iki seviyede kapatir:

1. Parent pipeline, `chunk_text()` cikisini worker job'u olusturmadan once yeniden dogrular ve oversized parcayi tekrar boler.
2. Bir oversized metin buna ragmen subprocess IPC'ye ulasirsa worker gorevi reddetmez; yerel olarak `<=220` alt parcalara ayirir, her parcayi ayni yuklu modelle seslendirir ve ara WAV'lari tek sonuc WAV'inda birlestirir.

Hazirlama logu artik gercek maksimum parcayi da gosterir. XTTS icin normal durumda sunu gormelisiniz:

```text
117 TTS parcasi hazirlandi (hedef: <= 220 karakter; gercek maks: 220).
```

Coklu-worker havuzu basladiktan sonra `232/246 karakter > 220` nedeniyle tek-worker fallback artik olmamalidir. Worker savunmasi devreye girmek zorunda kalirsa logda `XTTS worker savunmaci yeniden-bolme` mesaji gorunur; bu durum donusumu durdurmaz.

### v0.1.9 AutoTune + GPU scheduler

Worker sayisini elle tahmin etmek yerine **Otomatik (1-4 worker olc, en hizlisini sec)** modu kullanilabilir. AutoTune once cihaz-geneli VRAM'i kontrol eder, guvenli sayida XTTS subprocess yukler ve modelleri tekrar yuklemeden 1, 2, 3 ve 4 worker throughput'unu ayni test metinleriyle olcer. Hedef 4.00x realtime'dir; hedefe ulasan ilk daha-dusuk worker sayisi tercih edilir. Hedefe ulasilamazsa en hizli olculen ayar secilir.

Ornek log:

```text
XTTS AutoTune: 1 worker = 0.96x realtime
XTTS AutoTune: 2 worker = 1.82x realtime
XTTS AutoTune: 3 worker = 2.41x realtime
XTTS AutoTune: 4 worker = 2.36x realtime
XTTS AutoTune sonucu: 1w=0.96x | 2w=1.82x | 3w=2.41x | 4w=2.36x -> secilen=3 worker
```

Gercek kitap chunk'lari artik **Longest Processing Time First** ile dispatch edilir. Uzun chunk'lar once worker'lara verilerek son kuyrukta tek uzun parcanin tum isi geciktirmesi azaltılır. WAV dosya adlari/sequence bilgisi nedeniyle final M4B sirasi yine EPUB sirasi olarak kalir. Multi-worker child process'lerde CPU thread havuzlari 1'e sinirlanir; bu, 3-4 worker calisirken CPU oversubscription'in GPU'yu aclikta birakmasini azaltir.

GUI'de `Hiz Testi` AutoTune ile calistirilirsa kazanan worker sayisi otomatik secilir; boylece kitap donusumu benchmark'i tekrar etmek zorunda kalmaz. Benchmark calistirmadan dogrudan `M4B Olustur` denirse pipeline AutoTune'u kendi baslatir. CLI varsayilani da `--xtts-workers auto`'dur.

4.00x bir hedef olarak kalir; tek RTX 3090'da elde edilecek deger XTTS autoregressive GPT katmani, WDDM/CUDA context contention, DeepSpeed durumu ve diger GPU yuklerine baglidir.


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

## Yararlanılan kaynaklar / upstream projeler

Bu proje model ağırlıklarını veya aşağıdaki projelerin kod tabanlarını yeniden dağıtmayı amaçlamaz; entegrasyon, API davranışı, Windows kurulumu ve performans tasarımı için aşağıdaki açık kaynak / açık model kaynaklarından yararlanır. Her bileşenin kendi lisans koşulları geçerlidir; ayrıntılar için [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) dosyasına bakın.

| Kaynak | Bu projedeki kullanım | Bağlantı |
|---|---|---|
| Trendyol-TTS | Türkçe VoxCPM2 TTS motoru | https://huggingface.co/Trendyol/Trendyol-TTS |
| OpenBMB VoxCPM / VoxCPM2 | Trendyol-TTS temel çalışma zamanı ve API referansı | https://github.com/OpenBMB/VoxCPM |
| Coqui AI TTS (Idiap) | XTTS v2 runtime / low-level inference API | https://github.com/idiap/coqui-ai-TTS |
| XTTS-v2 model kartı | XTTS model bilgisi ve model lisansı | https://huggingface.co/coqui/XTTS-v2 |
| coqui-xtts-v2-turkish-local | Hazır speaker keşfi, Türkçe yerel XTTS kullanım akışı ve hız kontrolü için referans | https://github.com/muhammedsaban/coqui-xtts-v2-turkish-local |
| Facebook MMS Turkish | Hafif Türkçe TTS motoru | https://huggingface.co/facebook/mms-tts-tur |
| DeepSpeed | Opsiyonel XTTS inference hızlandırma denemeleri | https://github.com/deepspeedai/DeepSpeed |
| PyTorch | CUDA/TTS inference çalışma zamanı | https://github.com/pytorch/pytorch |
| Hugging Face Hub | Model indirme/cache ve Windows cache uyumluluğu | https://github.com/huggingface/huggingface_hub |
| Hugging Face Transformers | MMS runtime ve model altyapısı | https://github.com/huggingface/transformers |
| FFmpeg | WAV birleştirme, AAC/M4B mux, chapter/cover gömme | https://github.com/FFmpeg/FFmpeg |
| Qt for Python / PySide6 | Masaüstü GUI | https://doc.qt.io/qtforpython-6/ |
| Beautiful Soup | EPUB XHTML metin çıkarımı | https://www.crummy.com/software/BeautifulSoup/ |

Bu liste bundan sonraki sürümlerde yeni bir upstream proje, model, örnek repo veya teknik kaynak kullanıldıkça README ile birlikte güncellenecektir.

## Lisanslar ve kullanım sınırları

Uygulama kodu MIT lisanslıdır. Model ağırlıkları repoya dahil edilmez; ilk kullanımda ilgili sağlayıcıdan indirilir.

| Motor | Model lisansı | Ticari kullanım |
|---|---|---|
| Trendyol-TTS | Model kartı MIT; temel VoxCPM2 Apache-2.0 | Model kartı/upstream açısından mümkün; veri ve kullanım koşullarını ayrıca kontrol edin |
| Coqui XTTS v2 | Coqui Public Model License (CPML) | **Hayır** |
| Facebook MMS Turkish | CC-BY-NC-4.0 | **Hayır** |

XTTS ve MMS için model lisansı onay kutusu GUI'de varsayılan olarak işaretlidir; kullanıcı isterse kaldırabilir. CLI da model lisansını varsayılan kabul eder ve `--no-accept-model-license` ile kapatılabilir. XTTS yalnızca "Referans sesten klonlama" modu seçildiğinde referans ses dosyası ve **ayrı, açık ses kullanım/klonlama izni** ister. "Hazır XTTS sesi" modunda referans WAV gerekmez.

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

EPUB seçilip analiz edildiğinde **İçindekiler / Seslendirilecek Bölümler** ağacı otomatik doldurulur. v0.1.11'den itibaren varsayılan seçim gerçek EPUB navigasyonunu izler: TOC'de temsil edilen spine belgeleri işaretli, yalnız spine'da bulunan fakat TOC'de görünmeyen okunabilir belgeler işaretsiz gelir.

Ağaçta üç sütun vardır: **İçerik**, **Karakter**, **Kaynak / statü**. `Kaynak / statü` alanında `TOC`, `Spine / TOC dışı` veya TOC bulunamayan EPUB'lar için `Spine (TOC yok)` görünür. Hızlı seçim düğmeleri: **TOC İçeriğini Seç**, **Tümünü Seç**, **Tümünü Kaldır**.

EPUB3 `nav.xhtml` ve EPUB2 NCX hiyerarşisi korunur. Bazı EPUB'larda birden fazla TOC alt başlığı aynı XHTML dosyasındaki farklı anchor'lara işaret eder; v0.1.x seslendirme birimini spine/XHTML dosyası olarak tuttuğu için bu tür alias başlıklar birlikte seçilip kaldırılır.

Manifest'te bulunup spine'a hiç eklenmemiş XHTML yardımcı belgeleri ve CSS/font/resim gibi kaynaklar seslendirme listesine sokulmaz. Kullanılabilir navigasyon TOC'si hiç yoksa uygulama tüm okunabilir spine metnini varsayılan seçerek geriye uyumlu davranır.

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
  --xtts-workers 2
```

XTTS 2 worker + DeepSpeed denemesi:

```bash
epub2m4b-cli convert kitap.epub kitap.m4b \
  --engine xtts \
  --device cuda \
  --xtts-voice-mode builtin \
  --xtts-speaker "Chandra MacFarland" \
  --xtts-performance-mode deepspeed \
  --xtts-workers 2
```

XTTS referans sesten klonlama ile dönüştürme:

```bash
epub2m4b-cli convert kitap.epub kitap.m4b \
  --engine xtts \
  --xtts-voice-mode clone \
  --xtts-speed 1.0 \
  --xtts-performance-mode optimized \
  --reference-wav sesim.wav \
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
9. v0.1.9 — VRAM-aware AutoTune 1-4 worker, LPT scheduler, host-thread contention azaltma, worker-bazli throughput
10. v0.1.10 — parent + subprocess chunk-boundary guard; oversized gorev tum worker havuzunu artik dusurmez
10. v0.2 — Calibre üzerinden MOBI/AZW3 ingestion ve anchor-seviyesinde alt bölüm ayırma
11. v0.3 — Türkçe metin normalizasyonu (sayı, tarih, kısaltma), telaffuz sözlüğü
12. v0.4 — Engine subprocess/izole environment desteği, daha güçlü resume/checkpoint
13. v0.5 — Bilingual segment routing ve çoklu karakter/ses profilleri
14. v1.0 — Paketlenmiş Windows uygulaması, otomatik güncelleme ve regression kalite testleri

### Windows: `WinError 1314` / Hugging Face symlink hatasi

v0.1.1 ile uygulama bu durumu otomatik yonetir. Windows Developer Mode acik veya uygulama yonetici olarak calisiyor olmak zorunda degildir. Trendyol-TTS ya da MMS modeli indirilirken Hugging Face cache'i sembolik bag olusturamiyorsa uygulama gercek dosya kopyasi kullanir. Daha once indirilmis model blob'lari varsa bunlar yeniden kullanilir.

v0.1.0'dan guncelliyorsaniz yeni surumu ayni sanal ortamda yeniden kurduktan sonra uygulamayi tamamen kapatip acin. Eski yarim cache'i elle silmek normalde gerekmez.

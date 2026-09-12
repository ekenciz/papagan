# Changelog

## 0.1.8 - 2026-09-12

- Windows'taki gercek v0.1.7 logunda ortaya cikan XTTS subprocess **circular import** hatasi duzeltildi. `python -m epub2m4b.tts.xtts_worker_process` artik `tts.__init__ -> registry -> core.__init__ -> pipeline -> tts.registry` dongusune girmiyor.
- `epub2m4b.core` ve `epub2m4b.tts` paket API'leri PEP 562 `__getattr__` ile lazy hale getirildi; mevcut `from epub2m4b.core import ConversionPipeline` ve `from epub2m4b.tts import create_engine` API'leri korunuyor.
- Gercek worker bootstrap yolu icin subprocess regresyon testi eklendi: bos stdin ile worker `main()` seviyesine ulasip kod 2 ile cikmali; import sirasinda kod 1 / `partially initialized module` hatasi artik kabul edilmiyor.
- DeepSpeed Windows kurulumu upstream'in onerilen `build_win.bat` yolunu dogrudan kullanacak sekilde sadeleştirildi; once basarisiz olacak duz `pip install` build denemesi kaldirildi.
- DeepSpeed surumu tekrarlanabilir Windows build'i icin `0.19.6`'ya sabitlendi.
- DeepSpeed kurulumu basarisiz olursa GUI otomatik olarak `Optimize` moda donuyor fakat secili 2/3/4 worker sayisini koruyor.
- Cekirdek test sonucu: **46/46 passed**; worker module boot smoke testi, compileall ve CLI smoke testi gecti.

## 0.1.7 - 2026-09-12

- Windows/Qt'ta 2-worker seciminin gercekte tek-worker fallback'e dusmesine yol acabilen `multiprocessing`/`ProcessPoolExecutor(spawn)` yolu kaldirildi.
- XTTS paralelligi kalici `python -m epub2m4b.tts.xtts_worker_process` subprocess'leri + JSON-lines IPC ile yeniden yazildi; model her worker'da bir kez yukleniyor.
- Worker secenekleri 1/2'den **1/2/3/4**'e cikarildi. 2 varsayilan; 3/4 worker 24 GB VRAM kartlarda deneysel.
- Worker startup hatalari artik worker bazinda traceback/log ile raporlaniyor; kismi startup durumunda `aktif/istenen` worker sayisi gorunuyor.
- Paralel benchmark da ayni subprocess havuzunu kullaniyor; benchmark ile gercek kitap donusumu artik ayni scheduler yolunu test ediyor.
- GPU telemetrisi NVML yoksa `nvidia-smi --query-gpu` ile cihaz-geneli GPU %, guc ve VRAM bilgisine geri dusuyor. `nvidia-smi` fallback'i performansi etkilememek icin en fazla 1 Hz ornekleniyor.
- GUI `VRAM cihaz` ile `worker PyTorch alloc` degerlerini ayiriyor; 1.8 GB process allocation artik 24 GB kartin toplam kullanimi gibi sunulmuyor.
- DeepSpeed Windows kurulumu VS2022 C++ Build Tools tespiti, kullanici onayli `winget` VCTools kurulumu ve Developer Command Prompt altinda build destegi kazandi.
- Normal DeepSpeed pip build'i basarisiz olursa kaynak sdist + upstream `build_win.bat` wheel yolu deneniyor.
- DeepSpeed kurulumu zorunlu degil; basarisiz olursa Optimize subprocess worker modu korunuyor.
- Yeni subprocess pool ve `nvidia-smi` parser regresyon testleri eklendi. Cekirdek test sonucu: **43/43 passed**.

## 0.1.6 - 2026-09-12

- XTTS icin CUDA'da **1/2 process worker** secimi eklendi; GUI ve CLI varsayilani 2 worker.
- Paralellik ayni model objesini thread'lerle paylasmak yerine `spawn` tabanli iki bagimsiz Python process'i ve iki bagimsiz XTTS model instance'i kullanir.
- Paralel worker'lar chunk'lari farkli sirada tamamlasa bile WAV/M4B sirasi orijinal kitap sirasi olarak korunur.
- Her paralel chunk icin sabit deterministic seed uretilir; worker atamasi audio cache davranisini degistirmez.
- 2-worker baslatma/inference/OOM hatasinda tamamlanmis WAV'lar korunup otomatik tek-worker fallback denenir.
- XTTS'ye opsiyonel **DeepSpeed** performans modu eklendi. Coqui GPT inference wrapper `use_deepspeed=True` ile yeniden kurulmaya calisilir; import/init basarisizsa `optimized` moda otomatik geri donulur.
- DeepSpeed normal XTTS dependency setinden ayrildi; GUI'ye ayri **DeepSpeed Kur/Onar** akisi eklendi.
- GUI'ye secili worker/mode ayarini model isinmasindan sonra olcen **Hiz Testi** eklendi; sonuc x-realtime ve 4.00x hedef yuzdesi olarak gosterilir.
- Pipeline ETA hesabi ilk 10 uncached parcada gizlenip isinma sonrasi aggregate throughput ile hesaplanacak sekilde stabilize edildi.
- Paralel modda `realtime_factor` aggregate wall-clock throughput'u, `worker_realtime_factor` ise worker basina inference verimini ayri raporlar.
- NVML telemetrisi cihaz toplam VRAM kullanimini (`vram_device_used_gb`) raporlar; iki worker'in PyTorch allocation degerleri ayrica toplanir.
- Cache anahtari `worker_count` scheduling secenegini yok sayar; 1/2 worker degisimi ayni audio ayarlarinda mevcut WAV cache'ini gecersiz kilmaz.
- Windows multiprocessing spawn icin `epub2m4b.__main__` guvenli `if __name__ == "__main__"` guard'i ile duzeltildi.
- DeepSpeed/parallel seed/cache/ETA/2-worker/fallback davranislari icin regresyon testleri eklendi. Cekirdek test sonucu: **40/40 passed**.

## 0.1.5 - 2026-09-11

- XTTS varsayilan calisma yolu `optimized` oldu; modelin low-level `inference()` API'si kullaniliyor.
- Built-in speaker conditioning tensorleri kitap boyunca cache'leniyor.
- Voice cloning modunda referans ses conditioning latentleri bir kez hesaplanip tekrar kullaniliyor.
- XTTS inference `torch.inference_mode()` altinda calisiyor.
- CUDA icin TF32 matmul/cudnn izni ve `float32_matmul_precision=high` etkinlestirildi.
- GUI'ye `Optimize` / `Uyumluluk` XTTS calisma modu secimi eklendi.
- Pipeline realtime factor, tahmini kalan sure, uretilen ses suresi ve cache istatistikleri uretiyor.
- GUI'ye canli performans satiri eklendi: GPU, GPU %, guc, VRAM, realtime factor, ETA.
- NVIDIA NVML telemetrisi icin opsiyonel `nvidia-ml-py` entegrasyonu eklendi.
- `--xtts-performance-mode` CLI secenegi eklendi.
- TOC arac cubugundaki yinelenen `Tumunu Sec` widget eklemesi temizlendi.
- XTTS conditioning cache ve pipeline telemetry icin yeni regresyon testleri eklendi.

## 0.1.4 - 2026-09-11

- XTTS Türkçe chunk hedefi `240` karakterden `220` karaktere indirildi. XTTS v2 tokenizer'ının Türkçe için upstream karakter uyarı sınırı `226` olduğundan artık pipeline güvenli marjla bu sınırın altında kalıyor.
- XTTS `synthesize()` katmanına savunmacı uzunluk kontrolü eklendi; pipeline dışından yanlışlıkla 220 karakterden uzun Türkçe parça gönderilirse modelin olası kırpılmış ses üretmesine izin vermek yerine açık hata veriliyor.
- `torch.jit.script is deprecated` FutureWarning mesajı yalnız XTTS/Coqui çalışma yolunda, yalnız ilgili PyTorch internal warning deseni için filtrelendi. Diğer FutureWarning mesajları gizlenmiyor.
- XTTS bağımlılık runtime smoke testine aynı dar kapsamlı warning filtresi eklendi.
- XTTS 226/220 limit ilişkisi ve uzun Türkçe paragraf chunking davranışı için regresyon testleri eklendi.
- v0.1.3'te eklenen EPUB TOC checkbox seçimi aynen korunuyor; tüm bölümler varsayılan seçili, kullanıcı istemediği bölümlerin işaretini kaldırabiliyor.

## 0.1.3 - 2026-09-11

- XTTS bağımlılık denetimi yalnızca `find_spec()` ile "kurulu" saymak yerine bilinen sürüm uyumsuzluklarını da kontrol edecek şekilde güçlendirildi.
- `coqui-tts==0.27.5` için `transformers>=4.57,<5` sabitlendi; böylece `TTS.api` importunu bozabilen Transformers 5.x kurulumu GUI'de tespit edilip tek tıkla onarılabiliyor.
- **Bağımlılıkları Kur/Onar** düğmesi bağımlılıklar "Hazır" görünse bile erişilebilir tutuldu.
- Bağımlılık kurulumu sonuna gerçek runtime smoke testi eklendi: XTTS için `torch`, `torchaudio`, `transformers` ve `from TTS.api import TTS` ayrı Python sürecinde doğrulanıyor.
- XTTS import hataları artık "paketler kurulu değil" genellemesi yerine asıl alt hata türünü ve mesajını kullanıcıya aktarıyor.
- EPUB3 `nav.xhtml` ve EPUB2 NCX içindekiler yapısı okunup spine bölümleriyle eşleştiriliyor.
- GUI'ye **İçindekiler / Seslendirilecek Bölümler** checkbox ağacı eklendi; bütün içerik varsayılan olarak seçili geliyor.
- Kullanıcı TOC içindeki işareti kaldırarak önsöz, teşekkür, kaynakça, dizin veya başka bölümleri TTS ve M4B chapter çıktısından hariç tutabiliyor.
- Aynı XHTML dosyasına işaret eden birden fazla TOC alias/anchor girdisi birlikte seçilip kaldırılıyor; v0.1.3 seçim granülerliği spine/XHTML belgesidir.
- Pipeline yalnız `selected_chapter_indices` içindeki bölümleri chunk'layıp seslendiriyor ve yalnız seçili bölümler için M4B chapter zamanları üretiyor.
- CLI'ya `--chapters 1,3-5,9` bölüm filtresi eklendi.
- EPUB TOC parse, seçili bölüm pipeline ve XTTS dependency pin regresyon testleri eklendi. Son çekirdek test sonucu: 24/24 geçti.

## 0.1.2 - 2026-09-11

- Coqui XTTS v2 artık iki ses modu destekliyor: model içindeki hazır speaker'lar ve referans sesten voice cloning.
- Hazır speaker listesi Coqui modelinden dinamik okunuyor; varsayılan/önerilen speaker `Chandra MacFarland`.
- XTTS konuşma hızı `0.70x-1.60x` aralığında ayarlanabilir hale getirildi.
- GUI'ye XTTS ses yöntemi, speaker dropdown, speaker yenileme, hız seçimi ve yaklaşık 10 saniyelik ses önizleme eklendi.
- Önizleme arka plan thread'inde üretiliyor ve PySide6 multimedia ile doğrudan oynatılıyor.
- Built-in speaker modunda referans WAV ve ses klonlama izni artık zorunlu değil; clone modunda mevcut güvenlik/onay akışı korunuyor.
- XTTS ses modu/speaker/hız değerleri cache anahtarına dahil edilerek yanlış WAV cache tekrar kullanımı önleniyor.
- CLI'ya `--xtts-voice-mode`, `--xtts-speaker` ve `--xtts-speed` seçenekleri eklendi.
- Speaker discovery yaklaşımı için MIT lisanslı `muhammedsaban/coqui-xtts-v2-turkish-local` projesi teknik referans olarak belgelendi.
- XTTS speaker discovery ve mod doğrulamaları için yeni regresyon testleri eklendi.

## 0.1.1 - 2026-09-10

- Windows'ta Hugging Face onbellegi model dosyalarini symlink ile snapshot klasorune baglarken olusan `WinError 1314` duzeltildi.
- Hugging Face Hub 1.9+ icin Windows'ta `HF_HUB_DISABLE_SYMLINKS=1` otomatik etkinlestiriliyor.
- Transformers 4.x ile gelen eski Hugging Face Hub surumleri icin yalnizca WinError 1314 durumunda symlink yerine gercek dosya kopyalayan dar kapsamli uyumluluk katmani eklendi.
- Trendyol-TTS ve MMS motorlari bu Windows uyumluluk katmanini kullaniyor.
- TTS motorlarina pipeline log callback'i aktariliyor; uyumluluk modu GUI logunda gorulebiliyor.
- Windows symlink fallback davranisi icin regresyon testleri eklendi.

## 0.1.0 - 2026-09-09

- Ilk calisan surum: EPUB parser, Turkce chunker, Trendyol-TTS/VoxCPM2, XTTS v2, MMS-TTS, cache/resume ve FFmpeg tabanli chapter/cover destekli M4B uretimi.
- PySide6 masaustu arayuzu ve Windows/Linux kurulum betikleri.
- Unit testler, GitHub Actions, README, mimari, yol haritasi ve lisans dokumantasyonu.

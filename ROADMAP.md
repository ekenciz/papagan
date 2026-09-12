# Roadmap

## v0.1.8 - mevcut iskelet

- XTTS Windows-safe kalici subprocess havuzu: 1-4 worker, dinamik scheduler ve acik fallback telemetrisi.
- DeepSpeed Windows Build Tools otomasyonu ve `nvidia-smi` cihaz VRAM fallback telemetrisi.
- Windows XTTS subprocess circular-import bootstrap duzeltmesi; lazy `core`/`tts` package API ve gercek `python -m` worker smoke testi.
- DeepSpeed 0.19.6 sabit Windows source build + upstream `build_win.bat` yolu.

- EPUB ingestion + metadata/cover
- EPUB3 nav ve EPUB2 NCX TOC parse/eşleme
- GUI'de varsayılan tümü seçili checkable bölüm/TOC ağacı
- Seçilmeyen spine bölümlerini TTS ve M4B chapter çıktısından hariç tutma
- Trendyol-TTS / VoxCPM2
- Coqui XTTS v2
- Facebook MMS Turkish
- PySide6 GUI
- chapter + cover M4B
- tek tık kurulum betikleri
- cache/resume temeli
- Windows Hugging Face `WinError 1314` symlink uyumluluk katmanı
- XTTS hazır speaker / voice-clone modları
- XTTS dinamik speaker listesi ve `Chandra MacFarland` varsayılanı
- XTTS `0.70x-1.60x` hız kontrolü
- kısa XTTS ses önizleme ve GUI içi oynatma
- XTTS dependency health check + `transformers>=4.57,<5` pin + runtime import smoke test
- XTTS Türkçe için upstream 226 karakter sınırının altında 220 karakter güvenli chunk hedefi
- XTTS çalışma yolunda yalnız bilinen `torch.jit.script` FutureWarning desenini filtreleme
- XTTS low-level optimize inference + built-in/clone conditioning cache
- CUDA TF32 optimizasyonu ve `torch.inference_mode()`
- GUI canli GPU/VRAM/guc + realtime factor + ETA telemetrisi
- klasik `TTS.api` uyumluluk modu
- XTTS 1-4 kalici subprocess worker; CUDA'da 2 worker varsayilan, aktif/istenen worker fallback telemetrisi
- opsiyonel DeepSpeed inference + ayri kur/onar akisi
- XTTS Hiz Testi benchmarki ve 4.00x hedef gostergesi
- device-wide NVML VRAM + worker allocation telemetrisi
- ilk 10 parcayi warmup sayan stabilize ETA/RTF hesabi

## v0.2

- Aynı XHTML içindeki TOC anchor'larını ayrı seçilebilir seslendirme segmentlerine bölme
- Calibre `ebook-convert` ile MOBI/AZW/AZW3 ingestion adapter
- chapter include/exclude seçimlerini proje/job manifestinde saklama
- daha ayrıntılı resume manifesti

## v0.3

- Türkçe text normalization: sayılar, tarihler, para birimleri, ölçüler, URL/e-posta
- kullanıcı telaffuz sözlüğü
- abbreviation sözlüğü
- bölüm önizleme ve metin düzeltme ekranı
- XTTS speaker favorileri ve kullanıcıya özel ses profilleri

## v0.4

- her TTS motoru için ayrı subprocess/venv
- benchmark gecmisini kaydetme ve GPU sinifina gore otomatik guvenli tuning profilleri
- 1-4 worker benchmark sonucuna gore otomatik profil secimi
- uygun upstream/runtime bulunursa CUDA Graph / compile tabanli ek XTTS optimizasyonlarini arastirma
- model manager: indirme, cache boyutu, silme, sürüm sabitleme
- checksum/model revision kaydı

## v0.5

- TR/EN segment language detection
- çok dilli voice routing
- karakter bazlı ses profilleri
- bölüm bazlı farklı ses seçimi

## v1.0

- PyInstaller/Nuitka Windows paketleme
- installer/uninstaller
- regression audio fixtures
- ASR tabanlı kalite doğrulama
- crash recovery ve kullanıcı dostu hata raporu

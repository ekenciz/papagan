# Third-party components and model licenses

Bu dosya hukuki tavsiye değildir; dağıtım/üretim öncesi lisans metinlerini doğrudan kaynaklarından doğrulayın.

## Trendyol-TTS

- Model: `Trendyol/Trendyol-TTS`
- Model kartı lisans metadata: MIT
- Base model: `openbmb/VoxCPM2`
- Kaynak: https://huggingface.co/Trendyol/Trendyol-TTS

Model kartı ayrıca özel Türkçe veri seti kullanıldığını ve kullanıcıların veri sahibi politikaları dahil ilgili kısıtları kontrol etmesi gerektiğini belirtir. Bu nedenle uygulama "model ticari kullanılabilir" bilgisini bir hukuki garanti olarak sunmaz.

## VoxCPM2

- Code/model weights: Apache-2.0
- https://github.com/OpenBMB/VoxCPM
- https://huggingface.co/openbmb/VoxCPM2

## Coqui XTTS v2

- Model license: Coqui Public Model License 1.0.0 (CPML)
- Non-commercial use only
- https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt

Runtime olarak kullanılan maintained fork `coqui-tts` MPL-2.0 lisanslıdır; model lisansı bundan ayrıdır.

v0.1.3 çalışma zamanı uyumluluğu için `coqui-tts==0.27.5` ile `transformers>=4.57,<5` aralığını sabitler. Bu sürüm pinleri lisans şartlarını değiştirmez; yalnız Python dependency compatibility içindir.

### `coqui-xtts-v2-turkish-local` teknik referansı

- Repository: https://github.com/muhammedsaban/coqui-xtts-v2-turkish-local
- Repository license: MIT
- Bu proje v0.1.2+ sürümlerinde XTTS hazır speaker keşfi, `Chandra MacFarland` önerisi ve hız kontrolü davranışlarını tasarlarken bu açık kaynak projeyi teknik referans olarak kullanır.
- Upstream projenin Gradio arayüzü veya uzun metni RAM içinde NumPy ile birleştiren pipeline'ı epub-to-m4b içine gömülmez. epub-to-m4b kendi PySide6, disk cache ve FFmpeg mimarisini korur.
- XTTS model ağırlıklarının CPML koşulları bu MIT lisanslı uygulama örneğinden bağımsızdır.

## Facebook MMS TTS Turkish

- Model: `facebook/mms-tts-tur`
- License: CC-BY-NC-4.0
- https://huggingface.co/facebook/mms-tts-tur

## PySide6 / Qt for Python

- Community edition: LGPLv3/GPLv3
- Commercial licensing option also exists
- https://doc.qt.io/qtforpython-6/

## Beautiful Soup 4

- MIT
- https://www.crummy.com/software/BeautifulSoup/

## FFmpeg

FFmpeg ayrı bir executable olarak çağrılır ve bu repoya binary olarak gömülmez. Kullanılan FFmpeg build'inin kendi lisans/codec yapılandırması dağıtım ortamında ayrıca değerlendirilmelidir.

## Python packages

Tam bağımlılık listesi ve sürüm aralıkları `pyproject.toml` içindedir. Model ağırlıkları bu repoda bulunmaz.

## NVIDIA Management Library Python bindings

- Package: `nvidia-ml-py` / import module `pynvml`
- License: BSD
- Purpose: optional GPU utilization, power and VRAM telemetry in the GUI
- https://pypi.org/project/nvidia-ml-py/

The telemetry integration is optional at runtime; synthesis does not depend on NVML being available.

## DeepSpeed (optional XTTS accelerator)

- Package: `deepspeed`
- License: Apache-2.0
- Version used by optional installer: `0.19.6`
- Purpose: optional XTTS GPT inference kernel/inference-engine acceleration in v0.1.6+; v0.1.7 adds Windows build-tool automation; v0.1.8 pins the source build and uses upstream `build_win.bat` directly
- https://github.com/deepspeedai/DeepSpeed
- https://pypi.org/project/deepspeed/

DeepSpeed is not a mandatory dependency and is not bundled. On Windows it may require Visual C++ Build Tools and a compatible CUDA/PyTorch build environment. Failure to install or initialize DeepSpeed does not disable XTTS; the application falls back to the normal optimized XTTS path.

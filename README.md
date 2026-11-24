# Mage-VL

<p align="center">
  <a href="https://huggingface.co/APLUX-Pandora/Mage-VL"><img src="https://img.shields.io/badge/Hugging%20Face-MAGE--VL-E3B800?style=for-the-badge&amp;logo=huggingface&amp;logoColor=FFD21E&amp;labelColor=555555" alt="Hugging Face: Mage-VL"></a>
  <a href="https://github.com/APLUX-Pandora/mage-vl-demo"><img src="https://img.shields.io/badge/GitHub-MAGE--VL-000000?style=for-the-badge&amp;logo=github&amp;logoColor=white&amp;labelColor=555555" alt="GitHub: Mage-VL"></a>
</p>

Mage-VL answers questions about text, images and video on a device NPU. The Web Demo keeps video playing while streaming an English summary for each independent 15- or 30-second window.

Based on [Mage-VL](https://huggingface.co/microsoft/Mage-VL).

**Demo recording** [Watch the demonstration](https://huggingface.co/APLUX-Pandora/Mage-VL/resolve/main/media/demo.mp4) · [Footage and recording credits](docs/recording.md)

<a id="1-create-an-environment-and-install"></a>

## 1. Install

Clone the Demo and enter its root directory:

```bash
git clone https://github.com/APLUX-Pandora/mage-vl-demo.git
cd mage-vl-demo
```

### Prepare the device

Use a compatible Linux device with Aidlux LMS and the required drivers, DSP firmware and BSP/FastRPC support. The SDK includes its QNN runtime libraries; no separate QNN installation or path configuration is required.

Check the activation:

```bash
sudo lms check
```

Continue only when it returns true.

Create the environment with a supported Python that has `venv` available. On Debian-based systems, install `python3-venv` if it is missing.

### Install the Demo and SDK

Use Python 3.10–3.12. Create and activate the Demo environment, then install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

This installs the SDK, the Web Demo and the Hugging Face CLI. To use only the SDK in your own application, see the [SDK installation](sdk/README.md#install).

<a id="2-download-the-model"></a>

## 2. Get the model

Download the shared files and one device target. The commands below use QCS8550; for another device, use the folder in the [targets table](docs/MODEL_SETUP.md#targets).

For a private model, run `hf auth login` first.

```bash
hf download APLUX-Pandora/Mage-VL --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Mage-VL --local-dir models --include "targets/qcs8550_qnn248/*"
```

<a id="4-start-the-web-demo"></a>

## 3. Run the Web Demo

```bash
bash demo/run.sh --models models --host 0.0.0.0 --port 8080
```

Open `http://<device-ip>:8080/` and choose the café clip or upload an H.264 MP4/MOV, then select **Understand video**. Stop it with `Ctrl+C`. See the [Web Demo guide](demo/README.md) for controls and shutdown.

<a id="3-try-the-sdk"></a>

## 4. Python Usage

In the same environment, from the Demo root:

```python
from pandora_mage_vl import LanguageModel

with LanguageModel.from_pretrained("models") as model:
    result = model.generate(
        [{
            "role": "user",
            "content": [
                {"type": "image", "image": "demo/samples/cafe-frame.png"},
                {"type": "text", "text": "Describe the visible people and their actions."},
            ],
        }],
        max_new_tokens=64,
        do_sample=False,
        repetition_penalty=1.0,
    )
    print(result.text, result.finish_reason)
```

The published model package defaults to 256 output tokens, greedy decoding and a repetition penalty of 1.0. This Demo example explicitly uses a 64-token budget. The Web Demo uses 48 tokens and 35 words per 15-second window, or 64 tokens and 60 words per 30-second window.

More in the [Python API](sdk/PYTHON_API.md) and [examples](examples/README.md).

<a id="api-reference"></a>

## Documentation

- [Model setup](docs/MODEL_SETUP.md): device requirements, targets, download and folder layout
- [Python API](sdk/PYTHON_API.md): every public class, method and parameter
- [C ABI](docs/C_ABI.md): native integration
- [Examples](examples/README.md): runnable Python and C examples
- [SDK setup](sdk/README.md): SDK-only installation and native payload
- [Rebuilding and replacing FFmpeg](sdk/ffmpeg/README.md): replace the two bundled FFmpeg variants
- [Runtime API](sdk/RUNTIME_API.md): device and execution settings
- [Video codec parameters](docs/video-codec/README.md): sampling and canvas budgets
- [Packet API](sdk/ADVANCED_VIDEO_API.md): timed video packet integration
- [Conversation reference](sdk/LM_REFERENCE.md): explicit cross-turn cache

## License

See [LICENSING.md](LICENSING.md), [NOTICE](NOTICE) and [LICENSES](LICENSES/). The café clip is a resized and re-encoded MEVA excerpt by Kitware Inc. and IARPA. Retain its [attribution and CC BY 4.0 terms](demo/media/DEPLOYMENT_SOURCE.md).

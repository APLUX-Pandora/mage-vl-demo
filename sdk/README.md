# Mage-VL SDK

The Mage-VL SDK handles text, image and video requests through its bundled native library.

## What's included

| Path | Content |
| --- | --- |
| `python/pandora_mage_vl/` | Python package (`from pandora_mage_vl import LanguageModel`) |
| `include/` | C header |
| `lib/` | Prebuilt native library with its QNN runtime |
| `SHA256SUMS` | Checksums of the shipped files |

`lib/` also contains `libmage_ffmpeg_pixel.so` and `libmage_ffmpeg_bitcost.so`. `wheels/` contains the bundled Runtime wheel.

<a id="runtime-environment"></a>
<a id="install-the-sdk"></a>

## Install

In your application's activated Python 3.10–3.12 environment, from the Demo root:

```bash
python -m pip install sdk/wheels/pandora_runtime-*.whl
python -m pip install ./sdk
```

The device must pass `sudo lms check`. The SDK does not install LMS or drivers and does not download models; see [Get the model](../README.md#2-get-the-model).

Use Linux AArch64 with native LMS available to the system loader. For C integration, keep `libmage_vl.so`, `libmage_ffmpeg_pixel.so`, `libmage_ffmpeg_bitcost.so` and the `qnn248/` directory together in the same directory and make the Runtime library available to the loader. See [Build and link](../docs/C_ABI.md#build-and-link). PyAV handles container demux and Pillow handles local images.

The checksum file covers the shipped C headers, native library and runtime files. To verify them, run `sha256sum -c SHA256SUMS` from `sdk/`.

<a id="python-usage"></a>

## Usage

Run from the Demo root after downloading the model.

```python
from pandora_mage_vl import LanguageModel

with LanguageModel.from_pretrained("models") as model:
    result = model.generate(
        [{
            "role": "user",
            "content": [
                {"type": "video", "video": "demo/samples/cafe15.mp4"},
                {"type": "text", "text": "Summarize the visible actions in this video."},
            ],
        }],
        max_new_tokens=64,
        do_sample=False,
        repetition_penalty=1.0,
        video_target_canvas=12,    # Total canvas budget for the video
        video_group_size=20,       # Candidate frames sampled per temporal group
        video_images_per_group=4,  # Canvases assembled per group
    )
    print(result.text)
```

The published model package defaults to 256 output tokens, greedy decoding and a repetition penalty of 1.0. This Demo example explicitly uses a 64-token budget.

Close active streams, caches, the model and any caller-owned Runtime in that order. An automatically created Runtime closes with the model.

## Documentation

- [Python API](PYTHON_API.md)
- [C ABI](../docs/C_ABI.md)
- [Examples](../examples/README.md)
- [Licensing](../LICENSING.md)
- [Runtime API](RUNTIME_API.md)
- [Conversation and cache reference](LM_REFERENCE.md#conversation-policy)

# Examples

## Overview

| Example | What it shows |
| --- | --- |
| [python/text_chat.py](python/text_chat.py) | Ask a text question. |
| [python/image_chat.py](python/image_chat.py) | Describe the bundled café frame. |
| [python/video_chat.py](python/video_chat.py) | Summarize the bundled café clip. |
| [python/kv_cache_chat.py](python/kv_cache_chat.py) | Reuse context across three text turns. |
| [c/image_chat.c](c/image_chat.c) | Describe an RGB image. |
| [c/cache_chat.c](c/cache_chat.c) | Reuse a native cache lease across three text turns. |

## Before you run

Complete [Install](../README.md#1-install) and [Get the model](../README.md#2-get-the-model). Run every command from the Demo root in the activated environment. Stop the Web Demo first; examples and the Web Demo share the NPU.

The Python examples take no arguments. Their model path, questions and sample media paths are set in the scripts. Each uses a 64-token greedy budget with a repetition penalty of 1.0. See the [sample media credits](../demo/media/README.md#bundled-example-media) for the image and video sources and license.

## Python examples

### text_chat.py

Ask what video understanding means.

```bash
python examples/python/text_chat.py
```

Output (excerpt)

```text
Video understanding refers to the process of analyzing and interpreting the content of a video to extract meaningful information.
```

### image_chat.py

Describe `demo/samples/cafe-frame.png`.

```bash
python examples/python/image_chat.py
```

Output

```text
A group of people are gathered in a room, with some standing and others sitting.
```

### video_chat.py

Summarize `demo/samples/cafe15.mp4`. The script puts the video before the instruction in the final user message.

```bash
python examples/python/video_chat.py
```

Output (excerpt)

```text
A man in a green jacket and blue jeans is standing in a room with a white tiled floor.
```

### kv_cache_chat.py

Pass each follow-up through a `DynamicCache` so the model can recall words from earlier turns. The Web Demo processes each video window independently. See [cache ownership and recovery](../sdk/LM_REFERENCE.md#conversation-policy).

```bash
python examples/python/kv_cache_chat.py
```

Output

```text
ACK
Alice
ORCHID
```

<a id="c-integration"></a>

## C example

### image_chat.c

The first command converts the bundled image to 512×288 interleaved RGB8 (442,368 bytes). The example describes the image with the SDK defaults for hardware settings and a 16-token greedy budget. Program errors go to standard error and return a nonzero exit status.

Build against the headers and prebuilt library in `sdk/`:

```bash
python -c 'from pathlib import Path; from PIL import Image; Path("image-512x288.rgb").write_bytes(Image.open("demo/samples/cafe-frame.png").convert("RGB").resize((512, 288)).tobytes())'
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -Wall -Wextra -Werror -I sdk/include examples/c/image_chat.c -L sdk/lib -L"$runtime_dir" \
  -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" \
  -lmage_vl -Wl,-rpath,'$ORIGIN/sdk/lib' -o image_chat
./image_chat models image-512x288.rgb
```

Output

```text
The image is a wide-angle security camera view of a busy indoor space, likely
```

### cache_chat.c

Reuse a cache lease across three built-in requests with a 64-token greedy budget per turn. Release the cache lease before closing the model.

```bash
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -Wall -Wextra -Werror -I sdk/include examples/c/cache_chat.c -L sdk/lib -L"$runtime_dir" \
  -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" \
  -lmage_vl -Wl,-rpath,'$ORIGIN/sdk/lib' -o cache_chat
./cache_chat models
```

Output (excerpt)

```text
ACK
KV: turn=1 retained=37 reused=0 actual=37
Alice
KV: turn=2 retained=58 reused=37 actual=58
ORCHID
KV: turn=3 retained=82 reused=58 actual=82
```

See [C ABI](../docs/C_ABI.md) for ownership and error handling.

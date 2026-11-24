# Python API

`pandora_mage_vl` · Text, image and video requests through the Mage-VL SDK.

<a id="1-quick-start"></a>

## Quick start

Complete [Install](../README.md#1-install) and [Model Setup](../docs/MODEL_SETUP.md) first. From the repository root, run `source .venv/bin/activate` in the shell, then use Python in that environment:

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

The context manager closes the model and its automatically created default Runtime.

<a id="2-interface-overview"></a>

## API overview

| Entry / complete public signature | Purpose | Return | Example |
| --- | --- | --- | --- |
| `LanguageModel(model_dir, *, runtime=None)` | Construct a local model; equivalent to the preferred factory below. | `LanguageModel` | Quick start above uses the factory. |
| `LanguageModel.from_pretrained(model_dir, *, runtime=None)` | Load a local package with one complete matching target. | `LanguageModel` | [Image](../examples/python/image_chat.py) |
| `model.generate(messages, *, max_new_tokens=None, do_sample=None, temperature=None, top_p=None, top_k=None, repetition_penalty=None, return_audio=False, past_key_values=None, video_target_canvas=None, video_group_size=None, video_images_per_group=None)` | Run a synchronous independent request or one explicit cache turn. | `GenerationResult` | [Text](../examples/python/text_chat.py), [image](../examples/python/image_chat.py), [video](../examples/python/video_chat.py) |
| `model.generate_stream(messages, *, max_new_tokens=None, do_sample=None, temperature=None, top_p=None, top_k=None, repetition_penalty=None, return_audio=False, past_key_values=None, video_target_canvas=None, video_group_size=None, video_images_per_group=None)` | Reserve one request and return its context-managed Unicode update iterator. Work advances during iteration. | `GenerationStream`, yielding `GenerationUpdate` | [Streaming example](#lifecycle) |
| `model.close()` | Checked synchronous release after streams and caches; repeated successful close is harmless. | `None` | Quick-start `with` calls it automatically. |
| `DynamicCache()` | Create an initially unbound, explicit native KV conversation lease. | `DynamicCache` | [Three-turn cache](../examples/python/kv_cache_chat.py) |
| `cache.status()` | Query committed native KV state after closing the stream. | `dict` | [Cache status fields](LM_REFERENCE.md#conversation-policy) |
| `cache.close()` | Release the lease before model teardown; idempotent after success. | `None` | Cache example's `with` block |
| `stream.close()` | Wait for serialized work and discard the reserved request; safe on early loop exit. | `None` | [Lifecycle](#lifecycle). |

Properties have no call arguments: `model.capabilities` returns a read-only capability record; `model.generation_config` is a read-only mapping with the loaded model’s default generation budget; `model.runtime` returns the Runtime supplied at load time, or `None` when the model owns its default settings. `stream.result` returns the final `GenerationResult` only after a terminal update (or confirmed cancellation of a started stream); before then it raises `BusyError`.

For an already loaded `model` in the same activated environment, query supported capabilities using the actual public properties:

```python
print(model.capabilities.input_types)            # ('text', 'image', 'video')
print(model.capabilities.output_types)           # ('text',)
print(model.capabilities.generation_parameters)  # ('max_new_tokens', 'do_sample', 'repetition_penalty')
print(dict(model.generation_config))
```

[All Python/C examples](../examples/README.md) are indexed separately. `VideoPacketModel(model_dir, *, runtime=None, max_output_tokens=256, max_output_words=60, do_sample=None, repetition_penalty=None)` is the lower-level timed-packet extension; its methods, parameters and outputs are specified in the separate [packet reference](ADVANCED_VIDEO_API.md). `resolve_model_dir(model_dir=None)` is a path-resolution helper returning `pathlib.Path`, also documented there. Hardware classes and their support limits belong to [Runtime](RUNTIME_API.md), not generation parameters.

<a id="3-parameters"></a>

## Parameters

### Loading and generation

The loading rows apply to the constructor and `from_pretrained`; generation rows apply to both `generate` and `generate_stream`. None is accepted only where explicitly stated.

| Parameter | Type | Required / default; omitted or None result | Valid values / range / unit / restriction |
| --- | --- | --- | --- |
| `model_dir` | `str`, `os.PathLike` or `None` | Positional argument required. Explicit `None` resolves `MAGE_VL_MODELS`, then `./models`, then one unique immediate child package. | Local package root containing `models.json`, common resources and one complete target for the detected SoC. Relative paths use the caller's working directory and expand `~`. Multiple compatible complete targets raise an error. [Path rules](../docs/MODEL_SETUP.md). |
| `runtime` | This SDK's `Runtime` or `None` | Optional keyword-only; omitted/None creates a model-owned default Runtime. | CPU `default`, burst, normal priority, device 0; activity RPC control latency internally 100 microseconds. A supplied Runtime is caller-owned and closes after its model. [Runtime values](RUNTIME_API.md). |
| `messages` | Nonempty `list` or `tuple` of message mappings | Required; None/empty is invalid. | Each message has exactly `role` and `content`; supported role values below. Optional initial system, alternating user/assistant, final user. Only explicit messages are supplied; no implicit history. |
| `role` | `str` | Required in every message. No None. | `system` = initial instruction; `user` = input/question; `assistant` = supplied previous answer. No other role. Missing initial system uses `You are a helpful assistant.` |
| `content` | `str` or nonempty ordered `list`/`tuple` of item mappings | Required per message; None invalid. | Text must be nonempty after stripping except visual-only final user input. No NUL, invalid UTF-8 or model control markers. Text pieces concatenate without inserted separators. Item values below. |
| Item `type` | `str` | Required per content item. No default/None. | `text` = text fragment, `image` = local JPEG/PNG, `video` = supported local video. Exactly `type` and its matching value field are permitted. `audio` is unsupported. |
| Item `text` | `str` | Required when type is `text`. | Included verbatim as message text; same text restrictions apply. For video, place instruction text after the video item in the final user content list. |
| Item `image` | `str` or `os.PathLike` | Required for type `image`; None invalid. | One local nonanimated JPEG/PNG, nonempty and at most 64 MiB / 16,777,216 pixels. RGB BICUBIC resize to 512×288, without EXIF rotation or padding. |
| Item `video` | `str` or `os.PathLike` | Required for type `video`; None invalid. | One finite local H.264 MP4/MOV, one video stream, valid presentation/decode timestamps and initial keyframe. H.265 and URLs unsupported. No fixed FPS or 15/30-second duration requirement; bounded compressed packets/timing metadata up to 256 MiB. See [codec parameters](../docs/video-codec/README.md). |
| `max_new_tokens` | `int` excluding bool, or `None` | Optional; omission or None uses the model package’s token budget. Demo examples explicitly use 64. | 1..4094; input, retained KV and output reserve must fit4096. No silent truncation. |
| `do_sample` | `bool` or `None` | Optional; omitted/None = **False**. | False is supported; True raises UnsupportedFeatureError. Invalid types raise InputError. |
| `temperature` | Number or `None` | Optional; omitted/None = **1.0**, inactive in greedy mode. | Positive finite value; explicit non-None requires do_sample=True. This adapter does not support sampling. |
| `top_p` | Number or `None` | Optional; omitted/None = **1.0**, inactive in greedy mode. | Finite value in(0,1]; explicit non-None requires do_sample=True. Sampling is unsupported. |
| `top_k` | `int` excluding bool, or `None` | Optional; omitted/None = **0** (no top-k filtering). | Nonnegative uint32; explicit0 is supplied, not omission. Non-None requires do_sample=True; sampling is unsupported. |
| `repetition_penalty` | Number or `None` | Optional; omitted/None = **1.0** (no extra penalty). | Positive finite value; this adapter supports explicit1.0 only. Other values raise UnsupportedFeatureError. |
| `return_audio` | `bool` | Optional; False. Omission returns `audio=None`; None is invalid. | Only False supported; True raises `UnsupportedFeatureError`. |
| `past_key_values` | This SDK's `DynamicCache` or `None` | Optional; omitted/None means an independent request. | First use binds one model/process. Cached follow-ups accept one new user message with text or one image/video plus text; no replayed history. See [cache contract](LM_REFERENCE.md#conversation-policy). |
| `video_target_canvas` | positive uint32 `int` excluding bool, or None | Optional; omitted/None = **12**. | Total canvas upper budget; divisible by `video_images_per_group` and must fit remaining context/memory. New video requests only. |
| `video_group_size` | positive uint32 `int` excluding bool, or None | Optional; omitted/None = **20**. | Candidate frames per temporal group, divisible by `video_images_per_group`; not source FPS. New video requests only. |
| `video_images_per_group` | positive uint32 `int` excluding bool, or None | Optional; omitted/None = **4**. | Configurable canvases per group, at most both counts above by the divisibility rule. New video requests only. |

See the separate [video codec README](../docs/video-codec/README.md) for calculation, actual-frame limits and a complete 15-second example.

Each request resolves an omitted or None token budget from the loaded model. Other defaults for this greedy adapter are False, 1.0, 1.0, 0 and 1.0. Explicit temperature/top_p/top_k require do_sample=True; greedy calls reject them even when their value is neutral. Sampling and nonneutral repetition penalties remain unsupported.

The Demo examples explicitly use max_new_tokens=64, do_sample=False and repetition_penalty=1.0. The Web uses48tokens/35words for15-second windows and64tokens/60words for30-second windows, with the same greedy/no-extra-penalty behavior. Its validated token/word controls are passed to the packet SDK. These application presets do not replace the SDK defaults. Codec12/20/4 and model tokenizer/chat/BOS/EOS/RoPE/capacity are unchanged.

**Language and dynamic choices:** Mage exposes no `language`, `speaker`, voice/style parameter or language-code/`auto` enumeration, and no speaker/language query API. Do not pass such keywords, including `language=None`. The Demo asks for English using its instruction text; this is a caller instruction, not an SDK language default. Use `model.capabilities` above for the supported input/output/control set, not invented language or voice lists.

One image or video is allowed, only in the final user message. Replayed media history, multiple new visuals in one request and audio input are unsupported. With explicit DynamicCache, previously committed visual context stays in native KV. For video understanding, place the video before instruction text; text-before-video can produce numeric/timestamp-only answers and is outside the supported scope. The adapter preserves order and does not reorder across messages. Image order remains supported as supplied. Video descriptions may misidentify actions or relationships; generated descriptions are not ground-truth annotations. The 4096-token context covers visual tokens and output reserve; this file interface does not concatenate separate window answers into one conversation.

<a id="4-results-and-cleanup"></a>

## Results and cleanup

### `GenerationResult`

The result contains only the new answer.

| Field / value | Meaning |
| --- | --- |
| `text: str` | Newly generated answer, without replaying the input. |
| `audio: None` | No generated speech/audio. |
| `finish_reason="stop"` | Natural model end-of-sequence. |
| `finish_reason="length"` | Output token budget reached; can truncate a sentence. It does not alone indicate a semantic error. |
| `finish_reason="cancelled"` | Confirmed cancellation of a started request. |
| `is_complete: bool` | True exactly when finish_reason is `stop`; not a content-accuracy certificate. |

Inference failures raise exceptions rather than success results. `GenerationUpdate(text, delta, finish_reason=None)` has accumulated `text`, newly emitted Unicode `delta`, and None while active or one of the terminal values above. Its `is_final` property is true once a finish reason exists.

### Errors

| Exception | Meaning / handling |
| --- | --- |
| `InputError` (also `ValueError`) | Invalid messages, media, type or context/output budget; correct the input. |
| `UnsupportedFeatureError` | Unsupported role, media capability or explicit control; do not silently retry with different defaults. |
| `BusyError` | Active request/cache, conflicting operation or a final result requested too early; respect owner/close order. |
| `ClosedError` | An operation on a closed model/stream/cache. |
| `InferenceError` | Model loading/execution/native failure or failure to produce a final result; close/recreate as needed. |

These derive from `GenerationError` (`RuntimeError`) and can include `native_code` and `operation`. Low-level packet/path/checked-cleanup calls can raise the public `SDKError` with `.status`; see [packet errors](ADVANCED_VIDEO_API.md#abort-reset-and-errors). Unknown Python keywords raise `TypeError`. A cleanup error is not successful release: preserve the failed owner, do not reuse it or repeatedly retry destruction. Native diagnostics describe the failure; they do not certify generated content.

### Lifecycle

Use the following loop with a loaded model and valid `messages` in the same activated environment. This example uses the loaded model’s default token budget.

```python
with model.generate_stream(messages) as stream:
    for update in stream:
        print(update.delta, end='', flush=True)
    result = stream.result
```

Updates contain Unicode `delta`, accumulated `text` and `finish_reason=None` while active. Exactly one terminal update is produced. Read `stream.result` after consuming the stream. Early `close()` waits for serialized native work and discards request state. Close streams, then caches, then models, and finally caller-owned Runtime. Do not close a model with a live cache or active stream.

### Concurrency

Requests/iteration on one model are serialized; conflicting concurrent requests are rejected. One native model per process is supported. Handles are process-local: initialize after spawn/exec, never reuse inherited handles after fork. Loading, status and teardown require caller synchronization. Ordinary requests have no implicit history.

<a id="5-advanced-usage"></a>

## Advanced

<a id="conversation-policy"></a>
Use `DynamicCache` only for explicit native KV reuse. First use binds it to one model/process; follow-up turns accept exactly one new user message, optionally with one new image or video. A natural EOS commits a reusable turn. Budget termination, cancellation or execution failure ends that chain. Input preflight errors leave the committed context unchanged. Close the cache before unrelated requests or model teardown. See [complete cache ownership, diagnostics and recovery](LM_REFERENCE.md#conversation-policy) and [three-turn example](../examples/python/kv_cache_chat.py).

The Web Demo deliberately uses independent windows without DynamicCache. That application choice does not remove native context support.

[Shared Runtime API](RUNTIME_API.md) covers hardware settings and explicit close order. [Packet API](ADVANCED_VIDEO_API.md) documents `VideoPacketModel` for timed packet input through this same native library; [C ABI](../docs/C_ABI.md) documents native integration. These extensions do not require Web or a second inference engine.

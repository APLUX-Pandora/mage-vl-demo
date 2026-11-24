# Mage-VL LM integration reference

Complete [Install](../README.md#1-install) and [Model Setup](../docs/MODEL_SETUP.md) first. Run Python from the repository root after `source .venv/bin/activate`. Fragments below that reference `model`, `messages` or `model_dir` assume those values have already been initialized. See the [Python quick start](PYTHON_API.md#1-quick-start) and [shared Runtime usage](RUNTIME_API.md#python-usage) for complete examples.

```python
from pandora_mage_vl import LanguageModel
model = LanguageModel.from_pretrained(model_dir, runtime=None)
```

`model_dir` is a local model package root. `runtime` is keyword-only. The package must contain common resources and exactly one complete SoC/QNN target described by `models.json`; ambiguous complete targets fail explicitly. See [model setup](../docs/MODEL_SETUP.md).

## Messages and generation

Call `generate()` without `max_new_tokens` to use the loaded model's output token budget. The streaming and cache examples below explicitly use the Demo preset of 64 tokens.

```python
result = model.generate(messages)
```

`generate_stream()` accepts the same parameters and returns a context-managed iterator. Messages are a nonempty ordered sequence of `{role, content}`. An optional first `system` precedes alternating user/assistant messages ending in `user`. Content is text or an ordered list of `{type: 'text', text: ...}`, `{type: 'image', image: local_path}` and `{type: 'video', video: local_path}`. The current adapter accepts one image or video in the final user message. Image content order is preserved. Video understanding supports the video item followed by instruction text in the same final user message. Text-before-video is outside this supported scope; it may produce numeric or timestamp-only answers. The adapter preserves supplied order and does not reorder across messages. Media history, multiple visuals and audio are explicitly unsupported by this adapter.

Images are decoded from supported local image files and prepared at 512×288. A single video request accepts one finite local H.264 MP4/MOV with timestamped packets. FPS and duration are not fixed. See [video codec parameters](../docs/video-codec/README.md) for the default 12/20/4 budget, limits and a 15-second example. Paced independent-window playback remains in the public packet extension used by the Demo. The native model context is 4096 tokens, including visual tokens and the requested output reserve. Over-budget requests fail rather than silently truncating history.

Text-only requests are supported. `model.capabilities` is read-only and describes text/image/video input, text output, streaming, the implemented generation parameters and explicit native cross-turn cache support.

An omitted or None max_new_tokens uses the loaded model’s token budget for each request. Other defaults for the greedy adapter are do_sample False, temperature 1.0, top_p 1.0, top_k 0 and repetition_penalty 1.0. Explicit sampling fields require do_sampleTrue; this Mage adapter rejects sampling as unsupported. It supports explicit greedy and repetition_penalty1.0 only. The Demo examples pass64tokens/False/1.0 explicitly; Web passes its validated48/35 or64/60 token/word preset. See [all parameter ranges](PYTHON_API.md#3-parameters). Model tokenizer/chat and capacity remain SDK-owned. `return_audio=True` is unsupported.


## Results and streaming

`GenerationResult(text, audio, finish_reason)` contains only the new answer. `audio` is `None`. `finish_reason` is `stop`, `length` or `cancelled`, derived from native completion, the actual output budget or confirmed cancellation.

```python
with model.generate_stream(messages, max_new_tokens=64, do_sample=False, repetition_penalty=1.0) as stream:
    for update in stream:
        print(update.delta, end='', flush=True)
    result = stream.result
```

Updates expose Unicode `delta`, accumulated `text` and `finish_reason` (`None` while active). A completed stream provides one terminal update. Early `close()` waits for serialized native work and discards request state. Close the stream before model teardown. Concurrent iteration/requests are rejected; one model handle per process is supported.

## Conversation policy

Ordinary calls use only their explicit input messages and reset their request context. An application can supply textual history on each independent request. To reuse native KV across turns, create this SDK's `DynamicCache()` and pass it through `past_key_values`:

```python
from pandora_mage_vl import DynamicCache, LanguageModel

with LanguageModel.from_pretrained('models') as model, DynamicCache() as cache:
    for question in (
        'My name is Alice and my secret word is ORCHID. Reply only ACK.',
        'What is my name? Reply only the name.',
        'What is my secret word? Reply only the word.',
    ):
        result = model.generate([{'role': 'user', 'content': question}],
                                past_key_values=cache, max_new_tokens=64, do_sample=False, repetition_penalty=1.0)
        print(result.text)
        if result.finish_reason != 'stop':
            break
```

The first cached turn accepts text, one image, or one supported complete video, with an optional system message. Subsequent turns accept exactly one new user message, with text or one new image/video plus text. Replaying full history into an existing cache is unsupported. The SDK maintains native template boundaries and positions; it does not replay past text or rerun past visual encoding. The 4096-token limit includes all retained tokens, new input and output reserve. Preflight input/budget errors leave the committed native context unchanged.

A cache binds to one model instance and process on first use. One cache lease owns the model at a time; close that cache before starting an unrelated ordinary request or conversation. Concurrent streams and model close with a live cache fail explicitly. Wrong-model, inherited-process, closed and invalidated cache objects are rejected. Close an active stream first, then its cache, model and external Runtime. `close()` is idempotent.

Natural EOS commits a reusable turn. Output-budget termination, cancellation or execution failure invalidates that chain and releases its native KV lease. Start a new `DynamicCache` for another conversation; preserve any application history separately if recovery is needed. An execution failure can require reloading the model. An unstarted stream that is closed also ends its reserved cache chain.

`cache.status()` is an advanced diagnostic, queried only after closing the stream. It returns `valid`, `cache_id`, `cached_tokens`, `backend_tokens`, `turns`, `reused_tokens`, `last_prompt_tokens` and `last_generated_tokens`. `backend_tokens` comes from Genie's actual context occupancy. Invalidated status may retain the last completed-turn metadata, while `valid=False` and `backend_tokens=0` identify the released state. A closed cache rejects status queries.

The Demo intentionally disables cross-window conversational memory: every 15-second video window is understood independently. It uses no DynamicCache. This does not disable within-request KV/prefill processing and does not mean Mage-VL lacks context support.

## Errors and release

`InputError` reports invalid message structures, media paths and budgets. `UnsupportedFeatureError` reports unsupported capabilities or explicit parameters. `BusyError` reports an active request or conflicting owner operation. `ClosedError` reports closed objects, and `InferenceError` reports execution failures. Errors may include `native_code` and `operation`.

```python
with LanguageModel.from_pretrained('models') as model:
    print(model.capabilities)
```

No public `sys.path` modification or repository-local module import is required after installation. Models, streams and Runtime handles are process-local; initialize after spawn/exec and do not reuse inherited objects after fork.

## Finite-video packet extension

`VideoPacketModel(model_dir, *, runtime=None, max_output_tokens=256, max_output_words=60, do_sample=None, repetition_penalty=None)` is a public extension for timed packet input. It delegates to the same native library as `LanguageModel`. It exposes `open_stream`, `enqueue`, `feed`, `next`, `finish_input`, `read_text`, `read_event`, `stats`, `info`, `abort`, `reset` and `close`. The Web application uses it for packet delivery, scheduling and playback. Packet plans are independent contexts; no generated summary is appended to a later window. See the [packet API reference](ADVANCED_VIDEO_API.md), complete [C ABI packet structures](../docs/C_ABI.md) and [Demo implementation](../demo/server.py) for the matching packet facts. This extension does not implement a second model or bypass the SDK.

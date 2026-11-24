# Finite-video packet API

The standard video-first understanding route encodes the sampled canvases with repeated vision calls, concatenates their visual embeddings, then supplies the instruction. The Web Demo uses this packet route. It does not support arbitrary media/text or cross-message reordering.

The installed `pandora_mage_vl` package calls model C ABI 1. Complete [SDK installation](README.md#install-the-sdk), then activate the same `.venv` in the application shell before running Python. Use the installed package without sys.path or PYTHONPATH changes.

```python
from pandora_mage_vl import VideoPacketModel, SDKError, WouldBlock
```

## Process, library and package selection

`VideoPacketModel(..., runtime=None)` accepts the same provider-local [Runtime](RUNTIME_API.md) as LanguageModel. Defaults are burst/normal. Runtime options and unsupported values are documented there. Close caller-owned Runtime after the engine. Inherited engine/Runtime handles cannot be used after fork.


`resolve_model_dir(model_dir=None) -> pathlib.Path` accepts a string/Path package root, then `MAGE_VL_MODELS`, then the caller's `./models/models.json`, then exactly one immediate child package with models.json. Explicit relative paths use the current working directory; `~` is expanded. Missing/ambiguous/invalid paths raise `SDKError(-2, ...)` with the searched location. It checks models.json existence, not model hashes or hardware. See [layout](../models/README.md).

## Construction and ownership

```text
VideoPacketModel(model_dir, *, runtime=None,
                 max_output_tokens=256, max_output_words=60,
                 do_sample=None, repetition_penalty=None)
```

`model_dir` selects the local models.json package root. Output limits are positive integers; native model/context and queue budgets apply. The generic token default is256; the independent packet word limit is60. Omitted/None do_sample isFalse and repetition_penalty is1.0; explicitFalse/1.0 are supported, other modes are rejected. Web explicitly passes its confirmed48tokens/35words (15s) or64tokens/60words (30s) plus do_sample=False/repetition_penalty=1.0. These are application presets. Use one owner per packet transaction, serialize feed/next/drain/abort/reset/close, and do not use handles across fork. `with VideoPacketModel(...) as model:` closes synchronously. A caller-supplied Runtime is closed after the model. There is no public library override or process-wide protection switch on this constructor.

The installed native payload is used by default. `MAGE_VL_LIBRARY` is a diagnostic override that must name the matching complete native build; an explicit override does not fall back. It is not required for ordinary installation.

## Stream and segment input

`open_stream(metadata, extradata, keyframes, *, frame_times=None, duration=None) -> None`

- `metadata` is a dictionary of `StreamInfo` fields below; omit pointer/count fields because the method supplies those. Unknown field names raise `TypeError`. Values must fit the C field widths; this thin binding is not a general-purpose integer coercion validator.
- `extradata` is a bytes-like buffer containing original codec extradata (e.g. MP4 avcC); `keyframes` is a sequence of presentation-frame integer indices. The native call copies both before return.
- Requires EMPTY state; finite H.264 codec=1, positive dimensions/rate/time base/frame count, nonempty extradata and keyframes. Keyframes are sorted unique, begin at 0 and are below frame count. Input errors are native SDK errors.

| Metadata field | C representation / meaning |
| --- | --- |
| `codec` | uint32, 1 for H.264 |
| `width`, `height` | int32, positive source dimensions |
| `fps_num`, `fps_den` | int32 rational frame rate |
| `time_base_num`, `time_base_den` | int32 packet timestamp time base |
| `stream_start_pts` | int64 source start PTS |
| `frame_count` | int64 finite presentation-frame count |
| `color_primaries`, `color_transfer`, `color_matrix` | int32 H.264/ISO values; 2 means unspecified |
| `full_range` | int32: -1 unspecified, 0 limited, 1 full |
| `sample_aspect_num`, `sample_aspect_den` | int32 source sample aspect ratio |

`enqueue(segment_id, first_frame, frame_count, question, *, group_frames=500, sampled_frames_per_group=40, canvases_per_group=4) -> None`

`question` is a nonempty NUL-free UTF-8 Python string; it is copied by native enqueue. Pass valid text without embedded NUL because the native field is a C string. `segment_id` must be a unique uint64 below `NO_SEGMENT`, `first_frame` a nonnegative int64, and `frame_count` a positive int64. Native intervals start at 0, are contiguous/in source bounds, and must be enqueued before the decoder reaches their frames. Frame count must be a multiple of positive uint32 `group_frames`; samples are uint32 in [1, group_frames]; canvases are positive uint32 within context/memory budgets. Package/context and pending-buffer budgets also apply. IDs remain reserved until reset. A full plan queue raises `WouldBlock` without consuming the plan.

The legacy `enqueue` defaults describe a 30-second fixed-frame plan at 50 FPS: 1500 frames, groups 500/40/4. They remain available for callers explicitly using frame plans. Web uses the timestamp-driven method below instead; its default is 15 seconds, 12/20/4 and 35 words/48 tokens. Source FPS and tail length do not change the default budgets.

### Timestamp-driven windows (Web default)

Public `VideoSource(path, max_bytes=256*1024*1024)` demuxes finite H.264 MP4/MOV input without decoding/re-encoding pixels. It exposes `metadata`, `extradata`, `keyframes`, `packets`, `frame_times`, `duration`, `has_audio`, and `fingerprint()`. Packet records expose `data,pts,dts,duration,flags,due`; `due` is normalized DTS time for original-order delivery. Frame times are normalized presentation times in display order. VFR and non-50-FPS sources are supported; duplicate/missing PTS, missing DTS, inconsistent frame counts and a missing initial keyframe fail explicitly. Audio is not model input.

Pass **both** `frame_times=source.frame_times` and `duration=source.duration` to `open_stream` to select timed mode. The native SDK copies the strictly increasing table, requires its first time to be 0, one entry per presentation frame, and finite duration greater than the last time. Timestamp buffers are bounded. A retained conversation cache cannot own a timed independent-window transaction.

```text
enqueue_window(segment_id, start_s, end_s, question, *,
               video_target_canvas=None, video_group_size=None,
               video_images_per_group=None) -> None
next(*, media_time=None) -> int
```

Omitted/None codec controls resolve to **12/20/4** independently per window. Windows are unique-ID contiguous `[start_s,end_s)` intervals starting at 0 and bounded by duration. At least one source frame is required in each window. Each window uses equal-duration groups based on its own actual duration. Short groups use fewer candidates/canvases; see [calculation and 15s/tail examples](../docs/video-codec/README.md). Native integer, memory, queue and context checks apply before plan acceptance. `WouldBlock` consumes no plan. Enqueue before delivering packets that decode the window's frames, allowing for B-frame decode-order lookahead. Do not mix legacy `enqueue` with timed mode; reset first.

With a finite, monotonic `media_time` in `[0,duration]`, `next` may prefill earlier groups but waits for a window's actual end before processing its final group and starting its summary. Omit `media_time` for explicit unpaced/offline processing; it does not impose playback waits. Both forms serialize synchronous model work and can block. Feed packets in original DTS order; preserve decoder references across windows and flush at EOF, then continue next/drain until every window finishes. Each completed independent window resets language KV, retaining the loaded model.

```python
from pandora_mage_vl import VideoSource, VideoPacketModel

source = VideoSource("demo/samples/cafe15.mp4")
with VideoPacketModel("models", max_output_tokens=48, max_output_words=35,
                      do_sample=False, repetition_penalty=1.0) as model:
    model.open_stream(source.metadata, source.extradata, source.keyframes,
                      frame_times=source.frame_times, duration=source.duration)
    model.enqueue_window(0, 0.0, source.duration, "Describe the visible actions.")
    # Application owns DTS-paced packet feed, next(media_time=...), and draining.
    # See demo/policy.py for the complete playback/UTF-8/EOF/stop loop.
```

This snippet shows setup only; `demo/policy.py` is the complete loop and uses public SDK methods. C callers use additive `mage_vl_open_timed_stream`, `mage_vl_time_window`, `mage_vl_enqueue_window`, and `mage_vl_next_at`. Build these calls with the headers and native library from the same SDK.

`feed(data, pts, dts, duration, flags) -> None` copies original compressed packet bytes from a bytes-like buffer. `pts`, `dts`, `duration` are int64 in the stream time base; `flags` is uint32 0 or 1 (key packet). Preserve source packet framing, timing and decode order. The original data is copied before return. On `WouldBlock`, **nothing was consumed**: advance model work, drain outputs, and retry the exact same packet. Do not drop or skip it. Empty/oversized packets or unknown flags raise `SDKError`.

`finish_input() -> None` flushes decoder EOF once; repeat in EOF is idempotent. It requires an opened stream. Then continue advancing/draining to completed windows. Decoder/model failures can put the stream in FAILED; reset before reuse.

## Advance and outputs

`next() -> int` synchronously advances model work/generation, returning new queued text/event count, or 0 when no new output is available. It can include a long prefill: it is not a nonblocking poll. Zero alone does not prove all windows completed. Track events, source EOF and application scheduling. `WouldBlock` may require output draining.

`read_text(capacity=4096) -> tuple[int, bytes] | None` returns `(segment_id, raw_bytes)` or None when empty. Positive integer capacity is bounded by INT32_MAX; invalid capacity raises `ValueError`. One read belongs to one segment, can be short and can split UTF-8. Keep a separate incremental UTF-8 decoder per segment; do not decode each chunk independently. Reads perform no model work. A short read retains the suffix.

`read_event() -> dict | None` returns one event or None; no model execution. Text/event queues are independent, so completion can be observed before all text has been read. Drain both.

`info() -> dict` gives:

| Keys | Meaning |
| --- | --- |
| `abi_version`, `context_tokens`, `embedding_elements`, `visual_tokens_per_canvas`, `prefill_alignment_tokens` | ABI/profile: 1 / 4096 / 2560 / 144 / 128 |
| `queued_segments` | Current plan count, including any finished plan not yet retired by next |
| `stream_state` | 0 EMPTY, 1 OPEN, 2 EOF, 3 FAILED |
| `active_segment_id` | Oldest plan ID, or `NO_SEGMENT` |
| `generation_active`, `input_finished` | Integer boolean flags |

`stats() -> dict` contains counters `accepted_packets`, `decoded_pixel_frames`, `decoded_bitcost_frames`, `sampled_frames`, `canvases`, `vision_calls`, `prefill_calls`, `prompt_tokens`, `generated_tokens`, `emitted_text_bytes`, `completed_segments`; and floating millisecond accumulators `pixel_decode_ms`, `bitcost_decode_ms`, `codec_host_ms`, `vision_host_ms`, `vision_invoke_ms`, `prompt_embedding_ms`, `prefill_ms`, `decode_ms`. Prompt tokens count actual aggregate submitted prefix/tail tokens; generated tokens may include backend control tokens. Reset clears these statistics. They do not include browser/network latency.

Events have integer keys `type`, `segment_id`, `stop_reason`, `prompt_tokens`, `generated_tokens`, `emitted_words`:

| Event type | Meaning |
| --- | --- |
| 1 | Segment ready |
| 2 | Summary started |
| 3 | Summary finished |
| 4 | Segment cancelled |

Stop reasons: 0 none, 1 EOS, 2 token cap, 3 word cap, 4 cancelled.

## Abort, reset and errors

`abort(segment_id) -> None` cancels a pending/active unfinished segment between calls. Preserve a valid uint64 ID; negative/wrapped values are not meaningful. Generated text remains available and later plans and decoder continuity survive. Drain the output and call next as needed until the cancellation event arrives. Completed/unknown IDs fail with status -5. It cannot interrupt a concurrently executing native call.

`reset() -> None` synchronously clears stream/decoder/KV/plans/text/events/statistics and returns EMPTY while keeping models loaded. Stop the current application's feed transaction first. It discards queued output: drain anything needed before reset.

`SDKError(status, message)` is a `RuntimeError`; `.status` holds the negative native status. `WouldBlock` subclasses it for -7. Native status values: -1 argument, -2 model/package, -3 decode, -4 NPU, -5 state, -6 internal, -7 backpressure, -8 unsupported, -9 context budget, -10 busy. Python type/conversion/IO errors are not converted into SDKError. Do not catch every SDKError as retryable.

`NO_SEGMENT` in native output is `2**64 - 1`. Public Python callers use packet methods rather than private ctypes structures. C widths and layouts are authoritative in [mage_vl.h](include/mage_vl.h).

For a complete packet scheduling and UTF-8 example see [examples](../examples/README.md), `demo/source.py` (container demux) and `demo/policy.py` (scheduling/output ownership). Neither contains native model algorithms.

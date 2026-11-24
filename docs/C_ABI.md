# C ABI

`sdk/include/mage_vl.h` · `sdk/lib/libmage_vl.so` · Native text, image and packet inference.

## Build and link

From the Demo root, compile against the shipped header and library; the library carries its QNN runtime:

Install the SDK and its bundled Runtime wheel in the active environment as described in [SDK installation](../sdk/README.md#install).

```bash
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -I sdk/include your_app.c -L sdk/lib -L"$runtime_dir" \
  -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" \
  -lmage_vl -Wl,-rpath,'$ORIGIN/sdk/lib' -o your_app
```

Use the matching headers and library. For custom hardware settings, include [pandora_runtime.h](../sdk/include/pandora_runtime.h) and use the configuration and status layouts it declares. See [Runtime](../sdk/RUNTIME_API.md).

Use Linux AArch64. Keep `libmage_vl.so`, `libmage_ffmpeg_pixel.so`, `libmage_ffmpeg_bitcost.so` and the `qnn248/` directory together in the same directory. For a deployment without Python, extract `libpandora_runtime.so.5` from the bundled wheel and make it available to the system loader. The device requires native LMS and a compatible BSP, drivers, FastRPC and DSP firmware. If your application demuxes containers, link the demux library it uses. See [device requirements](MODEL_SETUP.md#device-requirements).

## Lifecycle

```text
initialize options → create → configure → submit input → advance and drain → reset or destroy
```

### Packet scheduling and shutdown

1. Initialize model options and create the model.
2. Open stream, enqueue contiguous windows ahead of their packets. The client chooses intervals; SDK chooses sampling/keyframe adjustment and model tensors.
3. Feed original packets in decode order. On WOULD_BLOCK do not unref/replace the packet: next/drain, retire finished plans and retry the same bytes. Bound no-progress retries and report incompatible resource budgets rather than dropping data.
4. Advance next and drain both queues. Use per-segment incremental UTF8 decoding or write raw bytes. Plan further windows when slots become available. Do not feed a future interval before its plan exists.
5. At real source EOF call finish_input; advance/drain until all expected windows finish and queues empty. Zero from next is insufficient as a completion condition.
6. On stop, stop new input, wait for active calls, optionally serialized abort/reset, then destroy. Release packet/container/output resources on every path. Never destroy from a signal handler or another thread while native work is active.

If creation fails with an empty owner slot, the slot stays empty. Copy the diagnostic and correct the cause before retrying. On checked cleanup failure the owner remains available for cleanup. Abort runs between native calls.

## Functions

| Function | Parameters and return / error |
| --- | --- |
| `int32_t mage_vl_prepare_process(void)` | Returns UNSUPPORTED; use create_status/create_error to inspect initialization errors. |
| `int32_t mage_vl_default_options(mage_vl_options *options)` | Non-NULL writable output; initializes every field, size and ABI. 0 or -1 for NULL. |
| `mage_vl_engine *mage_vl_create(const char *model_dir, const mage_vl_options *options)` | Nonempty models.json package-root path (relative to cwd if relative) and initialized options; returned owned pointer or NULL. No automatic discovery in C. On NULL read create_status/create_error on the same thread. Partial construction unwinds native owners. |
| `void mage_vl_destroy(mage_vl_engine *engine)` | Releases all model/context/decoder/queue resources. NULL is allowed; reusing/destroying an already freed non-NULL pointer is invalid. Wait for all users/calls first. |
| `int32_t mage_vl_create_status(void)` | Last prepare/create status for this thread; 0 or negative. |
| `const char *mage_vl_create_error(void)` | Borrowed thread-local NUL-terminated diagnostic; copy before another prepare/create on that thread or thread exit. Do not free. |
| `const char *mage_vl_last_error(const mage_vl_engine *engine)` | Borrowed diagnostic, or static invalid-handle text for NULL. Copy before another call changes the error or before destroy. Do not free. |
| `int32_t mage_vl_get_info(const mage_vl_engine *engine, mage_vl_info *info)` | Initialized writable output; 0 or negative. |
| `int32_t mage_vl_get_stats(const mage_vl_engine *engine, mage_vl_stats *stats)` | Initialized writable output; 0 or negative. |
| `int32_t mage_vl_open_stream(mage_vl_engine *engine, const mage_vl_stream_info *stream)` | Requires EMPTY, validates metadata; copies extradata/keyframe arrays. 0 or negative. |
| `int32_t mage_vl_enqueue_segment(mage_vl_engine *engine, const mage_vl_segment *segment)` | Requires OPEN, valid contiguous future window and copied question. 0, -7 queue full (not consumed), or another negative error. |
| `int32_t mage_vl_feed_packet(mage_vl_engine *engine, const mage_vl_packet *packet)` | Requires OPEN; consumes/copies the full original packet or none. 0, -7 backpressure, or another negative error. |
| `int32_t mage_vl_finish_input(mage_vl_engine *engine)` | Flushes EOF once, idempotent in EOF; invalid when unopened. 0 or negative. |
| `int32_t mage_vl_next(mage_vl_engine *engine)` | Synchronously advances model work/generation; number of new text/event items, 0 when no new item, or negative. May block for prefill; zero alone is not completion. |
| `int32_t mage_vl_read_text(mage_vl_engine *engine, uint8_t *dst, size_t capacity, mage_vl_text_info *info)` | Copies up to capacity bytes from one segment; count excludes NUL (no terminator added), 0 if empty/capacity zero, or negative. capacity <= INT32_MAX; dst may be NULL only for zero capacity. Sets segment_id when text is returned. Short read retains suffix; chunks can split UTF-8. |
| `int32_t mage_vl_read_event(mage_vl_engine *engine, mage_vl_event *event)` | Copies one event: 1, empty: 0, error: negative. No model work. |
| `int32_t mage_vl_abort(mage_vl_engine *engine, uint64_t segment_id)` | Serialized cancellation of pending unfinished window. Retains generated text and keeps later windows and decoder continuity. Drain the output and call next as needed until the CANCELLED event arrives. 0 or negative; not a concurrent interrupt. |
| `int32_t mage_vl_reset(mage_vl_engine *engine)` | Clears decoder/stream/KV/plans/text/events/stats while retaining loaded models; returns EMPTY. 0 or negative. |

| Function | Purpose | Returns |
| --- | --- | --- |
| `mage_vl_create_with_runtime` | Load a model into an empty owned output slot with an optional Runtime. | `0` or a negative status. |
| `mage_vl_destroy_owned` | Release the model and clear the owner slot on success. | `0` or a negative status. |
| `mage_vl_configure_request` | Configure one independent request. | `0` or a negative status. |
| `mage_vl_get_default_max_new_tokens` | Read the loaded model’s default generation token budget. | `0` on success, with a writable uint32 output. |
| `mage_vl_start_image_rgb` | Start image input with tightly packed RGB8. | `0` or a negative status. |
| `mage_vl_open_timed_stream` | Open a stream with a presentation timestamp for each frame. | `0` or a negative status. |
| `mage_vl_enqueue_window` | Queue a contiguous time interval before feeding its packets. | `0` or a negative status. |
| `mage_vl_next_at` | Advance a timed stream to the requested playback position. | Number of new output items or a negative status. |
| `mage_vl_configure_packet_generation` | Configure generation for an idle packet model. | `0` or a negative status. |

### Options and public structures

Options field defaults/ranges (initialized by `mage_vl_default_options`):

The default packet creation option is 256 output tokens. Web and example applications explicitly pass their own budgets; a 64-token application preset does not change this default.

| Field | C type | Default / contract |
| --- | --- | --- |
| `struct_size`, `abi_version` | uint32 | sizeof struct, 1; initialized by default_options |
| `max_output_tokens` | uint32 | 256, positive and <4096 context |
| `max_output_words` | uint32 | 60, positive whitespace word cap |
| `max_queued_segments` | uint32 | 2, at least 2 |
| `max_pending_bytes` | uint64 | 256 MiB, positive and enough for one segment's required media/model buffers |
| `max_output_queue_bytes` | uint64 | 64 KiB, at least 4096; drain output before producing more |
| `reserved0`, `reserved[8]` | uint32 / uint64 array | Zero |

All following structures have a leading uint32 struct_size and trailing reserved fields as declared in the header. Zero them; the following table documents the meaningful fields without duplicating their memory layout:

| Structure | Fields and contract |
| --- | --- |
| `mage_vl_stream_info` | uint32 codec=H264(1); int32 width/height, fps_num/den, time_base_num/den; int64 stream_start_pts/frame_count; const uint8_t* extradata + size_t extradata_size; const int64_t* keyframe_indices + size_t keyframe_count; int32 color_primaries/transfer/matrix/full_range/sample_aspect_num/den. Preserve original codec framing and rational timestamps. Positive dimensions/rates/count, finite stream and nonempty extradata/keyframes required. Keys sorted/unique start at 0 and lie below frame_count. Colors use H264/ISO values (2 unspecified), full_range=-1/0/1. |
| `mage_vl_packet` | uint32 flags (0 or MAGE_VL_PACKET_KEY=1); const uint8_t* data + size_t size (1..INT32_MAX); int64 pts/dts/duration in original stream time base; preserve decode order. MAGE_VL_NO_TIMESTAMP=INT64_MIN is the sentinel; finite metadata-known input in this profile requires valid packet timestamps. |
| `mage_vl_segment` | uint32 group_frames; uint64 id (unique until reset, not MAGE_VL_NO_SEGMENT=UINT64_MAX); int64 first_frame/frame_count; uint32 sampled_frames_per_group/canvases_per_group; const char* question_utf8. First window begins at 0, intervals contiguous/nonoverlapping/in-bounds, positive frame_count multiple of group_frames, samples in [1,group_frames], positive configurable canvases. Enqueue before any of its frames decode. Nonempty UTF8 question is copied; do not include NUL except the terminator. Context and memory budgets constrain valid combinations. |
| `mage_vl_info` | uint32 abi_version/context_tokens/embedding_elements/visual_tokens_per_canvas/prefill_alignment_tokens (1/4096/2560/144/128); queued_segments/stream_state; uint64 active_segment_id (or NO_SEGMENT); uint32 generation_active/input_finished. Queued count includes a finished window until next retires it. |
| `mage_vl_stats` | uint64 accepted_packets/decoded_pixel_frames/decoded_bitcost_frames/sampled_frames/canvases/vision_calls/prefill_calls/prompt_tokens/generated_tokens/emitted_text_bytes/completed_segments; double pixel_decode_ms/bitcost_decode_ms/codec_host_ms/vision_host_ms/vision_invoke_ms/prompt_embedding_ms/prefill_ms/decode_ms. Aggregates since reset, not network/browser timing. |
| `mage_vl_event` | uint32 type; uint64 segment_id; uint32 stop_reason; uint64 prompt_tokens/generated_tokens/emitted_words. Types: SEGMENT_READY=1, SUMMARY_STARTED=2, SUMMARY_FINISHED=3, SEGMENT_CANCELLED=4. Stop: NONE=0, EOS=1, TOKEN_LIMIT=2, WORD_LIMIT=3, CANCELLED=4. |
| `mage_vl_text_info` | uint64 segment_id for the bytes copied by read_text. |

Stream states: EMPTY=0, OPEN=1, EOF=2, FAILED=3. All structs/enums and exact field widths/order are authoritative in [mage_vl.h](../sdk/include/mage_vl.h). Output structures retain the header's struct_size and reserved fields; initialize them before reads. Read_text/read_event never run inference. Their queues are independent: a finished event can arrive while text still needs draining.

### Generic VLM requests

`int32_t mage_vl_configure_request(mage_vl_engine *engine, const char *request_json)` configures one ordinary request on a reset/EMPTY engine, before opening media input. The caller provides a UTF-8 NUL-terminated JSON object with messages(role/content string dictionaries) and optional positive max_new_tokens. Other fields report UNSUPPORTED. Roles follow optional system and alternating user/assistant, ending with user. Native tokenization validates text; reserved model markers and NUL are rejected. The request owns the final user question and the enqueued segment must match it. No summary instruction is inserted. Default model system wording is retained when no system message is supplied.

The native request path applies a real token budget and disables the application word cap. The SDK controls stopping at the requested budget; the matched Genie implicit END limit is set one token beyond it so that limit cannot be mislabeled as natural EOS. Existing packet/segment structs, functions and ABI1 remain unchanged. All calls remain serialized; finish native work before destroy. Ordinary request reset restores the original advanced engine options.

### Ordinary image input

`int32_t mage_vl_start_image_rgb(mage_vl_engine *engine, const uint8_t *rgb, size_t bytes)` starts an ordinary image request after reset/configure_request. `rgb` must contain exactly512*288*3 bytes of interleaved RGB8, row-major, tightly packed. The call copies the bytes before returning; the caller can release its buffer. It does not infer. The handle enters EOF with segment_id0; use the same serialized next/read_text/read_event sequence, drain text before accepting the terminal event, then reset for reuse or destroy. Do not open/feed/finish a video stream for an image.

Returns0 on success, ARGUMENT(-1) for NULL/wrong-size input or insufficient pending budget, STATE(-5) unless EMPTY with a configured request, CONTEXT(-9) if the actual image prompt plus output reserve cannot fit, or another native error. Wrong-size/state checks precede model work. File decoding and resizing are caller-owned; the Python adapter uses RGB conversion and Pillow BICUBIC to512x288 without EXIF rotation or padding. Native code performs normalization, patch order, spatial RoPE, one ViT call, visual/text embedding packing and generation. No repeated-frame video or codec JPEG round trip is introduced. Public C structs and ABI1 remain unchanged.

### Text requests and native cache leases

The model ABI remains 1. Set the Runtime configuration and status ABI fields to `PANDORA_RUNTIME_ABI_VERSION` from [pandora_runtime.h](../sdk/include/pandora_runtime.h). New cache functions are additive and require this SDK's matching headers and library.

| Function | Contract |
| --- | --- |
| `mage_vl_cache_begin(model, &id)` | Bind one model/process-local cache lease; caller initializes id=0. A second lease returns BUSY. |
| `mage_vl_configure_cached_request(model, id, json)` | Configure the first request or one new user follow-up, optionally with one new visual input. JSON uses messages, input_kind (`text`, `image`, `video`) and optional max_new_tokens. Parsing and input-budget validation precede native cache mutation. |
| `mage_vl_start_text(model)` | Start a configured text request. Advance and drain using the existing next/read_text/read_event calls. |
| `mage_vl_cache_get_info(model, id, &info)` | Initialize exact struct_size. Return retained/reused counts, turns and actual Genie context occupancy in backend_tokens. |
| `mage_vl_cache_release(model, id)` | Release the cache and reset its context. Close/stop active generation first. Retrying the last successful release is allowed until the next lease starts. Other IDs fail. |

First cached turns may use text or one supported image/video. Subsequent turns accept one new user message with text or one new image/video plus text. Use the image RGB or finite-video packet entry after configuring the corresponding input_kind; no repeated visual work is needed for text follow-ups. Only one complete visual plan is accepted within a cached request. Ordinary packet plans remain independent, resetting language state after each completed window.

Natural EOS retains native KV. Length stops, abort/reset or execution failures end that chain. A native lease blocks model destruction until explicitly released. Cache info's valid flag must be true before continuation. IDs are not transferable across model instances/providers/processes; all calls require application owner synchronization. See [cache_chat.c](../examples/c/cache_chat.c) for a complete three-turn example and cleanup sequence.

### Codec file request configuration

The same configure_request/configure_cached_request JSON can include `video_codec` when `input_kind="video"`. It contains positive uint32 `target_canvas`, `group_size`, `images_per_group`, a strictly increasing `frame_times` array in seconds starting at zero, and `duration` strictly beyond the last timestamp. The timestamp array covers every source frame in presentation order and must match open_stream.frame_count. This metadata is supplied by the container adapter; native code owns grouping, sampling, codec packing and context/memory validation.

Configure the request, open the H.264 stream, and enqueue exactly one full-source segment with first_frame 0, group_frames 1, sampled_frames_per_group matching group_size and canvases_per_group matching images_per_group. Native code derives time groups; feed/read/finish/close rules are unchanged. Packet requests without video_codec retain their explicit frame-based plans, with positive configurable canvases_per_group. The fixed `==4` check has been removed; callers must use a matching SDK library.

See the [codec README](video-codec/README.md) for public defaults 12/20/4 and integer/budget rules. No arbitrary model/Genie JSON, graph geometry override, H.265 input or cross-message media reorder is added.

Timestamp-driven packet windows use the additive `mage_vl_time_window`, `mage_vl_open_timed_stream`, `mage_vl_enqueue_window`, and `mage_vl_next_at` entries in the [public header](../sdk/include/mage_vl.h). These calls use the existing model ABI 1 structs. See [paced Python/C contract](../sdk/ADVANCED_VIDEO_API.md#timestamp-driven-windows-web-default) and [codec formulas](video-codec/README.md).

### Common LM defaults and packet generation

For ordinary and cached requests, an omitted or null max_new_tokens uses the loaded model’s default on each call. The other defaults for the greedy adapter are do_sample false, temperature 1.0, top_p 1.0, top_k 0 and repetition_penalty 1.0. This adapter supports explicit do_samplefalse and repetition_penalty1.0. Non-None sampling fields require do_sampletrue, and sampling remains unsupported. Invalid types/ranges fail before request state changes.

For the timed packet extension, call `mage_vl_configure_packet_generation(engine, parameters_json)` while idle and before opening input. An omitted or null `max_new_tokens` uses 256. An explicit value overrides that default. The other five generation fields follow the defaults and restrictions above. The separately supplied packet word cap still applies. Web and C examples explicitly pass their own token/word budgets and greedy/no-extra-penalty settings. Packet generation uses the existing model ABI 1 structs.

## Error codes

| Code | Meaning | What the caller should do |
| --- | --- | --- |
| `0` | Success, or no items for a read or advance call | Follow the return contract for the function. |
| `-1` | Invalid argument | Check inputs and initialize structures to their declared sizes. |
| `-2` | Model error | Check the diagnostic, model directory and target. |
| `-3` | Decode error | Check the input stream and reset or close the failed request. |
| `-4` | NPU error | Copy the diagnostic and check the device/runtime prerequisites. |
| `-5` | Invalid state | Check the call order and process ownership. |
| `-6` | Native engine error | Copy the diagnostic, then close the failed request. |
| `-7` | Backpressure | Drain and advance before retrying the same input. |
| `-8` | Unsupported operation or option | Use capabilities offered by this SDK. |
| `-9` | Context budget exceeded | Reduce input size or the output token budget. |
| `-10` | Busy | Complete or close the active request or cache before retrying. |
| `-11` | Authorization failure | Check the device activation and matching authorized model package. |

For status functions, negative values report failure. Read and copy the diagnostic before another call clears it. Decode or model failures can leave the stream in the FAILED state. Reset or close it before reuse.

## Threads and ownership

Opaque `mage_vl_engine*` is owned by the caller after successful create. Use RAII in C++ or one cleanup path in C. Call `mage_vl_default_options` for options. For other input/output structs, zero them and set `struct_size = sizeof(value)` before each first use; keep reserved fields/arrays zero. Header ABI_VERSION is 1. Use the exact supplied layout/field widths; never pack structures or cross the boundary with STL objects/exceptions. Pointers/size_t use the target AArch64 ABI. Text is NUL-terminated UTF-8 unless a byte length is explicitly supplied.

Only one handle per process is supported. Serialize every operation on it, including info, read, abort, reset and destroy. The native model worker serializes individual operations; a multi-call application transaction still requires one owner. Calls synchronously finish before return and do not call application callbacks. Native creation can create vendor runtime threads. The SDK preserves host policies. Bind an optional Runtime from the bundled provider using `mage_vl_create_with_runtime`; see [Runtime](../sdk/RUNTIME_API.md) for configuration, all values, ownership and error rules. Serialize creation with closing the same Runtime handle. `mage_vl_destroy_owned` clears the caller slot only after successful checked cleanup; cleanup failure retains the complete owner and returns an error. Do not use inherited handles after fork; status APIs return STATE before touching inherited locks. Legacy create uses default Runtime settings; legacy void destroy ignores inherited handles. New code uses the status-returning owned API.


The caller owns source/container demux, pacing and segment scheduling. The SDK owns compressed-packet decoding, model preprocessing/packing, tokenization and inference. All pointed input for open/enqueue/feed is copied before that call returns; caller buffers may then be reused/freed. Do not mutate or free them during the call. Returned text/events are copied into caller buffers, not SDK allocations to free.

## Example

Build and run [the C image example](../examples/README.md#c-integration) from [examples/c/image_chat.c](../examples/c/image_chat.c). It shows model initialization, image description and checked shutdown. For native conversation state, see [examples/c/cache_chat.c](../examples/c/cache_chat.c).

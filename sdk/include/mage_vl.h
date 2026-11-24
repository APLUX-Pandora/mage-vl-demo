#ifndef MAGE_VL_H
#define MAGE_VL_H

#include <stddef.h>
#include <stdint.h>

#if defined(__GNUC__)
#define MAGE_VL_API __attribute__((visibility("default")))
#else
#define MAGE_VL_API
#endif

#define MAGE_VL_VERSION "1.0.0"
#define MAGE_VL_ABI_VERSION 1u
#define MAGE_VL_NO_TIMESTAMP INT64_MIN
#define MAGE_VL_NO_SEGMENT UINT64_MAX

#ifdef __cplusplus
extern "C" {
#endif

/* Serialized video-packet/image-RGB C ABI; numerical/lifecycle coverage is separate.
 * All calls on a handle, including abort/read/destroy, must be serialized.
 * Calls execute on a persistent model-owned worker; no source IO, subprocess,
 * playback clock or callback to user code.
 * Model-package IO at creation and profiling elapsed-time measurements are allowed.
 * The caller owns source demux, pacing and scheduling. Packet decoding is in the SDK.
 * One model handle per process is supported initially; a second create reports BUSY.
 */
typedef struct mage_vl_engine mage_vl_engine;

/* A cache lease belongs to this model and process. Close streams, release the
 * cache lease, destroy the model, then destroy an external Runtime. Cache IDs
 * are opaque and never transferable between model instances. */
typedef struct mage_vl_cache_info {
    uint32_t struct_size, valid;
    uint64_t cache_id, cached_tokens, backend_tokens, turns, reused_tokens;
    uint64_t last_prompt_tokens, last_generated_tokens;
} mage_vl_cache_info;
MAGE_VL_API int32_t mage_vl_cache_begin(mage_vl_engine*, uint64_t* empty_id);
MAGE_VL_API int32_t mage_vl_cache_release(mage_vl_engine*, uint64_t cache_id);
MAGE_VL_API int32_t mage_vl_cache_get_info(mage_vl_engine*, uint64_t cache_id, mage_vl_cache_info*);
MAGE_VL_API int32_t mage_vl_configure_cached_request(mage_vl_engine*, uint64_t cache_id, const char* json);
MAGE_VL_API int32_t mage_vl_start_text(mage_vl_engine*);


struct mage_vl_options;
struct pandora_runtime;

/* Model creation publishes into an owned slot before returning, so
 * bindings can recover ownership if a language-level exception is delivered.
 * *out must be NULL. A NULL Runtime selects the model-owned defaults.
 * Serialize Runtime destruction with model creation on the same Runtime handle.
 * Successfully loaded models keep their own reference. See pandora_runtime.h.
 * Deprecated prepare_process returns UNSUPPORTED without changing host policy. */
MAGE_VL_API int32_t mage_vl_create_with_runtime(const char *, const struct mage_vl_options *,
                                              const struct pandora_runtime *, mage_vl_engine **out);
MAGE_VL_API int32_t mage_vl_destroy_owned(mage_vl_engine **owner);
typedef enum mage_vl_status {
    MAGE_VL_OK = 0,
    MAGE_VL_ERR_ARGUMENT = -1,
    MAGE_VL_ERR_MODEL = -2,
    MAGE_VL_ERR_DECODE = -3,
    MAGE_VL_ERR_NPU = -4,
    MAGE_VL_ERR_STATE = -5,
    MAGE_VL_ERR_INTERNAL = -6,
    MAGE_VL_ERR_WOULD_BLOCK = -7,
    MAGE_VL_ERR_UNSUPPORTED = -8,
    MAGE_VL_ERR_CONTEXT = -9,
    MAGE_VL_ERR_BUSY = -10,
    MAGE_VL_ERR_AUTHORIZATION = -11
} mage_vl_status;

typedef enum mage_vl_codec {
    MAGE_VL_CODEC_H264 = 1
} mage_vl_codec;

typedef enum mage_vl_stream_state {
    MAGE_VL_STREAM_EMPTY = 0,
    MAGE_VL_STREAM_OPEN = 1,
    MAGE_VL_STREAM_EOF = 2,
    MAGE_VL_STREAM_FAILED = 3
} mage_vl_stream_state;

typedef enum mage_vl_event_type {
    MAGE_VL_EVENT_SEGMENT_READY = 1,
    MAGE_VL_EVENT_SUMMARY_STARTED = 2,
    MAGE_VL_EVENT_SUMMARY_FINISHED = 3,
    MAGE_VL_EVENT_SEGMENT_CANCELLED = 4
} mage_vl_event_type;

typedef enum mage_vl_stop_reason {
    MAGE_VL_STOP_NONE = 0,
    MAGE_VL_STOP_EOS = 1,
    MAGE_VL_STOP_TOKEN_LIMIT = 2,
    MAGE_VL_STOP_WORD_LIMIT = 3,
    MAGE_VL_STOP_CANCELLED = 4
} mage_vl_stop_reason;

enum { MAGE_VL_PACKET_KEY = 1u };

typedef struct mage_vl_options {
    uint32_t struct_size;
    uint32_t abi_version;
    uint32_t max_output_tokens;       /* Default 256; package context is checked. */
    uint32_t max_output_words;        /* Default 60; English whitespace word cap. */
    uint32_t max_queued_segments;     /* Default 2; windows are explicitly submitted. */
    uint32_t reserved0;
    uint64_t max_pending_bytes;       /* Default 256 MiB of queued media/model inputs. */
    uint64_t max_output_queue_bytes;  /* Default 64 KiB; drain before producing more. */
    uint64_t reserved[8];
} mage_vl_options;

/* Container facts, not model-preprocessed tensors. All pointed-to input is copied
 * before the call returns. Only finite, metadata-known H.264 sources are in scope
 * for the first contract; unknown-keyframe live streams need another contract.
 * Codec data/extradata and timestamps retain the demuxer's original representation.
 * Color fields use the H.264/ISO numerical values, with 2 meaning unspecified.
 */
typedef struct mage_vl_stream_info {
    uint32_t struct_size;
    uint32_t codec;
    int32_t width;
    int32_t height;
    int32_t fps_num;
    int32_t fps_den;
    int32_t time_base_num;
    int32_t time_base_den;
    int64_t stream_start_pts;
    int64_t frame_count;
    const uint8_t *extradata;
    size_t extradata_size;
    const int64_t *keyframe_indices;   /* Sorted, unique presentation-frame indices. */
    size_t keyframe_count;
    int32_t color_primaries;
    int32_t color_transfer;
    int32_t color_matrix;
    int32_t full_range;              /* -1 unspecified, 0 limited, 1 full. */
    int32_t sample_aspect_num;
    int32_t sample_aspect_den;
    uint64_t reserved[8];
} mage_vl_stream_info;

typedef struct mage_vl_packet {
    uint32_t struct_size;
    uint32_t flags;
    const uint8_t *data;
    size_t size;
    int64_t pts;
    int64_t dts;
    int64_t duration;
    uint64_t reserved[4];
} mage_vl_packet;

/* The caller chooses segment intervals. The SDK derives sampling/keyframe shifts,
 * group packing, timestamp markup and all model tensors. Intervals are ordered,
 * contiguous, nonoverlapping, and frame-based; decoder state spans the intervals.
 * question_utf8 is application content. The SDK owns the model chat template.
 * For exact golden parity use the archived English football question verbatim.
 */
typedef struct mage_vl_segment {
    uint32_t struct_size;
    uint32_t group_frames;             /* Golden source: 500 (10 s at 50 fps). */
    uint64_t id;                       /* Unique until reset; NO_SEGMENT is reserved. */
    int64_t first_frame;
    int64_t frame_count;               /* Positive multiple of group_frames; golden: 1500. */
    uint32_t sampled_frames_per_group; /* Golden source: 40. */
    uint32_t canvases_per_group;       /* Golden source: 4; must fit package budget. */
    const char *question_utf8;         /* Required; copied at enqueue. */
    uint64_t reserved[8];
} mage_vl_segment;

/* Timestamp-driven packet windows. Counts must be positive; target_canvas and
 * group_size must be divisible by images_per_group. Native context/memory limits
 * still apply. All strings/tables are copied before calls return. */
typedef struct mage_vl_time_window {
    uint32_t struct_size;
    uint32_t target_canvas;          /* Default application budget12. */
    uint32_t group_size;             /* Candidate frames/group, default20. */
    uint32_t images_per_group;       /* Canvas budget/group, default4. */
    uint64_t id;
    double start_time_s;
    double end_time_s;
    const char *question_utf8;
    uint64_t reserved[4];
} mage_vl_time_window;

typedef struct mage_vl_info {
    uint32_t struct_size;
    uint32_t abi_version;
    uint32_t context_tokens;
    uint32_t embedding_elements;
    uint32_t visual_tokens_per_canvas;
    uint32_t prefill_alignment_tokens;
    uint32_t queued_segments;
    uint32_t stream_state;
    uint64_t active_segment_id;
    uint32_t generation_active;
    uint32_t input_finished;
    uint64_t reserved[8];
} mage_vl_info;

typedef struct mage_vl_stats {
    uint32_t struct_size;
    uint32_t reserved0;
    uint64_t accepted_packets;
    uint64_t decoded_pixel_frames;
    uint64_t decoded_bitcost_frames;
    uint64_t sampled_frames;
    uint64_t canvases;
    uint64_t vision_calls;
    uint64_t prefill_calls;
    uint64_t prompt_tokens;          /* Aggregate prefix and final-tail tokens once. */
    uint64_t generated_tokens;       /* Includes backend control tokens if generated. */
    uint64_t emitted_text_bytes;
    uint64_t completed_segments;
    double pixel_decode_ms;
    double bitcost_decode_ms;
    double codec_host_ms;
    double vision_host_ms;
    double vision_invoke_ms;
    double prompt_embedding_ms;
    double prefill_ms;
    double decode_ms;
    uint64_t reserved[8];
} mage_vl_stats;

typedef struct mage_vl_event {
    uint32_t struct_size;
    uint32_t type;
    uint64_t segment_id;
    uint32_t stop_reason;
    uint32_t reserved0;
    uint64_t prompt_tokens;
    uint64_t generated_tokens;
    uint64_t emitted_words;
    uint64_t reserved[4];
} mage_vl_event;

typedef struct mage_vl_text_info {
    uint32_t struct_size;
    uint32_t reserved0;
    uint64_t segment_id;
    uint64_t reserved[4];
} mage_vl_text_info;

/* Initialize options, then change documented fields. Other public structs must be
 * zeroed and struct_size set to sizeof(struct). Reserved fields must remain zero.
 * get_info/get_stats/read_event/read_text validate output struct_size before writing.
 */
/* Deprecated compatibility entry: returns MAGE_VL_ERR_UNSUPPORTED without
 * changing dumpability, core/memlock limits, signal policy or output streams.
 * The model owns its protected buffers. Diagnostic through
 * create_status/create_error. This function is never required for loading. */
MAGE_VL_API int32_t mage_vl_prepare_process(void);
MAGE_VL_API int32_t mage_vl_default_options(mage_vl_options *options);
MAGE_VL_API mage_vl_engine *mage_vl_create(const char *model_dir, const mage_vl_options *options);
MAGE_VL_API void mage_vl_destroy(mage_vl_engine *engine); /* NULL is allowed. */
MAGE_VL_API const char *mage_vl_create_error(void);       /* Thread-local diagnostic. */
MAGE_VL_API int32_t mage_vl_create_status(void);          /* Last create status on this thread. */
MAGE_VL_API const char *mage_vl_last_error(const mage_vl_engine *engine);
MAGE_VL_API int32_t mage_vl_get_info(const mage_vl_engine *engine, mage_vl_info *info);
MAGE_VL_API int32_t mage_vl_get_stats(const mage_vl_engine *engine, mage_vl_stats *stats);

/* open_stream requires EMPTY. Enqueue windows before packets covering their frame
 * range. The first interval begins at frame 0; seeking/discontinuities require reset.
 * feed_packet consumes the entire original packet or none. On WOULD_BLOCK, drain
 * outputs / advance generation and retry the same packet; no silent frame dropping.
 * H.264 packets must preserve the source extradata, framing, timing and key flags.
 */
MAGE_VL_API int32_t mage_vl_open_stream(mage_vl_engine *engine, const mage_vl_stream_info *stream);
/* Finite PTS table, one time per display frame in strictly increasing order,
 * normalized to start at0. duration_s extends beyond the final frame timestamp.
 * Use contiguous [start,end) windows; empty windows are rejected. Nominal FPS is
 * metadata only. reset before switching stream modes. */
MAGE_VL_API int32_t mage_vl_open_timed_stream(mage_vl_engine *engine,
    const mage_vl_stream_info *stream,const double *frame_times,size_t count,double duration_s);
MAGE_VL_API int32_t mage_vl_enqueue_window(mage_vl_engine *engine,const mage_vl_time_window *window);
MAGE_VL_API int32_t mage_vl_enqueue_segment(mage_vl_engine *engine, const mage_vl_segment *segment);
MAGE_VL_API int32_t mage_vl_feed_packet(mage_vl_engine *engine, const mage_vl_packet *packet);
MAGE_VL_API int32_t mage_vl_finish_input(mage_vl_engine *engine); /* Idempotent decoder EOF flush. */

/* next advances ready model work and generation synchronously; it returns the
 * number of newly queued text/event items, or a negative status. Zero means
 * this call queued no new output. Drain text and events after each call and retry
 * WOULD_BLOCK after draining. Use get_info to check whether input has ended and
 * whether segments or generation are pending. Before input ends, keep feeding
 * packets as available. After EOF, advance pending work until no segment remains.
 * Timed streams may also need a later playback time before work can advance.
 * feed_packet can decode future-window input between next calls. Only the oldest
 * uncancelled window can own LLM KV; later-window prefill waits for it to finish.
 * A call can include final prefill and is not a bounded-time/nonblocking operation.
 */
MAGE_VL_API int32_t mage_vl_next(mage_vl_engine *engine);
/* Timed playback variant: monotonic media time in [0,duration]. Earlier groups
 * may prefill; final-group work/summary waits for end_time_s. next() remains the
 * explicit unpaced/offline variant. Both can block during native model work. */
MAGE_VL_API int32_t mage_vl_next_at(mage_vl_engine *engine,double media_time_s);

/* Reads never execute models. read_text returns copied byte count (without NUL),
 * from one segment only, or 0 if empty. A chunk may split a UTF-8 character; clients
 * decode incrementally. Short reads retain the suffix. read_event returns 1 or 0.
 * Finished events may be read before all text is drained; queues are independent.
 */
MAGE_VL_API int32_t mage_vl_read_text(mage_vl_engine *engine, uint8_t *dst, size_t capacity,
                                    mage_vl_text_info *info);
MAGE_VL_API int32_t mage_vl_read_event(mage_vl_engine *engine, mage_vl_event *event);

/* Serialized cancellation stops generation. Drain existing output and call next
 * as needed to deliver pending text and the cancellation event. Decoder continuity
 * and later plans survive. Abort does not interrupt an executing call. Reset clears
 * stream, decoder, KV, queues and stats while keeping the models loaded. */
MAGE_VL_API int32_t mage_vl_abort(mage_vl_engine *engine, uint64_t segment_id);
MAGE_VL_API int32_t mage_vl_reset(mage_vl_engine *engine);
/* Configure an idle packet model before open_stream. JSON accepts the six LM
 * generation parameters with omission/null defaults 256/false/1/1/0/1.
 * Mage supports greedy only and repetition_penalty=1. Explicit sampling
 * fields require do_sample=true, which this adapter rejects as unsupported.
 * Packet word limits remain caller-owned creation options. */
MAGE_VL_API int32_t mage_vl_configure_packet_generation(mage_vl_engine*, const char* parameters_json);

/* Read the loaded model's default generation token budget. The output is
 * written only on success and is independent of per-request overrides. */
MAGE_VL_API int32_t mage_vl_get_default_max_new_tokens(mage_vl_engine *engine, uint32_t *out);

/* Generic VLM request, after reset and before opening input. JSON contains a
 * text messages array (role/content) and the six LM parameters. An omitted or
 * null token budget uses the loaded model's default on every request.
 * The greedy adapter uses false/1/1/0/1 for other omitted parameters.
 * It applies no application word limit and does not insert summary instructions.
 */
MAGE_VL_API int32_t mage_vl_configure_request(mage_vl_engine *engine, const char *request_json);

/* After reset/configure_request: copy one512x288 RGB8 image (512*288*3 bytes).
 * No video or JPEG round trip. next/read_text/read_event advance the same request.
 * Resize/file decoding is caller-owned; the Python file adapter uses Pillow BICUBIC.
 * Returns OK, ARGUMENT, STATE or a native error. All handle calls are serialized.
 */
MAGE_VL_API int32_t mage_vl_start_image_rgb(mage_vl_engine* engine,const uint8_t* rgb,size_t bytes);

#ifdef __cplusplus
}
#endif
#endif

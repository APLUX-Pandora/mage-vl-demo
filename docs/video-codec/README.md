# Video codec parameters

Use the same installed [LanguageModel](../../sdk/PYTHON_API.md) for video questions and explicit cached conversations. Run examples from the repository root after the [installation](../../README.md#1-install) and [model preparation](../MODEL_SETUP.md), with that environment activated.

## Parameters and defaults

Both `generate()` and `generate_stream()` accept these keyword-only options. Omission or `None` resolves independently on every request to the values below. They affect only the new video in that request; a cached conversation does not inherit a previous override.

| Parameter | Type | Omitted / None | Meaning |
| --- | --- | --- | --- |
| `video_target_canvas` | positive integer, excluding bool | **12** | Maximum total codec canvas images for this video. More canvases preserve more visual blocks and require more ViT calls and language context. |
| `video_group_size` | positive integer, excluding bool | **20** | Maximum distinct candidate frames selected per temporal group, before bitcost block selection. This is neither source FPS nor a duration. More candidates increase decoding/codec work without directly increasing the canvas budget. |
| `video_images_per_group` | positive integer, excluding bool | **4** | Canvas images assembled from each group. This is configurable, not a model requirement to always use four. |

All effective values must fit uint32. Both `video_target_canvas` and `video_group_size` must be divisible by `video_images_per_group`, following the upstream codec configuration contract. Consequently each is at least `video_images_per_group`. The native SDK also checks actual memory, timestamp/packet buffers and context capacity; satisfying integer relations does not guarantee that a large plan fits.

Specifying a non-None video option without a new video is an input error. Invalid values are rejected rather than ignored, rounded or silently reduced to fit context. Fixed model geometry remains **512 × 288 RGB per canvas**, **16 × 16 patches**, and **2 × 2 patch blocks**.

## Calculation

For a normal video with enough distinct frames:

```text
temporal groups       = video_target_canvas / video_images_per_group
candidate frame budget = temporal groups * video_group_size
canvas budget          = temporal groups * video_images_per_group
```

The whole file is divided into ordered equal-duration spans using presentation timestamps. Each group samples representative source frames, retaining the codec keyframe-avoidance rule. Bitcost scores select important blocks; canvases are encoded by repeated ViT calls and their visual features are concatenated in temporal order. This is fixed temporal grouping, not the upstream readiness grouping algorithm.

With the defaults, there are **3 groups × 20 candidates = 60 candidate frames**, producing up to **3 × 4 = 12 canvases**. Each full canvas contributes 144 visual tokens, so 12 canvases contribute 1728 visual tokens. The 4096-token context also includes timestamp/template tokens, the question, retained conversation KV and the requested output reserve.

| Total canvases | Candidates per group | Canvases per group | Groups | Candidate budget |
| --- | --- | --- | --- | --- |
| 12 | 20 | 4 | 3 | 60 |
| 12 | 20 | 2 | 6 | 120 |
| 12 | 24 | 3 | 4 | 96 |

These are arithmetic examples, not an accuracy ranking or a recommendation that every setting gives equal results. More candidates change what the codec can select; more canvases increase model input. Long videos at the same budget have sparser coverage and may miss brief actions.

## A 15-second video

For the supplied `demo/samples/cafe15.mp4` at 50 FPS, the source has 750 frames. The default plan splits it into 3 spans of 5 seconds, 250 source frames per span. Each span selects 20 candidates and generates 4 canvases:

```text
750 source frames -> 3 spans -> 60 selected candidate frames -> 12 canvases
```

```python
from pandora_mage_vl import LanguageModel

messages = [{
    "role": "user",
    "content": [
        {"type": "video", "video": "demo/samples/cafe15.mp4"},
        {"type": "text", "text": "Describe the visible actions."},
    ],
}]
with LanguageModel.from_pretrained("models") as model:
    result = model.generate(messages, max_new_tokens=64, do_sample=False, repetition_penalty=1.0)
    print(result.text)
    print(result.finish_reason)
```

The same codec selection is requested explicitly below. This fragment keeps the SDK common 256-token budget explicit; the Demo example above uses 64:

```python
result = model.generate(
    messages,
    max_new_tokens=256, do_sample=False, repetition_penalty=1.0,
    video_target_canvas=12,
    video_group_size=20,
    video_images_per_group=4,
)
```

This last snippet assumes the model is still open. For denser candidate selection at the same canvas budget, set `video_group_size=40`: 3 groups select up to 120 candidates while still producing 12 canvases.

## Different duration, frame rate, and short files

Only **H.264 MP4/MOV** is supported; **H.265 is unsupported**. Source FPS need not be 50 and file duration need not be 15/30 seconds. The transport requires one video stream, distinct presentation timestamps, valid decoding timestamps and an initial keyframe; compressed input and packet/timing metadata are bounded to 256 MiB. Audio tracks do not become model audio input.

At 15 seconds / 30 FPS, each default span contains approximately 150 source frames, still selecting up to 20 candidates. At 60 seconds / 30 FPS, each span covers 20 seconds, still selecting up to 20 candidates. Variable-rate files use actual presentation times for grouping and prompt timestamps. No conversion to 50 FPS is performed.

Empty time spans are omitted. Short groups use available distinct frames and fewer canvases when necessary; the target is an upper budget, not a demand to duplicate frames or add black frames. Material too short or lacking usable codec bitcost records fails explicitly. The native stats `sampled_frames`, `canvases` and `vision_calls` describe actual work; these differ from requested maxima on short media.

Video must precede the instruction in the final user content list. The known text-before-video limitation is retained. Descriptions can misidentify actions or relationships and are not ground-truth annotations.

## Conversation and Demo behavior

Use `past_key_values=cache` with this SDK's `DynamicCache` to append a new text, image or video user turn after a naturally completed turn. Pass only the new user message. Video controls affect that new video; prior visual context remains in native KV. Context/budget limits and the documented stop/length/cancellation rules still apply.

The Web Demo intentionally summarizes independent 15-second windows with the 12/20/4 profile and no cross-window conversation. Its optional 30-second profile explicitly uses 40 candidates per group. The Web uploader also uses real timestamps, supports non-50-FPS/VFR H.264 sources and includes the final short window. The same three controls are available through advanced settings and `POST /api/jobs`. [Advanced packet API](../../sdk/ADVANCED_VIDEO_API.md) describes packet transport and lifecycle separately.

## Web windows and tail calculation

`video_target_canvas` is the budget **per independent Web window**, while ordinary `LanguageModel.generate()` applies it to the complete video file in that request. For a Web interval `W`, source duration `D` and window index `i`:

```text
window_count = ceil(D / W)
start        = i * W
end          = min((i + 1) * W, D)
K            = video_target_canvas / video_images_per_group
span_j       = [start + (end-start)*j/K, start + (end-start)*(j+1)/K)
N_j          = distinct source frames whose PTS falls in span_j
candidates_j = min(video_group_size, N_j)
canvases_j   = min(video_images_per_group, candidates_j)
actual_canvases = sum(canvases_j for nonempty groups)
```

The source PTS table determines `N_j`, so these formulas apply to variable frame rate too. The frame sampling positions within a group retain the native codec rule. An empty group is omitted; a whole selected window containing no frames fails explicitly. The 12-canvas default is an upper budget even for a short tail, not a proportional-duration calculation. No repeated or black frames are inserted.

| Input / final window | Groups at12/20/4 | Candidates | Actual canvases |
| --- | --- | --- | --- |
|15s at50FPS (750frames) |3×5s;250frames/group |3×20=60 |12 |
|17s at30FPS, final2s (60frames) |3×2/3s;20frames/group |60 |12 |
|17s at 24 FPS, final2s (48frames) |3×2/3s;16frames/group |48 |12 |
|0.9s at10FPS (9frames) |3×0.3s;3frames/group |9 |9 |

These counts describe timing/count examples, not semantic-quality guarantees. Web uses one continuous H.264 decoder and independent language summaries. `VideoPacketModel.open_stream(..., frame_times=..., duration=...)`, `enqueue_window(...)` and `next(media_time=...)` provide the public paced SDK route. The source rate is metadata; windows and prompt timestamps use actual PTS. Final-group work waits for the real window boundary. There is no 50-FPS or complete-window rejection, and no arbitrary six-minute duration cap; 256 MiB input/metadata and native model/resource limits remain.

The SDK common generation defaults are 256 tokens, greedy decoding and no extra repetition penalty (temperature=1.0/top_p=1.0/top_k=0 are inactive unless sampling). The examples use an explicit 64-token greedy preset with repetition_penalty=1.0. The Web uses 48 tokens/35 words per 15-second window or 64 tokens/60 words per 30-second window. Sampling is not supported by this adapter. See the Python API for defaults, validation and limits.

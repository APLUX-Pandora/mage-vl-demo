# Video Highlights

An English browser demo over the native SDK. The original video plays continuously while independent 15- or 30-second windows produce streamed summaries. The next window can play while the preceding summary finishes.

## Start

From the repository root, after the [installation and model download](../README.md) and [runtime setup](../sdk/README.md#runtime-environment):

```sh
source .venv/bin/activate
bash demo/run.sh --models models --host 0.0.0.0 --port 8088
```

Use the supplied `sdk/lib/libmage_vl.so`; no SDK build, system Python install or Git LFS download is needed from the GitHub checkout. The launcher uses this project's `.venv` and preserves host process policies.

Open `http://BOARD_ADDRESS:8088` in a browser with H.264 playback support. The local server loads models once and owns one serialized SDK worker. It supports one active session at a time. `run.sh` only starts the server; it does not install packages or launch other services.

The installed SDK supplies the matching native library.`--media-dir` defaults to `demo/media`; `--runs-dir` defaults to `out/web`. The server listens on `127.0.0.1:8080` unless flags override it. Runtime and DSP environment variables are needed by vendor libraries, not interpreted as application policy.

## Controls

The desktop page fits the viewport: video and controls on the left, an interval activity banner and all segment rows on the right. The selected segment expands in place; choose another row to read its full summary. The page does not scroll vertically.

1. Choose **Cafe activity · fixed camera**, or **Upload video**. Upload accepts a single-video-stream H.264 MP4/MOV at its source frame rate (including VFR), up to 256 MiB. There is no fixed 50-FPS, minimum-window or six-minute duration requirement; the final short window is included. Unsupported inputs fail explicitly. Two uploads can be stored; **Remove upload** removes the selected inactive upload.
2. Click **Understand video** once. The application prepares the source, resets the stream, queues the first windows, then automatically starts playback and understanding. Preparation appears briefly as **Starting…**; it is not a separate user step. Models load before the button becomes available. If a browser blocks programmatic audible playback, the same button lets the user grant playback with another click.
3. The default clip is silent: the page shows **No audio track** and disables mute. Uploaded videos with an audio track play sound by default; **Sound on / Sound off** toggles mute. Audio is not a model input. **Pause** freezes source delivery while available analysis/generation can continue. Click **Understand video** to resume. Playback stays at normal speed; reset to restart instead of seeking.
4. The purple activity banner shows **Watching segment N**, a countdown and progress through the selected interval. At each boundary, the card and banner turn green with animated activity while the summary is prepared and streamed. The next video segment keeps playing. Completed rows remain selectable. Animations respect reduced-motion preferences.
5. **Stop** pauses playback and cancels unfinished windows between SDK calls, retaining already displayed text. **Reset** clears playback/cards and enables a new source/settings. Models stay loaded unless output options change.

**Advanced settings** contains **Maximum English words** (1-120, default 35) and **Maximum output tokens** (1-512, default 48). Words are the SDK's whitespace-based English word ceiling. Tokens are model generation units, not words; their ceiling can stop generation before the word ceiling and can truncate a sentence/word. The default prompt targets 20-30 words. Changing the word ceiling also adjusts prompt guidance. Both hard ceilings are independently enforced by the SDK. The interval selector changes video segmentation independently of these ceilings. The same panel exposes **Canvas budget per segment**, **Candidate frames per group**, and **Canvas budget per group** (15s defaults **12/20/4**). Both budgets must be divisible by the per-group canvas count; native context and memory limits still apply. These settings are frozen during a session. See the dedicated [video codec README](../docs/video-codec/README.md) for effects, formulas and examples.

Expanded completed cards show first-text latency, writing duration and final word count. Browser timing includes HTTP/SSE/render scheduling and differs from SDK stage timings. Token/word-ceiling stops are identified. The segmented playback bar is a progress display, not a seek control. At EOF the application flushes input and waits for the final summary. A new page observing an active session cannot feed a second playback clock; Stop/Reset explicitly to restart. SSE reconnection replays retained events without duplicating text or inference.

## Segment presets

The visible **Summary interval** selector defaults to **15 seconds**. Switching it while idle updates all cards, countdowns, prompt guidance and SDK limits together. The interval is fixed for an active job; reset before changing it.

| Interval | Groups | Samples per group | Canvases per group | Prompt target | Word ceiling | Token ceiling |
| --- | --- | --- | --- | --- | --- | --- |
| 30 seconds (optional) | 3 × 10 seconds | 40 | 4 | 40–50 words | 60 | 64 |
| 15 seconds (default) | 3 × 5 seconds | 20 | 4 | 20–30 words | 35 | 48 |

Both presets use the existing native continuous pixel/bitcost decoding, up to four fixed-shape ViT calls per group by default and AR128-aligned incremental prefill. Each window resets LLM state. A 180-second source produces 6 or 12 independent summaries. A shorter preset changes the input frames and output limits. Group membership and prompt times use actual presentation timestamps; the nominal FPS is not used to assign frames to windows.

API: `POST /api/jobs` accepts `segment_seconds: 15` or `30`; omitting `segment_seconds` selects 15 seconds; omitted output ceilings use that preset's defaults. `GET /api/config` exposes both presets. The public video example is `python examples/python/video_chat.py`; its paths and input are editable in the script. The same request accepts `video_target_canvas`, `video_group_size`, and `video_images_per_group`; omission uses 12/20/4 for 15s or 12/40/4 for the optional 30s preset. Source records contain `windows_by_interval`; job responses and the ready event contain the actual `windows` list of `{id,start_s,end_s,duration_s}`. UI card ranges, countdowns and completion use this list. The public native timed-window API exposes the same controls; legacy fixed-frame input remains available separately.

`timeline.json` includes the effective profile and sampled queue/feed-lag telemetry alongside first-visible-text, last-text and SDK-completion timestamps. Timing excludes model initialization and source preparation. Queue occupancy includes the open future window; it alone does not imply backlog.

## Architecture and outputs

`source.py` schedules windows over the SDK’s public `VideoSource` container transport; it only demuxes original compressed packets with PyAV; no pixels, resizing, frame selection, canvases or model prompts are computed in Python. `policy.py` owns the English question and segment schedule. The browser reports media time every 100 ms. The worker retries unchanged packets on backpressure and drains byte output with per-segment incremental UTF-8 decoders. All SDK calls, including stop/reset, occur on this worker. The shared library performs native decoding and inference.

SSE events are appended to a per-job disk journal rather than stopped at a fixed event count. Completed sessions write answers and `timeline.json` to `RUNS_DIR/JOB_ID`; optional browser measurements go to `browser.json`. The [Python API](../sdk/PYTHON_API.md) and [C ABI guide](../docs/C_ABI.md) describe the SDK contract; internal regression tools and reports are maintained in GitLab.

The default clip is a continuous 180-second fixed-camera cafe scene from the MEVA dataset by Kitware Inc. and IARPA, under CC BY 4.0. The page retains creator attribution, dataset/source/license links, a modification notice and a warranty-disclaimer link. Keep these credits with commercial website recordings. See [media credits](media/README.md).

See [Runtime settings](../sdk/RUNTIME_API.md) for supported configuration and ownership rules. Omit `--models` only when the default model layout is unambiguous. `--models` and `--model-dir` select the exact models.json package root.

The **Analysis prompt** field is always visible below the video controls. Edit it directly while idle; the counter enforces 200 whitespace-separated words and 2,048 UTF-8 bytes. **Restore default** restores interval-aware instructions. A session freezes its prompt; reset before editing. Output word/token limits remain independent.

## Failure recovery

If the model fails to load, check the model download and runtime setup, then
select **Reload model**. The server log shows the load error. For readiness
checks, `GET /api/ready` returns HTTP 200 when the model is ready and HTTP 503
while it is loading or unavailable.

Control requests time out after 10 seconds; uploads have a 120-second deadline.
If a request fails, pause playback and use **Retry connection** to recover the
current session before starting another one. A lost start response may still
have created a session. Retry preserves existing summaries.

After inference failure, use **Reload model**. The SDK owner closes the old
engine before constructing a replacement. Results remain visible; use **Reset**
to start a new session once the model is ready. A load failure can be retried.
If native cleanup fails, restart the service rather than loading another engine.

## Final short window

A 17-second source at 24 FPS produces **[0,15)** and **[15,17)**, including the 2-second tail. The default canvas budget stays 12 for each window; it is not scaled by 2/15. The tail is split into 3 equal-duration groups over its own 2 seconds. Its 48 distinct frames yield 16 candidates/group and 4 canvases/group: **48 candidates -> 12 canvases**. At 30 FPS, the same 2-second tail has 60 frames and can use all 20 candidates/group.

For a 0.9-second 10 FPS source,9 distinct frames split into3groups of 3: actual canvases are3+3+3=9. No repeated/black frames are added to reach 12. An entirely frame-empty window, or material without usable codec records, fails explicitly. The optional 30s preset applies the same tail rule with 40 candidate frames/group.

The worker performs early-group codec/ViT/prefill during playback. Final-group work and summary wait for the actual window end; decoder references continue across windows, while language KV resets after each independent summary. At EOF the decoder is flushed once and remaining summaries are drained before the UI says complete. A tail’s default prompt labels its actual duration; a custom prompt is passed unchanged.

# Demo media

Default: `cafe.mp4`, a continuous 180-second fixed-camera view of a staged cafe / refreshment area. People enter, leave, walk, use the counter and sit down. No audio track.

Footage: **“Multiview Extended Video with Activities” (MEVA) dataset by Kitware Inc. and IARPA**, [dataset](https://mevadata.org/), [source clip](https://mevadata-public-01.s3.amazonaws.com/drops-123-r13/2018-03-07/16/2018-03-07.16-50-00.16-55-00.school.G421.r13.avi). Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); full authoritative terms and warranty disclaimer: [LICENSE-MEVA.txt](LICENSE-MEVA.txt).

Edits: first 180 seconds selected; decoded timestamps rebased to zero; scaled with aspect ratio preserved and padded to 1280×720; re-encoded to H.264 with x264 fast/CRF23, 50 fps (source 30 fps). Normal speed, no loops. No endorsement implied.

Retain creator/source/license credit and the edit notice with website demo recordings. The footage remains CC BY 4.0 material, independently of the application's or SDK's license. Do not impose additional restrictions on this material.

SHA-256: `84f71f8e2602df70f31f9e5e08d7aec9288186bded2bdafd57a45422321643b7`. Exactly 9,000 video frames, 180 seconds.

## Bundled example media

The examples use the same MEVA source clip by Kitware Inc. and IARPA under CC BY 4.0.

- [`cafe15.mp4`](../samples/cafe15.mp4) contains the first 15 seconds of the resized, padded and re-encoded default clip, without audio.
- [`cafe-frame.png`](../samples/cafe-frame.png) is the first frame of the original footage, exported as a PNG at the source dimensions.

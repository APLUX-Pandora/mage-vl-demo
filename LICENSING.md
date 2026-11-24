# Component scope

| Component | Scope | Terms |
| --- | --- | --- |
| demo and examples, C header and Python binding | Supplied source | Apache-2.0, excluding media and attributed third-party portions |
| APLUX-owned SDK engine contributions | Supplied native binary | Pandora Model & SDK License Agreement, limited to APLUX rights |
| nlohmann JSON 3.12.0 | Compiled header implementation | MIT, full copyright and text retained |
| Adapted NumPy 1.26.4 selection/trigonometric arithmetic | Compiled portions | BSD, full copyright and text retained |
| Codec preprocessing adaptation | Compiled portions | Upstream metadata identifies MIT; applicable copyright and license notices remain controlling |
| Default cafe video, sample clip and sample frame | Supplied modified media | MEVA dataset by Kitware Inc. and IARPA, CC BY 4.0. See the [media credits](demo/media/README.md) for the source, edits and full license. |
| OpenCV 4.5.4, ICU 70.1, JPEG 2.1.2 and zlib | Statically linked in the native SDK | Their retained component licenses and notices continue to apply |
| Patched FFmpeg 5.1 pixel/bitcost implementations | Replaceable, separately namespaced shared libraries | LGPL-2.1-or-later; [license and corresponding source](LICENSES/FFmpeg.md) |
| Shared Pandora Runtime | Independent Runtime wheel and C header | [Apache-2.0](LICENSES/Apache-2.0.txt) |
| Qualcomm Genie | Statically linked vendor component | Supplied Qualcomm notices and terms apply |
| Rust tokenizer dependencies | Statically linked components | [Retained open-source notices and licenses](sdk/lib/LICENSES/Genie-Rust-Tokenizer.txt) |
| OpenSSL 3 crypto | Statically linked | Apache-2.0; retained copyright and license text in sdk/lib/LICENSES/OpenSSL.txt |
| Native model-format component | Statically linked vendor component | Applicable supplier terms remain controlling; no additional redistribution rights are granted here |
| Python packages | External application dependencies | Their supplied licenses continue to apply; no dependency is relicensed |
| QNN user-space runtime | Supplied next to the native SDK library | Vendor license and notices in sdk/lib/qnn248/; no additional rights are granted here |
| Model assets, device BSP/firmware and LMS | Supplied separately | Their own terms; no distribution authorization is asserted here |

The Chinese Pandora agreement governs its interpretation as stated in the unchanged agreement. Its restrictions apply only within its stated APLUX scope. Existing upstream permissions, including use, modification or reverse engineering rights granted by applicable third-party licenses, are preserved. This component index grants no additional rights over third-party components.

Model assets have their own terms; the original model card identifies Apache-2.0. No model weights or device firmware files are included in this SDK/application package. The SDK includes matched QNN user-space runtime libraries with their vendor terms. The statically linked vendor portions retain their separate terms.

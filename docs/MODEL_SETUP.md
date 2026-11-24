# Model setup

<a id="external-runtime"></a>

## Device requirements

- A compatible Linux device with Aidlux LMS (`sudo lms check` returns true), drivers, DSP firmware and BSP/FastRPC support.
- Python 3.10–3.12 in the Demo environment (see [Install](../README.md#1-install)).
- The SDK includes its QNN runtime libraries. Do not install QNN separately or set QNN paths.
- The native SDK runs on Linux AArch64. Native LMS must be available to the system loader. Use the SDK and model resources together.

## Targets

Read `/sys/devices/soc0/soc_id` on your device and pick the matching target folder.

| SoC | Target folder | SoC ID |
| --- | --- | --- |
| QCS8550 | `qcs8550_qnn248` | 603 |
| QCS8625 | `qcs8625_qnn248` | 702 |
| QCS8275 | `qcs8275_qnn248` | 675 |
| QCS9075 | `qcs9075_qnn248` | 676 |

QCS8275 also supports the QCS8625 target.

<a id="download-one-target"></a>

## Download

Replace `<target-folder>` with a folder from the table above.

From the Demo root, in the activated environment, download the shared resources once and then one target:

```bash
hf download APLUX-Pandora/Mage-VL --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Mage-VL --local-dir models --include "targets/<target-folder>/*"
```

Run `hf auth login` first if the repository is private. Keep one target per model folder: to switch devices, move the old `targets/` folder out or download into a new folder.

## Folder layout

With the QCS8550 target, `models/` contains these files. The Demo supplies `README.md`, and the Hugging Face CLI keeps its download cache in `.cache/`.

```text
models/
├── LICENSES/
│   ├── Apache-2.0.txt
│   └── MEVA-CC-BY-4.0.txt
├── models.json
├── NOTICE
├── README.md
├── SHA256SUMS
├── tokenizer.json
├── embedding.bin
└── targets/
    └── qcs8550_qnn248/
        ├── veg.serialized.bin.aidem
        ├── mage-vl_qnn248_qcs8550_cl4096_1_of_3.serialized.bin.aidem
        ├── mage-vl_qnn248_qcs8550_cl4096_2_of_3.serialized.bin.aidem
        └── mage-vl_qnn248_qcs8550_cl4096_3_of_3.serialized.bin.aidem
```

The SDK reads `models.json`, checks that the shared resources and one complete target are present, and reports what is missing. `hf download` verifies each large file's checksum.

The SDK selects a target for the detected SoC and reports which target folders it found if the matching files are unavailable.

An explicit model directory path takes priority, then `MAGE_VL_MODELS`, then `./models`. With no explicit path, discovery can also find one unambiguous immediate child package.

## Troubleshooting

| Message or symptom | What to do |
| --- | --- |
| `No complete model target for device SoC …; installed target folders: …` lists an incompatible SoC. | Move the existing `targets/` folder out of the model directory. Pick your device’s folder from [Targets](#targets) and follow [Download](#download). You can also download into a new model directory. |
| No complete model target because files are missing or empty | Download the full target folder for your device. Check that the path points to the directory containing `models.json`. |
| Multiple complete model targets | Keep one compatible target in the selected model directory. |
| Aidlux LMS activation check fails | Ask your device administrator to activate LMS before loading the model. |

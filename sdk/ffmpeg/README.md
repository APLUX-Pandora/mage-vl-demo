# Rebuilding and replacing FFmpeg

The SDK loads two replaceable FFmpeg libraries for pixel decoding and bit-cost extraction. Each library has its own symbol namespace so both variants can run in the same process.

## Rebuild the libraries

Use an AArch64 Linux system with a C compiler, GNU binutils, make, patch, Python 3, tar and xz. From an empty build directory, extract the [corresponding source bundle](ffmpeg-source.tar.xz) and build both libraries. The bundle contains the upstream source, patches, build scripts, license texts and reference symbol maps.

~~~bash
tar -xJf /path/to/ffmpeg-source.tar.xz
sha256sum -c SHA256SUMS
tar -xJf ffmpeg-5.1.tar.xz
bash tools/dependencies/build-codecs-static-board.sh "$PWD/ffmpeg-5.1"
for variant in pixel bitcost; do
  cmp "symbols/$variant-symbols.map" "codec-static-namespaced/$variant-symbols.map"
  bash tools/dependencies/link-codec-shared.sh cc "$variant" \
    "$PWD/codec-static-namespaced" "$PWD/libmage_ffmpeg_$variant.so"
done
~~~

The symbol maps in the bundle describe the supplied build. If you modify FFmpeg, keep the exports in the [replacement ABI header](../include/mage_ffmpeg.h) ABI-compatible and retain the two library names.

## Replace the libraries

Stop the application. In the SDK or C kit, copy the rebuilt libraries to the [lib directory](../lib/) alongside libmage_vl.so. For an installed Python wheel, locate the corresponding directory with the environment’s Python:

~~~bash
python -c 'from pathlib import Path; import _mage_vl_native; print(Path(_mage_vl_native.__file__).parent)'
~~~

Copy the rebuilt libraries to that directory and restart the application. You can replace either variant independently. Check your installation using the image and video examples. The published SDK checksums describe the supplied binaries and will differ for locally modified files.

FFmpeg is distributed under LGPL-2.1-or-later. Your rights to modify or replace the LGPL components and reverse engineer the combined work to debug those modifications are preserved. See the license texts in the source bundle.

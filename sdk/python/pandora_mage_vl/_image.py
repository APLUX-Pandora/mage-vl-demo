"""Bounded local image-file adapter; model tensors and inference stay native."""
from io import BytesIO
import os
from pathlib import Path
import struct
import zlib
from PIL import Image, UnidentifiedImageError
from ._generation import InputError

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _check_png(data):
    """Reject oversized/animated PNGs before the decoder allocates a canvas."""
    position, chunks, saw_data = 8, 0, False
    while position < len(data):
        if len(data) - position < 12:
            raise InputError('Truncated PNG chunk')
        size = struct.unpack_from('>I', data, position)[0]
        kind = data[position + 4:position + 8]
        end = position + 12 + size
        if end > len(data):
            raise InputError('Truncated PNG chunk')
        payload = memoryview(data)[position + 8:end - 4]
        crc = zlib.crc32(payload, zlib.crc32(kind)) & 0xffffffff
        if crc != struct.unpack_from('>I', data, end - 4)[0]:
            raise InputError('Invalid PNG chunk checksum')
        if chunks == 0:
            if kind != b'IHDR' or size != 13:
                raise InputError('PNG must begin with one IHDR chunk')
            width, height = struct.unpack_from('>II', payload)
            if width == 0 or height == 0 or width * height > MAX_PIXELS:
                raise InputError('Image exceeds16 megapixels or has empty dimensions')
        elif kind == b'IHDR':
            raise InputError('Duplicate PNG header')
        if kind in (b'acTL', b'fcTL', b'fdAT'):
            raise InputError('Animated images are unsupported')
        if kind == b'eXIf':
            # EXIF is not used for pixel conversion. Bound parser work if Pillow
            # consults it internally; do not accept repeated-prefix inputs.
            if size > 65536 or bytes(payload[:12]) == b'Exif\x00\x00Exif\x00\x00':
                raise InputError('Unsupported PNG EXIF metadata')
        if kind == b'IDAT':
            saw_data = True
        if kind == b'IEND':
            if size != 0 or not saw_data or end != len(data):
                raise InputError('Invalid PNG end or trailing data')
            return
        position, chunks = end, chunks + 1
    raise InputError('PNG end chunk is missing')


def read_image(path):
    if not isinstance(path, (str, os.PathLike)):
        raise InputError('images must name one local file')
    try:
        path = Path(path).expanduser()
        if not path.is_file():
            raise InputError('images must name one local file')
        # Validate and decode the same bounded byte snapshot; never reopen a path
        # after checking it, since its contents may have changed.
        with path.open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if not 0 < len(data) <= MAX_FILE_BYTES:
            raise InputError('Image must be a nonempty local file up to64MiB')
        if data.startswith(PNG_SIGNATURE):
            _check_png(data)
        elif not data.startswith(b'\xff\xd8\xff'):
            raise InputError('Use a JPEG or PNG image')
        with Image.open(BytesIO(data), formats=['JPEG', 'PNG']) as source:
            if source.format not in ('JPEG', 'PNG'):
                raise InputError('Use a single JPEG or PNG image')
            if getattr(source, 'n_frames', 1) != 1:
                raise InputError('Animated images are unsupported')
            if source.width * source.height > MAX_PIXELS:
                raise InputError('Image exceeds16 megapixels')
            # Decode at full scale. Never use draft()/thumbnail(), whose scaled
            # JPEG decoder has a different security and numerical profile.
            # Match the archived reference without EXIF rotation or padding.
            return source.convert('RGB').resize((512, 288), Image.Resampling.BICUBIC).tobytes()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError(f'Invalid image: {exc}') from exc

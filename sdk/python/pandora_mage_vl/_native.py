"""Load the installed Mage-VL native library once per resolved path."""
import ctypes

from functools import lru_cache
import os
from pathlib import Path

from pandora_runtime import load_library

# Initialize CPython's OpenSSL consumers before the vendor runtime exports its
# legacy crypto symbols into the process-global plugin lookup scope.
import hashlib  # noqa: F401  # initializes CPython's OpenSSL binding
import ssl  # noqa: F401  # initializes CPython's TLS binding

def _library_path(library=None):
    candidate = library if library is not None else os.environ.get('MAGE_VL_LIBRARY')
    if candidate is None:
        import _mage_vl_native
        candidate = Path(_mage_vl_native.__file__).parent / 'libmage_vl.so'
    candidate = Path(candidate).expanduser().resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f'Mage-VL native library not found: {candidate}')
    return str(candidate)

@lru_cache(maxsize=None)
def _load(path):
    load_library()
    return ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)


def library(path=None):
    return _load(_library_path(path))

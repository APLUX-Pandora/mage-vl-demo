"""Explicit process/model-bound lease on native Genie KV state."""
import ctypes as C
import os
from ._generation import InputError, BusyError, ClosedError

BACKEND_CLEANUP_ERRORS = (-4, -6)

class _CacheInfo(C.Structure):
    _fields_ = [('struct_size', C.c_uint32), ('valid', C.c_uint32)] + [
        (name, C.c_uint64) for name in ('cache_id','cached_tokens','backend_tokens',
        'turns','reused_tokens','last_prompt_tokens','last_generated_tokens')]

class DynamicCache:
    """One conversation per model. Close streams, cache, model, then Runtime."""
    def __init__(self):
        self._pid=os.getpid();self._owner=None;self._id=0
        self._closed=False;self._invalid=False;self._busy=False;self._last={}
        self._release_failed=False
    def _check(self, owner=None):
        if os.getpid()!=self._pid:
            raise InputError('Cache inherited across fork; create a new cache after spawn/exec')
        if self._closed: raise ClosedError('Cache is closed')
        if self._invalid: raise InputError('Cache chain ended; close it and create a new DynamicCache')
        if owner is not None and self._owner is not None and self._owner is not owner:
            raise InputError('Cache belongs to a different model instance')
        if self._busy: raise BusyError('Close the active stream before accessing its cache')
    def _bind(self, owner):
        self._check(owner);self._owner=owner;self._busy=True
    def _begin_native(self):
        if not self._id:
            value=C.c_uint64()
            try:
                self._owner._check(self._owner._lib.mage_vl_cache_begin(self._owner._handle,C.byref(value)))
            finally:
                self._id=value.value
    def _native_status(self):
        value=_CacheInfo();value.struct_size=C.sizeof(value)
        self._owner._check(self._owner._lib.mage_vl_cache_get_info(self._owner._handle,self._id,C.byref(value)))
        return {name:(bool(value.valid) if name=='valid' else getattr(value,name))
                for name,_ in value._fields_ if name!='struct_size'}
    def status(self):
        if os.getpid()!=self._pid: raise InputError('Cache belongs to another process')
        if self._closed: raise ClosedError('Cache is closed')
        if self._busy: raise BusyError('Close the active stream before querying cache status')
        if self._id:
            with self._owner._request_lock:
                if self._busy:raise BusyError("Close the active stream before querying cache status")
                state=self._native_status()
                state['valid']=state['valid'] and not self._invalid
                return state
        return {'valid':not self._invalid,'cache_id':0,'cached_tokens':0,
                'backend_tokens':0,'turns':0,'reused_tokens':0,
                'last_prompt_tokens':0,'last_generated_tokens':0,**self._last}
    def _release_native(self):
        owner=self._owner
        status=owner._lib.mage_vl_cache_release(owner._handle,self._id)
        self._release_failed=status in BACKEND_CLEANUP_ERRORS
        if status==0:
            self._id=0
        owner._check(status)

    def _invalidate(self):
        self._invalid=True
        if self._id:
            if not self._release_failed:
                try:
                    self._last=self._native_status()
                except RuntimeError:
                    # Status diagnostics must not prevent checked release.
                    pass
            self._release_native()
        self._last.update(valid=False,backend_tokens=0)
        if self._owner is not None and self._owner._cache_owner is self:
            self._owner._cache_owner=None
    def close(self):
        if os.getpid()!=self._pid: raise InputError('Cannot release an inherited cache')
        if self._closed:return
        if self._busy:raise BusyError('Close the active stream before cache.close()')
        owner=self._owner
        if owner is not None:
            with owner._request_lock:
                if self._busy:raise BusyError("Close the active stream before cache.close()")
                if self._id:
                    self._release_native()
                if owner._cache_owner is self:owner._cache_owner=None
        self._owner=None;self._last={};self._closed=True
    def __enter__(self):self._check();return self
    def __exit__(self,*_):self.close()

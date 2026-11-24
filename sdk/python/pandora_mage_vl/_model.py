"""Adapter for the Pandora simplified VLM generation contract."""
import codecs
import ctypes as C
import json
import os
import sys
from pathlib import Path

from ._cache import _CacheInfo

from ._generation import (GenerationModelMixin, GenerationCapabilities, GenerationStream,
    GenerationUpdate, prepare_request, InputError, UnsupportedFeatureError,
    BusyError, InferenceError, _remember_cache_cleanup_error)


def install_vlm_api(engine_class, native_error, would_block):
    class VLMModel(GenerationModelMixin, engine_class):
        def __init__(self, model_dir=None, *, library=None, protect_process=False,
                     max_output_tokens=256, max_output_words=60, **options):
            try:
                super().__init__(model_dir, library=library, protect_process=protect_process,
                                 max_output_tokens=max_output_tokens, max_output_words=max_output_words, **options)
                fn = self._lib.mage_vl_configure_request
                fn.argtypes, fn.restype = [C.c_void_p, C.c_char_p], C.c_int32
                fn = self._lib.mage_vl_start_image_rgb
                fn.argtypes, fn.restype = [C.c_void_p, C.c_void_p, C.c_size_t], C.c_int32
                self._cache_owner = None
                for name, args in (
                    ('mage_vl_start_text',[C.c_void_p]),
                    ('mage_vl_cache_begin',[C.c_void_p,C.POINTER(C.c_uint64)]),
                    ('mage_vl_cache_release',[C.c_void_p,C.c_uint64]),
                    ('mage_vl_cache_get_info',[C.c_void_p,C.c_uint64,C.POINTER(_CacheInfo)]),
                    ('mage_vl_configure_cached_request',[C.c_void_p,C.c_uint64,C.c_char_p])):
                    fn=getattr(self._lib,name);fn.argtypes=args;fn.restype=C.c_int32
                fn = self._lib.mage_vl_get_default_max_new_tokens
                fn.argtypes, fn.restype = [C.c_void_p, C.POINTER(C.c_uint32)], C.c_int32
                default_max_tokens = C.c_uint32()
                self._check(fn(self._handle, C.byref(default_max_tokens)))
                self._initialize_generation(GenerationCapabilities(
                    ("image", "video"), ("system", "user", "assistant"), True, ("max_new_tokens", "do_sample", "repetition_penalty")),
                    {"max_new_tokens": default_max_tokens.value, "do_sample": False, "temperature": 1.0,
                     "top_p": 1.0, "top_k": 0, "repetition_penalty": 1.0})
            except BaseException as exc:
                if getattr(self, '_handle', None):
                    engine_class.close(self)
                if isinstance(exc, native_error):
                    raise self._native_error(exc, 'from_pretrained') from exc
                if isinstance(exc, AttributeError):
                    raise UnsupportedFeatureError('VLMModel requires a matching native library with the generation API', operation='from_pretrained') from exc
                if isinstance(exc, OSError):
                    raise InferenceError(str(exc), operation='from_pretrained') from exc
                raise

        @property
        def handle(self):
            self._check_pid()
            return self._handle

        def _native_error(self, error, operation):
            code = error.status
            cls = {-1: InputError, -8: UnsupportedFeatureError, -9: InputError,
                   -10: BusyError}.get(code, InferenceError)
            return cls(str(error), native_code=code, operation=operation)

        def _validate_request(self, request):
            maximum = request.get('max_new_tokens', self.generation_config['max_new_tokens'])
            if maximum >= self.info()['context_tokens'] - 1:
                raise InputError('max_new_tokens exceeds model context')

        def generate_stream(self, prompt=None, *, messages=None, images=None, videos=None,
                            max_new_tokens=None, do_sample=None, temperature=None,
                            top_p=None, top_k=None, repetition_penalty=None, _visual_text=None, _cache=None,
                            video_target_canvas=None, video_group_size=None, video_images_per_group=None):
            self._check_pid()
            with self._request_lock:
                self._check_idle()
                if self._cache_owner is not None and self._cache_owner is not _cache:
                    raise BusyError('A cache conversation owns this model; close its cache first')
                if _cache is not None:
                    _cache._check(self)
                if images is not None and videos is not None:
                    raise InputError('Provide only one visual input')
                request = prepare_request(prompt, messages, dict(max_new_tokens=max_new_tokens,
                    do_sample=do_sample, temperature=temperature, top_p=top_p, top_k=top_k,
                    repetition_penalty=repetition_penalty), self.capabilities.generation_parameters)
                if _visual_text is not None:
                    request["visual_prefix_text"] = _visual_text[0]
                    request["messages"][-1]["content"] = _visual_text[1]
                self._validate_request(request)
                if _cache is not None and _cache._id and _cache._native_status()['turns']:
                    if len(request['messages'])!=1 or request['messages'][0]['role']!='user':
                        raise UnsupportedFeatureError('Cached follow-ups accept one new user message')
                if videos is None and any(v is not None for v in (video_target_canvas,video_group_size,video_images_per_group)):
                    raise InputError('Video codec parameters require a new video in this request')
                request['input_kind']='image' if images is not None else 'video' if videos is not None else 'text'
                if images is not None:
                    from ._image import read_image
                    request['_image'] = read_image(images)
                elif videos is not None:
                    if not isinstance(videos, (str, os.PathLike)):
                        raise InputError('videos must name one local file')
                    path = Path(videos).expanduser()
                    if not path.is_file():
                        raise InputError(f'Video not found: {path}')
                    from ._video import VideoSource, codec_parameters
                    import av
                    try:
                        settings=codec_parameters(video_target_canvas,video_group_size,video_images_per_group)
                        # Lower bound only; native code checks the exact rendered prompt before LM prefill.
                        occupied=_cache._native_status()['cached_tokens'] if _cache is not None and _cache._id else 0
                        limit=request.get('max_new_tokens',self.generation_config['max_new_tokens'])
                        if occupied+settings['target_canvas']*144+limit>=self.info()['context_tokens']:
                            raise InputError('Requested video canvas budget exceeds remaining context')
                        source=VideoSource(path)
                    except (ValueError,OSError,av.error.FFmpegError) as exc:
                        raise InputError(f'Invalid video request: {exc}') from exc
                    request['_source']=source
                    request['video_codec']=dict(settings,frame_times=source.frame_times,duration=source.duration)
                if _cache is not None:request['_cache']=_cache
                stream = GenerationStream(self, request)
                if _cache is not None:
                    _cache._bind(self);self._cache_owner=_cache
                self._active = stream
                return stream

        def generate(self, prompt=None, *, messages=None, images=None, videos=None,
                     max_new_tokens=None, do_sample=None, temperature=None,
                     top_p=None, top_k=None, repetition_penalty=None):
            with self.generate_stream(prompt, messages=messages, images=images, videos=videos,
                    max_new_tokens=max_new_tokens, do_sample=do_sample, temperature=temperature,
                    top_p=top_p, top_k=top_k, repetition_penalty=repetition_penalty) as stream:
                for _ in stream:
                    pass
                return stream.result

        def _iterate(self, request, cancel):
            source = request.get('_source')
            payload = {k: v for k, v in request.items() if not k.startswith('_')}
            decoder = codecs.getincrementaldecoder('utf-8')('strict')
            text, terminal, cursor = '', None, 0
            started = cancelling = False
            cache=request.get('_cache');success=False;entered_execution=False;preserve_input_error=False
            try:
                raw=json.dumps(payload, ensure_ascii=False).encode()
                if cache is None:
                    self.reset()
                    self._check(self._lib.mage_vl_configure_request(self._handle,raw))
                else:
                    cache._begin_native()
                    self._check(self._lib.mage_vl_configure_cached_request(self._handle,cache._id,raw))
                if request['input_kind']=='text':
                    self._check(self._lib.mage_vl_start_text(self._handle))
                elif source is None:
                    image = request['_image']
                    buffer = C.create_string_buffer(image)
                    self._check(self._lib.mage_vl_start_image_rgb(self._handle, buffer, len(image)))
                else:
                    self.open_stream(source.metadata, source.extradata, source.keyframes)
                    self.enqueue(0, 0, source.metadata['frame_count'], request['messages'][-1]['content'],
                        group_frames=1, sampled_frames_per_group=request['video_codec']['group_size'],
                        canvases_per_group=request['video_codec']['images_per_group'])
                started = True
                if cache is not None:
                    request['_cache_abort_pending']=True
                eof = False
                while terminal is None:
                    if cancel.is_set() and not cancelling:
                        try:
                            self.abort(0)
                        except BaseException as exc:
                            if cache is not None:
                                _remember_cache_cleanup_error(request, None, exc)
                            raise
                        request.pop('_cache_abort_pending',None)
                        cancelling = True
                    if not cancelling and source is not None and cursor < len(source.packets):
                        packet = source.packets[cursor]
                        try:
                            self.feed(packet.data, packet.pts, packet.dts, packet.duration, packet.flags)
                            cursor += 1
                        except would_block:
                            pass
                    elif not cancelling and source is not None and not eof:
                        self.finish_input()
                        eof = True
                    try:
                        entered_execution=True
                        self.next()
                    except would_block:
                        pass
                    delta_parts = []
                    while True:
                        item = self.read_text()
                        if item is None:
                            break
                        segment, raw = item
                        if segment != 0:
                            raise InferenceError('Output belongs to a different request')
                        delta = decoder.decode(raw)
                        if delta:
                            delta_parts.append(delta)
                    while True:
                        event = self.read_event()
                        if event is None:
                            break
                        if event['type'] in (3, 4):
                            terminal = event['stop_reason']
                            request.pop('_cache_abort_pending',None)
                    if delta_parts:
                        delta = ''.join(delta_parts)
                        text += delta
                        yield GenerationUpdate(text, delta)
                tail = decoder.decode(b'', final=True)
                if tail:
                    text += tail
                    yield GenerationUpdate(text, tail)
                reason = {1: 'stop', 2: 'length', 4: 'cancelled'}.get(terminal)
                if reason is None:
                    raise InferenceError('Runtime did not provide a supported terminal reason')
                success=reason=='stop'
                yield GenerationUpdate(text, '', reason)
            except native_error as exc:
                error = self._native_error(exc, 'generate')
                preserve_input_error=isinstance(error,InputError) and not entered_execution
                if isinstance(error,InputError) and cache is not None:
                    state=cache._native_status()
                    preserve_input_error=bool(state['valid'] and state['backend_tokens']==state['cached_tokens'])
                if isinstance(error, InferenceError):
                    self._failed = True
                raise error from exc
            except UnicodeError as exc:
                self._failed = True
                raise InferenceError('Invalid UTF-8 from native generation', operation='decode') from exc
            finally:
                if cache is not None:
                    original=sys.exc_info()[1]
                    try:
                        if not success and not preserve_input_error:
                            self._cleanup_cached_request(request)
                        request['_cache_cleanup_done']=True
                    except BaseException as exc:
                        if original is None or isinstance(original,GeneratorExit):
                            if isinstance(exc,native_error):
                                raise self._native_error(exc,'request_cleanup') from exc
                            raise
                        _remember_cache_cleanup_error(request, original, exc)
                elif started:
                    try:
                        self.reset()
                    except native_error as exc:
                        self._failed=True
                        raise self._native_error(exc,'request_cleanup') from exc

        def _cleanup_cached_request(self, request):
            cache=request['_cache']
            cache._invalid=True
            if request.get('_cache_abort_pending'):
                try:
                    self.abort(0)
                except native_error as exc:
                    # A terminal event may already be queued when a read is interrupted.
                    if exc.status!=-5 or self.info()['generation_active']:
                        raise
                request.pop('_cache_abort_pending',None)
            cache._invalidate()

        def _on_stream_close(self, request):
            cache=request.get('_cache') if request else None
            if cache is not None:
                try:
                    if not request.get('_cache_cleanup_done'):
                        self._cleanup_cached_request(request)
                        request['_cache_cleanup_done']=True
                finally:
                    cache._busy=False

        def close(self):
            self._check_pid()
            lock = getattr(self, '_request_lock', None)
            if lock is None:
                return engine_class.close(self)
            with lock:
                cache=self._cache_owner
                release_failed=cache is not None and cache._release_failed
                if self._active is not None and not (release_failed and self._active._cleanup_failed):
                    raise BusyError('Close the active LM stream before model.close()')
                if cache is not None and not release_failed:
                    raise BusyError('Close the DynamicCache before model.close()')
                try:
                    engine_class.close(self)
                finally:
                    if not self._handle and cache is not None:
                        cache._invalid=True
                        cache._id=0
                        cache._owner=None
                        cache._last.update(valid=False,backend_tokens=0)
                        cache._busy=False
                        self._cache_owner=None
                        self._active=None

    VLMModel.__name__ = 'VLMModel'
    VLMModel.__qualname__ = 'VLMModel'
    VLMModel.__module__ = 'mage_vl'
    return VLMModel

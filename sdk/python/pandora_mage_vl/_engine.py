"""Serialized ctypes binding of the packet-input/text-output C ABI."""
from __future__ import annotations
import ctypes as C
import math
import os
from pathlib import Path
import threading
from . import _native
from ._runtime import Runtime

U32, U64, I32, I64 = C.c_uint32, C.c_uint64, C.c_int32, C.c_int64
NO_SEGMENT = 2**64 - 1
INTEGER_FIELDS = {U32: (0, 2**32), U64: (0, 2**64),
                  I32: (-2**31, 2**31), I64: (-2**63, 2**63)}


def _check_integer(name, value, field):
    minimum, limit = INTEGER_FIELDS[field]
    if type(value) is not int or not minimum <= value < limit:
        raise ValueError(f'{name} is outside the supported integer range')


def _check_time(name, value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{name} must be a finite number')

WOULD_BLOCK = -7

class SDKError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f"SDK {status}: {message}")

class WouldBlock(SDKError):
    """No input was consumed; advance/drain and retry the same packet."""

class Struct(C.Structure):
    def __init__(self, **values):
        super().__init__()
        self.struct_size = C.sizeof(type(self))
        fields = dict(self._fields_)
        for name, value in values.items():
            field = fields.get(name)
            if field is None:
                raise TypeError(f"Unknown field: {name}")
            if field in INTEGER_FIELDS:
                _check_integer(name, value, field)
            elif field is C.c_double:
                _check_time(name, value)
            setattr(self, name, value)
    def as_dict(self):
        return {name: getattr(self, name) for name, *_ in self._fields_
                if name != 'struct_size' and not name.startswith('reserved')}

class Options(Struct):
    _fields_ = [(n, U32) for n in ('struct_size','abi_version','max_output_tokens','max_output_words','max_queued_segments','reserved0')] + [('max_pending_bytes',U64),('max_output_queue_bytes',U64),('reserved',U64*8)]
class StreamInfo(Struct):
    _fields_ = [('struct_size',U32),('codec',U32)] + [(n,I32) for n in ('width','height','fps_num','fps_den','time_base_num','time_base_den')] + [('stream_start_pts',I64),('frame_count',I64),('extradata',C.POINTER(C.c_uint8)),('extradata_size',C.c_size_t),('keyframe_indices',C.POINTER(I64)),('keyframe_count',C.c_size_t)] + [(n,I32) for n in ('color_primaries','color_transfer','color_matrix','full_range','sample_aspect_num','sample_aspect_den')] + [('reserved',U64*8)]
class Packet(Struct):
    _fields_ = [('struct_size',U32),('flags',U32),('data',C.POINTER(C.c_uint8)),('size',C.c_size_t),('pts',I64),('dts',I64),('duration',I64),('reserved',U64*4)]
class Segment(Struct):
    _fields_ = [('struct_size',U32),('group_frames',U32),('id',U64),('first_frame',I64),('frame_count',I64),('sampled_frames_per_group',U32),('canvases_per_group',U32),('question_utf8',C.c_char_p),('reserved',U64*8)]
class TimeWindow(Struct):
    _fields_ = [('struct_size',U32),('target_canvas',U32),('group_size',U32),('images_per_group',U32),
                ('id',U64),('start_time_s',C.c_double),('end_time_s',C.c_double),
                ('question_utf8',C.c_char_p),('reserved',U64*4)]
class Info(Struct):
    _fields_ = [(n,U32) for n in ('struct_size','abi_version','context_tokens','embedding_elements','visual_tokens_per_canvas','prefill_alignment_tokens','queued_segments','stream_state')] + [('active_segment_id',U64),('generation_active',U32),('input_finished',U32),('reserved',U64*8)]
class Stats(Struct):
    _fields_ = [('struct_size',U32),('reserved0',U32)] + [(n,U64) for n in ('accepted_packets','decoded_pixel_frames','decoded_bitcost_frames','sampled_frames','canvases','vision_calls','prefill_calls','prompt_tokens','generated_tokens','emitted_text_bytes','completed_segments')] + [(n,C.c_double) for n in ('pixel_decode_ms','bitcost_decode_ms','codec_host_ms','vision_host_ms','vision_invoke_ms','prompt_embedding_ms','prefill_ms','decode_ms')] + [('reserved',U64*8)]
class Event(Struct):
    _fields_ = [('struct_size',U32),('type',U32),('segment_id',U64),('stop_reason',U32),('reserved0',U32),('prompt_tokens',U64),('generated_tokens',U64),('emitted_words',U64),('reserved',U64*4)]
class TextInfo(Struct):
    _fields_ = [('struct_size',U32),('reserved0',U32),('segment_id',U64),('reserved',U64*4)]

def prepare_process(*, library=None):
    """Deprecated: process-wide model protection is no longer supported."""
    raise SDKError(-8, 'prepare_process is retired; SDK preserves host policy')

def resolve_model_dir(model_dir=None):
    """Resolve a package root; discovery does not certify contents or hardware."""
    explicit=model_dir if model_dir is not None else os.environ.get('MAGE_VL_MODELS')
    if explicit is not None:
        p=Path(explicit).expanduser().resolve()
        if not (p/'models.json').is_file():raise SDKError(-2,f'Model configuration not found: {p}/models.json; supply --models PACKAGE_ROOT')
        return p
    root=Path.cwd()/'models'
    if (root/'models.json').is_file():return root.resolve()
    choices=sorted(p for p in root.glob('*') if p.is_dir() and (p/'models.json').is_file())
    if len(choices)==1:return choices[0].resolve()
    if choices:raise SDKError(-2,'Multiple model packages; select --models: '+', '.join(str(p) for p in choices))
    raise SDKError(-2,f'No model package in {root}; download the documented HF variant and common assets, or supply --models PACKAGE_ROOT')

class Engine:
    """One loaded handle. All methods, including close, share one lock.

    Callbacks are absent. Returned text is bytes and can split UTF-8; callers
    must use an incremental decoder. The application owns IO and playback time.
    """
    def __init__(self, model_dir=None, *, library=None, protect_process=False, runtime=None, max_output_tokens=256,
                 max_output_words=60, max_queued_segments=2,
                 max_pending_bytes=None, max_output_queue_bytes=None):
        self._pid = os.getpid()
        self._lock = threading.RLock()
        self._owner = C.c_void_p()
        self._runtime = None
        if type(protect_process) is not bool:raise ValueError('protect_process must be boolean')
        model_dir=resolve_model_dir(model_dir)
        self._lib = _native.library(library)
        if runtime is not None and not isinstance(runtime, Runtime):
            raise TypeError('runtime must be a Pandora Runtime')
        self._bind()
        if protect_process:prepare_process(library=library)
        self._runtime = runtime
        options = Options()
        self._check(self._lib.mage_vl_default_options(C.byref(options)))
        for name, value in dict(max_output_tokens=max_output_tokens, max_output_words=max_output_words,
                                max_queued_segments=max_queued_segments, max_pending_bytes=max_pending_bytes,
                                max_output_queue_bytes=max_output_queue_bytes).items():
            if value is not None:
                bits = 64 if name.endswith('bytes') else 32
                if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**bits:
                    raise ValueError(f'{name} must be a positive uint{bits}')
                setattr(options, name, value)
        self.options = options.as_dict()
        try:
            create = self._lib.mage_vl_create_with_runtime
            directory = os.fsencode(model_dir)
            if runtime is None:
                code = create(directory, C.byref(options), None, C.byref(self._owner))
            else:
                with runtime.borrow_handle() as handle:
                    code = create(directory, C.byref(options), handle, C.byref(self._owner))
            self._check(code, self._lib.mage_vl_create_error())
            if not self._owner.value:raise RuntimeError('SDK create returned no owner')
            if self.info()['abi_version'] != 1:raise RuntimeError('Unsupported SDK ABI')
        except BaseException:
            self.close()
            raise
    @property
    def _handle(self):return self._owner.value
    @property
    def runtime(self):
        self._check_pid()
        return self._runtime
    def _check_pid(self):
        if os.getpid()!=self._pid:raise RuntimeError('Model inherited through fork; use spawn/exec and initialize there')
    def _bind(self):
        l = self._lib; h = C.c_void_p
        signatures = {
            'default_options': (I32,[C.POINTER(Options)]),
            'create_with_runtime': (I32,[C.c_char_p,C.POINTER(Options),h,C.POINTER(h)]),
            'destroy_owned': (I32,[C.POINTER(h)]),
            'destroy': (None,[h]), 'create_error': (C.c_char_p,[]), 'create_status': (I32,[]),
            'last_error': (C.c_char_p,[h]), 'get_info': (I32,[h,C.POINTER(Info)]),
            'get_stats': (I32,[h,C.POINTER(Stats)]), 'open_stream': (I32,[h,C.POINTER(StreamInfo)]),
            'open_timed_stream': (I32,[h,C.POINTER(StreamInfo),C.POINTER(C.c_double),C.c_size_t,C.c_double]),
            'enqueue_window': (I32,[h,C.POINTER(TimeWindow)]), 'next_at': (I32,[h,C.c_double]),
            'enqueue_segment': (I32,[h,C.POINTER(Segment)]), 'feed_packet': (I32,[h,C.POINTER(Packet)]),
            'finish_input': (I32,[h]), 'next': (I32,[h]),
            'read_text': (I32,[h,C.POINTER(C.c_uint8),C.c_size_t,C.POINTER(TextInfo)]),
            'configure_packet_generation': (I32,[h,C.c_char_p]),
            'read_event': (I32,[h,C.POINTER(Event)]), 'abort': (I32,[h,U64]), 'reset': (I32,[h]),
        }
        for name,(result,args) in signatures.items():
            fn=getattr(l,'mage_vl_'+name);fn.restype=result;fn.argtypes=args
    def _check(self, code, message=None):
        if code < 0:
            message = message or (self._lib.mage_vl_last_error(self._handle) if self._handle else b'Invalid options')
            raise (WouldBlock if code == WOULD_BLOCK else SDKError)(code,(message or b'Unknown error').decode('utf-8','replace'))
        return code
    def _call(self, name, *args):
        self._check_pid()
        with self._lock:
            if not self._handle:
                raise RuntimeError('Engine is closed')
            return self._check(getattr(self._lib,'mage_vl_'+name)(self._handle,*args))
    def _get(self, name, kind):
        value=kind();self._call(name,C.byref(value));return value.as_dict()
    def info(self):return self._get('get_info',Info)
    def stats(self):return self._get('get_stats',Stats)
    def open_stream(self, metadata, extradata, keyframes, *, frame_times=None, duration=None):
        info=StreamInfo(**metadata)
        extra=(C.c_uint8*len(extradata)).from_buffer_copy(extradata)
        for value in keyframes:
            _check_integer('keyframe index', value, I64)
        keys=(I64*len(keyframes))(*keyframes)
        info.extradata=extra;info.extradata_size=len(extra)
        info.keyframe_indices=keys;info.keyframe_count=len(keys)
        if frame_times is None and duration is None:
            self._call('open_stream',C.byref(info))
        elif frame_times is not None and duration is not None:
            _check_time('duration', duration)
            for value in frame_times:
                _check_time('frame time', value)
            times=(C.c_double*len(frame_times))(*frame_times)
            self._call('open_timed_stream',C.byref(info),times,len(times),duration)
        else:
            raise ValueError('Provide both frame_times and duration for a timed stream')
    def enqueue(self, segment_id, first_frame, frame_count, question, *, group_frames=500, sampled_frames_per_group=40, canvases_per_group=4):
        if not 0 <= segment_id < NO_SEGMENT or first_frame < 0 or frame_count <= 0:
            raise ValueError('Invalid segment interval or ID')
        s=Segment(id=segment_id,first_frame=first_frame,frame_count=frame_count,
                  group_frames=group_frames,sampled_frames_per_group=sampled_frames_per_group,
                  canvases_per_group=canvases_per_group,question_utf8=question.encode('utf-8'))
        self._call('enqueue_segment',C.byref(s))
    def enqueue_window(self, segment_id, start_s, end_s, question, *,
                       video_target_canvas=None, video_group_size=None, video_images_per_group=None):
        from ._video import codec_parameters
        controls=codec_parameters(video_target_canvas,video_group_size,video_images_per_group)
        if type(segment_id) is not int or not 0<=segment_id<NO_SEGMENT:
            raise ValueError('Invalid window ID')
        if not isinstance(question,str) or not question or '\0' in question:
            raise ValueError('Question must be nonempty text without NUL')
        window=TimeWindow(id=segment_id,start_time_s=start_s,end_time_s=end_s,
                          question_utf8=question.encode('utf-8'),**controls)
        return self._call('enqueue_window',C.byref(window))
    def feed(self, data, pts, dts, duration, flags):
        raw=(C.c_uint8*len(data)).from_buffer_copy(data)
        p=Packet(data=raw,size=len(raw),pts=pts,dts=dts,duration=duration,flags=flags)
        self._call('feed_packet',C.byref(p))
    def next(self, *, media_time=None):
        if media_time is None:
            return self._call('next')
        _check_time('media time', media_time)
        return self._call('next_at',media_time)
    def finish_input(self):return self._call('finish_input')
    def abort(self, segment_id):
        _check_integer('segment ID', segment_id, U64)
        return self._call('abort',segment_id)
    def reset(self):return self._call('reset')
    def read_text(self, capacity=4096):
        if not isinstance(capacity,int) or not 0 < capacity <= 2**31-1:
            raise ValueError('Invalid text read capacity')
        raw=(C.c_uint8*capacity)();info=TextInfo()
        n=self._call('read_text',raw,capacity,C.byref(info))
        return (info.segment_id,bytes(raw[:n])) if n else None
    def read_event(self):
        event=Event()
        return event.as_dict() if self._call('read_event',C.byref(event)) else None
    def configure_packet_generation(self, parameters):
        import json
        return self._call('configure_packet_generation', json.dumps(parameters).encode())
    def close(self):
        self._check_pid()
        with self._lock:
            if self._owner.value:
                self._check(self._lib.mage_vl_destroy_owned(C.byref(self._owner)))
            self._runtime = None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


from ._model import install_vlm_api
VLMModel = install_vlm_api(Engine, SDKError, WouldBlock)

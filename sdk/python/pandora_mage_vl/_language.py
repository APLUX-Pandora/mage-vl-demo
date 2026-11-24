"""LM v1 application entry; model inference remains in the shared native SDK."""
from dataclasses import dataclass
from collections.abc import Mapping
import os
from pathlib import Path
from ._engine import VLMModel as _VLMModel, Engine as _PacketEngine
from ._generation import InputError, UnsupportedFeatureError
from ._cache import DynamicCache

@dataclass(frozen=True)
class Capabilities:
    input_types: tuple = ('text', 'image', 'video')
    output_types: tuple = ('text',)
    streaming: bool = True
    generation_parameters: tuple = ('max_new_tokens', 'do_sample', 'repetition_penalty')
    text_only: bool = True
    max_media_per_request: int = 1
    cross_turn_cache: bool = True
    cache_integration_status: str = 'native_single_conversation'
    cached_followup_media: bool = True
    video_parameters: tuple = ('video_target_canvas', 'video_group_size', 'video_images_per_group')
    max_instances_per_process: int = 1

def _adapt_messages(messages):
    if not isinstance(messages, (list, tuple)) or not messages:
        raise InputError('messages must be a nonempty sequence')
    copied = []
    media = None
    before, after = '', ''
    for index, message in enumerate(messages):
        if not isinstance(message, Mapping) or set(message) != {'role', 'content'}:
            raise InputError('Each message requires role and content')
        role, content = message['role'], message['content']
        if isinstance(content, str):
            text = content
        elif isinstance(content, (list, tuple)) and content:
            pieces = []
            seen = False
            for item in content:
                if not isinstance(item, Mapping) or 'type' not in item:
                    raise InputError('Each content item requires type and its matching field')
                kind = item['type']
                if kind not in ('text', 'image', 'video', 'audio'):
                    raise UnsupportedFeatureError('Unsupported content type')
                if set(item) != {'type', kind}:
                    raise InputError('Content items require only type and its matching field')
                value = item[kind]
                if kind == 'text':
                    if not isinstance(value, str):
                        raise InputError('Text content must be a string')
                    pieces.append(value)
                    if index == len(messages)-1:
                        if seen: after += value
                        else: before += value
                else:
                    if kind == 'audio':
                        raise UnsupportedFeatureError('This SDK build has no audio input adapter')
                    if role != 'user' or index != len(messages)-1:
                        raise UnsupportedFeatureError('Media history is not yet supported by this SDK adapter')
                    if media is not None:
                        raise UnsupportedFeatureError('This SDK adapter accepts one visual file per request')
                    try:
                        path = os.fspath(value)
                        if not isinstance(path, str) or not path.strip() or '\0' in path:
                            raise ValueError("Empty or invalid media path")
                        value = Path(path).expanduser()
                        if not value.is_file():
                            raise ValueError("Media path must name a local file")
                    except (OSError, RuntimeError, TypeError, ValueError) as exc:
                        raise InputError(f"Invalid {kind} path") from exc
                    media = (kind, value)
                    seen = True
            text = ''.join(pieces)
        else:
            raise InputError('content must be text or a nonempty ordered content list')
        if not text.strip() and not (index == len(messages)-1 and media is not None):
            raise InputError('Text content must be nonempty')
        copied.append({'role': role, 'content': text or '.'})
    return copied, media, (before, after)

class LanguageModel:
    """No implicit conversation history. A caller supplies messages for each request."""
    def __init__(self, model_dir, *, runtime=None):
        self._engine = _VLMModel(model_dir, runtime=runtime)
        self._capabilities = Capabilities()
    @classmethod
    def from_pretrained(cls, model_dir, *, runtime=None):
        return cls(model_dir, runtime=runtime)
    @property
    def capabilities(self): return self._capabilities
    @property
    def runtime(self): return self._engine.runtime
    @property
    def generation_config(self): return self._engine.generation_config
    def generate_stream(self, messages, *, max_new_tokens=None, do_sample=None,
                        temperature=None, top_p=None, top_k=None, repetition_penalty=None,
                        return_audio=False, past_key_values=None,
                        video_target_canvas=None, video_group_size=None, video_images_per_group=None):
        if type(return_audio) is not bool:
            raise InputError('return_audio must be a bool')
        if return_audio:
            raise UnsupportedFeatureError('This SDK outputs text, not audio')
        if past_key_values is not None and not isinstance(past_key_values, DynamicCache):
            raise InputError('past_key_values must be this SDK DynamicCache')
        copied, visual, visual_text = _adapt_messages(messages)
        media_args={} if visual is None else {visual[0]+'s':visual[1]}
        return self._engine.generate_stream(messages=copied, **media_args,
            max_new_tokens=max_new_tokens, do_sample=do_sample, temperature=temperature,
            top_p=top_p, top_k=top_k, repetition_penalty=repetition_penalty,
            _visual_text=visual_text if visual is not None else None, _cache=past_key_values,
            video_target_canvas=video_target_canvas, video_group_size=video_group_size,
            video_images_per_group=video_images_per_group)
    def generate(self, messages, *, max_new_tokens=None, do_sample=None,
                 temperature=None, top_p=None, top_k=None, repetition_penalty=None,
                 return_audio=False, past_key_values=None,
                        video_target_canvas=None, video_group_size=None, video_images_per_group=None):
        with self.generate_stream(messages, max_new_tokens=max_new_tokens, do_sample=do_sample,
                temperature=temperature, top_p=top_p, top_k=top_k,
                repetition_penalty=repetition_penalty, return_audio=return_audio,
                past_key_values=past_key_values, video_target_canvas=video_target_canvas,
                video_group_size=video_group_size, video_images_per_group=video_images_per_group) as stream:
            for _ in stream: pass
            return stream.result
    def close(self): self._engine.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

class VideoPacketModel:
    """Documented public extension for the paced finite-video application.

    Packet delivery and independent windows use the same core as LanguageModel.
    There is no cross-window conversational memory. Request-local KV/prefill is
    an internal native optimization and is retained.
    """
    def __init__(self, model_dir, *, runtime=None, max_output_tokens=256, max_output_words=60,
                 do_sample=None, repetition_penalty=None):
        from ._generation import resolve_generation
        parameters = resolve_generation(dict(
            max_new_tokens=256 if max_output_tokens is None else max_output_tokens,
            do_sample=do_sample, repetition_penalty=repetition_penalty))
        self._engine = _PacketEngine(model_dir, runtime=runtime,
            max_output_tokens=parameters['max_new_tokens'], max_output_words=max_output_words)
        try:
            self._engine.configure_packet_generation(parameters)
        except BaseException:
            self._engine.close()
            raise
    @property
    def runtime(self): return self._engine.runtime
    def info(self): return self._engine.info()
    def stats(self): return self._engine.stats()
    def open_stream(self, *args, **kwargs): return self._engine.open_stream(*args, **kwargs)
    def enqueue(self, *args, **kwargs): return self._engine.enqueue(*args, **kwargs)
    def feed(self, *args, **kwargs): return self._engine.feed(*args, **kwargs)
    def enqueue_window(self, *args, **kwargs): return self._engine.enqueue_window(*args, **kwargs)
    def next(self, **kwargs): return self._engine.next(**kwargs)
    def finish_input(self): return self._engine.finish_input()
    def read_text(self, *args, **kwargs): return self._engine.read_text(*args, **kwargs)
    def read_event(self): return self._engine.read_event()
    def reset(self): return self._engine.reset()
    def abort(self, *args): return self._engine.abort(*args)
    def close(self): return self._engine.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

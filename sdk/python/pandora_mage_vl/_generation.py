"""Text-generation API primitives; no tokenizer or tensor dependency."""
from __future__ import annotations
from dataclasses import dataclass
import math
import threading
from types import MappingProxyType


class GenerationError(RuntimeError):
    def __init__(self, message, *, native_code=None, operation=None):
        super().__init__(message)
        self.native_code = native_code
        self.operation = operation


class InputError(GenerationError, ValueError):
    pass


class UnsupportedFeatureError(GenerationError):
    pass


class BusyError(GenerationError):
    pass


class ClosedError(GenerationError):
    pass


class InferenceError(GenerationError):
    pass


@dataclass(frozen=True)
class GenerationResult:
    text: str
    audio: object
    finish_reason: str

    @property
    def is_complete(self):
        return self.finish_reason == "stop"


@dataclass(frozen=True)
class GenerationUpdate:
    text: str
    delta: str
    finish_reason: str | None = None

    @property
    def is_final(self):
        return self.finish_reason is not None


@dataclass(frozen=True)
class GenerationCapabilities:
    input_types: tuple
    message_roles: tuple
    streaming: bool
    generation_parameters: tuple
    max_concurrent_requests: int = 1
    max_instances_per_process: int = 1


def prepare_request(prompt, messages, parameters, supported):
    if (prompt is None) == (messages is None):
        raise InputError("Provide exactly one of prompt or messages")
    if prompt is not None:
        messages = [{"role": "user", "content": prompt}]
    if not isinstance(messages, (list, tuple)) or not messages:
        raise InputError("messages must be a nonempty list or tuple")
    copied, previous = [], None
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise InputError("Each message requires only role and content")
        role, content = message["role"], message["content"]
        if not isinstance(role, str):
            raise InputError("Message role must be a string")
        if role not in ("system", "user", "assistant"):
            raise UnsupportedFeatureError(f"Unsupported message role: {role}")
        if not isinstance(content, str) or not content.strip() or "\0" in content:
            raise InputError("Message content must be nonempty text without NUL")
        try:
            content.encode("utf-8")
        except UnicodeError as exc:
            raise InputError("Message content must be valid UTF-8") from exc
        if "<｜" in content or "<|" in content:
            raise InputError("Model control markers must not occur in message content")
        if role == "system":
            valid = index == 0
        elif role == "user":
            valid = previous in (None, "system", "assistant")
        else:
            valid = previous == "user"
        if not valid:
            raise InputError("Expected optional system then alternating user/assistant messages")
        copied.append({"role": role, "content": content})
        previous = role
    if previous != "user":
        raise InputError("Last message must be user")
    return {"messages": copied, **resolve_generation(parameters, supported)}


def resolve_generation(parameters, supported=None):
    explicit = {k: v for k, v in parameters.items() if v is not None}
    for key, value in explicit.items():
        if key == "do_sample":
            valid = isinstance(value, bool)
        elif key in ("max_new_tokens", "top_k"):
            valid = isinstance(value, int) and not isinstance(value, bool) and value >= (1 if key == "max_new_tokens" else 0)
            if key == "top_k": valid = valid and value <= 0xffffffff
        else:
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
            if key == "top_p":
                valid = valid and value <= 1
        if not valid:
            raise InputError(f"Invalid {key}")
    if not explicit.get("do_sample", False) and any(k in explicit for k in ("temperature", "top_p", "top_k")):
        raise InputError("Explicit sampling parameters conflict with do_sample=False")
    if explicit.get("do_sample", False):
        raise UnsupportedFeatureError("Sampling is not supported by this Mage adapter")
    if explicit.get("repetition_penalty", 1.0) != 1.0:
        raise UnsupportedFeatureError("Only repetition_penalty=1 is supported")
    if supported is not None and set(explicit) - set(supported):
        raise UnsupportedFeatureError("Runtime cannot override: " + ", ".join(sorted(set(explicit) - set(supported))))
    return {"do_sample": False, "repetition_penalty": 1.0, **explicit}



def _remember_cache_cleanup_error(request, original, cleanup_error):
    first_error = request.setdefault('_cache_cleanup_error', cleanup_error)
    if original is not None and original is not first_error:
        try:
            original.cache_cleanup_error = first_error
        except BaseException:
            # Some exception types forbid setting attributes.
            pass


class GenerationStream:
    """An owned request. Use with, especially when leaving iteration early."""
    def __init__(self, model, request):
        self._model, self._request = model, request
        self._iterator = None
        self._cancel = threading.Event()
        self._closed = False
        self._result = None
        self._text = ""
        self._error = None
        self._cleanup_failed = False
        self._iterating = threading.Lock()

    def __enter__(self):
        if self._closed:
            raise ClosedError("Generation stream is closed")
        return self

    def __exit__(self, exc_type, error, traceback):
        request = self._request
        cached = request and request.get('_cache') is not None
        try:
            self.close()
        except BaseException as cleanup_error:
            if error is None or not cached:
                raise
            _remember_cache_cleanup_error(request, error, cleanup_error)

    def __iter__(self):
        return self

    def __next__(self):
        model = self._model
        if model is not None and hasattr(model, '_check_pid'):
            model._check_pid()
        if not self._iterating.acquire(blocking=False):
            raise BusyError("Stream iteration is already active")
        try:
            if self._closed or self._result is not None or self._cancel.is_set():
                raise StopIteration
            if self._iterator is None:
                self._iterator = self._model._iterate(self._request, self._cancel)
            try:
                update = next(self._iterator)
            except StopIteration as exc:
                self._error = InferenceError("Generation ended without a final update")
                raise self._error from exc
            except BaseException as exc:
                self._error = exc
                raise
            self._record(update)
            return update
        finally:
            self._iterating.release()

    def _record(self, update):
        self._text = update.text
        if update.is_final:
            self._result = GenerationResult(text=update.text, audio=None, finish_reason=update.finish_reason)

    @property
    def result(self):
        if self._error is not None:
            raise InferenceError("Generation failed; no final result") from self._error
        if self._result is None:
            raise BusyError("Generation has no final result")
        return self._result

    def close(self):
        model = self._model
        if model is not None and hasattr(model, '_check_pid'):
            model._check_pid()
        self._cancel.set()
        with self._iterating:
            if self._closed:
                return
            started = self._iterator is not None
            cached = self._request.get('_cache') is not None
            if started:
                try:
                    if self._result is None and self._error is None:
                        for update in self._iterator:
                            self._record(update)
                            if update.is_final:
                                break
                    self._iterator.close()
                except BaseException as exc:
                    if cached:
                        _remember_cache_cleanup_error(self._request, self._error, exc)
                    if not cached or self._error is None:
                        self._error = exc
                    self._cleanup_failed = True
                    raise
            with self._model._request_lock:
                if hasattr(self._model, "_on_stream_close"):
                    try:
                        self._model._on_stream_close(self._request)
                    except BaseException as exc:
                        if cached:
                            _remember_cache_cleanup_error(self._request, self._error, exc)
                        self._cleanup_failed = True
                        raise
                if self._model._active is self:
                    self._model._active = None
            if started and self._result is None and self._error is None:
                self._result = GenerationResult(text=self._text, audio=None, finish_reason="cancelled")
            self._closed = True
            self._iterator = None
            self._request = None
            self._model = None


class GenerationModelMixin:
    @classmethod
    def from_pretrained(cls, model_dir=None, *, library=None, **options):
        return cls(model_dir, library=library, **options)

    def _initialize_generation(self, capabilities, defaults):
        self._active = None
        self._request_lock = threading.Lock()
        self._failed = False
        self._capabilities = capabilities
        self._generation_config = MappingProxyType(dict(defaults))

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def generation_config(self):
        return self._generation_config

    def _check_idle(self):
        if not self.handle:
            raise ClosedError("Model is closed")
        if self._failed:
            raise InferenceError("Model failed; close and recreate it")
        if self._active is not None:
            raise BusyError("Close the active request before starting another")

    def generate_stream(self, prompt=None, *, messages=None, max_new_tokens=None,
                        do_sample=None, temperature=None, top_p=None, top_k=None,
                        repetition_penalty=None):
        parameters = dict(max_new_tokens=max_new_tokens, do_sample=do_sample,
                          temperature=temperature, top_p=top_p, top_k=top_k,
                          repetition_penalty=repetition_penalty)
        if hasattr(self, '_check_pid'):self._check_pid()
        with self._request_lock:
            self._check_idle()
            request = prepare_request(prompt, messages, parameters, self.capabilities.generation_parameters)
            self._validate_request(request)
            stream = GenerationStream(self, request)
            self._active = stream
            return stream

    def generate(self, prompt=None, *, messages=None, max_new_tokens=None,
                 do_sample=None, temperature=None, top_p=None, top_k=None,
                 repetition_penalty=None):
        with self.generate_stream(prompt, messages=messages, max_new_tokens=max_new_tokens,
                                 do_sample=do_sample, temperature=temperature, top_p=top_p,
                                 top_k=top_k, repetition_penalty=repetition_penalty) as stream:
            for _ in stream:
                pass
            return stream.result

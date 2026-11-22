"""Optional faster-whisper adapter and a backend-independent ASR facade."""
from __future__ import annotations

from importlib import import_module
from pathlib import Path
import threading

from .errors import MissingDependencyError, ModelUnavailableError, RecognitionError, ValidationError
from .models import Cue, Progress, Subtitle
from .recognition import ASRBackend, CancelCheck, ProgressCallback, check_cancelled, local_file, path_option


def _model_directory(model: str, *, cache_dir: str | None, local_files_only: bool, revision: str | None) -> str:
    """Resolve cached weights before construction to prevent tokenizer fallback downloads."""
    path = Path(model).expanduser()
    if not path.is_dir():
        if model.startswith(("/", "./", "../", "~/")):
            raise ModelUnavailableError("Local ASR model directory does not exist")
        download = import_module("faster_whisper.utils").download_model
        try:
            resolved = download(model, cache_dir=cache_dir, local_files_only=True, revision=revision)
        except Exception as exc:
            if local_files_only:
                raise
            errors = import_module("huggingface_hub.errors")
            missing = tuple(getattr(errors, name) for name in ("LocalEntryNotFoundError", "IncompleteSnapshotError") if isinstance(getattr(errors, name, None), type))
            if not isinstance(exc, missing):
                raise
            resolved = download(model, cache_dir=cache_dir, local_files_only=False, revision=revision)
        path = Path(resolved)
    # faster-whisper can otherwise fetch an OpenAI tokenizer even when its
    # model downloader was offline. Never permit that implicit fallback.
    if not all((path / filename).is_file() for filename in ("model.bin", "config.json", "tokenizer.json")):
        raise ModelUnavailableError("ASR model must contain model.bin, config.json and tokenizer.json; incomplete models are not loaded")
    return str(path)


class FasterWhisperBackend:
    """Cache/download on first use, never on import or construction.

    Reuse one instance to reuse loaded weights. local_files_only=True forbids
    Hub downloads; cache_dir=None honors the upstream Hugging Face cache.
    CUDA libraries must be installed separately when selecting device='cuda'.
    """

    def __init__(
        self, model: str | Path = "small", *, device: str = "cpu",
        compute_type: str = "int8", cache_dir: str | Path | None = None,
        local_files_only: bool = False, revision: str | None = None,
        beam_size: int = 5, vad_filter: bool = True,
    ) -> None:
        if not isinstance(model, (str, Path)) or not str(model).strip():
            raise ValidationError("model must be a model name or local directory")
        if device not in {"cpu", "cuda", "auto"}:
            raise ValidationError("ASR device must be cpu, cuda or auto")
        if not isinstance(compute_type, str) or not compute_type.strip():
            raise ValidationError("compute_type must be a non-empty string")
        if type(local_files_only) is not bool or type(vad_filter) is not bool:
            raise ValidationError("local_files_only and vad_filter must be booleans")
        if type(beam_size) is not int or beam_size < 1:
            raise ValidationError("beam_size must be a positive integer")
        if revision is not None and (not isinstance(revision, str) or not revision.strip()):
            raise ValidationError("revision must be a non-empty string or None")
        self._model_name = str(model.expanduser().absolute()) if isinstance(model, Path) else model
        cache = path_option(cache_dir, "cache_dir")
        self._options = dict(device=device, compute_type=compute_type,
                             download_root=str(cache) if cache is not None else None,
                             local_files_only=local_files_only, revision=revision)
        self._beam_size, self._vad_filter = beam_size, vad_filter
        self._model = None
        self._lock = threading.RLock()

    def prepare(self) -> FasterWhisperBackend:
        """Explicitly warm up (and, unless offline, download) the model."""
        with self._lock:
            if self._model is None:
                try:
                    factory = import_module("faster_whisper").WhisperModel
                except (ImportError, OSError):
                    raise MissingDependencyError('ASR needs optional dependencies: python -m pip install "reibosub[asr]"') from None
                try:
                    directory = _model_directory(self._model_name, cache_dir=self._options["download_root"],
                                                 local_files_only=self._options["local_files_only"], revision=self._options["revision"])
                    self._model = factory(directory, **(self._options | {"local_files_only": True}))
                except Exception:
                    raise ModelUnavailableError("Could not load ASR model. Check the model/cache path, offline policy, network and device runtime. No packages were installed or fallback model selected.") from None
        return self

    def close(self) -> None:
        """Drop this instance's model reference; allocator memory release is runtime-specific."""
        with self._lock:
            self._model = None

    def transcribe(
        self, source: Path, *, language: str | None = None,
        on_progress: ProgressCallback | None = None, cancelled: CancelCheck | None = None,
    ) -> Subtitle:
        check_cancelled(cancelled)
        source = local_file(source)
        with self._lock:
            self.prepare()
            check_cancelled(cancelled)
            try:
                segments, info = self._model.transcribe(str(source), language=language,
                                                       beam_size=self._beam_size, vad_filter=self._vad_filter)
                iterator = iter(segments)
                total = max(0, int(float(info.duration) * 1000))
            except Exception:
                raise RecognitionError("ASR could not decode/transcribe the local media file") from None
            cues, discarded = [], 0
            while True:
                check_cancelled(cancelled)
                try:
                    segment = next(iterator)
                except StopIteration:
                    break
                except Exception:
                    raise RecognitionError("ASR failed while decoding/transcribing media; no partial subtitle was returned") from None
                try:
                    text = segment.text.strip()
                    start, end = float(segment.start), float(segment.end)
                    # Do not invent timings for empty or zero-duration segments.
                    if not text or end == start:
                        discarded += 1
                        continue
                    cue = Cue(len(cues) + 1, start, end, text)
                except (AttributeError, TypeError, ValueError, ValidationError):
                    raise RecognitionError("ASR returned invalid text or timestamps") from None
                cues.append(cue)
                if on_progress is not None:
                    on_progress(Progress(min(total, int(end * 1000)), total, "asr"))
            check_cancelled(cancelled)
            if on_progress is not None:
                on_progress(Progress(total, total, "asr"))
            notices = (f"Discarded {discarded} empty or zero-duration ASR segments; no timing was fabricated.",) if discarded else ()
            return Subtitle(tuple(cues), language=language or getattr(info, "language", None), notices=notices)


class ASR:
    """Python ASR entry point; a custom backend needs no faster-whisper install."""

    def __init__(self, backend: ASRBackend | None = None, **options) -> None:
        if backend is not None and options:
            raise ValidationError("Configure custom backend options on the backend itself")
        self.backend = backend if backend is not None else FasterWhisperBackend(**options)
        if not callable(getattr(self.backend, "transcribe", None)):
            raise ValidationError("backend must implement transcribe()")

    def transcribe(
        self, source: str | Path, *, language: str | None = None,
        on_progress: ProgressCallback | None = None, cancelled: CancelCheck | None = None,
    ) -> Subtitle:
        if language is not None and (not isinstance(language, str) or not language.strip()):
            raise ValidationError("language must be a non-empty language code or None")
        check_cancelled(cancelled)
        result = self.backend.transcribe(local_file(source), language=language,
                                         on_progress=on_progress, cancelled=cancelled)
        check_cancelled(cancelled)
        if not isinstance(result, Subtitle):
            raise RecognitionError("ASR backend must return a Subtitle")
        return result

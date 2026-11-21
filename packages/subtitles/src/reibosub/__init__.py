"""ReiboSub's independent programming API (provisional 0.x surface).

Importing this package does not load OCR/ASR, discover credentials, connect to
storage or start a service. Chinese conversion loads OpenCC only when requested.
"""
from .errors import DependencyInstallError, MissingDependencyError, OperationCancelled, ReiboSubError, SubtitleFormatError, TranslationError, ValidationError
from .chinese import convert_text
from .dependencies import FEATURES, FeatureStatus, check_feature, ensure_feature
from .formats import FormatRegistry, SubtitleCodec
from .io import convert, load, save
from .models import Cue, Progress, Subtitle, SubtitleIssue
from .translation import TranslationBackend, Translator, translate

__version__ = "0.1.0"

__all__ = [
    "Cue", "Subtitle", "SubtitleIssue", "Progress", "load", "save", "convert", "convert_text",
    "FormatRegistry", "SubtitleCodec", "TranslationBackend", "Translator", "translate",
    "ReiboSubError", "ValidationError", "SubtitleFormatError", "MissingDependencyError",
    "TranslationError", "OperationCancelled",
    "DependencyInstallError", "FeatureStatus", "FEATURES", "check_feature", "ensure_feature",
]

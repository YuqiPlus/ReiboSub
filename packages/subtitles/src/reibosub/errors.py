"""Public exception types. Filesystem errors retain their standard Python types."""


class ReiboSubError(Exception):
    """Base class for library-domain errors."""


class ValidationError(ReiboSubError, ValueError):
    """Invalid subtitle data or API arguments."""


class SubtitleFormatError(ValidationError):
    """Unknown format or malformed subtitle content."""


class MissingDependencyError(ReiboSubError, ImportError):
    """A requested optional feature is not installed."""


class TranslationError(ReiboSubError):
    """Translation failed or the backend violated the batch contract."""


class OperationCancelled(ReiboSubError):
    """A cooperative cancellation check stopped processing."""


class DependencyInstallError(ReiboSubError):
    """An explicitly requested dependency install was unsafe or unsuccessful."""


class RecognitionError(ReiboSubError):
    """A recognition backend failed or returned malformed results."""


class ModelUnavailableError(RecognitionError):
    """Model initialization failed; local files, network or hardware need attention."""

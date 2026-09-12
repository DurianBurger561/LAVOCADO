"""Semantic errors shared by every screen-capture backend."""


class CaptureError(RuntimeError):
    """Base error for screen-capture failures."""


class CaptureUnavailableError(CaptureError):
    """The selected backend or a required native feature is unavailable."""


class CapturePermissionDeniedError(CaptureError):
    """The user or operating system explicitly denied capture permission."""


class CaptureRecoverableError(CaptureError):
    """A temporary failure may be resolved by reinitializing the backend."""


class CaptureFatalError(CaptureError):
    """An unexpected capture failure cannot be recovered safely."""

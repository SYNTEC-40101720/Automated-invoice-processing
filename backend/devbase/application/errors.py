class JobAlreadyRunningError(RuntimeError):
    """Raised when a second non-terminal job is requested."""


class NoCurrentJobError(RuntimeError):
    """Raised when an operation requires a current job but none exists."""


class JobNotCancellableError(RuntimeError):
    """Raised when the current job has already reached a terminal state."""

from __future__ import annotations


class StepchainError(Exception):
    """Base error for stepchain."""


class StepFailedError(StepchainError):
    """A step failed after exhausting retries or due to deadline constraints."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"Step '{step}' failed: {reason}")
        self.step = step
        self.reason = reason


class ValidationFailedError(StepchainError):
    """A step produced an invalid result (validate hook)."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"Validation failed in step '{step}': {reason}")
        self.step = step
        self.reason = reason

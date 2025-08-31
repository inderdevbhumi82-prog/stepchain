from __future__ import annotations


class StepchainError(Exception):
    """Base error for stepchain."""


class StepFailedError(StepchainError):
    """
    Raised when a step fails after exhausting retries or a retry is prevented due to deadline.

    Args:
      step: Step name.
      reason: Human-readable failure reason.
    """

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"Step '{step}' failed: {reason}")
        self.step = step
        self.reason = reason


class ValidationFailedError(StepchainError):
    """
    Raised when a step's `validate` hook rejects the produced result.

    Args:
      step: Step name.
      reason: Human-readable validation failure.
    """

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"Validation failed in step '{step}': {reason}")
        self.step = step
        self.reason = reason

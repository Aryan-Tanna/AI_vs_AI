"""Typed provider errors. The client retries only the retryable ones."""

from __future__ import annotations


class LLMError(Exception):
    retryable = False


class RateLimitedError(LLMError):
    retryable = True

    def __init__(self, message: str, retry_after_s: float | None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderUnavailableError(LLMError):
    """Server error, overload or timeout."""

    retryable = True


class ContextBudgetExceededError(LLMError):
    """The request is larger than the model or tier accepts. Never retried and never silently truncated."""


class ProviderRequestError(LLMError):
    """A client-side error (bad request, auth). Retrying cannot help."""


class ContentBlockedError(ProviderRequestError):
    """The provider refused to answer (safety block)."""


class SchemaValidationError(LLMError):
    """The model kept returning output that does not match the schema."""

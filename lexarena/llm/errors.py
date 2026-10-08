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


class GenerationRejectedError(LLMError):
    """The provider rejected its own sample (e.g. Groq's server-side check that the JSON matches the schema). A new
    sample can pass, so it is retried like an overload; a model that never conforms still fails after
    `llm.max_attempts` (D-083)."""

    retryable = True


class ContextBudgetExceededError(LLMError):
    """The request is larger than the model or tier accepts. Never retried and never silently truncated."""


class OutputTruncatedError(LLMError):
    """The model stopped at its output-token limit. Retrying the same request would truncate again, so it is
    never retried and never repaired; raise max_output_tokens in config or shrink the task."""


class ProviderRequestError(LLMError):
    """A client-side error (bad request, auth). Retrying cannot help."""


class ContentBlockedError(ProviderRequestError):
    """The provider refused to answer (safety block)."""


class SchemaValidationError(LLMError):
    """The model kept returning output that does not match the schema."""

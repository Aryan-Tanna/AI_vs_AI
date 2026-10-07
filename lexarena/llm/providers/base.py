from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from typing import Any, Protocol

import httpx

from lexarena.llm.errors import (
    ContextBudgetExceededError,
    ProviderRequestError,
    ProviderUnavailableError,
    RateLimitedError,
)
from lexarena.llm.types import LLMRequest, LLMResponse


class Provider(Protocol):
    def complete(self, request: LLMRequest, api_key: str) -> LLMResponse: ...


def error_message(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or err)
    return str(body)


def post_json(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_s: float,
    context_markers: tuple[str, ...],
    retry_after: Callable[[httpx.Response], float | None],
) -> dict[str, Any]:
    """POST and map transport and HTTP failures onto the typed errors the client understands.

    context_markers: lowercase substrings that identify a 400 caused by an oversized request.
    retry_after: reads the provider-specific retry hint (seconds) from a 429 response.
    """
    try:
        response = client.post(url, headers=headers, json=payload, timeout=timeout_s)
    except httpx.TimeoutException as exc:
        raise ProviderUnavailableError(f"timeout: {type(exc).__name__}") from exc
    except httpx.TransportError as exc:
        raise ProviderUnavailableError(f"transport error: {type(exc).__name__}") from exc

    status = response.status_code
    if status == HTTPStatus.OK:
        data = response.json()
        if not isinstance(data, dict):
            raise ProviderRequestError("provider returned a non-object JSON body")
        return data
    message = error_message(response)
    if status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE:
        raise ContextBudgetExceededError(message)
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        raise RateLimitedError(message, retry_after_s=retry_after(response))
    if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise ProviderUnavailableError(f"HTTP {status}: {message}")
    if status == HTTPStatus.BAD_REQUEST and any(
        m in message.lower() or m in response.text.lower() for m in context_markers
    ):
        raise ContextBudgetExceededError(message)
    raise ProviderRequestError(f"HTTP {status}: {message}")

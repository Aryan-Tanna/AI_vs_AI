"""The only way business logic talks to an LLM.

Model, temperature and seed come from config by role; output is validated against a Pydantic schema;
retries and backoff come from config; every call is logged with the session ID; schema-valid responses
are cached by a key that covers everything that can change the output.

Logs carry prompt IDs and hashes, never prompt or response text: prompts can contain real party names
(clerk input), and logs must not.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from lexarena.llm.cache import ResponseCache, request_key
from lexarena.llm.errors import LLMError, RateLimitedError, SchemaValidationError
from lexarena.llm.providers.base import Provider
from lexarena.llm.types import ChatMessage, LLMRequest, LLMResponse, LLMResult
from lexarena.prompts import PromptStore, RenderedPrompt
from lexarena.schemas.config import AppConfig
from lexarena.secrets import SecretStore

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger("lexarena.llm")


class LLMClient:
    def __init__(
        self,
        config: AppConfig,
        secrets: SecretStore,
        prompts: PromptStore,
        providers: Mapping[str, Provider],
        cache: ResponseCache | None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._secrets = secrets
        self._prompts = prompts
        self._providers = providers
        self._cache = cache
        self._sleep = sleep

    def complete_json(
        self, *, role: str, user: RenderedPrompt, schema: type[T], session_id: str, system: RenderedPrompt | None = None
    ) -> LLMResult[T]:
        if not session_id:
            raise ValueError("session_id is required for every LLM call")
        models = self._config.models.by_role()
        if role not in models:
            raise ValueError(f"unknown model role '{role}'")
        model = models[role]
        api_key = self._secrets.get(model.api_key_env)
        provider = self._providers[model.provider]

        prompts = [p for p in (system, user) if p is not None]
        messages = ([ChatMessage(role="system", content=system.text)] if system else []) + [
            ChatMessage(role="user", content=user.text)
        ]
        request = LLMRequest(
            model=model,
            messages=messages,
            json_schema=schema.model_json_schema(),
            schema_name=schema.__name__,
            seed=self._config.seed,
        )
        key = request_key(request)
        event: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "session_id": session_id,
            "role": role,
            "provider": model.provider,
            "model": model.name,
            "family": model.family,
            "temperature": model.temperature,
            "seed": self._config.seed,
            "schema": schema.__name__,
            "prompts": [{"id": p.prompt_id, "sha256": p.sha256} for p in prompts],
            "cache_key": key,
        }

        cached = self._cache.get(key) if self._cache else None
        if cached is not None:
            try:
                value = schema.model_validate_json(cached)
            except ValidationError:
                pass  # stale or corrupt entry: fall through to a real call
            else:
                self._emit(event, outcome="cache_hit", attempts=0, response=None, started=None)
                return LLMResult(
                    value=value,
                    attempts=0,
                    cached=True,
                    input_tokens=None,
                    output_tokens=None,
                )

        started = time.monotonic()
        attempts, transient_failures = 0, 0
        last_error: LLMError | None = None
        response: LLMResponse | None = None
        failed: list[dict[str, Any]] = []
        event["failed_attempts"] = failed  # error class names only, never text
        llm = self._config.llm
        while attempts < llm.max_attempts:
            attempts += 1
            try:
                response = provider.complete(request, api_key)
            except LLMError as exc:
                last_error = exc
                failed.append({"attempt": attempts, "error": type(exc).__name__})
                if not exc.retryable or attempts >= llm.max_attempts:
                    break
                hint = exc.retry_after_s if isinstance(exc, RateLimitedError) else None
                if hint is not None and hint > llm.backoff_max_s:
                    break  # the server wants a longer wait than we allow (e.g. a spent daily quota): fail now
                self._sleep(
                    hint
                    if hint is not None
                    else min(llm.backoff_initial_s * llm.backoff_multiplier**transient_failures, llm.backoff_max_s)
                )
                transient_failures += 1
                continue
            try:
                value = schema.model_validate_json(response.text)
            except ValidationError as exc:
                problems = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
                last_error = SchemaValidationError(f"{schema.__name__} validation failed: {problems}")
                failed.append({"attempt": attempts, "error": type(last_error).__name__})
                repair = self._prompts.render(
                    self._config.prompts.schema_repair.id,
                    self._config.prompts.schema_repair.version,
                    errors=json.dumps(problems),
                )
                request = request.model_copy(
                    update={
                        "messages": [
                            *request.messages,
                            ChatMessage(role="assistant", content=response.text),
                            ChatMessage(role="user", content=repair.text),
                        ]
                    }
                )
                continue
            if self._cache:
                self._cache.put(key, response.text)
            self._emit(event, outcome="ok", attempts=attempts, response=response, started=started)
            return LLMResult(
                value=value,
                attempts=attempts,
                cached=False,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )

        assert last_error is not None
        self._emit(
            event,
            outcome=type(last_error).__name__,
            attempts=attempts,
            response=response,
            started=started,
            error=str(last_error),
        )
        raise last_error

    def _emit(
        self,
        event: dict[str, Any],
        *,
        outcome: str,
        attempts: int,
        response: LLMResponse | None,
        started: float | None,
        error: str | None = None,
    ) -> None:
        record = {
            **event,
            "outcome": outcome,
            "attempts": attempts,
            "input_tokens": response.input_tokens if response else None,
            "output_tokens": response.output_tokens if response else None,
            "finish_reason": response.finish_reason if response else None,
            "latency_s": time.monotonic() - started if started is not None else None,
        }
        if error is not None:
            record["error"] = error
        log.info(json.dumps(record))

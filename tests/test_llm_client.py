from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from lexarena.config import load_config
from lexarena.llm.cache import ResponseCache
from lexarena.llm.client import LLMClient
from lexarena.llm.errors import (
    ContextBudgetExceededError,
    OutputTruncatedError,
    ProviderUnavailableError,
    RateLimitedError,
    SchemaValidationError,
)
from lexarena.llm.types import LLMResponse
from lexarena.prompts import PromptStore
from lexarena.schemas.config import AppConfig
from lexarena.secrets import MissingSecretError, SecretStore
from tests.conftest import CONFIG_V1, PROMPTS_ROOT
from tests.fakes import FakeProvider, text_response

VALID = '{"answer": 365, "unit": "days"}'


class DaysAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: int
    unit: str


class OtherAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int


@pytest.fixture
def cfg() -> AppConfig:
    return load_config(CONFIG_V1)


@pytest.fixture
def secrets(cfg: AppConfig) -> SecretStore:
    names = {m.api_key_env for m in cfg.models.by_role().values()}
    return SecretStore(env_file=None, environ={n: f"key-for-{n}" for n in names})


@pytest.fixture
def prompts() -> PromptStore:
    return PromptStore(PROMPTS_ROOT)


def make_client(
    cfg: AppConfig,
    secrets: SecretStore,
    fake: FakeProvider,
    *,
    cache: ResponseCache | None = None,
    sleeps: list[float] | None = None,
) -> LLMClient:
    record = sleeps if sleeps is not None else []
    return LLMClient(
        cfg,
        secrets,
        PromptStore(PROMPTS_ROOT),
        providers={name: fake for name in cfg.providers},
        cache=cache,
        sleep=record.append,
    )


def test_returns_schema_validated_object(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    fake = FakeProvider([text_response(VALID)])
    result = make_client(cfg, secrets, fake).complete_json(
        role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
    )
    assert result.value == DaysAnswer(answer=365, unit="days")
    assert result.attempts == 1 and not result.cached
    sent = fake.requests[0]
    assert sent.model.name == cfg.models.verifier.name
    assert sent.model.temperature == cfg.models.verifier.temperature
    assert sent.seed == cfg.seed
    assert sent.json_schema == DaysAnswer.model_json_schema()
    assert fake.api_keys == [f"key-for-{cfg.models.verifier.api_key_env}"]


def test_invalid_output_is_repaired_with_versioned_prompt(
    cfg: AppConfig, secrets: SecretStore, prompts: PromptStore
) -> None:
    fake = FakeProvider([text_response('{"answer": "many"}'), text_response(VALID)])
    result = make_client(cfg, secrets, fake).complete_json(
        role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
    )
    assert result.attempts == 2
    second = fake.requests[1].messages
    assert second[-2].role == "assistant" and second[-2].content == '{"answer": "many"}'
    assert second[-1].role == "user" and "answer" in second[-1].content
    repair = cfg.prompts.schema_repair
    template = (PROMPTS_ROOT / f"{repair.id}.v{repair.version}.txt").read_text(encoding="utf-8")
    assert template.split("$errors")[0].strip() in second[-1].content


def test_non_json_output_is_repaired(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    fake = FakeProvider([text_response("Sure! The answer is 365."), text_response(VALID)])
    result = make_client(cfg, secrets, fake).complete_json(
        role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
    )
    assert result.value.answer == 365


def test_gives_up_after_configured_attempts(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    fake = FakeProvider([text_response("{}")] * cfg.llm.max_attempts)
    with pytest.raises(SchemaValidationError):
        make_client(cfg, secrets, fake).complete_json(
            role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
        )
    assert len(fake.requests) == cfg.llm.max_attempts


def test_rate_limit_backs_off_then_succeeds(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    sleeps: list[float] = []
    fake = FakeProvider([RateLimitedError("slow down", retry_after_s=None), text_response(VALID)])
    result = make_client(cfg, secrets, fake, sleeps=sleeps).complete_json(
        role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
    )
    assert result.attempts == 2
    assert sleeps == [cfg.llm.backoff_initial_s]


def test_server_retry_after_is_respected(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    sleeps: list[float] = []
    wait = cfg.llm.backoff_initial_s + 7
    fake = FakeProvider([RateLimitedError("slow down", retry_after_s=wait), text_response(VALID)])
    make_client(cfg, secrets, fake, sleeps=sleeps).complete_json(
        role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
    )
    assert sleeps == [wait]


def test_quota_exhaustion_fails_fast_instead_of_sleeping_for_hours(
    cfg: AppConfig, secrets: SecretStore, prompts: PromptStore
) -> None:
    # Measured 2026-10-06: Gemini free tier answers a spent daily quota with retryDelay ~15206 s.
    sleeps: list[float] = []
    fake = FakeProvider(
        [RateLimitedError("daily quota", retry_after_s=cfg.llm.backoff_max_s + 1), text_response(VALID)]
    )
    with pytest.raises(RateLimitedError):
        make_client(cfg, secrets, fake, sleeps=sleeps).complete_json(
            role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
        )
    assert sleeps == [] and len(fake.requests) == 1


def test_backoff_grows_and_is_capped(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    sleeps: list[float] = []
    fake = FakeProvider([ProviderUnavailableError("busy")] * cfg.llm.max_attempts)
    with pytest.raises(ProviderUnavailableError):
        make_client(cfg, secrets, fake, sleeps=sleeps).complete_json(
            role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
        )
    expected = [
        min(cfg.llm.backoff_initial_s * cfg.llm.backoff_multiplier**i, cfg.llm.backoff_max_s)
        for i in range(cfg.llm.max_attempts - 1)
    ]
    assert sleeps == expected


def test_context_overflow_fails_immediately(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    sleeps: list[float] = []
    fake = FakeProvider([ContextBudgetExceededError("too large")])
    with pytest.raises(ContextBudgetExceededError):
        make_client(cfg, secrets, fake, sleeps=sleeps).complete_json(
            role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
        )
    assert len(fake.requests) == 1 and sleeps == []


def test_a_failed_call_logs_the_tokens_it_was_billed(
    cfg: AppConfig, secrets: SecretStore, prompts: PromptStore, caplog: pytest.LogCaptureFixture
) -> None:
    """D-107: DEV_0007's truncated Gemini calls cost about $0.59 each and logged no tokens at all."""
    fake = FakeProvider([OutputTruncatedError("hit max_output_tokens", input_tokens=1000, output_tokens=65536)])
    with caplog.at_level(logging.INFO, logger="lexarena.llm"), pytest.raises(OutputTruncatedError):
        make_client(cfg, secrets, fake).complete_json(
            role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
        )
    record = json.loads(caplog.records[-1].getMessage())
    assert (record["input_tokens"], record["output_tokens"]) == (1000, 65536)


def test_truncated_output_fails_immediately(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    fake = FakeProvider([OutputTruncatedError("hit max_output_tokens"), text_response(VALID)])
    with pytest.raises(OutputTruncatedError):
        make_client(cfg, secrets, fake).complete_json(
            role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
        )
    assert len(fake.requests) == 1


def test_cache_hit_skips_provider(tmp_path: Path, cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite")
    fake = FakeProvider([text_response(VALID)])
    client = make_client(cfg, secrets, fake, cache=cache)
    user = prompts.render("smoke/dummy", 1)
    first = client.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S1")
    second = client.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S2")
    assert not first.cached and second.cached
    assert second.value == first.value
    assert len(fake.requests) == 1


def test_cache_key_covers_model_schema_and_prompt(
    tmp_path: Path, cfg: AppConfig, secrets: SecretStore, prompts: PromptStore
) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite")
    fake = FakeProvider(
        [text_response(VALID), text_response(VALID), text_response('{"days": 365}'), text_response(VALID)]
    )
    client = make_client(cfg, secrets, fake, cache=cache)
    user = prompts.render("smoke/dummy", 1)
    client.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S")
    client.complete_json(role="clerk_secondary", user=user, schema=DaysAnswer, session_id="S")  # other model
    client.complete_json(role="verifier", user=user, schema=OtherAnswer, session_id="S")  # other schema
    other_prompt = prompts.render("llm/schema_repair", 1, errors="x")
    client.complete_json(role="verifier", user=other_prompt, schema=DaysAnswer, session_id="S")  # other prompt
    assert len(fake.requests) == 4


def test_failed_calls_are_not_cached(
    tmp_path: Path, cfg: AppConfig, secrets: SecretStore, prompts: PromptStore
) -> None:
    cache = ResponseCache(tmp_path / "c.sqlite")
    script: list[LLMResponse | Exception] = [text_response("{}") for _ in range(cfg.llm.max_attempts)]
    fake = FakeProvider([*script, text_response(VALID)])
    client = make_client(cfg, secrets, fake, cache=cache)
    user = prompts.render("smoke/dummy", 1)
    with pytest.raises(SchemaValidationError):
        client.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S")
    assert not client.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S").cached


def test_log_event_has_ids_and_hashes_but_no_text_or_key(
    cfg: AppConfig, secrets: SecretStore, prompts: PromptStore, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeProvider([text_response(VALID)])
    user = prompts.render("smoke/dummy", 1)
    with caplog.at_level(logging.INFO, logger="lexarena.llm"):
        make_client(cfg, secrets, fake).complete_json(
            role="verifier", user=user, schema=DaysAnswer, session_id="SESSION-42"
        )
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "lexarena.llm"]
    assert events, "no LLM log event emitted"
    event = events[-1]
    assert event["session_id"] == "SESSION-42"
    assert event["role"] == "verifier" and event["model"] == cfg.models.verifier.name
    assert event["prompts"] == [{"id": user.prompt_id, "sha256": user.sha256}]
    assert event["outcome"] == "ok"
    blob = json.dumps(events)
    assert user.text not in blob
    assert "key-for-" not in blob


def test_log_event_records_each_failed_attempt(
    cfg: AppConfig, secrets: SecretStore, prompts: PromptStore, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeProvider([ProviderUnavailableError("busy"), text_response('{"answer": "x"}'), text_response(VALID)])
    with caplog.at_level(logging.INFO, logger="lexarena.llm"):
        make_client(cfg, secrets, fake).complete_json(
            role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S"
        )
    event = json.loads(caplog.records[-1].getMessage())
    assert event["attempts"] == 3
    assert [f["error"] for f in event["failed_attempts"]] == ["ProviderUnavailableError", "SchemaValidationError"]
    assert [f["attempt"] for f in event["failed_attempts"]] == [1, 2]


def test_missing_key_fails_before_any_call(cfg: AppConfig, prompts: PromptStore) -> None:
    fake = FakeProvider([text_response(VALID)])
    client = make_client(cfg, SecretStore(env_file=None, environ={}), fake)
    with pytest.raises(MissingSecretError):
        client.complete_json(role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S")
    assert fake.requests == []


def test_session_id_is_required(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    client = make_client(cfg, secrets, FakeProvider([text_response(VALID)]))
    with pytest.raises(ValueError, match="session_id"):
        client.complete_json(role="verifier", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="")


def test_system_prompt_is_sent_first(cfg: AppConfig, secrets: SecretStore, prompts: PromptStore) -> None:
    fake = FakeProvider([text_response(VALID)])
    system = prompts.render("llm/schema_repair", 1, errors="(system test)")
    make_client(cfg, secrets, fake).complete_json(
        role="verifier", system=system, user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S"
    )
    assert [m.role for m in fake.requests[0].messages] == ["system", "user"]


def test_a_per_call_output_cap_lowers_the_role_cap_and_never_raises_it(
    cfg: AppConfig, secrets: SecretStore, prompts: PromptStore
) -> None:
    """D-109: the clerk's repair step has its own, smaller cap."""
    role_cap = cfg.models.verifier.max_output_tokens
    fake = FakeProvider([text_response(VALID), text_response(VALID)])
    client = make_client(cfg, secrets, fake)
    user = prompts.render("smoke/dummy", 1)
    client.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S1", max_output_tokens=100)
    client.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S1", max_output_tokens=role_cap * 2)
    assert [r.model.max_output_tokens for r in fake.requests] == [100, role_cap]


def test_cache_only_mode_never_calls_a_provider(
    tmp_path: Path, cfg: AppConfig, secrets: SecretStore, prompts: PromptStore
) -> None:
    """D-110: a replay that misses the cache stops instead of spending money."""
    from lexarena.llm.errors import CacheMissError

    cache = ResponseCache(tmp_path / "c.sqlite")
    fake = FakeProvider([text_response(VALID)])
    live = make_client(cfg, secrets, fake, cache=cache)
    user = prompts.render("smoke/dummy", 1)
    live.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S1")
    replay = LLMClient(
        cfg, secrets, prompts, {"groq": fake, "gemini": fake, "openrouter": fake}, cache, cache_only=True
    )
    assert replay.complete_json(role="verifier", user=user, schema=DaysAnswer, session_id="S2").cached
    with pytest.raises(CacheMissError):
        replay.complete_json(role="lawyer", user=user, schema=DaysAnswer, session_id="S2")
    assert len(fake.requests) == 1


def _with_fallback_keys(cfg: AppConfig, role: str, spares: tuple[str, ...]) -> AppConfig:
    model = getattr(cfg.models, role).model_copy(update={"fallback_key_envs": spares})
    return cfg.model_copy(update={"models": cfg.models.model_copy(update={role: model})})


def test_a_spent_daily_quota_moves_to_the_next_free_key(secrets: SecretStore, prompts: PromptStore) -> None:
    """D-118: a free key whose daily quota is spent hands the call to the role's next key, without sleeping."""
    base = load_config(CONFIG_V1)
    cfg = _with_fallback_keys(base, "clerk_secondary", ("SPARE_A", "SPARE_B"))
    keys = SecretStore(env_file=None, environ={**{n: f"key-for-{n}" for n in _names(cfg)}})
    sleeps: list[float] = []
    spent = RateLimitedError("daily quota", retry_after_s=cfg.llm.backoff_max_s + 1)
    fake = FakeProvider([spent, spent, text_response(VALID)])
    result = make_client(cfg, keys, fake, sleeps=sleeps).complete_json(
        role="clerk_secondary", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
    )
    assert result.value.answer == 365
    assert fake.api_keys == [f"key-for-{cfg.models.clerk_secondary.api_key_env}", "key-for-SPARE_A", "key-for-SPARE_B"]
    assert sleeps == []


def test_the_logged_key_is_the_one_that_answered(
    secrets: SecretStore, prompts: PromptStore, caplog: pytest.LogCaptureFixture
) -> None:
    """Quota pacing charges each call to the key variable that served it (D-118); names only, never key values."""
    base = load_config(CONFIG_V1)
    cfg = _with_fallback_keys(base, "clerk_secondary", ("SPARE_A",))
    keys = SecretStore(env_file=None, environ={n: f"key-for-{n}" for n in _names(cfg)})
    spent = RateLimitedError("daily quota", retry_after_s=cfg.llm.backoff_max_s + 1)
    with caplog.at_level(logging.INFO, logger="lexarena.llm"):
        make_client(cfg, keys, FakeProvider([spent, text_response(VALID)])).complete_json(
            role="clerk_secondary", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
        )
    line = json.loads(caplog.records[-1].getMessage())
    assert line["api_key_env"] == "SPARE_A"
    assert line["failed_attempts"] == [
        {"attempt": 1, "error": "RateLimitedError", "api_key_env": cfg.models.clerk_secondary.api_key_env}
    ]
    assert "key-for-" not in json.dumps(line)


def test_when_every_key_is_spent_the_rate_limit_is_raised(secrets: SecretStore, prompts: PromptStore) -> None:
    base = load_config(CONFIG_V1)
    cfg = _with_fallback_keys(base, "clerk_secondary", ("SPARE_A",))
    keys = SecretStore(env_file=None, environ={n: f"key-for-{n}" for n in _names(cfg)})
    spent = RateLimitedError("daily quota", retry_after_s=cfg.llm.backoff_max_s + 1)
    fake = FakeProvider([spent, spent, text_response(VALID)])
    with pytest.raises(RateLimitedError):
        make_client(cfg, keys, fake).complete_json(
            role="clerk_secondary", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
        )
    assert len(fake.requests) == 2


def test_other_errors_never_switch_keys(secrets: SecretStore, prompts: PromptStore) -> None:
    """Only a spent quota moves to a spare key; an overloaded server is the same for every key."""
    base = load_config(CONFIG_V1)
    cfg = _with_fallback_keys(base, "clerk_secondary", ("SPARE_A",))
    keys = SecretStore(env_file=None, environ={n: f"key-for-{n}" for n in _names(cfg)})
    fake = FakeProvider([ProviderUnavailableError("503"), text_response(VALID)])
    make_client(cfg, keys, fake).complete_json(
        role="clerk_secondary", user=prompts.render("smoke/dummy", 1), schema=DaysAnswer, session_id="S1"
    )
    assert set(fake.api_keys) == {f"key-for-{cfg.models.clerk_secondary.api_key_env}"}


def _names(cfg: AppConfig) -> set[str]:
    return {k for m in cfg.models.by_role().values() for k in (m.api_key_env, *m.fallback_key_envs)}

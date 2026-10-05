"""Composition root: builds configured components. Business logic receives these; it never builds its own."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from lexarena.llm.cache import ResponseCache
from lexarena.llm.client import LLMClient
from lexarena.llm.providers.base import Provider
from lexarena.llm.providers.gemini import GeminiProvider
from lexarena.llm.providers.openai_compat import OpenAICompatProvider
from lexarena.prompts import PromptStore
from lexarena.schemas.config import AppConfig, GeminiProviderConfig
from lexarena.secrets import SecretStore

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_ROOT = REPO_ROOT / "prompts"
DEFAULT_ENV_FILE = REPO_ROOT / ".env.local"


def build_providers(config: AppConfig, http: httpx.Client) -> dict[str, Provider]:
    providers: dict[str, Provider] = {}
    for name, provider_config in config.providers.items():
        if isinstance(provider_config, GeminiProviderConfig):
            providers[name] = GeminiProvider(provider_config, http)
        else:
            providers[name] = OpenAICompatProvider(provider_config, http)
    return providers


def build_llm_client(
    config: AppConfig,
    env_file: Path | None = DEFAULT_ENV_FILE,
    use_cache: bool = True,
    http: httpx.Client | None = None,
) -> LLMClient:
    cache = ResponseCache(REPO_ROOT / config.llm.cache_path) if (use_cache and config.llm.cache_enabled) else None
    return LLMClient(
        config,
        SecretStore(env_file=env_file),
        PromptStore(PROMPTS_ROOT),
        build_providers(config, http or httpx.Client()),
        cache,
    )


def configure_llm_logging(config: AppConfig) -> None:
    path = REPO_ROOT / config.llm.log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("lexarena.llm")
    if not any(isinstance(h, logging.FileHandler) and Path(h.baseFilename) == path for h in logger.handlers):
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)

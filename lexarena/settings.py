"""Process-level settings from the environment (or .env.local). Only locations, never tuning values."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from lexarena.app import DEFAULT_ENV_FILE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEXARENA_", env_file=DEFAULT_ENV_FILE, extra="ignore")

    config_path: Path

"""API keys and credentials: read from the process environment or a local .env file, never from config."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values


class MissingSecretError(KeyError):
    """Raised when a named secret is absent. The message names the variable, never any value."""


class SecretStore:
    def __init__(self, env_file: Path | None, environ: Mapping[str, str] | None = None) -> None:
        file_values = {k: v for k, v in dotenv_values(env_file).items() if v is not None} if env_file else {}
        process = dict(os.environ if environ is None else environ)
        self._values: dict[str, str] = {**file_values, **process}

    def get(self, name: str) -> str:
        value = self._values.get(name, "").strip().strip('"').strip("'")
        if not value:
            raise MissingSecretError(f"secret '{name}' is not set in the environment or the env file")
        return value

    def __repr__(self) -> str:
        return f"SecretStore(<{len(self._values)} names, values hidden>)"

    __str__ = __repr__

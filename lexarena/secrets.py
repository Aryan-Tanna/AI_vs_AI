"""API keys and credentials: read from the process environment or a local .env file, never from config."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from dotenv import dotenv_values


class MissingSecretError(KeyError):
    """Raised when a named secret is absent. The message names the variable, never any value."""


class SecretStore:
    def __init__(self, env_file: Path | Sequence[Path] | None, environ: Mapping[str, str] | None = None) -> None:
        """`env_file` may be several files, read in order (later files win); the process environment wins over all.

        Which files a process loads decides which credentials it can hold: session processes load only
        `.env.local`; offline and post-verdict processes also load `.env.sealed` (lexarena.storage.factory).
        """
        files = [env_file] if isinstance(env_file, Path) else list(env_file or [])
        file_values: dict[str, str] = {}
        for path in files:
            file_values.update({k: v for k, v in dotenv_values(path).items() if v is not None})
        process = dict(os.environ if environ is None else environ)
        self._values: dict[str, str] = {**file_values, **process}

    def _clean(self, name: str) -> str:
        return self._values.get(name, "").strip().strip('"').strip("'")

    def has(self, name: str) -> bool:
        return bool(self._clean(name))

    def get(self, name: str) -> str:
        value = self._clean(name)
        if not value:
            raise MissingSecretError(f"secret '{name}' is not set in the environment or the env file")
        return value

    def __repr__(self) -> str:
        return f"SecretStore(<{len(self._values)} names, values hidden>)"

    __str__ = __repr__

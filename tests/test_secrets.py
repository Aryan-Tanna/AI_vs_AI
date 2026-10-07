from __future__ import annotations

import re
from pathlib import Path

import pytest
from dotenv import dotenv_values

from lexarena.secrets import MissingSecretError, SecretStore
from tests.conftest import DOCKER_ENV_FILE, ENV_FILE, REPO_ROOT, SEALED_ENV_FILE


def test_reads_from_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("MY_KEY=abc123\n", encoding="utf-8")
    assert SecretStore(env_file=env, environ={}).get("MY_KEY") == "abc123"


def test_process_environment_overrides_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("MY_KEY=from_file\n", encoding="utf-8")
    assert SecretStore(env_file=env, environ={"MY_KEY": "from_env"}).get("MY_KEY") == "from_env"


def test_missing_secret_names_the_variable_only(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER=s3cr3t-value\n", encoding="utf-8")
    store = SecretStore(env_file=env, environ={})
    with pytest.raises(MissingSecretError, match="MY_KEY") as err:
        store.get("MY_KEY")
    assert "s3cr3t-value" not in str(err.value)


def test_missing_env_file_is_allowed() -> None:
    store = SecretStore(env_file=None, environ={"K": "v"})
    assert store.get("K") == "v"


def test_repr_never_shows_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("MY_KEY=very-secret-value\n", encoding="utf-8")
    store = SecretStore(env_file=env, environ={})
    assert "very-secret-value" not in repr(store)
    assert "very-secret-value" not in str(store)


def test_no_real_secret_value_appears_in_tracked_text() -> None:
    if not ENV_FILE.exists():
        pytest.skip(".env.local not present")
    secret_name = re.compile(r"(?i)key|api|password|secret|token|uri")
    env_files = [f for f in (ENV_FILE, SEALED_ENV_FILE, DOCKER_ENV_FILE) if f.exists()]
    values = [v for f in env_files for k, v in dotenv_values(f).items() if v and secret_name.search(k)]
    suffixes = {".py", ".yaml", ".yml", ".txt", ".md", ".json", ".toml"}
    folders = ("config", "prompts", "lexarena", "tests", "docs", "scripts")
    scanned = [p for d in folders for p in (REPO_ROOT / d).rglob("*") if p.is_file() and p.suffix in suffixes]
    scanned += [REPO_ROOT / "pyproject.toml", REPO_ROOT / "docker-compose.yml", REPO_ROOT / "CLAUDE.md"]
    scanned += list(REPO_ROOT.glob("*.example")) + list(REPO_ROOT.glob(".env*.example"))
    leaks = [
        str(p)
        for p in scanned
        if p.exists() and any(v in p.read_text(encoding="utf-8", errors="ignore") for v in values)
    ]
    assert leaks == []

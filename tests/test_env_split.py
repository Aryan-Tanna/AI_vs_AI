"""D-034: sealed and server-side credentials are absent from session processes."""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

from lexarena.secrets import SecretStore
from lexarena.storage.errors import CredentialLeakError
from lexarena.storage.factory import SESSION_FORBIDDEN_SECRETS, SealedProcess, SessionProcess, check_session_secrets
from tests.conftest import DOCKER_ENV_FILE, ENV_FILE, SEALED_ENV_FILE


def _names(path: Path) -> set[str]:
    if not path.exists():
        pytest.skip(f"{path.name} not present (run scripts/make_env.py)")
    return set(dotenv_values(path))


def test_env_local_holds_no_forbidden_credential() -> None:
    assert _names(ENV_FILE) & SESSION_FORBIDDEN_SECRETS == set()


def test_every_sealed_or_server_credential_is_forbidden_to_sessions() -> None:
    restricted = (_names(SEALED_ENV_FILE) | _names(DOCKER_ENV_FILE)) - _names(ENV_FILE)
    assert restricted <= SESSION_FORBIDDEN_SECRETS, restricted - SESSION_FORBIDDEN_SECRETS


def test_session_process_refuses_to_start_with_sealed_file_loaded(tmp_path: Path) -> None:
    sealed = tmp_path / ".env.sealed"
    sealed.write_text("LEXARENA_MONGO_SEALED_URI=mongodb://x\n", encoding="utf-8")
    with pytest.raises(CredentialLeakError, match="LEXARENA_MONGO_SEALED_URI"):
        SessionProcess(SecretStore(env_file=[sealed], environ={}))


@pytest.mark.parametrize("name", sorted(SESSION_FORBIDDEN_SECRETS))
def test_session_process_refuses_forbidden_names_from_the_environment(name: str) -> None:
    with pytest.raises(CredentialLeakError, match=name):
        check_session_secrets(SecretStore(env_file=None, environ={name: "x"}))


def test_session_secrets_cannot_open_the_sealed_database() -> None:
    _names(ENV_FILE)
    with pytest.raises(KeyError, match=r"LEXARENA_(MONGO_SEALED_URI|QDRANT_WRITE_API_KEY)"):
        SealedProcess(SecretStore(env_file=[ENV_FILE], environ={}))

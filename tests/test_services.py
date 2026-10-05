"""docker compose services are reachable. Run with: pytest --run-integration -m integration"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pymongo import MongoClient

from lexarena.secrets import SecretStore
from tests.conftest import ENV_FILE


@pytest.fixture(scope="module")
def secrets() -> SecretStore:
    return SecretStore(env_file=ENV_FILE)


@pytest.mark.integration
def test_mongo_app_user_can_connect(secrets: SecretStore) -> None:
    uri = secrets.get("LEXARENA_MONGO_APP_URI")
    client: MongoClient[dict[str, Any]]
    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        assert client.admin.command("ping")["ok"] == 1


@pytest.mark.integration
def test_mongo_app_user_cannot_read_sealed_database(secrets: SecretStore) -> None:
    uri = secrets.get("LEXARENA_MONGO_APP_URI")
    sealed_db = secrets.get("LEXARENA_MONGO_SEALED_DB")
    client: MongoClient[dict[str, Any]]
    with (
        MongoClient(uri, serverSelectionTimeoutMS=5000) as client,
        pytest.raises(Exception, match=r"(?i)not authorized|unauthorized"),
    ):
        client[sealed_db].list_collection_names()


@pytest.mark.integration
def test_qdrant_is_ready(secrets: SecretStore) -> None:
    url = secrets.get("LEXARENA_QDRANT_URL")
    assert httpx.get(f"{url}/readyz", timeout=5).status_code == 200


@pytest.mark.integration
def test_redis_answers_ping(secrets: SecretStore) -> None:
    import redis

    assert redis.Redis.from_url(secrets.get("LEXARENA_REDIS_URL")).ping()

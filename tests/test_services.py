"""The services enforce credentials themselves, independent of any Python check (D-024, D-034).

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import OperationFailure

from lexarena.secrets import SecretStore
from tests.conftest import ENV_FILE, SEALED_ENV_FILE

pytestmark = pytest.mark.integration
UNAUTHORIZED = r"(?i)not authorized|unauthorized|requires authentication"
Doc = dict[str, Any]


@pytest.fixture(scope="module")
def secrets() -> SecretStore:
    return SecretStore(env_file=[ENV_FILE, SEALED_ENV_FILE], environ={})


@pytest.fixture(scope="module")
def app(secrets: SecretStore) -> Iterator[MongoClient[Doc]]:
    client: MongoClient[Doc] = MongoClient(secrets.get("LEXARENA_MONGO_APP_URI"), serverSelectionTimeoutMS=5000)
    with client:
        yield client


@pytest.fixture(scope="module")
def sealed(secrets: SecretStore) -> Iterator[MongoClient[Doc]]:
    client: MongoClient[Doc] = MongoClient(secrets.get("LEXARENA_MONGO_SEALED_URI"), serverSelectionTimeoutMS=5000)
    with client:
        yield client


@pytest.fixture
def scratch_name() -> str:
    return f"t{uuid.uuid4().hex[:8]}_probe"


def _drop(db: Database[Doc], name: str) -> None:
    db.drop_collection(name)


# ---------------------------------------------------------------- MongoDB: the app user is refused on sealed data


def test_app_user_can_connect(app: MongoClient[Doc]) -> None:
    assert app.admin.command("ping")["ok"] == 1


def test_app_user_cannot_read_sealed_database(app: MongoClient[Doc], secrets: SecretStore) -> None:
    db = app[secrets.get("LEXARENA_MONGO_SEALED_DB")]
    with pytest.raises(OperationFailure, match=UNAUTHORIZED):
        db.list_collection_names()
    with pytest.raises(OperationFailure, match=UNAUTHORIZED):
        db["case_ground_truth"].find_one({})


def test_app_user_cannot_write_sealed_database(app: MongoClient[Doc], secrets: SecretStore) -> None:
    with pytest.raises(OperationFailure, match=UNAUTHORIZED):
        app[secrets.get("LEXARENA_MONGO_SEALED_DB")]["case_ground_truth"].insert_one({"probe": True})


def test_app_user_cannot_grant_itself_more_access(app: MongoClient[Doc], secrets: SecretStore) -> None:
    app_db = app[secrets.get("LEXARENA_MONGO_APP_DB")]
    sealed_db = secrets.get("LEXARENA_MONGO_SEALED_DB")
    with pytest.raises(OperationFailure, match=UNAUTHORIZED):
        app_db.command("grantRolesToUser", "lexarena_app", roles=[{"role": "read", "db": sealed_db}])
    with pytest.raises(OperationFailure, match=UNAUTHORIZED):
        app_db.command("createUser", f"probe_{uuid.uuid4().hex[:6]}", pwd="x", roles=[])
    with pytest.raises(OperationFailure, match=UNAUTHORIZED):
        app.admin.command("usersInfo", {"forAllDBs": True})


# ---------------------------------------------------------------- MongoDB: controls for the sealed user


def test_sealed_user_reads_and_writes_sealed_database(
    sealed: MongoClient[Doc], secrets: SecretStore, scratch_name: str
) -> None:
    db = sealed[secrets.get("LEXARENA_MONGO_SEALED_DB")]
    try:
        db[scratch_name].insert_one({"_id": "probe"})
        assert db[scratch_name].find_one({"_id": "probe"}) == {"_id": "probe"}
    finally:
        _drop(db, scratch_name)


def test_sealed_user_cannot_read_app_database(sealed: MongoClient[Doc], secrets: SecretStore) -> None:
    with pytest.raises(OperationFailure, match=UNAUTHORIZED):
        sealed[secrets.get("LEXARENA_MONGO_APP_DB")].list_collection_names()


def test_no_unauthenticated_access(secrets: SecretStore) -> None:
    url = secrets.get("LEXARENA_MONGO_APP_URI").split("@", 1)[1].split("/", 1)[0]  # host:port, no credentials
    anon: MongoClient[Doc] = MongoClient(f"mongodb://{url}", serverSelectionTimeoutMS=5000)
    with anon, pytest.raises(OperationFailure, match=UNAUTHORIZED):
        anon[secrets.get("LEXARENA_MONGO_SEALED_DB")].list_collection_names()


# ---------------------------------------------------------------- Qdrant: sessions get a read-only key


def test_qdrant_refuses_requests_without_a_key(secrets: SecretStore) -> None:
    url = secrets.get("LEXARENA_QDRANT_URL")
    assert httpx.get(f"{url}/readyz", timeout=5).status_code == httpx.codes.OK
    assert httpx.get(f"{url}/collections", timeout=5).status_code == httpx.codes.UNAUTHORIZED


def test_qdrant_read_only_key_reads_but_cannot_write(secrets: SecretStore, scratch_name: str) -> None:
    url = secrets.get("LEXARENA_QDRANT_URL")
    ro = {"api-key": secrets.get("LEXARENA_QDRANT_READ_ONLY_API_KEY")}
    assert httpx.get(f"{url}/collections", headers=ro, timeout=5).status_code == httpx.codes.OK
    body = {"vectors": {"size": 4, "distance": "Cosine"}}  # literal-ok: throwaway probe collection
    created = httpx.put(f"{url}/collections/{scratch_name}", json=body, headers=ro, timeout=5)
    assert created.status_code == httpx.codes.FORBIDDEN


def test_qdrant_write_key_can_write(secrets: SecretStore, scratch_name: str) -> None:
    url = secrets.get("LEXARENA_QDRANT_URL")
    rw = {"api-key": secrets.get("LEXARENA_QDRANT_WRITE_API_KEY")}
    body = {"vectors": {"size": 4, "distance": "Cosine"}}  # literal-ok: throwaway probe collection
    try:
        assert httpx.put(f"{url}/collections/{scratch_name}", json=body, headers=rw, timeout=5).is_success
    finally:
        httpx.delete(f"{url}/collections/{scratch_name}", headers=rw, timeout=5)


# ---------------------------------------------------------------- Redis


def test_redis_requires_the_password(secrets: SecretStore) -> None:
    import redis

    assert redis.Redis.from_url(secrets.get("LEXARENA_REDIS_URL")).ping()
    with pytest.raises(redis.exceptions.AuthenticationError):
        redis.Redis(host="127.0.0.1", port=6379).ping()  # literal-ok: compose port binding

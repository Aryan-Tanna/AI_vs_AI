"""Which process may hold which credentials, and which repositories each role receives.

Two kinds of process (D-034):

- `SessionProcess` runs a session: orchestrator, both lawyers, both THEMIS-LOCAL instances,
  THEMIS-GLOBAL and the judges. It loads `.env.local` only and refuses to start if any credential from
  `SESSION_FORBIDDEN_SECRETS` is visible to it, including through the process environment. It opens no
  connection to the sealed database and can build no ground-truth repository.
- `SealedProcess` runs offline and post-verdict work: the clerk, the evaluator and the reflection engine.
  It also loads `.env.sealed`. The orchestrator starts it as a separate process after the verdict is
  recorded, so ground-truth credentials never share memory with an agent (Step 13).

Each role gets a bundle holding only the repositories it may use, each bound to that role's principal;
the repositories re-check the policy on every call.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pymongo import MongoClient
from qdrant_client import QdrantClient

from lexarena.schemas.base import Side
from lexarena.schemas.retrieval import CaseScope
from lexarena.secrets import SecretStore
from lexarena.storage.cases import CaseRepository
from lexarena.storage.errors import CredentialLeakError
from lexarena.storage.ground_truth import GroundTruthRepository, JudgmentTextRepository
from lexarena.storage.law import LawRepository
from lexarena.storage.mongo import ROOT_NAMESPACE, Doc, Namespace
from lexarena.storage.policy import Principal, Role
from lexarena.storage.precedents import PrecedentRepository, ScopedPrecedentReader
from lexarena.storage.session_memory import InProcessSessionMemory, SessionMemoryHandle
from lexarena.storage.sessions import SessionRepository
from lexarena.storage.transcript import PrivateTurnRepository, TranscriptRepository

APP_URI = "LEXARENA_MONGO_APP_URI"
APP_DB = "LEXARENA_MONGO_APP_DB"
SEALED_URI = "LEXARENA_MONGO_SEALED_URI"
QDRANT_URL = "LEXARENA_QDRANT_URL"
QDRANT_READ_KEY = "LEXARENA_QDRANT_READ_ONLY_API_KEY"
QDRANT_WRITE_KEY = "LEXARENA_QDRANT_WRITE_API_KEY"

# Everything scripts/make_env.py writes to .env.sealed or .env.docker. A session process must see none of it.
SESSION_FORBIDDEN_SECRETS = frozenset(
    {
        "LEXARENA_MONGO_SEALED_URI",
        "LEXARENA_MONGO_SEALED_DB",
        "LEXARENA_MONGO_SEALED_USER",
        "LEXARENA_MONGO_SEALED_PASSWORD",
        "LEXARENA_MONGO_ROOT_USER",
        "LEXARENA_MONGO_ROOT_PASSWORD",
        "LEXARENA_MONGO_APP_USER",
        "LEXARENA_MONGO_APP_PASSWORD",
        "LEXARENA_QDRANT_WRITE_API_KEY",
        "LEXARENA_QDRANT_SERVER_API_KEY",
        "LEXARENA_QDRANT_SERVER_READ_ONLY_API_KEY",
        "LEXARENA_REDIS_PASSWORD",
    }
)


def check_session_secrets(secrets: SecretStore) -> None:
    visible = sorted(name for name in SESSION_FORBIDDEN_SECRETS if secrets.has(name))
    if visible:
        raise CredentialLeakError(f"a session process must not see these credentials: {visible}")


def open_qdrant(url: str, api_key: str) -> QdrantClient:
    """A Qdrant client. On a loopback URL the key travels over plain HTTP by design (compose binds 127.0.0.1)."""
    import warnings
    from urllib.parse import urlparse

    with warnings.catch_warnings():
        if urlparse(url).hostname in ("127.0.0.1", "localhost"):
            warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")
        return QdrantClient(url=url, api_key=api_key, https=url.startswith("https"))


# ---------------------------------------------------------------- bundles


@dataclass(frozen=True)
class LawyerStores:
    case: CaseRepository
    law: LawRepository
    precedents: ScopedPrecedentReader
    transcript: TranscriptRepository
    memory: SessionMemoryHandle


@dataclass(frozen=True)
class ThemisLocalStores:
    case: CaseRepository
    law: LawRepository
    precedents: ScopedPrecedentReader
    transcript: TranscriptRepository
    private_turns: PrivateTurnRepository
    agent_memory: SessionMemoryHandle  # its own agent's memory, read-only by policy


@dataclass(frozen=True)
class ObserverStores:
    """THEMIS-GLOBAL and the judges: the agent view and the published transcript, nothing else."""

    case: CaseRepository
    law: LawRepository
    precedents: ScopedPrecedentReader
    transcript: TranscriptRepository


@dataclass(frozen=True)
class OrchestratorStores:
    cases: CaseRepository
    law: LawRepository
    precedents: PrecedentRepository
    transcript: TranscriptRepository
    sessions: SessionRepository
    session_memory: InProcessSessionMemory


@dataclass(frozen=True)
class EvaluatorStores:
    cases: CaseRepository
    transcript: TranscriptRepository
    sessions: SessionRepository
    ground_truth: GroundTruthRepository
    judgment_texts: JudgmentTextRepository


@dataclass(frozen=True)
class ReflectionStores:
    cases: CaseRepository
    transcript: TranscriptRepository
    sessions: SessionRepository
    ground_truth: GroundTruthRepository
    judgment_texts: JudgmentTextRepository
    private_turns: PrivateTurnRepository


@dataclass(frozen=True)
class IngestStores:
    """Offline ingestion: writes the Law DB, approved side-collection items and the precedent DB."""

    law: LawRepository
    precedents: PrecedentRepository


@dataclass(frozen=True)
class ClerkStores:
    cases: CaseRepository
    law: LawRepository  # statute IDs for the issues and statutes_invoked (D-035)
    precedents: PrecedentRepository  # overlap check (SPEC B1)
    ground_truth: GroundTruthRepository
    judgment_texts: JudgmentTextRepository


@dataclass(frozen=True)
class ReviewStores:
    """The owner's check of a clerked case before it runs (D-056): read-only; sealed reads close at the first
    session."""

    cases: CaseRepository
    ground_truth: GroundTruthRepository
    judgment_texts: JudgmentTextRepository


# ---------------------------------------------------------------- processes


class _Process:
    def __init__(self, secrets: SecretStore, ns: Namespace, qdrant_key: str) -> None:
        self._ns = ns
        self._qdrant = open_qdrant(secrets.get(QDRANT_URL), secrets.get(qdrant_key))
        self._clients: list[MongoClient[Doc]] = []
        self._app_db = self._open(secrets.get(APP_URI))[secrets.get(APP_DB)]

    def _open(self, uri: str) -> MongoClient[Doc]:
        client: MongoClient[Doc] = MongoClient(uri)
        self._clients.append(client)
        return client

    def close(self) -> None:
        for client in self._clients:
            client.close()
        self._qdrant.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class SessionProcess(_Process):
    def __init__(self, secrets: SecretStore, ns: Namespace = ROOT_NAMESPACE) -> None:
        check_session_secrets(secrets)
        super().__init__(secrets, ns, QDRANT_READ_KEY)
        self._memory = InProcessSessionMemory()

    @classmethod
    def from_env_files(cls, env_files: Sequence[Path], ns: Namespace = ROOT_NAMESPACE) -> SessionProcess:
        return cls(SecretStore(env_file=env_files), ns)

    # Session roles get precedents only through a reader bound to the case's scope, which the orchestrator
    # builds from the full case (CaseScope.from_case); no session bundle holds an unscoped repository (D-052).

    def lawyer(self, side: Side, session_id: str, scope: CaseScope) -> LawyerStores:
        p = Principal(Role.LAWYER, side)
        return LawyerStores(
            case=CaseRepository(p, self._app_db, self._ns),
            law=LawRepository(p, self._app_db, self._ns),
            precedents=ScopedPrecedentReader(p, self._qdrant, scope),
            transcript=TranscriptRepository(p, self._app_db, self._ns),
            memory=self._memory.handle(p, session_id),
        )

    def themis_local(self, side: Side, session_id: str, scope: CaseScope) -> ThemisLocalStores:
        p = Principal(Role.THEMIS_LOCAL, side)
        return ThemisLocalStores(
            case=CaseRepository(p, self._app_db, self._ns),
            law=LawRepository(p, self._app_db, self._ns),
            precedents=ScopedPrecedentReader(p, self._qdrant, scope),
            transcript=TranscriptRepository(p, self._app_db, self._ns),
            private_turns=PrivateTurnRepository(p, self._app_db, self._ns),
            agent_memory=self._memory.handle(p, session_id),
        )

    def themis_global(self, scope: CaseScope) -> ObserverStores:
        return self._observer(Principal(Role.THEMIS_GLOBAL), scope)

    def judge(self, scope: CaseScope) -> ObserverStores:
        return self._observer(Principal(Role.JUDGE), scope)

    def orchestrator(self) -> OrchestratorStores:
        p = Principal(Role.ORCHESTRATOR)
        return OrchestratorStores(
            cases=CaseRepository(p, self._app_db, self._ns),
            law=LawRepository(p, self._app_db, self._ns),
            precedents=PrecedentRepository(p, self._qdrant),
            transcript=TranscriptRepository(p, self._app_db, self._ns),
            sessions=SessionRepository(p, self._app_db, self._ns),
            session_memory=self._memory,
        )

    def _observer(self, p: Principal, scope: CaseScope) -> ObserverStores:
        return ObserverStores(
            case=CaseRepository(p, self._app_db, self._ns),
            law=LawRepository(p, self._app_db, self._ns),
            precedents=ScopedPrecedentReader(p, self._qdrant, scope),
            transcript=TranscriptRepository(p, self._app_db, self._ns),
        )


class SealedProcess(_Process):
    def __init__(self, secrets: SecretStore, ns: Namespace = ROOT_NAMESPACE) -> None:
        super().__init__(secrets, ns, QDRANT_WRITE_KEY)
        self._sealed_db = self._open(secrets.get(SEALED_URI)).get_default_database()

    @classmethod
    def from_env_files(cls, env_files: Sequence[Path], ns: Namespace = ROOT_NAMESPACE) -> SealedProcess:
        return cls(SecretStore(env_file=env_files), ns)

    def evaluator(self) -> EvaluatorStores:
        p = Principal(Role.EVALUATOR)
        return EvaluatorStores(
            cases=CaseRepository(p, self._app_db, self._ns),
            transcript=TranscriptRepository(p, self._app_db, self._ns),
            sessions=SessionRepository(p, self._app_db, self._ns),
            ground_truth=GroundTruthRepository(p, self._sealed_db, self._app_db, self._ns),
            judgment_texts=JudgmentTextRepository(p, self._sealed_db, self._app_db, self._ns),
        )

    def reflection(self, side: Side | None = None) -> ReflectionStores:
        p = Principal(Role.REFLECTION, side)
        return ReflectionStores(
            cases=CaseRepository(p, self._app_db, self._ns),
            transcript=TranscriptRepository(p, self._app_db, self._ns),
            sessions=SessionRepository(p, self._app_db, self._ns),
            ground_truth=GroundTruthRepository(p, self._sealed_db, self._app_db, self._ns),
            judgment_texts=JudgmentTextRepository(p, self._sealed_db, self._app_db, self._ns),
            private_turns=PrivateTurnRepository(p, self._app_db, self._ns),
        )

    def ingest(self) -> IngestStores:
        p = Principal(Role.INGEST)
        return IngestStores(
            law=LawRepository(p, self._app_db, self._ns), precedents=PrecedentRepository(p, self._qdrant)
        )

    def clerk(self) -> ClerkStores:
        p = Principal(Role.CLERK)
        return ClerkStores(
            cases=CaseRepository(p, self._app_db, self._ns),
            law=LawRepository(p, self._app_db, self._ns),
            precedents=PrecedentRepository(p, self._qdrant),
            ground_truth=GroundTruthRepository(p, self._sealed_db, self._app_db, self._ns),
            judgment_texts=JudgmentTextRepository(p, self._sealed_db, self._app_db, self._ns),
        )

    def review(self) -> ReviewStores:
        p = Principal(Role.REVIEW)
        return ReviewStores(
            cases=CaseRepository(p, self._app_db, self._ns),
            ground_truth=GroundTruthRepository(p, self._sealed_db, self._app_db, self._ns),
            judgment_texts=JudgmentTextRepository(p, self._sealed_db, self._app_db, self._ns),
        )

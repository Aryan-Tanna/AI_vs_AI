"""Session-side code cannot even import the way to ground truth (D-034).

Agents, THEMIS, judges and retrieval receive role-bound repositories from the orchestrator; they never
read credentials or open databases themselves. The orchestrator may build a `SessionProcess` but never a
`SealedProcess` or a ground-truth repository; evaluator and reflection run in a separate process.
"""

from __future__ import annotations

import ast

import pytest

from tests.conftest import REPO_ROOT

PACKAGE = REPO_ROOT / "lexarena"
SEALED_PATHS = (
    "lexarena.storage.ground_truth",
    "lexarena.storage.factory.SealedProcess",
    "lexarena.app.SEALED_ENV_FILE",
    "lexarena.evaluator.evaluate",  # opens ground truth after the verdict; session-side code never imports it (D-072)
    "lexarena.reflection",  # reads ground truth and writes memory; session-side code reads memory via lexarena.memory
)
NO_INFRASTRUCTURE = (
    *SEALED_PATHS,
    "lexarena.evaluator",  # agents, THEMIS, judges and baselines never touch evaluation code at all (D-072, D-073)
    "lexarena.runner",
    "lexarena.secrets",
    "lexarena.storage.factory",
    "pymongo",
    "qdrant_client",
    "redis",
)

FORBIDDEN: dict[str, tuple[str, ...]] = {
    "agents": NO_INFRASTRUCTURE,
    "themis_local": NO_INFRASTRUCTURE,
    "themis_global": NO_INFRASTRUCTURE,
    "judges": NO_INFRASTRUCTURE,
    "baselines": NO_INFRASTRUCTURE,  # the single-LLM baseline sees the agent-visible case file only (D-072)
    "retrieval": SEALED_PATHS,
    "orchestrator": SEALED_PATHS,
    "runner": SEALED_PATHS,  # stages needing sealed data run as separate processes (D-073)
}


def imported_names(source: str) -> set[str]:
    """Fully qualified names a module imports: `a.b` for `import a.b`, `a.b.c` for `from a.b import c`."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names |= {f"{node.module}.{alias.name}" for alias in node.names} | {node.module}
    return names


def violations(source: str, forbidden: tuple[str, ...]) -> list[str]:
    return sorted(n for n in imported_names(source) for f in forbidden if n == f or n.startswith(f"{f}."))


def test_planted_imports_are_caught() -> None:
    planted = "from lexarena.storage.ground_truth import GroundTruthRepository\nimport pymongo\n"
    assert violations(planted, NO_INFRASTRUCTURE) == [
        "lexarena.storage.ground_truth",
        "lexarena.storage.ground_truth.GroundTruthRepository",
        "pymongo",
    ]
    assert violations("from lexarena.storage.factory import SealedProcess\n", SEALED_PATHS)
    assert not violations("from lexarena.storage.factory import SessionProcess\n", SEALED_PATHS)


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_session_side_packages_respect_boundaries(package: str) -> None:
    found = []
    for path in sorted((PACKAGE / package).rglob("*.py")) if (PACKAGE / package).exists() else []:
        bad = violations(path.read_text(encoding="utf-8"), FORBIDDEN[package])
        found += [f"{path.relative_to(REPO_ROOT)}: {name}" for name in bad]
    assert not found


def test_package_prefix_is_matched_whole() -> None:
    assert violations("from lexarena.evaluator.evaluate import evaluate_session", SEALED_PATHS)
    assert violations("from lexarena.evaluator.align import evaluate", NO_INFRASTRUCTURE)
    assert not violations("from lexarena.evaluators_elsewhere import x", SEALED_PATHS)

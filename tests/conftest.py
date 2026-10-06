from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_V1 = REPO_ROOT / "config" / "config.v1.yaml"
PROMPTS_ROOT = REPO_ROOT / "prompts"
ENV_FILE = REPO_ROOT / ".env.local"
SEALED_ENV_FILE = REPO_ROOT / ".env.sealed"
DOCKER_ENV_FILE = REPO_ROOT / ".env.docker"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-live", action="store_true", help="run tests that call real LLM APIs (spends quota)")
    parser.addoption("--run-integration", action="store_true", help="run tests that need docker compose services")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    gates = {"live": "--run-live", "integration": "--run-integration"}
    for item in items:
        for marker, option in gates.items():
            if marker in item.keywords and not config.getoption(option):
                item.add_marker(pytest.mark.skip(reason=f"needs {option}"))

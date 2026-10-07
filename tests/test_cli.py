from __future__ import annotations

import json

import pytest

from lexarena.cli import main
from tests.conftest import CONFIG_V1


def test_config_show_prints_roles_and_hash_without_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(CONFIG_V1), "config", "show"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == "v1"
    assert len(out["config_sha256"]) == len("0" * 64)
    assert set(out["models"]) >= {
        "lawyer",
        "verifier",
        "judge",
        "auditor",
        "clerk_primary",
        "clerk_secondary",
        "reflection",
    }
    assert all("api_key_env" in m and "api_key" not in m for m in out["models"].values())

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lexarena.prompts import PromptError, PromptStore
from tests.conftest import PROMPTS_ROOT


@pytest.fixture
def store(tmp_path: Path) -> PromptStore:
    (tmp_path / "comp").mkdir()
    (tmp_path / "comp" / "greet.v1.txt").write_text("Hello $name, you owe $$5.", encoding="utf-8")
    (tmp_path / "comp" / "greet.v2.txt").write_text("Hi $name.", encoding="utf-8")
    return PromptStore(tmp_path)


def test_renders_placeholders_and_escapes(store: PromptStore) -> None:
    p = store.render("comp/greet", 1, name="X")
    assert p.text == "Hello X, you owe $5."
    assert p.prompt_id == "comp/greet.v1"
    assert p.sha256 == hashlib.sha256(p.text.encode("utf-8")).hexdigest()


def test_versions_are_explicit(store: PromptStore) -> None:
    assert store.render("comp/greet", 2, name="X").text == "Hi X."


def test_missing_placeholder_value_fails(store: PromptStore) -> None:
    with pytest.raises(PromptError, match="name"):
        store.render("comp/greet", 1)


def test_unused_value_fails(store: PromptStore) -> None:
    with pytest.raises(PromptError, match="extra"):
        store.render("comp/greet", 1, name="X", extra="Y")


def test_missing_file_fails(store: PromptStore) -> None:
    with pytest.raises(PromptError, match="not found"):
        store.render("comp/greet", 9, name="X")


def test_path_traversal_is_refused(store: PromptStore) -> None:
    with pytest.raises(PromptError):
        store.render("../outside", 1)


def test_shipped_prompts_render() -> None:
    real = PromptStore(PROMPTS_ROOT)
    assert real.render("smoke/dummy", 1).text.strip()
    assert "boom" in real.render("llm/schema_repair", 1, errors="boom").text

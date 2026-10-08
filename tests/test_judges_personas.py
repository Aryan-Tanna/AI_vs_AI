"""Persona prompts need the owner's approval of their exact text (CLAUDE.md §4.8; D-071)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lexarena.config import load_config
from lexarena.judges.personas import PersonaNotApprovedError, PersonaRegistry
from lexarena.prompts import PromptStore
from lexarena.schemas.bench import PERSONAS
from tests.conftest import CONFIG_V1, PROMPTS_ROOT

CFG = load_config(CONFIG_V1)
TODAY = date(2000, 1, 2)  # literal-ok: placeholder date


def registry(tmp_path: Path, prompts_root: Path = PROMPTS_ROOT) -> PersonaRegistry:
    return PersonaRegistry(tmp_path / "review", PromptStore(prompts_root), CFG.prompts)


def test_shipped_persona_prompts_render_and_name_no_case() -> None:
    reg = PersonaRegistry(Path("unused"), PromptStore(PROMPTS_ROOT), CFG.prompts)
    for persona in PERSONAS:
        text = reg.render(persona).text
        assert persona.title() in text
        assert " v. " not in text and " vs " not in text  # method only, never a case (SPEC E2, non-negotiable 8)


def test_missing_draft_then_approved(tmp_path: Path) -> None:
    reg = registry(tmp_path)
    assert reg.status("TEXTUALIST") == "MISSING"
    with pytest.raises(PersonaNotApprovedError, match="MISSING"):
        reg.prompt("TEXTUALIST", allow_unapproved=False)
    assert reg.draft("TEXTUALIST").status == "DRAFT"
    assert reg.status("TEXTUALIST") == "DRAFT"
    reg.approve("TEXTUALIST", by="<owner>", today=TODAY)
    p = reg.prompt("TEXTUALIST", allow_unapproved=False)
    assert p.approved and reg.status("TEXTUALIST") == "APPROVED"


def test_unapproved_runs_only_when_explicitly_allowed_and_says_so(tmp_path: Path) -> None:
    p = registry(tmp_path).prompt("PURPOSIVIST", allow_unapproved=True)
    assert not p.approved


def test_editing_the_prompt_makes_the_approval_stale(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    for persona in PERSONAS:
        ref = CFG.prompts.judge_personas[persona]
        src = PROMPTS_ROOT / f"{ref.id}.v{ref.version}.txt"
        dst = prompts / f"{ref.id}.v{ref.version}.txt"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    reg = registry(tmp_path, prompts)
    reg.approve("PROCEDURALIST", by="<owner>", today=TODAY)
    ref = CFG.prompts.judge_personas["PROCEDURALIST"]
    path = prompts / f"{ref.id}.v{ref.version}.txt"
    path.write_text(path.read_text(encoding="utf-8") + " An edit.", encoding="utf-8")
    assert reg.status("PROCEDURALIST") == "STALE"
    with pytest.raises(PersonaNotApprovedError, match="STALE"):
        reg.prompt("PROCEDURALIST", allow_unapproved=False)
    assert reg.draft("PROCEDURALIST").status == "DRAFT"  # the new text starts over as a draft


def test_a_decision_is_final_for_its_text(tmp_path: Path) -> None:
    reg = registry(tmp_path)
    reg.reject("TEXTUALIST", by="<owner>", reason="<reason>", today=TODAY)
    assert reg.status("TEXTUALIST") == "REJECTED"
    with pytest.raises(ValueError, match="already REJECTED"):
        reg.approve("TEXTUALIST", by="<owner>", today=TODAY)

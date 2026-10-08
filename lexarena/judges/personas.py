"""Persona prompts and their approval (CLAUDE.md §4.8; SPEC E2; D-071).

A persona prompt tells a judge how to read the law, so the owner approves each one, as with legal drafts. The decision
lives in `review/judge_personas/<PERSONA>.json`, bound to the SHA-256 of the prompt's exact text: editing the prompt
makes the stored decision stale, and the persona counts as unapproved until the new text is approved.

`draft` writes or refreshes a DRAFT for the current text; `approve` and `reject` record the owner's decision and are
run only on the owner's explicit command, never by an agent on its own initiative (D-064).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from lexarena.prompts import PromptStore, RenderedPrompt
from lexarena.schemas.bench import PERSONAS, Persona, PersonaApproval
from lexarena.schemas.config import PromptsConfig

JSON_INDENT = 2  # literal-ok: file formatting


class PersonaNotApprovedError(RuntimeError):
    """A persona prompt whose exact text the owner has not approved."""


@dataclass(frozen=True)
class PersonaPrompt:
    persona: Persona
    rendered: RenderedPrompt
    approved: bool


class PersonaRegistry:
    def __init__(self, root: Path, prompts: PromptStore, refs: PromptsConfig) -> None:
        self._root = root
        self._prompts = prompts
        self._refs = refs

    def _path(self, persona: Persona) -> Path:
        return self._root / f"{persona}.json"

    def render(self, persona: Persona) -> RenderedPrompt:
        ref = self._refs.judge_personas[persona]
        return self._prompts.render(ref.id, ref.version)

    def stored(self, persona: Persona) -> PersonaApproval | None:
        path = self._path(persona)
        if not path.is_file():
            return None
        return PersonaApproval.model_validate_json(path.read_text(encoding="utf-8"))

    def status(self, persona: Persona) -> str:
        """APPROVED, REJECTED or DRAFT for the current text; STALE if a decision exists for other text; MISSING."""
        rec, text = self.stored(persona), self.render(persona)
        if rec is None:
            return "MISSING"
        if rec.sha256 != text.sha256 or rec.prompt_id != text.prompt_id:
            return "STALE"
        return rec.status

    def prompt(self, persona: Persona, *, allow_unapproved: bool) -> PersonaPrompt:
        rendered = self.render(persona)
        approved = self.status(persona) == "APPROVED"
        if not approved and not allow_unapproved:
            raise PersonaNotApprovedError(
                f"persona {persona} ({rendered.prompt_id}) is {self.status(persona)}, not APPROVED; "
                "the owner approves it with `lexarena judges approve`"
            )
        return PersonaPrompt(persona, rendered, approved)

    def _write(self, rec: PersonaApproval) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        text = json.dumps(rec.to_document(), indent=JSON_INDENT, ensure_ascii=False) + "\n"
        self._path(rec.persona).write_text(text, encoding="utf-8")

    def draft(self, persona: Persona) -> PersonaApproval:
        """A DRAFT for the current text. An existing decision on the same text is kept, never reset."""
        rendered = self.render(persona)
        current = self.stored(persona)
        if current is not None and current.sha256 == rendered.sha256 and current.prompt_id == rendered.prompt_id:
            return current
        rec = PersonaApproval(
            persona=persona,
            prompt_id=rendered.prompt_id,
            sha256=rendered.sha256,
            status="DRAFT",
            decided_by=None,
            decided_on=None,
            note=None,
        )
        self._write(rec)
        return rec

    def _decide(self, persona: Persona, status: str, by: str, note: str | None, today: date) -> PersonaApproval:
        current = self.draft(persona)
        if current.status != "DRAFT":
            raise ValueError(f"persona {persona} is already {current.status} for this text")
        rec = PersonaApproval.model_validate(
            {**current.to_document(), "status": status, "decided_by": by, "decided_on": today, "note": note}
        )
        self._write(rec)
        return rec

    def approve(self, persona: Persona, *, by: str, today: date, note: str | None = None) -> PersonaApproval:
        return self._decide(persona, "APPROVED", by, note, today)

    def reject(self, persona: Persona, *, by: str, reason: str, today: date) -> PersonaApproval:
        return self._decide(persona, "REJECTED", by, reason, today)

    def all_status(self) -> dict[Persona, str]:
        return {p: self.status(p) for p in PERSONAS}

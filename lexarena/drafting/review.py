"""The review folder (CLAUDE.md §9 `review/`): one JSON file per drafted item, decided by a human.

`review/temporal_overlay/<id>.json` and `review/predicate_registry/<id>.json`. Status moves once, from DRAFT
to APPROVED or REJECTED, and records who decided and when. A draft with blocking problems cannot be
approved. Claude Code never approves (non-negotiable 8); approvals are made with
`lexarena review approve <id> --by <name>` and committed to git by the reviewer.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter

from lexarena.drafting.models import Draft, OverlayDraft, PredicateDraft

KINDS = ("temporal_overlay", "predicate_registry")
JSON_INDENT = 2  # literal-ok: file indentation
_ADAPTER: TypeAdapter[OverlayDraft | PredicateDraft] = TypeAdapter(Draft)


class ReviewError(ValueError):
    pass


class ReviewStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, draft: OverlayDraft | PredicateDraft) -> Path:
        return self._root / draft.kind / f"{draft.draft_id}.json"

    def _write(self, draft: OverlayDraft | PredicateDraft) -> None:
        path = self._path(draft)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(draft.to_document(), indent=JSON_INDENT, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def save(self, draft: OverlayDraft | PredicateDraft) -> bool:
        """Write a new draft. Returns False, writing nothing, if a draft with this ID already exists."""
        if self._path(draft).exists():
            return False
        self._write(draft)
        return True

    def all(self) -> list[OverlayDraft | PredicateDraft]:
        found = []
        for kind in KINDS:
            for path in sorted((self._root / kind).glob("*.json")):
                found.append(_ADAPTER.validate_json(path.read_text(encoding="utf-8")))
        return found

    def get(self, draft_id: str) -> OverlayDraft | PredicateDraft:
        for kind in KINDS:
            path = self._root / kind / f"{draft_id}.json"
            if path.exists():
                return _ADAPTER.validate_json(path.read_text(encoding="utf-8"))
        raise ReviewError(f"no draft {draft_id} in {self._root}")

    def update_checks(self, draft: OverlayDraft | PredicateDraft) -> None:
        """Rewrite an undecided draft with freshly computed checks."""
        if self.get(draft.draft_id).status != "DRAFT":
            raise ReviewError(f"{draft.draft_id} is already decided")
        self._write(draft)

    def approve(self, draft_id: str, *, by: str, note: str | None = None) -> OverlayDraft | PredicateDraft:
        draft = self._undecided(draft_id, by)
        if draft.blocking_problems:
            raise ReviewError(f"{draft_id} has blocking problems and cannot be approved: {draft.blocking_problems}")
        return self._decide(draft, "APPROVED", by, note)

    def reject(self, draft_id: str, *, by: str, reason: str) -> OverlayDraft | PredicateDraft:
        draft = self._undecided(draft_id, by)
        if not reason.strip():
            raise ReviewError("a rejection needs a reason")
        return self._decide(draft, "REJECTED", by, reason)

    def _undecided(self, draft_id: str, by: str) -> OverlayDraft | PredicateDraft:
        if not by.strip():
            raise ReviewError("name the reviewer with --by")
        draft = self.get(draft_id)
        if draft.status != "DRAFT":
            raise ReviewError(f"{draft_id} is already {draft.status}")
        return draft

    def _decide(
        self, draft: OverlayDraft | PredicateDraft, status: str, by: str, note: str | None
    ) -> OverlayDraft | PredicateDraft:
        decided = draft.model_copy(
            update={"status": status, "decided_by": by.strip(), "decided_on": date.today(), "decision_note": note}
        )
        self._write(decided)
        return decided

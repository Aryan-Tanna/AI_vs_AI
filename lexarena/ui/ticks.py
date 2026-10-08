"""The reviewer's ticks for one clerked case: `reports/review/<case>.ticks.json`, a local file beside the clerk's review
file (D-056, S-007). Ticking never writes the case: marking a case reviewed stays the owner's command
(`lexarena clerk approve <case> --by NAME`), run by the clerk role."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from lexarena.schemas.base import NonEmptyStr, StoredModel

JSON_INDENT = 2  # literal-ok: file formatting


class Tick(StoredModel):
    ok: bool
    note: str | None
    by: NonEmptyStr
    at: datetime


class CaseTicks(StoredModel):
    case_id: NonEmptyStr
    ticks: dict[str, Tick] = Field(default_factory=dict)

    def done(self, item_ids: list[str]) -> bool:
        return bool(item_ids) and all(i in self.ticks and self.ticks[i].ok for i in item_ids)


class TickStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, case_id: str) -> Path:
        return self._root / f"{case_id}.ticks.json"

    def load(self, case_id: str) -> CaseTicks:
        path = self._path(case_id)
        if not path.is_file():
            return CaseTicks(case_id=case_id)
        return CaseTicks.model_validate_json(path.read_text(encoding="utf-8"))

    def set(self, case_id: str, item_id: str, *, ok: bool, by: str, note: str | None = None) -> CaseTicks:
        ticks = self.load(case_id)
        ticks.ticks[item_id] = Tick(ok=ok, note=note or None, by=by, at=datetime.now(UTC))
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._path(case_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(ticks.to_document(), indent=JSON_INDENT, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self._path(case_id))
        return ticks

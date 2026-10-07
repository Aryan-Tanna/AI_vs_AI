"""Statute citation alias table (`data/statute_aliases.json`, Q-028, D-049).

Each entry says that citations starting with `cited_prefix` name the same act as Law DB IDs starting with
`law_db_prefix` (e.g. a long act name and its short form). It is naming, not law: it never says what a provision
means, only which Law DB record a citation points to. The table is data, reviewed like any other data change.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, model_validator

from lexarena.schemas.base import NonEmptyStr, StoredModel

IdPrefix = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]


class StatuteAlias(StoredModel):
    cited_prefix: IdPrefix
    law_db_prefix: IdPrefix
    reason: NonEmptyStr

    @model_validator(mode="after")
    def _not_identity(self) -> StatuteAlias:
        if self.cited_prefix == self.law_db_prefix:
            raise ValueError(f"alias {self.cited_prefix!r} maps to itself")
        return self


class StatuteAliasTable(StoredModel):
    aliases: list[StatuteAlias]

    @model_validator(mode="after")
    def _unique_prefixes(self) -> StatuteAliasTable:
        seen: set[str] = set()
        for alias in self.aliases:
            if alias.cited_prefix in seen:
                raise ValueError(f"cited_prefix {alias.cited_prefix!r} appears twice")
            seen.add(alias.cited_prefix)
        return self

    def rewrite(self, cited: str) -> str | None:
        """The citation with its longest matching cited prefix replaced, or None if no alias applies."""
        matches = [a for a in self.aliases if cited.startswith(a.cited_prefix)]
        if not matches:
            return None
        best = max(matches, key=lambda a: len(a.cited_prefix))
        return best.law_db_prefix + cited[len(best.cited_prefix) :]

"""Base classes shared by every stored or exchanged object.

Two kinds of model:

- `StoredModel` for formats this project owns (SPEC H, side collections, lessons). Unknown fields are
  rejected, so a typo or a stray field fails at write time instead of silently persisting.
- `FrozenFormatModel` for the Law DB and precedent records (DATA_FORMATS §1-2), which are frozen and
  maintained outside this code. Documented fields are validated strictly (no type coercion). A field the
  format does not document is kept untouched and reported by `undocumented_fields()`, never dropped and
  never special-cased (D-033): the data will keep growing and the code must not track its quirks.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
UpperCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
UnitScore = Annotated[float, Field(ge=0, le=1)]
SourceParas = Annotated[list[NonEmptyStr], Field(min_length=1)]

Side = Literal["PETITIONER", "RESPONDENT"]
SIDES: tuple[Side, Side] = ("PETITIONER", "RESPONDENT")


class StoredModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_document(self) -> dict[str, Any]:
        """The MongoDB form: JSON-compatible values (dates as ISO strings), `_id` under its alias."""
        return self.model_dump(mode="json", by_alias=True)


class FrozenFormatModel(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)

    def undocumented_fields(self, prefix: str = "") -> list[str]:
        """Dotted paths of every field present in the data but absent from the documented format."""
        found = [f"{prefix}{name}" for name in (self.model_extra or {})]
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, FrozenFormatModel):
                found += value.undocumented_fields(f"{prefix}{name}.")
        return found

    def to_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

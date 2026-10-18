"""Redaction of a stored agent view (D-129): a leak found in triage (a real name, an address, a registration number) is
replaced by the case's own pseudonym or a fixed mask, without re-clerking. It can only remove: the replacement must
be one of the case's pseudonyms or a mask, and the result is validated and re-checked by the caller."""

from __future__ import annotations

import re
from typing import Any

from lexarena.clerk.names import ADDRESS_MASK
from lexarena.schemas.case import AgentView

NUMBER_MASK = "[number removed]"
NAME_MASK = "[name removed]"  # a name that is not a party (a project, a building): it identifies the case too
MASKS = frozenset({ADDRESS_MASK, NUMBER_MASK, NAME_MASK})


class RedactionError(ValueError):
    """The redaction would add content, or names text that is not there."""


def redact_view(
    view: AgentView, replacements: list[tuple[str, str]], *, allowed: set[str]
) -> tuple[AgentView, list[str]]:
    """`allowed`: the case's pseudonyms. Returns the new view and the paths of the fields changed."""
    for old, new in replacements:
        if not re.search(r"[A-Za-z]", old):
            raise RedactionError(f"'{new}' redaction: the text to replace must contain a letter (dates, amounts stay)")
        if new not in allowed and new not in MASKS:
            raise RedactionError(f"'{new}' is not a pseudonym of this case or a mask {sorted(MASKS)}")
    touched: list[str] = []

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            return {k: walk(v, f"{path}.{k}" if path else k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, f"{path}.{i}") for i, v in enumerate(node)]
        if isinstance(node, str):
            out = node
            for old, new in replacements:
                out = re.sub(re.escape(old), new, out, flags=re.IGNORECASE)
            if out != node:
                touched.append(path)
            return out
        return node

    data = view.model_dump(mode="json")
    for old, new in replacements:
        if not any(re.search(re.escape(old), s, re.IGNORECASE) for s in _strings(data)):
            raise RedactionError(f"the text to replace with '{new}' does not occur in the agent view")
    return AgentView.model_validate(walk(data, "")), touched


def _strings(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return [node] if isinstance(node, str) else []


def drop_key_dates(view: AgentView, labels: list[str]) -> AgentView:
    """Remove key dates that belong to another proceeding (D-133): a wrong FILING date silently picks the wrong law
    version (`storage/temporal.py`), while a missing one leaves the overlay row unresolved and reported."""
    present = {kd.label for kd in view.metadata.key_dates}
    if missing := sorted(set(labels) - present):
        raise RedactionError(f"no key date labelled {missing}")
    kept = [kd for kd in view.metadata.key_dates if kd.label not in labels]
    return view.model_copy(update={"metadata": view.metadata.model_copy(update={"key_dates": kept})})

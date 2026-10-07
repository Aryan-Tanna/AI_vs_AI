"""Reading JSON source files: a JSON array, JSON Lines, or objects simply concatenated."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_values(path: Path) -> tuple[list[Any], list[str]]:
    """Every top-level JSON value in a file, with array brackets and separators between values skipped.

    Where the text is not valid JSON, the location is recorded and reading resumes at the next `{`; the
    broken stretch is reported, never repaired.
    """
    text = path.read_text(encoding="utf-8")
    decoder, i = json.JSONDecoder(), 0
    values: list[Any] = []
    errors: list[str] = []
    while i < len(text):
        while i < len(text) and (text[i].isspace() or text[i] in ",[]"):
            i += 1
        if i >= len(text):
            break
        try:
            value, i = decoder.raw_decode(text, i)
            values.append(value)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name} char {exc.pos}: {exc.msg}")
            following = text.find("{", i + 1)
            i = len(text) if following < 0 else following
    return values, errors

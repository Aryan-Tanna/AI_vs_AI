"""Versioned prompt files: prompts/<component>/<name>.v<N>.txt with $placeholders (string.Template syntax).

No prompt text lives in Python. Rendering fails on a missing or an unused value, so a template and its
caller can never silently drift apart.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from string import Template

from pydantic import BaseModel, ConfigDict


class PromptError(ValueError):
    pass


class RenderedPrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_id: str
    text: str
    sha256: str


class PromptStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def render(self, name: str, version: int, /, **values: str) -> RenderedPrompt:
        path = (self._root / f"{name}.v{version}.txt").resolve()
        if not path.is_relative_to(self._root):
            raise PromptError(f"prompt '{name}' resolves outside the prompts directory")
        if not path.is_file():
            raise PromptError(f"prompt file not found: {name}.v{version}.txt")
        template = Template(path.read_text(encoding="utf-8"))
        wanted = set(template.get_identifiers())
        missing = sorted(wanted - values.keys())
        unused = sorted(values.keys() - wanted)
        if missing:
            raise PromptError(f"prompt {name}.v{version}: no value for {missing}")
        if unused:
            raise PromptError(f"prompt {name}.v{version}: values not used by the template: {unused}")
        text = template.substitute(values)
        return RenderedPrompt(
            prompt_id=f"{name}.v{version}", text=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()
        )

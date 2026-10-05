"""Non-negotiable 4: no legal constant or tuning number appears as a literal in lexarena/.

Allowed without comment: 0 and 1 (indexing, counting, identity). Anything else needs a trailing
`# literal-ok: <reason>` on the same line, which a reviewer can grep for.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.conftest import REPO_ROOT

ALLOWED_NUMBERS = {0, 1}
DATE_LIKE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}[./]\d{2}[./]\d{4}\b")
EXEMPT_MARK = "# literal-ok:"


def _violations(path: Path) -> list[str]:
    name = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path.name
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Constant):
            continue
        line = lines[node.lineno - 1]
        if EXEMPT_MARK in line:
            continue
        value = node.value
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and value not in ALLOWED_NUMBERS:
            found.append(f"{name}:{node.lineno}: number {value!r}")
        elif isinstance(value, str) and DATE_LIKE.search(value):
            found.append(f"{name}:{node.lineno}: date-like string {value!r}")
    return found


def test_no_numeric_or_date_literals_in_package() -> None:
    files = sorted((REPO_ROOT / "lexarena").rglob("*.py"))
    assert files, "package not found"
    violations = [v for f in files for v in _violations(f)]
    assert violations == []


def test_scanner_catches_a_planted_literal(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text("THRESHOLD = 10000000\nDATE = '2020-03-24'\nOK = 7  # literal-ok: test\n", encoding="utf-8")
    assert len(_violations(planted)) == 2

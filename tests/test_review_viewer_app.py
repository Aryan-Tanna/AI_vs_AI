"""The review viewer renders against the real services (D-056). Uses whatever clerked cases exist locally; it
reads only, through the REVIEW role, so it changes nothing.

Run with: pytest --run-integration -m integration
"""

from __future__ import annotations

import pytest

from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.integration


def test_viewer_renders_without_errors() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(REPO_ROOT / "lexarena" / "ui" / "app.py"), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "Clerk review"

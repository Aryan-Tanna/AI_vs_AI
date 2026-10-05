"""Load and fingerprint versioned config files."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from lexarena.schemas.config import AppConfig

CRLF, LF = b"\r\n", b"\n"


def load_config(path: Path) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(raw)


def config_sha256(path: Path) -> str:
    """Fingerprint stamped on every session, so a run can prove which config it used.

    Line endings are normalised first: git may check the same commit out with LF or CRLF.
    """
    return hashlib.sha256(path.read_bytes().replace(CRLF, LF)).hexdigest()

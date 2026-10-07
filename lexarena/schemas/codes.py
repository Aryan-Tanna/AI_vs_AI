"""The closed list of hard-error codes (SPEC D8, D-021).

These are verification-protocol codes defined by the SPEC, not law: only they may trigger a retry.
Law DB `audit_error_codes` label warnings, notes and lessons and are never hard errors (D-021).
"""

from __future__ import annotations

from typing import Literal, get_args

HardErrorCode = Literal[
    "ERR_THRESHOLD_MISSTATED",
    "ERR_THRESHOLD_APPLICATION",
    "ERR_TIMELINE_MISSTATED",
    "ERR_FACT_NOT_IN_RECORD",
    "ERR_EXHIBIT_CONTENT_FABRICATED",
    "ERR_PRECEDENT_MISATTRIBUTED",
    "ERR_REPEATED_ARGUMENT",
]
HARD_ERROR_CODES: frozenset[str] = frozenset(get_args(HardErrorCode))

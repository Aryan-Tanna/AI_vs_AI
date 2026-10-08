"""Process exit codes the run manager acts on (D-073). A stage is a `lexarena` subprocess; its exit code tells the
run manager whether to record success, pause for quota and resume later, or fail the run."""

from __future__ import annotations

OK = 0
FAILED = 1
QUOTA_EXHAUSTED = 75  # literal-ok: EX_TEMPFAIL from sysexits.h, "try again later"

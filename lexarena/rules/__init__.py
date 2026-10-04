"""Deterministic rule engine (CLAUDE.md §5, build Phase 1: steps M, N, O).

Computes dates, periods and thresholds. It never decides contested legal questions (bona fides under s.14,
sufficient cause under s.5 or s.61(2), plausibility of a dispute under Mobilox); those come back as notes
for the bench. Used by THEMIS Stage A and exposed to agents as `rules.*` tools.
"""
from lexarena.rules.appeal import appeal_timeline, sec61_appeal, sec62_appeal
from lexarena.rules.limitation import Acknowledgment, Interval, limitation, period_end
from lexarena.rules.result import RuleResult
from lexarena.rules.sec9_notice import dispute_ordering, sec9_filing_window
from lexarena.rules.sec10a import sec10a_bar
from lexarena.rules.threshold import class_creditor_threshold, minimum_default

__all__ = ["Acknowledgment", "Interval", "RuleResult", "appeal_timeline", "class_creditor_threshold",
           "dispute_ordering", "limitation", "minimum_default", "period_end", "sec10a_bar", "sec61_appeal",
           "sec62_appeal", "sec9_filing_window"]

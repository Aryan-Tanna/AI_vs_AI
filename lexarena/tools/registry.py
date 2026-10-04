"""Role -> allowed tools. This allowlist is the security boundary (CLAUDE.md §8.0, §8.1a)."""
RESEARCH = {"search_authorities", "get_provision", "authority_status", "rules_limitation", "rules_appeal_timeline",
            "rules_sec9_notice", "rules_sec10a", "rules_threshold"}

ROLE_TOOLS: dict[str, set[str]] = {
    "smoke": {"get_case_fact"},
    "baseline": set(),                                  # reads the case from its prompt only
    "extractor": set(),                                 # THEMIS claim extraction: prompt only
    "verifier": set(),                                  # THEMIS Stage B: prompt only
    "advocate": {"read_record", "read_transcript"} | RESEARCH,
    "judge": {"read_record", "read_transcript"} | RESEARCH,
}

# Specified in CLAUDE.md §8.1a, not built yet. Requesting one fails loudly instead of silently dropping it.
PLANNED = {"recall_lessons", "notes_write", "notes_read", "read_ground_truth", "propose_lesson", "pdf_search",
           "pdf_read_page", "validate_draft"}


def select_tools(role: str, available: dict, wanted: set[str] | None = None) -> list:
    """Return the SdkMcpTool objects `role` may use. `available` maps tool name -> tool built for this case.
    With `wanted=None`, every allowed tool that was provided is returned."""
    allowed = ROLE_TOOLS[role]
    if wanted is None:
        return [available[name] for name in sorted(allowed & set(available))]
    if extra := wanted - allowed:
        raise PermissionError(f"role '{role}' may not use {sorted(extra)}")
    if planned := wanted & PLANNED:
        raise NotImplementedError(f"tools not built yet: {sorted(planned)}")
    if missing := wanted - set(available):
        raise KeyError(f"tools not provided for this job: {sorted(missing)}")
    return [available[name] for name in sorted(wanted)]

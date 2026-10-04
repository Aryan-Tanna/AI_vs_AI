"""Role -> allowed tools. This allowlist is the security boundary (CLAUDE.md §8.0, §8.1a)."""
ROLE_TOOLS: dict[str, set[str]] = {
    "smoke": {"get_case_fact"},
    "baseline": set(),                                  # reads the case from its prompt only
    "advocate": {"read_record", "read_transcript"},
    "judge": {"read_record", "read_transcript"},
}

# Specified in CLAUDE.md §8.1a, not built yet. Requesting one fails loudly instead of silently dropping it.
PLANNED = {"search_authorities", "get_authority", "authority_status", "get_provision", "rules_limitation",
           "rules_threshold", "rules_sec10a", "rules_sec9_notice", "rules_appeal_timeline", "recall_lessons",
           "notes_write", "notes_read", "read_ground_truth", "propose_lesson", "pdf_search", "pdf_read_page",
           "validate_draft"}


def select_tools(role: str, available: dict, wanted: set[str] | None = None) -> list:
    """Return the SdkMcpTool objects `role` may use. `available` maps tool name -> tool built for this case."""
    allowed = ROLE_TOOLS[role]
    wanted = allowed if wanted is None else wanted
    if extra := wanted - allowed:
        raise PermissionError(f"role '{role}' may not use {sorted(extra)}")
    if planned := wanted & PLANNED:
        raise NotImplementedError(f"tools not built yet: {sorted(planned)}")
    if missing := wanted - set(available):
        raise KeyError(f"tools not provided for this job: {sorted(missing)}")
    return [available[name] for name in sorted(wanted)]

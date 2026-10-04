"""Record tools: read the unspoiled case file and the published transcript. Nothing else is reachable."""
from typing import Annotated

from claude_agent_sdk import tool

from lexarena.public_db import UnspoiledCase, to_json


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


def make_record_tools(case: UnspoiledCase, transcript: list[dict]) -> dict:
    sections = case.sections()

    @tool("read_record", "Read the appeal record. section='all' returns the whole record in one call (preferred); "
          "'index' lists the sections; or name one section.",
          {"section": Annotated[str, "'all', 'index', or a section name"]})
    async def read_record(args):
        name = args.get("section", "all")
        if name == "all":
            return _text(to_json(sections))
        if name == "index":
            return _text(to_json(sorted(sections)))
        if name not in sections:
            return {**_text(f"No section '{name}'. Available: {sorted(sections)}"), "is_error": True}
        return _text(to_json(sections[name]))

    @tool("read_transcript", "Read the published turns of this hearing (with any verifier flags).",
          {"from_turn": Annotated[int, "First turn number to return (1-based)"]})
    async def read_transcript(args):
        start = max(1, int(args.get("from_turn", 1)))
        turns = [{k: t[k] for k in ("turn", "speaker", "stage", "prose", "flags") if k in t}
                 for t in transcript if t["turn"] >= start]
        return _text(to_json(turns) if turns else "No published turns yet.")

    return {"read_record": read_record, "read_transcript": read_transcript}

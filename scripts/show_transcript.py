"""Print a session's published turns (what both lawyers and the judges see). Read-only.

Usage: python scripts/show_transcript.py [SESSION_ID]   (default: the most recent session)
"""

from __future__ import annotations

import sys

from dotenv import dotenv_values
from pymongo import MongoClient

from lexarena.storage.mongo import TRANSCRIPT_TURNS

env = dotenv_values(".env.local")
db = MongoClient(env["LEXARENA_MONGO_APP_URI"])[env["LEXARENA_MONGO_APP_DB"]]
turns = db[TRANSCRIPT_TURNS]
sid = sys.argv[1] if len(sys.argv) > 1 else next(iter(turns.find().sort("created_at", -1).limit(1)), {}).get("session_id")
if not sid:
    sys.exit("no published turns yet")
print(f"session {sid}\n")
for t in turns.find({"session_id": sid}).sort("turn", 1):
    flags = ", ".join(f.get("code", "?") for f in t.get("visible_flags", [])) or "none"
    print(f"=== Turn {t['turn']} | {t['speaker']} | {t['turn_type']} | issues {t.get('issues_addressed')} | flags: {flags}")
    print(t["published_text"])
    for c in t.get("claims", []):
        refs = c.get("record_ids", []) + ([c["statute_id"]] if c.get("statute_id") else []) + c.get("precedent_ids", [])
        print(f"  - [{c['type']}] {c['text'][:140]}  -> {refs}")
    print()

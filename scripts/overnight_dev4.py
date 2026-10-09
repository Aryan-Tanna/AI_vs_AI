"""Overnight chain: wait for the DEV_0004 clerk, then run the case under a $2 spend cap, then write a report."""
import json, subprocess, time, urllib.request
from pathlib import Path
from dotenv import dotenv_values
from pymongo import MongoClient

EXE = "C:/IPD_AIvsAI/.venv/Scripts/lexarena.exe"; RUN = "DEV4_E2E_2"; CAP = 2.0
OUT = Path("reports/dev_runs/DEV_0004_overnight.md"); OUT.parent.mkdir(parents=True, exist_ok=True)
PROGRESS = Path("reports/dev_runs/PROGRESS.log")
env = dotenv_values(".env.local")
def used():
    r = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={"Authorization": "Bearer " + env["paidAPI"]})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())["data"]["total_usage"]
def running():
    return "lexarena.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq lexarena.exe"], capture_output=True, text=True).stdout
log = []
def note(x):
    log.append(x); print(x, flush=True)
    with PROGRESS.open("a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M ") + x.strip().splitlines()[0][:300] + chr(10))
start = used(); note(f"start spend ${start:.3f}")
note("waiting for any running lexarena process to finish")
while running(): time.sleep(30)
db = MongoClient(env["LEXARENA_MONGO_APP_URI"])[env["LEXARENA_MONGO_APP_DB"]]
if not db["cases"].find_one({"_id": "DEV_0004"}):
    note("clerking DEV_0004 (Gemini 3.5 Flash primary, DeepSeek secondary)")
    c = subprocess.run([EXE, "clerk", "run", "--file", "data/dev/TATA CONSULTANCY SERVICES LIMITED.pdf", "--case-id", "DEV_0004"],
                       capture_output=True, text=True)
    Path("reports/dev_runs/clerk_DEV_0004.log").write_text(c.stdout + c.stderr, encoding="utf-8")
    note(f"clerk exit {c.returncode}; spend so far ${used()-start:.3f}")
case = db["cases"].find_one({"_id": "DEV_0004"})
if not case:
    note("CLERK FAILED: DEV_0004 not stored. Stopping. See reports/dev_runs/clerk_DEV_0004.log"); OUT.write_text("\n".join(log), encoding="utf-8"); raise SystemExit(1)
flags = case["build"].get("extraction_flags", [])
note(f"clerk ok; flags: {[f['code'] for f in flags]}; memorization probe: {case['build'].get('memorization_probe')}; evidence: {case['build'].get('evidence_dependency')}")
if any("LEAK" in f["code"] for f in flags):
    note("LEAKAGE FLAG: stopping before any session."); OUT.write_text("\n".join(log), encoding="utf-8"); raise SystemExit(1)
note(f"planning run {RUN}")
subprocess.run([EXE, "run", "plan", RUN, "--mode", "LEARN", "--case-id", "DEV_0004", "--allow-draft-personas"], check=True)
run = subprocess.Popen([EXE, "run", "go", RUN, "--skip-quota-check"], stdout=open("runs_dev4.log", "w"), stderr=subprocess.STDOUT)
note(f"run {RUN} started (session, baseline, evaluate, reflect); cap ${CAP}")
base = used()
while run.poll() is None:
    time.sleep(60)
    st = subprocess.run([EXE, "run", "status", RUN], capture_output=True, text=True).stdout
    stages = json.loads(st)["cases"]["DEV_0004"] if st.strip().startswith("{") else {}
    if stages != globals().get("_last"):
        globals()["_last"] = stages; note(f"stages now: {stages}")
    try: spent = used() - base
    except Exception: continue
    if spent > CAP:
        note(f"CAP HIT at ${spent:.3f}: stopping run"); subprocess.run(["taskkill", "/T", "/F", "/PID", str(run.pid)]); break
note(f"run exit {run.wait()}; run spend ${used()-base:.3f}; total today ${used():.3f}")
status = subprocess.run([EXE, "run", "status", RUN], capture_output=True, text=True).stdout
note("```\n" + status + "\n```")
s = db["sessions"].find_one({"case_id": "DEV_0004"}, sort=[("created_at", -1)])
if s:
    note(f"session {s['_id']} state {s.get('state')}")
    b = s.get("bench") or {}; note(f"bench winner: {b.get('winner')} ({b.get('status')})")
    for d in s.get("judge_decisions", []): note(f"- {d['judge']}: {d['status']} {d.get('result')} orders {[o.get('order') for o in d.get('opinions', [])]}")
    ev = s.get("evaluation") or {}; note(f"evaluation: {json.dumps(ev, default=str)[:1500]}")
    for t in db["transcript_turns"].find({"session_id": s["_id"]}).sort("turn", 1):
        note(f"\n### Turn {t['turn']} {t['speaker']} {t['turn_type']} flags={[f.get('code') for f in t.get('visible_flags', [])]}\n{t['published_text']}")
OUT.write_text("\n".join(log), encoding="utf-8"); note(f"report: {OUT}")

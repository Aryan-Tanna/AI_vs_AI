"""LexArena viewer (Streamlit). Read-only. Run with: python -m lexarena.ui

Pages: Live (transcript filling turn by turn, THEMIS gate per turn, tools used), Bench (THEMIS-GLOBAL findings,
judges, verdict, reveal of the real outcome), Evaluation (metrics vs baselines), Dashboard (queue, usage window,
cost), Cases (what the agents see). Research simulation, not legal advice.
"""
import datetime as dt
import html
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lexarena.config import ROOT, Settings
from lexarena.ui import data as D

st.set_page_config(page_title="LexArena viewer", page_icon="⚖", layout="wide")

STATUS_COLOR = {"PASSED": "#2e9e6b", "FLAGGED_SOFT": "#c99a0e", "FLAGGED_HARD": "#d64545", "FLAGGED_BOTH": "#9b4dca",
                "NOT_RUN": "#7a8291"}
SIDE_COLOR = {"APPELLANT": "#3b6fd8", "RESPONDENT": "#c9822b"}
LABEL_COLOR = {"DISMISSED": "#c9822b", "ALLOWED": "#3b6fd8", "ALLOWED_REMANDED": "#3b6fd8", "PARTLY_ALLOWED": "#5a8fe0"}

st.markdown("""
<style>
.lx-chip {display:inline-block; padding:2px 10px; margin:2px 4px 2px 0; border-radius:12px; font-size:0.78rem;
          border:1px solid rgba(128,128,128,.35); white-space:nowrap}
.lx-chip.done {background:rgba(46,158,107,.18); border-color:#2e9e6b}
.lx-chip.active {background:rgba(201,154,14,.22); border-color:#c99a0e; animation: lxpulse 1.2s infinite}
.lx-chip.pending {opacity:.55}
@keyframes lxpulse {0%{opacity:1} 50%{opacity:.45} 100%{opacity:1}}
.lx-card {border:1px solid rgba(128,128,128,.3); border-left:5px solid var(--side); border-radius:8px;
          padding:10px 14px; margin:6px 0 2px 0; background:rgba(128,128,128,.06)}
.lx-head {font-size:.82rem; opacity:.85; margin-bottom:6px}
.lx-badge {display:inline-block; padding:1px 8px; border-radius:10px; color:#fff; font-size:.72rem; margin-left:6px}
.lx-step {display:inline-block; padding:1px 7px; border-radius:6px; font-size:.72rem; margin-right:4px;
          border:1px solid rgba(128,128,128,.4)}
.lx-step.ok {background:rgba(46,158,107,.18)} .lx-step.bad {background:rgba(214,69,69,.18)}
.lx-prose {font-size:.92rem; line-height:1.45; white-space:pre-wrap}
.lx-vote {border:1px solid rgba(128,128,128,.3); border-top:5px solid var(--c); border-radius:8px; padding:10px 14px}
.lx-disc {font-size:.75rem; opacity:.7}
</style>
""", unsafe_allow_html=True)

settings = Settings()

# ---- sidebar ------------------------------------------------------------------------------------------------
st.sidebar.markdown("## ⚖ LexArena")
page = st.sidebar.radio("View", ["Live", "Bench", "Evaluation", "Dashboard", "Cases"], label_visibility="collapsed")
runs_dir = Path(st.sidebar.text_input("Runs folder", str(settings.runs_dir)))
db_options = {"public_db (gold)": settings.public_db_dir, "data/silver": settings.data_dir / "silver",
              "schema example": ROOT / "docs" / "schema" / "example"}
db_choice = st.sidebar.selectbox("Case DB", [k for k, v in db_options.items() if v.exists()] + ["custom…"])
db_dir = Path(st.sidebar.text_input("Case DB folder", "")) if db_choice == "custom…" else db_options[db_choice]
st.sidebar.markdown('<p class="lx-disc">Research simulation, not legal advice. Simulated orders are not NCLT/NCLAT '
                    'orders. Read-only view; real names (manifest) are never shown.</p>', unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s or ""))


def chip_strip(stages: list[dict]) -> str:
    return "".join(f'<span class="lx-chip {s["state"]}">{"✓ " if s["state"] == "done" else "● " if s["state"] == "active" else ""}'
                   f'{esc(s["name"])}</span>' for s in stages)


def case_record(case_uid: str) -> dict | None:
    return next((c for c in D.db_cases(db_dir) if c["case_uid"] == case_uid), None) if db_dir and db_dir.exists() else None


def turn_card(t: dict) -> None:
    status = t.get("themis", {}).get("status", "NOT_RUN")
    steps = "".join(f'<span class="lx-step {"ok" if g["ok"] else "bad"}">{esc(g["label"])} {"✓" if g["ok"] else "✗ " + str(len(g["findings"]))}</span>'
                    for g in D.gate_summary(t))
    prose = t.get("prose", "")
    short = prose if len(prose) < 900 else prose[:900] + " …"
    st.markdown(
        f'<div class="lx-card" style="--side:{SIDE_COLOR.get(t["speaker"], "#888")}">'
        f'<div class="lx-head"><b>Turn {t["turn"]} · {esc(t["speaker"])}</b> · {esc(t.get("stage"))}'
        f'<span class="lx-badge" style="background:{STATUS_COLOR.get(status, "#888")}">{esc(status)}</span></div>'
        f'<div style="margin-bottom:6px">{steps}</div><div class="lx-prose">{esc(short)}</div></div>', unsafe_allow_html=True)
    if len(prose) >= 900:
        with st.expander("Full submission"):
            st.markdown(prose)
    if t.get("flags") or t.get("themis", {}).get("log"):
        with st.expander(f"THEMIS details ({len(t.get('flags', []))} flags on the published version)"):
            for g in D.gate_summary(t):
                st.markdown(f"**{g['label']}** — {'passed' if g['ok'] else str(len(g['findings'])) + ' finding(s)'}")
                if g["findings"]:
                    st.dataframe(pd.DataFrame(g["findings"])[["code", "claim", "evidence"]], hide_index=True, use_container_width=True)
            notes = t.get("themis", {}).get("notes") or []
            if notes:
                st.caption("Notes: " + " · ".join(esc(n.get("note") or n.get("for_bench")) for n in notes[:8]))
    tools = [x for x in t.get("tool_trace", []) if x.get("type") == "tool_use" and not x["name"].endswith("StructuredOutput")]
    if tools:
        with st.expander(f"Research used ({len(tools)} tool calls)"):
            st.dataframe(pd.DataFrame([{"tool": x["name"].split("__")[-1], "input": json.dumps(x.get("input"), ensure_ascii=False)[:160]}
                                       for x in tools]), hide_index=True, use_container_width=True)


# ---- Live ---------------------------------------------------------------------------------------------------
def page_live() -> None:
    st.title("Live hearing")
    source = st.radio("Source", ["Queue jobs", "Saved runs"], horizontal=True)
    job, transcript, checkpoint, verdict, case_uid, run_id = None, [], {}, None, None, None
    if source == "Queue jobs":
        js = D.jobs(settings.jobs_db, ("debate",))
        if not js:
            st.info("No debate jobs in the queue yet. Enqueue one with `python -m lexarena.cli enqueue debate …`.")
            return
        pick = st.selectbox("Job", js, format_func=lambda j: f"{j['key']}  ·  {j['state']}")
        job, case_uid, run_id = pick, pick["payload"]["case_uid"], pick["payload"].get("run_id", "dev")
    else:
        rc = [r for r in D.run_cases(runs_dir) if r["transcript"]]
        if not rc:
            st.info(f"No saved transcripts under {runs_dir}.")
            return
        pick = st.selectbox("Run / case", rc, format_func=lambda r: f"{r['run_id']} / {r['case_uid']}"
                                                                     f"{'  ·  verdict' if r['verdict'] else ''}")
        case_uid, run_id = pick["case_uid"], pick["run_id"]
    live = bool(job and job["state"] in ("running", "pending")) and st.toggle("Auto-refresh every 3 s", value=True)

    @st.fragment(run_every=3 if live else None)
    def body():
        nonlocal transcript, checkpoint, verdict
        running = None
        if job:
            checkpoint = D.job_checkpoint(settings.jobs_db, job["key"])
            transcript = checkpoint.get("transcript", [])
            evs = D.events(settings.state_dir, job["key"])
            running = D.current_step(evs) if live else None
        else:
            transcript = (D.read_json(runs_dir / run_id / case_uid / "transcript.json") or {}).get("turns", [])
        verdict = D.read_json(runs_dir / run_id / case_uid / "verdict.json")

        statuses = [t.get("themis", {}).get("status", "NOT_RUN") for t in transcript]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Case", case_uid)
        c2.metric("Turns published", len(transcript))
        c3.metric("Flagged turns", sum(s.startswith("FLAGGED") for s in statuses))
        c4.metric("Now running", running or ("decided" if verdict else "—"))
        st.markdown(chip_strip(D.pipeline_stages(checkpoint, transcript, verdict, running)), unsafe_allow_html=True)

        rec = case_record(case_uid)
        if rec:
            with st.expander("The case as the agents see it (unspoiled record)"):
                io = rec["impugned_order"]
                st.markdown(f"**Impugned order** · NCLT {io['bench_city']} · {io['date']} · outcome below: `{io['outcome_below']}`")
                st.write(io["reasoning_summary"])
                st.markdown("**Issues**")
                for i in rec["issues"]:
                    st.markdown(f"- **{i['id']}** {i['text']}")

        left, right = st.columns(2, gap="large")
        for t in transcript:
            with (left if t["speaker"] == "APPELLANT" else right):
                turn_card(t)
        if running and running.startswith("turn_"):
            n = int(running[5:7])
            if n not in {t["turn"] for t in transcript}:
                side = "APPELLANT" if n % 2 else "RESPONDENT"
                with (left if side == "APPELLANT" else right):
                    st.markdown(f'<div class="lx-card" style="--side:{SIDE_COLOR[side]}"><div class="lx-head"><b>Turn {n} · {side}</b>'
                                f'<span class="lx-badge" style="background:#c99a0e">in progress</span></div>'
                                f'<div class="lx-prose">{esc(running.split("/", 1)[1])}…</div></div>', unsafe_allow_html=True)
        if verdict:
            st.success(f"Bench decided: **{verdict['label']}** (appellant {'won' if verdict['appellant_won'] else 'lost'}); "
                       f"votes {verdict['votes']}. Open the Bench view for reasons.")

    body()


# ---- Bench --------------------------------------------------------------------------------------------------
def page_bench() -> None:
    st.title("Bench")
    rc = [r for r in D.run_cases(runs_dir) if r["verdict"]]
    if not rc:
        st.info("No verdicts yet. The bench runs at the end of a debate job (payload `bench: true`, the default).")
        return
    pick = st.selectbox("Decided case", rc, format_func=lambda r: f"{r['run_id']} / {r['case_uid']}")
    v = D.read_json(runs_dir / pick["run_id"] / pick["case_uid"] / "verdict.json")
    st.markdown(f"### Result: **{v['label']}** · appellant {'won' if v['appellant_won'] else 'lost'} · "
                f"{'unanimous' if v['unanimous'] else 'with dissent'}")
    cols = st.columns(max(1, len(v["votes"])))
    for col, (persona, label) in zip(cols, v["votes"].items()):
        j = v["judgments"][persona]
        col.markdown(f'<div class="lx-vote" style="--c:{LABEL_COLOR.get(label, "#888")}"><b>{esc(persona.capitalize())}</b><br>'
                     f'{esc(label)}<br><span class="lx-disc">{"revised once · " if j.get("revised") else ""}'
                     f'{len(j.get("flags", []))} flag(s)</span></div>', unsafe_allow_html=True)
        with col.expander("Summary"):
            st.write(j["judgment"]["summary"])

    st.markdown("#### Issue by issue")
    grid = [{"issue": iss, **{p: f.get("finding") for p, f in per.items()}} for iss, per in v["issues"].items()]
    st.dataframe(pd.DataFrame(grid), hide_index=True, use_container_width=True)
    for iss, per in v["issues"].items():
        with st.expander(f"{iss}: reasons, record references, authorities"):
            for p, f in per.items():
                st.markdown(f"**{p.capitalize()}** — {f.get('finding')}")
                st.write(f.get("reasons"))
                st.caption(f"Record: {', '.join(f.get('record_refs') or []) or '—'} · Authorities: "
                           f"{', '.join(a['title'] for a in f.get('authorities_relied') or []) or '—'}"
                           + (f" · Disagrees with audit: {f['disagrees_with_global']}" if f.get("disagrees_with_global") else ""))
    if v.get("dissent"):
        st.warning("Dissent: " + "; ".join(f"{d['persona']} ({d['label']})" for d in v["dissent"]))

    st.markdown("#### THEMIS-GLOBAL (what the judges were given: findings, no verdict)")
    rep = v.get("global_report", {})
    tab1, tab2 = st.tabs(["Per issue", "Transcript-wide checks"])
    with tab1:
        for iss in rep.get("issues", []):
            st.markdown(f"**{iss['issue']}**")
            a, r = st.columns(2)
            for col, side in ((a, "appellant"), (r, "respondent")):
                f = iss.get(side) or {}
                col.markdown(f"*{side.capitalize()}*")
                for p in f.get("unanswered_points", []):
                    col.markdown(f"- unanswered: {p}")
                for c in f.get("contradictions", []):
                    col.markdown(f"- contradiction (turns {c['turns']}): {c['description']}")
                if not f.get("unanswered_points") and not f.get("contradictions"):
                    col.caption("nothing found")
    with tab2:
        det = rep.get("deterministic", {})
        per_side = det.get("per_side", {})
        if per_side:
            st.dataframe(pd.DataFrame([{"side": s, "turns": x["turns"], "claims": x["claims"],
                                        "Stage A re-run findings": len(x["stage_a_findings"]),
                                        "unsupported facts / turn": x["unsupported_fact_rate_per_turn"],
                                        "flags": json.dumps(x["flag_counts"])} for s, x in per_side.items()]),
                         hide_index=True, use_container_width=True)
        st.markdown("**Claim drift**: " + (f"{len(det.get('claim_drift', []))} fact(s) stated differently across turns"
                                           if det.get("claim_drift") else "none"))
        for d in det.get("claim_drift", []):
            st.caption(f"{d['side']} · {d['fact']}: " + " → ".join(f"turn {s['turn']}: {s['value']}" for s in d["statements"]))
        st.markdown("**Flagged citations reused**: " + (", ".join(f"{x['authority']} (turn {x['turn']})" for x in det.get("flagged_citations_reused", [])) or "none"))
        if rep.get("notes"):
            st.caption("Audit notes: " + " · ".join(rep["notes"][:6]))

    if v.get("order"):
        with st.expander("Simulated order (order writer)"):
            st.text(v["order"])

    st.markdown("#### Real outcome")
    if st.toggle("Reveal the real NCLAT outcome for this case"):
        g = D.reveal_ground_truth(db_dir, pick["case_uid"])
        if g is None:
            st.info(f"No ground truth for {pick['case_uid']} in {db_dir}. Pick the case DB this run used in the sidebar.")
        else:
            match = g["appellant_won"] == v["appellant_won"] if g["appellant_won"] is not None else None
            (st.success if match else st.error)(f"Real outcome: **{g['label']}** (appellant {'won' if g['appellant_won'] else 'lost'}) — "
                                                f"bench {'matched' if match else 'did not match'}.")
            with st.expander("Real ratio"):
                st.write(g["ratio_decidendi"])


# ---- Evaluation ---------------------------------------------------------------------------------------------
def page_eval() -> None:
    st.title("Evaluation")
    runs = D.runs_with_metrics(runs_dir)
    if not runs:
        st.info("No metrics yet. After a run: `python -m lexarena.cli evaluate --run-id <run> --split dev`.")
        return
    m = D.read_json(runs_dir / st.selectbox("Run", runs) / "metrics.json")
    st.caption(f"{m['cases_scored']} of {m['cases_in_split']} cases scored ({m['split']}); "
               f"verdicts missing: {len(m['verdicts_missing'])}. " + " ".join(m["notes"]))
    rows = [{"system": k, **{x: v.get(x) for x in ("n", "accuracy", "balanced_accuracy", "macro_f1")},
             "ci": v.get("balanced_accuracy_ci95")} for k, v in m["outcome"].items()]
    df = pd.DataFrame(rows)
    st.dataframe(df.drop(columns=["ci"]), hide_index=True, use_container_width=True)
    plot = df[df["n"].fillna(0) > 0]
    if not plot.empty:
        err = [[r["balanced_accuracy"] - r["ci"][0] if r["ci"] else 0 for _, r in plot.iterrows()],
               [r["ci"][1] - r["balanced_accuracy"] if r["ci"] else 0 for _, r in plot.iterrows()]]
        fig = go.Figure(go.Bar(x=plot["system"], y=plot["balanced_accuracy"], marker_color="#3b6fd8",
                               error_y={"type": "data", "symmetric": False, "array": err[1], "arrayminus": err[0]}))
        fig.add_hline(y=0.5, line_dash="dot", annotation_text="chance (0.5)")
        fig.update_layout(yaxis_title="Balanced accuracy (95% CI)", yaxis_range=[0, 1], height=340, margin={"t": 20, "b": 20})
        st.plotly_chart(fig, use_container_width=True)
    if m.get("system_vs_single_llm"):
        p = m["system_vs_single_llm"]
        st.markdown(f"**System vs single-LLM (same cases):** system-only correct {p['a_only_correct']}, "
                    f"baseline-only correct {p['b_only_correct']}, McNemar p = {p['p_value']:.3f}")
    st.markdown("#### THEMIS flags per side")
    st.dataframe(pd.DataFrame([{"side": s, **{k: v for k, v in x.items() if k not in ("codes", "statuses")}}
                               for s, x in m["themis_flags"].items()]), hide_index=True, use_container_width=True)
    with st.expander("Per case"):
        st.dataframe(pd.DataFrame(m["rows"]), hide_index=True, use_container_width=True)


# ---- Dashboard ----------------------------------------------------------------------------------------------
def page_dashboard() -> None:
    st.title("Dashboard")

    @st.fragment(run_every=5)
    def body():
        w = D.windows(settings.ledger_path)
        cols = st.columns(max(1, len(w)) + 1)
        for col, (name, x) in zip(cols, w.items()):
            util = x["utilization"]
            fig = go.Figure(go.Indicator(mode="gauge+number", value=(util or 0) * 100, number={"suffix": "%"},
                                         title={"text": f"{name} window · {x['status']}"},
                                         gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#3b6fd8"},
                                                "threshold": {"line": {"color": "#d64545", "width": 3}, "value": 85}}))
            fig.update_layout(height=200, margin={"t": 40, "b": 0, "l": 20, "r": 20})
            col.plotly_chart(fig, use_container_width=True)
            col.caption(("utilization not reported until a warning; " if util is None else "")
                        + (f"resets in {x['resets_in_min']} min" if x["resets_in_min"] is not None else ""))
        js = D.jobs(settings.jobs_db)
        if js:
            counts = pd.DataFrame(js).groupby(["kind", "state"]).size().unstack(fill_value=0)
            cols[-1].markdown("**Jobs**")
            cols[-1].dataframe(counts, use_container_width=True)
        st.markdown("#### Recent jobs")
        st.dataframe(pd.DataFrame([{"key": j["key"], "state": j["state"], "attempts": j["attempts"],
                                    "updated": dt.datetime.fromtimestamp(j["updated_at"]).strftime("%d %b %H:%M"),
                                    "error": (j["error"] or "")[:120]} for j in js[:30]]), hide_index=True, use_container_width=True)
        usage = D.usage_by_job(settings.ledger_path)
        if usage:
            st.markdown("#### Usage (API-equivalent cost; not billed on the subscription)")
            df = pd.DataFrame(usage)
            by_role = df.groupby("role")[["calls", "cost_usd", "output_tokens"]].sum().reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(go.Figure(go.Bar(x=by_role["role"], y=by_role["cost_usd"], marker_color="#c9822b"))
                            .update_layout(height=280, margin={"t": 10, "b": 10}, yaxis_title="$ (API-equivalent)"), use_container_width=True)
            c2.dataframe(df, hide_index=True, use_container_width=True, height=280)
        evs = D.events(settings.state_dir, tail=60)
        if evs:
            st.markdown("#### Latest steps")
            st.dataframe(pd.DataFrame([{"time": dt.datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S"), "job": e["job"],
                                        "step": e["step"], "phase": e["phase"], "seconds": e.get("seconds"), "error": e.get("error")}
                                       for e in reversed(evs)]), hide_index=True, use_container_width=True)

    body()


# ---- Cases --------------------------------------------------------------------------------------------------
def page_cases() -> None:
    st.title("Cases")
    st.caption(f"{db_dir} — unspoiled records only (what advocates and judges see).")
    cases = D.db_cases(db_dir) if db_dir and db_dir.exists() else []
    if not cases:
        st.info("No cases in this folder. Build silver with `python -m lexarena.ingest.build_silver`.")
        return
    c1, c2 = st.columns(2)
    splits = c1.multiselect("Split", sorted({c["_split"] for c in cases}), default=sorted({c["_split"] for c in cases}))
    types = c2.multiselect("Proceeding type", sorted({c["proceeding_type"] for c in cases}))
    shown = [c for c in cases if c["_split"] in splits and (not types or c["proceeding_type"] in types)]
    st.dataframe(pd.DataFrame([{"case": c["case_uid"], "split": c["_split"], "type": c["proceeding_type"],
                                "appellant": c["appellant_role"], "decision −1 day": c["law_as_of"], "issues": len(c["issues"]),
                                "events": len(c["chronology"])} for c in shown]), hide_index=True, use_container_width=True, height=260)
    if not shown:
        return
    c = next(x for x in shown if x["case_uid"] == st.selectbox("Open case", [x["case_uid"] for x in shown]))
    io = c["impugned_order"]
    st.markdown(f"### {c['title_anon']}")
    st.markdown(f"**Impugned order** · NCLT {io['bench_city']} · {io['date']} · `{io['application_type']}` → `{io['outcome_below']}`")
    st.write(io["reasoning_summary"])
    st.markdown("**Chronology**")
    st.dataframe(pd.DataFrame([{"id": e["id"], "date": e.get("date"), "event": e["event"]} for e in c["chronology"]]),
                 hide_index=True, use_container_width=True)
    st.markdown("**Issues**")
    for i in c["issues"]:
        st.markdown(f"- **{i['id']}** {i['text']}")
    a, r = st.columns(2)
    a.markdown("**Appellant grounds**")
    for g in c["appellant_grounds"]:
        a.markdown(f"- {g['id']} ({g['issue']}): {g['heading']}")
    r.markdown("**Respondent contentions**")
    for g in c.get("respondent_contentions", []):
        r.markdown(f"- {g['id']} ({g['issue']}): {g['heading']}")
    with st.expander("Typed facts and record documents"):
        st.json({"typed_facts": c.get("typed_facts"), "record_documents": c.get("record_documents")})


{"Live": page_live, "Bench": page_bench, "Evaluation": page_eval, "Dashboard": page_dashboard, "Cases": page_cases}[page]()
st.markdown('<p class="lx-disc">LexArena · research simulation, not legal advice.</p>', unsafe_allow_html=True)

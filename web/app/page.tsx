"use client";

import { useEffect, useState } from "react";
import type { RunInfo, Summary } from "@/lib/trace";

const POLL_MS = 4000;
const STAGES = ["SESSION", "BASELINE", "EVALUATE", "REFLECT"];

function statusPill(s: Summary) {
  if (s.status === "LIVE") return <span className="pill bad live">in session · {s.lastPhase.toLowerCase() || "opening"}</span>;
  if (s.status === "ABORTED") return <span className="pill bad">aborted</span>;
  if (s.status === "REBUILT") return <span className="pill neutral">rebuilt from records</span>;
  if (s.status === "EVALUATED") return <span className="pill ok">evaluated</span>;
  return <span className="pill bench">verdict</span>;
}

function winnerPill(w: string | null, status: string | null) {
  if (!status) return null;
  if (!w) return <span className="pill warn">bench unstable</span>;
  return <span className={`pill ${w === "PETITIONER" ? "pet" : "res"}`}>{w === "PETITIONER" ? "Petitioner" : "Respondent"} wins</span>;
}

export default function Home() {
  const [data, setData] = useState<{ sessions: Summary[]; runs: RunInfo[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const r = await fetch("/api/sessions", { cache: "no-store" });
        if (!stop) setData(await r.json());
        setErr(null);
      } catch (e) {
        if (!stop) setErr(String(e));
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, []);

  if (!data) return <p className="muted">{err ?? "Opening the court…"}</p>;
  const spent = data.sessions.reduce((s, x) => s + x.costUsd, 0);

  return (
    <>
      <div className="section-title" style={{ marginTop: 6 }}>
        <h2>Runs</h2>
        <span className="rule" />
      </div>
      {data.runs.length === 0 && <p className="muted small">No runs planned yet.</p>}
      <div className="grid2">
        {data.runs.map((run) => {
          const done = run.cases.filter((c) => STAGES.every((s) => ["DONE", "SKIPPED", "NOT_BUILT", "DRY"].includes(c.stages[s] ?? ""))).length;
          return (
            <div key={run.runId} className="card pad">
              <div className="row">
                <b>{run.runId}</b>
                <span className="pill neutral">{run.mode}</span>
                <span className={`pill ${run.status === "COMPLETE" ? "ok" : run.status === "RUNNING" ? "bad live" : run.status === "FAILED" ? "bad" : "warn"}`}>
                  {run.status.toLowerCase()}
                </span>
                <span className="spacer" />
                <span className="small muted">
                  {done} / {run.cases.length} cases
                </span>
              </div>
              <div className="bar" style={{ margin: "8px 0" }}>
                <span style={{ width: `${run.cases.length ? (100 * done) / run.cases.length : 0}%` }} />
              </div>
              {run.pauseReason && <div className="small warnc">{run.pauseReason}</div>}
              <div className="tablewrap">
                <table className="t">
                  <tbody>
                    {run.cases.map((c) => (
                      <tr key={c.caseId}>
                        <td className="mono">{c.seq}</td>
                        <td>{c.sessionId ? <a href={`/session/${c.sessionId}`}>{c.caseId}</a> : c.caseId}</td>
                        {STAGES.map((s) => (
                          <td key={s} className="tiny">
                            <span className={`pill ${c.stages[s] === "DONE" ? "ok" : c.stages[s] === "FAILED" ? "bad" : "neutral"}`}>{s.toLowerCase()}</span>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
      </div>

      <div className="section-title">
        <h2>Hearings</h2>
        <span className="rule" />
        <span className="small muted">
          {data.sessions.length} sessions · ${spent.toFixed(2)} in model calls shown
        </span>
      </div>
      {data.sessions.length === 0 && <p className="muted small">No session traces yet. They appear here as soon as a session starts.</p>}
      <div className="grid2">
        {data.sessions.map((s) => (
          <a key={s.id} href={`/session/${s.id}`} className="card session-card">
            <div className="row">
              <b style={{ fontFamily: "var(--serif)", fontSize: 17 }}>{s.caseId}</b>
              <span className="small muted">{s.runId}</span>
              <span className="spacer" />
              {statusPill(s)}
            </div>
            <div className="row small" style={{ marginTop: 6 }}>
              <span className="muted">{s.turnsPublished} turns</span>
              <span className="muted">· {s.calls} model calls</span>
              <span className="muted">· ${s.costUsd.toFixed(3)}</span>
              <span className="spacer" />
              {winnerPill(s.winner, s.benchStatus)}
              {s.realMatch !== null && <span className={`pill ${s.realMatch ? "ok" : "bad"}`}>{s.realMatch ? "matches the real court" : "differs from the real court"}</span>}
            </div>
            <div className="tiny muted mono" style={{ marginTop: 4 }}>{s.id}</div>
          </a>
        ))}
      </div>
    </>
  );
}

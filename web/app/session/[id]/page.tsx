"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import { build, lessonLine, ORDERS, parties, PERSONAS, sideLabel, SIDES, type Model, type Rec, type Side, type Turn } from "@/lib/model";
import { CallView, Collapse, Json, OutcomePill, Problems, schemaLabel, Thinking } from "./parts";

const POLL_MS = 3000;
type Tab = "court" | "chambers" | "file" | "costs";

// USD per million tokens, for display only (config runner.prices is the source of truth).
const PRICES: Record<string, [number, number]> = {
  "openrouter|deepseek/deepseek-v4.1-flash": [0.3, 1.2],
  "openrouter|qwen/qwen3.8-flash": [0.15, 0.47],
  "openrouter|qwen/qwen3.8-27b": [0.04, 2.3],
};
const cost = (r: Rec) => {
  const p = PRICES[`${r.provider}|${r.model}`];
  return !p || r.cached ? 0 : ((r.input_tokens ?? 0) * p[0] + (r.output_tokens ?? 0) * p[1]) / 1e6;
};

export default function SessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [recs, setRecs] = useState<Rec[]>([]);
  const [missing, setMissing] = useState(false);
  const [tab, setTab] = useState<Tab>("court");
  const last = useRef(-1);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const r = await fetch(`/api/session/${id}?after=${last.current}`, { cache: "no-store" });
        if (r.status === 404) return setMissing(true);
        const body = await r.json();
        const fresh: Rec[] = body.records ?? [];
        if (!stop && fresh.length) {
          last.current = fresh[fresh.length - 1].seq;
          setRecs((old) => [...old, ...fresh]);
        }
      } catch {
        // the next poll retries
      }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [id]);

  const m = useMemo(() => build(recs), [recs]);
  if (missing) return <p className="muted">No trace for {id}.</p>;
  if (!m.opened) return <p className="muted">Waiting for the court to sit…</p>;

  return (
    <>
      <CourtHead m={m} id={id} />
      <div className="tabs">
        {(
          [
            ["court", "Courtroom"],
            ["chambers", `Every model call (${m.llm.length})`],
            ["file", "Case file"],
            ["costs", "Costs"],
          ] as [Tab, string][]
        ).map(([k, label]) => (
          <button key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "court" && <Courtroom m={m} />}
      {tab === "chambers" && <AllCalls m={m} />}
      {tab === "file" && <CaseFile m={m} />}
      {tab === "costs" && <Costs m={m} />}
    </>
  );
}

// ------------------------------------------------------------------ header

function CourtHead({ m, id }: { m: Model; id: string }) {
  const av = m.opened!.agent_view;
  const meta = av.metadata ?? {};
  const year = String(meta.simulation_date ?? "").slice(0, 4);
  return (
    <div className="card court-head">
      <div className="forum">
        {meta.forum} · {String(meta.proceeding_type ?? "").replace(/_/g, " ").toLowerCase()} {year && `· decided ${year}`}
      </div>
      <h1>
        <span style={{ color: "var(--pet)" }}>{parties(m, "PETITIONER")}</span>
        <span className="vs">v.</span>
        <span style={{ color: "var(--res)" }}>{parties(m, "RESPONDENT")}</span>
      </h1>
      <div className="row" style={{ justifyContent: "center" }}>
        {m.live && <span className="pill bad live">in session · {(m.phase ?? "").toLowerCase()}</span>}
        {m.aborted && <span className="pill bad">aborted: {String(m.aborted.error).slice(0, 120)}</span>}
        {m.rebuilt && <span className="pill neutral">rebuilt from stored records: no reasoning text for this older session</span>}
        <span className="tiny muted mono">{id}</span>
      </div>
      <div className="issues">
        {(av.framed_issues ?? []).map((i: any) => (
          <div className="issue" key={i.issue_id}>
            <b>{i.issue_id}</b>
            <span>{i.question}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SectionTitle({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
      <span className="rule" />
      {right}
    </div>
  );
}

// ------------------------------------------------------------------ the courtroom

function Courtroom({ m }: { m: Model }) {
  const turns = [...m.turns.values()].sort((a, b) => a.turn - b.turn);
  const pending = m.live && m.phase === "TURN" && m.current?.turn && !m.turns.get(m.current.turn)?.published ? m.current : undefined;
  return (
    <>
      <SectionTitle title="Chambers: preparation (private to each side)" />
      <div className="grid2">
        {SIDES.map((s) => (
          <Preparation key={s} m={m} side={s} />
        ))}
      </div>

      <SectionTitle title="The hearing" right={<span className="small muted">{turns.filter((t) => t.published).length} submissions published</span>} />
      {turns.map((t) => (
        <TurnCard key={t.turn} t={t} m={m} />
      ))}
      {pending && !m.turns.get(pending.turn!) && (
        <div className={`turn ${pending.side}`}>
          <div className="speech">
            <div className="typing">
              {sideLabel(pending.side ?? "")} is preparing turn {pending.turn}…
            </div>
          </div>
        </div>
      )}
      {turns.length === 0 && <p className="muted small">The hearing has not started.</p>}

      {(m.audit || m.auditCalls.length > 0) && <Audit m={m} />}
      {(m.bench.size > 0 || m.verdict) && <Bench m={m} />}
      {m.verdict && <Verdict m={m} />}
    </>
  );
}

function Preparation({ m, side }: { m: Model; side: Side }) {
  const p = m.prepare[side];
  const lessons: any[] = m.opened?.lessons?.[side] ?? [];
  const explored = new Set<string>(m.opened?.explored ?? []);
  const notes = p.notes;
  const cls = side === "PETITIONER" ? "pet" : "res";
  return (
    <div className="card">
      <div className="speech-head">
        <span className={`pill ${cls}`}>{side === "PETITIONER" ? "Petitioner" : "Respondent"}</span>
        <span className="who">{sideLabel(side)}</span>
        <span className="small muted">{parties(m, side)}</span>
      </div>
      <div className="inner-body" style={{ paddingTop: 10 }}>
        <div className="small">
          <b>Experience base pinned ({lessons.length}):</b>
          {lessons.length === 0 && <span className="muted"> none yet</span>}
          {lessons.map((l) => (
            <div key={l.lesson_id} className="tiny" style={{ marginTop: 3 }}>
              <span className={`pill ${explored.has(l.lesson_id) ? "warn" : "bench"}`}>{explored.has(l.lesson_id) ? "random" : "top"}</span> {lessonLine(l)}
              {l.source_year && <span className="muted"> ({l.source_year} law)</span>}
            </div>
          ))}
        </div>
        {notes && (
          <>
            <div className="small">
              <b>Plan:</b> {notes.plan}
            </div>
            <div className="small">
              <b>Issues to press:</b> {(notes.issues_to_press ?? []).join("; ")}
            </div>
            <div className="small">
              <b>Attacks expected:</b> {(notes.expected_attacks ?? []).join("; ")}
            </div>
          </>
        )}
        {(p.held ?? []).length > 0 && (
          <Collapse title={`Authorities found in research (${p.held!.length})`}>
            {p.held!.map((c: any) => (
              <div key={c.precedent_uid} className="small">
                <span className="ref">{c.precedent_uid}</span> {c.case_title} ({c.forum}, {c.decision_date}): {c.rule}
              </div>
            ))}
          </Collapse>
        )}
        {p.calls.map((r) => (
          <CallView key={r.seq} r={r} who={sideLabel(side)} />
        ))}
        {!notes && p.calls.length === 0 && (
          <span className="small muted">{m.rebuilt ? "Not recorded for sessions run before the live trace." : "Not prepared yet."}</span>
        )}
      </div>
    </div>
  );
}

function TurnCard({ t, m }: { t: Turn; m: Model }) {
  const pub = t.published?.published;
  const tl = t.published?.themis_local;
  const attempts = [...t.attempts.values()].sort((a, b) => a.n - b.n);
  const cls = t.side === "PETITIONER" ? "pet" : "res";
  return (
    <div className={`turn ${t.side}`}>
      <div className="speech">
        <div className="speech-head">
          <span className={`pill ${cls}`}>Turn {t.turn}</span>
          <span className="who">{sideLabel(t.side)}</span>
          <span className="small muted">{t.type.toLowerCase()}</span>
          <span className="spacer" />
          {pub ? (
            <OutcomePill outcome={tl?.outcome} attempts={tl?.attempts} />
          ) : m.live ? (
            <span className="pill bad live">drafting · attempt {attempts.length || 1}</span>
          ) : (
            <span className="pill bad">never published</span>
          )}
        </div>
        {pub ? (
          <>
            <div className="speech-body">{pub.published_text}</div>
            {(pub.visible_flags ?? []).length > 0 && (
              <div className="claims">
                {pub.visible_flags.map((f: any, i: number) => (
                  <div key={i} className="small err">
                    ⚑ Verifier flag {f.code} {f.record_ids?.length ? `(${f.record_ids.join(", ")})` : ""}
                  </div>
                ))}
              </div>
            )}
            <Collapse title={`Claims the submission rests on (${pub.claims.length})`}>
              {pub.claims.map((c: any) => (
                <div key={c.claim_id} className="claim">
                  <span className="ref">{c.claim_id}</span>
                  <span>{c.text}</span>
                  {[...(c.record_ids ?? []), c.statute_id, ...(c.precedent_ids ?? [])].filter(Boolean).map((x: string) => (
                    <span key={x} className="ref">
                      {x}
                    </span>
                  ))}
                </div>
              ))}
            </Collapse>
          </>
        ) : (
          <div className="typing">{m.live ? "Being drafted and checked…" : "The session stopped before this turn was published."}</div>
        )}
        {attempts.length > 0 && (
          <Collapse title={`Behind the scenes: ${attempts.length} attempt(s), each checked by THEMIS`} open={!pub}>
            {attempts.map((a) => {
              const draft = a.calls.find((c) => c.schema === "LawyerDraft");
              const checks = a.calls.filter((c) => c.schema !== "LawyerDraft");
              const rejected = (a.check?.hard_errors ?? []).length > 0;
              return (
                <div key={a.n} className="attempt">
                  <div className="attempt-head">
                    <b>Attempt {a.n}</b>
                    {a.check && <span className={`pill ${rejected ? "bad" : "ok"}`}>{rejected ? "sent back" : "accepted"}</span>}
                  </div>
                  <div className="attempt-body">
                    {draft && <CallView r={draft} who={sideLabel(t.side)} />}
                    {rejected && a.check?.draft?.text && (
                      <Collapse title="The draft THEMIS sent back">
                        <div className="small" style={{ whiteSpace: "pre-wrap" }}>
                          {a.check.draft.text}
                        </div>
                      </Collapse>
                    )}
                    <Problems check={a.check} />
                    {checks.map((c) => (
                      <CallView key={c.seq} r={c} who="THEMIS" />
                    ))}
                  </div>
                </div>
              );
            })}
          </Collapse>
        )}
        {tl && attempts.length === 0 && (tl.hard_errors_by_attempt ?? []).some((x: string[]) => x.length) && (
          <Collapse title="THEMIS rejections before publication">
            {tl.hard_errors_by_attempt.map((codes: string[], i: number) => (
              <div key={i} className="small">
                Attempt {i + 1}: {codes.length ? <span className="err">{codes.join(", ")}</span> : <span style={{ color: "var(--ok)" }}>passed</span>}
              </div>
            ))}
          </Collapse>
        )}
        {t.lookups && (
          <Collapse title={`Lookups asked for the next turn (${(t.lookups.asked ?? []).length})`}>
            {(t.lookups.asked ?? []).map((x: any, i: number) => (
              <div key={i} className="small">
                <span className="pill neutral">{x.kind}</span> {x.query}
              </div>
            ))}
            <div className="json">{t.lookups.answers}</div>
          </Collapse>
        )}
      </div>
    </div>
  );
}

function Audit({ m }: { m: Model }) {
  const rep = m.audit?.report;
  const rd = rep?.rebuttal_depth ?? {};
  const points: any[] = rd.points ?? [];
  return (
    <>
      <SectionTitle title="THEMIS-GLOBAL: the auditor reads the whole hearing" />
      <div className="card pad">
        {rep ? (
          <div className="tablewrap">
            <table className="t">
              <thead>
                <tr>
                  <th>Side</th>
                  <th>Opponent points</th>
                  <th>Answered</th>
                  <th>Conceded</th>
                  <th>Ignored</th>
                  <th>Rebuttal depth</th>
                  <th>Self-contradictions</th>
                </tr>
              </thead>
              <tbody>
                {SIDES.map((s) => (
                  <tr key={s}>
                    <td>
                      <span className={`pill ${s === "PETITIONER" ? "pet" : "res"}`}>{s.toLowerCase()}</span>
                    </td>
                    <td>{rd[s]?.opponent_points}</td>
                    <td>{rd[s]?.answered}</td>
                    <td>{rd[s]?.conceded}</td>
                    <td>{rd[s]?.ignored}</td>
                    <td>{typeof rd[s]?.depth === "number" ? rd[s].depth.toFixed(2) : "-"}</td>
                    <td>{rep.consistency?.[s]?.contradictions ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <span className="small muted">Auditing…</span>
        )}
        {points.length > 0 && (
          <Collapse title={`Every point made, and whether it was answered (${points.length})`}>
            {points.map((p, i) => (
              <div key={i} className="small">
                <span className={`pill ${p.speaker === "PETITIONER" ? "pet" : "res"}`}>T{p.turn}</span> <span className="ref">{p.issue_id}</span> {p.summary}{" "}
                <span className={`pill ${p.status === "ANSWERED" ? "ok" : p.status === "IGNORED" ? "bad" : "warn"}`}>
                  {String(p.status).toLowerCase()}
                  {p.answered_in_turn ? ` in T${p.answered_in_turn}` : ""}
                </span>
              </div>
            ))}
          </Collapse>
        )}
        {(rep?.contradictions ?? []).length > 0 && (
          <Collapse title={`Self-contradictions found (${rep.contradictions.length}; not shown to the judges)`}>
            <Json value={rep.contradictions} />
          </Collapse>
        )}
        {m.auditCalls.map((r) => (
          <CallView key={r.seq} r={r} who="The auditor" />
        ))}
      </div>
    </>
  );
}

function Bench({ m }: { m: Model }) {
  const decisions = new Map(m.decisions.map((d) => [d.judge, d]));
  const v = m.verdict?.verdict;
  return (
    <>
      <SectionTitle title="The bench: three judges, each deciding twice with the sides in swapped order" />
      <div className="bench-wrap">
        <div className="grid3">
          {PERSONAS.map((p) => {
            const orders = m.bench.get(p);
            const d = decisions.get(p);
            const abstained = v?.abstaining_judges?.includes(p);
            return (
              <div key={p} className="judge">
                <div className="judge-head">
                  <span className="name">{p.charAt(0) + p.slice(1).toLowerCase()}</span>
                  <span className="spacer" />
                  {abstained && <span className="pill warn">abstains: the two orders disagreed</span>}
                  {d?.status === "DECIDED" && <span className={`pill ${d.result === "PETITIONER" ? "pet" : "res"}`}>for the {String(d.result).toLowerCase()}</span>}
                </div>
                <div className="judge-body">
                  {ORDERS.map((o) => {
                    const op = orders?.get(o);
                    if (!op) return null;
                    const opinion = op.opinion;
                    const invalid = opinion && "problems" in opinion;
                    const body = invalid ? opinion.draft : opinion;
                    return (
                      <div key={o} className="attempt">
                        <div className="attempt-head">
                          <b>{o === "PETITIONER_FIRST" ? "Petitioner heard first" : "Respondent heard first"}</b>
                          {body?.overall_result && (
                            <span className={`pill ${body.overall_result === "PETITIONER" ? "pet" : "res"}`}>{String(body.overall_result).toLowerCase()}</span>
                          )}
                          {opinion?.revised && <span className="pill neutral">revised once</span>}
                          {invalid && <span className="pill bad">invalid</span>}
                          {!opinion && <span className="pill bad live">deliberating</span>}
                        </div>
                        <div className="attempt-body">
                          {op.calls.map((c) => (
                            <Thinking key={c.seq} text={c.reasoning} who={`The ${p.toLowerCase()} judge`} />
                          ))}
                          {op.lookups && (
                            <div className="small">
                              <b>Looked up:</b> {(op.lookups.asked ?? []).map((x: any) => `${x.kind} ${x.query}`).join("; ")}
                            </div>
                          )}
                          {invalid && (opinion.problems ?? []).map((x: string, i: number) => <div key={i} className="tiny err">✗ {x}</div>)}
                          {body?.issue_decisions?.map((dd: any) => (
                            <div key={dd.issue_id} className="finding">
                              <span className="ref">{dd.issue_id}</span>{" "}
                              <span className={`pill ${dd.upholds === "PETITIONER" ? "pet" : dd.upholds === "RESPONDENT" ? "res" : "neutral"}`}>{String(dd.upholds).toLowerCase()}</span>
                              <div className="small">{dd.finding}</div>
                              <details className="inner" style={{ borderTop: "none" }}>
                                <summary style={{ padding: "2px 0" }}>reasoning and citations</summary>
                                <div className="tiny muted">
                                  {dd.application} → {dd.conclusion}
                                </div>
                                <div className="row" style={{ gap: 4, marginTop: 2 }}>
                                  {[...(dd.governing_rule_ids ?? []), ...(dd.record_ids ?? [])].map((x: string) => (
                                    <span key={x} className="ref">
                                      {x}
                                    </span>
                                  ))}
                                </div>
                              </details>
                            </div>
                          ))}
                          {body?.overall_reasons && (
                            <details className="inner" style={{ borderTop: "none" }}>
                              <summary style={{ padding: "2px 0" }}>overall reasons</summary>
                              <div className="small">{body.overall_reasons}</div>
                            </details>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {!orders && <span className="small muted">Waiting to sit.</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

function Verdict({ m }: { m: Model }) {
  const v = m.verdict!.verdict;
  const ev = m.evaluation?.evaluation;
  const won = v.winner;
  return (
    <>
      <SectionTitle title="Judgment" />
      <div className="verdict">
        <div className="gavel">🔨</div>
        <h2 style={{ color: won === "PETITIONER" ? "var(--pet)" : won === "RESPONDENT" ? "var(--res)" : "var(--warn)" }}>
          {won ? `The bench finds for the ${won.toLowerCase()}` : `No decision: ${String(v.unstable_reason ?? "unstable").toLowerCase().replace(/_/g, " ")}`}
        </h2>
        <div className="small muted">
          {v.decided_by && `${String(v.decided_by).toLowerCase()} · `}votes petitioner {v.votes?.PETITIONER ?? 0}, respondent {v.votes?.RESPONDENT ?? 0}
          {(v.abstaining_judges ?? []).length ? ` · abstaining: ${v.abstaining_judges.join(", ").toLowerCase()}` : ""}
        </div>
        <div className="tablewrap" style={{ marginTop: 12 }}>
          <table className="t">
            <thead>
              <tr>
                <th>Issue</th>
                <th>The bench held</th>
                <th>Votes</th>
                {ev && <th>The real court held</th>}
                {ev && <th>Same?</th>}
              </tr>
            </thead>
            <tbody>
              {(v.issue_findings ?? []).map((f: any) => {
                const real = ev?.issues?.find((x: any) => x.issue_id === f.issue_id);
                return (
                  <tr key={f.issue_id}>
                    <td className="mono">{f.issue_id}</td>
                    <td>{f.upholds ? f.upholds.toLowerCase() : <span className="warnc">{String(f.status).toLowerCase()}</span>}</td>
                    <td className="small">
                      P {f.votes?.PETITIONER ?? 0} · R {f.votes?.RESPONDENT ?? 0}
                    </td>
                    {ev && <td>{real ? `${String(real.real).toLowerCase()} (${String(real.driver).toLowerCase()})` : "-"}</td>}
                    {ev && <td>{real?.aligned === true ? "✓" : real?.aligned === false ? "✗" : "-"}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {ev ? (
          <div className="row" style={{ justifyContent: "center", marginTop: 12 }}>
            <span className="pill neutral">the real court: {String(ev.real_overall ?? "?").toLowerCase()}</span>
            {ev.winner_matches_real !== null && (
              <span className={`pill ${ev.winner_matches_real ? "ok" : "bad"}`}>{ev.winner_matches_real ? "same result as the real court" : "a different result from the real court"}</span>
            )}
            {typeof ev.issue_alignment === "number" && <span className="pill neutral">issues aligned {(100 * ev.issue_alignment).toFixed(0)}%</span>}
          </div>
        ) : (
          <div className="small muted" style={{ marginTop: 10 }}>
            The real judgment stays sealed until the evaluator runs.
          </div>
        )}
      </div>
      {m.reflection && (
        <>
          <SectionTitle title="What the agents learnt" />
          <div className="card pad small">
            <div>
              <b>Lessons written:</b> {(m.reflection.written ?? []).join(", ") || "none"}
            </div>
            {(m.reflection.rejected ?? []).length > 0 && (
              <Collapse title={`Candidates rejected (${m.reflection.rejected.length})`}>
                {m.reflection.rejected.map((x: string, i: number) => (
                  <div key={i} className="tiny">
                    {x}
                  </div>
                ))}
              </Collapse>
            )}
            {m.reflectCalls.map((r) => (
              <CallView key={r.seq} r={r} who="Reflection" />
            ))}
          </div>
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ other tabs

function AllCalls({ m }: { m: Model }) {
  const [role, setRole] = useState("all");
  const roles = [...new Set(m.llm.map((r) => r.role))];
  const shown = m.llm.filter((r) => role === "all" || r.role === role);
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        <span className="small muted">Role</span>
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="all">all</option>
          {roles.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </div>
      <div className="inner-body" style={{ padding: 0 }}>
        {shown.map((r) => (
          <div key={r.seq}>
            <div className="tiny muted" style={{ margin: "2px 0" }}>
              #{r.seq} · {r.phase ?? ""} {r.side ? `· ${r.side.toLowerCase()}` : ""} {r.turn ? `· turn ${r.turn}` : ""} {r.attempt ? `· attempt ${r.attempt}` : ""}{" "}
              {r.persona ? `· ${r.persona.toLowerCase()} ${r.order?.toLowerCase()}` : ""}
            </div>
            <CallView r={r} who={r.role} />
          </div>
        ))}
      </div>
    </>
  );
}

function CaseFile({ m }: { m: Model }) {
  const av = m.opened!.agent_view;
  const rec = av.record;
  return (
    <div className="inner-body" style={{ padding: 0 }}>
      <div className="card pad small">
        <b>Background.</b> {av.factual_background}
      </div>
      {av.lower_forum_order?.exists && (
        <div className="card pad small">
          <b>Order under appeal ({av.lower_forum_order.forum}).</b> {av.lower_forum_order.result}. {av.lower_forum_order.reasons_summary}
        </div>
      )}
      <div className="card pad">
        <h3 style={{ fontSize: 16, marginBottom: 6 }}>Stipulated facts</h3>
        {rec.stipulated_facts.map((f: any) => (
          <div key={f.fact_id} className="claim">
            <span className="ref">{f.fact_id}</span>
            <span>{f.text}</span>
          </div>
        ))}
      </div>
      <div className="card pad">
        <h3 style={{ fontSize: 16, marginBottom: 6 }}>Contested facts</h3>
        {rec.contested_facts.map((c: any) => (
          <div key={c.fact_id} className="finding small">
            <span className="ref">{c.fact_id}</span> <b>{c.question}</b>
            <div className="grid2" style={{ marginTop: 4 }}>
              <div style={{ color: "var(--pet)" }}>Petitioner: {c.petitioner_version}</div>
              <div style={{ color: "var(--res)" }}>Respondent: {c.respondent_version}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="card pad">
        <h3 style={{ fontSize: 16, marginBottom: 6 }}>Exhibits</h3>
        {rec.exhibits.map((e: any) => (
          <div key={e.exhibit_id} className="claim">
            <span className="ref">{e.exhibit_id}</span>
            <span>
              <b>{e.title}</b> ({String(e.filed_by).toLowerCase()}): {(e.known_contents ?? []).join("; ")}
            </span>
          </div>
        ))}
      </div>
      <div className="card pad">
        <h3 style={{ fontSize: 16, marginBottom: 6 }}>Amounts</h3>
        {rec.amounts.map((a: any) => (
          <div key={a.amount_id} className="claim">
            <span className="ref">{a.amount_id}</span>
            <span>
              {a.label}: ₹{Number(a.value_inr).toLocaleString("en-IN")} {a.date ? `(${a.date})` : ""}
            </span>
          </div>
        ))}
      </div>
      <div className="card pad">
        <h3 style={{ fontSize: 16, marginBottom: 6 }}>Procedural history</h3>
        {(av.procedural_history ?? []).map((s: any) => (
          <div key={s.step} className="claim">
            <span className="ref">{s.date}</span>
            <span>
              {s.forum}: {s.event}
            </span>
          </div>
        ))}
      </div>
      <div className="card pad">
        <h3 style={{ fontSize: 16, marginBottom: 6 }}>Pleaded grounds</h3>
        <div className="grid2">
          {SIDES.map((s) => (
            <div key={s}>
              <span className={`pill ${s === "PETITIONER" ? "pet" : "res"}`}>{s.toLowerCase()}</span>
              {(av.opening_positions?.[s] ?? []).map((g: any, i: number) => (
                <div key={i} className="small" style={{ marginTop: 4 }}>
                  <span className="ref">{g.issue_id}</span> {g.ground}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Costs({ m }: { m: Model }) {
  const by = new Map<string, { calls: number; tin: number; tout: number; usd: number; secs: number }>();
  for (const r of m.llm) {
    const k = `${r.role} · ${schemaLabel(r.schema)}`;
    const v = by.get(k) ?? { calls: 0, tin: 0, tout: 0, usd: 0, secs: 0 };
    v.calls += 1;
    v.tin += r.input_tokens ?? 0;
    v.tout += r.output_tokens ?? 0;
    v.usd += cost(r);
    v.secs += r.latency_s ?? 0;
    by.set(k, v);
  }
  const rows = [...by.entries()].sort((a, b) => b[1].usd - a[1].usd);
  const total = rows.reduce((s, [, v]) => s + v.usd, 0);
  return (
    <div className="card pad">
      <div className="tablewrap">
        <table className="t">
          <thead>
            <tr>
              <th>Call</th>
              <th>Calls</th>
              <th>Tokens in</th>
              <th>Tokens out</th>
              <th>Time</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{v.calls}</td>
                <td>{v.tin.toLocaleString()}</td>
                <td>{v.tout.toLocaleString()}</td>
                <td>{v.secs ? `${Math.round(v.secs / 60)} min` : "-"}</td>
                <td>${v.usd.toFixed(4)}</td>
              </tr>
            ))}
            <tr>
              <td>
                <b>Total</b>
              </td>
              <td colSpan={4} />
              <td>
                <b>${total.toFixed(3)}</b>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="tiny muted" style={{ marginTop: 6 }}>
        At list prices; cached calls cost nothing.
      </div>
    </div>
  );
}

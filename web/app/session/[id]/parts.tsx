"use client";

import { useState } from "react";
import type { Rec } from "@/lib/model";

const SCHEMA_LABEL: Record<string, string> = {
  ResearchPlan: "Research plan",
  StrategyNotes: "Strategy notes",
  LawyerDraft: "Draft submission",
  ArgumentExtraction: "THEMIS layer 1: claims mirrored to the statute checklists",
  Layer2Review: "THEMIS layer 2: record fidelity and responsiveness",
  FidelityConfirmation: "THEMIS: second check before rejecting",
  EntailmentBatch: "THEMIS: do the cited precedents support the claims?",
  TranscriptAudit: "THEMIS-GLOBAL: map of the whole hearing",
  OpinionDraft: "Judge's opinion",
  LessonCandidates: "Reflection: lessons from this case",
  CompareVerdict: "Reflection: is this lesson new?",
  SingleLLMDraft: "Single-model baseline",
};

export function schemaLabel(s: string): string {
  return SCHEMA_LABEL[s] ?? s;
}

export function Thinking({ text, who }: { text?: string | null; who: string }) {
  if (!text) return null;
  return (
    <div className="thinking">
      <span className="label">💭 {who} is thinking</span>
      {text}
    </div>
  );
}

export function Json({ value }: { value: unknown }) {
  return <div className="json">{JSON.stringify(value, null, 2)}</div>;
}

export function Collapse({ title, children, open = false }: { title: React.ReactNode; children: React.ReactNode; open?: boolean }) {
  return (
    <details className="inner" open={open}>
      <summary>{title}</summary>
      <div className="inner-body">{children}</div>
    </details>
  );
}

export function tokens(r: Rec): string {
  if (r.cached) return "from cache";
  const i = r.input_tokens ?? "?";
  const o = r.output_tokens ?? "?";
  const lat = typeof r.latency_s === "number" ? ` · ${Math.round(r.latency_s)}s` : "";
  return `${i} in / ${o} out${lat}`;
}

export function CallView({ r, who, showOutput = true }: { r: Rec; who: string; showOutput?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="attempt">
      <div className="attempt-head">
        <b>{schemaLabel(r.schema)}</b>
        <span className="pill neutral">{r.role}</span>
        <span className="tiny muted">{r.model}</span>
        <span className="tiny muted">· {tokens(r)}</span>
        {r.error && <span className="pill bad">{String(r.error).slice(0, 80)}</span>}
        <span className="spacer" />
        {showOutput && r.output && (
          <button className="theme-btn" style={{ color: "var(--muted)", borderColor: "var(--line)" }} onClick={() => setOpen(!open)}>
            {open ? "hide answer" : "show answer"}
          </button>
        )}
      </div>
      {(r.reasoning || open) && (
        <div className="attempt-body">
          <Thinking text={r.reasoning} who={who} />
          {open && <Json value={r.output} />}
        </div>
      )}
    </div>
  );
}

export function Problems({ check }: { check?: Rec }) {
  if (!check) return null;
  const errs: any[] = check.hard_errors ?? [];
  const warns: any[] = check.warnings ?? [];
  return (
    <div className="themis-box">
      <span className="label">⚖ THEMIS-LOCAL verdict on this attempt</span>
      {errs.length === 0 ? (
        <div className="small" style={{ color: "var(--ok)" }}>
          No hard error{warns.length ? `; ${warns.length} note(s)` : ""}.
        </div>
      ) : (
        errs.map((e, i) => (
          <div key={i} className="small err">
            ✗ <b>{e.code}</b> {e.detail}
            {e.record_ids?.length ? <span className="ref">{e.record_ids.join(", ")}</span> : null}
          </div>
        ))
      )}
      {warns.map((w, i) => (
        <div key={i} className="tiny warnc">
          △ {w.code}: {w.detail}
        </div>
      ))}
    </div>
  );
}

export function OutcomePill({ outcome, attempts }: { outcome?: string; attempts?: number }) {
  if (!outcome) return null;
  const cls = outcome === "PASS" ? "ok" : outcome === "PASS_WITH_NOTES" ? "themis" : "bad";
  const label = outcome === "PASS" ? "verified" : outcome === "PASS_WITH_NOTES" ? "verified with notes" : "published FLAGGED";
  return (
    <span className={`pill ${cls}`}>
      ⚖ {label}
      {attempts && attempts > 1 ? ` · ${attempts} attempts` : ""}
    </span>
  );
}

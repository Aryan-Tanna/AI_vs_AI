// Reads the session traces the Python side writes (lexarena/trace.py, D-110) and the run ledgers. Server-side only.
// Read-only: this app never writes anywhere, and it is served on 127.0.0.1 only.

import { promises as fs } from "fs";
import path from "path";

export const REPO_ROOT = process.env.LEXARENA_ROOT ?? path.resolve(process.cwd(), "..");
export const TRACE_DIR = path.join(REPO_ROOT, "runs", "live");
export const RUNS_DIR = path.join(REPO_ROOT, "runs");
const SAFE_ID = /^[A-Za-z0-9_.-]+$/;

export type Rec = { seq: number; ts?: string | null; kind: "llm" | "event"; event?: string; [k: string]: any };

export function safeId(id: string): boolean {
  return SAFE_ID.test(id);
}

export async function readTrace(id: string): Promise<Rec[]> {
  if (!safeId(id)) throw new Error("bad id");
  const text = await fs.readFile(path.join(TRACE_DIR, `${id}.jsonl`), "utf-8");
  const out: Rec[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      out.push(JSON.parse(line));
    } catch {
      // the last line may be half written while the session runs: skip it, the next poll gets it whole
    }
  }
  return out;
}

export type Summary = {
  id: string;
  caseId: string;
  runId: string;
  status: "LIVE" | "VERDICT" | "EVALUATED" | "ABORTED" | "REBUILT";
  turnsPublished: number;
  lastPhase: string;
  winner: string | null;
  benchStatus: string | null;
  realMatch: boolean | null;
  // Set once the evaluation ran, also when there is no verdict comparison (real outcome MIXED, or bench unstable).
  evaluated: boolean;
  realOverall: string | null;
  issueAlignment: number | null;
  costUsd: number;
  calls: number;
  updated: number;
};

// USD per million tokens, mirrored from config runner.prices for display only (the guard lives in Python).
const PRICES: Record<string, [number, number]> = {
  "openrouter|deepseek/deepseek-v4.1-flash": [0.3, 1.2],
  "openrouter|qwen/qwen3.8-flash": [0.15, 0.47],
  "openrouter|qwen/qwen3.8-27b": [0.04, 2.3],
  "openrouter|google/gemini-3.5-flash": [1.5, 9.0],
};

export function callCost(r: Rec): number {
  if (r.kind !== "llm" || r.cached) return 0;
  const p = PRICES[`${r.provider}|${r.model}`];
  if (!p) return 0;
  return ((r.input_tokens ?? 0) * p[0] + (r.output_tokens ?? 0) * p[1]) / 1e6;
}

export function summarize(id: string, recs: Rec[], mtime: number): Summary {
  const opened = recs.find((r) => r.event === "case_opened");
  const has = (e: string) => recs.some((r) => r.event === e);
  const verdict = recs.find((r) => r.event === "verdict")?.verdict;
  const evaluation = recs.find((r) => r.event === "evaluation")?.evaluation;
  const last = [...recs].reverse().find((r) => r.phase);
  let status: Summary["status"] = "LIVE";
  if (opened?.rebuilt) status = "REBUILT";
  else if (has("aborted")) status = "ABORTED";
  else if (evaluation) status = "EVALUATED";
  else if (verdict) status = "VERDICT";
  const llm = recs.filter((r) => r.kind === "llm");
  return {
    id,
    caseId: opened?.case_id ?? id.split("_").slice(0, 2).join("_"),
    runId: opened?.run_id ?? "",
    status,
    turnsPublished: recs.filter((r) => r.event === "turn_published").length,
    lastPhase: last?.phase ?? "",
    winner: verdict?.winner ?? null,
    benchStatus: verdict?.status ?? null,
    realMatch: evaluation?.winner_matches_real ?? null,
    evaluated: Boolean(evaluation),
    realOverall: evaluation?.real_overall ?? null,
    issueAlignment: typeof evaluation?.issue_alignment === "number" ? evaluation.issue_alignment : null,
    costUsd: llm.reduce((s, r) => s + callCost(r), 0),
    calls: llm.length,
    updated: mtime,
  };
}

export async function listSessions(): Promise<Summary[]> {
  let names: string[] = [];
  try {
    names = (await fs.readdir(TRACE_DIR)).filter((n) => n.endsWith(".jsonl"));
  } catch {
    return [];
  }
  const out: Summary[] = [];
  for (const n of names) {
    const id = n.slice(0, -".jsonl".length);
    if (!safeId(id)) continue;
    const stat = await fs.stat(path.join(TRACE_DIR, n));
    out.push(summarize(id, await readTrace(id), stat.mtimeMs));
  }
  return out.sort((a, b) => b.updated - a.updated);
}

export type RunInfo = {
  runId: string;
  status: string;
  pauseReason: string | null;
  mode: string;
  cases: { seq: number; caseId: string; stages: Record<string, string>; sessionId?: string }[];
};

export async function listRuns(): Promise<RunInfo[]> {
  let dirs: string[] = [];
  try {
    dirs = await fs.readdir(RUNS_DIR);
  } catch {
    return [];
  }
  const out: RunInfo[] = [];
  for (const d of dirs) {
    if (!safeId(d) || d === "live") continue;
    try {
      const led = JSON.parse(await fs.readFile(path.join(RUNS_DIR, d, "ledger.json"), "utf-8"));
      out.push({
        runId: led.manifest.run_id,
        status: led.status,
        pauseReason: led.pause_reason,
        mode: led.manifest.mode,
        cases: led.jobs.map((j: any) => ({
          seq: j.seq,
          caseId: j.case_id,
          stages: Object.fromEntries(j.stages.map((s: any) => [s.stage, s.status])),
          sessionId: j.stages.find((s: any) => s.stage === "SESSION")?.outputs?.session_id,
        })),
      });
    } catch {
      // not a run directory
    }
  }
  return out.sort((a, b) => a.runId.localeCompare(b.runId));
}

// Turns a session trace (lexarena/trace.py records, in order) into what the courtroom page shows. Pure; client-safe.

export type Rec = { seq: number; ts?: string | null; kind: "llm" | "event"; event?: string; [k: string]: any };
export type Side = "PETITIONER" | "RESPONDENT";
export const SIDES: Side[] = ["PETITIONER", "RESPONDENT"];
export const PERSONAS = ["TEXTUALIST", "PURPOSIVIST", "PROCEDURALIST"];
export const ORDERS = ["PETITIONER_FIRST", "RESPONDENT_FIRST"];

export type Attempt = { n: number; calls: Rec[]; check?: Rec };
export type Turn = {
  turn: number;
  side: Side;
  type: string;
  attempts: Map<number, Attempt>;
  published?: Rec;
  lookups?: Rec;
};
export type Opinion = { calls: Rec[]; opinion?: any; lookups?: Rec };

export type Model = {
  opened?: Rec;
  prepare: Record<Side, { calls: Rec[]; notes?: any; held?: any[] }>;
  turns: Map<number, Turn>;
  audit?: Rec;
  auditCalls: Rec[];
  bench: Map<string, Map<string, Opinion>>;
  decisions: any[];
  verdict?: Rec;
  evaluation?: Rec;
  reflection?: Rec;
  reflectCalls: Rec[];
  aborted?: Rec;
  llm: Rec[];
  rebuilt: boolean;
  live: boolean;
  phase?: string;
  current?: { side?: Side; turn?: number; attempt?: number };
};

export function build(recs: Rec[]): Model {
  const m: Model = {
    prepare: { PETITIONER: { calls: [] }, RESPONDENT: { calls: [] } },
    turns: new Map(),
    auditCalls: [],
    bench: new Map(),
    decisions: [],
    reflectCalls: [],
    llm: [],
    rebuilt: false,
    live: false,
  };
  const turnOf = (r: Rec): Turn | undefined => {
    if (typeof r.turn !== "number" || !r.side) return undefined;
    let t = m.turns.get(r.turn);
    if (!t) {
      t = { turn: r.turn, side: r.side, type: r.turn_type ?? "", attempts: new Map() };
      m.turns.set(r.turn, t);
    }
    if (r.turn_type) t.type = r.turn_type;
    return t;
  };
  const attemptOf = (t: Turn, n: number): Attempt => {
    let a = t.attempts.get(n);
    if (!a) {
      a = { n, calls: [] };
      t.attempts.set(n, a);
    }
    return a;
  };
  const opinionOf = (persona: string, order: string): Opinion => {
    if (!m.bench.has(persona)) m.bench.set(persona, new Map());
    const p = m.bench.get(persona)!;
    if (!p.has(order)) p.set(order, { calls: [] });
    return p.get(order)!;
  };

  for (const r of recs) {
    if (r.phase) {
      m.phase = r.phase;
      m.current = { side: r.side, turn: r.turn, attempt: r.attempt };
    }
    if (r.kind === "llm") {
      m.llm.push(r);
      if (r.phase === "PREPARE" && r.side) m.prepare[r.side as Side].calls.push(r);
      else if (r.phase === "TURN") {
        const t = turnOf(r);
        if (t) attemptOf(t, r.attempt ?? 1).calls.push(r);
      } else if (r.phase === "AUDIT") m.auditCalls.push(r);
      else if (r.phase === "BENCH" && r.persona) opinionOf(r.persona, r.order).calls.push(r);
      else if (r.phase === "REFLECT") m.reflectCalls.push(r);
      continue;
    }
    switch (r.event) {
      case "case_opened":
        m.opened = r;
        m.rebuilt = !!r.rebuilt;
        break;
      case "prepared":
        m.prepare[r.side as Side].notes = r.notes;
        m.prepare[r.side as Side].held = r.held;
        break;
      case "themis_check": {
        const t = turnOf(r);
        if (t) attemptOf(t, r.attempt ?? 1).check = r;
        break;
      }
      case "turn_published": {
        const t = turnOf(r);
        if (t) t.published = r;
        break;
      }
      case "lookups": {
        const t = turnOf(r);
        if (t) t.lookups = r;
        break;
      }
      case "audit":
        m.audit = r;
        break;
      case "opinion":
        opinionOf(r.persona, r.order).opinion = r.opinion;
        break;
      case "judge_lookups":
        opinionOf(r.persona, r.order).lookups = r;
        break;
      case "judge_decision":
        m.decisions.push(r.decision);
        for (const o of r.decision.opinions ?? []) opinionOf(r.decision.judge, o.order).opinion = o;
        break;
      case "verdict":
        m.verdict = r;
        break;
      case "evaluation":
        m.evaluation = r;
        break;
      case "reflection":
        m.reflection = r;
        break;
      case "aborted":
        m.aborted = r;
        break;
    }
  }
  m.live = !m.rebuilt && !m.verdict && !m.aborted;
  return m;
}

export function sideLabel(side: string): string {
  return side === "PETITIONER" ? "Counsel for the Petitioner" : "Counsel for the Respondent";
}

export function parties(m: Model, side: Side): string {
  const ps = (m.opened?.agent_view?.parties ?? []).filter((p: any) => p.simulation_side === side);
  return ps.map((p: any) => `${p.pseudonym} (${String(p.status).toLowerCase().replace(/_/g, " ")})`).join(", ");
}

export function lessonLine(l: any): string {
  return `When ${l.trigger}: ${l.lesson}`;
}

# LexArena: Verified Multi-Agent Courtroom Simulation Framework

### Complete Architectural, Mathematical, and Operational Technical Blueprint

---

## 1. Executive Summary & Problem Formulation

### 1.1 What the System Is

**LexArena** is an autonomous, multi-agent adversarial simulation environment designed to model corporate courtroom litigation under Indian Corporate Law—specifically corporate insolvency resolution disputes before the National Company Law Tribunal (NCLT) and the National Company Law Appellate Tribunal (NCLAT).

Rather than treating legal reasoning as a single-turn question-answering task, LexArena frames litigation as an adversarial, multi-turn game between two competing advocate agents:

* **LEX-P** (Petitioner / Plaintiff)
* **LEX-D** (Respondent / Corporate Debtor / Defendant)

These agents litigate across ten structured debate turns before a **Three-Persona Judicial Bench** (Textualist, Commercial Pragmatist, and Proceduralist).

Crucially, the entire debate is arbitrated in real time by **THEMIS-LOCAL**—a hybrid verification gate combining symbolic Satisfiability Modulo Theories (SMT) mathematical solvers with local dense vector semantic checking—and post-trial by **THEMIS-GLOBAL**.

The system undergoes continuous, in-context self-improvement across a 500-case training curriculum through an **Agent Reflection Engine** that updates vector-indexed episodic memory without modifying the underlying frozen weights of the foundation LLMs.

```
                ┌─────────────────────────────────────────────────────────┐
                │                    LEXARENA PIPELINE                    │
                └────────────────────────────┬────────────────────────────┘
                                             │
      ┌──────────────────────────────────────┴──────────────────────────────────────┐
      ▼                                                                             ▼
┌───────────────────────────┐                                         ┌───────────────────────────┐
│     STATUTORY DOMAIN      │                                         │    CORE RESEARCH GAPS     │
├───────────────────────────┤                                         ├───────────────────────────┤
│ • Insolvency & Bankruptcy │                                         │ 1. Legal Hallucinations   │
│   Code, 2016 (IBC)        │                                         │ 2. Single-Agent Bias      │
│ • Companies Act, 2013     │                                         │ 3. Static/Stateless LLMs  │
│ • Limitation Act, 1963    │                                         │ 4. Formalist Judicial     │
│ • Indian Contract Act     │                                         │    Over-simplification    │
└───────────────────────────┘                                         └───────────────────────────┘

```

---

### 1.2 Why Existing Legal AI Fails

Current state-of-the-art Legal AI architectures suffer from five structural deficiencies:

1. **The Citation Hallucination Trap:** Generative models produce convincing yet fabricated case citations, non-existent bench orders, or inverted statutory provisions.


2. **Failure of Standard RAG on Temporal and Quantitative Constraints:** Standard vector search retrieves text based on linguistic proximity. In Indian insolvency, disputes hinge on exact arithmetic conditions (such as whether a financial default meets the statutory ₹1 Crore threshold under Section 4 of the IBC) and temporal windows (such as whether a Section 7 petition was filed within 3 years of default under Article 137 of the Limitation Act, or if balance sheet entries reset the clock under Section 18). Probabilistic RAG cannot verify mathematical satisfiability.


3. **The Stateless API Memory Problem:** When foundation LLMs interact over stateless APIs across 500 cases, the models retain zero memory of past procedural mistakes. An agent that makes a flawed argument in Case 1 will make the exact same error in Case 450 unless structured in-context memory retention is enforced.
4. **Single-Agent Confirmation Bias:** Querying a single model for a legal opinion yields an echo chamber of the prompt's assumptions. Real law is inherently adversarial; truth and procedural validity emerge only when contradictory arguments are subjected to cross-examination.
5. **Judicial Formalism vs. Equitable Pragmatism:** Monolithic AI judges act as rigid legal formalists, applying statutory text literally without understanding commercial reality or procedural equity.

---

## 2. High-Level System Architecture & Database Separation

The architecture is partitioned into two specialized database environments to balance deterministic precision with low-latency semantic retrieval:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   DATA INFRASTRUCTURE                                       │
├──────────────────────────────────────────────┬──────────────────────────────────────────────┤
│               MONGODB CLUSTER                │             QDRANT VECTOR ENGINE             │
│            (Deterministic State)             │             (Dense Semantic Memory)          │
├──────────────────────────────────────────────┼──────────────────────────────────────────────┤
│ • Laws DB: Bare Acts, Rules, L4L Predicates  │ • Precedent DB: 500 NCLT/NCLAT Vector Points │
│ • Public DB: Transcripts, Trial Artifacts    │ • Case Library (C): Thresholded RAG (τ=0.75) │
│ • Bench DB: Judicial Scorecards & Calibration│ • KB-P / KB-D: Agent Experience (τ=0.90)     │
└──────────────────────────────────────────────┴──────────────────────────────────────────────┘

```

### 2.1 MongoDB: Deterministic Relational & Document Store

* **`laws_db`:** Houses exact statutory provisions, section hierarchies, sub-clauses, and pre-compiled **Logic-for-Law (L4L)** diagnostic checklists. It does not use vector embeddings. Statutes require exact, deterministic retrieval via section IDs (e.g., `IBC_SEC_7`) to prevent semantic drift from pulling unrelated provisions.
* **`public_db`:** The permanent ledger storing multi-turn trial transcripts, audit logs from `THEMIS-LOCAL`, and historical ground truth records.
* **`bench_db`:** Stores multi-criteria scoring breakdowns from the Textualist, Pragmatist, and Proceduralist judges, as well as Human-AI judicial divergence logs.



### 2.2 Qdrant: Dense Vector Database Engine

* **Precedent Database (`nclt_precedents` / `case_library`):** Contains dense vector embeddings of 500 real, highly curated NCLT/NCLAT historical disputes encoded via `BAAI/bge-small-en-v1.5` (384-dimensional vector space).
* **Agent Private Experience Memory (`kb_e_memory_p` and `kb_e_memory_d`):** Dedicated vector collections for `LEX-P` and `LEX-D`. Stores tactical anti-patterns, procedural failure lessons, and winning moves with associated **Retention Weights ($W$)**, queried via strict semantic deduplication thresholds ($\tau_{\text{dedup}} = 0.90$).

---

## 3. Data Ingestion, Structuring, and the "Unspoiled Case" Model

### 3.1 The Unspoiled Case Protocol

A core innovation of LexArena is the prevention of outcome leakage. In standard legal benchmarks, models are evaluated on raw judgment texts that inadvertently contain the judge’s final decision, leading to data contamination.

The **Clerk State Machine** ingests raw tribunal orders (PDF format), strips away all judicial commentary, bench ratio, and final dispositions, and isolates the pre-trial facts into an **Unspoiled Case Payload**. The final ruling is stored separately in an encrypted, isolated `ground_truth` block accessed only by `THEMIS-GLOBAL` during post-trial evaluation.

```
RAW TRIBUNAL ORDER (PDF)
        │
        ▼ (pdfminer.six + GPT-4o-mini Parsing)
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SPLIT DOCUMENT ARCHITECTURE                        │
├──────────────────────────────────────┬──────────────────────────────────────┤
│    UNSPOILED CASE DATA (Active)      │     GROUND TRUTH DATA (Isolated)     │
│   (Fed to LEX-P and LEX-D at t=0)    │  (Hidden; Fed only to Post-Trial)    │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ 1. Metadata & Tribunal Bench         │ 1. Historical Final Verdict          │
│ 2. Core Factual Background           │ 2. Historical Case Citation          │
│ 3. Claim Quantum & Default Metrics   │ 3. Bench Ratio Summary               │
│ 4. Framed Legal Issues (Neutral)     │ 4. Court's Specific Legal Analysis   │
│ 5. Petitioner Starting Position      │                                      │
│ 6. Respondent Starting Position      │                                      │
│ 7. Statutory Provisions Invoked      │                                      │
└──────────────────────────────────────┴──────────────────────────────────────┘

```

### 3.2 The 6 Essential Sections of an Unspoiled Case

1. **Tribunal Metadata:** Identifies the bench (e.g., *NCLT Mumbai Bench III*), filing year, and governing statute.
2. **Core Factual Background:** Objective chronological narrative of the commercial relationship, loan disbursement or service delivery, and the emergence of default.
3. **Claim Quantum & Dates:** Exact monetary amounts (principal, interest) and precise calendar dates of default.
4. **Framed Legal Issues:** 2 to 4 structured, open-ended legal questions formulated to center the adversarial debate (e.g., *"Whether balance sheet acknowledgment resets limitation under Section 18 of the Limitation Act?"*).


5. **Petitioner & Respondent Starting Contention Headers:** Initial grounds asserted in the petition and initial objections raised in the reply affidavit.
6. **Statutory Provisions Invoked:** Explicit list of section identifiers triggering diagnostic checklist lookups in the Laws DB.

### 3.3 Evidentiary Mode vs. Substantive Moot Court Mode

When sourcing high-volume datasets, physical documentary evidence (bank statements, NeSL records, postal receipts) is not always fully readable from judgment texts.

To prevent `LEX-D` from exploiting missing documents and stalling the debate with repeated evidentiary objections (*"Petitioner failed to produce the certified bank statement, petition must be dismissed"*), LexArena supports **Substantive Law Presumption Mode**:

* The system prompt injects an explicit legal presumption:

$$\forall d \in \text{ClaimQuantum}, \quad \text{PresumeDocumented}(d) = \text{True}$$


* This forces both agents to litigate purely on statutory interpretation, limitation laws, pre-existing disputes, and commercial definitions, rather than falling into procedural avoidance loops.

---

## 4. Multi-Agent Courtroom Runtime Workflow

The live simulation follows five distinct phases:

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   LIVE SIMULATION PHASES                                        │
├─────────────────┬─────────────────┬───────────────────┬───────────────────┬─────────────────────┤
│     PHASE 0     │     PHASE 1     │      PHASE 2      │      PHASE 3      │       PHASE 4       │
│   Offline KB    │ 10-Turn Debate  │    Post-Trial     │  Judicial Bench   │  Agent Reflection   │
│  Construction   │  & Local Audit  │  Forensic Audit   │    Evaluation     │  & Memory Update    │
└─────────────────┴─────────────────┴───────────────────┴───────────────────┴─────────────────────┘

```

```
                                  PHASE 1: LIVE RUNTIME
                                  
     Clerk State Machine: Loads Unspoiled Case + Fetches Dynamic Context
                                        │
                                        ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ Turn r: LEX Agent Draft Generation                                     │
   │ Input: Strategy Plan + Laws Context + Pinned Anti-Patterns + RAG Cases │
   └────────────────────────────────────┬───────────────────────────────────┘
                                        │
                                        ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ THEMIS-LOCAL Audit Gate                                                │
   │ 1. SMT Logic Solver (Z3): Validates numerical & temporal constraints   │
   │ 2. Dense Semantic Verifier: Verifies citations against Qdrant payloads │
   └────────────────────────────────────┬───────────────────────────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 │                                             │
      [FAIL: S_local < 0.70]                        [PASS: S_local >= 0.70]
                 │                                             │
                 ▼                                             ▼
┌───────────────────────────────────┐        ┌───────────────────────────────────┐
│ Max 3 Retries                     │        │ Commit Argument to Public DB      │
│ Injects exact SMT error violation │        │ Update Multi-Turn Transcript Log  │
│ into next draft prompt            │        │ Hand over turn to Opposing Agent  │
└───────────────────────────────────┘        └───────────────────────────────────┘

```

### 4.1 Step-by-Step Runtime Execution

#### Step 1: Initialization & Dynamic Context Slicing

When an unseen case begins, the Clerk State Machine extracts its factual summary and invokes Qdrant and MongoDB to build the agent's context window. Instead of dumping all past data, the Clerk constructs a focused prompt of **~500 to 650 tokens** total Knowledge Base overhead:

* **Regulations ($R$):** The top statutory diagnostic checklist items for the invoked sections.
* **Experience Base ($E$):** The top 5 highest-weighted anti-pattern rules (e.g., *"Do not cite COVID-19 hardship for corporate term loans"*).
* **Case Library ($C$):** Sliced via thresholded vector search. If historical cases in Qdrant have a cosine similarity $\ge 0.75$ with the current facts, the top 1 or 2 winning pivots are injected. If no cases meet this cutoff, 0 cases are injected, saving tokens and preventing false analogies.

#### Step 2: Adversarial Debate Turns (1 to 10)

`LEX-P` opens in Turn 1 by submitting its Petition Arguments. The draft does not go directly to the public transcript. It must first pass `THEMIS-LOCAL`.

#### Step 3: Real-Time THEMIS-LOCAL Interception

`THEMIS-LOCAL` evaluates the draft:

* **Layer 1 (SMT Mathematical Gate):** Verifies that claimed dates, limitation calculations, and statutory financial thresholds satisfy formal logic.
* **Layer 2 (Semantic Grounding Gate):** Checks that all cited case citations exist in the Precedent Database and that the stated legal principles match their vector payloads.
* If the draft scores $S_{\text{local}} \ge 0.70$, it is committed to the Public Case DB and visible to the opponent.
* If it scores $S_{\text{local}} < 0.70$, it triggers an immediate in-turn regeneration loop (up to 3 retries), feeding the exact failure reason back to the agent.

#### Step 4: Turn Progression

`LEX-D` receives the verified Turn 1 submission, formulates its defense and counter-arguments, passes through its own `THEMIS-LOCAL` gate, and publishes Turn 2. This alternating structure continues across 10 rounds, covering Sur-Rejoinders and Closing Statements.

---

## 5. Verification Framework: THEMIS-LOCAL and THEMIS-GLOBAL

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   THEMIS VERIFICATION SUITE                                     │
├────────────────────────────────────────────────┬────────────────────────────────────────────────┤
│                  THEMIS-LOCAL                  │                 THEMIS-GLOBAL                  │
│             (In-Turn Micro-Auditor)            │             (Post-Trial Macro-Auditor)         │
├────────────────────────────────────────────────┼────────────────────────────────────────────────┤
│ • Execution: Real-time per turn (Synchronous)  │ • Execution: After Turn 10 closes (Batch)      │
│ • Layer 1: Microsoft Z3 SMT Symbolic Solver    │ • Transcript Aggregation: Multi-turn coherence │
│ • Layer 2: Vector Cross-checking (BGE-M3)      │ • Forensic Hallucination & Rebuttal Auditing   │
│ • Enforces: Mathematical/Temporal/Statutory    │ • Computes: S_global composite score vector    │
│   bounds; Blocks invalid drafts before release │ • Triggers: Multi-Persona Judicial Evaluation  │
└────────────────────────────────────────────────┴────────────────────────────────────────────────┘

```

### 5.1 THEMIS-LOCAL Deep Dive

`THEMIS-LOCAL` functions as a real-time gatekeeper. It enforces two layers of verification:

```
[Agent Draft Argument]
          │
          ▼
┌──────────────────────────────────────────────────────┐
│ Layer 1: Logic-for-Law (L4L) + Z3 SMT Solver         │
│ Checks: Temporal bounds, debt thresholds, statutory  │
│ preconditions. Returns SAT (1) or UNSAT (0).         │
└──────────────────────────┬───────────────────────────┘
                           │
                 ┌─────────┴─────────┐
                 │                   │
             [UNSAT = 0]          [SAT = 1]
                 │                   │
                 ▼                   ▼
     ┌───────────────────────┐ ┌──────────────────────────────────────────────────┐
     │ Instant Rejection     │ │ Layer 2: LLM & Embedding Semantic Verifier       │
     │ S_local = 0           │ │ Checks: Precedent ratio alignment, citation      │
     │ Forces Retry Loop     │ │ validity, grounding. Returns S_llm ∈ [0, 1].     │
     └───────────────────────┘ └────────────────────────┬─────────────────────────┘
                                                        │
                                                        ▼
                                       ┌──────────────────────────────────┐
                                       │ Composite Local Score:           │
                                       │ S_local = S_smt * [0.3*S_rule +  │
                                       │                    0.7*S_llm]    │
                                       └──────────────────────────────────┘

```

#### What Happens on Consecutive Failures (3-Retry Fallback)

If an agent fails `THEMIS-LOCAL` three times in a single turn:

1. The system halts the retry loop to avoid pipeline deadlocks.
2. It publishes the candidate draft that achieved the highest composite score among the three failed attempts.
3. The entry is marked in the transcript with a permanent flag: `VERIFICATION_FAILED_FLAG = True`, along with the specific audit error code (e.g., `ERR_LIMITATION_EXPIRED`).
4. This flag serves as context for the opposing agent in the next turn (allowing it to exploit the procedural defect) and imposes a heavy penalty in `THEMIS-GLOBAL` scoring.

### 5.2 THEMIS-GLOBAL Deep Dive

Once Turn 10 concludes, `THEMIS-GLOBAL` aggregates the full transcript:

* Evaluates cross-turn consistency (detecting whether an agent contradicted in Turn 6 an assertion it made in Turn 2).
* Calculates the **Rebuttal Depth Score** by evaluating semantic similarity between an opponent's argument and the agent's counter-rebuttal (penalizing evasive answers).
* Computes the multi-dimensional performance score vector $S_{\text{global}}$.

---

## 6. The Three-Persona Judicial Bench

Real judicial systems are not uniform reasoning engines; different judges operate under distinct jurisprudence philosophies. LexArena deploys a three-judge bench to evaluate each trial:

```
                      ┌─────────────────────────────────────────┐
                      │      THREE-PERSONA JUDICIAL BENCH       │
                      └────────────────────┬────────────────────┘
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         ▼                                 ▼                                 ▼
┌──────────────────┐             ┌──────────────────┐             ┌──────────────────┐
│  THE TEXTUALIST  │             │  THE PRAGMATIST  │             │ THE PROCEDURALIST│
├──────────────────┤             ├──────────────────┤             ├──────────────────┤
│ Focus:           │             │ Focus:           │             │ Focus:           │
│ Strict statutory │             │ Economic impact, │             │ Limitation bars, │
│ compliance and   │             │ commercial       │             │ notice service,  │
│ plain-meaning    │             │ viability, going-│             │ filing defects,  │
│ construction.    │             │ concern rescue.  │             │ evidentiary rule.│
└──────────────────┘             └──────────────────┘             └──────────────────┘
         │                                 │                                 │
         └─────────────────────────────────┼─────────────────────────────────┘
                                           │
                                           ▼
                      ┌─────────────────────────────────────────┐
                      │      VERDICT CONSISTENCY VALIDATOR      │
                      │ 1. Aggregates multi-criteria matrix     │
                      │ 2. Synthesizes explainable verdict      │
                      │ 3. Flags Human-AI reasoning divergence  │
                      └─────────────────────────────────────────┘

```

1. **The Textualist Persona:** Adheres strictly to the literal text of the statute. If the plain meaning of Section 7 indicates that a debt and default exist, the Textualist admits the petition, disregarding hardship arguments.
2. **The Commercial Pragmatist Persona:** Prioritizes economic viability, corporate resuscitation, and market impact. Evaluates whether initiating insolvency will preserve enterprise value or destroy jobs and operational capacity.
3. **The Proceduralist Persona:** Scrutinizes procedural timelines, limitation periods under Article 137, delivery proof of Section 8 demand notices, and stamp-duty compliance.

### Multi-Criteria Aggregation & The Verdict Consistency Validator

Each judge evaluates the transcript independently across four dimensions:

* Statutory Correctness (35%)
* Logical Consistency (25%)
* Adversarial Rebuttal Depth (20%)
* Precedent Grounding (20%)

The **Verdict Consistency Validator** aggregates the individual scorecards, resolves ideological conflicts between textualist stricture and commercial pragmatism, and synthesizes a structured, human-readable judicial opinion. It verifies that the declared winner corresponds directly to the higher aggregated score and confirms that the reasoning contains no internal legal contradictions.

---

## 7. In-Context Continuous Learning: The Reflection Engine

The foundational LLMs operate over frozen APIs with zero weight fine-tuning. LexArena achieves continuous learning across its 500-case curriculum via an **Agent Reflection Engine** that updates vector-indexed episodic memory:

```
                              POST-TRIAL LEARNING LOOP
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ Aggregator: Gathers Transcript, SMT Audit     │
                 │ Logs, Failed Retries, and Judicial Scorecard  │
                 └───────────────────────┬───────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ Reflection LLM (GPT-4o-mini in JSON Mode)     │
                 │ Generates concise tactical anti-pattern rule  │
                 │ Assigns Severity Rating (1 to 5)              │
                 └───────────────────────┬───────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ Dense Vector Encoding (BGE-small-en-v1.5)     │
                 │ Candidate Vector: v_lesson ∈ R^384            │
                 └───────────────────────┬───────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ Qdrant Semantic Deduplication Gate            │
                 │ Nearest vector search: Sim(v_lesson, v_match) │
                 └───────────────────────┬───────────────────────┘
                                         │
                    ┌────────────────────┴────────────────────┐
                    │                                         │
        [Sim >= 0.90: MATCH]                     [Sim < 0.90: NOVEL]
                    │                                         │
                    ▼                                         ▼
    ┌───────────────────────────────┐         ┌───────────────────────────────┐
    │ Increment Frequency Count += 1│         │ Insert New Memory Point       │
    │ Update Max Severity           │         │ Initial Frequency = 1         │
    │ Recalculate W = Sev * Freq    │         │ Initial W = Severity * 1      │
    └───────────────────────────────┘         └───────────────────────────────┘
                    │                                         │
                    └────────────────────┬────────────────────┘
                                         │
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │ System Prompt Dynamic Pinning:                │
                 │ Top-K highest-weighted anti-patterns are      │
                 │ automatically injected into next trial prompt │
                 └───────────────────────────────────────────────┘

```

### Solving Stateless Forgetting Without Token Bloat

If an agent repeatedly argues that contractual frustration under Section 56 of the Indian Contract Act excuses a financial debt default under IBC Section 7, the system updates its memory deterministically:

1. The Reflection LLM extracts the tactical lesson: *"Never cite Section 56 contractual frustration for corporate term loans under IBC Section 7."*
2. It sets `Severity = 5` (instant statutory failure).
3. The lesson vector is checked against Qdrant. Because similar lessons already exist, the similarity exceeds $\tau_{\text{dedup}} = 0.90$.
4. Qdrant **increments the frequency count** of the existing vector and updates the **Retention Weight ($W = \text{Severity} \times \text{Frequency}$)** without storing redundant text strings.
5. In subsequent trials, the prompt builder ranks memories by $W$ and pins this rule at the very top of the system prompt under `BANNED ANTI-PATTERNS`. The agent is structurally barred from repeating the mistake.

---

## 8. Master Mathematical Formulation

### 8.1 SMT Hard Gate Satisfiability Evaluation

Let $A$ denote an argument draft generated by agent $i$, and let $\mathbf{\Phi}_{\text{L4L}}(A)$ be the set of first-order symbolic logic predicates derived from governing statutes and case facts. The SMT satisfiability indicator $S_{\text{smt}}(A)$ evaluates as:

$$S_{\text{smt}}(A) = \begin{cases} 1 & \text{if } \mathbf{\Phi}_{\text{L4L}}(A) \models \text{SAT} \\ 0 & \text{if } \mathbf{\Phi}_{\text{L4L}}(A) \models \text{UNSAT} \end{cases}$$

Where $\text{SAT}$ denotes that the quantitative and temporal claims contain zero mathematical or statutory contradictions, and $\text{UNSAT}$ denotes a direct statutory violation.

---

### 8.2 Composite Local Verification Score (`THEMIS-LOCAL`)

The overall local score $S_{\text{local}}(A) \in [0, 1]$ combines symbolic satisfiability with rule matching and semantic precedent grounding:

$$S_{\text{local}}(A) = S_{\text{smt}}(A) \cdot \left[ w_{\text{rule}} \cdot S_{\text{rule}}(A) + w_{\text{llm}} \cdot S_{\text{llm}}(A) \right]$$

Where:

* $S_{\text{rule}}(A) \in \{0, 1\}$ represents the boolean diagnostic checklist match score.
* $S_{\text{llm}}(A) \in [0, 1]$ represents the semantic grounding score evaluated against retrieved Qdrant precedent vectors.
* $w_{\text{rule}} = 0.30$ and $w_{\text{llm}} = 0.70$ are the normalized weight coefficients.
* *Note:* If $S_{\text{smt}}(A) = 0$, the composite score collapses to zero ($S_{\text{local}} = 0$) regardless of the LLM grounding score.

The draft publication condition is governed by the acceptance threshold $\theta = 0.70$:

$$\text{Action}(A) = \begin{cases} \text{PUBLISH\_TO\_PUBLIC\_DB} & \text{if } S_{\text{local}}(A) \ge 0.70 \\ \text{REJECT\_AND\_TRIGGER\_RETRY} & \text{if } S_{\text{local}}(A) < 0.70 \end{cases}$$

---

### 8.3 Argument Quality Smoothing Across Multi-Turn Debates

To mitigate turn-level variance and prevent an isolated anomaly from skewing debate trajectory evaluation, quality is smoothed across turns $t \in \{1, 2, \dots, N\}$ via an exponential moving average:

$$Q_t = (1 - T) \cdot Q_{t-1} + T \cdot \text{Quality}(\text{Turn}_t)$$

Where:

* $T = 0.5$ is the memory smoothing parameter.
* $\text{Quality}(\text{Turn}_t)$ is the composite quality metric of the argument generated at turn $t$.
* $Q_N$ represents the final smoothed quality value passed to `THEMIS-GLOBAL`.

---

### 8.4 Global Multi-Dimensional Evaluation (`THEMIS-GLOBAL`)

At trial conclusion, `THEMIS-GLOBAL` computes an aggregate performance vector $S_{\text{global}}(i)$ for each agent $i \in \{\text{LEX-P}, \text{LEX-D}\}$:

$$S_{\text{global}}(i) = \alpha \cdot \text{Accuracy}(i) + \beta \cdot \text{Consistency}(i) + \gamma \cdot \text{AdversarialDepth}(i) + \delta \cdot \text{Grounding}(i)$$

Subject to the normalization constraint:

$$\alpha + \beta + \gamma + \delta = 1.0$$

Where:

* $\alpha = 0.35$ (Statutory and Legal Accuracy)
* $\beta = 0.25$ (Internal Logical Consistency across 10 turns)
* $\gamma = 0.20$ (Adversarial Directness and Rebuttal Quality)
* $\delta = 0.20$ (Precedent Grounding and Factual Fidelity)

---

### 8.5 Continuous Learning Reward Function (`AdvEvol`)

Following debate adjudication, the scalar training reward signal assigned to agent $i$ is calculated as:

$$\text{Reward}(i) = S_{\text{global}}(i) + w_{\text{fair}} \cdot S_{\text{fairness}} - \sum_{r=1}^{N} \text{Penalty}_{\text{local}}(r, i)$$

Where:

* $S_{\text{fairness}} \in [0, 1]$ represents procedural compliance.
* $w_{\text{fair}} = 0.10$ is the procedural fairness weight.
* $\text{Penalty}_{\text{local}}(r, i)$ is the cumulative penalty incurred by agent $i$ across debate rounds $r$ from failed `THEMIS-LOCAL` attempts.

---

### 8.6 Knowledge Base Retention Weight ($W$) & Prompt Selection

For any memory entry $j \in \mathcal{R} \cup \mathcal{E}$, its retention weight $W_j \in \mathbb{R}^+$ is determined by:

$$W_j = \text{SeverityRating}_j \times \text{FrequencyCount}_j$$

Where:

* $\text{SeverityRating}_j \in \{1, 2, 3, 4, 5\}$
* $\text{FrequencyCount}_j \in \mathbb{Z}^+$

The subset of anti-patterns pinned into the agent's system prompt is determined by solving:

$$\text{PinnedSet} = \operatorname*{arg\,max}_{S \subseteq (\mathcal{R} \cup \mathcal{E}), \, \vert{}S\vert{} = K} \sum_{j \in S} W_j \quad \text{subject to} \quad \sum_{j \in S} \text{Tokens}(j) \le 250$$

---

### 8.7 Vector Similarity & Retrieval Dynamics (Qdrant)

For dense embedding vectors $\mathbf{u}, \mathbf{v} \in \mathbb{R}^{384}$ generated via `BAAI/bge-small-en-v1.5`, cosine similarity is defined as:

$$\text{Sim}(\mathbf{u}, \mathbf{v}) = \frac{\mathbf{u} \cdot \mathbf{v}}{\Vert{}\mathbf{u}\Vert{}_2 \Vert{}\mathbf{v}\Vert{}_2} = \frac{\sum_{k=1}^{384} u_k v_k}{\sqrt{\sum_{k=1}^{384} u_k^2} \sqrt{\sum_{k=1}^{384} v_k^2}}$$

#### Dynamic Case Library ($C$) RAG Retrieval:

Given an unseen case fact vector $\mathbf{v}_{\text{query}}$, historical precedent cases are retrieved according to:

$$\mathcal{C}_{\text{retrieved}} = \left\{ c \in \mathcal{C} \;\middle\vert{}\; \text{Sim}(\mathbf{v}_{\text{query}}, \mathbf{v}_c) \ge \tau_C \right\}, \quad \tau_C = 0.75, \quad \text{limit} = 2$$

#### Post-Trial Deduplication Gate:

When the Reflection LLM outputs a candidate lesson vector $\mathbf{v}_{\text{lesson}}$, Qdrant identifies the nearest existing memory vector $\mathbf{v}_{j^*}$:

$$j^* = \operatorname*{arg\,max}_{j \in \text{KB}} \text{Sim}(\mathbf{v}_{\text{lesson}}, \mathbf{v}_j)$$

The database state transition operates under a strict threshold $\tau_{\text{dedup}} = 0.90$:

$$\text{StateUpdate}(\mathbf{v}_{\text{lesson}}) = \begin{cases}  \begin{aligned} &\text{FrequencyCount}_{j^*} \leftarrow \text{FrequencyCount}_{j^*} + 1 \\ &\text{SeverityRating}_{j^*} \leftarrow \max\left(\text{SeverityRating}_{j^*}, \sigma_{\text{new}}\right) \\ &W_{j^*} \leftarrow \text{SeverityRating}_{j^*} \times \text{FrequencyCount}_{j^*} \end{aligned} & \text{if } \text{Sim}(\mathbf{v}_{\text{lesson}}, \mathbf{v}_{j^*}) \ge 0.90 \\ \\ \begin{aligned} &\text{Insert New Vector Point } j_{\text{new}} \text{ with:} \\ &\text{FrequencyCount}_{j_{\text{new}}} = 1, \quad \text{SeverityRating}_{j_{\text{new}}} = \sigma_{\text{new}}, \quad W_{j_{\text{new}}} = \sigma_{\text{new}} \end{aligned} & \text{if } \text{Sim}(\mathbf{v}_{\text{lesson}}, \mathbf{v}_{j^*}) < 0.90 \end{cases}$$

---

### 8.8 Formal First-Order Logic Predicates for Insolvency Law

#### IBC Section 7: Financial Creditor CIRP Initiation

$$\mathbf{\Phi}_{\text{IBC\_Sec7}} \iff \left( \text{ClaimAmount} \ge 10^7 \right) \land \left( \Delta t_{\text{default}} \le 1095 \lor \text{HasSection18Ack} \right) \land \neg \text{FraudulentInitiation}$$

Where:

* $\text{ClaimAmount} \ge 10,000,000$ enforces the statutory ₹1 Crore default threshold.
* $\Delta t_{\text{default}} \le 1095$ checks the 3-year limitation window under Article 137 of the Limitation Act, 1963.
* $\text{HasSection18Ack} \in \{\text{True}, \text{False}\}$ checks for balance sheet acknowledgment resetting the limitation clock.
* $\neg \text{FraudulentInitiation}$ enforces Section 65 penalty avoidance.

#### IBC Section 9: Operational Creditor CIRP Initiation

$$\mathbf{\Phi}_{\text{IBC\_Sec9}} \iff \left( \text{ClaimAmount} \ge 10^7 \right) \land \left( \Delta t_{\text{notice}} \ge 10 \right) \land \neg \left( t_{\text{dispute}} < t_{\text{demand\_notice}} \right)$$

Where:

* $\Delta t_{\text{notice}} \ge 10$ validates that at least 10 clear days have elapsed following delivery of the statutory Form 3/4 demand notice under Section 8.
* $t_{\text{dispute}} < t_{\text{demand\_notice}}$ models the Supreme Court's *Mobilox Innovations* doctrine: if documentary evidence establishes a pre-existing dispute prior to demand notice dispatch, the petition is rendered unsatisfiable.

---

## 9. Complete Technology Stack

| Layer | Component | Selected Technology | Technical Role |
| --- | --- | --- | --- |
| **Vector DB** | Vector Database Engine | **Qdrant** | High-performance vector storage with cosine metric, dynamic payload filtering, and thresholded search ($\tau=0.75, 0.90$). |
| **Document Store** | Structured Data Store | **MongoDB (`pymongo`)** | Houses `laws_db` (Bare Acts/L4L), `public_db` (transcripts), and `bench_db` (scorecards). |
| **Local Embedder** | Dense Vector Representation | **`BAAI/bge-small-en-v1.5`** | Local 384-dimensional dense embedding model running via `sentence-transformers` for ₹0 API overhead. |
| **Symbolic Logic** | SMT Constraint Solver | **Microsoft Z3 (`z3-solver`)** | Evaluates mathematical, temporal, and statutory logic satisfiability ($\text{SAT} / \text{UNSAT}$) deterministically. |
| **Foundation LLMs** | Reasoning & Generation | **Google Gemini & OpenAI GPT-4o-mini** | **Gemini:** Live debate argumentation and Judicial Bench evaluations.<br>

<br>**GPT-4o-mini:** Offline PDF parsing and structured reflection updating. |
| **Agent Orchestration** | State Machine & Execution | **LangGraph / Python State Machine** | Manages turn-taking, retry loops, private memory state transitions, and context assembly. |
| **Validation** | Data Schema Validation | **Pydantic (`pydantic`)** | Enforces strict schema conformity for all JSON inputs, LLM outputs, and diagnostic checklists. |
| **API Backend** | REST Microservices | **FastAPI + Uvicorn** | Exposes endpoints for precedent searching, bulk data ingestion, and simulation triggering. |
| **User Interface** | Human Evaluation Dashboard | **Streamlit / React** | Web dashboard allowing legal professionals to review transcripts, record verdicts, and inspect divergence metrics. |
| **Document Utility** | Raw Document Ingestion | **`pdfminer.six`** | Extracts text and structure from raw tribunal PDF orders. |

---

## 10. End-to-End System Execution Lifecycle

```
===================================================================================================
1. OFFLINE PREPARATION (Phase 0)
   - Ingest 500 NCLT/NCLAT Tribunal PDF judgments via pdfminer.six.
   - Parse judgments with GPT-4o-mini into unspoiled_case_data and isolated ground_truth.
   - Vectorize unspoiled factual backgrounds into Qdrant nclt_precedents using bge-small-en-v1.5.
   - Ingest Bare Acts and L4L diagnostic checklists into MongoDB laws_db.
===================================================================================================
                                              │
                                              ▼
===================================================================================================
2. TRIAL INITIALIZATION (t = 0)
   - Clerk State Machine loads Case N.
   - Clerk embeds case facts; queries Qdrant case_library with score_threshold >= 0.75 (Top 2 max).
   - Python queries MongoDB for Top 5 highest-weighted anti-patterns (W = Severity * Frequency).
   - Injects dynamic Knowledge Base payload (~500–650 tokens) into LEX-P and LEX-D system prompts.
===================================================================================================
                                              │
                                              ▼
===================================================================================================
3. ADVERSARIAL DEBATE RUNTIME (Turns 1 to 10)
   - LEX-P generates Turn 1 argument draft.
   - THEMIS-LOCAL evaluates draft:
       * Z3 evaluates L4L constraints (ClaimAmount >= 1Cr, Limitation <= 1095 days).
       * bge-small-en-v1.5 checks cited precedent ratio against Qdrant payloads.
       * Composite Score calculated: S_local = S_smt * [0.3*S_rule + 0.7*S_llm].
   - If S_local >= 0.70: Draft published to MongoDB public_db transcript.
   - If S_local < 0.70: Rejection feedback injected into draft prompt (up to 3 retries).
   - LEX-D reads published Turn 1, generates Turn 2 defense, passes through THEMIS-LOCAL.
   - Debate continues alternately through Turn 10 (Closing Arguments).
===================================================================================================
                                              │
                                              ▼
===================================================================================================
4. POST-TRIAL ADJUDICATION & BENCH SYNTHESIS (Phase 2 & Phase 3)
   - THEMIS-GLOBAL aggregates 10-turn transcript and logs consistency and rebuttal depth metrics.
   - Three-Persona Judicial Bench evaluates transcript:
       * Textualist evaluates strict statutory compliance.
       * Pragmatist evaluates commercial viability and rescue intent.
       * Proceduralist evaluates limitation, service, and procedural defects.
   - Verdict Consistency Validator aggregates scores and generates an explainable verdict.
   - Unlocks isolated ground_truth; logs Human-AI reasoning divergence metrics.
===================================================================================================
                                              │
                                              ▼
===================================================================================================
5. AGENT REFLECTION & EPIGENETIC MEMORY UPDATE (Phase 4)
   - Post-Trial Aggregator bundles transcript, THEMIS audit logs, and judicial feedback.
   - Reflection LLM (GPT-4o-mini JSON mode) extracts discrete tactical anti-pattern rule + severity.
   - bge-small-en-v1.5 encodes lesson vector v_lesson into 384 dimensions.
   - Qdrant queries agent's private memory collection with score_threshold = 0.90:
       * If Sim >= 0.90: Increment frequency count of existing vector; update max severity; update W.
       * If Sim < 0.90: Insert new vector point with initial frequency = 1.
   - High-weight lessons are prioritized for system prompt pinning in Case N + 1.
===================================================================================================

```

---

## 11. Concrete Case Walkthrough: *Sandeep Mittal v. ASREC (India) Ltd.*

To see the pipeline in action, consider how the system processes **Company Appeal (AT) (Insolvency) No. 37 of 2024** (*Sandeep Mittal v. ASREC (India) Ltd.*):

```
                                  CASE FACT MATRIX
                                  
  Original Loan: Term loans granted to GPPL in 1980s by GSFC, GIIC, BoB, Dena Bank.
  Default & Sale: GPPL defaulted. GSFC auctioned assets under Sec 29 SFC Act.
  Agreement (27.11.1990): Rama Finance (now SIL) agrees to buy assets for ₹3.88 Cr.
                          ₹50 Lakh down payment; ₹3.38 Cr in 20 quarterly installments.
  Debt Assignment: Bank of Baroda assigns its share to ASREC (India) Ltd in 2011.
  Default Notice: ASREC claims ₹92.35 Crore default, files Section 7 petition in 2022.

```

### 1. What the Clerk Prepares (`unspoiled_case_data`)

* **Issues Framed:**
1. *Whether deferred purchase installments under an auction sale constitute a "financial debt" under Section 5(8) of the IBC?*

2. *Whether handing over physical assets without disbursing loan funds satisfies the requirement of "disbursement against the time value of money"?*

3. *Whether subsequent corporate letters or OTS proposals can convert an Agreement of Sale into a financial debt?*



* **Ground Truth (Hidden):** The appellate bench set aside admission, ruling that unpaid sale consideration is not a financial debt under Section 5(8). This is encrypted until Phase 3 ends.



### 2. Turn 1 (`LEX-P` / ASREC)

* **Argument:** `LEX-P` asserts that the 1990 agreement allowed the buyer to pay over five years with 16% interest, which has the "commercial effect of a borrowing" under Section 5(8)(f).


* **THEMIS-LOCAL Check:**
* Claim amount (₹92.35 Cr) exceeds ₹1 Cr ($S_{\text{smt}} = 1$).
* The citation of Section 5(8)(f) exists in the database.
* Score: $S_{\text{local}} = 0.84 \ge 0.70 \rightarrow$ **PASS**.



### 3. Turn 2 (`LEX-D` / Corporate Debtor)

* **Argument:** `LEX-D` argues that the original borrower was GPPL, not SIL. SIL was merely an auction purchaser under Section 29 of the SFC Act. No funds were disbursed to SIL's bank account, citing the Supreme Court ruling in *Pioneer Urban* that "disbursement of money" is an essential precondition.


* **THEMIS-LOCAL Check:**
* Checks *Pioneer Urban* payload in Qdrant: confirmed that the ratio requires money to pass from creditor to debtor.

   
* Score: $S_{\text{local}} = 0.91 \ge 0.70 \rightarrow$ **PASS**.



### 4. Post-Trial Adjudication & Memory Update

* **Bench Findings:** The Textualist notes the strict statutory phrasing ("disbursed against... time value of money"). The Proceduralist highlights the absence of a loan agreement. The bench rules for `LEX-D`.


* **Reflection Engine Action:** `LEX-P` logs an anti-pattern: *"Do not characterize unpaid asset sale consideration under SFC Act auctions as financial debt under Section 5(8)(f)."*
* **Qdrant Storage:** The lesson is embedded. If novel, it is added with `Severity = 5`. In future cases involving asset purchases, `LEX-P` avoids filing under Section 7 and explores alternative legal pathways instead.
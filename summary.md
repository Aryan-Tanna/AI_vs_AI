### LexArena: Project Master Summary

**LexArena** is a verified, multi-agent adversarial courtroom simulation framework designed for Indian corporate insolvency proceedings before the National Company Law Tribunal (NCLT) and Appellate Tribunal (NCLAT) under the Insolvency and Bankruptcy Code, 2016 (IBC). It shifts legal AI from static, single-turn question-answering to a multi-turn, verifiable litigation game between two advocate agents—**LEX-P** (Petitioner) and **LEX-D** (Respondent)—adjudicated by an impartial **Three-Persona Judicial Bench** and continuously verified by the **THEMIS** framework.

---

### 1. Core Architecture & Storage Topology

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              DATA ARCHITECTURE                             │
├─────────────────────────────────────┬──────────────────────────────────────┤
│         MONGODB CLUSTER             │         QDRANT VECTOR ENGINE         │
│     (Deterministic Document)        │        (Dense Semantic Vectors)      │
├─────────────────────────────────────┼──────────────────────────────────────┤
│ • laws_db: Bare acts & L4L          │ • nclt_precedents: 500 NCLT/NCLAT    │
│   checklists (exact ID match)[cite: 50]│   case vectors (BGE-small-en-v1.5)   │
│ • public_db: Transcripts, case      │ • kb_e_memory_p: LEX-P private       │
│   JSONs, audit logs[cite: 50]         │   experience vectors (τ_dedup=0.90)  │
│ • bench_db: Judicial scorecards     │ • kb_e_memory_d: LEX-D private       │
│   and divergence reports[cite: 50]    │   experience vectors (τ_dedup=0.90)  │
└─────────────────────────────────────┴──────────────────────────────────────┘

```

* **The Clerk State Machine & Unspoiled Case Protocol:** Ingests raw tribunal judgment PDFs via `pdfminer.six` and isolates them into two partitions:
* `unspoiled_case_data`: Core factual background, monetary default quantum, default dates, neutral framed legal issues, and initial party contentions (fed to `LEX-P` and `LEX-D` at $t=0$).


* `ground_truth`: Final ruling, bench ratio, and judicial analysis (isolated and encrypted; unlocked only post-trial for evaluation).




* **Documentary Evidence & Fact Presumption:** Sourced via structured exhibit and notice markers (`Annexure`, `Form C`, `Form E`). For abstract training runs, facts in the claim quantum are presumed admitted, preventing procedural avoidance loops and forcing substantive statutory debate.



---

### 2. Real-Time Symbolic & Semantic Verification (`THEMIS`)

```
                          ARGUMENT DRAFT GENERATION
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │         THEMIS-LOCAL          │
                     ├───────────────────────────────┤
                     │ Layer 1: L4L + Z3 SMT Solver  │
                     │          (Checks SAT/UNSAT)   │
                     │ Layer 2: Vector Cross-Checker │
                     │          (Semantic Grounding) │
                     └───────────────┬───────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
          [S_local >= 0.70: PASS]           [S_local < 0.70: FAIL]
                    │                                 │
                    ▼                                 ▼
         Published to Public DB              Max 3 Retries
         Transcript for Turn t+1             (Fallback: Flagged Publish
                                              + 0.15 Penalty per retry)

```

* **Layer 1 (L4L & Z3 SMT Solver):** Translates statutory checklists into formal logic ($\mathbf{\Phi}_{\text{L4L}}$) to evaluate arithmetic debt thresholds ($\ge ₹1\text{ Cr}$) and temporal limitation windows ($\le 1,095\text{ days}$ unless saved by Section 18 acknowledgment) deterministically, returning $\text{SAT}$ ($1$) or $\text{UNSAT}$ ($0$).
* **Layer 2 (Semantic Grounding):** Extracts legal citations and verifies their existence against the Citation DB and Qdrant precedent store, checking that asserted ratios align with the stored vector payloads.
* **Composite Local Formula:**

$$S_{\text{local}}(A) = S_{\text{smt}}(A) \cdot \left[ 0.30 \cdot S_{\text{rule}}(A) + 0.70 \cdot S_{\text{llm}}(A) \right]$$



*(An $\text{UNSAT}$ result instantly zeros the entire score).*

---

### 3. Multi-Persona Judicial Bench & Evaluation

* **The Three Personas:**
1. *The Textualist:* Enforces strict black-letter statutory compliance and plain-meaning interpretation.


2. *The Commercial Pragmatist:* Evaluates enterprise rescue, going-concern preservation, and commercial feasibility.


3. *The Proceduralist:* Audits procedural timelines, limitation bars, notice defects, and evidentiary burdens.




* **Verdict Consistency Validator:** Aggregates individual scorecards via a multi-criteria matrix ($\text{Accuracy: } 0.35$, $\text{Consistency: } 0.25$, $\text{Adversarial Depth: } 0.20$, $\text{Grounding: } 0.20$), synthesizes an explainable judgment, and validates that the reasoning aligns with the winning score.


* **Two-Track Evaluation:**
* *Track A (End-to-End Alignment):* Compares the final simulated outcome against historical court ground truth.


* *Track B (Judicial Divergence):* Feeds identical factual pleadings to AI judges and human legal experts to isolate and measure formalist vs. equitable reasoning divergence.





---

### 4. Continuous Learning Engine (Reflection Without Fine-Tuning)

```
                            POST-TRIAL REFLECTION
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │ Reflection LLM (GPT-4o-mini)  │
                      │ Extracts tactical lesson +    │
                      │ assigns Severity Rating (1-5) │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │    BGE Vectorization (384d)   │
                      │    Cosine Check against VDB   │
                      └───────────────┬───────────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     │                                 │
           [Sim >= 0.90: MATCH]              [Sim < 0.90: NOVEL]
                     │                                 │
                     ▼                                 ▼
          Increment Frequency Count         Insert New Vector Point
          Update Max Severity               (Freq = 1, W = Severity)
          Recalculate W = Sev * Freq

```

* **Retention Weighting ($W$):** Memory priority is governed by $W_j = \text{SeverityRating}_j \times \text{FrequencyCount}_j$.
* **Dynamic System Prompt Pinning:** Before every trial, the Python Prompt Builder selects the top $K$ anti-patterns maximizing $\sum W_j$ within a 250-token budget and injects them under `BANNED ANTI-PATTERNS`, preventing agents from repeating past procedural and statutory mistakes.
* **Semantic Deduplication ($\tau_{\text{dedup}} = 0.90$):** If a generated lesson vector has a cosine similarity $\ge 0.90$ with an existing vector, Qdrant increments the existing record's frequency and updates its severity rather than storing duplicate text strings.
* **Precedent Retrieval ($\tau_C = 0.75$):** Historical case precedents from Qdrant are only injected into trial prompts if the factual cosine similarity meets or exceeds $0.75$ (capped at the top 2 cases).

---

### 5. Verified Case Implementations

1. **Company Appeal (AT) (Insolvency) No. 37 of 2024 (*Sandeep Mittal v. ASREC India Ltd.*):**

* *Core Issue:* Whether deferred purchase installments under an auction sale (Section 29 SFC Act) constitute a financial debt under IBC Section 5(8).


* *Historical Holding:* Unpaid purchase consideration is not a financial debt because no money was disbursed to the debtor; Section 7 petition dismissed.




2. **Company Appeal (AT) (Insolvency) No. 1572 of 2024 (*Era Labourer Union of SIDCUL v. Apex Buildsys Ltd.*):**

* *Core Issue:* Whether NCLT has residuary jurisdiction under Section 60(5)(c) to decide the legality of a pre-CIRP factory closure and transfer notice under state labor laws.


* *Historical Holding:* NCLT lacks subject-matter jurisdiction over independent labor disputes outside the insolvency process; post-closure wage claims rightly rejected.
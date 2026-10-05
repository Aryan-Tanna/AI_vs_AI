LexArena: Issues & Fixes Register
Oct 5, 2026 · @Someone
How to use this register
This register lists every issue found so far in the LexArena blueprint, the two DB schemas and the precedent sample, each with its fix. The Law DB and Precedent DB schemas stay frozen: every fix lives in the public case object, a side collection, or code.
Every rule, schema and check in this register is general and applies to any IBC case in your dataset. Case names and figures that appear (Sandeep Mittal, Vibrant Buildwell, the EPFO attachment appeal) are illustrations taken from the samples you shared, not assumptions about your data.
Fix the P0 items before running any of the 500 cases. P0 items either break the simulation or corrupt the results; P1 items weaken them; P2 items are refinement.
ID
Issue
Priority
Where the fix lives
D1
Z3 checks whether the case is winnable, not whether the argument is honest
P0
THEMIS-LOCAL code
D2
Contested interpretations hardcoded as Z3 constraints
P0
THEMIS-LOCAL code
D3
Threshold and limitation predicates are legally wrong
P0
temporal_overlay + Z3
B1
Same real case may exist in both the public and precedent DBs
P1
Clerk exclusion filter
A1
Presumption mode biases outcomes toward creditors
P0
Public case object
A2
Exhibits named without contents invite hallucination
P0
Public case object + THEMIS
E1
Advocacy-score verdict is open to judge bias
P0
Judicial bench
F1
Lessons ban the client's own position
P1
Reflection engine
D4
Embeddings cannot detect inverted holdings
P1
THEMIS layer 2
B3
statutes_cited IDs may not match Law DB IDs
P1
ID normalizer
B4
Supreme Court authorities absent from the DB
P1
Citation tiers
A3
Framed issues lead toward the answer
P1
Clerk rewrite pass
A4
Party names visible, enabling recall of the real case
P1
Anonymizer
E2
Pragmatist persona conflicts with current Section 7 law
P1
Bench prompts
F2
Memory weights only grow, never decay
P1
Reflection engine
B5
512-token limit truncates material_facts
P2
Embedding builder
B6
Similarity thresholds 0.75 / 0.90 uncalibrated
P2
Calibration script
G3
Inconsistent numbers and leftover artifacts in the blueprint
P2
Blueprint text
D8
Too many arguments could be rejected; no tiered outcome policy
P0
THEMIS-LOCAL policy
E6
Structural advantages between agents (last word, memory size, prompts)
P0
Session orchestration
H1
Public DB has no fixed schema
P0
Public DB
A. Case construction and evidence
Evidence stays in the simulation as a closed record built from what each judgment says about it. Nothing is invented and nothing beyond the judgment's description is usable.
A1. Presumption mode biases outcomes (P0)
Problem. Substantive Law Presumption Mode deems every fact in the background and claim quantum admitted and proved. Under Section 7 this makes admission nearly automatic, so the bench leans toward the creditor. It also erases Section 9 cases, where the pre-existing dispute is the whole fight.
Fix. Narrow the presumption to authenticity and due execution of exhibits only. Contested facts stay contested, and the legal character of a document stays arguable. The prompt line becomes: "Exhibits are presumed genuine and duly executed; do not object that a document was not produced. Facts marked CONTESTED remain disputed."
A2. Exhibits listed by name only (P0)
Problem. evidence_attached holds only titles such as "OTS Proposal Letter dated 15.03.2016". Agents fill the gap by inventing contents.
Fix. Replace the list with a three-tier record inside the unspoiled case object (public DB, not the frozen DBs):
"record": {
  "stipulated_facts": [
    {"fact_id": "F1", "text": "Agreement executed on 27.11.1990 for purchase of assets for Rs 3.88 Cr", "source_para": "3"}
  ],
  "contested_facts": [
    {"fact_id": "C1", "question": "Nature of the balance consideration",
     "petitioner_version": "Converted into a loan carrying interest",
     "respondent_version": "Unpaid sale price under an Agreement to Sell"}
  ],
  "exhibits": [
    {"exhibit_id": "EX-5", "title": "OTS Proposal Letter dated 15.03.2016", "filed_by": "PETITIONER",
     "known_contents": ["Corporate debtor proposed a one-time settlement of the outstanding balance"],
     "contents_beyond_known": "UNKNOWN", "authenticity": "PRESUMED"}
  ]
}
The clerk fills known_contents from the judgment's own description, the same way your precedent material_facts already has a FACTUAL EVIDENCE block. THEMIS enforces three rules:
1. Every factual sentence in an argument cites a fact_id or exhibit_id.
2. Any sentence describing an exhibit's contents must be entailed by its known_contents (LLM entailment check).
3. Violations get ERR_EXHIBIT_CONTENT_FABRICATED or ERR_FACT_NOT_IN_RECORD. Arguments about what the record does not show stay allowed.
A3. Framed issues lead toward the answer (P1)
Problem. Issues such as "Whether the physical delivery of property satisfies the requirement of disbursement of money" signal the holding. Labels like dispute_category: FINANCIAL_DEBT_VS_SALE_CONSIDERATION_DEFAULT do the same.
Fix. Add a second clerk pass that rewrites each issue as a neutral question ("Whether the balance consideration constitutes financial debt under Section 5(8)") and flags evaluative words: erred, merely, satisfies, failed. Drop dispute_category from what agents see, or replace it with the statute IDs alone.
A4. Real names enable recall of the real case (P1)
Problem. case_id: CASE_NCLAT_2024_SANDEEP_MITTAL_VS_ASREC and party names are visible. These judgments are public, so the model may simply remember the outcome.
Fix. Replace party and company names with stable pseudonyms (Creditor-A, Debtor-B), use opaque case IDs, and remove IA and appeal numbers from the agent view. Then run a probe: give a model the sanitized facts and ask it to name the case. Any case it names correctly goes to a contaminated subset, reported separately.
A5. Clerk truncates long judgments (P1)
Problem. clerk_parser.py sends pdf_text[:14000]. NCLAT judgments often run past 30 pages, so facts or the operative order get cut.
Fix. Split the text by detected headings (facts, submissions, analysis, order) and parse each part separately, then merge. Log any case where no operative order was found.
A6. Appeals have no explicit role or outcome mapping (P1)
Problem. In an appeal, the appellant may be on the debtor side, for example a suspended director challenging admission. "APPEAL_ALLOWED" says nothing about which agent's position won.
Fix. Store outcomes normalized per side and per issue:
"issue_findings": [
  {"issue_id": "I1", "favours": "RESPONDENT", "driver": "LAW"},
  {"issue_id": "I2", "favours": "PETITIONER", "driver": "LAW"}
],
"conclusion": {"overall_favours": "MIXED"}
Side labels are always PETITIONER and RESPONDENT, as defined in I2; the full sealed format is in H2.
For appeals, include the lower order in the record, as a real appellate bench would see it.
A7. Cases decided on evidence you lack (P1)
Problem. Some outcomes rest on a factual finding ("notice was never served") that no amount of argument can reach without the document.
Fix. Tag each case LAW_ONLY, MIXED or EVIDENCE_DECIDED. Run Track A on the first two. For EVIDENCE_DECIDED, either exclude the case or stipulate the finding and score only the remaining issues, unless the finding alone decides the case.
B. Precedent DB (schema frozen)
The precedent schema stays as is, with material_facts and ratio_decidendi as the two vectors. Every fix below is a filter, a preprocessing step, or a verification rule.
B1. The same real case may exist in both DBs (P1)
Problem. The public DB is built separately from the precedent DB, which removes structural overlap. But both are drawn from real NCLT/NCLAT judgments, so the same dispute, its NCLT order, or its NCLAT appeal can still appear in both. One dispute often spans several connected appeals, so matching on a single case number is not enough.
Fix. Run a one-time overlap check while building each public case: compare case and appeal numbers, corporate debtor names, and decision dates against the 3000 precedents. Store matches in that case's build.excluded_precedent_ids (H) and apply them as a must_not filter on every search in its sessions (code in B7).
B2. Agents can cite authorities that did not exist yet (P0)
Problem. A 2019 case could be argued with a 2024 NCLAT ruling.
Fix. Add a datetime payload index on decision_date and restrict every search to precedents decided before the simulated case's own decision date.
B3. statutes_cited IDs may not match Law DB IDs (P1)
Problem. Precedents use sub-clause IDs like IBC_2016_SEC_29A_C; earlier documents used IBC_SEC_7. If the Law DB _id is section-level, joins and statute filters silently return nothing.
Fix. Write one normalizer that maps any sub-clause ID to its parent section ID in the Law DB format. Run a one-time integrity check: every statutes_cited value across all 3000 precedents must resolve to a Law DB _id. Store the normalized list in the Qdrant payload as a separate key used only for filtering; the original field is untouched.
B4. Supreme Court authorities are not in the DB (P1)
Problem. Agents rely on Mobilox, Pioneer Urban, Swiss Ribbons and similar SC rulings. Your sample relies on Hari Babu Thota. A strict existence check rejects all of these as fabricated.
Fix. Use three verification tiers instead of pass/fail:
Tier
Condition
Effect on score
VERIFIED
Authority is in the DB and the proposition is entailed by its ratio
Full grounding credit
REFERENCED
Not in the DB, but a DB precedent's ratio or summary cites it for a consistent proposition
Reduced credit, no rejection
UNVERIFIABLE
Neither
Flag and penalize; reject only if the proposition contradicts a DB ratio
NCLAT judgments cite the landmark SC rulings constantly, so the REFERENCED tier covers most of them from your 3000 precedents alone.
B5. The 512-token limit truncates material_facts (P1)
Problem. bge-small-en-v1.5 reads at most 512 tokens and silently drops the rest. Long material_facts lose their last sections, often FACTUAL EVIDENCE and PROCEDURAL HISTORY, which lawyers need to search.
Fix without changing the precedent DB. Vectors are derived data: you can rebuild them any time while the precedent JSONL stays exactly as it is. First count how many records exceed 512 tokens with the bge tokenizer; then pick one option.
Option
Rebuild vectors?
Covers the full field?
Trade-off
Section multivector with bge-small (recommended)
Yes
Yes, each section embedded separately
One point per precedent; best-matching section wins, so noisy sections cannot dilute the match
Long-context model (bge-m3, 8192 tokens)
Yes
Yes, whole field in one vector
Simplest; 1024 dimensions and slower on CPU
Full-text payload index
No
Yes, by keyword
Fallback if vectors cannot be rebuilt; a filter, not a ranking
Section multivector. Each labelled section of material_facts gets its own vector, and sections longer than about 480 tokens are split into sentence windows. Qdrant stores them as one multivector and scores with MAX_SIM. Keep every section except PARTY IDENTITIES: STATUTORY TIMELINES often holds the decisive facts, especially when the order of dates decides an issue.
import re, uuid
from qdrant_client import QdrantClient
from qdrant_client.models import (VectorParams, Distance, MultiVectorConfig,
                                  MultiVectorComparator, PointStruct)
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-small-en-v1.5")
client = QdrantClient(path="./qdrant_data")
RATIO_KEEP = {"ABSTRACT LEGAL RULE", "STATUTORY INTERPRETATION", "EVIDENTIARY TEST APPLIED"}

def split_sections(text: str) -> dict:
    parts = re.split(r"\s*\d+\.\s+([A-Z][A-Z ]+):\s*", text)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}

def windows(text: str, max_tokens: int = 480) -> list[str]:
    out, cur = [], ""
    for sent in re.split(r"(?<=[.;])\s+", text):
        cand = f"{cur} {sent}".strip()
        if cur and len(model.tokenizer.tokenize(cand)) > max_tokens:
            out.append(cur)
            cur = sent
        else:
            cur = cand
    return out + ([cur] if cur else [])

client.create_collection(
    collection_name="nclt_precedents_v2",
    vectors_config={
        "facts": VectorParams(size=384, distance=Distance.COSINE,
                              multivector_config=MultiVectorConfig(comparator=MultiVectorComparator.MAX_SIM)),
        "ratio": VectorParams(size=384, distance=Distance.COSINE),
    },
)

def to_point(rec: dict) -> PointStruct:
    sections = split_sections(rec["material_facts"]) or {"FACTS": rec["material_facts"]}
    fact_texts = [f"{name}: {chunk}" for name, body in sections.items()
                  if name != "PARTY IDENTITIES" for chunk in windows(body)]
    ratio_parts = split_sections(rec["ratio_decidendi"])
    ratio_text = " ".join(f"{k}: {v}" for k, v in ratio_parts.items() if k in RATIO_KEEP) or rec["ratio_decidendi"]
    return PointStruct(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, rec["precedent_id"])),
        vector={
            "facts": model.encode(fact_texts, normalize_embeddings=True).tolist(),
            "ratio": model.encode(ratio_text, normalize_embeddings=True).tolist(),
        },
        payload=rec,  # the precedent record, unchanged
    )
Querying a multivector field takes a list of vectors. A lawyer's free-text search sends one vector, [query_vec]. A case-to-case search can send the current case's own section vectors; MAX_SIM then sums each section's best match, which rewards precedents similar on several sections at once.
Facts-to-facts search is symmetric, so embed both sides without a prefix. Proposition-to-ratio search is asymmetric, so prepend bge's retrieval instruction ("Represent this sentence for searching relevant passages: ") to the query only.
Fallback if vectors cannot be rebuilt. Add a full-text index on the stored field; it covers the whole text, including the part past 512 tokens. Adjust the key if your payload nests the record.
from qdrant_client.models import TextIndexParams, TokenizerType, Filter, FieldCondition, MatchText

client.create_payload_index("nclt_precedents", field_name="material_facts",
    field_schema=TextIndexParams(type="text", tokenizer=TokenizerType.WORD, lowercase=True))

keyword_filter = Filter(must=[FieldCondition(key="material_facts", match=MatchText(text="MSME registration"))])
B6. Similarity thresholds are uncalibrated (P2)
Problem. IBC facts share vocabulary (corporate debtor, default, CIRP), so facts similarity scores cluster high. A fixed 0.75 may let nearly everything through. A fixed 0.90 for lesson dedup has the opposite risk (see F3).
Fix. Embed about 200 precedents, label a sample of pairs as related or unrelated, and set each threshold at the gap between the two score distributions. Expect separate thresholds for the facts vector and the ratio vector.
B7. No issue vector, so facts search can match the wrong legal question (P1)
Problem. With only facts and ratio vectors, a search can return a case with similar commerce but a different legal issue.
Fix. Filter by statute overlap first, then rank by facts similarity. One query also applies B1 and B2:
from qdrant_client.models import Filter, FieldCondition, MatchAny, DatetimeRange

def find_similar_cases(client, facts_vec, case):
    return client.query_points(
        collection_name="nclt_precedents",
        query=[facts_vec],  # multivector field (B5)
        using="facts",
        query_filter=Filter(
            must=[
                FieldCondition(key="statutes_normalized", match=MatchAny(any=case["statutes_normalized"])),
                FieldCondition(key="decision_date", range=DatetimeRange(lt=case["decision_date"])),
            ],
            must_not=[
                FieldCondition(key="precedent_id", match=MatchAny(any=case["excluded_precedent_ids"])),
            ],
        ),
        limit=5,
    ).points
B8. is_overruled is a single flag (P2)
Problem. A precedent overruled in 2025 was good law for a 2023 case, but the flag cannot say when.
Fix. Treat the flag as "not good law today" only. Record the handful of known overrulings with dates in temporal_overlay (C2) and apply them by the simulated case's date.
B9. Retire ingest_api.py (P1)
Problem. The script hardcodes verdict_outcome: "ADMITTED" and statute_ids: ["IBC_2016"] for every case, stores text[250:1200] as the ratio, and its keyword filter pulls in High Court and SC judgments that merely mention NCLT.
Fix. Delete it from the pipeline and the blueprint. Your curated JSONL replaces it.
C. Law DB (schema frozen)
Two side collections cover what the Law DB cannot hold: machine-checkable predicates and date-dependent rules. Several existing fields already do the rest.
C1. Checklist items are free text, so Z3 cannot read them (P0)
Problem. diagnostic_checklist entries are plain strings with no predicate names, so there is nothing for the solver to evaluate.
Fix. Create a predicate_registry collection keyed by statute_id, checklist field, and a hash of the checklist string. Only quantitative or temporal items get a predicate; qualitative items ("debt must be a financial debt") go to THEMIS layer 2 with core_judicial_inquiry. Build it once for the 50 to 80 sections your cases actually use, with an LLM drafting and a human reviewing. If a Law DB string changes, its hash no longer matches and the mapping is marked stale.
{
  "statute_id": "IBC_2016_SEC_9",
  "field": "mandatory_prerequisites",
  "item_hash": "sha1:4be1...",
  "predicate": "days_between(demand_notice_delivered, filing_date) >= 10",
  "record_inputs": ["demand_notice_delivered", "filing_date"],
  "error_code": "ERR_NOTICE_PERIOD_NOT_ELAPSED",
  "reviewed_by": "human"
}
C2. No effective dates, so one law applies to every year (P0)
Problem. financial_threshold.minimum_amount holds one number, but the Section 4 threshold depends on the filing date. Section 10A and the COVID limitation exclusion are date windows the schema cannot express.
Fix. Create a temporal_overlay collection with a few rows the solver reads before the Law DB value:
statute_id
Parameter
Value
Applies when
IBC_2016_SEC_4
minimum_default_inr
1,00,000
Application filed before 24.03.2020
IBC_2016_SEC_4
minimum_default_inr
1,00,00,000
Application filed on or after 24.03.2020
IBC_2016_SEC_10A
bar_window
25.03.2020 to 24.03.2021
Default arose inside the window (bars Sections 7, 9, 10)
LIMITATION_ACT_EXCLUSION
excluded_period
15.03.2020 to 28.02.2022
Limitation running during the window (SC suo motu orders)
Add known overrulings here with their dates too (B8). Have a practitioner confirm each row's exact terms before use.
C3. Existing fields that should drive THEMIS and the bench
These need no change, only wiring:
Law DB field
Use
jurisdiction_type
Picks the Z3 template by role: INITIATING_CLAIM (show prerequisites met), PROHIBITORY_SHIELD (show bar applies), SAVING_PROVISION (show exception conditions hold)
core_judicial_inquiry
The question each judge answers per issue, and the question THEMIS layer 2 checks the argument addresses
audit_error_codes
Names for Z3 tracked assertions, so unsat cores come back as error codes
intersecting_statute_ids
Auto-loads related provisions together, so Section 29A always arrives with Section 240A
D. THEMIS-LOCAL
THEMIS-LOCAL must check whether an argument is honest and grounded, never whether the case is winnable. Z3 encodes arithmetic, dates and undisputed statutory conditions; anything a court had to settle is a parameter the argument chooses.
D1. Argument checklist vs Law DB checklist (P0)
Your design. For each statute an argument invokes, an extractor builds a JSON with the same keys as that statute's diagnostic_checklist and procedural_timelines, recording what the argument says the law requires. Z3 checks it against the real entry in the Law DB. An argument citing three statutes produces three checks.
This is a sound design: it catches a lawyer misstating the law. Four gaps need closing.
1. List fields are free text. Z3 cannot compare strings. The extractor maps each claimed item to the index of the matching Law DB item, or null if none matches, and must quote the argument span it came from.
2. The law check alone misses misapplied facts. A lawyer can state the ₹1 crore threshold correctly and still claim a ₹60 lakh default meets it. Add the record values (amount, dates) from the public case to the same solver.
3. Stance matters. An argument asserting a claim, invoking a bar, or invoking a saving exception needs different checks. The extractor records the stance; jurisdiction_type confirms which template applies.
4. Extraction errors must never reject a good argument. Items with confidence below 0.7 or no quoted span are marked UNMAPPED and go to layer 2. They never cause a Z3 rejection.
Extracted JSON for one statute:
{
  "statute_id": "IBC_2016_SEC_9",
  "stance": "ASSERT_CLAIM",
  "asserts_threshold_met": true,
  "diagnostic_checklist": {
    "applicant_eligibility": [{"law_index": 0, "quote": "the petitioner supplied goods...", "confidence": 0.9}],
    "financial_threshold": {"minimum_amount": 10000000, "currency": "INR"},
    "mandatory_prerequisites": [{"law_index": 0, "quote": "demand notice in Form 3 was delivered...", "confidence": 0.92}],
    "statutory_bars": [],
    "saving_exceptions": []
  },
  "procedural_timelines": {"adjudication_window_days": null, "rectification_window_days": 7}
}
What each check does and how hard it is:
Check
Code
Effect
Claimed threshold differs from the law (date-aware, C2)
ERR_THRESHOLD_MISSTATED
Hard error
Says threshold met, record amount is below it (or the reverse)
ERR_THRESHOLD_APPLICATION
Hard error
Claimed timeline differs from the law
ERR_TIMELINE_MISSTATED
Hard error
Condition claimed that is not in the Law DB list
WARN_CONDITION_NOT_IN_STATUTE
Warning only; it may come from a precedent, so layer 2 checks it
Asserts a claim but leaves some mandatory prerequisites unaddressed
WARN_PREREQUISITE_UNADDRESSED
Warning; lowers S_rule
Low-confidence or unquoted extraction
UNMAPPED
Sent to layer 2, never rejected
Implementation: numbers and dates go through Z3 with tracked assertions; list matching is plain set logic.
from z3 import Solver, Int, Bool, BoolVal, sat

LIST_FIELDS = ("applicant_eligibility", "mandatory_prerequisites", "statutory_bars", "saving_exceptions")

def audit_statute(law: dict, arg: dict, record: dict, law_min) -> dict:
    """law: Law DB entry. arg: extracted checklist (same keys). law_min: threshold after temporal_overlay."""
    s = Solver()
    s.set(unsat_core=True)

    ft = arg["diagnostic_checklist"].get("financial_threshold") or {}
    if law_min is not None and ft.get("minimum_amount") is not None:
        claimed = Int("claimed_min")
        s.add(claimed == int(ft["minimum_amount"]))
        s.assert_and_track(claimed == law_min, Bool("ERR_THRESHOLD_MISSTATED"))

    if law_min is not None and arg.get("asserts_threshold_met") is not None:
        amount = Int("default_amount")
        s.add(amount == int(record["default_amount_inr"]))
        s.assert_and_track((amount >= law_min) == BoolVal(arg["asserts_threshold_met"]),
                           Bool("ERR_THRESHOLD_APPLICATION"))

    for key, value in (arg.get("procedural_timelines") or {}).items():
        law_value = law["procedural_timelines"].get(key)
        if value is not None and law_value is not None:
            v = Int(f"claimed_{key}")
            s.add(v == int(value))
            s.assert_and_track(v == int(law_value), Bool("ERR_TIMELINE_MISSTATED"))

    warnings, unmapped = [], []
    for field in LIST_FIELDS:
        for item in arg["diagnostic_checklist"].get(field, []):
            if item.get("confidence", 0) < 0.7 or not item.get("quote"):
                unmapped.append({"field": field, **item})
            elif item.get("law_index") is None:
                warnings.append({"code": "WARN_CONDITION_NOT_IN_STATUTE", "field": field, "quote": item["quote"]})

    if arg.get("stance") == "ASSERT_CLAIM":
        total = len(law["diagnostic_checklist"]["mandatory_prerequisites"])
        addressed = {i["law_index"] for i in arg["diagnostic_checklist"].get("mandatory_prerequisites", [])
                     if i.get("law_index") is not None}
        missing = sorted(set(range(total)) - addressed)
        if missing:
            warnings.append({"code": "WARN_PREREQUISITE_UNADDRESSED", "law_indices": missing})

    hard = [] if s.check() == sat else [str(c) for c in s.unsat_core()]
    return {"hard_errors": hard, "warnings": warnings, "unmapped": unmapped}
The Law DB is never asked whether the case is winnable; only whether what the lawyer said about the law and the record is accurate. A lawyer on a weak side can always pass by arguing honestly.
D2. Contested interpretations hardcoded as constraints (P0)
Problem. Example: in a Section 240A dispute, the main issue can be which cut-off date decides MSME status. Hardcoding one tribunal's answer into Z3 would fail the other side's argument every time, even where a lower forum accepted that reading. The code below uses illustrative dates.
Fix. Make the interpretation a parameter taken from the argument. Z3 checks only that the agent's facts hold under the reading it chose:
from z3 import Solver, Int, Bool, sat
from datetime import date

def audit_240a(record: dict, claim: dict) -> dict:
    s = Solver()
    s.set(unsat_core=True)
    reg, cutoff, exempt = Int("msme_reg"), Int("cutoff"), Bool("exempt")
    cutoff_date = (record["plan_submission"] if claim["cutoff_basis"] == "PLAN_SUBMISSION"
                   else record["cirp_commencement"])
    s.add(reg == record["msme_registration"].toordinal())
    s.add(cutoff == cutoff_date.toordinal())
    s.add(exempt == (reg < cutoff))
    s.assert_and_track(exempt == claim["asserts_exemption"], Bool("ERR_SAVING_EXCEPTION_MISAPPLIED"))
    if s.check() == sat:
        return {"status": "SAT"}
    return {"status": "UNSAT", "error_codes": [str(c) for c in s.unsat_core()]}

record = {"cirp_commencement": date(2022, 2, 22),
          "msme_registration": date(2022, 5, 24),
          "plan_submission":   date(2022, 7, 11)}

audit_240a(record, {"cutoff_basis": "PLAN_SUBMISSION",   "asserts_exemption": True})   # SAT
audit_240a(record, {"cutoff_basis": "CIRP_COMMENCEMENT", "asserts_exemption": False})  # SAT
audit_240a(record, {"cutoff_basis": "CIRP_COMMENCEMENT", "asserts_exemption": True})   # UNSAT
D3. Threshold and limitation predicates are legally wrong (P0)
Problem. The Section 7 and 9 formulas in the blueprint have six errors:
1. ClaimAmount >= 10^7 ignores that pre-24.03.2020 applications use Rs 1 lakh.
2. HasSection18Ack as a free OR lets an acknowledgment made after expiry revive a dead claim.
3. 1095 days ignores leap years; limitation runs in calendar years.
4. The 15.03.2020 to 28.02.2022 COVID exclusion is missing.
5. The Section 10A bar is missing.
6. ¬FraudulentInitiation is not an admission precondition; Section 65 is a penalty provision and cannot be computed.
The Mobilox test also has a qualitative half: Z3 can check that a dispute predates the demand notice, not whether it is plausible.
Fix. Read thresholds and windows from temporal_overlay (C2), drop FraudulentInitiation, send Mobilox plausibility to the judges, and compute limitation as a date chain:
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

EXCL_START, EXCL_END, RESUME = date(2020, 3, 15), date(2022, 2, 28), date(2022, 3, 1)

def limitation_expiry(default_date: date, acknowledgments: list[date]) -> date:
    # Article 137: three years from the date of default
    expiry = default_date + relativedelta(years=3)
    # Section 18: only an acknowledgment made before expiry starts a fresh three years
    for ack in sorted(acknowledgments):
        if ack <= expiry:
            expiry = max(expiry, ack + relativedelta(years=3))
    # SC suo motu exclusion: balance runs from 01.03.2022, minimum 90 days
    if default_date <= EXCL_END and expiry >= EXCL_START:
        running_from = max(default_date, EXCL_START)
        balance = (expiry - running_from).days
        expiry = RESUME + timedelta(days=max(balance, 90))
    return expiry
Two cautions. Acknowledgments made inside the excluded window need manual review, because this sketch applies them before the exclusion. Have a practitioner verify the exclusion arithmetic against the SC orders before relying on it.
D4. Embeddings cannot detect inverted holdings (P1)
Problem. "The court held X" and "the court held not X" embed almost identically, so cosine similarity cannot catch the most dangerous citation error.
Fix. Use vectors only to find a precedent. To verify, fetch it by precedent_id, take ratio parts 1 to 3, and run an LLM entailment check that returns SUPPORTS, CONTRADICTS or NOT_ADDRESSED. CONTRADICTS is a hard failure (ERR_PRECEDENT_MISATTRIBUTED). Citing part 4 (the case-specific conclusion) as a general rule is also NOT_ADDRESSED.
D5. Layer 2 has no defined scope (P1)
Fix. Give layer 2 four jobs and read-only tools, temperature 0, no web access, and no sight of the real judgment:
Job
Tool
Fails with
Citation verification (B4 tiers + D4 entailment)
get_precedent(id), get_statute(id, as_of)
ERR_PRECEDENT_MISATTRIBUTED
Record fidelity (A2)
get_record_item(id)
ERR_FACT_NOT_IN_RECORD, ERR_EXHIBIT_CONTENT_FABRICATED
Responsiveness to the opponent's last turn
get_session_history(agent)
Score only, no rejection
Repetition of own earlier arguments
Redis session memory
ERR_REPEATED_ARGUMENT
D6. Scoring formula problems (P1)
Problem. With S_rule boolean, any argument with S_rule = 0 needs S_llm = 1.0 to reach 0.70, so it is a hidden hard gate. The penalty 0.15 × FailedRetries, summed over five turns, can reach 2.25 and swamp S_global, which tops out at 1.0. Soft NLP metrics risk being used as gates.
Fix. Make S_rule the fraction of applicable checklist items the argument addresses (0 to 1). Cap total local penalty at 0.30 per agent per case. Gate only on misstatements (D1), fabrication (A2), misattribution (D4) and repetition; log readability and persuasiveness metrics without rejecting on them.
D7. Retry feedback is vague (P2)
Fix. Feed the retry prompt the unsat-core error codes plus the specific record IDs or precedent IDs involved, for example: "ERR_LIMITATION_MISSTATED: you stated default on 01.04.2019; record F4 shows 01.04.2017." The same codes are what the reflection engine stores.
D8. Rejection policy: reject only what is provably wrong (P0)
Problem. With a numeric S_local ≥ 0.70 gate on top of several checks, honest but imperfect arguments get rejected, and every turn burns retries. Rejections then reflect the verifier's noise rather than the lawyer's errors.
Fix. Only a fixed list of hard errors triggers a retry. Everything else is a warning that lowers the score but publishes the argument. The 0.70 threshold stays as a score, not a gate.
Outcome
Triggered by
What happens
Who sees what
PASS
No hard errors, no warnings
Published
Everyone sees the text
PASS_WITH_NOTES
Warnings or UNMAPPED items only
Published; score reduced
Notes go only to that agent's reflection, never to the opponent or judges
REVISE
One or more hard errors
Retry with the exact codes and record IDs (D7), max 3
Private to the agent
FLAGGED
Hard error remains after 3 retries
Best attempt published with flag and code
Opponent and judges see the flag and code
The complete hard-error list:
1. ERR_THRESHOLD_MISSTATED, ERR_THRESHOLD_APPLICATION, ERR_TIMELINE_MISSTATED (D1)
2. ERR_FACT_NOT_IN_RECORD, ERR_EXHIBIT_CONTENT_FABRICATED (A2)
3. ERR_PRECEDENT_MISATTRIBUTED: entailment returns CONTRADICTS (D4)
4. ERR_REPEATED_ARGUMENT: only when similarity to the agent's own earlier turn exceeds 0.95; lower similarity is a warning
Not on the list, so never a rejection: UNVERIFIABLE citations, unaddressed prerequisites, conditions not in the Law DB, low responsiveness, extraction failures.
Calibrate on the 20-case pilot (G4). If the first-attempt pass rate falls below about 70%, sample the rejections and check how many were verifier mistakes before tightening anything.
E. THEMIS-GLOBAL and the judicial bench
The winner is the side with the higher aggregated advocacy score, as designed; the fixes below keep that score free of bias. The real outcome is used only after the verdict, for evaluation and reflection.
E1. Advocacy-score verdict: keep it, remove the bias in it (P0)
Your design. The side with the higher aggregated advocacy score across the three judges wins. This stays.
What to report. Since the winner reflects argument quality, report alignment with the real outcome as "advocacy-to-outcome alignment": how often the better-argued side is also the side that really won. State this once in the paper; it is a finding, not a flaw.
Bias risks in LLM scoring and their guards:
Risk
Guard
Longer arguments score higher
Same token cap per turn for both agents; check the score-length correlation in the pilot
The side read first or last scores differently
Each judge scores each issue twice with the two sides presented in swapped order, then averages; if the orders differ by more than 0.15, re-run
Agent or model names sway judges
Judges see only "Petitioner's counsel" and "Respondent's counsel"; no agent names, memory contents or retry counts
Verifier scores anchor the judges
Judges see only FLAGGED hard errors (D8), never S_local, warnings or notes
A flagged error is penalized twice
Judges score accuracy normally; Penalty_local is removed from the winner calculation and kept only in the reflection reward (F2)
One issue dominates the total
Score per framed issue, then average across issues
A persona systematically favours one role
Track each persona's win rate by role; flag any persona above 65% for one role over 50+ cases
Scoring rule. Each side's score is the mean, across 3 judges, all framed issues and both presentation orders, of 0.35 × accuracy + 0.25 × consistency + 0.20 × rebuttal + 0.20 × grounding. The higher score wins. If the gap is under 0.02, the higher accuracy component decides; if that also ties, record a tie.
{
  "judge": "TEXTUALIST",
  "issue_scores": [
    {"issue_id": "I1", "order": "PETITIONER_FIRST",
     "PETITIONER": {"accuracy": 0.70, "consistency": 0.80, "rebuttal": 0.60, "grounding": 0.75},
     "RESPONDENT": {"accuracy": 0.80, "consistency": 0.85, "rebuttal": 0.70, "grounding": 0.80},
     "reasons": "...", "record_ids_relied_on": ["F1", "EX-5"]},
    {"issue_id": "I1", "order": "RESPONDENT_FIRST", "PETITIONER": {}, "RESPONDENT": {}, "reasons": "..."}
  ]
}
The Verdict Consistency Validator confirms the declared winner matches the higher aggregate and that each judge's stated reasons do not contradict its own scores.
E2. Pragmatist persona conflicts with current law (P1)
Problem. The Commercial Pragmatist weighs hardship and rescue before admitting a Section 7 petition. After M. Suresh Kumar Reddy v. Canara Bank (2023) confined Vidarbha Industries to its facts, admission follows once debt and default are established and the application is complete. This persona will diverge from real outcomes for legal reasons, not philosophical ones.
Fix. Define personas by interpretive method, not preferred outcome:
Persona
Method
Typical question
Textualist
Plain meaning of the provision
What do the words of Section 5(8) require?
Purposivist
Reading in light of the Code's object of resolution over recovery (Swiss Ribbons)
Which reading serves the Code's purpose within its text?
Proceduralist
Limitation, service, maintainability, forum
Was the application filed in time and in proper form?
Each persona's prompt states that it must apply binding Supreme Court law; method shapes reasoning, not the right to disregard it.
E3. Rebuttal depth measured by similarity (P1)
Problem. Scoring rebuttal by semantic similarity between an opponent's argument and the reply rewards restating the opponent's words rather than answering them.
Fix. THEMIS-GLOBAL lists the opponent's distinct points per turn, then an LLM marks each as ANSWERED, CONCEDED or IGNORED in the reply. Rebuttal depth is the share answered, weighted by how central the point was to a framed issue.
E4. Turn smoothing undervalues early turns (P2)
Problem. The exponential moving average with T = 0.5 gives turn 10 half the weight and turn 2 under 1%. Opening arguments, where most issues are first raised, barely count.
Fix. Score quality per issue across all turns that touch it, then average across issues. Keep the EMA only if you want a trajectory chart.
E5. Cross-turn contradiction check (keep)
This part of THEMIS-GLOBAL is sound. Make it concrete by comparing each agent's tracked claims (from D1 claim extraction) across turns, so a contradiction is two claim records with opposite values, not an LLM impression.
E6. Structural fairness between the agents (P0)
Problem. Several advantages come from the setup, not from argument quality. With alternating turns and LEX-P opening, LEX-D always has the last word, and LLM judges weigh the final text heavily. Unequal memory, retrieval or prompts would tilt results the same way.
Fix. Make every input to the two agents symmetric, and write closings blind:
Source of advantage
Guard
Last word
Turns 1 to 8 alternate (P, D, P, D...). Turns 9 and 10 are closing statements written in parallel from the transcript through turn 8; neither agent sees the other's closing
Model and settings
Same model, temperature and token cap for both lawyers
Prompts
One system prompt template; only the role line differs. No hints about which side is stronger
Record
Both see the identical record, including exhibits filed by the other side, in the same order
Retrieval
Same tools, top-k, thresholds and filters, including the same excluded_precedent_ids
Memory
Same pinned-lesson token budget (250) and the same K for both, even if one memory is larger
Verification
Same hard-error list, retry cap and outcome rules (D8)
Visibility
Both sides' FLAGGED codes are shown to the other side; warnings stay private for both
The hallucination guards apply equally to both agents: the closed record (A2), citation tiers (B4), entailment checks (D4), no ground truth anywhere before the verdict, and lessons without party names (F7).
F. Reflection engine and memory
Lawyer memory stores how to argue better; judge memory stores what the law is. Every lesson must be general, earn its weight by helping later, and fade if it stops helping.
F1. Lessons ban the client's own position (P1)
Problem. Example: after losing a sale-consideration case, LEX-P stores "Do not characterize unpaid asset sale consideration as financial debt." The next time that is its client's case, LEX-P has no argument left. The blueprint also says LEX-P will "avoid filing under Section 7", but the lawyer never chooses the forum; the case arrives already filed.
Fix. Split lessons by type and owner:
Type
Stored in
Example (illustrative)
ADVOCACY
Lawyer memory (by role)
Expect the Pioneer Urban disbursement objection; lead with the 5(8)(f) commercial-effect argument and the interest-bearing instalments rather than later letters
LEGAL_RULE
Judge memory
Unpaid purchase price under a sale is not financial debt absent disbursement of money
PROCEDURAL_ERROR
Lawyer memory
Misstated dates or fabricated exhibit contents, keyed by error code
The reflection prompt forbids lessons that tell an advocate to abandon its side's position. Remove the forum-choice sentence from the blueprint.
F2. Lawyer reward and judge reward are conflated (P1)
Problem. If lawyers are rewarded for matching the real outcome, the side that rightly lost learns nothing useful.
Fix. Judges are scored on per-issue agreement with the real judgment and on using the same legal test. Lawyers are scored on: raising the points the real court found decisive, citing the authorities it relied on, avoiding THEMIS failures, and answering the opponent's points (E3). State in the blueprint that Reward(i) is consumed only by the reflection engine; nothing is trained on it.
F3. Deduplication can merge opposite lessons (P1)
Problem. "Cite Section 18 acknowledgment early" and "Do not cite Section 18 acknowledgment" can score above 0.90 with bge-small, so they merge and add their frequencies.
Fix. Deduplicate in three steps: match on a structured key (lesson_type, role, statute IDs, error code); then compare embeddings within that key; then ask an LLM "same lesson, opposite lesson, or different?" before merging. Opposite lessons are kept apart and the older one loses confidence.
F4. Memory weight only grows (P1)
Problem. W = Severity × Frequency never decreases, so a wrong lesson reinforced a few times stays pinned forever.
Fix. Weight by validated usefulness and age:
W_j = \mathrm{Sev}_j \cdot \log(1 + \mathrm{Freq}_j) \cdot \mathrm{Conf}_j \cdot \lambda^{a_j}
Here a_j is the number of cases since the lesson was last retrieved and λ is about 0.98. Conf starts at 0.5, rises when the lesson is retrieved and the agent's advocacy score improves, and falls when it does not. Lessons below Conf 0.2 are retired.
F5. Lessons learned from evidence the agents never had (P1)
Fix. Use the driver tag on each real holding (A6). Mismatches on EVIDENCE holdings produce no lesson; only LAW holdings do.
F6. LEX-P only ever learns the creditor side (P2)
Problem. In IBC the petitioner is nearly always the creditor, so LEX-P learns creditor strategy only and LEX-D debtor strategy only.
Fix. Either swap which agent argues which side on alternate cases, or keep role-specific lessons in separate memories that whichever agent takes that role loads.
F7. Lesson schema
{
  "lesson_id": "L-0142-03",
  "lesson_type": "ADVOCACY",
  "role": "CREDITOR",
  "statute_ids": ["IBC_2016_SEC_5_8"],
  "error_code": null,
  "trigger": "Sec 7 claim on deferred sale consideration; debtor raises no-disbursement objection",
  "lesson": "Lead with 5(8)(f) commercial effect and the interest-bearing instalment structure; do not rely on later letters to recharacterize the transaction",
  "driver": "LAW",
  "source_case": "TRAIN_0142",
  "severity": 4,
  "frequency": 1,
  "confidence": 0.5,
  "last_retrieved_case": 142
}
Lessons never name parties or say "in case X the answer is Y"; the reflection prompt rejects any lesson containing a party name.
G. Evaluation, cost and document cleanup
The core claim to prove is that the reflection loop improves results on unseen cases; the split and baselines below are built to test exactly that.
G1. No train/test protocol (P0)
Fix. Split the 500 public cases by time, stratified by provision (Sections 7, 9, 10, 12A, 29A, 31, 60(5), 66 and so on) and by winning side:
Split
Cases
Memory
Purpose
Train
Oldest ~350
Read and write
Reflection builds memory
Validation
Next ~50
Read only
Tune thresholds, weights, prompts
Test
Newest ~100
Frozen
Report results once
Run the test set twice: once with empty memory, once with trained memory. The difference is your main result. Add ablations for no THEMIS, no memory, and no exhibit cards.
G2. Alignment metric too coarse (P1)
Fix. Report verdict alignment and per-issue alignment, each on LAW_ONLY and MIXED cases only (A7). Report the contaminated subset from the memorization probe (A4) separately. Track B (human vs AI judges) is unaffected.
G3. Inconsistencies and artifacts in the blueprint (P2)
Where
Problem
Fix
Blueprint case-study sections
Interest rate given as 15% in the schema, 16% in the walkthrough
Check the judgment; use one figure
Data infrastructure
Precedent DB described as 500 cases; actual design is 3000 precedents + 500 curriculum
State both sets and that they are disjoint (B1)
THEMIS-LOCAL
Embedder named as BGE-M3 in one place, bge-small-en-v1.5 elsewhere
Use bge-small-en-v1.5 throughout
Case studies and summary
Leftover [cite: N] markers
Remove all
Section 9.2
ingest_api.py with hardcoded payloads
Remove (B9)
Literature table
Several 2026 entries I could not confirm
Verify every author, venue and year against the actual paper before submission
Panel defense Q3
Says layer 2 checks ratio by semantic distance
Update to entailment check (D4)
Panel defense Q5
Says winner is the higher composite score
Keep; add the debiasing steps from E1
Case walkthrough
LEX-P "avoids filing under Section 7" in future
Remove (F1)
SMT section
¬FraudulentInitiation and 1095-day limitation
Replace with D3 predicates
For a project about citation hallucination, an unverifiable reference in your own literature table is the first thing a panel will check.
G4. Cost not budgeted (P2)
A rough count per case: 10 turns × 1 to 4 drafts × (1 lawyer call + about 2 THEMIS calls for claim extraction and entailment), plus about 3 for THEMIS-GLOBAL, 3 judges, 1 validator and 2 reflection calls. That is roughly 40 to 130 LLM calls per case, or 20,000 to 65,000 across 500 cases. Run a 20-case pilot first, measure the real retry rate, and budget from that.
H. Public DB format
The public DB holds four collections. Agents read only cases.agent_view and published turn text; the real outcome lives in a physically separate collection, so a query or projection bug cannot leak it.
Collection
Holds
Who can read
cases
Agent view of each case plus build information
Clerk; agents get agent_view only
case_ground_truth
Real submissions, statutory and precedent analysis, court reasoning, conclusion, anonymization map
Only after the verdict: evaluation, reflection engine, admin
transcript_turns
One document per published turn
Text and visible flags: opponent and judges. Attempts, warnings, scores: owning agent's reflection only
sessions
One document per run: audits, scorecards, winner, metrics
Evaluation and reflection
H0. How a judgment maps to the public DB
Every NCLT/NCLAT judgment has the same parts, and each part has one destination. Facts, issues, reliefs sought and headline grounds go to the agents; everything the court did with them stays sealed.
Judgment part
Goes to
Agents see it?
Header: case number, parties, counsel, bench, date
case_ground_truth.citation and anonymization_map; pseudonymized parties in agent_view.parties
Pseudonyms and roles only
Impugned order (appeals)
agent_view.lower_forum_order
Yes
Brief facts
agent_view.record, procedural_history, factual_background
Yes, neutralized
Issues framed by the court, or derived from submissions
agent_view.framed_issues
Yes, rewritten as neutral questions
Petitioner / appellant submissions
Headline grounds and reliefs in agent_view; full contentions with authorities in real_submissions
Headline grounds only
Respondent submissions
Same as above
Headline grounds only
Analysis of statutes
case_ground_truth.statutory_analysis
No
Precedent analysis
case_ground_truth.precedent_analysis
No
Court's reasoning and findings
case_ground_truth.issue_findings
No
Conclusion and operative order
case_ground_truth.conclusion
No
The authorities each counsel cited are sealed by default. If agents saw them, the debate would replay the real hearing instead of testing research. The sealed copy is used afterwards to score whether each lawyer found the authorities real counsel used and the court relied on. A config flag show_pleaded_authorities can switch this on for experiments.
H1. cases (what agents can see)
{
  "_id": "STRING (Opaque case ID, e.g., PUB_0001; never derived from party names or case numbers)",
  "split": "STRING (TRAIN | VALIDATION | TEST)",

  "build": {
    "source_forum": "STRING (NCLT | NCLAT)",
    "evidence_dependency": "STRING (LAW_ONLY | MIXED | EVIDENCE_DECIDED)",
    "issues_source": "STRING (FRAMED_BY_COURT | DERIVED_FROM_SUBMISSIONS)",
    "memorization_probe": "STRING (NOT_IDENTIFIED | IDENTIFIED)",
    "excluded_precedent_ids": [
      "STRING (precedent_id of the same dispute, connected appeals, or the same corporate debtor)"
    ],
    "extraction_flags": [
      {
        "code": "STRING (e.g., CONFLICTING_FIGURES, DATE_INCONSISTENCY, MISSING_TABLE, ENCODING_ERROR)",
        "detail": "STRING (What conflicts or is missing, with paragraph numbers)",
        "resolution": "STRING (Which value was used and why, or MOVED_TO_CONTESTED)"
      }
    ],
    "human_reviewed": "BOOLEAN",
    "clerk_version": "STRING"
  },

  "agent_view": {
    "metadata": {
      "forum": "STRING (Forum hearing the simulated matter: NCLT | NCLAT)",
      "proceeding_type": "STRING (e.g., SEC_7_APPLICATION, SEC_9_APPLICATION, IA_IN_CIRP, IA_IN_LIQUIDATION, APPEAL_UNDER_SEC_61)",
      "statutes_invoked": ["STRING (Law DB _id values, normalized to section level)"],
      "simulation_date": "DATE (Real decision date; used server-side for law versions and the precedent cut-off; stripped before prompting)",
      "key_dates": [
        {
          "label": "STRING (e.g., DEFAULT, DEMAND_NOTICE, CIRP_COMMENCEMENT, FILING, LIQUIDATION_ORDER)",
          "date": "DATE",
          "fact_id": "STRING (Record fact this date comes from)"
        }
      ]
    },

    "parties": [
      {
        "party_id": "STRING (e.g., A1, R1, R2)",
        "pseudonym": "STRING (e.g., Liquidator-A, Authority-B)",
        "status": "STRING (e.g., FINANCIAL_CREDITOR, OPERATIONAL_CREDITOR, CORPORATE_DEBTOR, RESOLUTION_PROFESSIONAL, LIQUIDATOR, STATUTORY_AUTHORITY, BANK, SUSPENDED_DIRECTOR)",
        "simulation_side": "STRING (PETITIONER | RESPONDENT | PROFORMA)",
        "appeal_position": "STRING or NULL (APPELLANT | RESPONDENT_1, RESPONDENT_2 ...)",
        "represented_by_agent": "STRING (LEX_P | LEX_D | NONE)",
        "substituted_from": "STRING or NULL (party_id this party replaced during the proceedings)"
      }
    ],

    "factual_background": "STRING (Neutral chronology; each sentence ends with the fact or exhibit IDs it rests on)",

    "record": {
      "stipulated_facts": [
        {"fact_id": "STRING (F1, F2 ...)", "text": "STRING", "source_paras": ["STRING"]}
      ],
      "contested_facts": [
        {
          "fact_id": "STRING (C1, C2 ...)",
          "question": "STRING (The disputed point, phrased neutrally)",
          "petitioner_version": "STRING",
          "respondent_version": "STRING",
          "source_paras": ["STRING"]
        }
      ],
      "exhibits": [
        {
          "exhibit_id": "STRING (EX-1, EX-2 ...)",
          "title": "STRING (Document type and date as the judgment names it)",
          "filed_by": "STRING (party_id)",
          "known_contents": ["STRING (Only what the judgment says the document contains)"],
          "contents_beyond_known": "UNKNOWN",
          "authenticity": "STRING (PRESUMED | DISPUTED)"
        }
      ],
      "amounts": [
        {
          "amount_id": "STRING (AM1, AM2 ...)",
          "label": "STRING (e.g., CLAIMED_DEFAULT, CLAIM_ADMITTED, ATTACHMENT_DEMAND, RESOLUTION_PLAN_VALUE)",
          "value_inr": "NUMBER",
          "date": "DATE or NULL",
          "party_id": "STRING or NULL",
          "fact_id": "STRING"
        }
      ]
    },

    "procedural_history": [
      {"step": "NUMBER", "date": "DATE", "forum": "STRING", "event": "STRING (Neutral description, no evaluation)", "fact_id": "STRING"}
    ],

    "lower_forum_order": {
      "exists": "BOOLEAN (True only for appeals)",
      "forum": "STRING or NULL",
      "result": "STRING or NULL (e.g., ADMITTED, DISMISSED, PARTLY_ALLOWED)",
      "directions": ["STRING (Each operative direction of the order under appeal)"],
      "reasons_summary": "STRING or NULL",
      "ex_parte": "BOOLEAN or NULL (Whether a party did not appear below)"
    },

    "framed_issues": [
      {
        "issue_id": "STRING (I1, I2 ...)",
        "question": "STRING (Neutral question; no words like erred, merely, satisfies, failed)",
        "statutes": ["STRING (Law DB _id values)"],
        "raised_by": "STRING (PETITIONER | RESPONDENT | COURT)"
      }
    ],

    "reliefs_sought": {
      "PETITIONER": ["STRING (Each order the petitioner side asks for)"],
      "RESPONDENT": ["STRING (Each order the respondent side asks for)"]
    },

    "opening_positions": {
      "PETITIONER": [{"issue_id": "STRING", "ground": "STRING (Headline ground; no case citations)"}],
      "RESPONDENT": [{"issue_id": "STRING", "ground": "STRING (Headline ground; no case citations)"}]
    },

    "presumptions": [
      "STRING (e.g., Exhibits are presumed genuine and duly executed)",
      "STRING (e.g., Facts marked CONTESTED remain disputed)",
      "STRING (e.g., Nothing is known about an exhibit beyond its known_contents)"
    ]
  }
}
amounts and key_dates are the values the D1 Z3 checks read from, so every number or date an argument can be checked against must appear in one of them. simulation_side follows I2: the party seeking relief in the proceeding being simulated is PETITIONER (the appellant, in appeals) and is argued by LEX-P. Parties with no live stake (a bank holding attached accounts, for example) are PROFORMA and have no agent.
H2. case_ground_truth (sealed until the verdict)
{
  "_id": "STRING (Same as cases._id)",
  "access": "SEALED_UNTIL_VERDICT",

  "citation": {
    "case_number": "STRING (e.g., Company Appeal (AT) (Ins.) No. ___ of ____)",
    "arising_from": "STRING or NULL (Lower forum, IA and CP numbers, order date)",
    "bench": ["STRING (Member name and designation)"],
    "decision_date": "DATE",
    "source_title": "STRING (Title as published by the source)"
  },

  "anonymization_map": {
    "PSEUDONYM": "STRING (Real name)"
  },

  "real_submissions": {
    "PETITIONER": [
      {
        "issue_id": "STRING",
        "contention": "STRING (Paraphrased argument)",
        "statutes_cited": ["STRING (Law DB _id values)"],
        "authorities_cited": [
          {
            "name": "STRING (Case name as cited)",
            "precedent_id": "STRING or NULL (If it exists in the precedent DB)",
            "forum": "STRING (SC | NCLAT | NCLT | HC)",
            "proposition": "STRING (What counsel cited it for)"
          }
        ],
        "source_paras": ["STRING"]
      }
    ],
    "RESPONDENT": ["SAME STRUCTURE AS PETITIONER"]
  },

  "statutory_analysis": [
    {
      "statute_id": "STRING (Law DB _id)",
      "interpretation": "STRING (How the court read the provision)",
      "interacts_with": ["STRING (Other statute_ids the court read it with, including other Acts)"],
      "source_paras": ["STRING"]
    }
  ],

  "precedent_analysis": [
    {
      "name": "STRING",
      "precedent_id": "STRING or NULL",
      "forum": "STRING (SC | NCLAT | NCLT | HC)",
      "bench_strength": "NUMBER or NULL",
      "cited_by": "STRING (PETITIONER | RESPONDENT | COURT)",
      "treatment": "STRING (FOLLOWED | APPLIED | DISTINGUISHED | NOT_FOLLOWED | DOUBTED | NOTED)",
      "proposition": "STRING (What the court took from it)",
      "later_history": "STRING or NULL (e.g., AFFIRMED_BY_SC, APPEAL_DISMISSED_BY_SC)",
      "source_paras": ["STRING"]
    }
  ],

  "issue_findings": [
    {
      "issue_id": "STRING",
      "favours": "STRING (PETITIONER | RESPONDENT | NEITHER)",
      "driver": "STRING (LAW | EVIDENCE | MIXED)",
      "finding": "STRING (One-sentence holding on this issue)",
      "reasoning": "STRING (The court's chain of reasoning, paraphrased)",
      "test_applied": "STRING (Legal test used, ideally matching a core_judicial_inquiry)",
      "decisive_points": ["STRING"],
      "authorities_relied_on": ["STRING (Names from precedent_analysis)"],
      "source_paras": ["STRING"]
    }
  ],

  "conclusion": {
    "disposition": "STRING (ALLOWED | DISMISSED | PARTLY_ALLOWED | DISPOSED_WITH_DIRECTIONS | REMANDED | SET_ASIDE)",
    "reliefs": [
      {
        "relief": "STRING (Matches an item in agent_view.reliefs_sought)",
        "sought_by": "STRING (PETITIONER | RESPONDENT)",
        "outcome": "STRING (GRANTED | REFUSED | PARTLY_GRANTED | MODIFIED)"
      }
    ],
    "directions": ["STRING (Each operative direction, paraphrased)"],
    "costs": "STRING or NULL",
    "overall_favours": "STRING (PETITIONER | RESPONDENT | MIXED)"
  }
}
Outcomes are often mixed: one side wins the relief it asked for while the other side's legal position is upheld. Record both: reliefs per relief, issue_findings per issue, and overall_favours as MIXED when they split. Since the winner is decided by advocacy score (E1), these fields are used only for evaluation (G2) and reflection (F2).
H3. transcript_turns
{
  "_id": "PUB_0142_R1_T03",
  "case_id": "PUB_0142",
  "session_id": "PUB_0142_R1",
  "turn": 3,
  "speaker": "PETITIONER",
  "turn_type": "REJOINDER",
  "issues_addressed": ["I1", "I2"],
  "published_text": "...",
  "claims": [
    {"claim_id": "T03-C1", "type": "FACT", "text": "...", "record_ids": ["F2", "EX-1"]},
    {"claim_id": "T03-C2", "type": "LAW", "text": "...", "statute_id": "IBC_2016_SEC_5_8",
     "precedent_ids": ["<precedent_id>"], "citation_tier": "VERIFIED", "entailment": "SUPPORTS"}
  ],
  "statute_checklists": ["one extracted JSON per statute, as in D1"],
  "themis_local": {
    "outcome": "PASS_WITH_NOTES",
    "attempts": 2,
    "hard_errors_by_attempt": [["ERR_THRESHOLD_APPLICATION"], []],
    "warnings": [{"code": "WARN_PREREQUISITE_UNADDRESSED", "law_indices": [2]}],
    "s_local": 0.81
  },
  "visible_flags": [],
  "created_at": "YYYY-MM-DDTHH:MM:SSZ"
}
turn_type follows the schedule in E6: OPENING, REPLY, REJOINDER, SUR_REJOINDER and so on through turn 8, then two CLOSING turns written in parallel.
H4. sessions
{
  "_id": "PUB_0142_R1",
  "case_id": "PUB_0142",
  "split": "TRAIN",
  "config": {"lawyer_model": "...", "judge_model": "...", "memory_snapshot": "mem_v37", "seed": 7},
  "themis_global": {"consistency": {}, "rebuttal_depth": {}, "contradictions": []},
  "judge_scorecards": ["one per judge, as in E1"],
  "aggregate": {"PETITIONER": 0.74, "RESPONDENT": 0.81},
  "winner": "RESPONDENT",
  "evaluation": {"winner_matches_real": true, "issue_alignment": 1.0},
  "lessons_written": ["L-0142-03"]
}
memory_snapshot records which memory version a run used, so test runs can prove memory was frozen (G1). The evaluation block is written only after case_ground_truth is unsealed.
H5. Clerk extraction rules
These rules apply to every judgment the clerk parses. The left column describes problems typical of tribunal PDFs; the specific instances mentioned were seen in the sample you shared.
#
What appears in judgments
Rule
1
Repeated page headers and footers (source title, site URL, case number on every page) and broken characters such as "Employeesâ’"
Strip page furniture and fix encoding before any parsing; log ENCODING_ERROR if text was repaired
2
The facts section of an appeal includes the lower forum's own findings
Route them to lower_forum_order, never to stipulated_facts
3
The same figures or dates differ inside one judgment (two amounts swapped between the facts and a party's submissions; one appointment dated 2022 in one paragraph and 2023 in another)
Never pick silently. Prefer the court's own facts section, log CONFLICTING_FIGURES or DATE_INCONSISTENCY, and move the point to contested_facts if an issue depends on it
4
Tables lost in PDF text ("a table ... is given below:" followed by nothing)
Log MISSING_TABLE; never reconstruct the values
5
No "issues for consideration" paragraph
Derive issues from the competing submissions, rewrite them neutrally, set issues_source to DERIVED_FROM_SUBMISSIONS
6
A party replaced mid-proceedings (an RP replaced by the liquidator as appellant)
Keep one party_id per role, record substituted_from
7
Many respondents, some with no real stake (banks holding attached accounts)
Mark them PROFORMA; only the parties actually arguing get an agent
8
A party absent below, so the lower order was passed ex parte
Set lower_forum_order.ex_parte; note it in procedural_history
9
Long verbatim quotations of precedents and statutes inside submissions
Paraphrase the proposition into real_submissions; keep paragraph references; put nothing quoted into agent_view
10
The court weighs benches against each other (a three-member bench preferred over an earlier two-member bench)
Fill bench_strength and treatment for each precedent; this is what lets THEMIS and the judges reason about which authority binds
11
Mixed outcomes (an attachment removed at the appellant's request, while the respondents' claim is ordered paid in full outside the waterfall)
Record per relief and per issue; set overall_favours to MIXED
12
Text that cites the court's later reasoning inside the facts ("as held below", "this Tribunal has already held")
Remove it from the agent view; it belongs in issue_findings or precedent_analysis
After extraction, a second pass checks the agent view for leakage: no case number, real names, bench names, decision date, or evaluative words, and no sentence copied from the analysis or conclusion sections.
I. Consistency and loophole audit
The system stays consistent if three things hold: every store has fixed readers and writers, every ambiguous choice has one rule, and the remaining loopholes below are closed. Where an earlier section disagrees with this one, this section wins.
I1. Who reads and writes each store
The knowledge base maps onto three stores: regulation memory is the Law DB with its side collections (read-only), the case library is the precedent DB (read-only), and the experience DB is the two lesson memories (written only by reflection, after a verdict). Agents never retrieve past session transcripts; only distilled lessons carry across cases.
Store
Written by
When
Read by
Never read by
Law DB, temporal_overlay, predicate_registry
You, through ingestion scripts
Offline, between runs
Lawyers, THEMIS, judges, reflection (as of the case date)
—
Precedent DB (case library)
You, through ingestion scripts
Offline, between runs
Lawyers, THEMIS, judges (date cut-off and exclusion list always applied)
—
cases.agent_view
Clerk
Offline, before the case runs
Lawyers, THEMIS, judges
—
case_ground_truth
Clerk
Offline
Evaluator and reflection, only after the verdict
Lawyers, THEMIS-LOCAL, THEMIS-GLOBAL, judges
Published turns (text + visible flags)
Orchestrator
During the session
Both lawyers, THEMIS, judges
—
Private turn data (attempts, warnings, scores)
THEMIS-LOCAL
During the session
That agent's reflection only
Opponent, judges
Redis session memory
Each agent
During the session; cleared at the end
That agent and its own THEMIS-LOCAL
Opponent, later sessions
Lawyer experience memory
Reflection
After the verdict
Lawyers whose party status matches, at session start
Judges, THEMIS
Judge experience memory
Reflection
After the verdict
Judges
Lawyers, THEMIS
sessions
Orchestrator and evaluator
During and after the session
Reflection, your analysis
Any agent
Config
You
Between runs only
All components
—
In test runs, both experience memories are read-only.
I2. Single rules for choices that were ambiguous
Topic
Rule
Who LEX-P represents
The party seeking relief in the proceeding being simulated: the applicant in an original matter, the appellant in an appeal. LEX-D represents the side opposing that relief.
Side labels
PETITIONER and RESPONDENT everywhere: agent view, ground truth, scorecards, sessions.
Memory key
Lessons are keyed by party status (for example FINANCIAL_CREDITOR, CORPORATE_DEBTOR, LIQUIDATOR) plus statute IDs, not by agent name. An agent loads lessons for the status it represents in that case.
Case date
simulation_date is the real decision date. It sets the precedent cut-off and the law version, server-side only. Each overlay row names which key date it keys on (filing, default, commencement).
Personas
Textualist, Purposivist, Proceduralist. "Commercial Pragmatist" is retired in every document.
THEMIS-LOCAL
Two instances with identical rules and config; each keeps only its own agent's session history.
Turn schedule
Turns 1 to 8 alternate starting with LEX-P; turns 9 and 10 are parallel closings, which may answer turn 8. Five turns each.
Winner
Higher aggregate advocacy score (E1). Penalties affect only the reflection reward.
Alignment metric
Per-issue alignment is primary. Verdict alignment is computed only when the real overall_favours is not MIXED.
Learning signal conflicts
On what the law is, the real judgment wins over judge scores. Judge scorecards shape only advocacy-craft lessons.
Lesson timing
Lessons from case N become readable from case N+1.
Versions
Every session stores code, config, Law DB, precedent DB and memory snapshot versions.
I3. Remaining loopholes and their fixes
#
Loophole
Fix
1
The original blueprint lets THEMIS-GLOBAL read ground truth, and its report goes to the judges
Split it: THEMIS-GLOBAL audits before the verdict with no ground-truth access; a separate evaluator reads ground truth after the verdict
2
The same dispute can recur across years (a CIRP case, then a liquidation case of the same corporate debtor), putting one in train and one in test
Group cases by corporate debtor or dispute; a whole group goes into one split
3
Agents can cite sections inserted after the case date
Add overlay rows for when each section was inserted or omitted; get_statute(id, as_of) hides sections not in force
4
Lessons are pinned by weight alone, so irrelevant ones fill the prompt
Filter lessons by the case's statutes and party status first, then rank by weight
5
Reflection can store base-rate lessons ("creditors usually win Section 7") that bias later cases
Reject any lesson that does not state a legal rule, a tactic or a procedural error; judge memory takes LEGAL_RULE lessons only
6
Judges and reflection can hallucinate law while scoring or writing lessons
Give both read-only tools (get_statute, get_precedent, get_record_item). Every reason and lesson must cite record, statute or precedent IDs, and the validator checks each ID exists and is allowed by date and exclusion
7
THEMIS on the same model as the lawyers can rubber-stamp their errors
Run THEMIS layer 2 and the entailment check on a different model family from the lawyers, set in config
8
Clerk extraction errors silently corrupt everything downstream
Every stipulated fact and exhibit content needs source_paras; an automatic entailment check against those paragraphs, two-model agreement, and your check against the judgment
9
Reusing the same pseudonym for an entity across cases lets memory learn about that entity
Generate fresh pseudonyms per case; lessons containing any pseudonym are rejected
10
Running training cases in parallel breaks the one-by-one learning order
Run training cases strictly in sequence. If batching is ever needed, every case in a batch reads the same memory snapshot and writes after the batch
11
REFERENCED citations could rely on a precedent decided after the case date
REFERENCED support counts only from precedents inside the case's cut-off and outside its exclusion list
12
Without a lawyer, open interpretations might be encoded as fixed Z3 rules
A predicate is closed only when the statute text fixes it literally; everything else is an open parameter (D2)
13
Recalibrating thresholds as the precedent DB grows would change behaviour mid-run
Recalibrate only between runs, under a new config version
14
Lawyers could learn to satisfy THEMIS rather than argue well
THEMIS gates only provable errors (D8); advocacy quality is judged separately, and lessons from warnings carry low severity
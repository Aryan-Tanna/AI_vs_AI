"""Clerk-review viewer (D-056, S-007, R-003). Start it with:

    .venv/Scripts/streamlit run lexarena/ui/app.py

It runs as the REVIEW role in a sealed process: it reads a clerked case, its sealed ground truth and the judgment text,
and only while the case has no session (after that the repository refuses and the page says so). Each item is shown
beside the judgment text it rests on, with a tick box; ticks go to a local file. Marking the case reviewed is not done
here: when every item is ticked, the page shows the owner's `lexarena clerk approve` command.
"""

from __future__ import annotations

import streamlit as st

from lexarena.app import DEFAULT_ENV_FILE, REPO_ROOT, SEALED_ENV_FILE
from lexarena.storage.errors import NotFoundError, SealedError
from lexarena.storage.factory import SealedProcess
from lexarena.ui.review_model import ReviewPage, build_page
from lexarena.ui.ticks import TickStore

TICKS = TickStore(REPO_ROOT / "reports" / "review")
COLUMN_WIDTHS = [3, 2]  # literal-ok: page layout, item text beside the tick box


@st.cache_resource
def _process() -> SealedProcess:
    return SealedProcess.from_env_files([DEFAULT_ENV_FILE, SEALED_ENV_FILE])


def _load(case_id: str) -> ReviewPage:
    stores = _process().review()
    case = stores.cases.get(case_id)
    truth = stores.ground_truth.get_for_review(case_id)
    judgment = stores.judgment_texts.get_for_review(case_id)
    return build_page(case, truth, judgment)


def main() -> None:
    st.set_page_config(page_title="Clerk review", layout="wide")
    st.title("Clerk review")
    stores = _process().review()
    cases = sorted(c for c, _, _ in stores.cases.index())
    if not cases:
        st.info("No clerked cases. Run `lexarena clerk run --file ... --case-id ...` first.")
        return
    case_id = st.sidebar.selectbox("Case", cases)
    reviewer = st.sidebar.text_input("Reviewer", value="")
    try:
        page = _load(case_id)
    except SealedError as exc:
        st.warning(f"Review window closed: {exc}")
        return
    except NotFoundError as exc:
        st.error(f"Incomplete clerk output: {exc}")
        return
    ticks = TICKS.load(case_id)
    ids = [i.item_id for i in page.items]
    ticked = sum(1 for i in ids if i in ticks.ticks and ticks.ticks[i].ok)
    st.caption(f"{page.source_file} | {ticked} of {len(ids)} items ticked | human_reviewed: {page.human_reviewed}")
    st.progress(ticked / len(ids) if ids else 0.0)
    if page.flags:
        with st.expander(f"Clerk flags ({len(page.flags)})", expanded=True):
            for flag in page.flags:
                st.markdown(f"- {flag}")
    section = st.sidebar.radio("Section", page.sections())
    only_open = st.sidebar.checkbox("Only unticked items")
    for item in (i for i in page.items if i.section == section):
        current = ticks.ticks.get(item.item_id)
        if only_open and current is not None and current.ok:
            continue
        left, right = st.columns(COLUMN_WIDTHS)
        with left:
            st.markdown(f"**{item.title}**")
            for line in item.lines:
                st.write(line)
            for src in item.sources:
                where = f"page {src.page}, {src.part or 'unrouted'}" if src.found else "missing"
                st.markdown(f"> **{src.source_id}** ({where}): {src.text}")
        with right:
            note = st.text_input("Note", value=(current.note or "") if current else "", key=f"note:{item.item_id}")
            ok = st.checkbox("Matches the judgment", value=bool(current and current.ok), key=f"ok:{item.item_id}")
            if ok != bool(current and current.ok) or (current and note != (current.note or "")):
                if not reviewer.strip():
                    st.error("Enter your name in the sidebar before ticking.")
                else:
                    TICKS.set(case_id, item.item_id, ok=ok, by=reviewer.strip(), note=note)
        st.divider()
    if ticks.done(ids):
        st.success("Every item is ticked. To mark the case reviewed, run:")
        st.code(f".venv/Scripts/lexarena clerk approve {case_id} --by {reviewer.strip() or 'NAME'}")


main()

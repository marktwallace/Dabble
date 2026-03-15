import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from .. import conversation_file as conv_file

NOTEBOOKS_DIR = os.environ.get("NOTEBOOKS_DIR", "notebooks")
INITIAL_SHOW = 5


def render():
    st.title("Generate notebook")

    if st.button("← Back to conversation"):
        st.session_state.pop("notebook_draft", None)
        st.session_state.notebook_show_all = False
        st.session_state.page = "conversation"
        st.rerun()

    draft = st.session_state.get("notebook_draft")

    if draft is None:
        _render_selection()
    else:
        _render_preview(draft)


# ---------------------------------------------------------------------------
# Selection phase
# ---------------------------------------------------------------------------

def _render_selection():
    options = _build_options()

    if not options:
        st.info("No charts or dataframes available in this conversation.")
        return

    show_all = st.session_state.get("notebook_show_all", False)
    visible = options if show_all else options[:INITIAL_SHOW]

    st.caption("Select artifacts to include in the notebook.")

    for i, (typ, k, data) in enumerate(visible):
        label = f"Chart: {k}" if typ == "chart" else f"Table: {k} ({len(data)} rows)"
        st.checkbox(label, value=(i == 0), key=f"notebook_cb_{typ}_{k}")

    if not show_all and len(options) > INITIAL_SHOW:
        if st.button(f"Show all {len(options)} options"):
            st.session_state.notebook_show_all = True
            st.rerun()

    st.divider()

    selected = [
        (typ, k, data)
        for typ, k, data in visible
        if st.session_state.get(f"notebook_cb_{typ}_{k}", False)
    ]

    if not selected:
        st.warning("Select at least one item above.")
        return

    if st.button("Generate notebook", type="primary"):
        selected_ids = [k for _, k, _ in selected]
        conversation_path = st.session_state.get("conversation_path", "")
        conversation_text = conv_file.read_text(conversation_path) if conversation_path else ""

        with st.spinner("Generating notebook..."):
            draft = st.session_state.handler.generate_notebook(conversation_text, selected_ids)

        if "error" in draft:
            st.error(f"Generation failed: {draft['error']}")
            return

        st.session_state.notebook_draft = draft
        st.rerun()


# ---------------------------------------------------------------------------
# Preview phase
# ---------------------------------------------------------------------------

def _render_preview(draft):
    title = draft.get("title", "Notebook")
    code = draft.get("code", "")

    st.subheader(title)

    with st.expander("View generated code"):
        st.code(code, language="python")

    st.divider()

    if st.button("Save notebook", type="primary"):
        path = _save(code, title)
        st.success(f"Saved: `{path}`")
        db_path = os.environ.get("DUCKDB_ANALYTIC_FILE", "")
        prefix = f"DUCKDB_ANALYTIC_FILE={db_path} " if db_path else ""
        st.code(f"{prefix}marimo edit {path}", language="bash")

    if st.button("Start over"):
        st.session_state.pop("notebook_draft", None)
        st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save(code, title):
    Path(NOTEBOOKS_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M")
    slug = title.lower().replace(" ", "_")[:40]
    path = Path(NOTEBOOKS_DIR) / f"notebook_{timestamp}_{slug}.py"
    path.write_text(code, encoding="utf-8")
    return str(path)


def _build_options():
    """Return (type, key, data) tuples in reverse chronological order."""
    figures = st.session_state.get("figures", {})
    dataframes = st.session_state.get("dataframes", {})
    artifact_order = st.session_state.get("artifact_order", [])

    seen = set()
    options = []
    for typ, key in reversed(artifact_order):
        if (typ, key) in seen:
            continue
        seen.add((typ, key))
        if typ == "chart":
            v = figures.get(key, {})
            if "figure" in v:
                options.append(("chart", key, v))
        else:
            df = dataframes.get(key)
            if df is not None:
                options.append(("table", key, df))
    return options

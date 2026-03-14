import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from .. import conversation_file as conv_file

NOTEBOOKS_DIR = os.environ.get("NOTEBOOKS_DIR", "notebooks")


def render():
    st.title("Generate notebook")

    if st.button("← Back to conversation"):
        st.session_state.pop("notebook_draft", None)
        st.session_state.page = "conversation"
        st.rerun()

    draft = st.session_state.get("notebook_draft")

    if draft is None:
        _render_generate()
    else:
        _render_preview(draft)


def _render_generate():
    st.caption("Generate a Marimo notebook from this conversation.")

    if st.button("Generate notebook", type="primary"):
        conversation_path = st.session_state.get("conversation_path", "")
        conversation_text = conv_file.read_text(conversation_path) if conversation_path else ""

        with st.spinner("Generating notebook..."):
            draft = st.session_state.handler.generate_notebook(conversation_text)

        if "error" in draft:
            st.error(f"Generation failed: {draft['error']}")
            return

        st.session_state.notebook_draft = draft
        st.rerun()


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


def _save(code, title):
    Path(NOTEBOOKS_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M")
    slug = title.lower().replace(" ", "_")[:40]
    path = Path(NOTEBOOKS_DIR) / f"notebook_{timestamp}_{slug}.py"
    path.write_text(code, encoding="utf-8")
    return str(path)

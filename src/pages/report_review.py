import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from .. import conversation_file as conv_file

REPORTS_DIR = os.environ.get("REPORTS_DIR", "reports")
INITIAL_SHOW = 5


def render():
    st.title("Generate report")

    if st.button("← Back to conversation"):
        st.session_state.pop("report_draft", None)
        st.session_state.report_show_all = False
        st.session_state.page = "conversation"
        st.rerun()

    draft = st.session_state.get("report_draft")

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

    show_all = st.session_state.get("report_show_all", False)
    visible = options if show_all else options[:INITIAL_SHOW]

    st.caption("Select items to include in the report.")

    for i, (typ, k, data) in enumerate(visible):
        label = f"Chart: {k}" if typ == "chart" else f"Table: {k} ({len(data)} rows)"
        st.checkbox(label, value=(i == 0), key=f"report_cb_{typ}_{k}")

    if not show_all and len(options) > INITIAL_SHOW:
        if st.button(f"Show all {len(options)} options"):
            st.session_state.report_show_all = True
            st.rerun()

    st.divider()

    selected = [
        (typ, k, data)
        for typ, k, data in visible
        if st.session_state.get(f"report_cb_{typ}_{k}", False)
    ]

    if not selected:
        st.warning("Select at least one item above.")
        return

    if st.button("Generate report", type="primary"):
        handler = st.session_state.handler
        conversation_path = st.session_state.get("conversation_path", "")

        selected_items = []
        for typ, key, data in selected:
            if typ == "chart":
                selected_items.append({
                    "type": "chart",
                    "id": key,
                    "chart_code": data.get("code", ""),
                })
            else:
                selected_items.append({"type": "table", "id": key})

        with st.spinner("Generating report..."):
            conversation_text = conv_file.read_text(conversation_path) if conversation_path else ""
            draft = handler.generate_report(conversation_text, selected_items)

        if "error" in draft:
            st.error(f"Generation failed: {draft['error']}")
            return

        st.session_state.report_draft = draft
        st.rerun()


# ---------------------------------------------------------------------------
# Preview phase
# ---------------------------------------------------------------------------

def _render_preview(draft):
    summary = draft.get("summary", {})
    code = draft.get("code", "")

    st.subheader(summary.get("title", "Report"))

    q_count = summary.get("query_count", 0)
    c_count = summary.get("chart_count", 0)
    st.caption(f"{q_count} {'query' if q_count == 1 else 'queries'} · {c_count} {'chart' if c_count == 1 else 'charts'}")

    params = summary.get("parameters", [])
    if params:
        st.caption("Uncheck any parameter to hardcode it at its default value.")
        for p in params:
            default_str = p.get("default", "")
            label = f"`{p['name']}` — {p.get('description', '')}"
            if default_str:
                label += f"  *(default: `{default_str}`)*"
            st.checkbox(label, value=True, key=f"report_param_{p['name']}")
    else:
        st.write("No parameters — report will re-query with fixed logic.")

    with st.expander("View generated code"):
        st.code(code, language="python")

    st.divider()

    if st.button("Save report", type="primary"):
        hardcoded = [
            p for p in params
            if not st.session_state.get(f"report_param_{p['name']}", True)
        ]
        final_code = code
        if hardcoded:
            with st.spinner("Finalizing..."):
                final_code = st.session_state.handler.finalize_report(code, hardcoded)
        path = _save(final_code, summary)
        st.success(f"Saved: `{path}`")
        db_path = os.environ.get("DUCKDB_ANALYTIC_FILE", "")
        prefix = f"DUCKDB_ANALYTIC_FILE={db_path} " if db_path else ""
        st.code(f"{prefix}streamlit run {path}", language="bash")

    if st.button("Start over"):
        st.session_state.pop("report_draft", None)
        st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save(code, summary):
    Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M")
    title = summary.get("title", "report").lower().replace(" ", "_")[:40]
    path = Path(REPORTS_DIR) / f"report_{timestamp}_{title}.py"
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

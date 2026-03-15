import copy
import os
from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

REPORTS_DIR = os.environ.get("REPORTS_DIR", "reports")
INITIAL_SHOW = 5


def render():
    st.title("Generate snapshot")

    if st.button("← Back to conversation"):
        st.session_state.snapshot_show_all = False
        st.session_state.page = "conversation"
        st.rerun()

    options = _build_options()

    if not options:
        st.info("No charts or dataframes available in this conversation.")
        return

    show_all = st.session_state.get("snapshot_show_all", False)
    visible = options if show_all else options[:INITIAL_SHOW]

    st.caption("Select one or more items to include in the snapshot.")

    for i, (typ, k, data) in enumerate(visible):
        label = f"Chart: {k}" if typ == "chart" else f"Table: {k} ({len(data)} rows)"
        st.checkbox(label, value=(i == 0), key=f"snapshot_cb_{typ}_{k}")

    if not show_all and len(options) > INITIAL_SHOW:
        if st.button(f"Show all {len(options)} options"):
            st.session_state.snapshot_show_all = True
            st.rerun()

    st.divider()

    selected = [
        (typ, k, data)
        for typ, k, data in visible
        if st.session_state.get(f"snapshot_cb_{typ}_{k}", False)
    ]

    if not selected:
        st.warning("Select at least one item above.")
        return

    if st.button("Generate snapshot", type="primary"):
        path = _generate(selected)
        st.success(f"Saved: `{path}`")
        html_bytes = Path(path).read_bytes()
        st.download_button(
            "Download HTML",
            data=html_bytes,
            file_name=Path(path).name,
            mime="text/html",
            key="dl_snap_generated",
        )


# ---------------------------------------------------------------------------
# Option building
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _generate(selected):
    Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M")
    first_key = selected[0][1]
    slug = first_key.replace(" ", "_").lower()[:40]
    path = Path(REPORTS_DIR) / f"snapshot_{timestamp}_{slug}.html"

    title_parts = [_title(k) for _, k, _ in selected[:2]]
    title = " & ".join(title_parts)
    if len(selected) > 2:
        title += f" (+{len(selected) - 2} more)"

    path.write_text(_build_html(selected, title), encoding="utf-8")
    return str(path)


def _title(key):
    return key.replace("_", " ").title()


def _fig_div(fig, include_plotlyjs=False):
    # Use Plotly's own to_html() — the only path that correctly handles its
    # internal numpy binary serialisation (dtype/bdata). Strip the Streamlit
    # template first so colours render correctly in a plain browser context.
    # include_plotlyjs='cdn' on the first figure injects the exact versioned
    # Plotly.js that matches this Python package, which can decode bdata.
    f = copy.deepcopy(fig)
    f.update_layout(template="plotly", plot_bgcolor="white", paper_bgcolor="white",
                    title=None)
    return f.to_html(full_html=False, include_plotlyjs=include_plotlyjs)


def _table_fig(df):
    fig = go.Figure(go.Table(
        header=dict(values=list(df.columns), align="left",
                    fill_color="#f0f2f6", font=dict(size=13)),
        cells=dict(values=[df[c].tolist() for c in df.columns], align="left",
                   font=dict(size=12)),
    ))
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    return fig


def _build_html(selected, title):
    multi = len(selected) > 1
    sections = []
    for i, (typ, key, data) in enumerate(selected):
        fig = data["figure"] if typ == "chart" else _table_fig(data)
        # 'cdn' on the first figure injects the versioned Plotly.js script;
        # subsequent figures reuse it with include_plotlyjs=False.
        div = _fig_div(fig, include_plotlyjs="cdn" if i == 0 else False)
        header = f"<h2>{_title(key)}</h2>\n" if multi else ""
        sections.append(f"{header}{div}")

    body = "\n<hr>\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: sans-serif; max-width: 1200px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 1.5rem; }}
  h2 {{ font-size: 1.0rem; margin-top: 2rem; color: #555; }}
  hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 2rem 0; }}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>"""

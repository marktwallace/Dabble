import os
from datetime import datetime
from pathlib import Path

import streamlit as st

REPORTS_DIR = os.environ.get("REPORTS_DIR", "reports")
INITIAL_SHOW = 5


def render():
    st.title("Generate report")

    if st.button("← Back to conversation"):
        st.session_state.report_show_all = False
        st.session_state.page = "conversation"
        st.rerun()

    options = _build_options()

    if not options:
        st.info("No charts or dataframes available in this conversation.")
        return

    show_all = st.session_state.get("report_show_all", False)
    visible = options if show_all else options[:INITIAL_SHOW]

    st.caption("Select one or more items to include in the report.")

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
        path = _generate(selected)
        st.success(f"Saved: `{path}`")
        st.code(f"streamlit run {path}", language="bash")


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
    slug = first_key.replace(" ", "_").lower()
    filename = f"{timestamp}_{slug}.py"
    path = Path(REPORTS_DIR) / filename

    if len(selected) == 1:
        typ, key, data = selected[0]
        if typ == "chart":
            df_id = data.get("dataframe_id", key)
            df = st.session_state.dataframes.get(df_id)
            content = _chart_report(df, data.get("code", ""), key)
        else:
            content = _table_report(data, key)
    else:
        content = _multi_report(selected)

    path.write_text(content, encoding="utf-8")
    return str(path)


def _title(key):
    return key.replace("_", " ").title()


def _chart_report(df, plotly_code, key):
    title = _title(key)
    csv_data = df.to_csv(index=False)
    return f'''import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="{title}", layout="wide")
st.title("{title}")

DATA = """{csv_data}"""

df = pd.read_csv(io.StringIO(DATA))

{plotly_code}

st.plotly_chart(fig, width="stretch")
'''


def _table_report(df, key):
    title = _title(key)
    csv_data = df.to_csv(index=False)
    return f'''import io

import pandas as pd
import streamlit as st

st.set_page_config(page_title="{title}", layout="wide")
st.title("{title}")

DATA = """{csv_data}"""

df = pd.read_csv(io.StringIO(DATA))

st.dataframe(df, width="stretch")
'''


def _multi_report(selected):
    title_parts = [_title(k) for _, k, _ in selected[:2]]
    title = " & ".join(title_parts)
    if len(selected) > 2:
        title += f" (+{len(selected) - 2} more)"

    header = f'''import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="{title}", layout="wide")
st.title("{title}")
'''

    sections = []
    for i, (typ, key, data) in enumerate(selected):
        section_title = _title(key)
        if i > 0:
            sections.append("st.divider()\n")

        if typ == "chart":
            df_id = data.get("dataframe_id", key)
            df = st.session_state.dataframes.get(df_id)
            csv_data = df.to_csv(index=False)
            code = data.get("code", "")
            sections.append(f'''st.subheader("{section_title}")

DATA = """{csv_data}"""

df = pd.read_csv(io.StringIO(DATA))

{code}

st.plotly_chart(fig, width="stretch")
''')
        else:
            csv_data = data.to_csv(index=False)
            sections.append(f'''st.subheader("{section_title}")

DATA = """{csv_data}"""

df = pd.read_csv(io.StringIO(DATA))

st.dataframe(df, width="stretch")
''')

    return header + "\n" + "\n".join(sections)

import os
from datetime import datetime
from pathlib import Path

import streamlit as st

REPORTS_DIR = os.environ.get("REPORTS_DIR", "reports")


def render():
    st.title("Generate report")

    if st.button("← Back to conversation"):
        st.session_state.page = "conversation"
        st.rerun()

    figures = st.session_state.get("figures", {})
    dataframes = st.session_state.get("dataframes", {})

    # Build options: charts first (most recent first), then dataframes
    chart_options = [
        ("chart", k, v)
        for k, v in reversed(list(figures.items()))
        if "figure" in v
    ]
    df_options = [
        ("table", k, df)
        for k, df in reversed(list(dataframes.items()))
    ]
    options = chart_options + df_options

    if not options:
        st.info("No charts or dataframes available in this conversation.")
        return

    labels = [
        f"Chart: {k}" if typ == "chart" else f"Table: {k} ({len(data)} rows)"
        for typ, k, data in options
    ]

    selected_idx = st.selectbox(
        "Include in report",
        range(len(options)),
        format_func=lambda i: labels[i],
        index=0,
    )

    typ, key, data = options[selected_idx]

    if st.button("Generate report", type="primary"):
        path = _generate(typ, key, data)
        st.success(f"Saved: `{path}`")
        st.code(f"streamlit run {path}", language="bash")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _generate(typ, key, data):
    Path(REPORTS_DIR).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M")
    slug = key.replace(" ", "_").lower()
    filename = f"{timestamp}_{slug}.py"
    path = Path(REPORTS_DIR) / filename

    if typ == "chart":
        df_id = data.get("dataframe_id", key)
        df = st.session_state.dataframes.get(df_id)
        code = data.get("code", "")
        content = _chart_report(df, code, key)
    else:
        content = _table_report(data, key)

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

st.plotly_chart(fig, use_container_width=True)
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

st.dataframe(df, use_container_width=True)
'''

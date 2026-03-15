import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)

from src.duckdb_analytic import DuckDBAnalytic
from src.pages import conversation, entry, learn_review, notebook_review, report_review, snapshot_review


def main():
    st.set_page_config(page_title="Dabble", layout="wide")

    if "analytic_db" not in st.session_state:
        db_path = os.environ.get("DUCKDB_ANALYTIC_FILE")
        if db_path:
            st.session_state.analytic_db = DuckDBAnalytic(db_path)

    if "page" not in st.session_state:
        st.session_state.page = "entry"
    if "messages" not in st.session_state:
        st.session_state.messages = []

    page = st.session_state.page
    if page == "entry":
        entry.render()
    elif page == "conversation":
        conversation.render()
    elif page == "learn_review":
        learn_review.render()
    elif page == "snapshot_review":
        snapshot_review.render()
    elif page == "report_review":
        report_review.render()
    elif page == "notebook_review":
        notebook_review.render()
    else:
        st.session_state.page = "entry"
        st.rerun()


main()

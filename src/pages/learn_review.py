import os
from pathlib import Path

import streamlit as st

from ..knowledge_base import write_chunk

KNOWLEDGE_DIR = os.environ.get("KNOWLEDGE_DIR", "knowledge")


def render():
    st.title("Review knowledge chunks")

    if st.button("← Back to conversation"):
        st.session_state.page = "conversation"
        st.rerun()

    chunks = st.session_state.get("learn_chunks", [])
    if not chunks:
        st.info("No knowledge chunks were extracted from this conversation.")
        return

    st.caption(f"{len(chunks)} chunks extracted. Select the ones worth keeping.")
    st.divider()

    selections = []
    for i, chunk in enumerate(chunks):
        checked = st.checkbox(chunk["description"], key=f"chunk_{i}", value=True)
        with st.expander("Full content"):
            st.text(chunk["content"])
        selections.append((checked, chunk))

    st.divider()

    approved = [chunk for checked, chunk in selections if checked]
    if st.button(
        f"Save {len(approved)} chunk{'s' if len(approved) != 1 else ''}",
        type="primary",
    ):
        _save(approved)
        st.session_state.page = "conversation"
        st.rerun()


def _save(chunks):
    for chunk in chunks:
        write_chunk(chunk["description"], chunk["content"], KNOWLEDGE_DIR)

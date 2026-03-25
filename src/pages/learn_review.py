import os
from pathlib import Path

import streamlit as st

from ..knowledge_base import add_chunk, remove_chunks_by_source

KNOWLEDGE_DIR = os.environ.get("KNOWLEDGE_DIR", "knowledge")
KB_PATH = os.environ.get("KB_PATH")
CHUNK_SEPARATOR = "\n---\n"


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
    source_path = st.session_state.get("learn_source_path", "")
    stem = Path(source_path).stem if source_path else ""
    stem = stem or "manual"
    out_path = Path(KNOWLEDGE_DIR) / f"{stem}.txt"

    chunk_texts = [f"description: {c['description']}\n{c['content']}" for c in chunks]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(CHUNK_SEPARATOR.join(chunk_texts), encoding="utf-8")

    if KB_PATH:
        remove_chunks_by_source(out_path.name, KB_PATH)
        for text in chunk_texts:
            add_chunk(text, {"source_file": out_path.name}, KB_PATH)

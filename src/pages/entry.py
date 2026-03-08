import os

import streamlit as st

from ..conversation_file import list_conversations, new_path

CONVERSATIONS_DIR = os.environ.get("CONVERSATIONS_DIR", "conversations")


def render():
    st.title("list-pet")

    if st.button("New conversation", type="primary"):
        st.session_state.conversation_path = new_path(CONVERSATIONS_DIR)
        st.session_state.messages = []
        st.session_state.page = "conversation"
        st.rerun()

    st.divider()

    conversations = list_conversations(CONVERSATIONS_DIR)
    if not conversations:
        st.caption("No conversations yet.")
        return

    for conv in conversations:
        title = conv["title"] or conv["filename"]
        date_display = _parse_date(conv["filename"])
        label = f"{title}  \n*{date_display}*"
        if st.button(label, key=conv["filename"], use_container_width=True):
            st.session_state.conversation_path = conv["path"]
            st.session_state.messages = []
            st.session_state.page = "conversation"
            st.rerun()


def _parse_date(filename: str) -> str:
    """Turn '2026-03-07T14-32.txt' into '2026-03-07 14:32'."""
    stem = filename.replace(".txt", "")
    if "T" in stem:
        date_part, time_part = stem.split("T", 1)
        time_display = time_part.replace("-", ":", 1)
        return f"{date_part} {time_display}"
    return stem

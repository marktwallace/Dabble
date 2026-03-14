import os
from pathlib import Path

import streamlit as st

from ..conversation_file import list_conversations, new_path

CONVERSATIONS_DIR = os.environ.get("CONVERSATIONS_DIR", "conversations")
REPORTS_DIR = os.environ.get("REPORTS_DIR", "reports")


def render():
    st.title("list-pet")

    if st.button("New conversation", type="primary"):
        st.session_state.conversation_path = new_path(CONVERSATIONS_DIR)
        st.session_state.page = "conversation"
        st.rerun()

    st.divider()

    conversations = list_conversations(CONVERSATIONS_DIR)
    if not conversations:
        st.caption("No conversations yet.")
        return

    labels = [
        f"{_parse_date(c['filename'])}  —  {c['title'] or c['filename']}"
        for c in conversations
    ]
    paths = [c["path"] for c in conversations]

    def _open_selected():
        idx = labels.index(st.session_state.conv_list)
        st.session_state.conversation_path = paths[idx]
        st.session_state.page = "conversation"

    st.radio("Conversations", labels, index=None, key="conv_list", label_visibility="collapsed", on_change=_open_selected)

    reports = _list_by_prefix("report")
    if reports:
        st.divider()
        st.subheader("Reports")
        for r in reports:
            with st.expander(f"{r['date']}  —  {r['title']}"):
                st.code(f"streamlit run {r['path']}", language="bash")

    snapshots = _list_by_prefix("snapshot")
    if snapshots:
        st.divider()
        st.subheader("Snapshots")
        for r in snapshots:
            with st.expander(f"{r['date']}  —  {r['title']}"):
                st.code(f"streamlit run {r['path']}", language="bash")


def _list_by_prefix(prefix: str) -> list[dict]:
    reports_dir = Path(REPORTS_DIR)
    if not reports_dir.exists():
        return []
    files = sorted(
        reports_dir.glob(f"{prefix}_*.py"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result = []
    for f in files:
        without_prefix = f.stem[len(prefix) + 1:]  # e.g. "2026-03-08T14-30_tracks_by_length"
        parts = without_prefix.split("_", 1)
        if len(parts) == 2:
            date_display = _parse_date(parts[0] + ".txt")
            title = parts[1].replace("_", " ").title()
        else:
            date_display = ""
            title = without_prefix
        result.append({"path": str(f), "title": title, "date": date_display})
    return result


def _parse_date(filename: str) -> str:
    """Turn '2026-03-07T14-32.txt' into '2026-03-07 14:32'."""
    stem = filename.replace(".txt", "")
    if "T" in stem:
        date_part, time_part = stem.split("T", 1)
        time_display = time_part.replace("-", ":", 1)
        return f"{date_part} {time_display}"
    return stem

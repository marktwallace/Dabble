import os
from pathlib import Path

import streamlit as st

from .. import conversation_file as conv_file
from ..claude_handler import ClaudeHandler

PROMPTS_DIR = os.environ.get("PROMPTS_DIR", "prompts")
KB_PATH = os.environ.get("KB_PATH")


def render():
    _init_session()

    if st.button("← Conversations"):
        st.session_state.page = "entry"
        st.rerun()

    turns = st.session_state.turns
    n = len(turns)
    for i, turn in enumerate(turns):
        if turn["role"] == "user":
            with st.chat_message("user"):
                st.markdown(turn["text"])
        else:
            with st.chat_message("assistant"):
                _render_assistant_turn(turn, is_latest=(i == n - 1))

    if st.session_state.get("pending_input"):
        _run_agent(st.session_state.pending_input)
        st.session_state.pending_input = None
        st.rerun()

    user_input = st.chat_input("Ask anything...")
    if user_input:
        _enqueue_input(user_input.strip())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init_session():
    path = st.session_state.get("conversation_path")
    if st.session_state.get("_active_path") != path:
        st.session_state._active_path = path
        st.session_state.dataframes = {}
        st.session_state.figures = {}
        st.session_state.tables_to_show = []
        st.session_state.turns = []

    if "handler" not in st.session_state:
        prompt_path = Path(PROMPTS_DIR) / "system_prompt.txt"
        system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        st.session_state.handler = ClaudeHandler(system_prompt, KB_PATH)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def _enqueue_input(text):
    if text == "/learn":
        _handle_learn()
        return
    if text == "/report":
        _handle_report()
        return

    path = st.session_state.conversation_path
    st.session_state.turns.append({"role": "user", "text": text})
    st.session_state.messages.append({"role": "user", "content": text})
    conv_file.append_user(path, text)
    st.session_state.pending_input = text
    st.rerun()


def _run_agent(text):
    path = st.session_state.conversation_path
    handler = st.session_state.handler
    is_first = len(st.session_state.turns) == 1  # only the user turn just added

    prev_len = len(st.session_state.messages)
    st.session_state.tables_to_show = []

    with st.spinner("working..."):
        messages, _response = handler.run_tool_loop(st.session_state.messages)

    st.session_state.messages = messages
    new_messages = messages[prev_len:]

    if is_first:
        title = handler.generate_title(text)
        conv_file.write_title(path, title)

    _write_new_messages(path, new_messages)

    for turn in _extract_assistant_turns(new_messages):
        st.session_state.turns.append(turn)


def _handle_learn():
    path = st.session_state.conversation_path
    with st.spinner("Extracting knowledge chunks..."):
        text = conv_file.read_text(path)
        chunks = st.session_state.handler.extract_learn_chunks(text)
    st.session_state.learn_chunks = chunks
    st.session_state.learn_source_path = path
    st.session_state.page = "learn_review"
    st.rerun()


def _handle_report():
    st.session_state.page = "report_review"
    st.rerun()


# ---------------------------------------------------------------------------
# File persistence
# ---------------------------------------------------------------------------

def _write_new_messages(path, new_messages):
    i = 0
    while i < len(new_messages):
        msg = new_messages[i]
        if msg["role"] == "assistant":
            tool_results = []
            if (
                i + 1 < len(new_messages)
                and new_messages[i + 1]["role"] == "user"
                and isinstance(new_messages[i + 1]["content"], list)
                and any(b.get("type") == "tool_result" for b in new_messages[i + 1]["content"])
            ):
                tool_results = new_messages[i + 1]["content"]
                i += 1
            conv_file.append_assistant_turn(path, msg["content"], tool_results)
        i += 1


# ---------------------------------------------------------------------------
# Turn extraction (messages → display dicts)
# ---------------------------------------------------------------------------

def _extract_assistant_turns(new_messages):
    turns = []
    i = 0
    while i < len(new_messages):
        msg = new_messages[i]
        if msg["role"] != "assistant":
            i += 1
            continue

        result_map = {}
        if (
            i + 1 < len(new_messages)
            and new_messages[i + 1]["role"] == "user"
            and isinstance(new_messages[i + 1]["content"], list)
        ):
            for b in new_messages[i + 1]["content"]:
                if b.get("type") == "tool_result":
                    result_map[b["tool_use_id"]] = b["content"]
            i += 2
        else:
            i += 1

        tool_calls = []
        text_parts = []
        for block in msg["content"]:
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "name": block["name"],
                    "inputs": block["input"],
                    "result": result_map.get(block["id"], ""),
                })

        turns.append({
            "role": "assistant",
            "tool_calls": tool_calls,
            "text": "\n".join(text_parts).strip(),
        })
    return turns


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_assistant_turn(turn, is_latest):
    for tc in turn["tool_calls"]:
        with st.expander(_expander_label(tc["name"], tc["inputs"]), expanded=is_latest):
            name = tc["name"]
            if name == "run_sql":
                st.code(tc["inputs"].get("sql", ""), language="sql")
            elif name in ("render_chart", "run_python"):
                st.code(tc["inputs"].get("code", ""), language="python")
            if tc["result"]:
                st.text(tc["result"])

    for tc in turn["tool_calls"]:
        if tc["name"] == "show_table":
            df = st.session_state.dataframes.get(tc["inputs"].get("dataframe_id"))
            if df is not None:
                st.dataframe(df, use_container_width=True)

    for tc in turn["tool_calls"]:
        if tc["name"] == "render_chart":
            key = tc["inputs"].get("chart_id") or tc["inputs"].get("dataframe_id")
            fig_data = st.session_state.figures.get(key)
            if fig_data and "figure" in fig_data:
                st.plotly_chart(fig_data["figure"], use_container_width=True)

    if turn["text"]:
        st.markdown(turn["text"])


def _expander_label(name, inputs):
    if name == "run_sql":
        df_id = inputs.get("dataframe_id", "")
        df = st.session_state.dataframes.get(df_id)
        rows = f" — {len(df)} rows" if df is not None else ""
        return f"SQL: {df_id}{rows}"
    if name == "render_chart":
        return f"Chart: {inputs.get('chart_id') or inputs.get('dataframe_id', '')}"
    if name == "show_table":
        df_id = inputs.get("dataframe_id", "")
        df = st.session_state.dataframes.get(df_id)
        rows = f" — {len(df)} rows" if df is not None else ""
        return f"Table: {df_id}{rows}"
    if name == "run_python":
        return f"Python → {inputs.get('output_dataframe_id', '')}"
    if name == "search_knowledge_base":
        return f"Search: {inputs.get('query', '')[:50]}"
    return name

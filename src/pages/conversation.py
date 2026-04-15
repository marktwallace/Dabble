import base64
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
import streamlit as st

from .. import conversation_file as conv_file
from ..claude_handler import ClaudeHandler
from ..knowledge_base import list_registry

PROMPTS_DIR = os.environ.get("PROMPTS_DIR", "prompts")
KNOWLEDGE_DIR = os.environ.get("KNOWLEDGE_DIR", "knowledge")
UPLOADS_DIR = os.environ.get("UPLOADS_DIR", "uploads")


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
                for img in turn.get("images", []):
                    st.image(base64.b64decode(img["data"]))
                if turn.get("file"):
                    st.caption(f"📄 {turn['file']['name']}")
                st.markdown(turn["text"])
        else:
            with st.chat_message("assistant"):
                _render_assistant_turn(turn, turn_idx=i, is_latest=(i == n - 1))

    if st.session_state.get("pending_input"):
        _run_agent(st.session_state.pending_input)
        st.session_state.pending_input = None
        st.rerun()

    uploader_key = f"uploader_{st.session_state.upload_counter}"
    with st.popover("📎"):
        st.file_uploader(
            "Attach file",
            type=[
                "png", "jpg", "jpeg", "gif", "webp",
                "txt", "md", "py", "js", "ts", "jsx", "tsx",
                "sql", "json", "jsonl", "yaml", "yml", "toml", "xml",
                "html", "css", "sh", "r", "go", "rs", "java",
                "scala", "rb", "csv", "tsv", "parquet", "xlsx", "xls",
            ],
            key=uploader_key,
            label_visibility="collapsed",
        )
    user_input = st.chat_input("Ask a question, or type / for commands...")

    if user_input:
        attachment = None
        uploaded = st.session_state.get(uploader_key)
        if uploaded is not None:
            raw = uploaded.read()
            if uploaded.type.startswith("image/"):
                attachment = {
                    "kind": "image",
                    "data": base64.b64encode(raw).decode("utf-8"),
                    "media_type": uploaded.type,
                    "name": uploaded.name,
                }
            else:
                attachment = _save_upload(raw, uploaded.name)
            st.session_state.upload_counter += 1
        _enqueue_input(user_input.strip(), attachment)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _replay_tool_calls(messages: list[dict], handler) -> None:
    """Re-execute artifact-producing tool calls to restore session state on load."""
    for msg in messages:
        if msg["role"] != "assistant":
            continue
        for block in msg["content"]:
            if block.get("type") == "tool_use" and block["name"] in ("run_sql", "run_python", "render_chart", "save_file", "show_table"):
                handler._execute_tool(block["name"], block["input"])


def _build_schema_context() -> str:
    db = st.session_state.get("analytic_db")
    if not db:
        return ""
    tables_df, err = db.execute_query("SHOW TABLES")
    if err or tables_df is None or tables_df.empty:
        return ""
    lines = ["## Current database schema"]
    for table in tables_df["name"]:
        desc_df, desc_err = db.execute_query(f"DESCRIBE \"{table}\"")
        if desc_err or desc_df is None:
            lines.append(f"- {table}")
        else:
            cols = ", ".join(
                f"{row['column_name']} ({row['column_type']})"
                for _, row in desc_df.iterrows()
            )
            lines.append(f"- {table}: {cols}")
    lines.append("""
## Tool execution environment

render_chart namespace: df (the dataframe), go (plotly.graph_objects), px (plotly.express), pd (pandas), np (numpy). Must assign a go.Figure to 'fig'.

run_python namespace: df (the input dataframe), pd (pandas), np (numpy). You can import any installed package. Installed packages: anthropic, chromadb, duckdb, numpy, openai, openpyxl, pandas, plotly, scikit-learn, scipy, streamlit.

To save a dataframe as a downloadable file, use the save_file tool.""")
    return "\n".join(lines)


def _init_session():
    if "upload_counter" not in st.session_state:
        st.session_state.upload_counter = 0

    path = st.session_state.get("conversation_path")
    if st.session_state.get("_active_path") != path:
        st.session_state._active_path = path
        prompt_path = Path(PROMPTS_DIR) / "system_prompt.md"
        system_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        pt = datetime.now(ZoneInfo("America/Los_Angeles"))
        utc = datetime.now(ZoneInfo("UTC"))
        now = (
            f"{pt.strftime('%A, %B %-d, %Y, %-I:%M %p %Z')} (office); "
            f"server is {utc.strftime('%-I:%M %p UTC')}"
        )
        system_prompt = f"Current date and time: {now}\n\n" + system_prompt
        schema = _build_schema_context()
        if schema:
            system_prompt = system_prompt + ("\n\n" if system_prompt else "") + schema
        st.session_state.handler = ClaudeHandler(system_prompt, KNOWLEDGE_DIR)
        st.session_state.dataframes = {}
        st.session_state.figures = {}
        st.session_state.artifact_order = []
        st.session_state.tables_to_show = []
        st.session_state.shown_dataframes = set()
        st.session_state.exported_files = {}
        saved = conv_file.load_messages(path) if path else []
        st.session_state.messages = saved
        st.session_state.turns = _messages_to_turns(saved)
        _replay_tool_calls(saved, st.session_state.handler)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def _save_upload(raw: bytes, name: str) -> dict:
    """Save an uploaded non-image file to UPLOADS_DIR and return an attachment dict."""
    uploads = Path(UPLOADS_DIR)
    uploads.mkdir(parents=True, exist_ok=True)
    conv_stem = Path(st.session_state.conversation_path).stem
    dest = uploads / f"{conv_stem}_{name}"
    dest.write_bytes(raw)
    try:
        content = raw.decode("utf-8")
        is_binary = False
    except UnicodeDecodeError:
        content = None
        is_binary = True
    return {
        "kind": "file",
        "name": name,
        "path": str(dest.resolve()),
        "content": content,
        "size": len(raw),
        "is_binary": is_binary,
    }


def _build_file_message(attachment: dict) -> str:
    """Build the text block sent to Claude describing an uploaded file."""
    name = attachment["name"]
    path = attachment["path"]
    size = attachment["size"]

    if attachment["is_binary"]:
        return f"[File: {name}]\nPath: {path}\nSize: {size // 1024} KB (binary)"

    content = attachment["content"]
    lines = content.splitlines()
    n = len(lines)

    if n <= 200 and len(content) <= 8_000:
        preview = content
    else:
        head = "\n".join(lines[:10])
        tail = "\n".join(lines[-5:])
        preview = f"{head}\n... ({n - 15} lines omitted) ...\n{tail}"

    return f"[File: {name}]\nPath: {path}\n{n} lines\n\n{preview}"


_COMMANDS_HELP = (
    "**Available commands:**\n"
    "- `/learn` — save useful patterns from this conversation to the knowledge base\n"
    "- `/kb` — list what's in the knowledge base\n"
    "- `/refresh` — reload the database (picks up latest ETL run)\n"
    "- `/snapshot` — generate a static shareable chart or table\n"
    "- `/report` — generate a live parameterized Streamlit report\n"
    "- `/notebook` — generate an editable Marimo notebook\n\n"
    "To download data as a CSV, just ask — for example: *\"save the results as a CSV\"*.\n\n"
    "Not sure where to start? Try: *\"Give me an overview of the data.\"*"
)

_KNOWN_COMMANDS = {"/learn", "/kb", "/snapshot", "/report", "/notebook", "/refresh"}


def _enqueue_input(text, attachment=None):
    if text == "/learn":
        _handle_learn(attachment)
        return
    if text.startswith("/kb"):
        _handle_kb()
        return
    if text == "/snapshot":
        _handle_snapshot()
        return
    if text == "/report":
        _handle_report()
        return
    if text == "/notebook":
        _handle_notebook()
        return
    if text == "/refresh":
        _handle_refresh()
        return
    if text.startswith("/") and text.split()[0] not in _KNOWN_COMMANDS:
        st.session_state.turns.append({"role": "user", "text": text, "tool_calls": []})
        st.session_state.turns.append({"role": "assistant", "text": _COMMANDS_HELP, "tool_calls": []})
        st.rerun()
        return

    path = st.session_state.conversation_path

    if attachment and attachment["kind"] == "image":
        image_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": attachment["media_type"],
                "data": attachment["data"],
            },
        }
        api_content = [image_block, {"type": "text", "text": text}]
        turn = {"role": "user", "text": text, "images": [attachment]}
        conv_file.append_user(path, text, image_name=attachment["name"])
    elif attachment and attachment["kind"] == "file":
        file_block = {"type": "text", "text": _build_file_message(attachment)}
        api_content = [file_block, {"type": "text", "text": text}]
        turn = {"role": "user", "text": text, "file": {"name": attachment["name"]}}
        conv_file.append_user(path, text, file_attachment=attachment)
    else:
        api_content = text
        turn = {"role": "user", "text": text}
        conv_file.append_user(path, text)

    st.session_state.turns.append(turn)
    st.session_state.messages.append({"role": "user", "content": api_content})
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
        # Prepend title without losing the user turn already written by append_user
        existing = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        Path(path).write_text(title + "\n" + existing, encoding="utf-8")

    _write_new_messages(path, new_messages)
    conv_file.save_messages(path, messages)

    for turn in _extract_assistant_turns(new_messages):
        st.session_state.turns.append(turn)


def _handle_learn(attachment=None):
    path = st.session_state.conversation_path
    with st.spinner("Extracting knowledge chunks..."):
        if attachment and attachment.get("kind") == "file" and attachment.get("content"):
            chunks = st.session_state.handler.extract_document_chunks(
                attachment["content"], attachment["name"]
            )
        else:
            text = conv_file.read_text_for_learn(path)
            chunks = st.session_state.handler.extract_learn_chunks(text)
    st.session_state.learn_chunks = chunks
    st.session_state.learn_source_path = path
    st.session_state.page = "learn_review"
    st.rerun()


def _handle_kb():
    entries = list_registry(KNOWLEDGE_DIR)
    st.session_state.turns.append({"role": "user", "text": "/kb", "tool_calls": []})
    if entries:
        hint = "_Ask Claude to update, merge, or delete any of these — or ask for a full cleanup pass. Tip: chunks with a shared slug prefix (e.g. `run-joining-*`) sort together alphabetically._"
    else:
        hint = "_Knowledge base is empty. Use /learn after a productive conversation to start building it._"
    st.session_state.turns.append({
        "role": "assistant",
        "text": f"**Knowledge base:** {len(entries)} chunk(s)\n\n{hint}",
        "tool_calls": [],
        "kb_entries": entries,
    })
    st.rerun()


def _handle_refresh():
    db = st.session_state.get("analytic_db")
    st.session_state.turns.append({"role": "user", "text": "/refresh", "tool_calls": []})
    if not db:
        st.session_state.turns.append({
            "role": "assistant",
            "text": "No database connection to refresh.",
            "tool_calls": [],
        })
    elif db.refresh():
        st.session_state.turns.append({
            "role": "assistant",
            "text": f"Database refreshed. Data as of: {db.get_timestamp()}",
            "tool_calls": [],
        })
    else:
        st.session_state.turns.append({
            "role": "assistant",
            "text": "Refresh failed — check logs for details.",
            "tool_calls": [],
        })
    st.rerun()


def _handle_snapshot():
    st.session_state.snapshot_show_all = False
    st.session_state.page = "snapshot_review"
    st.rerun()


def _handle_report():
    st.session_state.pop("report_draft", None)
    st.session_state.report_show_all = False
    st.session_state.page = "report_review"
    st.rerun()


def _handle_notebook():
    st.session_state.pop("notebook_draft", None)
    st.session_state.page = "notebook_review"
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

def _messages_to_turns(messages: list[dict]) -> list[dict]:
    """Rebuild display turns from a full saved messages list (used on load)."""
    turns = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg["role"] == "user":
            content = msg["content"]
            if isinstance(content, str):
                turns.append({"role": "user", "text": content})
            elif isinstance(content, list) and not any(
                b.get("type") == "tool_result" for b in content
            ):
                images = [
                    {"data": b["source"]["data"], "media_type": b["source"].get("media_type", "")}
                    for b in content
                    if b.get("type") == "image" and b.get("source", {}).get("type") == "base64"
                ]
                file_info = None
                text_parts = []
                for b in content:
                    if b.get("type") == "text":
                        t = b.get("text", "")
                        if file_info is None and t.startswith("[File: ") and "]\n" in t:
                            fname = t[7:t.index("]\n")]
                            # Extract saved path if present (Path: line)
                            fpath = None
                            for ln in t.splitlines():
                                if ln.startswith("Path: "):
                                    fpath = ln[6:].strip()
                                    break
                            file_info = {"name": fname, "path": fpath}
                        else:
                            text_parts.append(t)
                text = " ".join(text_parts)
                turn = {"role": "user", "text": text, "images": images}
                if file_info:
                    turn["file"] = file_info
                if text or images or file_info:
                    turns.append(turn)
            i += 1
        elif msg["role"] == "assistant":
            result_map = {}
            if (
                i + 1 < len(messages)
                and messages[i + 1]["role"] == "user"
                and isinstance(messages[i + 1]["content"], list)
            ):
                for b in messages[i + 1]["content"]:
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
        else:
            i += 1
    return turns


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

def _render_assistant_turn(turn, turn_idx, is_latest):

    if "kb_entries" in turn and turn["kb_entries"]:
        df = pd.DataFrame(turn["kb_entries"])[["slug", "description", "date"]]
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "slug": st.column_config.TextColumn("Chunk", width="medium"),
                "description": st.column_config.TextColumn("Description", width="large"),
                "date": st.column_config.TextColumn("Saved", width="small"),
            },
        )

    for tc in turn["tool_calls"]:
        with st.expander(_expander_label(tc["name"], tc["inputs"]), expanded=is_latest):
            name = tc["name"]
            if name == "run_sql":
                st.code(tc["inputs"].get("sql", ""), language="sql")
            elif name in ("render_chart", "run_python"):
                st.code(tc["inputs"].get("code", ""), language="python")
            if tc["result"]:
                st.text(tc["result"])

    for tc_idx, tc in enumerate(turn["tool_calls"]):
        if tc["name"] == "show_table":
            df_id = tc["inputs"].get("dataframe_id")
            df = st.session_state.dataframes.get(df_id)
            if df is not None:
                st.dataframe(df, width="stretch", key=f"table_{turn_idx}_{tc_idx}_{df_id}")

    for tc_idx, tc in enumerate(turn["tool_calls"]):
        if tc["name"] == "render_chart":
            key = tc["inputs"].get("chart_id") or tc["inputs"].get("dataframe_id")
            fig_data = st.session_state.figures.get(key)
            if fig_data and "figure" in fig_data:
                st.plotly_chart(fig_data["figure"], width="stretch", key=f"chart_{turn_idx}_{tc_idx}_{key}")

    for tc_idx, tc in enumerate(turn["tool_calls"]):
        if tc["name"] == "save_file":
            filename = tc["inputs"].get("filename", "")
            fmt = tc["inputs"].get("format", "")
            data = st.session_state.exported_files.get(filename)
            if data is not None:
                mime = {"csv": "text/csv", "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "parquet": "application/octet-stream"}.get(fmt, "application/octet-stream")
                st.download_button(f"Download {filename}", data=data, file_name=filename, mime=mime, key=f"dl_{turn_idx}_{tc_idx}_{filename}")

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
    if name == "save_file":
        return f"Save: {inputs.get('filename', '')}"
    return name

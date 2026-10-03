"""The parts of a conversation turn that do not depend on Streamlit.

Shared by the conversation page and the headless runner (run_turn.py), so both
build the same system prompt, restore state the same way and write the same
files. Moved unchanged from src/pages/conversation.py.
"""

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import conversation_file as conv_file
from . import prompt_files
from .claude_handler import configured_model

REPLAYED_TOOLS = ("run_sql", "run_python", "render_chart", "save_file", "show_table")


def build_system_prompt(prompts_dir: str, db) -> str:
    """Date and model line, INSTANCE_CONTEXT, the overlay's system_prompt.md (includes
    expanded), live schema."""
    prompt_path = Path(prompts_dir) / "system_prompt.md"
    system_prompt = prompt_files.read(prompts_dir, "system_prompt.md") if prompt_path.exists() else ""
    pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    utc = datetime.now(ZoneInfo("UTC"))
    now = (
        f"{pt.strftime('%A, %B %-d, %Y, %-I:%M %p %Z')} (office); "
        f"server is {utc.strftime('%-I:%M %p UTC')}"
    )
    instance_context = os.environ.get("INSTANCE_CONTEXT", "").strip()
    if instance_context:
        system_prompt = instance_context + "\n\n" + system_prompt
    effort = os.environ.get("CLAUDE_EFFORT", "").strip()
    model_line = f"Model: {configured_model()}" + (f", effort {effort}" if effort else "")
    system_prompt = f"Current date and time: {now}\n{model_line}\n\n" + system_prompt
    schema = schema_context(db)
    if schema:
        system_prompt = system_prompt + ("\n\n" if system_prompt else "") + schema
    return system_prompt


def schema_context(db) -> str:
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
    for catalog in getattr(db, "extra_catalogs", []):
        names_df, names_err = db.execute_query(
            f"SELECT table_name FROM duckdb_tables() WHERE database_name = '{catalog}' ORDER BY table_name"
        )
        if names_err or names_df is None or names_df.empty:
            continue
        lines.append(f"\n## Attached catalog `{catalog}` (read-only; query as {catalog}.<table>)")
        for table in names_df["table_name"]:
            desc_df, desc_err = db.execute_query(f"DESCRIBE {catalog}.\"{table}\"")
            if desc_err or desc_df is None:
                lines.append(f"- {catalog}.{table}")
            else:
                cols = ", ".join(
                    f"{row['column_name']} ({row['column_type']})"
                    for _, row in desc_df.iterrows()
                )
                lines.append(f"- {catalog}.{table}: {cols}")
    lines.append("""
## Tool execution environment

render_chart namespace: df (the dataframe), go (plotly.graph_objects), px (plotly.express), pd (pandas), np (numpy). Must assign a go.Figure to 'fig'.

run_python namespace: df (the input dataframe), pd (pandas), np (numpy). You can import any installed package. Installed packages: anthropic, boto3, duckdb, numpy, openpyxl, pandas, plotly, python-dotenv, streamlit.

To save a dataframe as a downloadable file, use the save_file tool.""")
    return "\n".join(lines)


def replay_tool_calls(messages: list[dict], handler) -> None:
    """Re-execute artifact-producing tool calls to restore session state on load."""
    for msg in messages:
        if msg["role"] != "assistant":
            continue
        for block in msg["content"]:
            if block.get("type") == "tool_use" and block["name"] in REPLAYED_TOOLS:
                handler._execute_tool(block["name"], block["input"])


def prepend_title(path: str, title: str) -> None:
    """Put the title on the first line without losing the user turn already written."""
    existing = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
    Path(path).write_text(title + "\n" + existing, encoding="utf-8")


def write_new_messages(path, new_messages):
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

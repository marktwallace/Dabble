import json
import os
import traceback
from textwrap import dedent
from typing import Optional

import anthropic
import numpy as np
import pandas as pd
import streamlit as st

from .chart_renderer import render_chart as _render_chart
from .knowledge_base import search as kb_search


# ---------------------------------------------------------------------------
# DataFrame text summary — used both as tool results returned to Claude and
# as the log entry written to the conversation file. Same representation for
# both, so Claude's in-session reasoning matches the durable record.
# ---------------------------------------------------------------------------

def df_summary(df: pd.DataFrame) -> str:
    """Compact text summary of a DataFrame for Claude and the conversation log."""
    lines = []
    lines.append(f"rows: {len(df)}  columns: {', '.join(df.columns)}")

    for col in df.columns:
        series = df[col].dropna()
        if series.empty:
            lines.append(f"  {col}: all null")
        elif pd.api.types.is_numeric_dtype(df[col]):
            lines.append(
                f"  {col}: min={series.min():.4g}  max={series.max():.4g}  mean={series.mean():.4g}"
            )
        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            lines.append(f"  {col}: {series.min()} to {series.max()}")
        else:
            n_unique = series.nunique()
            if n_unique <= 20:
                counts = series.value_counts()
                lines.append(f"  {col}: " + ", ".join(f"{v} ({c})" for v, c in counts.items()))
            else:
                lines.append(f"  {col}: {n_unique} unique values")

    lines.append("")
    lines.append("  sample:")
    if len(df) <= 6:
        for row in df.itertuples(index=False):
            lines.append("  " + " | ".join(str(v) for v in row))
    else:
        for row in df.head(3).itertuples(index=False):
            lines.append("  " + " | ".join(str(v) for v in row))
        lines.append(f"  ... ({len(df) - 6} rows)")
        for row in df.tail(3).itertuples(index=False):
            lines.append("  " + " | ".join(str(v) for v in row))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ClaudeHandler
# ---------------------------------------------------------------------------

class ClaudeHandler:
    def __init__(self, system_prompt: str, kb_path: Optional[str] = None):
        self.system_prompt = system_prompt
        self.kb_path = kb_path
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

    # --- Tool definitions ---------------------------------------------------

    def _tools(self) -> list[dict]:
        return [
            {
                "name": "run_sql",
                "description": (
                    "Execute a DuckDB SQL query. Stores the full result as a named dataframe in session memory. "
                    "Returns a text summary (row count, per-column stats, sample rows) so you can reason about the data. "
                    "Always call this before render_chart or run_python."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "DuckDB SQL to execute."},
                        "dataframe_id": {"type": "string", "description": "Short descriptive name for the result (e.g. 'sales_by_month')."},
                    },
                    "required": ["sql", "dataframe_id"],
                },
            },
            {
                "name": "show_table",
                "description": (
                    "Display a previously fetched dataframe to the user as an interactive table. "
                    "The user reads it visually — you do not need to re-examine the data."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dataframe_id": {"type": "string", "description": "The dataframe_id from a previous run_sql call."},
                    },
                    "required": ["dataframe_id"],
                },
            },
            {
                "name": "render_chart",
                "description": (
                    "Render a Plotly chart from a previously fetched dataframe. "
                    "The full dataframe is available as 'df'. "
                    "Use plotly.graph_objects (go) or plotly.express (px) — both are available. "
                    "Assign a go.Figure to 'fig'. "
                    "If the tool returns an error, analyse it and retry with corrected code. "
                    "You can call this multiple times to iterate on a chart without re-querying."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dataframe_id": {"type": "string", "description": "The dataframe_id from a previous run_sql call."},
                        "code": {"type": "string", "description": "Python code that assigns a go.Figure to 'fig'. Available: df, go, px, pd, np."},
                        "chart_id": {"type": "string", "description": "Optional ID for this chart. Defaults to dataframe_id. Use different values for multiple charts from the same dataframe."},
                    },
                    "required": ["dataframe_id", "code"],
                },
            },
            {
                "name": "run_python",
                "description": (
                    "Transform a dataframe using pandas when SQL alone is insufficient. "
                    "The input dataframe is available as 'df'. Assign the output DataFrame to 'result'."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dataframe_id": {"type": "string", "description": "Input dataframe_id from a previous run_sql call."},
                        "code": {"type": "string", "description": "Python code with df, pd, np available. Must assign a DataFrame to 'result'."},
                        "output_dataframe_id": {"type": "string", "description": "Name for the resulting dataframe."},
                    },
                    "required": ["dataframe_id", "code", "output_dataframe_id"],
                },
            },
            {
                "name": "search_knowledge_base",
                "description": (
                    "Search the knowledge base for relevant domain knowledge and prior successful analysis sequences. "
                    "Use this when schema knowledge, domain context, or a worked example would improve accuracy."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language search query."},
                    },
                    "required": ["query"],
                },
            },
        ]

    # --- Tool implementations ------------------------------------------------

    def _execute_tool(self, name: str, inputs: dict) -> str:
        try:
            if name == "run_sql":
                return self._run_sql(inputs["sql"], inputs["dataframe_id"])
            elif name == "show_table":
                return self._show_table(inputs["dataframe_id"])
            elif name == "render_chart":
                return self._render_chart(inputs["dataframe_id"], inputs["code"], inputs.get("chart_id"))
            elif name == "run_python":
                return self._run_python(inputs["dataframe_id"], inputs["code"], inputs["output_dataframe_id"])
            elif name == "search_knowledge_base":
                return self._search_kb(inputs["query"])
            else:
                return f"Unknown tool: {name}"
        except Exception:
            return traceback.format_exc()

    def _run_sql(self, sql: str, dataframe_id: str) -> str:
        db = st.session_state.get("analytic_db")
        if not db:
            return "Error: no analytic database configured."
        df, err = db.execute_query(sql)
        if err:
            return f"SQL error: {err}"
        if df is None or df.empty:
            return "Query returned no rows."
        st.session_state.dataframes[dataframe_id] = df
        st.session_state.artifact_order.append(("dataframe", dataframe_id))
        return df_summary(df)

    def _show_table(self, dataframe_id: str) -> str:
        if dataframe_id not in st.session_state.dataframes:
            return f"Error: '{dataframe_id}' not found. Call run_sql first."
        st.session_state.tables_to_show.append(dataframe_id)
        return "Displayed to user."

    def _render_chart(self, dataframe_id: str, code: str, chart_id: str | None) -> str:
        df = st.session_state.dataframes.get(dataframe_id)
        if df is None:
            return f"Error: '{dataframe_id}' not found. Call run_sql first."
        fig, err = _render_chart(df, code)
        key = chart_id or dataframe_id
        if err:
            st.session_state.figures[key] = {"error": err}
            return f"Chart error:\n{err}"
        st.session_state.figures[key] = {"figure": fig, "code": code, "dataframe_id": dataframe_id}
        st.session_state.artifact_order.append(("chart", key))
        return "Chart rendered."

    def _run_python(self, dataframe_id: str, code: str, output_id: str) -> str:
        df = st.session_state.dataframes.get(dataframe_id)
        if df is None:
            return f"Error: '{dataframe_id}' not found. Call run_sql first."
        ns = {"df": df.copy(), "pd": pd, "np": np, "result": None}
        try:
            exec(dedent(code.strip()), ns)  # noqa: S102
            result = ns.get("result")
            if not isinstance(result, pd.DataFrame):
                return "Error: code must assign a pandas DataFrame to 'result'."
            st.session_state.dataframes[output_id] = result
            return df_summary(result)
        except Exception:
            return traceback.format_exc()

    def _search_kb(self, query: str) -> str:
        if not self.kb_path:
            return "Knowledge base not configured."
        chunks = kb_search(query, self.kb_path)
        if not chunks:
            return "No relevant knowledge found."
        return "\n\n".join(f"[{i}] {c['description']}\n{c['content']}" for i, c in enumerate(chunks, 1))

    # --- Tool loop -----------------------------------------------------------

    def run_tool_loop(self, messages: list[dict]) -> tuple[list[dict], object]:
        """Run the Claude tool loop until stop_reason is not 'tool_use'.

        Appends all new messages (assistant turns and tool results) to the
        messages list and also returns it. The caller is responsible for
        persisting the new messages to the conversation file.
        """
        while True:
            response = self.client.messages.create(
                model=self.model,
                system=self.system_prompt,
                messages=messages,
                tools=self._tools(),
                max_tokens=8096,
            )
            messages.append({
                "role": "assistant",
                "content": [b.model_dump() for b in response.content],
            })
            if response.stop_reason != "tool_use":
                break
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
        return messages, response

    # --- Standalone LLM calls ------------------------------------------------

    def generate_title(self, user_message: str) -> str:
        """Generate a short conversation title from the first user message."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=60,
                messages=[{"role": "user", "content": (
                    "Generate a short title (max 60 chars) for a data analysis conversation "
                    "that starts with this message. No quotes, no punctuation at the end.\n\n"
                    + user_message[:400]
                )}],
            )
            return response.content[0].text.strip()[:60]
        except Exception:
            return "Untitled conversation"

    def extract_learn_chunks(self, conversation_text: str) -> list[dict]:
        """Analyse a conversation and extract knowledge chunks for /learn.

        Returns a list of dicts with 'description' and 'content' keys.
        """
        prompt = (
            "You are analysing a data analysis conversation to extract knowledge chunks "
            "for a persistent knowledge base used by future analysis sessions.\n\n"
            "Extract 2-5 sequence chunks worth preserving. Each chunk should capture a complete "
            "analytical episode: the user's intent, the approach that worked (including any SQL "
            "iteration), key data shape observations, domain corrections, or schema/data quality "
            "discoveries. Prefer sequences that show *how to reason* in this domain over isolated facts.\n\n"
            "Return a JSON array. Each object must have:\n"
            "  description: one sentence capturing the intent (used for semantic search)\n"
            "  content: full chunk text including SQL, data notes, and conclusions\n\n"
            "Return only valid JSON, no markdown fences.\n\n"
            "Conversation:\n\n" + conversation_text[:12000]
        )
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except Exception:
            return []

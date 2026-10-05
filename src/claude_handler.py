import json
import logging
import os
import re
import time
import traceback
from pathlib import Path
from textwrap import dedent
from typing import Optional

logger = logging.getLogger(__name__)

import anthropic
import numpy as np
import pandas as pd

from .chart_renderer import render_chart as _render_chart
from .knowledge_base import build_registry_block, delete_chunk, overwrite_chunk, read_chunk, write_chunk
from .prompt_files import PromptFileError
from .prompt_files import read as read_prompt_file
from .session import SessionState


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
        elif pd.api.types.is_bool_dtype(df[col]):
            counts = series.value_counts()
            parts = ", ".join(f"{v} ({c})" for v, c in counts.items())
            lines.append(f"  {col}: {parts}")
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


MAX_STORED_DATAFRAMES = 10

# Room for thinking as well as the reply. On models that always think (Opus 5.5,
# Fable 5.1), thinking counts toward max_tokens even when its text isn't returned,
# so a limit sized for the reply alone cuts the reply off.
MAX_TOKENS = 16000


def configured_model() -> str:
    """The model every request uses. CLAUDE_MODEL is required; there is no default."""
    model = os.environ.get("CLAUDE_MODEL", "").strip()
    if not model:
        raise RuntimeError("CLAUDE_MODEL is not set. Set it in .env to the model this instance uses.")
    return model


def make_client():
    """The API client, chosen by CLAUDE_PROVIDER: `anthropic` (default) or `bedrock`.

    anthropic: the Claude API, with ANTHROPIC_API_KEY.
    bedrock: Amazon Bedrock's bedrock-runtime endpoint, signed with the AWS credentials
    found the usual way (an instance or task role, a profile, or keys in the environment),
    in AWS_REGION. CLAUDE_MODEL is then a Bedrock model or inference profile ID,
    e.g. us.anthropic.claude-opus-5-5.
    """
    provider = os.environ.get("CLAUDE_PROVIDER", "anthropic").strip().lower() or "anthropic"
    if provider == "anthropic":
        return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    if provider == "bedrock":
        return anthropic.AnthropicBedrock()
    raise RuntimeError(f"CLAUDE_PROVIDER is {provider!r}; use anthropic or bedrock.")


def response_text(response) -> str:
    """The text of a response, read by block type.

    A response can begin with thinking blocks, so content[0] is not
    necessarily text.
    """
    return "".join(b.text for b in response.content if b.type == "text")

def _log_api_error(e: "anthropic.APIStatusError", round_trip: int) -> None:
    """Log what the API said about a failed request, after the SDK's own retries.

    The request ID and the retry-after / x-ratelimit-* / anthropic-* headers are
    what distinguish one kind of 429 from another, and what Anthropic support asks for;
    on Bedrock the request ID and error type come in x-amzn-* headers.
    """
    headers = {
        k: v for k, v in e.response.headers.items()
        if k == "retry-after" or k.startswith(("x-ratelimit", "anthropic-", "x-amzn-"))
    }
    logger.error(
        "API error on round-trip %d: HTTP %s request_id=%s headers=%s body=%s",
        round_trip, e.status_code, e.request_id, headers, e.body,
    )


# ---------------------------------------------------------------------------
# ClaudeHandler
# ---------------------------------------------------------------------------

class ClaudeHandler:
    def __init__(self, system_prompt: str, knowledge_dir: Optional[str] = None, state: Optional[SessionState] = None,
                 prompts_dir: Optional[str] = None):
        self.knowledge_dir = knowledge_dir
        # Where read_document looks. Unset, the tool is not offered.
        self.prompts_dir = prompts_dir
        self.state = state if state is not None else SessionState()
        registry = build_registry_block(knowledge_dir) if knowledge_dir else ""
        self.system_prompt = system_prompt + ("\n\n" + registry if registry else "")
        self.client = make_client()
        self.model = configured_model()
        # Both optional; unset, requests are exactly as before.
        # CLAUDE_EFFORT: low / medium / high / xhigh / max.
        self.effort = os.environ.get("CLAUDE_EFFORT", "").strip()
        # CLAUDE_THINKING_BLOCK_BINDING: drop_block or error. Only for models that
        # tie thinking blocks to the conversation that produced them (Opus 5.5,
        # Fable 5.1). A resumed conversation runs under a rebuilt system prompt,
        # so its earlier thinking blocks no longer match; drop_block has the API
        # drop them instead of rejecting the request. Setting this also sends
        # adaptive thinking, which those models run regardless.
        self.block_binding = os.environ.get("CLAUDE_THINKING_BLOCK_BINDING", "").strip()

    def _request_options(self) -> dict:
        """Optional request fields set from the environment."""
        opts = {}
        if self.effort:
            opts["output_config"] = {"effort": self.effort}
        return opts

    # --- Tool definitions ---------------------------------------------------

    def _tools(self) -> list[dict]:
        tools = [
            {
                "name": "run_sql",
                "description": (
                    "Execute a DuckDB SQL query. Stores the full result as a named dataframe in session memory. "
                    "Stored dataframes are available to show_table, render_chart, and run_python, not to later "
                    "run_sql queries; to build on a result in SQL, repeat its query as a CTE. "
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
                    "The full dataframe is available as 'df'; further dataframes named in dataframe_ids, "
                    "with the first, are in the dict 'dfs' by id. "
                    "Use plotly.graph_objects (go) or plotly.express (px) — both are available. "
                    "Assign a go.Figure to 'fig'. "
                    "Charts are shown in the app's theme (dark), so leave colors unset unless the user "
                    "asks for a particular look. "
                    "If the tool returns an error, analyse it and retry with corrected code. "
                    "You can call this multiple times to iterate on a chart without re-querying."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dataframe_id": {"type": "string", "description": "The dataframe_id from a previous run_sql call."},
                        "dataframe_ids": {"type": "array", "items": {"type": "string"},
                                          "description": "Optional further dataframe_ids the code needs, available in 'dfs'."},
                        "code": {"type": "string", "description": "Python code that assigns a go.Figure to 'fig'. Available: df, dfs, go, px, pd, np."},
                        "chart_id": {"type": "string", "description": "Optional ID for this chart. Defaults to dataframe_id. Use different values for multiple charts from the same dataframe."},
                    },
                    "required": ["dataframe_id", "code"],
                },
            },
            {
                "name": "run_python",
                "description": (
                    "Run Python code against a dataframe. Use for transforms, statistical analysis, "
                    "modelling, or any computation where SQL alone is insufficient. "
                    "The full scientific Python stack is available — import any installed package. "
                    "The input dataframe is available as 'df'; when the code needs more than one, name the "
                    "others in dataframe_ids and read every one, the first included, from the dict 'dfs' by id. "
                    "If you assign a DataFrame to 'result', it is stored and summarised. "
                    "If 'result' is any other value, it is returned as a string. "
                    "If 'result' is not assigned, the tool returns 'Code executed successfully.'"
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dataframe_id": {"type": "string", "description": "Input dataframe_id from a previous run_sql call."},
                        "dataframe_ids": {"type": "array", "items": {"type": "string"},
                                          "description": "Optional further input dataframe_ids, available in 'dfs'."},
                        "code": {"type": "string", "description": "Python code with df, dfs, pd, np available. Optionally assign a DataFrame or any value to 'result'."},
                        "output_dataframe_id": {"type": "string", "description": "Name for the resulting dataframe. Required only if result is a DataFrame."},
                    },
                    "required": ["dataframe_id", "code"],
                },
            },
            {
                "name": "recall_knowledge",
                "description": (
                    "Retrieve a domain knowledge chunk by name. "
                    "Call this when <available_knowledge> lists an entry relevant to your current task. "
                    "Returns the full chunk content."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "chunk": {
                            "type": "string",
                            "description": "The chunk name from <available_knowledge> (e.g. 'qc-status-codes').",
                        },
                    },
                    "required": ["chunk"],
                },
            },
            {
                "name": "update_knowledge",
                "description": (
                    "Create or overwrite a knowledge base chunk. "
                    "Use this to save a new chunk, edit an existing one, or write a merged replacement. "
                    "If updating an existing chunk, pass its slug from <available_knowledge>. "
                    "If creating a new chunk, omit slug and one will be derived from the description. "
                    "Changes take effect from the next conversation — tell the user this after saving."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Routing phrase completing 'recall this when the user asks about ___'. Be specific.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full chunk content: SQL, data notes, join patterns, domain corrections, etc.",
                        },
                        "slug": {
                            "type": "string",
                            "description": "Chunk name to overwrite (from <available_knowledge>). Omit to create a new chunk.",
                        },
                    },
                    "required": ["description", "content"],
                },
            },
            {
                "name": "delete_knowledge",
                "description": (
                    "Delete a knowledge base chunk by slug. "
                    "Use after merging chunks or when a chunk is stale or incorrect. "
                    "For bulk deletions (3 or more), list the slugs you plan to remove and "
                    "wait for explicit user confirmation before calling this tool."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "slug": {
                            "type": "string",
                            "description": "The chunk slug to delete (from <available_knowledge>).",
                        },
                    },
                    "required": ["slug"],
                },
            },
            {
                "name": "save_file",
                "description": (
                    "Save a dataframe to a file. The file is placed in the exports/ directory "
                    "and a download button is shown to the user. "
                    "Supported formats: csv, excel, parquet."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dataframe_id": {"type": "string", "description": "The dataframe to save."},
                        "filename": {"type": "string", "description": "Output filename (e.g. 'sales_summary.csv')."},
                        "format": {"type": "string", "enum": ["csv", "excel", "parquet"], "description": "File format."},
                    },
                    "required": ["dataframe_id", "filename", "format"],
                },
            },
        ]
        if self.prompts_dir:
            tools.append({
                "name": "read_document",
                "description": (
                    "Read a reference document from the prompt directory, in full. "
                    "Use the paths the system prompt names, and read a document before "
                    "relying on what it covers."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path relative to the prompt directory, as the system prompt names it (e.g. 'topics/example.md')."},
                    },
                    "required": ["path"],
                },
            })
        return tools

    # --- Tool implementations ------------------------------------------------

    def _execute_tool(self, name: str, inputs: dict) -> str:
        try:
            if name == "run_sql":
                return self._run_sql(inputs["sql"], inputs["dataframe_id"])
            elif name == "show_table":
                return self._show_table(inputs["dataframe_id"])
            elif name == "render_chart":
                return self._render_chart(inputs["dataframe_id"], inputs["code"], inputs.get("chart_id"),
                                          inputs.get("dataframe_ids"))
            elif name == "run_python":
                return self._run_python(inputs["dataframe_id"], inputs["code"], inputs.get("output_dataframe_id"),
                                        inputs.get("dataframe_ids"))
            elif name == "save_file":
                return self._save_file(inputs["dataframe_id"], inputs["filename"], inputs["format"])
            elif name == "recall_knowledge":
                return self._recall_knowledge(inputs["chunk"])
            elif name == "update_knowledge":
                return self._update_knowledge(inputs["description"], inputs["content"], inputs.get("slug"))
            elif name == "delete_knowledge":
                return self._delete_knowledge(inputs["slug"])
            elif name == "read_document":
                return self._read_document(inputs["path"])
            else:
                return f"Unknown tool: {name}"
        except Exception:
            tb = traceback.format_exc()
            logger.error("Tool %s raised exception: %s", name, tb)
            return tb

    def _run_sql(self, sql: str, dataframe_id: str) -> str:
        db = self.state.analytic_db
        if not db:
            return "Error: no analytic database configured."
        df, err = db.execute_query(sql)
        if err:
            logger.debug("SQL error [%s]: %s", dataframe_id, err)
            return f"SQL error: {err}"
        if df is None or df.empty:
            return "Query returned no rows."
        self.state.dataframes[dataframe_id] = df
        self.state.artifact_order.append(("dataframe", dataframe_id))
        self._evict_dataframes()
        return df_summary(df)

    def _show_table(self, dataframe_id: str) -> str:
        if dataframe_id not in self.state.dataframes:
            return f"Error: '{dataframe_id}' not found. Call run_sql first."
        self.state.shown_dataframes.add(dataframe_id)
        self.state.tables_to_show.append(dataframe_id)
        return "Displayed to user."

    def _evict_dataframes(self) -> None:
        """Evict oldest DataFrames once the store exceeds MAX_STORED_DATAFRAMES.

        DataFrames marked as shown via show_table are protected — evicting them
        would break table display when the user scrolls up. Only intermediate
        DataFrames (used as chart/python inputs but never directly shown) are
        candidates for eviction.
        """
        if len(self.state.dataframes) <= MAX_STORED_DATAFRAMES:
            return
        protected = self.state.shown_dataframes
        ordered_ids = list(dict.fromkeys(
            aid for kind, aid in self.state.artifact_order if kind == "dataframe"
        ))
        evict_candidates = [i for i in ordered_ids if i not in protected]
        n_to_evict = len(self.state.dataframes) - MAX_STORED_DATAFRAMES
        for eid in evict_candidates[:n_to_evict]:
            self.state.dataframes.pop(eid, None)

    def _inputs(self, dataframe_id: str, extra_ids: list | None) -> tuple[dict | None, str | None]:
        """The named input dataframes, the first being dataframe_id; or an error naming those not found."""
        ids = list(dict.fromkeys([dataframe_id, *(extra_ids or [])]))
        missing = [i for i in ids if i not in self.state.dataframes]
        if missing:
            return None, f"Error: {', '.join(repr(i) for i in missing)} not found. Call run_sql first."
        return {i: self.state.dataframes[i] for i in ids}, None

    def _render_chart(self, dataframe_id: str, code: str, chart_id: str | None, extra_ids: list | None = None) -> str:
        dfs, err = self._inputs(dataframe_id, extra_ids)
        if err:
            return err
        fig, err = _render_chart(dfs[dataframe_id], code, dfs)
        key = chart_id or dataframe_id
        if err:
            self.state.figures[key] = {"error": err}
            return f"Chart error:\n{err}"
        self.state.figures[key] = {"figure": fig, "code": code, "dataframe_id": dataframe_id}
        self.state.artifact_order.append(("chart", key))
        return "Chart rendered."

    def _run_python(self, dataframe_id: str, code: str, output_id: str | None, extra_ids: list | None = None) -> str:
        dfs, err = self._inputs(dataframe_id, extra_ids)
        if err:
            return err
        dfs = {i: d.copy() for i, d in dfs.items()}
        ns = {"df": dfs[dataframe_id], "dfs": dfs, "pd": pd, "np": np}
        try:
            exec(dedent(code.strip()), ns)  # noqa: S102
            result = ns.get("result")
            if isinstance(result, pd.DataFrame):
                store_id = output_id or dataframe_id
                self.state.dataframes[store_id] = result
                self.state.artifact_order.append(("dataframe", store_id))
                return df_summary(result)
            elif result is not None:
                return str(result)
            else:
                return "Code executed successfully."
        except Exception:
            return traceback.format_exc()

    def _save_file(self, dataframe_id: str, filename: str, fmt: str) -> str:
        df = self.state.dataframes.get(dataframe_id)
        if df is None:
            return f"Error: '{dataframe_id}' not found. Call run_sql first."
        exports_dir = Path("exports")
        exports_dir.mkdir(exist_ok=True)
        path = exports_dir / filename
        if fmt == "csv":
            df.to_csv(path, index=False)
        elif fmt == "excel":
            df.to_excel(path, index=False)
        elif fmt == "parquet":
            df.to_parquet(path, index=False)
        self.state.exported_files[filename] = path.read_bytes()
        return f"Saved {len(df)} rows to {path}"

    def _recall_knowledge(self, chunk: str) -> str:
        if not self.knowledge_dir:
            return "Error: no knowledge directory configured."
        return read_chunk(chunk, self.knowledge_dir)

    def _update_knowledge(self, description: str, content: str, slug: str | None) -> str:
        if not self.knowledge_dir:
            return "Error: no knowledge directory configured."
        if slug:
            overwrite_chunk(slug, description, content, self.knowledge_dir)
            return f"Updated chunk '{slug}'. Takes effect from the next conversation."
        else:
            saved_slug = write_chunk(description, content, self.knowledge_dir)
            return f"Saved new chunk '{saved_slug}'. Takes effect from the next conversation."

    def _delete_knowledge(self, slug: str) -> str:
        if not self.knowledge_dir:
            return "Error: no knowledge directory configured."
        try:
            delete_chunk(slug, self.knowledge_dir)
            return f"Deleted chunk '{slug}'."
        except FileNotFoundError:
            return f"Error: no chunk named '{slug}'."

    def _read_document(self, path: str) -> str:
        if not self.prompts_dir:
            return "Error: no prompt directory configured."
        try:
            return read_prompt_file(self.prompts_dir, path)
        except PromptFileError as e:
            return f"Error: {e}"

    # --- Tool loop -----------------------------------------------------------

    def run_tool_loop(self, messages: list[dict]) -> tuple[list[dict], object]:
        """Run the Claude tool loop until stop_reason is not 'tool_use'.

        Appends all new messages (assistant turns and tool results) to the
        messages list and also returns it. The caller is responsible for
        persisting the new messages to the conversation file.
        """
        system = [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}]
        round_trip = 0
        t_start = time.monotonic()
        while True:
            round_trip += 1
            t0 = time.monotonic()
            request = dict(
                model=self.model,
                system=system,
                messages=messages,
                tools=self._tools(),
                max_tokens=MAX_TOKENS,
                **self._request_options(),
            )
            try:
                if self.block_binding:
                    response = self.client.beta.messages.create(
                        **request,
                        thinking={
                            "type": "adaptive",
                            "block_binding": {"prefix_mismatch_behavior": self.block_binding},
                        },
                        betas=["thinking-binding-controls-2026-08-01"],
                    )
                    dropped = getattr(response, "input_transformations", None)
                    if dropped:
                        logger.info("Thinking blocks dropped by the API: %s", dropped)
                else:
                    response = self.client.messages.create(**request)
            except anthropic.APIStatusError as e:
                _log_api_error(e, round_trip)
                raise
            elapsed = time.monotonic() - t0
            if response.stop_reason == "refusal":
                # Declined by a safety classifier or by the model. Content is
                # empty or partial, so it is not appended: an empty assistant
                # turn would make the next request invalid. The caller shows
                # the refusal from response.stop_details.
                logger.warning(
                    "Claude refused after %d round-trip(s): %s",
                    round_trip, getattr(response, "stop_details", None),
                )
                break
            messages.append({
                "role": "assistant",
                "content": [b.model_dump() for b in response.content],
            })
            if response.stop_reason != "tool_use":
                total = time.monotonic() - t_start
                logger.info(
                    "Claude done: %d round-trip(s), %.1fs total (last=%.1fs) stop=%s",
                    round_trip, total, elapsed, response.stop_reason,
                )
                break
            tool_calls = [b for b in response.content if b.type == "tool_use"]
            tool_names = ", ".join(b.name for b in tool_calls)
            logger.info("Round-trip %d: %.1fs — tools: %s", round_trip, elapsed, tool_names)
            tool_results = []
            for block in tool_calls:
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
                max_tokens=MAX_TOKENS,
                **self._request_options(),
                messages=[{"role": "user", "content": (
                    "Generate a short title (max 60 chars) for a data analysis conversation "
                    "that starts with this message. No quotes, no punctuation at the end.\n\n"
                    + user_message[:400]
                )}],
            )
            return response_text(response).strip()[:60]
        except Exception:
            return "Untitled conversation"

    def generate_report(self, conversation_text: str, selected_items: list[dict]) -> dict:
        """Generate a parameterized Streamlit report from a conversation.

        selected_items: list of {"type": "chart"|"table", "id": str, "chart_code": str (charts only)}
        Returns {"summary": {...}, "code": "..."} or {"error": "..."} on failure.
        """
        artifact_lines = []
        chart_code_parts = []
        for item in selected_items:
            if item["type"] == "chart":
                artifact_lines.append(f"- Chart: {item['id']}")
                if item.get("chart_code"):
                    chart_code_parts.append(f"# Chart: {item['id']}\n{item['chart_code']}")
            else:
                artifact_lines.append(f"- Table: {item['id']}")

        artifact_desc = "\n".join(artifact_lines)
        chart_code_block = "\n\n".join(chart_code_parts) or "(none)"

        prompt = (
            "You are generating a reusable parameterized Streamlit report from a data analysis conversation.\n\n"
            f"The analyst selected these artifacts:\n{artifact_desc}\n\n"
            "Generate a complete standalone Python file that:\n"
            "1. Sets: DB_PATH = os.environ.get(\"DUCKDB_ANALYTIC_FILE\") and stops with st.error() if None\n"
            "2. Uses st.sidebar widgets for parameters you identify from the conversation\n"
            "3. Re-queries DuckDB with those parameters for each selected artifact\n"
            "4. Reproduces selected chart code verbatim (provided below)\n\n"
            "Guidance on parameters:\n"
            "- Read the user's intent from the conversation, not just the SQL literals.\n"
            "  'Show me last week' → weeks_back slider with timedelta, not a hardcoded date.\n"
            "- If a value is a fixed analytical boundary (protocol change date, defined period), hardcode it.\n"
            "- Date/recency parameters are the most common and most valuable to expose.\n"
            "- If no parameters are needed, generate a simple live-query file with no widgets.\n\n"
            "The file must be self-contained: import only os, datetime, duckdb, pandas, plotly, streamlit.\n\n"
            "Respond using exactly this format — no markdown fences:\n\n"
            "<summary>\n"
            "{\n"
            '  "title": "short report title",\n'
            '  "parameters": [{"name": "variable_name", "description": "Human-readable label", "default": "python_expression"}],\n'
            '  "query_count": N,\n'
            '  "chart_count": N\n'
            "}\n"
            "</summary>\n\n"
            "<code>\n"
            "complete Python file here\n"
            "</code>\n\n"
            f"Chart code to reproduce verbatim:\n{chart_code_block}\n\n"
            f"Conversation:\n{conversation_text[:15000]}"
        )
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                **self._request_options(),
                messages=[{"role": "user", "content": prompt}],
            )
            text = response_text(response).strip()
            summary_match = re.search(r"<summary>(.*?)</summary>", text, re.DOTALL)
            code_match = re.search(r"<code>(.*?)</code>", text, re.DOTALL)
            if not summary_match or not code_match:
                return {"error": "Could not parse response — missing <summary> or <code> tags."}
            summary = json.loads(summary_match.group(1).strip())
            code = code_match.group(1).strip()
            return {"summary": summary, "code": code}
        except Exception as e:
            return {"error": str(e)}

    def generate_notebook(self, conversation_text: str, selected_ids: list[str] | None = None) -> dict:
        """Generate a Marimo notebook from a conversation transcript."""
        selection_instruction = (
            f"Only include cells for these artifact IDs: {', '.join(selected_ids)}. "
            "Omit any queries or charts not in this list.\n"
            if selected_ids else ""
        )
        prompt = (
            "Generate a Marimo notebook from the Dabble conversation transcript below.\n\n"
            f"{selection_instruction}"
            "Rules:\n"
            "- The file must start with exactly `import marimo` then `app = marimo.App(width=\"medium\")`. "
            "No other imports or code at module level. All imports (including `import marimo as mo`) go inside the first `@app.cell`.\n"
            "- Use the final successful version of each query (ignore any with SQL errors); "
            "if the conversation corrects a calculation mid-session (e.g. a wrong unit), apply the corrected formula\n"
            "- The last un-assigned expression in a cell is what gets displayed (like Jupyter). "
            "The return tuple is only for exporting variables to downstream cells. These are separate.\n"
            "- To display a DataFrame: make it the last expression before `return`\n"
            "- To display a chart: `mo.ui.plotly(fig)` as the last expression before `return`\n"
            "- A query whose result is needed by a chart cell must `return (df,)` so the chart cell can declare it as an argument\n"
            "- DB_PATH must use `os.environ.get(\"DUCKDB_ANALYTIC_FILE\")` — never hardcode a path\n"
            "- Close with the assistant's narrative summary as a `mo.md(...)` cell\n\n"
            "Respond using exactly this format — no markdown fences:\n\n"
            "<title>short notebook title</title>\n\n"
            "<code>\n"
            "complete Python file here\n"
            "</code>\n\n"
            f"Conversation:\n{conversation_text}"
        )
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                **self._request_options(),
                messages=[{"role": "user", "content": prompt}],
            )
            text = response_text(response).strip()
            title_match = re.search(r"<title>(.*?)</title>", text, re.DOTALL)
            code_match = re.search(r"<code>(.*?)</code>", text, re.DOTALL)
            if not code_match:
                return {"error": "Could not parse response — missing <code> tags."}
            title = title_match.group(1).strip() if title_match else "Notebook"
            code = code_match.group(1).strip()
            return {"title": title, "code": code}
        except Exception as e:
            return {"error": str(e)}

    def finalize_report(self, code: str, hardcoded: list[dict]) -> str:
        """Replace selected parameter widgets with hardcoded values.

        hardcoded: list of {"name": "weeks_back", "default": "1"}
        Returns the modified code string, or the original on failure.
        """
        lines_desc = "\n".join(f"  {p['name']} = {p['default']}" for p in hardcoded)
        prompt = (
            "In the following Python code, replace these sidebar widget assignments with hardcoded values:\n"
            f"{lines_desc}\n\n"
            "Keep everything else exactly the same — including all imports, comments, and logic. "
            "Return only the modified Python code, no explanation, no markdown fences.\n\n"
            f"{code}"
        )
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                **self._request_options(),
                messages=[{"role": "user", "content": prompt}],
            )
            text = response_text(response).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return text
        except Exception:
            return code

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
            "  description: a phrase completing 'recall this when the user asks about ___' — "
            "specific enough to fire on the right queries and not on unrelated ones "
            "(e.g. 'joining runs with reportable calls' not 'sequencing run query patterns')\n"
            "  content: full chunk text including SQL, data notes, and conclusions\n\n"
            "Return only valid JSON, no markdown fences.\n\n"
            "Conversation:\n\n" + conversation_text[:80000]
        )
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                **self._request_options(),
                messages=[{"role": "user", "content": prompt}],
            )
            text = response_text(response).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except Exception:
            return []

    def extract_document_chunks(self, content: str, filename: str) -> list[dict]:
        """Chunk a reference document for /learn (bypasses conversation analysis).

        Used when the user drops a file and immediately types /learn, rather than
        sending the file as a regular message first. Splits the document at natural
        boundaries and asks Claude to generate a search description for each chunk.
        """
        segments = _split_document(content)
        if not segments:
            return []

        segments_text = "\n\n---\n\n".join(
            f"Segment {i + 1}:\n{seg}" for i, seg in enumerate(segments)
        )
        prompt = (
            f"You are indexing a reference document ({filename}) for a knowledge base "
            "used by future data analysis sessions.\n\n"
            "For each segment below, write a description: a phrase completing "
            "'recall this when the user asks about ___' — specific enough to fire on "
            "the right queries and not on unrelated ones.\n\n"
            "Return a JSON array where each object has:\n"
            "  description: routing phrase for this chunk\n"
            "  content: the segment text verbatim\n\n"
            "Return only valid JSON, no markdown fences.\n\n"
            + segments_text[:60000]
        )
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                **self._request_options(),
                messages=[{"role": "user", "content": prompt}],
            )
            text = response_text(response).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            chunks = json.loads(text)
            # Always use the original segments as content - don't trust Claude to reproduce verbatim
            for i, chunk in enumerate(chunks):
                if i < len(segments):
                    chunk["content"] = segments[i]
            return chunks
        except Exception:
            return []


def _split_document(content: str, max_chars: int = 3000) -> list[str]:
    """Split a document into chunks at natural boundaries.

    Prefers markdown section headers; falls back to paragraph breaks.
    Merges small segments and hard-splits oversized ones at line boundaries.
    """
    header_re = re.compile(r'(?m)(?=^#{1,4} )')
    if header_re.search(content):
        parts = header_re.split(content)
    else:
        parts = re.split(r'\n\n+', content)

    chunks = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(buf) + len(part) + 2 <= max_chars:
            buf = (buf + "\n\n" + part).strip() if buf else part
        else:
            if buf:
                chunks.append(buf)
            if len(part) <= max_chars:
                buf = part
            else:
                lines = part.splitlines(keepends=True)
                buf = ""
                for line in lines:
                    if len(buf) + len(line) <= max_chars:
                        buf += line
                    else:
                        if buf.strip():
                            chunks.append(buf.strip())
                        buf = line
    if buf.strip():
        chunks.append(buf.strip())
    return chunks

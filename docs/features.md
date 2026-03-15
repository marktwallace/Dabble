# Dabble v2 Requirements

## Vision

A conversational data analysis tool that gives non-engineers Claude-Code-like flexibility for exploring data — packaged as a minimal Streamlit app. The user works with a DuckDB analytic database using plain English: asking questions, getting inline charts, iterating on them conversationally, and producing shareable outputs without writing code or SQL.

The architecture is intentionally simple. Its value is in giving Claude a set of well-designed domain tools — DuckDB, pandas, Plotly — that are more focused than what general-purpose coding assistants provide. The shape of the architecture is expressed by the simplicity of the code itself. Claude is not constrained by pre-drawn boxes; it is given good tools and allowed to reason freely.

**Dabble is domain-agnostic and open-source.** It ships without a system prompt, database, or knowledge base. There are two usage modes:

**Bootstrap mode** — point at a new DuckDB file, import a CSV, start exploring. Domain knowledge accumulates over time via `/learn`. This is the fastest path to a working session and requires no upfront configuration.

**Domain overlay mode** — a separate (typically private) repository provides a system prompt, knowledge base seed content, and a pre-populated DuckDB file. The overlay is wired to Dabble via `.env`. Dabble knows nothing about any specific domain; the overlay is what makes it accurate for a given context. A production overlay system prompt may be large — covering schema documentation, data quality quirks, join patterns, and analytical conventions — and can run to tens of thousands of tokens. The DuckDB file and ChromaDB directory live with the overlay, not in this repository, and are not under source control.

---

## Users

**Analyst (primary)** — domain expert, non-engineer. Uses the tool for daily data exploration. Provides domain corrections conversationally. Triggers /learn when a conversation produced something worth remembering.

**Developer (admin)** — configures the domain overlay, seeds the knowledge base, maintains the data pipeline.

**Colleagues (consumers)** — receive generated outputs (presentations, reports). Do not use the tool directly.

---

## Core Features

### 1. Entry Screen

A landing page listing previous conversations sorted by date descending, with a "New conversation" button. Each entry shows date and inferred title on one line.

Conversations are plain text files in `conversations/`. No metadata database. Filenames are timestamp-based (e.g. `2026-03-07T14-32.txt`). The title shown on the entry screen is the first line of the file, written by Claude when the conversation starts.

The conversation list is rendered as `st.radio` with `index=None` (nothing pre-selected). Clicking any item navigates immediately via `on_change`. Date is shown first for scannability.

Below the conversation list, two sections: **Reports** (live, parameterized) and **Snapshots** (static), each listing generated files by date descending. Each entry is a collapsed expander showing the `streamlit run` command.

### 2. Conversational Analysis

A chat interface backed by Claude (claude-sonnet-4-6). The full tool loop runs synchronously before Streamlit rerenders — no queue, no multi-rerun machinery, no intermediate buttons to advance the state.

**UI layout — conversation view:**

- `st.chat_input()` is the primary input. It handles regular messages, /learn, /snapshot, and /report uniformly — no special buttons.
- A `st.popover("📎")` button above the chat input exposes an optional file uploader. The analyst can attach either an image (PNG, JPG, JPEG, GIF, WebP) or any text/data file (CSV, TSV, Markdown, SQL, Python, JSON, JSONL, plain text, etc.) to any message. The popover hides the widget until needed; once a file is attached and the message sent, the uploader resets automatically.
- A spinner shows while the tool loop is running ("working...").
- Each assistant turn renders as:
  1. One `st.expander` per tool call, labelled with the tool name and dataframe_id (e.g. *"SQL: abundance\_by\_type — 312 rows"*). Collapsed by default for older turns; **open by default for the most recent turn** so the analyst can immediately verify what just ran.
  2. `st.dataframe(df)` inline if `show_table` was called.
  3. `st.plotly_chart(fig)` inline if `render_chart` succeeded.
  4. The narrative text.
- No custom HTML or CSS. No sidebar. Streamlit's default styling is sufficient.

**In-memory environment per session:**
- One DuckDB connection (read-only, path from environment config)
- `dataframes` dict — named DataFrames produced by run_sql or run_python
- `figures` dict — named Plotly figures produced by render_chart
- `exported_files` dict — file bytes keyed by filename, produced by save_file

**Five tools:**

`run_sql(sql, dataframe_id)` — execute DuckDB SQL, store full DataFrame in session memory, return schema + sample to Claude for reasoning.

`show_table(dataframe_id)` — render the full DataFrame in the Streamlit UI using `st.dataframe()`. The human's visual system reads it; Claude does not need to re-read it.

`render_chart(dataframe_id, plotly_code, chart_id)` — render a Plotly figure using the full in-memory DataFrame. Claude can iterate on a chart without re-querying. The human reads the chart visually.

`run_python(dataframe_id, code, output_dataframe_id?)` — run Python against a dataframe for transforms, statistical analysis, modelling, or any computation where SQL alone is insufficient. The full scientific Python stack is available. If `result` is assigned a DataFrame it is stored; if it is any other value it is returned as a string; if unassigned, returns "Code executed successfully."

`save_file(dataframe_id, filename, format)` — save a dataframe to `exports/` as CSV, Excel, or Parquet and render a download button in the conversation. Covers the "email me this data" workflow that a Jupyter user handles with `df.to_csv()`.

The system prompt is loaded from `prompts/system_prompt.txt` if provided by a domain overlay. In bootstrap mode this file may be absent or minimal. The live database schema (table names and column names) is injected dynamically at session start so Claude never needs to discover it via tool calls. A static block documenting the exec namespace available inside `run_python` and `render_chart` (available variables, importable packages) is also injected at session start. Additional domain context is retrieved from the knowledge base and injected before each question is processed.

### 3. Conversation Persistence

Each conversation is a plain text file in `conversations/`, written incrementally turn by turn. The file is the complete record of the session — tool calls, tool results, and assistant narrative are all preserved. This is essential for /learn: the SQL that worked, the iteration that got there, and the data that confirmed correctness are all evidence that must survive.

The format uses simple labeled sections (`User:`, `Assistant:`, `tool_use:`, `tool_result:`) with two-space indented content. See `conversations/example.txt` for a reference.

**Cognitive division of labor:**

The human and Claude each get a representation suited to their cognitive strengths:

- **Human** — sees `st.dataframe(df)` (full interactive viewer, sortable, filterable) and Plotly charts. Visual pattern recognition does the work.
- **Claude** — reads a structured text summary logged to the conversation file. Fast text scanning, no visual input.

These are complementary, not redundant. The Streamlit UI is for the human; the conversation file is for Claude.

**tool_result formatting for DataFrames:**

The structured text summary is always written to the conversation file when a DataFrame is produced — regardless of whether `show_table` is called. It is Claude's durable record of the data shape:

    tool_result: run_sql
      rows: 312  columns: sample_type, week, avg_abundance
      sample_type: blood (187), swab (125)
      week: 2025-12-15 to 2026-03-01
      avg_abundance: min=1.2  max=8.9  mean=4.3

      sample:
      blood | 2025-12-15 | 4.2
      blood | 2025-12-22 | 4.8
      swab  | 2025-12-15 | 3.1
      ... (309 rows)
      swab  | 2026-03-01 | 3.4

Summary statistics generated automatically per column type: value counts for low-cardinality categoricals, min/max/mean for numerics, range for dates. First and last 3 rows shown when more than 6 rows. This requires no extra Claude tool calls.

When the summary is not sufficient, Claude uses `run_python` or `run_sql` to interrogate further — and that interrogation is also logged, preserving the reasoning trail.

The file is opened at session start. The first line is the title, written by Claude on its first turn.

**JSON sidecar and session resumption:**

Alongside each `.txt` file, a `.json` sidecar stores the full Anthropic messages list — every user message, assistant content block, tool_use, and tool_result — as a JSON array. It is written after every agent turn and loaded when a previous conversation is opened from the entry screen.

On load, two things happen:

1. The messages list are restored into `st.session_state.messages`, so Claude's full context is available for the next question — no history is lost. Attached image content blocks are stored in the JSON as `{"type": "omitted"}` — the base64 payload is not preserved. The primary purpose of the JSON sidecar is to recover charts and analytical state; re-displaying user-uploaded screenshots on resume is not a goal.
2. Every `run_sql`, `run_python`, `render_chart`, and `save_file` call in the saved history is replayed in order, repopulating `dataframes`, `figures`, and `exported_files` in session state. This means charts, tables, and download buttons render correctly in the conversation view without any user action.

The replay is purely mechanical — no LLM call is made. It runs the same SQL and Plotly code that is already recorded in the message history. If the underlying data has changed, the queries return updated rows; the chart code still runs against whatever data comes back.

The `.txt` file remains the human-readable record and the source for `/learn`. The `.json` file is the machine-readable state; it is not intended for human reading.

### 4. /learn Command

The knowledge base grows from real analysis sessions. When the analyst types `/learn`, the app navigates to a separate confirmation screen (not a dialog — a full Streamlit page). On that screen:

1. Claude has already extracted a set of sequence chunks from the conversation (see below)
2. Each chunk is listed with a short description and its full content
3. The analyst approves or rejects each chunk individually
4. Confirmed chunks are saved as a file in `knowledge/` and immediately loaded into ChromaDB

**Two extraction paths:**

When `/learn` is triggered immediately after a file was attached (with no other turns between them), the command takes a *document chunking* path: the file content is split structurally (on Markdown headers, blank lines, or fixed-size windows) into segments, each segment is passed to Claude to produce a description + content chunk, and the results go to the review screen. This path is appropriate when the user's intent is clearly "index this document."

When `/learn` is triggered after a normal conversation (possibly one that included a file earlier), the command takes the *conversation extraction* path: Claude reads the full `.txt` conversation transcript and extracts analytical episodes as sequence chunks. Because file content is written in full to the `.txt` file at send time, it is naturally available to the extraction call — no special handling is needed.

**What a sequence chunk contains:**

A chunk captures a complete analytical episode — enough to convey a semantic plan that can be adapted to a new situation. Typically: the user's intent, the SQL that worked (possibly after iteration), a representative extract of the result that confirmed correctness, and the chart or conclusion that followed. Data quality discoveries are especially valuable: if the correct answer required understanding that a column is sparsely populated, or that NULL has a specific meaning, that context is part of the chunk.

This episodic form is more useful for retrieval than isolated facts. When Claude searches the knowledge base with a new user request, it retrieves prior sequences that succeeded in similar situations — and adapts the plan, rather than assembling one from scratch. Sequences convey *how to reason* in the domain, not just *what is true*.

**On embeddings:**

The vector for each chunk is computed on the user's intent and a short Claude-generated description of what was accomplished — not on the full chunk text. Intent is what matches a new user request at retrieval time. The full chunk (SQL, data extract, chart code, domain notes) is what gets injected as context once retrieved.

Each chunk gets its own embedding. The knowledge file is the organizational unit for humans; the chunk is the retrieval unit for Claude.

**On schema and data quality knowledge:**

Understanding the database schema and its quirks is critical to getting correct answers. Wrong results often look like blank cells or missing values rather than errors — the analyst sees a plausible-looking but wrong answer. The knowledge base is the primary mechanism for encoding this kind of knowledge: which columns are reliably populated, what NULL means in a given context, how to join tables correctly, what valid value ranges look like. These facts belong in sequence chunks alongside the queries that exposed them.

ChromaDB entries include metadata: source file, date, topic label (generated by Claude).

The `knowledge/` directory is the durable source of truth. ChromaDB can be fully rebuilt from it at any time.

### 5. /snapshot Command

When the analyst types `/snapshot`, the app navigates to a snapshot review screen (not a dialog — a full Streamlit page). On that screen the analyst selects one or more items to include, then clicks Generate to produce a self-contained HTML file.

**Selection UI:** Checkboxes, one per available artifact, listed in reverse chronological order (most recent first). The first item is checked by default; the rest are unchecked. Up to 5 are shown initially; a "Show all N options" button reveals the rest. The list includes all charts rendered without error and all dataframes produced by `run_sql` or `run_python`.

**Chronological ordering:** A session-scoped `artifact_order` list records each `run_sql` and successful `render_chart` call in insertion order. The review screen walks it in reverse to produce the option list. This preserves true cross-type ordering — not just within-dict ordering.

The generated file is a self-contained HTML page. Charts are rendered as interactive Plotly figures (zoom, hover, tooltips). Tables are rendered as Plotly tables. The only external dependency is the Plotly CDN script tag — the file opens in any browser with no Python required.

**Structure:** An HTML page with a `<h1>` title. For multi-item snapshots, each section has an `<h2>` header and an `<hr>` divider. For single-item snapshots the `<h2>` is omitted — it would duplicate the page title. The Plotly figure's own title is stripped before export for the same reason. A versioned Plotly CDN script is injected by Plotly's `to_html()` on the first figure; subsequent figures share it.

The snapshot title is derived from the first two selected item names (e.g. "Track Durations & Songs By Artist").

**File naming:** `reports/snapshot_<timestamp>_<first_item_id>.html`.

**No dependencies.** Open in any browser or email as an attachment.

**Template location:** `src/pages/snapshot_review.py`. Generation is deterministic — no LLM call is needed.

---

### 6. /report Command

When the analyst types `/report`, the app navigates to a report review screen. On that screen the analyst selects one or more artifacts to include, then clicks Generate. An LLM call produces a complete parameterized Streamlit file that connects to DuckDB at runtime, exposing Streamlit widgets for parameters Claude identified from the conversation.

**Selection UI:** Same as /snapshot — checkboxes in reverse chronological order, first item checked by default.

**Generation:** The LLM call receives the full conversation messages (user turns and tool calls) plus the selected artifact IDs. Claude produces a complete Streamlit Python file. Python's only job is to write that file to disk. No parameter extraction logic lives in Python — Claude does it all, reading user intent from the conversation rather than inferring it solely from SQL literals.

This is the critical design principle: give Claude the full conversation so it can reason about intent, not just code. A user who said "show me the last week" and ended up with `WHERE date >= '2026-03-02'` in the SQL wants a relative date widget (`timedelta`), not a date picker defaulting to that hardcoded value. A model with domain overlay context may identify parameters the current model would miss — this design does not constrain that.

**Review screen:** Shows a structured preview of the draft file before writing — parameters identified, number of queries, number of charts — with a confirm button. The scientist can also see the generated code if they want to inspect it.

**Generated file structure:**

```python
import duckdb
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DB_PATH = "/path/to/data.db"   # edit if the database moves

st.set_page_config(page_title="<title>", layout="wide")
st.title("<title>")

# Parameters (Claude-generated widgets based on conversation intent)
weeks_back = st.sidebar.slider("Weeks back", 1, 12, 1)
sample_type = st.sidebar.selectbox("Sample type", ["blood", "swab"])

# Queries
con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute("""
    SELECT week, avg_abundance
    FROM samples
    WHERE sample_type = ? AND week >= ?
    ORDER BY week
""", [sample_type, date.today() - timedelta(weeks=weeks_back)]).df()

# Chart (verbatim from conversation)
fig = px.line(df, x="week", y="avg_abundance")
st.plotly_chart(fig, use_container_width=True)
```

The generated file is intentionally readable. A scientist can open it in a text editor, understand every line, edit `DB_PATH` if it moves, or remove a widget and hardcode its value.

**File naming:** `reports/report_<timestamp>_<first_item_id>.py`.

**Dependencies:** `streamlit`, `duckdb`, `pandas`, `plotly`. The DuckDB file is expected to be accessible at the path embedded in the file — typically a shared network location updated by regular ETL.

---

## Knowledge Base

ChromaDB persistent store at `db/knowledge_base/`. Embeddings via OpenAI text-embedding-3-small.

**Seeding:** A one-time script (`tools/seed_knowledge_base.py`) loads initial domain content from the `knowledge/` directory. Run by the developer when setting up a domain overlay.

**Growth:** /learn appends to `knowledge/` and ChromaDB over time. The knowledge base reflects accumulated domain reasoning from real analysis sessions.

**Rebuild:** `tools/rebuild_knowledge_base.py` clears and reloads ChromaDB from the `knowledge/` directory. Allows re-embedding without losing content.

---

## Architecture

**Five Streamlit pages:** entry screen, conversation view, /learn confirmation screen, /snapshot review screen, /report review screen.

**No metadata database.** Conversation management is the filesystem.

**No sidebar conversation list.** Moved to entry screen.

**LLM:** Anthropic SDK, claude-sonnet-4-6. Synchronous (non-streaming) tool loop for v1.

**Analytic data:** DuckDB, read-only. Path via environment variable.

**Conversation files:** `conversations/` — plain text (`.txt`) written incrementally; JSON sidecar (`.json`) stores the full messages list for session resumption.

**Uploaded files:** `uploads/` — non-image files attached via the popover are saved here at send time. Filenames are prefixed with the conversation timestamp to avoid collisions. The directory is gitignored and treated as ephemeral (a scratchpad); it is not part of the recoverable conversation state.

**Knowledge files:** `knowledge/` — plain text sequence chunks, source of truth for ChromaDB.

**Generated files:** `reports/` — Snapshots (`snapshot_*.html`) are self-contained HTML files, openable in any browser. Reports (`report_*.py`) are parameterized Streamlit apps that connect to DuckDB at runtime. Notebooks (`notebook_*.py`) are Marimo reactive notebooks.

**Knowledge base:** ChromaDB at `db/knowledge_base/`.

---

## Out of Scope (v2)

- Message editing / regeneration UI
- Feedback scoring (thumbs up/down)
- Training data export pipeline
- Streaming responses
- Scheduled or automated report execution
- Parameterized report editing UI beyond the initial review step
- Multi-user support or authentication
- Any cloud execution environment
- Kafka, MinIO, PostgreSQL

---

## Open Questions

- Should /learn allow the analyst to edit chunk text before confirming, or only approve/reject?
- The /learn extraction prompt needs careful design to produce well-sized sequence chunks. This is best validated with real domain conversations before coding the extraction logic.

---

## Implementation Strategy

### Start from scratch

The v1 codebase has the wrong shape for this architecture. A 1000-line Streamlit file built around multi-rerun queues, session state flags, and a metadata database is a worse starting point than a blank file — those patterns leak into new code even when we try to ignore them. The new codebase should read as if written intentionally for this architecture.

### What to keep from v1

**`src/duckdb_analytic.py` — keep, clean up**

This file earned its complexity. The hot-swap feature (auto-detecting and loading a new `.db` file while the app is running) solves a real operational problem and is completely transparent to Claude — it lives below the `execute_query()` call that `run_sql` uses. Remove the excessive DEBUG logging; keep the connection management and hot-swap logic.

**`src/chart_renderer.py` — rewrite**

The concept is right: `exec` Plotly code in a controlled namespace, return `(fig, error)` so Claude can self-correct. But the current implementation constrains Claude to `plotly.graph_objects` only. Rewrite it to include both `go` (plotly.graph_objects) and `px` (plotly.express) in the exec namespace, so Claude can choose the most appropriate API. The file is ~20 lines.

**`src/prompt_loader.py` — delete**

The `@include` pattern solved a prompt composition problem that no longer exists. The system prompt is now a single compact file. Domain knowledge comes from ChromaDB at query time. Replace with `open().read()` inline.

**Everything else — delete or ignore**

`streamlit_ui.py`, `conversation_manager.py`, `metadata_database.py`, `llm_handler.py`, `parsing.py`, `python_executor.py` and all legacy prompts. Do not use them as reference while writing new code.

### New files to write

Listed in dependency order — each file should be completable and testable before the next begins.

1. `src/duckdb_analytic.py` — clean up from v1 (remove debug noise)
2. `src/chart_renderer.py` — rewrite with `go` + `px` in namespace
3. `src/knowledge_base.py` — ChromaDB wrapper: `search(query)`, `add_chunk(text, metadata)`, `rebuild_from_directory(path)`
4. `src/claude_handler.py` — ClaudeHandler: 5 tool definitions, synchronous tool loop, `generate_title()`
5. `src/conversation_file.py` — read/write conversation text files; format DataFrame tool results as structured text summaries (value counts, min/max/mean, date ranges, head+tail sample)
6. `src/pages/entry.py` — Streamlit entry screen: list conversations, new conversation button
7. `src/pages/conversation.py` — Streamlit conversation view: chat loop, inline charts and tables
8. `src/pages/learn_review.py` — Streamlit /learn confirmation screen: list extracted chunks, approve/reject each
9. `src/pages/snapshot_review.py` — Streamlit /snapshot review screen: checkbox selection, static file generation (no LLM call)
10. `src/pages/report_review.py` — Streamlit /report review screen: checkbox selection, LLM call to generate parameterized file, preview and confirm
11. `app.py` — top-level Streamlit multi-page entry point
12. `tools/seed_knowledge_base.py` — one-time script to load `knowledge/` into ChromaDB
13. `tools/rebuild_knowledge_base.py` — clear and reload ChromaDB from `knowledge/`

### Guiding constraints

Every file should be short enough that its full contents fit comfortably in a code review. If a file is getting long, the architecture is probably wrong — not the file length limit.

**Design for future models.** Future Claude models will have more domain context, more capability, and better tool use than the model available today. Anthropic's product roadmap makes this certain. The architecture should not encode analytical judgments in Python that a future model could make better. Prefer thin Python wrappers around LLM calls over Python logic that pre-processes or second-guesses what the model receives. The /report generation call exemplifies this: Claude gets the full conversation and produces the complete file — Python writes it to disk, nothing more.

# list-pet v2 Requirements

## Vision

A conversational data analysis tool that gives non-engineers Claude-Code-like flexibility for exploring data — packaged as a minimal Streamlit app. The user works with a DuckDB analytic database using plain English: asking questions, getting inline charts, iterating on them conversationally, and producing shareable outputs without writing code or SQL.

The architecture is intentionally simple. Its value is in giving Claude a set of well-designed domain tools — DuckDB, pandas, Plotly — that are more focused than what general-purpose coding assistants provide. The shape of the architecture is expressed by the simplicity of the code itself. Claude is not constrained by pre-drawn boxes; it is given good tools and allowed to reason freely.

**list-pet is domain-agnostic and open-source.** Domain-specific configuration (database schema documentation, system prompt, knowledge base seed content) lives in a separate overlay project. list-pet knows nothing about any particular domain.

---

## Users

**Analyst (primary)** — domain expert, non-engineer. Uses the tool for daily data exploration. Provides domain corrections conversationally. Triggers /learn when a conversation produced something worth remembering.

**Developer (admin)** — configures the domain overlay, seeds the knowledge base, maintains the data pipeline.

**Colleagues (consumers)** — receive generated outputs (presentations, reports). Do not use the tool directly.

---

## Core Features

### 1. Entry Screen

A landing page listing previous conversations sorted by date descending, with a "New conversation" button. Each entry shows an inferred title and timestamp.

Conversations are plain text files in `conversations/`. No metadata database. Filenames are timestamp-based (e.g. `2026-03-07T14-32.txt`). The title shown on the entry screen is the first line of the file, written by Claude when the conversation starts.

### 2. Conversational Analysis

A chat interface backed by Claude (claude-sonnet-4-6). The full tool loop runs synchronously before Streamlit rerenders — no queue, no multi-rerun machinery, no intermediate buttons to advance the state.

**UI layout — conversation view:**

- `st.chat_input()` is the only input. It handles regular messages, /learn, and /presentation uniformly — no special buttons.
- A spinner shows while the tool loop is running ("working...").
- Each assistant turn renders as:
  1. One `st.expander` per tool call, labelled with the tool name and dataframe_id (e.g. *"SQL: abundance\_by\_type — 312 rows"*). Collapsed by default for older turns; **open by default for the most recent turn** so the analyst can immediately verify what just ran.
  2. `st.dataframe(df)` inline if `show_table` was called.
  3. `st.plotly_chart(fig)` inline if `render_chart` succeeded.
  4. The narrative text.
- No custom HTML or CSS. No sidebar. Streamlit's default styling is sufficient.

**In-memory environment per session:**
- One DuckDB connection (read-only, path from environment config)
- `dataframes` dict — named DataFrames produced by run_sql
- `figures` dict — named Plotly figures produced by render_chart

**Five tools:**

`run_sql(sql, dataframe_id)` — execute DuckDB SQL, store full DataFrame in session memory, return schema + sample to Claude for reasoning.

`show_table(dataframe_id)` — render the full DataFrame in the Streamlit UI using `st.dataframe()`. The human's visual system reads it; Claude does not need to re-read it.

`render_chart(dataframe_id, plotly_code, chart_id)` — render a Plotly figure using the full in-memory DataFrame. Claude can iterate on a chart without re-querying. The human reads the chart visually.

`run_python(dataframe_id, code, output_dataframe_id)` — pandas transform when SQL alone is insufficient.

`search_knowledge_base(query)` — semantic search in ChromaDB for prior successful sequences and domain knowledge.

The system prompt is loaded from `prompts/system_prompt.txt` (provided by the domain overlay project). Domain context is injected dynamically via knowledge base search, not hardcoded in the prompt.

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

### 4. /learn Command

The knowledge base grows from real analysis sessions. When the analyst types `/learn`, the app navigates to a separate confirmation screen (not a dialog — a full Streamlit page). On that screen:

1. Claude has already extracted a set of sequence chunks from the conversation (see below)
2. Each chunk is listed with a short description and its full content
3. The analyst approves or rejects each chunk individually
4. Confirmed chunks are saved as a file in `knowledge/` and immediately loaded into ChromaDB

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

### 5. /report Command

When the analyst types `/report`, the app navigates to a report review screen (not a dialog — a full Streamlit page). On that screen the analyst selects which chart or dataframe to include, then clicks Generate to produce a standalone Streamlit Python file.

**Default selection:** the most recently rendered chart. If no chart exists in the session, fall back to the most recently produced dataframe.

**Type 1 — Static snapshot (implemented):**

The generated file embeds the selected dataframe as a CSV string literal and reproduces the Plotly chart code verbatim. This guarantees the report renders identically to what the analyst saw in the chat — the chart code is the same code Claude produced, run against the same data.

Generated file structure:

```python
import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="<title>", layout="wide")
st.title("<title>")

DATA = """<csv export of selected dataframe>"""

df = pd.read_csv(io.StringIO(DATA))

<plotly code verbatim from render_chart call>

st.plotly_chart(fig, use_container_width=True)
```

For a dataframe-only report (no chart), `st.dataframe(df, use_container_width=True)` is used instead.

**Type 2 — Parameterized live report (future scope):** a report that re-queries DuckDB with user-supplied parameters (e.g. a date range). Not implemented in v2.

**File naming:** `reports/<timestamp>_<chart_or_dataframe_id>.py`, e.g. `reports/2026-03-08T14-30_tracks_by_length.py`.

**No list-pet dependency.** Generated files import only: `streamlit`, `pandas`, `plotly`. The analyst runs them with `streamlit run reports/<filename>.py`.

**Entry screen:** Generated reports appear in a Reports section on the entry screen, listed by date descending. Each entry shows the filename stem and timestamp.

**Template location:** The report file template is an f-string in `src/pages/report_review.py`. It is short and deterministic — no LLM call is needed for generation.

---

## Knowledge Base

ChromaDB persistent store at `db/knowledge_base/`. Embeddings via OpenAI text-embedding-3-small.

**Seeding:** A one-time script (`tools/seed_knowledge_base.py`) loads initial domain content from the `knowledge/` directory. Run by the developer when setting up a domain overlay.

**Growth:** /learn appends to `knowledge/` and ChromaDB over time. The knowledge base reflects accumulated domain reasoning from real analysis sessions.

**Rebuild:** `tools/rebuild_knowledge_base.py` clears and reloads ChromaDB from the `knowledge/` directory. Allows re-embedding without losing content.

---

## Architecture

**Three Streamlit pages:** entry screen, conversation view, /learn confirmation screen.

**No metadata database.** Conversation management is the filesystem.

**No sidebar conversation list.** Moved to entry screen.

**LLM:** Anthropic SDK, claude-sonnet-4-6. Synchronous (non-streaming) tool loop for v1.

**Analytic data:** DuckDB, read-only. Path via environment variable.

**Conversation files:** `conversations/` — plain text, written incrementally.

**Knowledge files:** `knowledge/` — plain text sequence chunks, source of truth for ChromaDB.

**Generated reports:** `reports/` — standalone Streamlit Python files.

**Knowledge base:** ChromaDB at `db/knowledge_base/`.

---

## Out of Scope (v2)

- Message editing / regeneration UI
- Feedback scoring (thumbs up/down)
- Training data export pipeline
- Streaming responses
- Scheduled or automated report execution
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
9. `app.py` — top-level Streamlit multi-page entry point
10. `tools/seed_knowledge_base.py` — one-time script to load `knowledge/` into ChromaDB
11. `tools/rebuild_knowledge_base.py` — clear and reload ChromaDB from `knowledge/`

### Guiding constraint

Every file should be short enough that its full contents fit comfortably in a code review. If a file is getting long, the architecture is probably wrong — not the file length limit.

# Implementation Decisions

Design decisions that are non-obvious, were debated, or where the wrong choice is an easy mistake. Intended as context for future development sessions.

---

## DuckDB connection mode: read-write by default, read-only via env var

`DuckDBAnalytic` opens the database read-write by default. Set `DUCKDB_READ_ONLY=true` in the environment (or `.env`) to open it read-only.

**Rationale:** The lightweight open-source use case is "bootstrap" — the user loads their own tables into DuckDB from within the app. That requires a read-write connection. The ELT/hot-swap case (database written by an external pipeline) uses read-only so that generated reports can open the same file concurrently. DuckDB allows multiple concurrent read-only connections but rejects any second connection when one process holds a read-write lock.

The default is read-write because bootstrap is the simpler, more common starting point. ELT deployments set `DUCKDB_READ_ONLY=true` in their `.env`.

---

## No fallback values for configuration

When a required configuration value is missing (e.g. `DUCKDB_ANALYTIC_FILE`), fail loudly rather than silently substituting a default. Generated reports use `os.environ.get("DUCKDB_ANALYTIC_FILE")` with no fallback string — if the variable is not set, the report shows a clear error and stops.

Fallback values hide misconfiguration. A hardcoded path that only works on the developer's machine would let a report appear to succeed in some environments while silently using stale or wrong data in others. An explicit error forces the operator to set the variable correctly.

This applies project-wide: prefer `os.environ["VAR"]` (KeyError on miss) or a guarded `os.environ.get` with an explicit error over silent defaults.

---

## Knowledge base: proactive injection, not a tool

An early version exposed `search_knowledge_base(query)` as a Claude tool. The idea is natural: Claude knows what the user asked, so let it decide when prior context is relevant.

In practice this was wasteful. Claude called it reflexively on nearly every first turn — often getting back "knowledge base not configured" or results it didn't use. It also consumed a tool call turn before any analysis began, adding latency for no benefit.

The current design removes the tool entirely. Instead, `get_kb_context(query)` is called by the app before handing off to the tool loop. Relevant chunks are injected into the system prompt for that turn. Claude gets the context without spending a turn fetching it, and the decision about when to search is made by the application, not by Claude.

This is a general principle: if the app can determine that context is always useful for a given type of request, inject it rather than teaching Claude to ask for it.

---

## Prompt caching: system prompt only

Anthropic's prompt caching allows the API to skip re-processing stable content across calls. Cached blocks are marked with `cache_control: {"type": "ephemeral"}`. The system prompt is passed as a list-of-blocks rather than a plain string so that `cache_control` can be attached.

An earlier iteration also cached message-level tool results — the idea being that earlier tool results in a long conversation are stable and could benefit from caching. This caused two bugs:

1. The API enforces a hard limit of **4 blocks with `cache_control`** across system and messages combined. The system prompt consumes one. Adding cache markers to tool result batches exhausted the limit after a few tool calls in a session.
2. The `cached_tool_results` counter reset to zero on each `run_tool_loop` call, but cache markers from previous questions persisted in the messages list. Starting question 2 with 3 existing markers in history, then adding more, exceeded the limit again.

Both bugs were consequences of managing something we didn't need. At the scale this tool operates — system prompts up to ~20K tokens, sessions with a handful of tool calls — message-level caching provides negligible benefit. The system prompt is the only thing worth caching: it is genuinely stable across all turns in a session and is large enough to make caching worthwhile.

Current state: one `cache_control` block on the system prompt. No message-level caching.

---

## Schema injection at session start

Without explicit help, Claude's first action in a new conversation was typically `SHOW TABLES` — a wasted turn just to discover that the database has a `playlist` table with an `Artist` column. This is information the user already knows and could easily provide.

The fix is to inject the live schema into the system prompt at session initialisation. `_build_schema_context()` runs `SHOW TABLES` and `DESCRIBE <table>` for each table, then appends the result to the system prompt before the `ClaudeHandler` is created. Claude begins the first real question with full schema knowledge and goes directly to analysis.

This also means the schema in Claude's context reflects the actual database at session start — not a potentially stale description in the system prompt file. For domain overlays where the system prompt documents the schema, this is redundant but harmless; for bootstrap mode where there is no system prompt, it is essential.

---

## KB deduplication across turns

The knowledge base is searched before every question in a session. Without deduplication, the same chunks would be re-injected into the system prompt on every turn where the query happened to match them — accumulating repetitive noise and growing the prompt unnecessarily.

`ClaudeHandler` maintains `_injected_chunk_ids: set[str]` for the lifetime of the session. Each chunk has a stable ID (an MD5 hash of its content). `get_kb_context()` filters out any chunk whose ID is already in the set before building the injection string, then records the new IDs. A chunk is injected at most once per session, on the first turn where it was retrieved.

This keeps the system prompt stable across turns (which also benefits prompt caching — the cached system prompt isn't invalidated by new KB chunks after the first injection).

---

## ChromaDB distance threshold

ChromaDB returns results ranked by L2 distance. A small distance means the query embedding is close to the chunk embedding — high relevance. Without a threshold, even the most distant match in the collection is returned, which means a single irrelevant chunk can be injected as "context" just because it's the closest thing available.

`DISTANCE_THRESHOLD = 1.0` in `src/knowledge_base.py` filters out chunks whose L2 distance exceeds this value. For normalised embeddings (which `text-embedding-3-small` produces), L2 distance of 1.0 corresponds roughly to cosine similarity of 0.5 — a moderate relevance floor. If the knowledge base has nothing genuinely relevant to a query, `search()` returns an empty list and nothing is injected.

The threshold was set conservatively. If retrieval turns out to be too aggressive (injecting marginally relevant chunks), lower it; if useful chunks are being missed, raise it or inspect actual distances in a session.

## Conversation resumption: eager replay vs. lazy/on-demand

**Decision:** Eager replay — on load, re-execute all `run_sql`, `run_python`, and `render_chart` tool calls from saved history in order.

**Rejected:** Lazy replay triggered by expander open (requires Streamlit callback machinery that doesn't exist cleanly; was implemented in v1 and regretted).

**Rationale:** The architecture only runs forward in time. No dependency tracing needed. Short sessions make the cost of re-running all queries negligible. Simpler code is worth more than avoiding a few milliseconds of DuckDB queries.

---

## Conversation state format: two files

**Decision:** Two files per conversation — `.txt` (human-readable, for `/learn`) and `.json` (Anthropic messages list, for resumption). Each serves a different reader.

**Rejected:** Parsing the `.txt` back into message format. The plain text format is designed for human + Claude reading, not for round-tripping into typed API blocks.

---

## Report selection: checkboxes, not radio buttons

**Decision:** Checkboxes — multiple charts and/or dataframes can be included in one report.

**Rationale:** Multi-item reports are the typical case (replaces Looker dashboards). Radio buttons assumed single selection, which was wrong for the use case.

---

## /snapshot generation: template-based, no LLM call

**Decision:** Deterministic f-string templates. Chart code is reproduced verbatim from the saved `render_chart` call. Data is embedded as a CSV string literal.

**Rationale:** The chart code already exists and already worked. Re-asking the LLM to regenerate it introduces unnecessary non-determinism. The snapshot must render identically to what the analyst saw.

---

## Generated file DB_PATH: environment variable, not hardcoded path

**Decision:** Generated reports and notebooks read the database path from `os.environ.get("DUCKDB_ANALYTIC_FILE")` at runtime. They do not embed the path at generation time.

**Rationale:** Generated files are run on a different machine from where they were created. A path hardcoded at generation time (e.g. `/Users/mark.wallace/...`) is guaranteed to be wrong on any other system. The environment variable must be set wherever the file is run — reports with `DUCKDB_ANALYTIC_FILE=... streamlit run`, notebooks with `DUCKDB_ANALYTIC_FILE=... marimo edit`.

**How to apply:** Any LLM generation prompt that produces file code must instruct Claude to use `os.environ.get("DUCKDB_ANALYTIC_FILE")`, not a path placeholder. The review screen shows the correct startup command after saving, so the analyst knows what to set.

---

## /report generation: full conversation to LLM, thin Python wrapper

**Decision:** The LLM call for `/report` receives the full conversation text (user intent + SQL + results) and the verbatim chart code for selected artifacts. Claude produces the complete Streamlit Python file. Python's only job is to write it to disk.

**Rejected:** Pre-processing the conversation in Python to extract SQL before handing it to Claude; hardcoded parameter detection logic in Python.

**Rationale:** The user's intent lives in their natural language messages, not in the SQL literals. A user who said "show me last week" and ended up with `WHERE date >= '2026-03-02'` in the SQL wants a `timedelta` widget, not a date picker defaulting to that literal. Claude can reason about this only if it sees the full conversation. Python logic that pre-processes or second-guesses what the model receives is also fragile against future models that would make better decisions with more context — the thin wrapper approach stays correct as models improve.

**Response format:** Claude returns `<summary>` and `<code>` XML tags (not JSON-wrapped code) to avoid multiline escaping issues in the JSON code field. The summary is a small JSON object containing title, parameter list, and counts — enough for the review screen preview without parsing Python.

**DB_PATH:** Generated reports use `os.environ.get("DUCKDB_ANALYTIC_FILE")` with no fallback — if the variable is unset, the report shows an error and stops. See "No fallback values for configuration".

---

## Artifact ordering: explicit `artifact_order` list

**Decision:** A flat `artifact_order = []` list appended in both `_run_sql` and `_render_chart`, used to drive the `/snapshot` and `/report` review screens in reverse chronological order.

**Rejected:** Using dict insertion order from `dataframes` and `figures` separately. Cross-type chronological ordering is lost when artifacts are in separate dicts.

---

## `/snapshot` and `/report` review: show 5 initially, "Show all" button

**Decision:** Show the 5 most recent options by default; a button reveals the rest. First item pre-checked.

**Rationale:** Long sessions accumulate many artifacts; the analyst almost always wants something recent. Avoids overwhelming the screen.

---

## `run_python`: general computation, not pandas transform

**Decision:** `run_python` is framed as "run Python with full scientific stack access" rather than "pandas transform." `output_dataframe_id` is optional. If `result` is a DataFrame it is stored; any other value is returned as a string; no assignment returns "Code executed successfully."

**Rationale:** The tool description shapes how Claude uses it. A description that says "pandas transform" causes Claude to think only in terms of DataFrame-in/DataFrame-out. Broadening the framing — and relaxing the `result` contract — lets Claude compute scalars, run statistical tests, and fit models without being forced to wrap everything in a one-row DataFrame. The exec namespace (`df`, `pd`, `np`) is unchanged; Claude can `import` anything installed.

---

## `save_file` tool: downloadable file exports

**Decision:** A `save_file(dataframe_id, filename, format)` tool writes to `exports/` and renders a `st.download_button` in the conversation. Supported formats: CSV, Excel, Parquet.

**Rationale:** Covers the "email me this data" workflow that a Jupyter user handles with `df.to_csv()`. Without it, there is no way to produce a downloadable artifact mid-conversation. The tool is narrow by design — it does not write arbitrary files, only dataframes in one of three formats. `exports/` is gitignored. On conversation reload, `save_file` is included in the replay list so download buttons survive session resumption.

---

## No `render_html` tool

**Decision:** Do not add a general HTML rendering tool.

**Rationale:** The structured-output property of the current tools — Plotly figures reproducible from code, dataframes embeddable as CSV — is what makes `/snapshot` and `/report` work. An HTML blob is opaque: it cannot be reproduced from code or embedded as data. Claude will gravitate toward the most expressive tool available; if `render_html` exists it will use it for cases where `render_chart` would have been better, and those outputs will not be reproducible in generated reports. If a specific visualisation need arises that Plotly genuinely cannot handle, solve it then as a narrowly scoped tool for that case.

---

## Exec namespace: static string in system prompt, not a tool

**Decision:** The variables and packages available inside `run_python` and `render_chart` are documented as a static string block injected into the system prompt at session start, not exposed via an "inspect environment" tool.

**Rationale:** What Claude needs is not the Python source of the tool wrappers — it needs to know what names are in scope inside each `exec`. That is a documentation problem, not a tooling problem. A static string is cheaper than a tool call, more reliable than Claude inferring namespace contents from source code, and does not consume a turn before analysis begins. The installed package list changes rarely; a static list updated when `requirements.txt` changes is more reliable than dynamic `pip list` introspection.

---

## Entry screen list: st.radio, not buttons

**Decision:** The conversation list uses `st.radio` with `index=None` (nothing pre-selected). Clicking an item triggers `on_change` which navigates immediately.

**Rejected:** Styled `st.button` per row. Full-width buttons have inherent padding and centered text that can't be reliably overridden via CSS injection — Streamlit's emotion-generated class names are unstable and `data-testid` selectors don't reliably reach the inner flex container that controls alignment.

**Rationale:** `st.radio` is natively left-aligned, compact, and single-click. `index=None` ensures every click is a value change, so the first item in the list is always clickable. No CSS needed.

---

## Image upload: popover above chat input, not same row

**Decision:** The `st.popover("📎")` image upload button renders above `st.chat_input`, not on the same row.

**Rationale:** `st.chat_input` is a fixed-position widget pinned to the bottom of the viewport that does not participate in Streamlit column layouts. Placing other widgets in `st.columns()` alongside it has no effect on `st.chat_input`'s position. True same-row placement requires CSS injection via `st.markdown("<style>...")`, which conflicts with the project's no-custom-HTML principle.

In practice the positioning is fine: when conversation content fills the page the popover button naturally sits just above the chat bar. It only appears displaced when the conversation is short and content sits near the top.

---

## Stay on Streamlit

**Decision:** Streamlit remains the UI framework. No migration to Panel, Gradio, or a custom frontend.

**Rationale:** Streamlit provides a chat UI, rich interactive output primitives (`st.dataframe`, `st.plotly_chart`), and generated reports that are readable Python deployable with one command. The constraints it imposes — synchronous reruns, linear layout, no persistent client state — are not currently blocking real analytical workflows.

Revisit if either of these become genuine pain points:
- Long conversations where the analyst needs to reference an earlier chart while asking a new question (pinning / side-by-side layout).
- Tool loops longer than ~20 seconds where streaming would meaningfully improve the experience.

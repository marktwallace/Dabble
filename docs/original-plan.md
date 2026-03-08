# list-pet v2 Build Plan

One file at a time. Review after each before proceeding.

## Files

1. `src/duckdb_analytic.py` — clean up from v1. Keep hot-swap and connection management. Remove excessive debug logging.

2. `src/chart_renderer.py` — rewrite from scratch. Same concept: exec Plotly code, return (fig, error). Add `px` (plotly.express) to the namespace alongside `go`.

3. `src/knowledge_base.py` — new. Thin ChromaDB wrapper: `search(query)`, `add_chunk(text, metadata)`, `rebuild_from_directory(path)`. Embeddings via OpenAI text-embedding-3-small.

4. `src/claude_handler.py` — new. ClaudeHandler class: 5 tool definitions, synchronous tool loop, `generate_title()`. Tool results returned to Claude as structured text summaries (same format as conversation file), not raw JSON rows.

5. `src/conversation_file.py` — new. Incremental write to `conversations/` text files. DataFrame tool results formatted as structured text summary (value counts, min/max/mean, date range, head+tail sample). Full tool calls and results preserved — nothing stripped.

6. `src/pages/entry.py` — new. Streamlit entry screen. Conversation list sorted newest first (title + date from filename and first line). "New conversation" button.

7. `src/pages/conversation.py` — new. Streamlit conversation view. `st.chat_input()` only input. Spinner during tool loop. Assistant turns render: expanders per tool call (open for most recent turn, closed for older), `st.dataframe()` for show_table, `st.plotly_chart()` for render_chart, narrative text. Handles /learn and /presentation commands.

8. `src/pages/learn_review.py` — new. /learn confirmation screen. Shows extracted chunks with approve/reject per chunk. Confirmed chunks saved to `knowledge/` and loaded into ChromaDB.

9. `app.py` — rewrite. Top-level Streamlit multi-page entry point.

10. `tools/seed_knowledge_base.py` — new. One-time script: load `knowledge/` directory into ChromaDB. Run by developer when setting up a domain overlay.

11. `tools/rebuild_knowledge_base.py` — new. Clear and reload ChromaDB from `knowledge/`. Run when re-embedding is needed.

## Also needed before the app runs

- `requirements.txt` — update: add anthropic, chromadb, numpy; remove langchain*, openai, and other legacy deps.
- `prompts/system_prompt.txt` — rewrite for tool-calling (compact, no @include).
- `prompts/title.txt` — keep as-is.
- `prompts/welcome_message.txt` — rewrite (remove old XML reasoning tag).
- `conversations/` — directory exists (has example.txt).
- `knowledge/` — create empty directory.
- `reports/` — create empty directory.

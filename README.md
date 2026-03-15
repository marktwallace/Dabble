# Dabble

A conversational data analysis tool built on Claude's native tool loop. You ask questions in plain English; it queries DuckDB, renders Plotly charts, and produces shareable outputs.

The tool surface is deliberately small: five tools — `run_sql`, `show_table`, `render_chart`, `run_python`, `search_knowledge_base` — that form a complete analytical loop. Claude isn't writing arbitrary code; it's operating a coherent set of instruments. When `render_chart` returns a traceback, Claude reads it, fixes the code, and retries without the user seeing it. When a SQL query returns unexpected nulls, Claude investigates before reporting results.

DuckDB is not an incidental choice. It is fast, embedded, and SQL-native — Claude can query CSV files, Parquet, or a persistent database file with nothing between it and the data. The query-result-iterate loop runs in milliseconds.

## Outputs

Every session can produce shareable artifacts directly from the conversation:

**`/snapshot`** — a self-contained HTML file. Charts and tables are rendered as interactive Plotly figures. Open in any browser or email as an attachment — no Python required.

**`/report`** — a parameterized Streamlit app that connects to DuckDB at runtime. Claude reads the full conversation to identify parameters (date ranges, filters, groupings) and generates appropriate widgets. The output is an intentionally readable Python file the analyst can open in an editor and extend.

**`/notebook`** — a [Marimo](https://marimo.io) reactive notebook. Change a date slider and downstream SQL and charts update automatically. Stored as a plain `.py` file; can be served as an app or edited in an IDE. The analyst owns an artifact they can extend without Dabble.

## Knowledge base

`/learn` extracts analytical sequences from a conversation — the SQL that worked, the iteration that got there, the domain correction that made results correct — and lets you approve each chunk before saving it to ChromaDB. Future sessions retrieve this context via semantic search before each question. Domain knowledge accumulates from real sessions rather than being pre-authored.

## Getting started

**Bootstrap mode:** point `DUCKDB_ANALYTIC_FILE` at a new path and start asking questions.

> "Import data/mydata.csv"

Claude inspects the file, creates a persistent table, and you begin exploring immediately.

**Domain overlay mode:** for sustained use, a separate (typically private) repository provides a system prompt, seed knowledge base, and pre-populated DuckDB file, wired to Dabble via `.env`. Dabble itself knows nothing about any specific domain — the overlay is what makes it accurate for a given context.

## Setup

**Prerequisites:** conda (recommended — macOS system Python is unreliable across OS upgrades)

```bash
git clone <repo_url>
cd list-pet
conda create -n dabble python=3.12
conda activate dabble
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `OPENAI_API_KEY` | Yes | ChromaDB embeddings (text-embedding-3-small) |
| `DUCKDB_ANALYTIC_FILE` | Yes | Path to your DuckDB file (created on first run if absent) |
| `KB_PATH` | Yes | Path for the ChromaDB knowledge base directory |
| `CONVERSATIONS_DIR` | No | Conversation files (default: `conversations`) |
| `KNOWLEDGE_DIR` | No | Knowledge `.txt` files (default: `knowledge`) |
| `DB_TIMESTAMP_QUERY` | No | SQL to read a data freshness timestamp |

```bash
streamlit run app.py
```

## Knowledge base tools

```bash
python -m tools.seed_knowledge_base      # load knowledge/ into ChromaDB
python -m tools.rebuild_knowledge_base   # clear and reload from knowledge/
```

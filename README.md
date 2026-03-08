# list-pet

A conversational data analysis tool built on Claude's native tool loop. You ask questions in plain English; it queries DuckDB, renders Plotly charts, and produces standalone Streamlit reports to share with colleagues.

The core idea is simple: give Claude a small set of tools — query DuckDB, transform with pandas, render a Plotly chart, search a knowledge base — and let it reason freely within them. No agent framework. No pre-drawn analysis steps. Five tools that form a complete analytical loop, run synchronously until Claude has something worth showing. The architecture fits in a short code review; if a file gets long, the design is probably wrong.

DuckDB is not an incidental choice. It is fast, embedded, and SQL-native — Claude can query CSV files, Parquet, or a persistent database file with nothing between it and the data. No connection pool, no server to restart, no ORM. The query-result-iterate loop runs in milliseconds, which is what makes conversational analysis feel responsive rather than tedious, and what separates this from tools that treat the database as a distant service.

## Why this works differently from a general-purpose coding assistant

The tool surface is small and deliberately domain-specific: five tools — `run_sql`, `show_table`, `render_chart`, `run_python`, `search_knowledge_base` — that form a complete analytical loop. None of them is interesting in isolation. Together they cover the full cycle: query data, display it, visualize it, iterate on a chart without re-querying, apply a pandas transform when SQL isn't enough, and retrieve prior domain context. The constraint matters: Claude isn't writing arbitrary code, it's operating a coherent set of instruments.

The tool loop itself is about 30 lines. Send messages to Claude, execute tool calls locally when Claude requests them, append results, repeat until Claude stops. No agent framework, no queuing machinery, no intermediate state flags. It runs synchronously as a single Streamlit render pass. Anthropic's prompt caching makes multi-step loops fast — the stable context (system prompt, earlier turns) is cached server-side, so each iteration only re-evaluates new tool results.

## Why now and not 18 months ago

This architecture is simple enough that it should have worked earlier. It didn't, reliably. The threshold Claude 4.x crossed isn't general capability — it's **reliable multi-step tool use with self-correction**. When `render_chart` returns a traceback, Claude reads it, fixes the code, and retries without the user seeing it. When a SQL query returns unexpected nulls, Claude investigates before reporting results. That loop — call tool, read result as evidence, adjust — is what makes the tool feel like a real analyst rather than an unreliable script. The model quality needed to cross that bar arrived in early 2025.

## The knowledge base

The `/learn` command extracts analytical sequences from a conversation — the SQL that worked, the iteration that got there, the domain correction that made results correct — and lets you approve each chunk before saving it to ChromaDB. Future sessions retrieve this context via semantic search at the start of a new question. The knowledge base grows from real sessions rather than being manually authored. It's how domain knowledge (which columns are reliably populated, what NULL means in a given context, how to join these two tables correctly) accumulates over time.

## Reports

`/report` generates a standalone Streamlit `.py` file: the chart's dataframe is embedded as a CSV literal, and the Plotly code Claude produced is reproduced verbatim. No list-pet dependency. The analyst runs `streamlit run reports/<file>.py` and gets the exact same chart they saw in the conversation.

---

## Setup

**Prerequisites:** conda (recommended — macOS system Python is unreliable across OS upgrades)

```bash
git clone <repo_url>
cd list-pet
conda create -n list-pet python=3.12
conda activate list-pet
pip install -r requirements.txt
```

**Configure environment:**

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `OPENAI_API_KEY` | Yes | Used for ChromaDB embeddings (text-embedding-3-small) |
| `DUCKDB_ANALYTIC_FILE` | Yes | Path to your DuckDB file (created automatically if it doesn't exist) |
| `KB_PATH` | Yes | Path for the ChromaDB knowledge base directory (e.g. `db/knowledge_base`) |
| `CONVERSATIONS_DIR` | No | Where to store conversation files (default: `conversations`) |
| `KNOWLEDGE_DIR` | No | Where to store knowledge .txt files (default: `knowledge`) |
| `DB_TIMESTAMP_QUERY` | No | SQL to read a data freshness timestamp (e.g. `SELECT max(updated_at) FROM etl_log`) |

## Running

```bash
streamlit run app.py
```

The DuckDB file and ChromaDB directory are created automatically on first run.

## Starting with an empty database

Point `DUCKDB_ANALYTIC_FILE` at a new path (e.g. `db/mydata.duckdb`). The file will be created when the app starts. Then ask list-pet to import your data:

> "Import data/playlist.csv"

Claude will inspect the file, confirm the column names, and create a persistent table.

## Knowledge base

**To seed from existing `.txt` files in `knowledge/`:**

```bash
python -m tools.seed_knowledge_base
```

**To clear and rebuild from scratch:**

```bash
python -m tools.rebuild_knowledge_base
```

**To add knowledge from a conversation:** type `/learn` during a session. list-pet extracts useful sequences and lets you approve each chunk before saving.

## Conversation files

Each conversation is saved as a plain text file in `conversations/`. These files are the complete record — SQL queries, tool results, and narrative — and are the source material for `/learn`.

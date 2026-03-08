# list-pet

A conversational data analysis assistant. Ask questions about your data in plain English — list-pet queries DuckDB, renders Plotly charts, and builds up a knowledge base of what works in your domain.

Built with Claude (Anthropic) for reasoning, DuckDB for data, ChromaDB for semantic search, and Streamlit for the UI.

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

If you don't have an existing DuckDB file, just point `DUCKDB_ANALYTIC_FILE` at a new path (e.g. `db/mydata.duckdb`). The file will be created when the app starts. Then ask list-pet to import your data:

> "Import data/playlist.csv"

Claude will inspect the file, confirm the column names, and create a persistent table.

## Knowledge base

The knowledge base stores domain context and successful analysis sequences for reuse across sessions.

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

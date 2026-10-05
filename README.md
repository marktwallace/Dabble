# Dabble

A conversational data analysis tool built on Claude's native tool loop. You ask questions in plain English; it queries DuckDB, renders Plotly charts, and produces shareable outputs.

The tool surface is deliberately small: `run_sql`, `show_table`, `render_chart`, `run_python` and `save_file` form a complete analytical loop, and `recall_knowledge`, `update_knowledge` and `delete_knowledge` read and curate the knowledge base. Claude isn't writing arbitrary code; it's operating a coherent set of instruments. When `render_chart` returns a traceback, Claude reads it, fixes the code, and retries without the user seeing it. When a SQL query returns unexpected nulls, Claude investigates before reporting results.

DuckDB is not an incidental choice. It is fast, embedded, and SQL-native — Claude can query CSV files, Parquet, or a persistent database file with nothing between it and the data. The query-result-iterate loop runs in milliseconds.

## Outputs

Every session can produce shareable artifacts directly from the conversation:

**`/snapshot`** — a self-contained HTML file. Charts and tables are rendered as interactive Plotly figures. Open in any browser or email as an attachment — no Python required.

**`/report`** — a parameterized Streamlit app that connects to DuckDB at runtime. Claude reads the full conversation to identify parameters (date ranges, filters, groupings) and generates appropriate widgets. The output is an intentionally readable Python file the analyst can open in an editor and extend.

**`/notebook`** — a [Marimo](https://marimo.io) reactive notebook. Change a date slider and downstream SQL and charts update automatically. Stored as a plain `.py` file; can be served as an app or edited in an IDE. The analyst owns an artifact they can extend without Dabble.

## Knowledge base

`/learn` extracts analytical sequences from a conversation — the SQL that worked, the iteration that got there, the domain correction that made results correct — and lets you approve each chunk before saving it as a `.txt` file in `knowledge/`. Each session's system prompt lists every chunk's description, and Claude calls `recall_knowledge` to read the ones that bear on the question. Domain knowledge accumulates from real sessions rather than being pre-authored.

## Getting started

**Bootstrap mode:** point `DUCKDB_ANALYTIC_FILE` at a new path and start asking questions.

> "Import data/mydata.csv"

Claude inspects the file, creates a persistent table, and you begin exploring immediately.

**Domain overlay mode:** for sustained use, a separate (typically private) repository provides a system prompt, seed knowledge base, and pre-populated DuckDB file, wired to Dabble via `.env`. Dabble itself knows nothing about any specific domain — the overlay is what makes it accurate for a given context.

## Setup

**Prerequisites:** [uv](https://docs.astral.sh/uv/)

```bash
git clone <repo_url>
cd dabble
uv sync
```

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `CLAUDE_PROVIDER` | No | `anthropic` (default): the Claude API. `bedrock`: Amazon Bedrock's `bedrock-runtime` endpoint, signed with the AWS credentials found the usual way (instance or task role, profile, or keys) |
| `ANTHROPIC_API_KEY` | With `anthropic` | Claude API key |
| `AWS_REGION` | With `bedrock` | Region of the Bedrock endpoint, e.g. `us-east-1` |
| `CLAUDE_MODEL` | Yes | Model every request uses (e.g. `claude-opus-5-5`; on Bedrock a model or inference profile ID such as `us.anthropic.claude-opus-5-5`); also named to the model in its system prompt |
| `DUCKDB_ANALYTIC_FILE` | One database mode | Path to your DuckDB file (created on first run if absent) |
| `DUCKDB_READ_ONLY` | No | `1`, `true` or `yes` opens the DuckDB file read-only |
| `DABBLE_S3_BUCKET` | One database mode | DuckLake on S3: catalog downloaded from `s3://<bucket>/<prefix>/catalog.duckdb` at start and on `/refresh`, data read from `<prefix>/data/` |
| `DABBLE_S3_PREFIX` | No | Prefix within the bucket (default: `prod`) |
| `DABBLE_DATA_PATH` | One database mode | DuckLake synced to a local directory holding `catalog.duckdb` and `data/` |
| `DABBLE_DB_NAME` | With a DuckLake | Catalog alias; must match what the writer used |
| `DABBLE_EXTRA_CATALOGS` | No | More DuckLake catalogs, attached read-only beside the main database in any mode: comma-separated `name=<catalog>`, each attached as `ATTACH 'ducklake:<catalog>' AS name`, so it uses the data path recorded in its catalog. A catalog file on S3 (`s3://…`) is downloaded first; any other value is passed to `ATTACH` as is. Tables are queried as `name.table` and listed so in the system prompt's schema |
| `PROMPTS_DIR` | No | Directory holding `system_prompt.md` and the documents `read_document` reads (default: `prompts`) |
| `CONVERSATIONS_DIR` | No | Conversation files (default: `conversations`) |
| `KNOWLEDGE_DIR` | No | Knowledge `.txt` files (default: `knowledge`) |
| `UPLOADS_DIR`, `REPORTS_DIR`, `NOTEBOOKS_DIR` | No | Uploaded files, `/report` and `/notebook` outputs (defaults: `uploads`, `reports`, `notebooks`) |
| `DB_TIMESTAMP_QUERY` | No | SQL to read a data freshness timestamp (file mode; DuckLake modes use the latest snapshot time) |
| `CLAUDE_EFFORT` | No | Effort level sent with every request (`low`, `medium`, `high`, `xhigh`, `max`); unset uses the model's default |
| `CLAUDE_THINKING_BLOCK_BINDING` | No | `drop_block` or `error`. For models that tie thinking blocks to their conversation: what the API does with earlier thinking blocks a resumed conversation no longer matches |
| `INSTANCE_CONTEXT` | No | Text added to the system prompt after the date line — e.g. which environment's data this instance reads |

```bash
uv run streamlit run app.py
```

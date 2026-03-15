# Next Step: Parquet as the Primary Data Store

## Architecture Overview

The ETL pipeline runs on an EC2 instance with fast local storage. It pulls from Postgres nightly (or more frequently) and writes Parquet files to local disk. Dabble reads from those local files. After each ETL run, the Parquet files are synced to S3, making them available to colleagues running shared reports or working on laptops.

```
Postgres
    └── ETL (EC2, nightly)
            └── Parquet files (EC2 local disk)
                    ├── Dabble reads directly (fast, no network hop)
                    └── S3 sync (async, after ETL completes)
                                ├── Shared reports connect to S3
                                └── Analysts sync to laptop for local notebooks
```

The `.duckdb` file is eliminated. Parquet is the single source of truth. The ETL has one output format and no knowledge of its consumers.

---

## Partitioning

Use Hive-style partitioning — one directory per table, subdivided by month:

```
/data/dabble/
    samples/
        year=2025/month=01/data.parquet
        year=2025/month=02/data.parquet
        ...
        year=2026/month=03/data.parquet
    patients/
        year=2025/month=01/data.parquet
        ...
```

**Why monthly partitions at this scale (40–60 GB, 1–2 years):**

- Monthly partitioning produces 12–24 files per table, each roughly 2–5 GB — a good Parquet file size.
- DuckDB reads multiple files in parallel across threads. Full-table scans over 24 files are no slower than a single 50 GB file; the S3/disk throughput is the bottleneck either way.
- Queries filtered by month or year benefit from partition pruning — DuckDB skips irrelevant files entirely and only reads what it needs. For Dabble's typical queries ("last month's trend," "this quarter vs. last"), this is a significant win.
- The ETL only rewrites the current month's partition on each run. A nightly incremental update writes ~2–5 GB rather than the full 50 GB. S3 sync uploads only the changed file.
- Late-arriving data that falls in a past month requires rewriting that historical partition. Whether this is a concern depends on your Postgres pipeline.

---

## DuckDB Views for Transparent Queries

Dabble (and generated reports) use DuckDB views to map table names to Parquet paths. All SQL generated during a session works without modification — it sees table names, not file paths.

**Dabble on EC2 (local paths):**

```python
con = duckdb.connect()
con.execute("""
    CREATE VIEW samples AS
    SELECT * FROM read_parquet('/data/dabble/samples/**/*.parquet', hive_partitioning=true)
""")
# All Dabble-generated SQL works unchanged:
df = con.execute("SELECT week, avg_abundance FROM samples WHERE ...").df()
```

**Shared report on a colleague's machine (S3):**

```python
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")
con.execute("""
    CREATE VIEW samples AS
    SELECT * FROM read_parquet('s3://internal-bucket/dabble/samples/**/*.parquet', hive_partitioning=true)
""")
# Identical SQL — same queries, same results
```

**Analyst on a laptop (after `aws s3 sync`):**

```bash
aws s3 sync s3://internal-bucket/dabble/ ~/data/dabble/ --delete
```

```python
con = duckdb.connect()
con.execute("""
    CREATE VIEW samples AS
    SELECT * FROM read_parquet('~/data/dabble/samples/**/*.parquet', hive_partitioning=true)
""")
```

The view preamble is the only thing that changes across environments. The SQL is identical everywhere.

---

## Dabble Changes

### Connection initialisation

Replace the `DUCKDB_ANALYTIC_FILE` connection with a view-based in-memory connection. At session start, Dabble reads `DABBLE_DATA_PATH` (local) or `DABBLE_S3_PREFIX` (remote) from the environment, discovers table names from the directory structure, and creates one view per table.

```python
DATA_PATH = os.environ.get("DABBLE_DATA_PATH")   # /data/dabble
S3_PREFIX  = os.environ.get("DABBLE_S3_PREFIX")  # s3://bucket/dabble
```

If `DABBLE_DATA_PATH` is set, use local paths. If `DABBLE_S3_PREFIX` is set, load `httpfs` and use S3 paths. Exactly one should be set; fail loudly if neither or both are.

### Schema injection

`_build_schema_context()` currently runs `SHOW TABLES` and `DESCRIBE <table>` against the DuckDB connection. This continues to work unchanged — after views are created, DuckDB exposes them as tables to these introspection queries.

### Generated reports and notebooks

The report and notebook generators receive the table list (already available from schema injection) and emit the appropriate view-creation preamble based on whether `DABBLE_DATA_PATH` or `DABBLE_S3_PREFIX` is set. The startup command shown on the review screen changes accordingly:

```bash
# Local (EC2 or laptop after sync)
DABBLE_DATA_PATH=/data/dabble streamlit run report_2026-03-14_....py

# S3
DABBLE_S3_PREFIX=s3://internal-bucket/dabble streamlit run report_2026-03-14_....py
```

### Optional: httpfs caching

For S3 access, DuckDB's object cache reduces redundant downloads on repeated queries:

```python
con.execute("SET enable_http_metadata_cache=true;")
con.execute("SET enable_object_cache=true;")
```

Not needed for local paths.

---

## ETL Changes

- Remove the DuckDB write step entirely.
- Add a Parquet write step: for each table, append new rows to the current month's partition file (or rewrite it if simpler).
- After writing, sync to S3:

```bash
aws s3 sync /data/dabble/ s3://internal-bucket/dabble/ --delete
```

Run the sync as the final ETL step. It uploads only changed files.

---

## Mid-ETL Availability: Hot-Swap

`src/duckdb_analytic.py` already implements a hot-swap protocol for `.duckdb` files. The same pattern applies to Parquet:

- ETL writes new partition files to a staging directory (`/data/dabble-new/`)
- When the ETL completes cleanly, it atomically renames `/data/dabble-new/` to `/data/dabble/`, keeping the previous directory as `/data/dabble-old/` as a fallback
- Dabble detects the swap on the next query and re-creates its views against the new files
- If the swap fails, `/data/dabble-old/` is restored

This means Dabble always reads from a complete, consistent snapshot. A query mid-ETL sees the previous night's data, not a partially-written one. The swap is a directory rename — atomic on Linux filesystems.

The hot-swap feature is planned but not yet implemented for the Parquet layout. It should be built alongside the Parquet migration.

---

## Limitations

- **Very frequent ETL.** If the ETL runs every 15 minutes, rewriting even a single monthly partition file 96 times a day is wasteful. For sub-hourly refresh, consider appending small Parquet files and periodically compacting them, or keeping a small `.duckdb` for intraday data and merging at EOD.
- **Write access.** Views over Parquet are read-only. This is correct for Dabble's use case.

---

## Architectural Context

This pattern is an instance of the **data lakehouse** model — Hive-partitioned Parquet as the source of truth, with a lightweight query engine (DuckDB) reading it directly without a server process. It is the same architectural idea behind Delta Lake, Apache Iceberg, and AWS Athena, scaled down to a single EC2 instance.

The combination of Hive-partitioned Parquet, DuckDB views for query transparency, and S3 as a distribution layer is well-documented and in wide production use. It is what teams use when they have outgrown Postgres for analytics but do not need (or want) Snowflake, Redshift, or BigQuery. Tools like dbt + DuckDB and Evidence.dev use this layout as their recommended production setup.

The local-first variant here — EC2 local disk as Dabble's primary store, S3 as secondary distribution — is smarter than pure S3-first at this scale. Dabble gets lakehouse portability and sharing without paying S3 latency on every query. Colleagues and laptop analysts pay that latency only when they need to, and can avoid it entirely with `aws s3 sync`.

# Smoke Test Plan

Covers changes from 2026-03-26: `/refresh` command, `/learn` fixes (delete-before-add, save-zero-chunks), S3/DuckLake connection mode, ETL CHECKPOINT, and ETL `--mode singlefile`.

**Note:** `/kb rebuild` is documented but not yet implemented. Skip it.

Both ETL modes are production paths. Single-file DuckDB and DuckLake are run in parallel while DuckLake matures toward 1.0.

---

## 1. ETL single-file mode (EC2)

Produces a plain DuckDB file — no S3, no Parquet, no DuckLake dependency.

**Run:**

```bash
cd ~/agent-single-file
ENV_FILE=etl.env ./run_etl_nohup.sh --db db/diagonal.duckdb --mode singlefile --start-date 2026-03-23 --verbose
tail -f logs/etl_staged_*.log
```

**Expected log lines:**

```
Mode    : singlefile
DB path : /home/ubuntu/agent-single-file/db/diagonal.duckdb
...
ETL complete — sruns=... records=... watermark=...
Single-file mode: output at .../diagonal.duckdb
```

---

## 2. Dabble single-file mode (EC2)

**`.env` (relevant lines):**

```
DUCKDB_ANALYTIC_FILE=/home/ubuntu/agent-single-file/db/diagonal.duckdb
# DABBLE_S3_BUCKET must be unset (or absent)
# DABBLE_DATA_PATH must be unset (or absent)
```

- Start Dabble, ask a question that hits the DB — confirm data returns
- Type `/refresh` — should respond: `Database refreshed. Data as of: ...`

---

## 3. ETL DuckLake mode + S3 (EC2)

Uses the existing `~/agent-dimensional-test/` repo (already on `ducklake` branch). Switch from single-file mode by editing `etl.env` to enable S3 sync.

**How S3 sync is controlled:**
`DIAGONAL_S3_BUCKET` in the ETL's environment is the only switch. If it is set, the ETL runs `CHECKPOINT` then syncs to S3. If absent or empty, the ETL writes locally and exits — no S3 activity, no error.

**Edit `~/agent-dimensional-test/etl.env`** — comment out the singlefile DB path and add S3 vars:

```bash
# export DUCKDB_ANALYTIC_FILE="/home/ubuntu/agent-dimensional-test/db/diagonal.duckdb"
export DUCKDB_ANALYTIC_FILE="/home/ubuntu/agent-dimensional-test/db/catalog.duckdb"
export DIAGONAL_S3_BUCKET=qcagent.kariusdx.com
export DIAGONAL_S3_PREFIX="smoke-test"
```

**Verify the env before running:**

```bash
cd ~/agent-dimensional-test
source etl.env && echo "bucket: $DIAGONAL_S3_BUCKET"
# Must print: bucket: qcagent.kariusdx.com
# If it prints "bucket:" the variable is missing — stop and fix etl.env first.
```

**Run:**

```bash
ENV_FILE=etl.env ./run_etl_nohup.sh --db db/catalog.duckdb --start-date 2026-03-23 --verbose
tail -f logs/etl_staged_*.log
```

**Expected log lines (in order):**

```
Mode    : ducklake
DB path : /home/ubuntu/agent-dimensional-test/db/catalog.duckdb
...
ETL complete — sruns=... records=... watermark=...
Running CHECKPOINT before S3 sync
Syncing to s3://qcagent.kariusdx.com/smoke-test
...
S3 sync complete: N uploaded, 0 unchanged
```

If you see `No changes detected. Nothing to do.` — no data in the date range. Try an earlier `--start-date`.

If you see `ETL complete` but no `Running CHECKPOINT` — `DIAGONAL_S3_BUCKET` was not in the Python process's environment. Re-check the env verify step above.

**Confirm S3:**

```bash
aws s3 ls s3://qcagent.kariusdx.com/smoke-test/ --recursive
# Expect: catalog.duckdb and data/ parquet files
```

---

## 4. Dabble DuckLake/S3 mode (EC2)

Point Dabble at the smoke-test prefix written in test 3.

**`.env` (relevant lines):**

```
DABBLE_S3_BUCKET=qcagent.kariusdx.com
DABBLE_S3_PREFIX=smoke-test
DABBLE_DB_NAME=diagonal
# DUCKDB_ANALYTIC_FILE must be unset (or absent)
# DABBLE_DATA_PATH must be unset (or absent)
```

- Start Dabble, ask a question — confirm data returns from S3
- Type `/refresh` — confirm response includes a valid timestamp

---

## 5. `/learn` re-learn replaces previous entries

Pick a conversation that was previously learned from.

- Run `/learn` on it again with a different chunk selection than before
- After saving, run `/kb <something from the old selection>` — old chunk should not appear
- Run `/kb <something from the new selection>` — new chunk should appear

---

## 6. `/learn` save zero chunks

- Run `/learn` on any conversation, uncheck all chunks, click Save
- Confirm Save button is not disabled and the save completes
- Run `/kb` — entries for that conversation's source file should be gone

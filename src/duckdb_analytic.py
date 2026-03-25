import os
import tempfile
from datetime import datetime, timezone

import duckdb


class DuckDBAnalytic:
    """
    Two modes, selected by environment variables:

    S3/DuckLake mode  — DABBLE_S3_BUCKET is set.
        Downloads catalog.duckdb from S3 at init and on refresh().
        Attaches via DuckLake with OVERRIDE_DATA_PATH pointing to S3.
        Prefix defaults to DABBLE_S3_PREFIX (default: "prod").

    Local file mode   — DUCKDB_ANALYTIC_FILE is set.
        Opens a plain DuckDB file directly. No S3 involved.
    DuckLake mode requires DABBLE_DB_NAME — the catalog alias and metadata catalog
    base name. This must match what the ETL used when writing.

    """

    def __init__(self):
        self.conn = None
        self.cached_timestamp = None
        self._local_catalog_path = None  # temp file path in S3 mode
        self._connect()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self):
        s3_bucket = os.environ.get("DABBLE_S3_BUCKET")
        if s3_bucket:
            self._connect_ducklake(s3_bucket)
        else:
            self._connect_local()
        self.cached_timestamp = self._query_timestamp()

    def _db_name(self) -> str:
        name = os.environ.get("DABBLE_DB_NAME")
        if not name:
            raise RuntimeError("DABBLE_DB_NAME is required for DuckLake mode")
        return name

    def _connect_ducklake(self, bucket: str):
        prefix = os.environ.get("DABBLE_S3_PREFIX", "prod")

        import boto3
        s3 = boto3.client("s3")

        # Download catalog to a temp file (overwrite on refresh)
        if self._local_catalog_path is None:
            tmp = tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False)
            self._local_catalog_path = tmp.name
            tmp.close()

        s3.download_file(bucket, f"{prefix}/catalog.duckdb", self._local_catalog_path)

        if self.conn:
            self.conn.close()

        self.conn = duckdb.connect()
        self.conn.execute("SET TimeZone = 'UTC'")
        self.conn.execute("INSTALL ducklake; LOAD ducklake;")
        self.conn.execute("INSTALL httpfs; LOAD httpfs;")
        # Force path-style URLs — buckets with dots in the name don't work with
        # virtual-hosted-style (https://<bucket>.s3.amazonaws.com) over HTTPS
        # because AWS can't issue a wildcard cert for dotted subdomains.
        self.conn.execute("SET s3_url_style = 'path';")
        db_name = self._db_name()
        self.conn.execute(f"""
            ATTACH 'ducklake:{self._local_catalog_path}' AS {db_name} (
                DATA_PATH 's3://{bucket}/{prefix}/data/',
                METADATA_CATALOG '{db_name}_meta',
                OVERRIDE_DATA_PATH TRUE
            )
        """)
        self.conn.execute(f"USE {db_name}")
        self._assert_tables_exist(self._local_catalog_path)

    def _connect_local(self):
        data_path = os.environ.get("DABBLE_DATA_PATH")
        if data_path:
            self._connect_ducklake_local(data_path)
            return
        db_path = os.environ.get("DUCKDB_ANALYTIC_FILE")
        if not db_path:
            return
        read_only = os.environ.get("DUCKDB_READ_ONLY", "").lower() in ("1", "true", "yes")
        if self.conn:
            self.conn.close()
        self.conn = duckdb.connect(db_path, read_only=read_only)
        self.conn.execute("SET TimeZone = 'UTC'")

    def _connect_ducklake_local(self, data_path: str):
        """Attach a locally synced DuckLake catalog (catalog.duckdb + data/ directory)."""
        import os as _os
        catalog_path = _os.path.join(data_path, "catalog.duckdb")
        parquet_data = _os.path.join(data_path, "data")
        if not _os.path.exists(catalog_path):
            raise FileNotFoundError(f"DuckLake catalog not found: {catalog_path}")
        if self.conn:
            self.conn.close()
        self.conn = duckdb.connect()
        self.conn.execute("SET TimeZone = 'UTC'")
        self.conn.execute("INSTALL ducklake; LOAD ducklake;")
        db_name = self._db_name()
        self.conn.execute(f"""
            ATTACH 'ducklake:{catalog_path}' AS {db_name} (
                DATA_PATH '{parquet_data}/',
                METADATA_CATALOG '{db_name}_meta',
                OVERRIDE_DATA_PATH TRUE
            )
        """)
        self.conn.execute(f"USE {db_name}")
        self._assert_tables_exist(catalog_path)

    def _assert_tables_exist(self, catalog_path: str):
        tables = self.conn.execute("SHOW TABLES").fetchall()
        if not tables:
            raise RuntimeError(
                f"DuckLake attached but contains no tables — catalog may be empty or corrupt: {catalog_path}"
            )

    # ------------------------------------------------------------------
    # Refresh (replaces hot-swap)
    # ------------------------------------------------------------------

    def refresh(self) -> bool:
        """Re-download catalog (S3 mode) or reconnect (local mode) and update timestamp."""
        try:
            self._connect()
            return True
        except Exception as e:
            print(f"Refresh failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def execute_query(self, sql: str) -> tuple:
        """Execute SQL. Returns (DataFrame | None, error_message | None)."""
        try:
            if not self.conn:
                raise RuntimeError("No database connection")
            return self.conn.execute(sql).fetchdf(), None
        except Exception as e:
            return None, str(e)

    # ------------------------------------------------------------------
    # Timestamp
    # ------------------------------------------------------------------

    def _query_timestamp(self) -> str:
        if not self.conn:
            return "Unknown"

        # DuckLake mode: use snapshot log
        if os.environ.get("DABBLE_S3_BUCKET"):
            try:
                result = self.conn.execute("""
                    SELECT MAX(snapshot_time)
                    FROM ducklake_snapshots('{self._db_name()}')
                """).fetchone()
                if result and result[0]:
                    val = result[0]
                    if hasattr(val, "strftime"):
                        if val.tzinfo is None:
                            val = val.replace(tzinfo=timezone.utc)
                        return val.strftime("%Y-%m-%d %H:%M UTC")
                    return str(val)
            except Exception:
                pass
            return "Unknown"

        # Local file mode: use DB_TIMESTAMP_QUERY env var
        query = os.environ.get("DB_TIMESTAMP_QUERY")
        if not query:
            return "Unknown"
        try:
            result = self.conn.execute(query).fetchone()
            if not result or not result[0]:
                return "Unknown"
            val = result[0]
            if isinstance(val, str):
                try:
                    val = datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    return str(val)
            if hasattr(val, "strftime"):
                if val.tzinfo is None:
                    val = val.replace(tzinfo=timezone.utc)
                return val.strftime("%Y-%m-%d %H:%M UTC")
            return str(val)
        except Exception:
            return "Unknown"

    def get_timestamp(self) -> str:
        return self.cached_timestamp or "Unknown"

    # ------------------------------------------------------------------
    # Info / cleanup
    # ------------------------------------------------------------------

    def get_connection_info(self) -> dict:
        s3_bucket = os.environ.get("DABBLE_S3_BUCKET")
        if s3_bucket:
            prefix = os.environ.get("DABBLE_S3_PREFIX", "prod")
            path = f"s3://{s3_bucket}/{prefix}/"
        else:
            path = os.environ.get("DUCKDB_ANALYTIC_FILE", "unknown")
        return {
            "type": "DuckDB",
            "path": path,
            "connected": self.conn is not None,
            "last_updated": self.get_timestamp(),
        }

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            finally:
                self.conn = None
                self.cached_timestamp = None

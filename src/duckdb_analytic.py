import logging
import os
import re
import tempfile
from datetime import datetime, timezone

import duckdb

logger = logging.getLogger(__name__)


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

    Extra catalogs (any mode) — DABBLE_EXTRA_CATALOGS, comma-separated
        name=<catalog> entries. Each is attached read-only beside the main
        database as ATTACH 'ducklake:<catalog>' AS name (READ_ONLY), so it uses
        the data path recorded in its catalog; queries reach it as name.table.
        A catalog given as s3://... is downloaded first, since DuckDB does not
        open a database file from S3; any other value is passed to ATTACH as is.

    """

    def __init__(self):
        self.conn = None
        self.cached_timestamp = None
        self._local_catalog_path = None  # temp file path in S3 mode
        self._extra_catalog_paths = {}  # name -> temp file path
        self.extra_catalogs = []  # names attached beside the main database
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
        self._attach_extra_catalogs()
        self.cached_timestamp = self._query_timestamp()
        if self.conn:
            logger.info("Database ready: watermark=%s", self.cached_timestamp)

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

        logger.info("Downloading catalog from s3://%s/%s/catalog.duckdb", bucket, prefix)
        s3.download_file(bucket, f"{prefix}/catalog.duckdb", self._local_catalog_path)

        if self.conn:
            self.conn.close()

        self.conn = duckdb.connect()
        self.conn.execute("SET TimeZone = 'UTC'")
        self.conn.execute("INSTALL ducklake; LOAD ducklake;")
        self.conn.execute("INSTALL httpfs; LOAD httpfs;")
        # Use EC2 instance role (or any credential in the AWS default chain).
        # In-memory only — lives for the lifetime of this connection.
        self.conn.execute("CREATE SECRET s3_creds (TYPE S3, PROVIDER CREDENTIAL_CHAIN);")
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

    def _attach_extra_catalogs(self):
        """Attach each DABBLE_EXTRA_CATALOGS entry read-only beside the main database."""
        self.extra_catalogs = []
        entries = _parse_extra_catalogs(os.environ.get("DABBLE_EXTRA_CATALOGS", ""))
        if not entries:
            return
        if not self.conn:
            raise RuntimeError("DABBLE_EXTRA_CATALOGS is set but no main database is configured")
        # The same S3 access the DuckLake mode sets up, for catalogs or data on S3.
        self.conn.execute("INSTALL ducklake; LOAD ducklake;")
        self.conn.execute("INSTALL httpfs; LOAD httpfs;")
        self.conn.execute("CREATE SECRET IF NOT EXISTS s3_creds (TYPE S3, PROVIDER CREDENTIAL_CHAIN);")
        self.conn.execute("SET s3_url_style = 'path';")
        for name, catalog in entries:
            if catalog.startswith("s3://"):
                catalog = self._download_extra_catalog(name, catalog)
            catalog_sql = catalog.replace("'", "''")
            self.conn.execute(f"ATTACH 'ducklake:{catalog_sql}' AS {name} (READ_ONLY)")
            self.extra_catalogs.append(name)
            logger.info("Attached extra catalog %s", name)

    def _download_extra_catalog(self, name: str, uri: str) -> str:
        """Download an s3:// catalog file to a temp file (reused on refresh); return its path."""
        bucket, _, key = uri[len("s3://"):].partition("/")
        if not bucket or not key:
            raise ValueError(f"DABBLE_EXTRA_CATALOGS: {name}: expected s3://bucket/key, got {uri!r}")
        path = self._extra_catalog_paths.get(name)
        if path is None:
            tmp = tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False)
            path = tmp.name
            tmp.close()
            self._extra_catalog_paths[name] = path
        import boto3
        logger.info("Downloading extra catalog %s from %s", name, uri)
        boto3.client("s3").download_file(bucket, key, path)
        return path

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
        logger.info("Connecting to local DuckDB file: %s (read_only=%s)", db_path, read_only)
        self.conn = duckdb.connect(db_path, read_only=read_only)
        self.conn.execute("SET TimeZone = 'UTC'")

    def _connect_ducklake_local(self, data_path: str):
        """Attach a locally synced DuckLake catalog (catalog.duckdb + data/ directory)."""
        import os as _os
        catalog_path = _os.path.join(data_path, "catalog.duckdb")
        parquet_data = _os.path.join(data_path, "data")
        if not _os.path.exists(catalog_path):
            raise FileNotFoundError(f"DuckLake catalog not found: {catalog_path}")
        logger.info("Attaching local DuckLake catalog: %s", catalog_path)
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
        logger.info("Connected: %d tables visible", len(tables))

    # ------------------------------------------------------------------
    # Refresh (replaces hot-swap)
    # ------------------------------------------------------------------

    def refresh(self) -> bool:
        """Re-download catalog (S3 mode) or reconnect (local mode) and update timestamp."""
        logger.info("Refreshing database connection")
        try:
            self._connect()
            logger.info("Refresh complete: watermark=%s", self.cached_timestamp)
            return True
        except Exception as e:
            logger.error("Refresh failed: %s", e)
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
        if os.environ.get("DABBLE_S3_BUCKET") or os.environ.get("DABBLE_DATA_PATH"):
            try:
                db_name = self._db_name()
                result = self.conn.execute(f"""
                    SELECT MAX(snapshot_time)
                    FROM ducklake_snapshots('{db_name}')
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


_CATALOG_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_extra_catalogs(value: str) -> list[tuple[str, str]]:
    """Parse 'name=<catalog>,...' into (name, catalog) pairs."""
    entries = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, catalog = item.partition("=")
        name, catalog = name.strip(), catalog.strip()
        if not sep or not catalog or not _CATALOG_NAME.match(name):
            raise ValueError(f"DABBLE_EXTRA_CATALOGS: bad entry {item!r}; expected name=<catalog>")
        entries.append((name, catalog))
    names = [e[0] for e in entries]
    if len(names) != len(set(names)):
        raise ValueError(f"DABBLE_EXTRA_CATALOGS: duplicate names in {names}")
    return entries

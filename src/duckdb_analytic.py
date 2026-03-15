import duckdb
import os
import shutil
from datetime import datetime, timezone


class DuckDBAnalytic:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self.cached_timestamp = None
        self._connect()

    def _connect(self):
        read_only = os.environ.get("DUCKDB_READ_ONLY", "").lower() in ("1", "true", "yes")
        self.conn = duckdb.connect(self.db_path, read_only=read_only)
        self.conn.execute("SET TimeZone = 'UTC'")
        self.cached_timestamp = self._query_timestamp()

    def _ensure_connected(self):
        if not self.conn:
            raise RuntimeError("No database connection")

    def check_and_swap(self) -> bool:
        """Hot-swap the database file if a .new file is present.

        The ETL pipeline writes a fresh database to <db_path>.new, then this
        method atomically replaces the live file. The old file is kept as
        <db_path>.old until the next successful swap.
        """
        new_path = f"{self.db_path}.new"
        if not os.path.exists(new_path):
            return False

        backup_path = f"{self.db_path}.old"
        new_wal = f"{new_path}.wal"
        cur_wal = f"{self.db_path}.wal"
        bak_wal = f"{backup_path}.wal"

        try:
            # Move files before closing connection to avoid race conditions
            if os.path.exists(self.db_path):
                shutil.move(self.db_path, backup_path)
            if os.path.exists(cur_wal):
                shutil.move(cur_wal, bak_wal)
            shutil.move(new_path, self.db_path)
            if os.path.exists(new_wal):
                shutil.move(new_wal, cur_wal)

            if self.conn:
                self.conn.close()
            self._connect()
            return True

        except Exception as e:
            print(f"Hot-swap failed: {e}")
            # Attempt to restore from backup
            if os.path.exists(backup_path):
                try:
                    if os.path.exists(self.db_path):
                        os.remove(self.db_path)
                    shutil.move(backup_path, self.db_path)
                    if os.path.exists(bak_wal):
                        if os.path.exists(cur_wal):
                            os.remove(cur_wal)
                        shutil.move(bak_wal, cur_wal)
                    if self.conn:
                        self.conn.close()
                    self._connect()
                except Exception as restore_err:
                    print(f"Hot-swap restore also failed: {restore_err}")
            return False

    def execute_query(self, sql: str) -> tuple:
        """Execute SQL, checking for a hot-swap first.

        Returns (DataFrame | None, error_message | None).
        """
        try:
            self.check_and_swap()
            self._ensure_connected()
            return self.conn.execute(sql).fetchdf(), None
        except Exception as e:
            return None, str(e)

    def _query_timestamp(self) -> str:
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

    def get_connection_info(self) -> dict:
        return {
            "type": "DuckDB",
            "path": self.db_path,
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

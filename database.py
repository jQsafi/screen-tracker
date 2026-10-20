"""
Database access layer using SQLite.
Stores screenshot metadata, extracted OCR text, active application name, and Git push status.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


class TrackerDatabase:
    """Manages SQLite storage for screenshot tracking events."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a database connection with row factory enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create necessary tables and indices if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS screenshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    app_name TEXT,
                    window_title TEXT,
                    extracted_text TEXT,
                    image_path TEXT NOT NULL,
                    image_blob BLOB,
                    github_pushed INTEGER DEFAULT 0,
                    commit_hash TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_screenshots_timestamp ON screenshots(timestamp);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_screenshots_app ON screenshots(app_name);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_screenshots_pushed ON screenshots(github_pushed);"
            )
            logger.info("Initialized database at %s", self.db_path)

    def insert_screenshot(
        self,
        timestamp: str,
        app_name: str,
        window_title: str,
        extracted_text: str,
        image_path: str,
        image_blob: Optional[bytes] = None,
    ) -> int:
        """
        Insert a newly captured screenshot record into the database.
        Returns the inserted row ID.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO screenshots (
                    timestamp,
                    app_name,
                    window_title,
                    extracted_text,
                    image_path,
                    image_blob,
                    github_pushed
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    timestamp,
                    app_name,
                    window_title,
                    extracted_text,
                    str(image_path),
                    image_blob,
                ),
            )
            inserted_id = cursor.lastrowid
            logger.info("Saved screenshot #%d (%s) to database", inserted_id, app_name)
            return inserted_id

    def mark_as_pushed(self, record_id: int, commit_hash: str) -> bool:
        """Mark a screenshot record as committed/pushed to GitHub."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE screenshots
                SET github_pushed = 1,
                    commit_hash = ?
                WHERE id = ?
                """,
                (commit_hash, record_id),
            )
            return cursor.rowcount > 0

    def get_unpushed(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve list of screenshots not yet pushed to GitHub."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, app_name, window_title, image_path
                FROM screenshots
                WHERE github_pushed = 0
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent screenshot captures without image blobs for quick overview."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, app_name, window_title, extracted_text,
                       image_path, github_pushed, commit_hash, created_at
                FROM screenshots
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_filtered(
        self,
        query: str = "",
        app_name: str = "",
        since_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Search and filter screenshot records with pagination or delta since_id.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            conditions = []
            params = []

            if since_id is not None:
                conditions.append("id > ?")
                params.append(since_id)

            if app_name:
                conditions.append("app_name = ?")
                params.append(app_name)

            if query:
                wildcard = f"%{query}%"
                conditions.append(
                    "(extracted_text LIKE ? OR window_title LIKE ? OR app_name LIKE ?)"
                )
                params.extend([wildcard, wildcard, wildcard])

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            # Get total matching count
            count_sql = f"SELECT COUNT(*) FROM screenshots {where_clause}"
            cursor.execute(count_sql, params)
            total_count = cursor.fetchone()[0]

            # Fetch items
            order_clause = "ORDER BY id ASC" if since_id is not None else "ORDER BY id DESC"
            select_sql = f"""
                SELECT id, timestamp, app_name, window_title, extracted_text,
                       image_path, github_pushed, commit_hash, created_at
                FROM screenshots
                {where_clause}
                {order_clause}
                LIMIT ? OFFSET ?
            """
            cursor.execute(select_sql, params + [limit, offset])
            items = [dict(row) for row in cursor.fetchall()]

            return {"total": total_count, "items": items}

    def get_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single screenshot record by its ID, including raw blob if stored."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, app_name, window_title, extracted_text,
                       image_path, image_blob, github_pushed, commit_hash, created_at
                FROM screenshots
                WHERE id = ?
                """,
                (record_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_unique_apps(self) -> List[str]:
        """Return distinct list of captured application names."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT app_name
                FROM screenshots
                WHERE app_name IS NOT NULL AND app_name != ''
                ORDER BY app_name ASC
                """
            )
            return [row[0] for row in cursor.fetchall()]

    def search_text(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search across extracted OCR text and window titles."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            wildcard = f"%{query}%"
            cursor.execute(
                """
                SELECT id, timestamp, app_name, window_title, extracted_text,
                       image_path, github_pushed
                FROM screenshots
                WHERE extracted_text LIKE ? OR window_title LIKE ? OR app_name LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (wildcard, wildcard, wildcard, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics of tracked screenshots."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM screenshots")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM screenshots WHERE github_pushed = 1")
            pushed = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT app_name, COUNT(*) as count
                FROM screenshots
                GROUP BY app_name
                ORDER BY count DESC
                LIMIT 5
                """
            )
            top_apps = [dict(row) for row in cursor.fetchall()]

            return {
                "total_captured": total,
                "github_pushed": pushed,
                "pending_push": total - pushed,
                "top_apps": top_apps,
            }

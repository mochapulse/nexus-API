"""Database connection and schema management for Nexus API.

Provides SQLite connection utilities and table creation.
"""

import sqlite3
from pathlib import Path
from typing import Union

from api.config.paths import DB_PATH


def get_db_connection(
    db_path: Union[str, Path] = DB_PATH
) -> sqlite3.Connection:
    """Create and return a SQLite connection with foreign keys enabled.

    Establishes a connection to the specified SQLite database file,
    enables foreign key enforcement, and sets row_factory to sqlite3.Row
    for dict-like access to query results.

    Args:
        db_path: Path to the SQLite database file, a path string,
                 or ':memory:' for an in-memory database.
                 Defaults to DB_PATH from config.

    Returns:
        Configured sqlite3.Connection with foreign keys enabled and
        row_factory set to sqlite3.Row.
    """
    path_str = str(db_path) if isinstance(db_path, Path) else db_path

    conn = sqlite3.connect(path_str)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row

    return conn


def create_db_tables(conn: sqlite3.Connection) -> None:
    """Create all required database tables if they do not already exist.

    Uses CREATE TABLE IF NOT EXISTS to safely initialize the schema
    without dropping existing data.

    Args:
        conn: Active sqlite3.Connection to execute DDL against.
    """
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS example_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        );
        """
    )

    conn.commit()

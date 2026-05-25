"""
SQLite persistence layer.

Tables
------
state         — single-row tracker of the current position in the Quran.
verse_history — append-only audit log of every posting attempt.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional

# ------------------------------------------------------------------ #
# Connection helper                                                    #
# ------------------------------------------------------------------ #

@contextmanager
def get_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Schema initialisation                                                #
# ------------------------------------------------------------------ #

def init_db(db_path: str) -> None:
    """Create tables if they do not already exist."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS state (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                current_chapter INTEGER NOT NULL DEFAULT 1,
                current_verse   INTEGER NOT NULL DEFAULT 1,
                last_posted_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS verse_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                posted_at     TEXT    NOT NULL,
                chapter_number INTEGER NOT NULL,
                verse_number  INTEGER NOT NULL,
                arabic_text   TEXT,
                english_text  TEXT,
                tweet_ids     TEXT,
                status        TEXT    NOT NULL CHECK (status IN ('success', 'failed', 'skipped')),
                error_message TEXT
            );
            """
        )


# ------------------------------------------------------------------ #
# State helpers                                                        #
# ------------------------------------------------------------------ #

def get_state(conn: sqlite3.Connection) -> sqlite3.Row:
    """Return the current state row, creating a default one if absent."""
    row = conn.execute("SELECT * FROM state WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO state (id, current_chapter, current_verse) VALUES (1, 1, 1)"
        )
        row = conn.execute("SELECT * FROM state WHERE id = 1").fetchone()
    return row


def save_state(
    conn: sqlite3.Connection,
    chapter: int,
    verse: int,
    posted_at: Optional[datetime] = None,
) -> None:
    """Upsert the single state row."""
    ts = (posted_at or datetime.now(timezone.utc)).isoformat()
    conn.execute(
        """
        INSERT INTO state (id, current_chapter, current_verse, last_posted_at)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            current_chapter = excluded.current_chapter,
            current_verse   = excluded.current_verse,
            last_posted_at  = excluded.last_posted_at
        """,
        (chapter, verse, ts),
    )


# ------------------------------------------------------------------ #
# History helpers                                                      #
# ------------------------------------------------------------------ #

def log_verse(
    conn: sqlite3.Connection,
    chapter_number: int,
    verse_number: int,
    arabic_text: str,
    english_text: str,
    tweet_ids: list,
    status: str,
    error_message: Optional[str] = None,
    posted_at: Optional[datetime] = None,
) -> int:
    """Append a row to verse_history and return its new id."""
    ts = (posted_at or datetime.now(timezone.utc)).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO verse_history
            (posted_at, chapter_number, verse_number,
             arabic_text, english_text, tweet_ids, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            chapter_number,
            verse_number,
            arabic_text,
            english_text,
            json.dumps(tweet_ids),
            status,
            error_message,
        ),
    )
    return cursor.lastrowid


def get_history(conn: sqlite3.Connection, limit: int = 50) -> list:
    """Return the most recent verse_history rows (newest first)."""
    rows = conn.execute(
        "SELECT * FROM verse_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]

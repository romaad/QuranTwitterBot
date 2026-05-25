"""
Shared pytest fixtures.
"""

import pytest

import db


@pytest.fixture()
def mem_db():
    """In-memory SQLite database for fast unit tests."""
    db.init_db(":memory:")
    # Return the path string; tests open their own connections
    return ":memory:"


@pytest.fixture()
def tmp_db(tmp_path):
    """File-based SQLite in a temp directory for integration tests."""
    path = str(tmp_path / "test_quran.db")
    db.init_db(path)
    return path


@pytest.fixture()
def db_at_last_verse(tmp_db):
    """
    Seed state at the last verse of chapter 1 (Al-Fatiha has 7 verses).
    Useful for testing chapter-advance logic.
    """
    with db.get_connection(tmp_db) as conn:
        db.save_state(conn, chapter=1, verse=7)
    return tmp_db

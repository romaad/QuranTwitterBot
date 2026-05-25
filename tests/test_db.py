"""Unit tests for db.py."""
import json

import pytest

import db


class TestInitDb:
    def test_creates_state_table(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='state'"
            ).fetchall()
        assert len(rows) == 1

    def test_creates_verse_history_table(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='verse_history'"
            ).fetchall()
        assert len(rows) == 1

    def test_idempotent(self, tmp_db):
        # Calling init_db again should not raise
        db.init_db(tmp_db)


class TestGetState:
    def test_default_state_created(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
        assert state["current_chapter"] == 1
        assert state["current_verse"] == 1
        assert state["last_posted_at"] is None

    def test_returns_existing_state(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            db.save_state(conn, chapter=5, verse=3)
        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
        assert state["current_chapter"] == 5
        assert state["current_verse"] == 3


class TestSaveState:
    def test_upsert_creates_then_updates(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            db.save_state(conn, chapter=2, verse=10)
        with db.get_connection(tmp_db) as conn:
            db.save_state(conn, chapter=3, verse=1)
        with db.get_connection(tmp_db) as conn:
            rows = conn.execute("SELECT COUNT(*) as c FROM state").fetchone()
        assert rows["c"] == 1

    def test_last_posted_at_set(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            db.save_state(conn, chapter=1, verse=1)
            state = db.get_state(conn)
        assert state["last_posted_at"] is not None


class TestLogVerse:
    def test_appends_row(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            db.log_verse(
                conn,
                chapter_number=1,
                verse_number=1,
                arabic_text="بِسْمِ ٱللَّهِ",
                english_text="In the name of Allah",
                tweet_ids=["123", "456"],
                status="success",
            )
        with db.get_connection(tmp_db) as conn:
            rows = conn.execute("SELECT * FROM verse_history").fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["status"] == "success"
        assert json.loads(row["tweet_ids"]) == ["123", "456"]

    def test_history_is_append_only(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            for i in range(1, 4):
                db.log_verse(
                    conn,
                    chapter_number=1,
                    verse_number=i,
                    arabic_text="text",
                    english_text="text",
                    tweet_ids=[],
                    status="success",
                )
        with db.get_connection(tmp_db) as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM verse_history").fetchone()["c"]
        assert count == 3

    def test_failed_status_stored(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            db.log_verse(
                conn,
                chapter_number=2,
                verse_number=1,
                arabic_text="",
                english_text="",
                tweet_ids=[],
                status="failed",
                error_message="Network timeout",
            )
        with db.get_connection(tmp_db) as conn:
            row = conn.execute("SELECT * FROM verse_history").fetchone()
        assert row["error_message"] == "Network timeout"

    def test_invalid_status_raises(self, tmp_db):
        with pytest.raises(Exception):
            with db.get_connection(tmp_db) as conn:
                db.log_verse(
                    conn,
                    chapter_number=1,
                    verse_number=1,
                    arabic_text="",
                    english_text="",
                    tweet_ids=[],
                    status="invalid_status",
                )


class TestGetHistory:
    def test_returns_newest_first(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            for i in range(1, 6):
                db.log_verse(conn, 1, i, "ar", "en", [], "success")
        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn, limit=5)
        ids = [r["verse_number"] for r in history]
        assert ids == sorted(ids, reverse=True)

    def test_respects_limit(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            for i in range(1, 11):
                db.log_verse(conn, 1, i, "ar", "en", [], "success")
        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn, limit=3)
        assert len(history) == 3

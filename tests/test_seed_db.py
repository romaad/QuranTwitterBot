"""Unit tests for seed_db.py."""

import db
import seed_db


class TestSeed:
    def test_default_seed_sets_chapter_29_verse_61(self, tmp_path):
        path = str(tmp_path / "quran.db")
        seed_db.seed(seed_db._DEFAULT_CHAPTER, seed_db._DEFAULT_VERSE, db_path=path)
        with db.get_connection(path) as conn:
            state = db.get_state(conn)
        assert state["current_chapter"] == 29
        assert state["current_verse"] == 61

    def test_custom_seed_position(self, tmp_path):
        path = str(tmp_path / "quran.db")
        seed_db.seed(2, 256, db_path=path)
        with db.get_connection(path) as conn:
            state = db.get_state(conn)
        assert state["current_chapter"] == 2
        assert state["current_verse"] == 256

    def test_seed_creates_db_if_missing(self, tmp_path):
        path = str(tmp_path / "subdir" / "quran.db")
        seed_db.seed(1, 1, db_path=path)  # directory doesn't exist yet
        with db.get_connection(path) as conn:
            state = db.get_state(conn)
        assert state["current_chapter"] == 1
        assert state["current_verse"] == 1

    def test_seed_overwrites_existing_state(self, tmp_db):
        # tmp_db starts at 1:1 — reseed to a different position
        seed_db.seed(114, 6, db_path=tmp_db)
        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
        assert state["current_chapter"] == 114
        assert state["current_verse"] == 6

    def test_default_chapter_is_29(self):
        assert seed_db._DEFAULT_CHAPTER == 29

    def test_default_verse_is_61(self):
        assert seed_db._DEFAULT_VERSE == 61

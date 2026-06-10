"""
Unit + integration tests for bot.py.

Unit tests mock both quran_api and twitter_client.
Integration tests (marked @pytest.mark.integration) hit the real Quran API
but always mock the X API.
"""
from unittest.mock import patch

import pytest

import bot
import db

# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

MOCK_CHAPTER = {
    "id": 1,
    "verses_count": 7,
    "name_arabic": "الفاتحة",
    "translated_name": {"name": "The Opener"},
}

MOCK_VERSE = {
    "text_uthmani": "بِسْمِ ٱللَّهِ",
    "ruku_number": 1,
    "translations": [{"text": "In the name of Allah"}],
}


def _patch_quran(chapter=MOCK_CHAPTER, verse=MOCK_VERSE):
    """Return a context manager that patches both quran_api functions."""
    import unittest.mock as mock
    return mock.patch.multiple(
        "bot.quran_api",
        get_chapter=mock.MagicMock(return_value=chapter),
        get_verse=mock.MagicMock(return_value=verse),
        extract_arabic=mock.MagicMock(return_value="بِسْمِ ٱللَّهِ"),
        extract_english=mock.MagicMock(return_value="In the name of Allah"),
        extract_ruku_number=mock.MagicMock(return_value=1),
        get_verses_audio_urls=mock.MagicMock(
            return_value=["https://cdn.example.com/verse.mp3"]
        ),
    )


def _patch_twitter(tweet_ids=("111", "222")):
    import unittest.mock as mock
    return mock.patch("bot.twitter_client.post_thread", return_value=list(tweet_ids))


def _patch_video_twitter(tweet_ids=("aaa", "bbb", "ccc")):
    import unittest.mock as mock
    return mock.patch(
        "bot.twitter_client.post_video_thread", return_value=list(tweet_ids)
    )


# ------------------------------------------------------------------ #
# Unit tests                                                           #
# ------------------------------------------------------------------ #

class TestNextPosition:
    def test_increments_verse(self):
        assert bot._next_position(1, 3, 7) == (1, 4)

    def test_advances_chapter_at_end(self):
        assert bot._next_position(1, 7, 7) == (2, 1)

    def test_wraps_after_chapter_114(self):
        assert bot._next_position(114, 6, 6) == (1, 1)


class TestPostVerse:
    def test_success_advances_state(self, tmp_db):
        with _patch_quran(), _patch_twitter():
            bot.post_verse(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
        # Started at 1:1; chapter 1 has 7 verses → next is 1:2
        assert state["current_chapter"] == 1
        assert state["current_verse"] == 2

    def test_success_logs_history_row(self, tmp_db):
        with _patch_quran(), _patch_twitter():
            bot.post_verse(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn)
        assert len(history) == 1
        assert history[0]["status"] == "success"
        assert history[0]["chapter_number"] == 1
        assert history[0]["verse_number"] == 1

    def test_failure_logs_failed_row(self, tmp_db):
        with _patch_quran():
            with patch("bot.twitter_client.post_thread", side_effect=Exception("API error")):
                bot.post_verse(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn)
            state = db.get_state(conn)

        assert history[0]["status"] == "failed"
        assert "API error" in history[0]["error_message"]
        # State should NOT advance on failure
        assert state["current_chapter"] == 1
        assert state["current_verse"] == 1

    def test_chapter_advances_at_chapter_end(self, db_at_last_verse):
        """State seeded at chapter 1, verse 7 (last verse of Al-Fatiha)."""
        chapter_with_7_verses = dict(MOCK_CHAPTER, verses_count=7)
        with _patch_quran(chapter=chapter_with_7_verses), _patch_twitter():
            bot.post_verse(db_path=db_at_last_verse)

        with db.get_connection(db_at_last_verse) as conn:
            state = db.get_state(conn)
        assert state["current_chapter"] == 2
        assert state["current_verse"] == 1

    def test_wraps_from_chapter_114(self, tmp_db):
        with db.get_connection(tmp_db) as conn:
            db.save_state(conn, chapter=114, verse=6)

        last_chapter = {
            "id": 114,
            "verses_count": 6,
            "name_arabic": "الناس",
            "translated_name": {"name": "Mankind"},
        }
        with _patch_quran(chapter=last_chapter), _patch_twitter():
            bot.post_verse(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
        assert state["current_chapter"] == 1
        assert state["current_verse"] == 1

    def test_quran_api_failure_logs_failed(self, tmp_db):
        with patch("bot.quran_api.get_chapter", side_effect=Exception("Timeout")):
            bot.post_verse(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn)
        assert history[0]["status"] == "failed"
        assert "Timeout" in history[0]["error_message"]


# ------------------------------------------------------------------ #
# Integration tests (live Quran API, mocked X API)                    #
# ------------------------------------------------------------------ #

@pytest.mark.integration
@pytest.mark.usefixtures("patch_quran_url")
class TestIntegration:
    def test_real_chapter_1_metadata(self):
        import quran_api
        chapter = quran_api.get_chapter(1)
        assert chapter["verses_count"] == 7
        assert "name_arabic" in chapter

    def test_real_verse_1_1(self):
        import quran_api
        verse = quran_api.get_verse(1, 1)
        arabic = quran_api.extract_arabic(verse)
        english = quran_api.extract_english(verse)
        assert len(arabic) > 0
        assert len(english) > 0

    def test_full_cycle_chapter_1(self, tmp_db):
        """Full posting cycle using local Quran API server, mocked X."""
        with _patch_twitter(tweet_ids=("live_1", "live_2")):
            bot.post_verse(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn)
            state = db.get_state(conn)

        assert history[0]["status"] == "success"
        assert state["current_verse"] == 2  # advanced from verse 1

    def test_real_chapter_2_verse_1(self):
        import quran_api
        verse = quran_api.get_verse(2, 1)
        assert quran_api.extract_arabic(verse)

    def test_real_chapter_3_verse_1(self):
        import quran_api
        verse = quran_api.get_verse(3, 1)
        assert quran_api.extract_arabic(verse)


# ------------------------------------------------------------------ #
# Tests for _collect_ruku_positions                                    #
# ------------------------------------------------------------------ #

class TestCollectRukuPositions:
    def _chapter(self, verse_count):
        return {"verses_count": verse_count}

    def _verse(self, ruku_number):
        return {"ruku_number": ruku_number, "text_uthmani": "", "translations": []}

    def test_single_verse_ruku(self):
        """When the very next verse starts a new ruku, only the start position is returned."""
        cache = {1: self._chapter(7)}
        verse_sequence = [self._verse(1), self._verse(2)]  # start=ruku1, next=ruku2

        with (
            patch("bot.quran_api.get_verse", side_effect=verse_sequence),
            patch("bot.quran_api.extract_ruku_number", side_effect=lambda v: v["ruku_number"]),
        ):
            positions = bot._collect_ruku_positions(1, 1, cache)

        assert positions == [(1, 1)]

    def test_multi_verse_ruku(self):
        """All verses in the same ruku are collected."""
        cache = {1: self._chapter(7)}
        # get_verse is called once for start, then once per "next" verse check:
        # start=(1,1) ruku=1, next=(1,2) ruku=1, next=(1,3) ruku=1, next=(1,4) ruku=2 → stop
        verse_sequence = [
            self._verse(1),  # start verse (1,1) → target_ruku = 1
            self._verse(1),  # check next (1,2): same ruku → continue
            self._verse(1),  # check next (1,3): same ruku → continue
            self._verse(2),  # check next (1,4): new ruku  → break
        ]

        with (
            patch("bot.quran_api.get_verse", side_effect=verse_sequence),
            patch("bot.quran_api.extract_ruku_number", side_effect=lambda v: v["ruku_number"]),
        ):
            positions = bot._collect_ruku_positions(1, 1, cache)

        assert positions == [(1, 1), (1, 2), (1, 3)]

    def test_populates_chapter_cache(self):
        """Chapter metadata is fetched lazily and stored in the cache."""
        cache = {}
        verse_sequence = [{"ruku_number": 1}, {"ruku_number": 2}]

        with (
            patch("bot.quran_api.get_chapter", return_value=self._chapter(7)) as mock_ch,
            patch("bot.quran_api.get_verse", side_effect=verse_sequence),
            patch("bot.quran_api.extract_ruku_number", side_effect=lambda v: v["ruku_number"]),
        ):
            bot._collect_ruku_positions(1, 1, cache)

        mock_ch.assert_called_once_with(1)
        assert 1 in cache


# ------------------------------------------------------------------ #
# Tests for post_ruku_group                                            #
# ------------------------------------------------------------------ #

class TestPostRukuGroup:
    def _build_video_noop(self, audio_urls, nature_video, output_path, **kwargs):
        with open(output_path, "wb") as fh:
            fh.write(b"FAKEMP4")
        return output_path

    def test_success_advances_state_to_next_ruku(self, tmp_db):
        """State must advance past all verses in the ruku on success."""
        cache_holder: list[dict] = []

        def fake_collect_ruku(ch, v, cache=None):
            # Pretend the ruku spans 3 verses: (1,1), (1,2), (1,3)
            if cache is not None:
                cache[1] = {"verses_count": 7}
                cache_holder.append(cache)
            return [(1, 1), (1, 2), (1, 3)]

        with (
            _patch_quran(),
            _patch_video_twitter(),
            patch("bot._collect_ruku_positions", side_effect=fake_collect_ruku),
            patch("bot.video_maker.build_video", side_effect=self._build_video_noop),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
        # Last position is (1,3); chapter 1 has 7 verses → next is (1,4)
        assert state["current_chapter"] == 1
        assert state["current_verse"] == 4

    def test_success_logs_history_row(self, tmp_db):
        def fake_collect_ruku(ch, v, cache=None):
            if cache is not None:
                cache[1] = {"verses_count": 7}
            return [(1, 1)]

        with (
            _patch_quran(),
            _patch_video_twitter(),
            patch("bot._collect_ruku_positions", side_effect=fake_collect_ruku),
            patch("bot.video_maker.build_video", side_effect=self._build_video_noop),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn)
        assert history[0]["status"] == "success"

    def test_failure_does_not_advance_state(self, tmp_db):
        with (
            _patch_quran(),
            patch("bot._collect_ruku_positions", side_effect=RuntimeError("API down")),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
            history = db.get_history(conn)

        assert state["current_chapter"] == 1
        assert state["current_verse"] == 1
        assert history[0]["status"] == "failed"

    def test_uses_pexels_for_each_query_when_api_key_set(self, tmp_db, monkeypatch):
        """When PEXELS_API_KEY is set, fetch_nature_video is called once per query."""
        monkeypatch.setenv("PEXELS_API_KEY", "fake_key")
        fetched_queries: list[str] = []

        def fake_fetch(query, api_key, dest):
            fetched_queries.append(query)
            with open(dest, "wb") as fh:
                fh.write(b"NATURE")
            return dest

        def fake_build(audio_urls, nature_paths, output, **kw):
            with open(output, "wb") as fh:
                fh.write(b"MP4")
            return output

        def fake_collect_ruku(ch, v, cache=None):
            if cache is not None:
                cache[1] = {"verses_count": 7}
            return [(1, 1)]

        with (
            _patch_quran(),
            _patch_video_twitter(),
            patch("bot._collect_ruku_positions", side_effect=fake_collect_ruku),
            patch("bot.video_maker.fetch_nature_video", side_effect=fake_fetch),
            patch("bot.video_maker.build_video", side_effect=fake_build),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        # One call per query in config.nature_video_queries (default: nature, wildlife)
        from config import config as cfg
        assert fetched_queries == list(cfg.nature_video_queries)

    def test_passes_list_of_paths_to_build_video(self, tmp_db, monkeypatch):
        """build_video must receive a list of background video paths."""
        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        captured_paths: list = []

        def fake_build(audio_urls, nature_paths, output, **kw):
            captured_paths.append(nature_paths)
            with open(output, "wb") as fh:
                fh.write(b"MP4")
            return output

        def fake_collect_ruku(ch, v, cache=None):
            if cache is not None:
                cache[1] = {"verses_count": 7}
            return [(1, 1)]

        with (
            _patch_quran(),
            _patch_video_twitter(),
            patch("bot._collect_ruku_positions", side_effect=fake_collect_ruku),
            patch("bot.video_maker.build_video", side_effect=fake_build),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        assert isinstance(captured_paths[0], list)


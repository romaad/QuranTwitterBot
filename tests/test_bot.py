"""
Unit + integration tests for bot.py.

Unit tests mock both quran_api and twitter_client.
Integration tests (marked @pytest.mark.integration) hit the real Quran API
but always mock the X API.
"""
from unittest.mock import MagicMock, patch

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
        get_verses_audio_urls=mock.MagicMock(
            return_value=["https://cdn.example.com/verse.mp3"]
        ),
    )


def _patch_twitter(tweet_ids=("111", "222")):
    import unittest.mock as mock
    return mock.patch("bot.twitter_client.post_thread", return_value=list(tweet_ids))


def _patch_video_twitter(tweet_ids=("aaa", "bbb")):
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
# Tests for _collect_group_positions                                   #
# ------------------------------------------------------------------ #

class TestCollectGroupPositions:
    def _chapter(self, verse_count):
        return {"verses_count": verse_count}

    def test_within_single_chapter(self):
        cache = {1: self._chapter(7)}
        positions = bot._collect_group_positions(1, 3, 3, cache)
        assert positions == [(1, 3), (1, 4), (1, 5)]

    def test_wraps_to_next_chapter(self):
        cache = {1: self._chapter(7), 2: self._chapter(286)}
        positions = bot._collect_group_positions(1, 6, 3, cache)
        assert positions == [(1, 6), (1, 7), (2, 1)]

    def test_wraps_from_chapter_114(self):
        cache = {114: self._chapter(6), 1: self._chapter(7)}
        positions = bot._collect_group_positions(114, 5, 3, cache)
        # chapter 114 has 6 verses; verse 5, 6 then wraps to 1:1
        assert positions[0] == (114, 5)
        assert positions[1] == (114, 6)
        assert positions[2] == (1, 1)

    def test_populates_cache_lazily(self):
        cache = {}
        with patch("bot.quran_api.get_chapter", return_value=self._chapter(7)) as mock_ch:
            bot._collect_group_positions(1, 1, 2, cache)
        mock_ch.assert_called_once_with(1)
        assert 1 in cache

    def test_size_one_returns_single_element(self):
        cache = {1: self._chapter(7)}
        positions = bot._collect_group_positions(1, 4, 1, cache)
        assert positions == [(1, 4)]


# ------------------------------------------------------------------ #
# Tests for post_verse_group                                           #
# ------------------------------------------------------------------ #

class TestPostVerseGroup:
    def _build_video_noop(self, audio_urls, nature_video, output_path):
        # Create a tiny fake video file so os.unlink succeeds
        with open(output_path, "wb") as fh:
            fh.write(b"FAKEMP4")
        return output_path

    def test_success_advances_state_by_group_size(self, tmp_db):
        with (
            _patch_quran(),
            _patch_video_twitter(),
            patch("bot.video_maker.build_video", side_effect=self._build_video_noop),
            patch("bot.config.group_size", 3),
            patch("bot.config.enable_video", True),
        ):
            bot.post_verse_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
        # Started at 1:1; group_size=3 → should be at 1:4
        assert state["current_chapter"] == 1
        assert state["current_verse"] == 4

    def test_success_logs_history_row(self, tmp_db):
        with (
            _patch_quran(),
            _patch_video_twitter(),
            patch("bot.video_maker.build_video", side_effect=self._build_video_noop),
            patch("bot.config.group_size", 2),
        ):
            bot.post_verse_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn)
        assert len(history) == 1
        assert history[0]["status"] == "success"
        assert history[0]["chapter_number"] == 1
        assert history[0]["verse_number"] == 1

    def test_failure_does_not_advance_state(self, tmp_db):
        with (
            _patch_quran(),
            patch(
                "bot.video_maker.build_video",
                side_effect=RuntimeError("ffmpeg missing"),
            ),
            patch("bot.config.group_size", 3),
        ):
            bot.post_verse_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
            history = db.get_history(conn)

        assert state["current_chapter"] == 1
        assert state["current_verse"] == 1
        assert history[0]["status"] == "failed"
        assert "ffmpeg missing" in history[0]["error_message"]

    def test_cleans_up_temp_video_on_success(self, tmp_db):
        deleted: list[str] = []

        def fake_build(audio_urls, nature, output):
            with open(output, "wb") as fh:
                fh.write(b"MP4")
            return output

        original_unlink = __import__("os").unlink

        def tracking_unlink(path):
            deleted.append(path)
            original_unlink(path)

        with (
            _patch_quran(),
            _patch_video_twitter(),
            patch("bot.video_maker.build_video", side_effect=fake_build),
            patch("bot.config.group_size", 1),
            patch("bot.os.unlink", side_effect=tracking_unlink),
        ):
            bot.post_verse_group(db_path=tmp_db)

        assert len(deleted) == 1
        import os
        assert not os.path.exists(deleted[0])


"""
Unit + integration tests for bot.py.

Unit tests mock both quran_api and twitter_client.
Integration tests (marked @pytest.mark.integration) hit the real Quran API
but always mock the X API.
"""

import unittest.mock as mock
from unittest.mock import MagicMock, patch

import pytest

import bot
import db
from config import config as cfg
import quran_api
from secrets import Secrets
from twitter_client import Tweet

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


def _make_verse(ruku_number=1, chapter=1, verse_num=1):
    """Build a quran_api.Verse for use in mocks."""
    return quran_api.Verse(
        verse_key=f"{chapter}:{verse_num}",
        chapter_number=chapter,
        verse_number=verse_num,
        arabic="بِسْمِ ٱللَّهِ",
        english="In the name of Allah",
        audio_url="https://cdn.example.com/verse.mp3",
        audio_segments=[],
    )


def _patch_quran(chapter=MOCK_CHAPTER, verse=MOCK_VERSE):
    """Return a context manager that patches both quran_api functions."""
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
    return mock.patch("bot.twitter_client.post_thread", return_value=list(tweet_ids))


def _patch_ruku_twitter(tweet_ids=("aaa", "bbb", "ccc")):
    """Patch twitter_client.post_thread for ruku (returns 3 IDs)."""
    return mock.patch("bot.twitter_client.post_thread", return_value=list(tweet_ids))


def _patch_secrets():
    """Patch Secrets.from_env so tests don't need real Twitter credentials."""
    fake = Secrets(
        twitter_api_key="fake_key",
        twitter_api_secret="fake_secret",
        twitter_access_token="fake_token",
        twitter_access_token_secret="fake_token_secret",
        pexels_api_key=None,
    )
    return mock.patch("bot.Secrets.from_env", return_value=fake)


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
            with patch(
                "bot.twitter_client.post_thread", side_effect=Exception("API error")
            ):
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
        chapter = quran_api.get_chapter(1)
        assert chapter["verses_count"] == 7
        assert "name_arabic" in chapter

    def test_real_verse_1_1(self):
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
        verse = quran_api.get_verse(2, 1)
        assert quran_api.extract_arabic(verse)

    def test_real_chapter_3_verse_1(self):
        verse = quran_api.get_verse(3, 1)
        assert quran_api.extract_arabic(verse)


# ------------------------------------------------------------------ #
# Tests for post_ruku_group                                            #
# ------------------------------------------------------------------ #


class TestPostRukuGroup:
    def _build_video_noop(self, *args, **kwargs):
        output_path = kwargs.get("output_path")
        if output_path is None and len(args) >= 3:
            output_path = args[2]
        assert output_path is not None
        with open(output_path, "wb") as fh:
            fh.write(b"FAKEMP4")
        return output_path

    def _make_verses(self, count=3):
        return [
            _make_verse(ruku_number=1, chapter=1, verse_num=i + 1) for i in range(count)
        ]

    def test_success_advances_state_to_next_ruku(self, tmp_db, monkeypatch):
        """State must advance past all verses in the ruku on success."""
        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        verses = self._make_verses(3)  # (1,1), (1,2), (1,3)

        with (
            _patch_secrets(),
            _patch_quran(),
            _patch_ruku_twitter(),
            patch("bot.quran_api.get_verses_by_ruku", return_value=verses),
            patch("bot.video_maker.build_video", side_effect=self._build_video_noop),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
        # Last position is (1,3); chapter 1 has 7 verses → next is (1,4)
        assert state["current_chapter"] == 1
        assert state["current_verse"] == 4

    def test_success_logs_history_row(self, tmp_db, monkeypatch):
        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        verses = self._make_verses(1)

        with (
            _patch_secrets(),
            _patch_quran(),
            _patch_ruku_twitter(),
            patch("bot.quran_api.get_verses_by_ruku", return_value=verses),
            patch("bot.video_maker.build_video", side_effect=self._build_video_noop),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            history = db.get_history(conn)
        assert history[0]["status"] == "success"

    def test_failure_does_not_advance_state(self, tmp_db, monkeypatch):
        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        with (
            _patch_secrets(),
            _patch_quran(),
            patch(
                "bot.quran_api.get_verses_by_ruku",
                side_effect=RuntimeError("API down"),
            ),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        with db.get_connection(tmp_db) as conn:
            state = db.get_state(conn)
            history = db.get_history(conn)

        assert state["current_chapter"] == 1
        assert state["current_verse"] == 1
        assert history[0]["status"] == "failed"

    def test_uses_pexels_client_when_api_key_set(self, tmp_db, monkeypatch):
        """When PEXELS_API_KEY is set, PexelsClient.fetch_video is called once per query."""
        monkeypatch.setenv("PEXELS_API_KEY", "fake_pexels_key")
        fetched_queries: list[str] = []

        def fake_fetch_video(self_client, query, dest, **kw):
            fetched_queries.append(query)
            with open(dest, "wb") as fh:
                fh.write(b"NATURE")
            return dest

        def fake_build(*args, **kw):
            output = kw.get("output_path")
            assert output is not None
            with open(output, "wb") as fh:
                fh.write(b"MP4")
            return output

        verses = self._make_verses(1)

        pexels_secrets = Secrets(
            twitter_api_key="k",
            twitter_api_secret="s",
            twitter_access_token="t",
            twitter_access_token_secret="ts",
            pexels_api_key="fake_pexels_key",
        )

        with (
            patch("bot.Secrets.from_env", return_value=pexels_secrets),
            _patch_quran(),
            _patch_ruku_twitter(),
            patch("bot.quran_api.get_verses_by_ruku", return_value=verses),
            patch("bot.PexelsClient.fetch_video", fake_fetch_video),
            patch("bot.video_maker.build_video", side_effect=fake_build),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        assert fetched_queries == list(cfg.nature_video_queries)

    def test_passes_list_of_paths_to_build_video(self, tmp_db, monkeypatch):
        """build_video must receive a list of background video paths."""
        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        captured_paths: list = []

        def fake_build(*args, **kw):
            captured_paths.append(kw.get("nature_video_paths"))
            output = kw.get("output_path")
            assert output is not None
            with open(output, "wb") as fh:
                fh.write(b"MP4")
            return output

        verses = self._make_verses(1)

        with (
            _patch_secrets(),
            _patch_quran(),
            _patch_ruku_twitter(),
            patch("bot.quran_api.get_verses_by_ruku", return_value=verses),
            patch("bot.video_maker.build_video", side_effect=fake_build),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        assert isinstance(captured_paths[0], list)

    def test_posts_three_tweet_thread(self, tmp_db, monkeypatch):
        """post_thread must be called with exactly 3 tweets: Arabic, English, video."""
        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        captured_tweets: list = []

        def fake_post_thread(tweets, **kw):
            captured_tweets.extend(tweets)
            return ["t1", "t2", "t3"]

        verses = self._make_verses(1)

        with (
            _patch_secrets(),
            _patch_quran(),
            patch("bot.twitter_client.post_thread", side_effect=fake_post_thread),
            patch("bot.quran_api.get_verses_by_ruku", return_value=verses),
            patch("bot.video_maker.build_video", side_effect=self._build_video_noop),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        assert len(captured_tweets) == 3
        assert captured_tweets[0].text is not None
        assert captured_tweets[1].text is not None
        assert captured_tweets[2].video_path is not None
        assert captured_tweets[0].video_path is None
        assert captured_tweets[1].video_path is None

    def test_ruku_number_passed_to_build_video(self, tmp_db, monkeypatch):
        """build_video must be called using the ruku_number-based API."""
        monkeypatch.delenv("PEXELS_API_KEY", raising=False)
        captured_kwargs: list[dict] = []

        def fake_build(*args, **kw):
            captured_kwargs.append(kw)
            output = kw.get("output_path")
            assert output is not None
            with open(output, "wb") as fh:
                fh.write(b"MP4")
            return output

        verse = _make_verse(chapter=1, verse_num=1)
        verse.audio_segments = [[0, 0, 1000], [1, 1000, 2000]]

        with (
            _patch_secrets(),
            _patch_quran(),
            _patch_ruku_twitter(),
            patch("bot.quran_api.get_verses_by_ruku", return_value=[verse]),
            patch("bot.video_maker.build_video", side_effect=fake_build),
        ):
            bot.post_ruku_group(db_path=tmp_db)

        assert captured_kwargs[0].get("ruku_number") == 1
        assert captured_kwargs[0].get("verse_texts") is None
        assert captured_kwargs[0].get("verse_segments") is None

"""Unit tests for twitter_client.py (tweepy mocked)."""
from unittest.mock import MagicMock

import pytest

import twitter_client


def _make_tweet_response(tweet_id: str):
    mock = MagicMock()
    mock.data = {"id": tweet_id}
    return mock


class TestFormatTweet:
    def test_short_verse_unchanged(self):
        result = twitter_client._format_tweet("Hello", "Al-Fatiha", 1, 280)
        assert result == '"Hello" {Al-Fatiha:1}'

    def test_long_verse_truncated(self):
        long_text = "A" * 300
        result = twitter_client._format_tweet(long_text, "Al-Baqarah", 5, 280)
        assert len(result) <= 280
        assert result.endswith("{Al-Baqarah:5}")

    def test_attribution_always_present(self):
        result = twitter_client._format_tweet("short", "Al-Nas", 6, 40)
        assert "{Al-Nas:6}" in result


class TestPostThread:
    def test_thread_mode_posts_reply(self):
        client = MagicMock()
        client.create_tweet.side_effect = [
            _make_tweet_response("111"),
            _make_tweet_response("222"),
        ]
        ids = twitter_client.post_thread(
            arabic_text="بِسْمِ ٱللَّهِ",
            english_text="In the name of Allah",
            chapter_name_arabic="الفاتحة",
            chapter_name_english="The Opener",
            verse_number=1,
            mode="thread",
            client=client,
        )
        assert ids == ["111", "222"]
        # Second call must include in_reply_to_tweet_id
        _, kwargs = client.create_tweet.call_args_list[1]
        assert kwargs.get("in_reply_to_tweet_id") == "111"

    def test_separate_mode_no_reply(self):
        client = MagicMock()
        client.create_tweet.side_effect = [
            _make_tweet_response("333"),
            _make_tweet_response("444"),
        ]
        twitter_client.post_thread(
            arabic_text="text",
            english_text="text",
            chapter_name_arabic="name",
            chapter_name_english="name",
            verse_number=1,
            mode="separate",
            client=client,
        )
        _, kwargs = client.create_tweet.call_args_list[1]
        assert "in_reply_to_tweet_id" not in kwargs

    def test_returns_both_tweet_ids(self):
        client = MagicMock()
        client.create_tweet.side_effect = [
            _make_tweet_response("aaa"),
            _make_tweet_response("bbb"),
        ]
        ids = twitter_client.post_thread(
            arabic_text="ar",
            english_text="en",
            chapter_name_arabic="ch_ar",
            chapter_name_english="ch_en",
            verse_number=2,
            client=client,
        )
        assert len(ids) == 2

    def test_propagates_api_error(self):
        client = MagicMock()
        client.create_tweet.side_effect = Exception("Rate limit exceeded")
        with pytest.raises(Exception, match="Rate limit exceeded"):
            twitter_client.post_thread(
                arabic_text="ar",
                english_text="en",
                chapter_name_arabic="ch",
                chapter_name_english="ch",
                verse_number=1,
                client=client,
            )

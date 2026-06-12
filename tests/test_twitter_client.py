"""Unit tests for twitter_client.py (tweepy mocked)."""

from unittest.mock import MagicMock

import pytest

import twitter_client
from secrets import Secrets
from twitter_client import Tweet


def _make_tweet_response(tweet_id: str):
    mock = MagicMock()
    mock.data = {"id": tweet_id}
    return mock


# ------------------------------------------------------------------ #
# Tweet dataclass                                                      #
# ------------------------------------------------------------------ #


class TestTweetDataclass:
    def test_text_only_tweet(self):
        t = Tweet(text="Hello world")
        assert t.text == "Hello world"
        assert t.video_path is None

    def test_video_only_tweet(self):
        t = Tweet(video_path="/tmp/video.mp4")
        assert t.video_path == "/tmp/video.mp4"
        assert t.text is None

    def test_raises_when_both_none(self):
        with pytest.raises(ValueError, match="must have either text or video_path"):
            Tweet()

    def test_raises_when_text_too_long(self):
        long_text = "A" * 281
        with pytest.raises(ValueError, match="exceeds"):
            Tweet(text=long_text)

    def test_text_at_exact_max_length_is_valid(self):
        text = "A" * twitter_client.MAX_TWEET_LENGTH
        t = Tweet(text=text)
        assert t.text == text

    def test_video_and_text_together(self):
        t = Tweet(text="Caption", video_path="/tmp/v.mp4")
        assert t.text == "Caption"
        assert t.video_path == "/tmp/v.mp4"


# ------------------------------------------------------------------ #
# post_thread                                                          #
# ------------------------------------------------------------------ #


class TestPostThread:
    def test_thread_mode_posts_reply(self):
        client = MagicMock()
        client.create_tweet.side_effect = [
            _make_tweet_response("111"),
            _make_tweet_response("222"),
        ]
        ids = twitter_client.post_thread(
            [Tweet(text="Arabic text"), Tweet(text="English text")],
            mode="thread",
            client=client,
        )
        assert ids == ["111", "222"]
        # Second call must include in_reply_to_tweet_id pointing at first tweet
        second_kwargs = client.create_tweet.call_args_list[1][1]
        assert second_kwargs.get("in_reply_to_tweet_id") == "111"

    def test_separate_mode_no_reply(self):
        client = MagicMock()
        client.create_tweet.side_effect = [
            _make_tweet_response("333"),
            _make_tweet_response("444"),
        ]
        twitter_client.post_thread(
            [Tweet(text="Arabic"), Tweet(text="English")],
            mode="separate",
            client=client,
        )
        second_kwargs = client.create_tweet.call_args_list[1][1]
        assert "in_reply_to_tweet_id" not in second_kwargs

    def test_returns_all_tweet_ids(self):
        client = MagicMock()
        client.create_tweet.side_effect = [
            _make_tweet_response("aaa"),
            _make_tweet_response("bbb"),
        ]
        ids = twitter_client.post_thread(
            [Tweet(text="ar"), Tweet(text="en")],
            client=client,
        )
        assert len(ids) == 2

    def test_video_tweet_uploads_media_and_attaches_id(self):
        client = MagicMock()
        api = MagicMock()
        api.media_upload.return_value = MagicMock(media_id=9999)
        client.create_tweet.side_effect = [
            _make_tweet_response("aaa"),
            _make_tweet_response("bbb"),
            _make_tweet_response("ccc"),
        ]
        ids = twitter_client.post_thread(
            [
                Tweet(text="Arabic"),
                Tweet(text="English"),
                Tweet(video_path="/tmp/v.mp4"),
            ],
            mode="thread",
            client=client,
            api=api,
        )
        assert ids == ["aaa", "bbb", "ccc"]
        # Video tweet must have media_ids
        third_kwargs = client.create_tweet.call_args_list[2][1]
        assert third_kwargs.get("media_ids") == ["9999"]
        # Text tweets must not have media_ids
        first_kwargs = client.create_tweet.call_args_list[0][1]
        assert "media_ids" not in first_kwargs

    def test_thread_reply_chain_with_video(self):
        client = MagicMock()
        api = MagicMock()
        api.media_upload.return_value = MagicMock(media_id=111222)
        client.create_tweet.side_effect = [
            _make_tweet_response("111"),
            _make_tweet_response("222"),
            _make_tweet_response("333"),
        ]
        twitter_client.post_thread(
            [
                Tweet(text="ar"),
                Tweet(text="en"),
                Tweet(video_path="/tmp/v.mp4"),
            ],
            mode="thread",
            client=client,
            api=api,
        )
        # English replies to Arabic
        second_kwargs = client.create_tweet.call_args_list[1][1]
        assert second_kwargs.get("in_reply_to_tweet_id") == "111"
        # Video replies to English
        third_kwargs = client.create_tweet.call_args_list[2][1]
        assert third_kwargs.get("in_reply_to_tweet_id") == "222"

    def test_separate_mode_no_reply_for_video(self):
        client = MagicMock()
        api = MagicMock()
        api.media_upload.return_value = MagicMock(media_id=111)
        client.create_tweet.side_effect = [
            _make_tweet_response("333"),
            _make_tweet_response("444"),
            _make_tweet_response("555"),
        ]
        twitter_client.post_thread(
            [Tweet(text="ar"), Tweet(text="en"), Tweet(video_path="/tmp/v.mp4")],
            mode="separate",
            client=client,
            api=api,
        )
        second_kwargs = client.create_tweet.call_args_list[1][1]
        assert "in_reply_to_tweet_id" not in second_kwargs
        third_kwargs = client.create_tweet.call_args_list[2][1]
        assert "in_reply_to_tweet_id" not in third_kwargs

    def test_propagates_api_error(self):
        client = MagicMock()
        client.create_tweet.side_effect = Exception("Rate limit exceeded")
        with pytest.raises(Exception, match="Rate limit exceeded"):
            twitter_client.post_thread(
                [Tweet(text="ar")],
                client=client,
            )


# ------------------------------------------------------------------ #
# upload_video                                                         #
# ------------------------------------------------------------------ #


class TestUploadVideo:
    def test_returns_media_id_string(self):
        api = MagicMock()
        api.media_upload.return_value = MagicMock(media_id=99887766)
        result = twitter_client.upload_video("/tmp/video.mp4", api=api)
        assert result == "99887766"
        api.media_upload.assert_called_once_with(
            filename="/tmp/video.mp4",
            media_category="tweet_video",
            chunked=True,
        )


class TestCredentialValidation:
    def test_make_client_raises_when_credentials_missing(self):
        with pytest.raises(ValueError, match="Missing required Twitter credentials"):
            twitter_client._make_client(
                Secrets(
                    twitter_api_key=None,
                    twitter_api_secret="secret",
                    twitter_access_token="token",
                    twitter_access_token_secret="token_secret",
                )
            )

    def test_make_api_raises_when_credentials_missing(self):
        with pytest.raises(ValueError, match="Missing required Twitter credentials"):
            twitter_client._make_api(
                Secrets(
                    twitter_api_key="key",
                    twitter_api_secret=None,
                    twitter_access_token="token",
                    twitter_access_token_secret="token_secret",
                )
            )


# ------------------------------------------------------------------ #
# _format_tweet                                                        #
# ------------------------------------------------------------------ #


class TestFormatTweet:
    def test_short_verse_returns_single_tweet(self):
        result = twitter_client._format_tweet("Hello", "Al-Fatiha", 1, 280)
        assert result == ['"Hello" {Al-Fatiha:1}']

    def test_long_verse_splits_into_multiple_tweets(self):
        long_text = "A" * 300
        result = twitter_client._format_tweet(long_text, "Al-Baqarah", 5, 280)
        assert isinstance(result, list)
        assert len(result) > 1
        assert all(len(t) <= 280 for t in result)
        assert result[-1].endswith("{Al-Baqarah:5}")

    def test_attribution_always_on_last_tweet(self):
        result = twitter_client._format_tweet("short", "Al-Nas", 6, 40)
        assert any("{Al-Nas:6}" in t for t in result)

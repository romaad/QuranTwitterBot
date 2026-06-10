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


class TestPostVideoThread:
    def _make_client_with_ids(self, *ids):
        client = MagicMock()
        client.create_tweet.side_effect = [_make_tweet_response(i) for i in ids]
        return client

    def _make_api_with_media_id(self, media_id="111222"):
        api = MagicMock()
        api.media_upload.return_value = MagicMock(media_id=int(media_id))
        return api

    def test_arabic_tweet_has_no_video_attachment(self):
        client = self._make_client_with_ids("aaa", "bbb", "ccc")
        api = self._make_api_with_media_id("9999")
        twitter_client.post_video_thread(
            video_path="/tmp/video.mp4",
            arabic_text="ar",
            english_text="en",
            chapter_name_arabic="الفاتحة",
            chapter_name_english="The Opener",
            verse_start=1,
            verse_end=5,
            client=client,
            api=api,
        )
        first_call_kwargs = client.create_tweet.call_args_list[0][1]
        assert "media_ids" not in first_call_kwargs

    def test_attaches_media_id_to_video_tweet(self):
        client = self._make_client_with_ids("aaa", "bbb", "ccc")
        api = self._make_api_with_media_id("9999")
        twitter_client.post_video_thread(
            video_path="/tmp/video.mp4",
            arabic_text="ar",
            english_text="en",
            chapter_name_arabic="الفاتحة",
            chapter_name_english="The Opener",
            verse_start=1,
            verse_end=5,
            client=client,
            api=api,
        )
        third_call_kwargs = client.create_tweet.call_args_list[2][1]
        assert third_call_kwargs.get("media_ids") == ["9999"]

    def test_thread_mode_reply_chain(self):
        client = self._make_client_with_ids("111", "222", "333")
        api = self._make_api_with_media_id()
        twitter_client.post_video_thread(
            video_path="/tmp/v.mp4",
            arabic_text="ar",
            english_text="en",
            chapter_name_arabic="ch",
            chapter_name_english="ch",
            verse_start=1,
            verse_end=5,
            mode="thread",
            client=client,
            api=api,
        )
        # English replies to Arabic
        second_call_kwargs = client.create_tweet.call_args_list[1][1]
        assert second_call_kwargs.get("in_reply_to_tweet_id") == "111"
        # Video replies to English
        third_call_kwargs = client.create_tweet.call_args_list[2][1]
        assert third_call_kwargs.get("in_reply_to_tweet_id") == "222"

    def test_separate_mode_no_reply(self):
        client = self._make_client_with_ids("333", "444", "555")
        api = self._make_api_with_media_id()
        twitter_client.post_video_thread(
            video_path="/tmp/v.mp4",
            arabic_text="ar",
            english_text="en",
            chapter_name_arabic="ch",
            chapter_name_english="ch",
            verse_start=1,
            verse_end=5,
            mode="separate",
            client=client,
            api=api,
        )
        second_call_kwargs = client.create_tweet.call_args_list[1][1]
        assert "in_reply_to_tweet_id" not in second_call_kwargs
        third_call_kwargs = client.create_tweet.call_args_list[2][1]
        assert "in_reply_to_tweet_id" not in third_call_kwargs

    def test_single_verse_label_has_no_dash(self):
        client = self._make_client_with_ids("x1", "x2", "x3")
        api = self._make_api_with_media_id()
        twitter_client.post_video_thread(
            video_path="/tmp/v.mp4",
            arabic_text="text",
            english_text="text",
            chapter_name_arabic="ch",
            chapter_name_english="ch",
            verse_start=3,
            verse_end=3,
            client=client,
            api=api,
        )
        first_tweet_text = client.create_tweet.call_args_list[0][1]["text"]
        assert ":3}" in first_tweet_text
        assert "-" not in first_tweet_text

    def test_range_verse_label_has_dash(self):
        client = self._make_client_with_ids("y1", "y2", "y3")
        api = self._make_api_with_media_id()
        twitter_client.post_video_thread(
            video_path="/tmp/v.mp4",
            arabic_text="text",
            english_text="text",
            chapter_name_arabic="ch",
            chapter_name_english="ch",
            verse_start=1,
            verse_end=5,
            client=client,
            api=api,
        )
        first_tweet_text = client.create_tweet.call_args_list[0][1]["text"]
        assert ":1-5}" in first_tweet_text

    def test_returns_three_tweet_ids(self):
        client = self._make_client_with_ids("p1", "p2", "p3")
        api = self._make_api_with_media_id()
        ids = twitter_client.post_video_thread(
            video_path="/tmp/v.mp4",
            arabic_text="ar",
            english_text="en",
            chapter_name_arabic="ch",
            chapter_name_english="ch",
            verse_start=1,
            verse_end=3,
            client=client,
            api=api,
        )
        assert ids == ["p1", "p2", "p3"]

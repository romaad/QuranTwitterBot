"""
X (Twitter) API v2 client using tweepy.

Reads credentials from environment variables:
    API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET
"""
import os
from typing import Optional

import tweepy


def _make_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["API_KEY"],
        consumer_secret=os.environ["API_SECRET"],
        access_token=os.environ["ACCESS_TOKEN"],
        access_token_secret=os.environ["ACCESS_TOKEN_SECRET"],
    )


def _make_api() -> tweepy.API:
    """Create a tweepy v1.1 API client used for media (video) upload."""
    auth = tweepy.OAuth1UserHandler(
        os.environ["API_KEY"],
        os.environ["API_SECRET"],
        os.environ["ACCESS_TOKEN"],
        os.environ["ACCESS_TOKEN_SECRET"],
    )
    return tweepy.API(auth)


def upload_video(video_path: str, api: Optional[tweepy.API] = None) -> str:
    """
    Upload a video file to X using chunked upload.

    Returns the media_id as a string, ready to pass to ``create_tweet``.
    """
    if api is None:
        api = _make_api()
    media = api.media_upload(
        filename=video_path,
        media_category="tweet_video",
        chunked=True,
    )
    return str(media.media_id)


def post_thread(
    arabic_text: str,
    english_text: str,
    chapter_name_arabic: str,
    chapter_name_english: str,
    verse_number: int,
    max_length: int = 280,
    mode: str = "thread",
    client: Optional[tweepy.Client] = None,
) -> list[str]:
    """
    Post a verse as a tweet (or thread).

    In "thread" mode the Arabic tweet is posted first, then the English
    translation is posted as a reply to it.
    In "separate" mode both tweets are posted independently.

    Returns a list of tweet IDs that were created.
    """
    if client is None:
        client = _make_client()

    arabic_tweet = _format_tweet(
        arabic_text, chapter_name_arabic, verse_number, max_length
    )
    english_tweet = _format_tweet(
        english_text, chapter_name_english, verse_number, max_length
    )

    tweet_ids: list[str] = []

    # Post Arabic tweet
    response = client.create_tweet(text=arabic_tweet)
    arabic_id = str(response.data["id"])
    tweet_ids.append(arabic_id)

    # Post English tweet
    reply_to = arabic_id if mode == "thread" else None
    kwargs = {"text": english_tweet}
    if reply_to:
        kwargs["in_reply_to_tweet_id"] = reply_to
    response = client.create_tweet(**kwargs)
    tweet_ids.append(str(response.data["id"]))

    return tweet_ids


def post_video_thread(
    video_path: str,
    arabic_text: str,
    english_text: str,
    chapter_name_arabic: str,
    chapter_name_english: str,
    verse_start: int,
    verse_end: int,
    max_length: int = 280,
    mode: str = "thread",
    client: Optional[tweepy.Client] = None,
    api: Optional[tweepy.API] = None,
) -> list[str]:
    """
    Upload *video_path* and post a verse-group tweet (or thread).

    The Arabic tweet carries the video attachment; the English translation
    is posted as a reply (thread mode) or independently (separate mode).

    Returns a list of tweet IDs created.
    """
    if client is None:
        client = _make_client()

    verse_label = f"{verse_start}-{verse_end}" if verse_start != verse_end else str(verse_start)
    arabic_tweet = _format_tweet(arabic_text, chapter_name_arabic, verse_label, max_length)
    english_tweet = _format_tweet(english_text, chapter_name_english, verse_label, max_length)

    media_id = upload_video(video_path, api)

    tweet_ids: list[str] = []

    # Post Arabic tweet with video
    response = client.create_tweet(text=arabic_tweet, media_ids=[media_id])
    arabic_id = str(response.data["id"])
    tweet_ids.append(arabic_id)

    # Post English tweet
    reply_to = arabic_id if mode == "thread" else None
    kwargs = {"text": english_tweet}
    if reply_to:
        kwargs["in_reply_to_tweet_id"] = reply_to
    response = client.create_tweet(**kwargs)
    tweet_ids.append(str(response.data["id"]))

    return tweet_ids


def _format_tweet(
    text: str, chapter_name: str, verse_number: "int | str", max_length: int
) -> str:
    """Format verse text with attribution, truncating if needed."""
    attribution = f" {{{chapter_name}:{verse_number}}}"
    body = f'"{text}"'
    full = body + attribution
    if len(full) <= max_length:
        return full
    # Truncate body to fit attribution + ellipsis
    truncated_body = body[: max_length - len(attribution) - 4] + "…\""
    return truncated_body + attribution

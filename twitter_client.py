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


def _format_tweet(text: str, chapter_name: str, verse_number: int, max_length: int) -> str:
    """Format verse text with attribution, truncating if needed."""
    attribution = f" {{{chapter_name}:{verse_number}}}"
    body = f'"{text}"'
    full = body + attribution
    if len(full) <= max_length:
        return full
    # Truncate body to fit attribution + ellipsis
    truncated_body = body[: max_length - len(attribution) - 4] + "…\""
    return truncated_body + attribution

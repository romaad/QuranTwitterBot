"""
X (Twitter) API v2 client using tweepy.

Credentials are loaded via :class:`secrets.Secrets` which reads the
``API_KEY``, ``API_SECRET``, ``ACCESS_TOKEN``, and ``ACCESS_TOKEN_SECRET``
environment variables.
"""
from dataclasses import dataclass
from typing import Optional

import tweepy

from secrets import Secrets

MAX_TWEET_LENGTH = 280


@dataclass
class Tweet:
    """Represents a single tweet: either text-only or a video (with optional caption)."""

    text: str | None = None
    video_path: str | None = None

    def __post_init__(self) -> None:
        if self.text is None and self.video_path is None:
            raise ValueError("Tweet must have either text or video_path")
        if self.text is not None and len(self.text) > MAX_TWEET_LENGTH:
            raise ValueError(
                f"Tweet text exceeds {MAX_TWEET_LENGTH} characters "
                f"({len(self.text)}): {self.text[:50]!r}…"
            )


def _make_client(secrets: Secrets | None = None) -> tweepy.Client:
    if secrets is None:
        secrets = Secrets.from_env()
    return tweepy.Client(
        consumer_key=secrets.twitter_api_key,
        consumer_secret=secrets.twitter_api_secret,
        access_token=secrets.twitter_access_token,
        access_token_secret=secrets.twitter_access_token_secret,
    )


def _make_api(secrets: Secrets | None = None) -> tweepy.API:
    """Create a tweepy v1.1 API client used for media (video) upload."""
    if secrets is None:
        secrets = Secrets.from_env()
    auth = tweepy.OAuth1UserHandler(
        secrets.twitter_api_key,
        secrets.twitter_api_secret,
        secrets.twitter_access_token,
        secrets.twitter_access_token_secret,
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
    tweets: list[Tweet],
    mode: str = "thread",
    client: Optional[tweepy.Client] = None,
    api: Optional[tweepy.API] = None,
) -> list[str]:
    """
    Post a list of :class:`Tweet` objects as a thread.

    Each tweet may contain text, a video, or both.  In ``"thread"`` mode every
    tweet after the first is posted as a reply to the previous one.  In
    ``"separate"`` mode each tweet is posted independently.

    Returns the list of created tweet IDs in posting order.
    """
    if client is None:
        client = _make_client()

    tweet_ids: list[str] = []
    prev_id: str | None = None

    for tweet in tweets:
        kwargs: dict = {}
        if prev_id and mode == "thread":
            kwargs["in_reply_to_tweet_id"] = prev_id

        if tweet.video_path:
            media_id = upload_video(tweet.video_path, api)
            kwargs["text"] = tweet.text or "\u200b"  # zero-width space filler
            kwargs["media_ids"] = [media_id]
        else:
            kwargs["text"] = tweet.text

        response = client.create_tweet(**kwargs)
        tweet_id = str(response.data["id"])
        tweet_ids.append(tweet_id)
        prev_id = tweet_id

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

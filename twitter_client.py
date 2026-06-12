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


def _require_twitter_credentials(secrets: Secrets) -> tuple[str, str, str, str]:
    """Return required Twitter credentials or raise a clear error."""
    missing: list[str] = []
    if not secrets.twitter_api_key:
        missing.append("API_KEY")
    if not secrets.twitter_api_secret:
        missing.append("API_SECRET")
    if not secrets.twitter_access_token:
        missing.append("ACCESS_TOKEN")
    if not secrets.twitter_access_token_secret:
        missing.append("ACCESS_TOKEN_SECRET")

    if missing:
        raise ValueError("Missing required Twitter credentials: " + ", ".join(missing))

    return (
        secrets.twitter_api_key,
        secrets.twitter_api_secret,
        secrets.twitter_access_token,
        secrets.twitter_access_token_secret,
    )


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
    api_key, api_secret, access_token, access_token_secret = (
        _require_twitter_credentials(secrets)
    )
    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )


def _make_api(secrets: Secrets | None = None) -> tweepy.API:
    """Create a tweepy v1.1 API client used for media (video) upload."""
    if secrets is None:
        secrets = Secrets.from_env()
    api_key, api_secret, access_token, access_token_secret = (
        _require_twitter_credentials(secrets)
    )
    auth = tweepy.OAuth1UserHandler(
        api_key,
        api_secret,
        access_token,
        access_token_secret,
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
    text: str, chapter_name: str, verse_number: int | str, max_length: int
) -> list[str]:
    """Format verse text with attribution, splitting into multiple tweets if needed.

    The attribution suffix ``{chapter_name:verse_number}`` is appended to the
    *last* tweet only.  If the full quoted text fits within *max_length* it is
    returned as a single-element list; otherwise the text is split on word
    boundaries so every tweet stays within *max_length*.
    """
    attribution = f" {{{chapter_name}:{verse_number}}}"
    # Characters available for the inner text (excluding surrounding "…" quotes)
    last_budget = max_length - 2 - len(attribution)
    mid_budget = max_length - 2

    if len(text) <= last_budget:
        return [f'"{text}"' + attribution]

    tweets: list[str] = []
    remaining = text
    while len(remaining) > last_budget:
        split_at = remaining.rfind(" ", 0, mid_budget + 1)
        if split_at <= 0:
            split_at = mid_budget
        tweets.append(f'"{remaining[:split_at]}"')
        remaining = remaining[split_at:].lstrip()

    tweets.append(f'"{remaining}"' + attribution)
    return tweets

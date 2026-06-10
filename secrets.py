"""
Centralised secrets / credentials management.

All API keys and tokens are read from environment variables so that nothing
sensitive is ever hard-coded.  Instantiate :class:`Secrets` via
:meth:`Secrets.from_env` at application start-up and pass the object where
credentials are needed.
"""
import os
from dataclasses import dataclass


@dataclass
class Secrets:
    """Holds all credentials required by the bot."""

    twitter_api_key: str
    twitter_api_secret: str
    twitter_access_token: str
    twitter_access_token_secret: str
    pexels_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Secrets":
        """Load all credentials from environment variables.

        Raises ``KeyError`` if any mandatory Twitter variable is absent.
        ``PEXELS_API_KEY`` is optional; its absence means Pexels integration
        will be skipped.
        """
        return cls(
            twitter_api_key=os.environ["API_KEY"],
            twitter_api_secret=os.environ["API_SECRET"],
            twitter_access_token=os.environ["ACCESS_TOKEN"],
            twitter_access_token_secret=os.environ["ACCESS_TOKEN_SECRET"],
            pexels_api_key=os.environ.get("PEXELS_API_KEY"),
        )

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

    twitter_api_key: str | None = None
    twitter_api_secret: str | None = None
    twitter_access_token: str | None = None
    twitter_access_token_secret: str | None = None
    pexels_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Secrets":
        """Load all credentials from environment variables.

        Missing variables are returned as ``None`` and should be validated by
        the caller that needs them.
        """
        return cls(
            twitter_api_key=os.environ.get("API_KEY"),
            twitter_api_secret=os.environ.get("API_SECRET"),
            twitter_access_token=os.environ.get("ACCESS_TOKEN"),
            twitter_access_token_secret=os.environ.get("ACCESS_TOKEN_SECRET"),
            pexels_api_key=os.environ.get("PEXELS_API_KEY"),
        )

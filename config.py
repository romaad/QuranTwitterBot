"""
Bot configuration. Edit this file to control scheduling and behaviour.
All settings are plain Python — no extra config file format needed.
"""
from dataclasses import dataclass


@dataclass
class BotConfig:
    # ------------------------------------------------------------------ #
    # Scheduling                                                           #
    # ------------------------------------------------------------------ #
    # Cron expression: minute hour day-of-month month day-of-week
    # Default: 7 times a day at 8am, 10am, 12pm, 2pm, 4pm, 6pm, and 8pm UTC
    schedule_cron: str = "0 8,10,12,14,16,18,20 * * *"

    # ------------------------------------------------------------------ #
    # Posting behaviour                                                    #
    # ------------------------------------------------------------------ #
    # "thread" posts Arabic tweet first, then English as a reply.
    # "separate" posts two independent tweets.
    tweet_mode: str = "thread"

    # Maximum characters per tweet (X limit is 280).
    max_tweet_length: int = 280

    # Translation ID used with the quran.com v4 API.
    # 20 = Saheeh International (English)
    translation_id: int = 20

    # ------------------------------------------------------------------ #
    # Quran traversal                                                      #
    # ------------------------------------------------------------------ #
    # Total number of chapters in the Quran.
    num_chapters: int = 114

    # ------------------------------------------------------------------ #
    # Video posts (Phase 4 — not yet implemented)                          #
    # ------------------------------------------------------------------ #
    enable_video: bool = False

    # ------------------------------------------------------------------ #
    # SQLite path                                                          #
    # ------------------------------------------------------------------ #
    db_path: str = "data/quran_bot.db"


# Singleton used throughout the application.
config = BotConfig()

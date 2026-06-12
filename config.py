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
    # Video posts                                                          #
    # ------------------------------------------------------------------ #
    enable_video: bool = False

    # Recitation ID used with the quran.com v4 API.
    # 7 = Abdul Basit Abdul Samad (Murattal)
    recitation_id: int = 7

    # Path to the background nature video file.
    # Used as fallback when PEXELS_API_KEY is not set.
    nature_video_path: str = "assets/nature.mp4"

    # Pexels search queries used to auto-fetch background nature videos.
    # One video is fetched per query and they are mixed together with a fade
    # transition.  The PEXELS_API_KEY environment variable must be set to
    # enable auto-fetching; otherwise *nature_video_path* is used.
    nature_video_queries: tuple[str, ...] = (
        "nature",
        "nature birds",
        "nature forest",
        "nature waterfall",
        "natural",
    )

    # Output video dimensions for mobile portrait (9:16) aspect ratio.
    # Set both to 0 to skip the crop/scale step.
    video_width: int = 1080
    video_height: int = 1920

    # How much to darken the background video (0.0 = no darkening, 1.0 = black).
    # How much to darken the background video (0.0 = no darkening, 1.0 = black).
    video_darken: float = 0.15

    # Arabic subtitle font size used in ASS style configuration.
    # Previously 40; increased by 50% to 60.
    subtitle_arabic_font_size: int = 80

    # English subtitle font size used in ASS style configuration.
    # Doubled from the old value (20 -> 40).
    subtitle_english_font_size: int = 40

    # Maximum Arabic words per subtitle chunk.
    subtitle_max_arabic_words: int = 12

    # Bottom margins (in ASS pixels). Lower value means closer to bottom edge.
    subtitle_arabic_margin_v: int = 220
    subtitle_english_margin_v: int = 120

    # Side margin used when estimating subtitle wrapping width.
    subtitle_side_margin: int = 40

    # Number of Arabic characters per subtitle screen chunk.
    subtitle_chunk_size: int = 85

    # ------------------------------------------------------------------ #
    # SQLite path                                                          #
    # ------------------------------------------------------------------ #
    db_path: str = "data/quran_bot.db"


# Singleton used throughout the application.
config = BotConfig()

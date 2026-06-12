"""
Main bot entry-point.

Runs an APScheduler cron job that:
1. Reads the current position from SQLite.
2. Fetches the ruku (or single verse) from the Quran API.
3. Posts to X (Twitter).
4. Logs the result to verse_history.
5. Advances state on success.
"""

import logging
import os
import tempfile

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import db
import quran_api
import twitter_client
import video_maker
from config import config
from pexels import PexelsClient
from secrets import Secrets
from twitter_client import Tweet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


def _next_position(chapter: int, verse: int, verses_in_chapter: int) -> tuple[int, int]:
    """Return the (chapter, verse) that follows the given position."""
    if verse < verses_in_chapter:
        return chapter, verse + 1
    # Move to next chapter, wrapping around after chapter 114
    next_chapter = chapter + 1 if chapter < config.num_chapters else 1
    return next_chapter, 1


def post_verse(db_path: str = None) -> None:
    """
    Core posting cycle. Exposed as a standalone function so tests can call
    it directly without the scheduler.
    """
    if db_path is None:
        db_path = config.db_path

    db.init_db(db_path)

    with db.get_connection(db_path) as conn:
        state = db.get_state(conn)
        chapter_num = state["current_chapter"]
        verse_num = state["current_verse"]

        log.info("Posting chapter %d, verse %d", chapter_num, verse_num)

        arabic_text = ""
        english_text = ""
        tweet_ids: list = []
        error_msg = None
        status = "failed"

        try:
            chapter = quran_api.get_chapter(chapter_num)
            verse = quran_api.get_verse(chapter_num, verse_num, config.translation_id)

            arabic_text = quran_api.extract_arabic(verse)
            english_text = quran_api.extract_english(verse)

            chapter_name_ar = chapter.get("name_arabic", "")
            chapter_name_en = chapter.get("translated_name", {}).get("name", "")

            tweets = [
                Tweet(text=t)
                for t in twitter_client._format_tweet(
                    arabic_text, chapter_name_ar, verse_num, config.max_tweet_length
                )
            ] + [
                Tweet(text=t)
                for t in twitter_client._format_tweet(
                    english_text, chapter_name_en, verse_num, config.max_tweet_length
                )
            ]
            tweet_ids = twitter_client.post_thread(tweets, mode=config.tweet_mode)
            status = "success"
            log.info("Posted tweets: %s", tweet_ids)

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            log.error("Failed to post verse: %s", error_msg)

        # Always log the attempt — even on failure
        db.log_verse(
            conn=conn,
            chapter_number=chapter_num,
            verse_number=verse_num,
            arabic_text=arabic_text,
            english_text=english_text,
            tweet_ids=tweet_ids,
            status=status,
            error_message=error_msg,
        )

        # Only advance state on success
        if status == "success":
            chapter_for_next = quran_api.get_chapter(chapter_num)
            next_ch, next_v = _next_position(
                chapter_num, verse_num, chapter_for_next["verses_count"]
            )
            db.save_state(conn, next_ch, next_v)
            log.info("State advanced to chapter %d, verse %d", next_ch, next_v)


def _fetch_background_videos(secrets: Secrets, work_dir: str) -> list[str]:
    """
    Return the list of background video paths to use for the ruku video.

    When *secrets.pexels_api_key* is set, one video is fetched per query in
    *config.nature_video_queries* using :class:`~pexels.PexelsClient` and
    saved inside *work_dir*.  Otherwise the single local file at
    *config.nature_video_path* is used.
    """
    if secrets.pexels_api_key:
        client = PexelsClient(secrets.pexels_api_key)
        paths: list[str] = []
        for i, query in enumerate(config.nature_video_queries):
            dest = os.path.join(work_dir, f"nature_bg_{i:02d}.mp4")
            client.fetch_video(query, dest)
            paths.append(dest)
        return paths
    return [config.nature_video_path]


def post_ruku_group(db_path: str = None) -> None:
    """
    Post all verses in the current ruku as a single video tweet thread.

    Uses the Quran API's ruku endpoint to retrieve all verses in the current
    ruku in one call, then builds a video (with optional Pexels background and
    verse-text subtitle overlay), and posts a three-tweet thread:
    Arabic text → English text → video.

    Credentials are loaded from environment variables via
    :class:`~secrets.Secrets`.  State is advanced to the first verse of the
    next ruku on success.
    """
    if db_path is None:
        db_path = config.db_path

    db.init_db(db_path)

    with db.get_connection(db_path) as conn:
        state = db.get_state(conn)
        chapter_num = state["current_chapter"]
        verse_num = state["current_verse"]

        log.info(
            "Posting ruku group starting at chapter %d, verse %d",
            chapter_num,
            verse_num,
        )

        arabic_text = ""
        english_text = ""
        tweet_ids: list = []
        error_msg = None
        status = "failed"
        verses = []

        try:
            secrets = Secrets.from_env()

            # ── 1. Identify ruku number ───────────────────────────────── #
            start_verse_data = quran_api.get_verse(
                chapter_num, verse_num, config.translation_id
            )
            ruku_number = quran_api.extract_ruku_number(start_verse_data)
            log.info("Current verse is in ruku %s", ruku_number)

            # ── 2. Fetch all verses in this ruku ─────────────────────── #
            verses = quran_api.get_verses_by_ruku(
                ruku_number, config.translation_id, config.recitation_id
            )
            log.info(
                "Ruku %s spans %d verse(s): %s … %s",
                ruku_number,
                len(verses),
                verses[0].verse_key,
                verses[-1].verse_key,
            )

            arabic_text = " ".join(v.arabic for v in verses)
            english_text = " ".join(v.english for v in verses)

            first_verse = verses[0]
            last_verse = verses[-1]
            chapter_data = quran_api.get_chapter(first_verse.chapter_number)
            chapter_name_ar = chapter_data.get("name_arabic", "")
            chapter_name_en = chapter_data.get("translated_name", {}).get("name", "")
            verse_label = (
                f"{first_verse.verse_number}-{last_verse.verse_number}"
                if first_verse.verse_number != last_verse.verse_number
                else str(first_verse.verse_number)
            )

            with tempfile.TemporaryDirectory(prefix="quran_ruku_") as tmp_dir:
                output_path = os.path.join(tmp_dir, "output.mp4")
                nature_paths = _fetch_background_videos(secrets, tmp_dir)

                video_maker.build_video(
                    ruku_number=ruku_number,
                    nature_video_paths=nature_paths,
                    output_path=output_path,
                )

                arabic_tweets = [
                    Tweet(text=t)
                    for t in twitter_client._format_tweet(
                        arabic_text,
                        chapter_name_ar,
                        verse_label,
                        config.max_tweet_length,
                    )
                ]
                english_tweets = [
                    Tweet(text=t)
                    for t in twitter_client._format_tweet(
                        english_text,
                        chapter_name_en,
                        verse_label,
                        config.max_tweet_length,
                    )
                ]
                tweet_ids = twitter_client.post_thread(
                    arabic_tweets + english_tweets + [Tweet(video_path=output_path)],
                    mode=config.tweet_mode,
                )

            status = "success"
            log.info("Posted ruku video tweets: %s", tweet_ids)

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            log.error("Failed to post ruku group: %s", error_msg)

        db.log_verse(
            conn=conn,
            chapter_number=chapter_num,
            verse_number=verse_num,
            arabic_text=arabic_text,
            english_text=english_text,
            tweet_ids=tweet_ids,
            status=status,
            error_message=error_msg,
        )

        # Advance state to the first verse of the next ruku
        if status == "success":
            last_ch = verses[-1].chapter_number
            last_v = verses[-1].verse_number
            chapter_data = quran_api.get_chapter(last_ch)
            next_ch, next_v = _next_position(
                last_ch, last_v, chapter_data["verses_count"]
            )
            db.save_state(conn, next_ch, next_v)
            log.info("State advanced to chapter %d, verse %d", next_ch, next_v)


def run_scheduler(
    db_path: str | None = None,
    schedule_cron: str | None = None,
    enable_video: bool | None = None,
) -> None:
    """Start the APScheduler loop with optional runtime overrides."""
    if db_path is None:
        db_path = config.db_path
    if schedule_cron is None:
        schedule_cron = config.schedule_cron
    if enable_video is None:
        enable_video = config.enable_video

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db.init_db(db_path)

    scheduler = BlockingScheduler(timezone="UTC")
    trigger = CronTrigger.from_crontab(schedule_cron)
    if enable_video:
        job = post_ruku_group
    else:
        job = post_verse
    scheduler.add_job(job, trigger)

    log.info("Scheduler started. Cron: %s  DB: %s", schedule_cron, db_path)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    __import__("main").main()

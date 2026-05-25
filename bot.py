"""
Main bot entry-point.

Runs an APScheduler cron job that:
1. Reads the current position from SQLite.
2. Fetches the verse from the Quran API.
3. Posts to X (Twitter).
4. Logs the result to verse_history.
5. Advances state on success.
"""
import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import db
import quran_api
import twitter_client
from config import config

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
            tweet_ids = twitter_client.post_thread(
                arabic_text=arabic_text,
                english_text=english_text,
                chapter_name_arabic=chapter_name_ar,
                chapter_name_english=chapter_name_en,
                verse_number=verse_num,
                max_length=config.max_tweet_length,
                mode=config.tweet_mode,
            )
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


def main() -> None:
    db_path = config.db_path
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db.init_db(db_path)

    scheduler = BlockingScheduler(timezone="UTC")
    trigger = CronTrigger.from_crontab(config.schedule_cron)
    scheduler.add_job(post_verse, trigger)

    log.info(
        "Scheduler started. Cron: %s  DB: %s", config.schedule_cron, db_path
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()

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
import tempfile

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import db
import quran_api
import twitter_client
import video_maker
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


def _collect_group_positions(
    start_chapter: int,
    start_verse: int,
    size: int,
    chapter_cache: dict | None = None,
) -> list[tuple[int, int]]:
    """
    Return a list of *size* consecutive (chapter, verse) positions
    starting at (*start_chapter*, *start_verse*).

    *chapter_cache* is an optional dict that maps chapter numbers to their
    metadata dicts; entries are added lazily to avoid redundant API calls.
    """
    if chapter_cache is None:
        chapter_cache = {}
    positions: list[tuple[int, int]] = []
    chapter, verse = start_chapter, start_verse
    for _ in range(size):
        positions.append((chapter, verse))
        if chapter not in chapter_cache:
            chapter_cache[chapter] = quran_api.get_chapter(chapter)
        verses_count = chapter_cache[chapter]["verses_count"]
        chapter, verse = _next_position(chapter, verse, verses_count)
    return positions


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


def post_verse_group(db_path: str = None) -> None:
    """
    Post a group of consecutive verses as a video tweet.

    Fetches *config.group_size* verses starting from the current position,
    downloads their audio, overlays it on *config.nature_video_path*, and
    posts the resulting video to X.  State is advanced by the full group
    size on success.
    """
    if db_path is None:
        db_path = config.db_path

    db.init_db(db_path)

    with db.get_connection(db_path) as conn:
        state = db.get_state(conn)
        chapter_num = state["current_chapter"]
        verse_num = state["current_verse"]

        log.info(
            "Posting verse group starting at chapter %d, verse %d (size=%d)",
            chapter_num, verse_num, config.group_size,
        )

        arabic_texts: list[str] = []
        english_texts: list[str] = []
        tweet_ids: list = []
        error_msg = None
        status = "failed"
        chapter_cache: dict = {}

        try:
            positions = _collect_group_positions(
                chapter_num, verse_num, config.group_size, chapter_cache
            )

            # Fetch text for all verses
            for ch, v in positions:
                if ch not in chapter_cache:
                    chapter_cache[ch] = quran_api.get_chapter(ch)
                verse = quran_api.get_verse(ch, v, config.translation_id)
                arabic_texts.append(quran_api.extract_arabic(verse))
                english_texts.append(quran_api.extract_english(verse))

            arabic_text = " ".join(arabic_texts)
            english_text = " ".join(english_texts)

            # Fetch audio and build video
            audio_urls = quran_api.get_verses_audio_urls(positions, config.recitation_id)

            first_ch, first_v = positions[0]
            last_ch, last_v = positions[-1]
            chapter_data = chapter_cache[first_ch]
            chapter_name_ar = chapter_data.get("name_arabic", "")
            chapter_name_en = chapter_data.get("translated_name", {}).get("name", "")

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                output_path = tmp.name

            try:
                video_maker.build_video(audio_urls, config.nature_video_path, output_path)

                tweet_ids = twitter_client.post_video_thread(
                    video_path=output_path,
                    arabic_text=arabic_text,
                    english_text=english_text,
                    chapter_name_arabic=chapter_name_ar,
                    chapter_name_english=chapter_name_en,
                    verse_start=first_v,
                    verse_end=last_v,
                    max_length=config.max_tweet_length,
                    mode=config.tweet_mode,
                )
            finally:
                os.unlink(output_path)

            status = "success"
            log.info("Posted video tweets: %s", tweet_ids)

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            log.error("Failed to post verse group: %s", error_msg)

        # Log the first verse of the group as a representative entry
        db.log_verse(
            conn=conn,
            chapter_number=chapter_num,
            verse_number=verse_num,
            arabic_text=" ".join(arabic_texts),
            english_text=" ".join(english_texts),
            tweet_ids=tweet_ids,
            status=status,
            error_message=error_msg,
        )

        # Only advance state on success — move forward by group_size positions
        if status == "success":
            next_ch, next_v = chapter_num, verse_num
            for _ in range(config.group_size):
                if next_ch not in chapter_cache:
                    chapter_cache[next_ch] = quran_api.get_chapter(next_ch)
                verses_count = chapter_cache[next_ch]["verses_count"]
                next_ch, next_v = _next_position(next_ch, next_v, verses_count)
            db.save_state(conn, next_ch, next_v)
            log.info("State advanced to chapter %d, verse %d", next_ch, next_v)


def main() -> None:
    db_path = config.db_path
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db.init_db(db_path)

    scheduler = BlockingScheduler(timezone="UTC")
    trigger = CronTrigger.from_crontab(config.schedule_cron)
    job = post_verse_group if config.enable_video else post_verse
    scheduler.add_job(job, trigger)

    log.info(
        "Scheduler started. Cron: %s  DB: %s", config.schedule_cron, db_path
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()

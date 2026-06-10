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


def _collect_ruku_positions(
    start_chapter: int,
    start_verse: int,
    chapter_cache: dict | None = None,
) -> list[tuple[int, int]]:
    """
    Return all (chapter, verse) positions that belong to the same ruku as
    the verse at (*start_chapter*, *start_verse*).

    Fetches each verse's ``ruku_number`` field from the API and stops as
    soon as the number changes.  *chapter_cache* is an optional dict mapping
    chapter numbers to their metadata dicts; entries are added lazily.
    """
    if chapter_cache is None:
        chapter_cache = {}

    start_verse_data = quran_api.get_verse(start_chapter, start_verse, config.translation_id)
    target_ruku = quran_api.extract_ruku_number(start_verse_data)

    positions: list[tuple[int, int]] = []
    chapter, verse = start_chapter, start_verse

    while True:
        positions.append((chapter, verse))
        if chapter not in chapter_cache:
            chapter_cache[chapter] = quran_api.get_chapter(chapter)
        verses_count = chapter_cache[chapter]["verses_count"]
        next_ch, next_v = _next_position(chapter, verse, verses_count)

        next_verse_data = quran_api.get_verse(next_ch, next_v, config.translation_id)
        next_ruku = quran_api.extract_ruku_number(next_verse_data)
        if next_ruku != target_ruku:
            break
        chapter, verse = next_ch, next_v

    return positions


def _resolve_nature_videos(work_dir: str) -> list[str]:
    """
    Return the list of background video paths to use.

    When ``PEXELS_API_KEY`` is set in the environment, one video is fetched
    per query in *config.nature_video_queries* and saved as separate files
    inside *work_dir*.  Otherwise the single local file at
    *config.nature_video_path* is returned.
    """
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if api_key:
        paths: list[str] = []
        for i, query in enumerate(config.nature_video_queries):
            dest = os.path.join(work_dir, f"nature_bg_{i:02d}.mp4")
            video_maker.fetch_nature_video(query, api_key, dest)
            paths.append(dest)
        return paths
    return [config.nature_video_path]


def post_ruku_group(db_path: str = None) -> None:
    """
    Post all verses in the current ruku as a single video tweet.

    Groups verses automatically by their ``ruku_number`` field from the API,
    so each post covers exactly one natural Quran section regardless of its
    length.  State is advanced to the first verse of the next ruku on success.

    The background video is auto-fetched from Pexels when ``PEXELS_API_KEY``
    is set in the environment; otherwise *config.nature_video_path* is used.
    The output video is scaled/cropped to *config.video_width* ×
    *config.video_height* (default 1080 × 1920, mobile portrait 9:16).
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
            chapter_num, verse_num,
        )

        arabic_texts: list[str] = []
        english_texts: list[str] = []
        tweet_ids: list = []
        error_msg = None
        status = "failed"
        chapter_cache: dict = {}

        try:
            positions = _collect_ruku_positions(chapter_num, verse_num, chapter_cache)
            log.info("Ruku spans %d verses: %s … %s", len(positions), positions[0], positions[-1])

            # Fetch text for all verses in the ruku
            for ch, v in positions:
                if ch not in chapter_cache:
                    chapter_cache[ch] = quran_api.get_chapter(ch)
                verse = quran_api.get_verse(ch, v, config.translation_id)
                arabic_texts.append(quran_api.extract_arabic(verse))
                english_texts.append(quran_api.extract_english(verse))

            arabic_text = " ".join(arabic_texts)
            english_text = " ".join(english_texts)

            audio_urls = quran_api.get_verses_audio_urls(positions, config.recitation_id)

            first_ch, first_v = positions[0]
            last_ch, last_v = positions[-1]
            chapter_data = chapter_cache[first_ch]
            chapter_name_ar = chapter_data.get("name_arabic", "")
            chapter_name_en = chapter_data.get("translated_name", {}).get("name", "")

            with tempfile.TemporaryDirectory(prefix="quran_ruku_") as tmp_dir:
                output_path = os.path.join(tmp_dir, "output.mp4")
                nature_paths = _resolve_nature_videos(tmp_dir)
                video_maker.build_video(
                    audio_urls,
                    nature_paths,
                    output_path,
                    width=config.video_width,
                    height=config.video_height,
                )

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

            status = "success"
            log.info("Posted ruku video tweets: %s", tweet_ids)

        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)
            log.error("Failed to post ruku group: %s", error_msg)

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

        # Advance state to the first verse of the next ruku
        if status == "success":
            # positions already computed; advance one step past the last verse
            last_ch, last_v = positions[-1]
            if last_ch not in chapter_cache:
                chapter_cache[last_ch] = quran_api.get_chapter(last_ch)
            verses_count = chapter_cache[last_ch]["verses_count"]
            next_ch, next_v = _next_position(last_ch, last_v, verses_count)
            db.save_state(conn, next_ch, next_v)
            log.info("State advanced to chapter %d, verse %d", next_ch, next_v)


def main() -> None:
    db_path = config.db_path
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db.init_db(db_path)

    scheduler = BlockingScheduler(timezone="UTC")
    trigger = CronTrigger.from_crontab(config.schedule_cron)
    if config.enable_video:
        job = post_ruku_group
    else:
        job = post_verse
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

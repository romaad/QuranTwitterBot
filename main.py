"""Unified CLI entry point for scheduler and video demo tasks."""

from __future__ import annotations

import argparse
import logging
import os
from dotenv import load_dotenv

load_dotenv()

import bot
import video_maker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger(__name__)


def _add_bot_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("bot", help="Run scheduled posting loop")
    parser.add_argument("--db-path", help="Override SQLite DB path")
    parser.add_argument("--cron", help="Override cron expression")
    parser.add_argument(
        "--enable-video",
        action="store_true",
        help="Use ruku video posting job",
    )
    parser.add_argument(
        "--disable-video",
        action="store_true",
        help="Force text-only verse posting job",
    )


def _add_video_demo_command(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "video-example",
        help="Build a small local sample Quran video",
    )
    parser.add_argument(
        "--ruku",
        type=int,
        default=1,
        help="Ruku number to render (default: 1)",
    )
    parser.add_argument(
        "--verse-limit",
        type=int,
        default=2,
        help="How many verses from the ruku to include (default: 2)",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to store generated assets",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quran bot command-line entry point",
    )
    subparsers = parser.add_subparsers(dest="command")

    _add_bot_command(subparsers)
    _add_video_demo_command(subparsers)
    return parser


def _resolve_enable_video(args: argparse.Namespace) -> bool | None:
    if args.enable_video and args.disable_video:
        raise ValueError("Use only one of --enable-video or --disable-video")
    if args.enable_video:
        return True
    if args.disable_video:
        return False
    return None


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in (None, "bot"):
        enable_video = _resolve_enable_video(args)
        bot.run_scheduler(
            db_path=args.db_path,
            schedule_cron=args.cron,
            enable_video=enable_video,
        )
        return

    if args.command == "video-example":
        output = video_maker.build_video(
            ruku_number=args.ruku,
            verse_limit=args.verse_limit,
            output_dir=args.output_dir,
        )
        log.info("Example video created at %s", output)
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()

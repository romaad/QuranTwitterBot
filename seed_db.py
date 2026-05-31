"""
Seed the SQLite database to resume posting from after a specific verse.

Sets ``current_chapter`` / ``current_verse`` in the state table so the bot
will post that verse on its next scheduled run.  Run this once before (or
instead of) the first ``docker compose up``.

Usage
-----
# Resume after Al-Ankabut (The Spider) 29:60  [default]
python seed_db.py

# Resume after any arbitrary verse, e.g. Al-Baqara 2:255
python seed_db.py 2 256
"""
import os
import sys

import db
from config import config

# ------------------------------------------------------------------ #
# Default seed position: next verse after Al-Ankabut (The Spider) 29:60
# ------------------------------------------------------------------ #
_DEFAULT_CHAPTER = 29
_DEFAULT_VERSE = 61


def seed(chapter: int, verse: int, db_path: str | None = None) -> None:
    """Initialise (or re-seed) the DB so the next post will be chapter:verse."""
    if db_path is None:
        db_path = config.db_path
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    db.init_db(db_path)
    with db.get_connection(db_path) as conn:
        db.save_state(conn, chapter, verse)
    print(f"Database seeded — next verse to post: {chapter}:{verse}")


if __name__ == "__main__":
    ch = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_CHAPTER
    v = int(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_VERSE
    seed(ch, v)

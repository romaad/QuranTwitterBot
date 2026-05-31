# Quran Twitter / X Bot

A Python bot that posts daily Quran verses to X (Twitter).  
Each post tweets the Arabic verse followed by an English translation as a threaded reply.

---

## Quick start

```bash
cp .env.example .env
# Edit .env with your X API credentials
docker compose up -d
```

The container wakes itself up on a cron schedule (default: **daily at 08:00 UTC**).  
Edit `config.py` to change the schedule, tweet mode, or translation.

---

## Resuming from a specific verse

If you've already been posting elsewhere and want the bot to pick up from a
particular point, seed the database before the first run:

```bash
# Resume after Al-Ankabut (The Spider) 29:60 — the default
python seed_db.py

# Resume after any verse, e.g. Al-Baqara 2:255
python seed_db.py 2 256
```

The script creates the database and sets the next verse to post.  Run it
**once**, before `docker compose up -d`.

---

## Configuration (`config.py`)

| Field | Default | Description |
|-------|---------|-------------|
| `schedule_cron` | `"0 8 * * *"` | Cron expression for when to post |
| `tweet_mode` | `"thread"` | `"thread"` (English reply) or `"separate"` |
| `max_tweet_length` | `280` | Truncation limit per tweet |
| `translation_id` | `131` | quran.com translation ID (131 = Saheeh International) |
| `num_chapters` | `114` | Total chapters in the Quran |
| `enable_video` | `False` | Phase 4 video posts (not yet implemented) |
| `db_path` | `"data/quran_bot.db"` | SQLite database path |

---

## Database

SQLite is stored in `./data/` (mounted as a Docker volume for persistence).

- **`state`** — single row tracking the current chapter/verse position.
- **`verse_history`** — append-only log of every posting attempt (success, failed, or skipped) with tweet IDs and error messages.

---

## Development

```bash
pip install -r requirements.txt

# Unit tests only (no network required)
pytest -m "not integration"

# All tests including live Quran API calls
pytest
```

---

## CI

GitHub Actions runs on every push/PR:

1. **Lint** — ruff
2. **Unit tests** — Python 3.11 & 3.12 with coverage
3. **Integration tests** — live Quran API, mocked X API
4. **Docker build** — verifies the `Dockerfile` compiles

---

## Roadmap

- [ ] Phase 4: Video posts with Quran recitation over calm backgrounds


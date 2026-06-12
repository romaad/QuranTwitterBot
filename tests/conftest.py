"""
Shared pytest fixtures.
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import db
import quran_api

# ------------------------------------------------------------------ #
# Local mock Quran API server                                         #
# ------------------------------------------------------------------ #

_CHAPTERS = {
    1: {
        "id": 1,
        "verses_count": 7,
        "name_arabic": "الفاتحة",
        "translated_name": {"name": "The Opener"},
    },
    2: {
        "id": 2,
        "verses_count": 286,
        "name_arabic": "البقرة",
        "translated_name": {"name": "The Cow"},
    },
    3: {
        "id": 3,
        "verses_count": 200,
        "name_arabic": "آل عمران",
        "translated_name": {"name": "Family of Imran"},
    },
}

_VERSES = {
    (1, 1): {
        "id": 1,
        "verse_number": 1,
        "ruku_number": 1,
        "text_uthmani": "بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
        "translations": [
            {
                "id": 131,
                "text": "In the name of Allah, the Entirely Merciful, the Especially Merciful.",
            }
        ],
    },
    (1, 2): {
        "id": 2,
        "verse_number": 2,
        "ruku_number": 1,
        "text_uthmani": "ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَـٰلَمِينَ",
        "translations": [
            {"id": 131, "text": "All praise is due to Allah, Lord of the worlds."}
        ],
    },
    (2, 1): {
        "id": 8,
        "verse_number": 1,
        "ruku_number": 2,
        "text_uthmani": "الٓمٓ",
        "translations": [{"id": 131, "text": "Alif, Lam, Meem."}],
    },
    (3, 1): {
        "id": 293,
        "verse_number": 1,
        "ruku_number": 10,
        "text_uthmani": "الٓمٓ",
        "translations": [{"id": 131, "text": "Alif, Lam, Meem."}],
    },
}


class _QuranHandler(BaseHTTPRequestHandler):
    """Minimal request handler that serves fixture data for the Quran API v4."""

    def log_message(self, format, *args):  # noqa: A002 — suppress request logs
        pass

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        # GET /api/v4/chapters/{n}
        m = re.match(r"^/api/v4/chapters/(\d+)$", path)
        if m:
            n = int(m.group(1))
            if n in _CHAPTERS:
                self._send_json(200, {"chapter": _CHAPTERS[n]})
            else:
                self._send_json(404, {"error": "chapter not found"})
            return

        # GET /api/v4/verses/by_chapter/{n}
        m = re.match(r"^/api/v4/verses/by_chapter/(\d+)$", path)
        if m:
            chapter = int(m.group(1))
            qs = parse_qs(parsed.query)
            page = int(qs.get("page", ["1"])[0])
            verse = _VERSES.get((chapter, page))
            if verse:
                self._send_json(200, {"verses": [verse]})
            else:
                self._send_json(404, {"error": "verse not found"})
            return

        self._send_json(404, {"error": "not found"})

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="session")
def quran_local_server():
    """Start a local mock Quran API server once per test session. Returns its base URL."""
    server = HTTPServer(("127.0.0.1", 0), _QuranHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


@pytest.fixture()
def patch_quran_url(quran_local_server):
    """Redirect quran_api to the local mock server for the duration of a test."""
    original = quran_api.BASE_URL
    quran_api.BASE_URL = f"{quran_local_server}/api/v4"
    yield
    quran_api.BASE_URL = original


# ------------------------------------------------------------------ #
# Database fixtures                                                    #
# ------------------------------------------------------------------ #


@pytest.fixture()
def mem_db():
    """In-memory SQLite database for fast unit tests."""
    db.init_db(":memory:")
    # Return the path string; tests open their own connections
    return ":memory:"


@pytest.fixture()
def tmp_db(tmp_path):
    """File-based SQLite in a temp directory for integration tests."""
    path = str(tmp_path / "test_quran.db")
    db.init_db(path)
    return path


@pytest.fixture()
def db_at_last_verse(tmp_db):
    """
    Seed state at the last verse of chapter 1 (Al-Fatiha has 7 verses).
    Useful for testing chapter-advance logic.
    """
    with db.get_connection(tmp_db) as conn:
        db.save_state(conn, chapter=1, verse=7)
    return tmp_db

"""
Quran.com API v4 client.

Docs: https://api.quran.com/api/v4
"""
import requests

BASE_URL = "https://api.quran.com/api/v4"

_session = requests.Session()
_session.headers.update({"Accept": "application/json"})


def get_chapter(chapter_number: int) -> dict:
    """
    Fetch metadata for a single chapter.

    Returns the chapter dict, e.g.:
    {
        "id": 1,
        "verses_count": 7,
        "name_arabic": "الفاتحة",
        "translated_name": {"name": "The Opener", ...},
        ...
    }
    """
    url = f"{BASE_URL}/chapters/{chapter_number}"
    response = _session.get(url, timeout=15)
    response.raise_for_status()
    return response.json()["chapter"]


def get_verse(chapter_number: int, verse_number: int, translation_id: int = 131) -> dict:
    """
    Fetch a single verse by chapter + verse number (1-based).

    Returns a dict with keys:
    - text_uthmani  (Arabic text)
    - translations  (list with at least one entry whose 'text' is the English translation)
    """
    url = f"{BASE_URL}/verses/by_chapter/{chapter_number}"
    params = {
        "translations": translation_id,
        "fields": "text_uthmani",
        "per_page": 1,
        # verse_number is 1-based; the API accepts verse_key like "1:1"
        # but offset+limit on by_chapter is simpler for sequential traversal.
        "page": verse_number,
    }
    response = _session.get(url, params=params, timeout=15)
    response.raise_for_status()
    verses = response.json().get("verses", [])
    if not verses:
        raise ValueError(
            f"No verse found for chapter {chapter_number}, verse {verse_number}"
        )
    return verses[0]


def extract_arabic(verse: dict) -> str:
    """Return the Uthmani Arabic text from a verse dict."""
    return verse.get("text_uthmani", "")


def extract_english(verse: dict) -> str:
    """Return the English translation text from a verse dict."""
    translations = verse.get("translations", [])
    if not translations:
        return ""
    # Strip any HTML tags the API may include
    text = translations[0].get("text", "")
    return _strip_html(text)


def _strip_html(text: str) -> str:
    """Remove simple HTML tags from a string."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()

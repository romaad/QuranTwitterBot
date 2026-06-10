"""
Quran.com API v4 client.

Docs: https://api.quran.com/api/v4
"""
import requests

BASE_URL = "https://api.quran.com/api/v4"
AUDIO_CDN_BASE = "https://verses.quran.com/"

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
        "fields": "text_uthmani,ruku_number",
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


def extract_ruku_number(verse: dict) -> int | None:
    """Return the ruku number from a verse dict, or None if absent."""
    return verse.get("ruku_number")


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


def get_verse_audio_url(
    chapter_number: int, verse_number: int, recitation_id: int = 7
) -> str:
    """
    Fetch the audio URL for a single verse.

    Returns a fully-qualified HTTPS URL pointing to the MP3 file.
    """
    url = f"{BASE_URL}/recitations/{recitation_id}/by_chapter/{chapter_number}"
    params = {"per_page": 1, "page": verse_number}
    response = _session.get(url, params=params, timeout=15)
    response.raise_for_status()
    audio_files = response.json().get("audio_files", [])
    if not audio_files:
        raise ValueError(
            f"No audio found for chapter {chapter_number}, verse {verse_number}"
        )
    raw_url = audio_files[0].get("url", "")
    return _normalise_audio_url(raw_url)


def get_verses_audio_urls(
    positions: list[tuple[int, int]], recitation_id: int = 7
) -> list[str]:
    """
    Fetch audio URLs for a list of (chapter, verse) positions.

    Returns a list of fully-qualified HTTPS URLs in the same order.
    """
    return [
        get_verse_audio_url(ch, v, recitation_id) for ch, v in positions
    ]


def _normalise_audio_url(url: str) -> str:
    """Ensure the URL is absolute HTTPS, prepending the CDN base if needed."""
    if url.startswith("//"):
        return "https:" + url
    if not url.startswith("http"):
        return AUDIO_CDN_BASE + url.lstrip("/")
    return url

"""Unit tests for quran_api.py (HTTP calls mocked with responses library)."""

import pytest
import responses as resp_lib

import quran_api

CHAPTER_1_PAYLOAD = {
    "chapter": {
        "id": 1,
        "verses_count": 7,
        "name_arabic": "الفاتحة",
        "translated_name": {"name": "The Opener"},
    }
}

VERSE_1_1_PAYLOAD = {
    "verses": [
        {
            "id": 1,
            "verse_number": 1,
            "text_uthmani": "بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
            "translations": [
                {"id": 131, "text": "In the name of Allah, the Entirely Merciful, the Especially Merciful."}
            ],
        }
    ]
}


@pytest.fixture(autouse=True)
def mock_http():
    with resp_lib.RequestsMock() as rsps:
        yield rsps


class TestGetChapter:
    def test_returns_chapter_dict(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/chapters/1",
            json=CHAPTER_1_PAYLOAD,
            status=200,
        )
        chapter = quran_api.get_chapter(1)
        assert chapter["id"] == 1
        assert chapter["verses_count"] == 7
        assert chapter["name_arabic"] == "الفاتحة"

    def test_raises_on_http_error(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/chapters/999",
            status=404,
        )
        with pytest.raises(Exception):
            quran_api.get_chapter(999)


class TestGetVerse:
    def test_returns_verse_dict(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/verses/by_chapter/1",
            json=VERSE_1_1_PAYLOAD,
            status=200,
        )
        verse = quran_api.get_verse(1, 1)
        assert verse["text_uthmani"].startswith("بِسْمِ")

    def test_raises_when_no_verses(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/verses/by_chapter/1",
            json={"verses": []},
            status=200,
        )
        with pytest.raises(ValueError, match="No verse found"):
            quran_api.get_verse(1, 999)


class TestExtractArabic:
    def test_returns_uthmani_text(self):
        verse = {"text_uthmani": "بِسْمِ ٱللَّهِ"}
        assert quran_api.extract_arabic(verse) == "بِسْمِ ٱللَّهِ"

    def test_empty_when_missing(self):
        assert quran_api.extract_arabic({}) == ""


class TestExtractEnglish:
    def test_returns_translation_text(self):
        verse = {"translations": [{"text": "In the name of Allah"}]}
        assert quran_api.extract_english(verse) == "In the name of Allah"

    def test_strips_html_tags(self):
        verse = {"translations": [{"text": "<sup>1</sup> In the name"}]}
        result = quran_api.extract_english(verse)
        assert "<" not in result
        assert "In the name" in result

    def test_empty_when_no_translations(self):
        assert quran_api.extract_english({"translations": []}) == ""


class TestChapterBoundary:
    def test_last_chapter_number_is_114(self, mock_http):
        """Sanity check: verify the API is called with chapter 114."""
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/chapters/114",
            json={
                "chapter": {
                    "id": 114,
                    "verses_count": 6,
                    "name_arabic": "الناس",
                    "translated_name": {"name": "Mankind"},
                }
            },
            status=200,
        )
        chapter = quran_api.get_chapter(114)
        assert chapter["id"] == 114

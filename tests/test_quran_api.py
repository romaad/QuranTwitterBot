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


AUDIO_PAYLOAD_CH1_V1 = {
    "audio_files": [
        {"verse_key": "1:1", "url": "audio/recitations/7/001001.mp3"}
    ]
}

AUDIO_PAYLOAD_CH1_V2 = {
    "audio_files": [
        {"verse_key": "1:2", "url": "//audio.qurancdn.com/007002.mp3"}
    ]
}


class TestGetVerseAudioUrl:
    def test_returns_absolute_url_for_relative_path(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/recitations/7/by_chapter/1",
            json=AUDIO_PAYLOAD_CH1_V1,
            status=200,
        )
        url = quran_api.get_verse_audio_url(1, 1, recitation_id=7)
        assert url.startswith("https://")
        assert "001001.mp3" in url

    def test_returns_absolute_url_for_protocol_relative(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/recitations/7/by_chapter/1",
            json=AUDIO_PAYLOAD_CH1_V2,
            status=200,
        )
        url = quran_api.get_verse_audio_url(1, 2, recitation_id=7)
        assert url.startswith("https://audio.qurancdn.com/")

    def test_raises_when_no_audio_files(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/recitations/7/by_chapter/1",
            json={"audio_files": []},
            status=200,
        )
        with pytest.raises(ValueError, match="No audio found"):
            quran_api.get_verse_audio_url(1, 1, recitation_id=7)


class TestGetVersesAudioUrls:
    def test_returns_list_of_urls(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/recitations/7/by_chapter/1",
            json=AUDIO_PAYLOAD_CH1_V1,
            status=200,
        )
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/recitations/7/by_chapter/1",
            json=AUDIO_PAYLOAD_CH1_V2,
            status=200,
        )
        urls = quran_api.get_verses_audio_urls([(1, 1), (1, 2)], recitation_id=7)
        assert len(urls) == 2
        assert all(u.startswith("https://") for u in urls)


class TestNormaliseAudioUrl:
    def test_keeps_absolute_https(self):
        url = "https://cdn.example.com/audio.mp3"
        assert quran_api._normalise_audio_url(url) == url

    def test_prefixes_protocol_relative(self):
        url = "//cdn.example.com/audio.mp3"
        assert quran_api._normalise_audio_url(url) == "https://cdn.example.com/audio.mp3"

    def test_prepends_cdn_base_for_relative_path(self):
        url = "audio/recitations/7/001001.mp3"
        result = quran_api._normalise_audio_url(url)
        assert result == quran_api.AUDIO_CDN_BASE + url


# ------------------------------------------------------------------ #
# Verse dataclass                                                      #
# ------------------------------------------------------------------ #

class TestVerseDataclass:
    def test_verse_fields(self):
        v = quran_api.Verse(
            verse_key="1:1",
            chapter_number=1,
            verse_number=1,
            arabic="بِسْمِ ٱللَّهِ",
            english="In the name of Allah",
            audio_url="https://cdn.example.com/1.mp3",
            audio_segments=[[0, 0, 500]],
        )
        assert v.verse_key == "1:1"
        assert v.chapter_number == 1
        assert v.verse_number == 1
        assert v.arabic == "بِسْمِ ٱللَّهِ"
        assert v.english == "In the name of Allah"
        assert v.audio_url == "https://cdn.example.com/1.mp3"
        assert v.audio_segments == [[0, 0, 500]]

    def test_verse_audio_segments_default_empty(self):
        v = quran_api.Verse(
            verse_key="2:1",
            chapter_number=2,
            verse_number=1,
            arabic="الم",
            english="Alif Lam Meem",
            audio_url="https://cdn.example.com/2.mp3",
        )
        assert v.audio_segments == []


# ------------------------------------------------------------------ #
# get_verses_by_ruku                                                   #
# ------------------------------------------------------------------ #

RUKU_VERSES_PAYLOAD = {
    "verses": [
        {
            "id": 1,
            "verse_key": "1:1",
            "verse_number": 1,
            "chapter_number": 1,
            "text_uthmani": "بِسْمِ ٱللَّهِ",
            "translations": [{"id": 131, "text": "In the name of Allah"}],
        },
        {
            "id": 2,
            "verse_key": "1:2",
            "verse_number": 2,
            "chapter_number": 1,
            "text_uthmani": "ٱلْحَمْدُ لِلَّهِ",
            "translations": [{"id": 131, "text": "All praise is for Allah"}],
        },
    ]
}

# Separate audio payloads — one per verse (the API is called once per verse)
RUKU_AUDIO_V1_PAYLOAD = {
    "audio_files": [
        {
            "verse_key": "1:1",
            "url": "audio/recitations/7/001001.mp3",
            "segments": [[0, 0, 500], [1, 500, 1200]],
        }
    ]
}

RUKU_AUDIO_V2_PAYLOAD = {
    "audio_files": [
        {
            "verse_key": "1:2",
            "url": "audio/recitations/7/001002.mp3",
            "segments": [],
        }
    ]
}


class TestGetVersesByRuku:
    def _add_ruku_mocks(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/verses/by_ruku/1",
            json=RUKU_VERSES_PAYLOAD,
            status=200,
        )
        # First audio call → verse 1 (with segments)
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/recitations/7/by_chapter/1",
            json=RUKU_AUDIO_V1_PAYLOAD,
            status=200,
        )
        # Second audio call → verse 2 (no segments)
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/recitations/7/by_chapter/1",
            json=RUKU_AUDIO_V2_PAYLOAD,
            status=200,
        )

    def test_returns_list_of_verses(self, mock_http):
        self._add_ruku_mocks(mock_http)
        verses = quran_api.get_verses_by_ruku(1, translation_id=131, recitation_id=7)
        assert len(verses) == 2
        assert all(isinstance(v, quran_api.Verse) for v in verses)

    def test_verse_arabic_and_english_fields(self, mock_http):
        self._add_ruku_mocks(mock_http)
        verses = quran_api.get_verses_by_ruku(1, translation_id=131, recitation_id=7)
        assert verses[0].arabic == "بِسْمِ ٱللَّهِ"
        assert "In the name" in verses[0].english
        assert verses[1].arabic == "ٱلْحَمْدُ لِلَّهِ"

    def test_audio_url_is_absolute(self, mock_http):
        self._add_ruku_mocks(mock_http)
        verses = quran_api.get_verses_by_ruku(1, translation_id=131, recitation_id=7)
        assert verses[0].audio_url.startswith("https://")

    def test_segments_populated_from_audio_payload(self, mock_http):
        self._add_ruku_mocks(mock_http)
        verses = quran_api.get_verses_by_ruku(1, translation_id=131, recitation_id=7)
        assert verses[0].audio_segments == [[0, 0, 500], [1, 500, 1200]]
        assert verses[1].audio_segments == []

    def test_raises_when_ruku_empty(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/verses/by_ruku/999",
            json={"verses": []},
            status=200,
        )
        with pytest.raises(ValueError, match="No verses found"):
            quran_api.get_verses_by_ruku(999, recitation_id=7)

    def test_raises_on_http_error(self, mock_http):
        mock_http.add(
            resp_lib.GET,
            f"{quran_api.BASE_URL}/verses/by_ruku/1",
            status=500,
        )
        with pytest.raises(Exception):
            quran_api.get_verses_by_ruku(1, recitation_id=7)

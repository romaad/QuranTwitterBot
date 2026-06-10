"""Unit tests for pexels.py (PexelsClient)."""
from unittest.mock import MagicMock, patch

import pytest

from pexels import PexelsClient


def _pexels_response(video_id=1, width=1080, height=1920, link="https://pexels.com/v.mp4"):
    return {
        "videos": [
            {
                "id": video_id,
                "video_files": [
                    {
                        "id": 1,
                        "file_type": "video/mp4",
                        "width": width,
                        "height": height,
                        "link": link,
                    }
                ],
            }
        ]
    }


class _MockSearchResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _MockDownloadResponse:
    def __init__(self, content=b"VIDEODATA"):
        self._content = content

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=None):
        return [self._content]


class TestPexelsClientFetchVideo:
    def test_downloads_video_to_output_path(self, tmp_path):
        output = str(tmp_path / "nature.mp4")
        pexels_data = _pexels_response()
        client = PexelsClient(api_key="test_key")

        with patch("pexels.requests.get") as mock_get:
            mock_get.side_effect = [
                _MockSearchResponse(pexels_data),
                _MockDownloadResponse(b"FAKEMP4"),
            ]
            result = client.fetch_video("nature", output)

        assert result == output
        with open(output, "rb") as fh:
            assert fh.read() == b"FAKEMP4"

    def test_raises_on_empty_results(self, tmp_path):
        output = str(tmp_path / "nature.mp4")
        client = PexelsClient(api_key="test_key")

        with patch("pexels.requests.get") as mock_get:
            mock_get.return_value = _MockSearchResponse({"videos": []})
            with pytest.raises(ValueError, match="No Pexels videos found"):
                client.fetch_video("nature", output)

    def test_raises_when_no_mp4_file(self, tmp_path):
        output = str(tmp_path / "nature.mp4")
        data = {
            "videos": [{"id": 1, "video_files": [{"file_type": "video/webm", "link": "x"}]}]
        }
        client = PexelsClient(api_key="key")

        with patch("pexels.requests.get") as mock_get:
            mock_get.return_value = _MockSearchResponse(data)
            with pytest.raises(ValueError, match="No MP4 file found"):
                client.fetch_video("nature", output)

    def test_picks_highest_resolution_file(self, tmp_path):
        output = str(tmp_path / "nature.mp4")
        hd_link = "https://pexels.com/hd.mp4"
        sd_link = "https://pexels.com/sd.mp4"
        data = {
            "videos": [
                {
                    "id": 1,
                    "video_files": [
                        {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": hd_link},
                        {"file_type": "video/mp4", "width": 540, "height": 960, "link": sd_link},
                    ],
                }
            ]
        }
        downloaded_urls: list[str] = []

        def fake_get(url, **kwargs):
            if "pexels.com/videos/search" in url:
                return _MockSearchResponse(data)
            downloaded_urls.append(url)
            return _MockDownloadResponse()

        client = PexelsClient(api_key="key")
        with patch("pexels.requests.get", side_effect=fake_get):
            client.fetch_video("nature", output)

        assert downloaded_urls == [hd_link]

    def test_sends_api_key_header(self, tmp_path):
        output = str(tmp_path / "nature.mp4")
        pexels_data = _pexels_response()
        captured: list[dict] = []

        def fake_get(url, headers=None, **kwargs):
            if "pexels.com/videos/search" in url:
                captured.append(headers or {})
                return _MockSearchResponse(pexels_data)
            return _MockDownloadResponse()

        client = PexelsClient(api_key="MY_API_KEY")
        with patch("pexels.requests.get", side_effect=fake_get):
            client.fetch_video("nature", output)

        assert captured[0].get("Authorization") == "MY_API_KEY"

    def test_sends_humans_zero_param(self, tmp_path):
        """The search request must include humans=0 to exclude human subjects."""
        output = str(tmp_path / "nature.mp4")
        pexels_data = _pexels_response()
        captured_params: list[dict] = []

        def fake_get(url, params=None, **kwargs):
            if "pexels.com/videos/search" in url:
                captured_params.append(params or {})
                return _MockSearchResponse(pexels_data)
            return _MockDownloadResponse()

        client = PexelsClient(api_key="key")
        with patch("pexels.requests.get", side_effect=fake_get):
            client.fetch_video("nature", output)

        assert captured_params[0].get("humans") == 0

"""Unit tests for video_maker.py (ffmpeg and network calls mocked)."""
import subprocess
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

import video_maker


class TestDownloadAudio:
    def test_writes_response_content_to_file(self, tmp_path):
        dest = str(tmp_path / "verse.mp3")
        mock_response = MagicMock()
        mock_response.content = b"MP3DATA"

        with patch("video_maker.requests.get", return_value=mock_response) as mock_get:
            video_maker.download_audio("https://example.com/audio.mp3", dest)

        mock_get.assert_called_once_with("https://example.com/audio.mp3", timeout=30)
        mock_response.raise_for_status.assert_called_once()
        with open(dest, "rb") as fh:
            assert fh.read() == b"MP3DATA"

    def test_raises_on_http_error(self, tmp_path):
        dest = str(tmp_path / "verse.mp3")
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")

        with patch("video_maker.requests.get", return_value=mock_response):
            with pytest.raises(Exception, match="404 Not Found"):
                video_maker.download_audio("https://bad.url/audio.mp3", dest)


class TestBuildVideo:
    def test_raises_on_empty_audio_urls(self):
        with pytest.raises(ValueError, match="audio_urls must not be empty"):
            video_maker.build_video([], "nature.mp4", "/tmp/out.mp4")

    def test_calls_ffmpeg_twice(self, tmp_path):
        audio_urls = [
            "https://cdn.example.com/verse_001.mp3",
            "https://cdn.example.com/verse_002.mp3",
        ]
        nature_video = str(tmp_path / "nature.mp4")
        nature_video_obj = open(nature_video, "wb")
        nature_video_obj.close()
        output = str(tmp_path / "out.mp4")

        mock_response = MagicMock()
        mock_response.content = b"MP3"

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg") as mock_ffmpeg,
        ):
            video_maker.build_video(audio_urls, nature_video, output)

        # Expect two ffmpeg calls: concat + overlay
        assert mock_ffmpeg.call_count == 2
        concat_args = mock_ffmpeg.call_args_list[0][0][0]
        overlay_args = mock_ffmpeg.call_args_list[1][0][0]
        assert "-f" in concat_args and "concat" in concat_args
        assert "-stream_loop" in overlay_args
        assert output in overlay_args

    def test_cleans_up_temp_dir_on_success(self, tmp_path):
        """Temporary working directory must be removed after a successful build."""
        created_dirs: list[str] = []
        original_mkdtemp = __import__("tempfile").mkdtemp

        def track_mkdtemp(**kwargs):
            d = original_mkdtemp(**kwargs)
            created_dirs.append(d)
            return d

        mock_response = MagicMock()
        mock_response.content = b"MP3"

        with (
            patch("video_maker.tempfile.mkdtemp", side_effect=track_mkdtemp),
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg"),
        ):
            video_maker.build_video(
                ["https://cdn.example.com/v1.mp3"],
                "nature.mp4",
                str(tmp_path / "out.mp4"),
            )

        import os
        for d in created_dirs:
            assert not os.path.exists(d), f"Temp dir not cleaned up: {d}"

    def test_cleans_up_temp_dir_on_failure(self, tmp_path):
        """Temporary working directory must be removed even when ffmpeg fails."""
        created_dirs: list[str] = []
        original_mkdtemp = __import__("tempfile").mkdtemp

        def track_mkdtemp(**kwargs):
            d = original_mkdtemp(**kwargs)
            created_dirs.append(d)
            return d

        mock_response = MagicMock()
        mock_response.content = b"MP3"

        with (
            patch("video_maker.tempfile.mkdtemp", side_effect=track_mkdtemp),
            patch("video_maker.requests.get", return_value=mock_response),
            patch(
                "video_maker._run_ffmpeg",
                side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
            ),
            pytest.raises(subprocess.CalledProcessError),
        ):
            video_maker.build_video(
                ["https://cdn.example.com/v1.mp3"],
                "nature.mp4",
                str(tmp_path / "out.mp4"),
            )

        import os
        for d in created_dirs:
            assert not os.path.exists(d), f"Temp dir not cleaned up: {d}"

    def test_returns_output_path(self, tmp_path):
        mock_response = MagicMock()
        mock_response.content = b"MP3"
        output = str(tmp_path / "final.mp4")

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg"),
        ):
            result = video_maker.build_video(
                ["https://cdn.example.com/v1.mp3"], "nature.mp4", output
            )

        assert result == output


class TestRunFfmpeg:
    def test_raises_on_nonzero_exit(self):
        with patch("video_maker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=b"", stderr=b"err")
            with pytest.raises(subprocess.CalledProcessError):
                video_maker._run_ffmpeg(["-i", "input.mp3", "output.mp3"])

    def test_passes_on_zero_exit(self):
        with patch("video_maker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            video_maker._run_ffmpeg(["-i", "input.mp3", "output.mp3"])
        # No exception raised — test passes

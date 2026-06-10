"""Unit tests for video_maker.py (ffmpeg and network calls mocked)."""
import subprocess
from unittest.mock import MagicMock, patch

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
        open(nature_video, "wb").close()
        output = str(tmp_path / "out.mp4")

        mock_response = MagicMock()
        mock_response.content = b"MP3"

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg") as mock_ffmpeg,
        ):
            video_maker.build_video(audio_urls, nature_video, output)

        # Two ffmpeg calls: concat + overlay (single clip → no xfade step)
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

    def test_applies_vf_filter_when_dimensions_set(self, tmp_path):
        """When width/height are given, overlay ffmpeg call must contain -vf and libx264."""
        mock_response = MagicMock()
        mock_response.content = b"MP3"
        output = str(tmp_path / "out.mp4")

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg") as mock_ffmpeg,
        ):
            video_maker.build_video(
                ["https://cdn.example.com/v1.mp3"],
                "nature.mp4",
                output,
                width=1080,
                height=1920,
            )

        overlay_args = mock_ffmpeg.call_args_list[1][0][0]
        assert "-vf" in overlay_args
        vf_value = overlay_args[overlay_args.index("-vf") + 1]
        assert "1080" in vf_value and "1920" in vf_value
        assert "libx264" in overlay_args

    def test_vf_filter_includes_darkening_by_default(self, tmp_path):
        """Default darken=0.15 must always add an eq brightness filter."""
        mock_response = MagicMock()
        mock_response.content = b"MP3"
        output = str(tmp_path / "out.mp4")

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg") as mock_ffmpeg,
        ):
            video_maker.build_video(
                ["https://cdn.example.com/v1.mp3"], "nature.mp4", output
            )

        overlay_args = mock_ffmpeg.call_args_list[1][0][0]
        assert "-vf" in overlay_args
        vf_value = overlay_args[overlay_args.index("-vf") + 1]
        assert "eq=brightness" in vf_value

    def test_no_vf_filter_when_darken_zero_and_no_resize(self, tmp_path):
        """With darken=0 and no resize, -c:v copy is used and -vf is absent."""
        mock_response = MagicMock()
        mock_response.content = b"MP3"
        output = str(tmp_path / "out.mp4")

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg") as mock_ffmpeg,
        ):
            video_maker.build_video(
                ["https://cdn.example.com/v1.mp3"], "nature.mp4", output, darken=0.0
            )

        overlay_args = mock_ffmpeg.call_args_list[1][0][0]
        assert "-vf" not in overlay_args
        assert "copy" in overlay_args

    def test_subtitle_filter_included_when_verse_texts_given(self, tmp_path):
        """When verse_texts is provided, the overlay -vf must include a subtitles filter."""
        mock_response = MagicMock()
        mock_response.content = b"MP3"
        output = str(tmp_path / "out.mp4")

        # Provide fake segments: verse has one word from 0..1000 ms
        verse_texts = [("Arabic text", "English text")]
        verse_segments = [[[0, 0, 1000]]]

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg") as mock_ffmpeg,
            patch("video_maker._get_audio_duration", return_value=1.0),
        ):
            video_maker.build_video(
                ["https://cdn.example.com/v1.mp3"],
                "nature.mp4",
                output,
                verse_texts=verse_texts,
                verse_segments=verse_segments,
            )

        overlay_args = mock_ffmpeg.call_args_list[1][0][0]
        assert "-vf" in overlay_args
        vf_value = overlay_args[overlay_args.index("-vf") + 1]
        assert "subtitles" in vf_value


class TestComputeVerseTimings:
    def test_uses_segments_when_provided(self, tmp_path):
        audio_files = [str(tmp_path / "v1.mp3")]
        open(audio_files[0], "wb").close()
        verse_texts = [("Arabic", "English")]
        verse_segments = [[[0, 0, 500], [1, 500, 1200]]]

        with patch("video_maker._get_audio_duration", return_value=1.2):
            timings = video_maker.compute_verse_timings(
                audio_files, verse_texts, verse_segments
            )

        assert len(timings) == 1
        t = timings[0]
        assert t.arabic == "Arabic"
        assert t.english == "English"
        assert t.start_ms == 0
        assert t.end_ms == 1200  # max of last segment end

    def test_ffprobe_fallback_when_no_segments(self, tmp_path):
        audio_files = [str(tmp_path / "v1.mp3")]
        open(audio_files[0], "wb").close()
        verse_texts = [("Ar", "En")]
        verse_segments = [[]]  # empty → use ffprobe

        with patch("video_maker._get_audio_duration", return_value=3.5):
            timings = video_maker.compute_verse_timings(
                audio_files, verse_texts, verse_segments
            )

        assert timings[0].end_ms == 3500  # 3.5s * 1000

    def test_cumulative_start_offsets(self, tmp_path):
        a1 = str(tmp_path / "v1.mp3")
        a2 = str(tmp_path / "v2.mp3")
        for p in (a1, a2):
            open(p, "wb").close()
        verse_texts = [("Ar1", "En1"), ("Ar2", "En2")]
        # Verse 1: 2s; Verse 2: 3s
        verse_segments = [[[0, 0, 2000]], [[0, 0, 3000]]]

        with patch("video_maker._get_audio_duration", side_effect=[2.0, 3.0]):
            timings = video_maker.compute_verse_timings(
                [a1, a2], verse_texts, verse_segments
            )

        assert timings[0].start_ms == 0
        assert timings[0].end_ms == 2000
        assert timings[1].start_ms == 2000  # offset by duration of first verse
        assert timings[1].end_ms == 5000   # 2000 + 3000


class TestBuildSubtitleFile:
    def test_creates_srt_file(self, tmp_path):
        from video_maker import VerseTiming, _build_subtitle_file

        timings = [
            VerseTiming(arabic="بسم الله", english="In the name", start_ms=0, end_ms=2000),
            VerseTiming(arabic="الحمد", english="All praise", start_ms=2000, end_ms=5000),
        ]
        srt_path = str(tmp_path / "subs.srt")
        _build_subtitle_file(timings, srt_path)

        with open(srt_path, encoding="utf-8") as fh:
            content = fh.read()

        assert "بسم الله" in content
        assert "In the name" in content
        assert "الحمد" in content
        assert "00:00:00,000 --> 00:00:02,000" in content

    def test_srt_sequence_numbers(self, tmp_path):
        from video_maker import VerseTiming, _build_subtitle_file

        timings = [
            VerseTiming(arabic="A", english="a", start_ms=0, end_ms=1000),
            VerseTiming(arabic="B", english="b", start_ms=1000, end_ms=2000),
        ]
        srt_path = str(tmp_path / "subs.srt")
        _build_subtitle_file(timings, srt_path)

        with open(srt_path) as fh:
            content = fh.read()
        # SRT sequence numbers appear as standalone lines
        lines = content.splitlines()
        assert "1" in lines
        assert "2" in lines


class TestBuildVideoMultiClip:
    """Tests for multi-clip xfade background behaviour."""

    def test_three_ffmpeg_calls_for_two_clips(self, tmp_path):
        """Two background clips → concat audio, build xfade bg, overlay (3 calls)."""
        clip1 = str(tmp_path / "clip1.mp4")
        clip2 = str(tmp_path / "clip2.mp4")
        for p in (clip1, clip2):
            open(p, "wb").close()
        output = str(tmp_path / "out.mp4")

        mock_response = MagicMock()
        mock_response.content = b"MP3"

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg") as mock_ffmpeg,
            patch("video_maker._get_audio_duration", return_value=60.0),
        ):
            video_maker.build_video(["https://cdn.example.com/v1.mp3"], [clip1, clip2], output)

        assert mock_ffmpeg.call_count == 3
        xfade_args = mock_ffmpeg.call_args_list[1][0][0]
        assert "filter_complex" in " ".join(xfade_args)
        assert "xfade" in " ".join(xfade_args)

    def test_xfade_background_uses_both_clip_paths(self, tmp_path):
        """Each clip path must appear in the xfade ffmpeg call inputs."""
        clip1 = str(tmp_path / "a.mp4")
        clip2 = str(tmp_path / "b.mp4")
        for p in (clip1, clip2):
            open(p, "wb").close()
        output = str(tmp_path / "out.mp4")

        mock_response = MagicMock()
        mock_response.content = b"MP3"

        with (
            patch("video_maker.requests.get", return_value=mock_response),
            patch("video_maker._run_ffmpeg") as mock_ffmpeg,
            patch("video_maker._get_audio_duration", return_value=30.0),
        ):
            video_maker.build_video(["https://cdn.example.com/v1.mp3"], [clip1, clip2], output)

        xfade_args = mock_ffmpeg.call_args_list[1][0][0]
        assert clip1 in xfade_args
        assert clip2 in xfade_args


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

"""
Video production module.

Downloads verse audio files, concatenates them with ffmpeg, then overlays
the combined audio on a looped nature video to produce a single MP4 that
can be uploaded to X (Twitter).

Requirements: ffmpeg must be available on PATH.
"""
import logging
import os
import shutil
import subprocess
import tempfile

import requests

log = logging.getLogger(__name__)


def download_audio(url: str, dest_path: str) -> None:
    """Download an audio file from *url* and write it to *dest_path*."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    with open(dest_path, "wb") as fh:
        fh.write(response.content)


def build_video(
    audio_urls: list[str],
    nature_video_path: str,
    output_path: str,
) -> str:
    """
    Produce a video by combining verse audio with a looped nature clip.

    Steps:
    1. Download each MP3 listed in *audio_urls* to a temporary directory.
    2. Concatenate them into a single MP3 using ffmpeg's concat demuxer.
    3. Loop *nature_video_path* to match the audio length (``-shortest`` flag).
    4. Write the final MP4 to *output_path*.

    Returns *output_path* on success.
    Raises ``ValueError`` if *audio_urls* is empty.
    Raises ``subprocess.CalledProcessError`` if ffmpeg fails.
    """
    if not audio_urls:
        raise ValueError("audio_urls must not be empty")

    work_dir = tempfile.mkdtemp(prefix="quran_video_")
    try:
        # ── 1. Download audio files ──────────────────────────────────── #
        audio_files: list[str] = []
        for i, url in enumerate(audio_urls):
            dest = os.path.join(work_dir, f"verse_{i:03d}.mp3")
            log.debug("Downloading audio %d/%d: %s", i + 1, len(audio_urls), url)
            download_audio(url, dest)
            audio_files.append(dest)

        # ── 2. Concatenate audio ─────────────────────────────────────── #
        concat_list = os.path.join(work_dir, "concat.txt")
        with open(concat_list, "w") as fh:
            for path in audio_files:
                fh.write(f"file '{path}'\n")

        combined_audio = os.path.join(work_dir, "combined.mp3")
        _run_ffmpeg(
            [
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                combined_audio,
            ]
        )

        # ── 3 & 4. Overlay audio on looped nature video ──────────────── #
        _run_ffmpeg(
            [
                "-stream_loop", "-1", "-i", nature_video_path,
                "-i", combined_audio,
                "-shortest",
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac",
                output_path,
            ]
        )

        log.info("Video produced: %s", output_path)
        return output_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with the given argument list, raising on non-zero exit."""
    cmd = ["ffmpeg", "-y"] + args
    log.debug("ffmpeg command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )

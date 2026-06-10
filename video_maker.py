"""
Video production module.

Downloads verse audio files, concatenates them with ffmpeg, then overlays
the combined audio on a looped nature video to produce a single MP4 that
can be uploaded to X (Twitter).

Nature videos can be fetched automatically from the Pexels API
(https://www.pexels.com/api/) by calling ``fetch_nature_video``.
Set the ``PEXELS_API_KEY`` environment variable and pass ``orientation="portrait"``
to get a mobile-ready 9:16 clip without needing a local file.

Requirements: ffmpeg must be available on PATH.
"""
import logging
import os
import random
import shutil
import subprocess
import tempfile

import requests

log = logging.getLogger(__name__)

PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"


def fetch_nature_video(
    query: str,
    api_key: str,
    output_path: str,
    orientation: str = "portrait",
    per_page: int = 15,
) -> str:
    """
    Search Pexels for a *query* video and download it to *output_path*.

    Parameters
    ----------
    query:
        Search term, e.g. ``"nature"`` or ``"forest"``
    api_key:
        Pexels API key (obtain a free key at https://www.pexels.com/api/).
    output_path:
        Destination file path for the downloaded MP4.
    orientation:
        ``"portrait"`` (default, 9:16 mobile), ``"landscape"``, or ``"square"``.
    per_page:
        Number of results to retrieve; a random one is selected.

    Returns *output_path* on success.
    Raises ``ValueError`` if no results are found or no suitable video file exists.
    Raises ``requests.HTTPError`` if the API or download request fails.
    """
    headers = {"Authorization": api_key}
    params = {"query": query, "orientation": orientation, "per_page": per_page}
    response = requests.get(PEXELS_VIDEO_SEARCH_URL, headers=headers, params=params, timeout=30)
    response.raise_for_status()

    videos = response.json().get("videos", [])
    if not videos:
        raise ValueError(f"No Pexels videos found for query '{query}'")

    video = random.choice(videos)

    # Pick the highest-resolution MP4 link available
    video_files = [
        vf for vf in video.get("video_files", [])
        if vf.get("file_type") == "video/mp4" and vf.get("link")
    ]
    if not video_files:
        raise ValueError(f"No MP4 file found for Pexels video id={video.get('id')}")

    best = max(video_files, key=lambda vf: (vf.get("width", 0) * vf.get("height", 0)))
    link = best["link"]

    log.debug("Downloading Pexels video %s → %s", link, output_path)
    dl = requests.get(link, timeout=120, stream=True)
    dl.raise_for_status()
    with open(output_path, "wb") as fh:
        for chunk in dl.iter_content(chunk_size=1 << 20):
            fh.write(chunk)

    log.info("Pexels nature video saved to %s", output_path)
    return output_path


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
    width: int = 0,
    height: int = 0,
) -> str:
    """
    Produce a video by combining verse audio with a looped nature clip.

    Steps:
    1. Download each MP3 listed in *audio_urls* to a temporary directory.
    2. Concatenate them into a single MP3 using ffmpeg's concat demuxer.
    3. Loop *nature_video_path* to match the audio length (``-shortest`` flag).
    4. Optionally scale/crop to *width* × *height* (e.g. 1080 × 1920 for
       mobile portrait 9:16).  When both values are > 0 the video is scaled
       up (preserving aspect ratio) and then centre-cropped to the exact
       target dimensions using ``libx264`` encoding.
    5. Write the final MP4 to *output_path*.

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
        apply_resize = width > 0 and height > 0
        overlay_args = [
            "-stream_loop", "-1", "-i", nature_video_path,
            "-i", combined_audio,
            "-shortest",
            "-map", "0:v:0", "-map", "1:a:0",
        ]
        if apply_resize:
            # Scale up (maintaining AR) then centre-crop to exact dimensions
            vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            )
            overlay_args += ["-vf", vf, "-c:v", "libx264", "-c:a", "aac"]
        else:
            overlay_args += ["-c:v", "copy", "-c:a", "aac"]
        overlay_args.append(output_path)
        _run_ffmpeg(overlay_args)

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

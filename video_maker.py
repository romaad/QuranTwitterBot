"""
Video production module.

Downloads verse audio files, concatenates them with ffmpeg, then overlays
the combined audio on a nature background to produce a single MP4 that
can be uploaded to X (Twitter).

When multiple background clips are provided they are joined with an
xfade (cross-fade) transition so the final background is a smooth montage
that fills the audio duration.  A configurable darkening filter is also
applied so overlaid text remains readable.

Nature videos can be fetched automatically from the Pexels API
(https://www.pexels.com/api/) by calling ``fetch_nature_video``.
Set the ``PEXELS_API_KEY`` environment variable and pass ``orientation="portrait"``
to get a mobile-ready 9:16 clip without needing a local file.

Requirements: ffmpeg and ffprobe must be available on PATH.
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
    Search Pexels for a *query* video (excluding human subjects) and
    download it to *output_path*.

    Parameters
    ----------
    query:
        Search term, e.g. ``"nature"`` or ``"wildlife"``
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
    params = {
        "query": query,
        "orientation": orientation,
        "per_page": per_page,
        "humans": 0,
    }
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


def _get_audio_duration(path: str) -> float:
    """Return the duration of a media file in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _build_xfade_background(
    paths: list[str],
    total_duration: float,
    work_dir: str,
) -> str:
    """
    Concatenate *paths* with cross-fade transitions to produce a single
    background clip of exactly *total_duration* seconds.

    Each source clip is looped if it is shorter than its share of the
    target duration.  The resulting file is written to *work_dir* and its
    path is returned.
    """
    n = len(paths)
    # Keep the fade short relative to per-clip time to avoid artefacts
    fade_dur = min(1.0, total_duration / max(n * 4, 1))
    # Per-clip duration: each clip must fill an equal share of the timeline;
    # the fades overlap so we add (n-1)*fade_dur back to the total.
    clip_dur = (total_duration + fade_dur * (n - 1)) / n

    # Inputs: loop each source clip long enough to guarantee sufficient frames
    cmd: list[str] = []
    for p in paths:
        cmd += ["-stream_loop", "-1", "-t", f"{clip_dur + 1:.3f}", "-i", p]

    # filter_complex: trim+reset PTS per clip, then chain xfade filters
    filters: list[str] = []
    for i in range(n):
        filters.append(f"[{i}:v]trim=0:{clip_dur:.3f},setpts=PTS-STARTPTS[cv{i}]")

    prev = "cv0"
    for i in range(1, n):
        offset = clip_dur * i - fade_dur * i
        out = f"xfv{i}"
        filters.append(
            f"[{prev}][cv{i}]xfade=transition=fade:duration={fade_dur:.3f}:"
            f"offset={offset:.3f}[{out}]"
        )
        prev = out

    bg_path = os.path.join(work_dir, "background.mp4")
    _run_ffmpeg([
        *cmd,
        "-filter_complex", ";".join(filters),
        "-map", f"[{prev}]",
        "-t", f"{total_duration:.3f}",
        "-c:v", "libx264", "-preset", "fast",
        bg_path,
    ])
    return bg_path


def build_video(
    audio_urls: list[str],
    nature_video_paths: "list[str] | str",
    output_path: str,
    width: int = 0,
    height: int = 0,
    darken: float = 0.15,
) -> str:
    """
    Produce a video by combining verse audio with one or more nature clips.

    Steps:
    1. Download each MP3 listed in *audio_urls* to a temporary directory.
    2. Concatenate them into a single MP3 using ffmpeg's concat demuxer.
    3. If *nature_video_paths* contains more than one clip, build a blended
       background using xfade transitions sized to match the audio duration.
       Otherwise the single clip is looped to cover the audio.
    4. Apply a darkening filter (*darken* controls brightness reduction) and
       optionally scale/crop to *width* × *height* (e.g. 1080 × 1920 for
       mobile portrait 9:16).
    5. Write the final MP4 to *output_path*.

    Parameters
    ----------
    nature_video_paths:
        One or more local video file paths used as the background.
        A plain string is treated as a single-element list.
    darken:
        Brightness reduction applied to the background (0.0 = none,
        positive values darken; default 0.15).

    Returns *output_path* on success.
    Raises ``ValueError`` if *audio_urls* is empty.
    Raises ``subprocess.CalledProcessError`` if ffmpeg fails.
    """
    if not audio_urls:
        raise ValueError("audio_urls must not be empty")

    if isinstance(nature_video_paths, str):
        nature_video_paths = [nature_video_paths]

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
        _run_ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            combined_audio,
        ])

        # ── 3. Build background video ─────────────────────────────────── #
        if len(nature_video_paths) > 1:
            audio_duration = _get_audio_duration(combined_audio)
            bg_path = _build_xfade_background(nature_video_paths, audio_duration, work_dir)
            bg_input_args = ["-i", bg_path]
            shortest_flag: list[str] = []
        else:
            bg_path = nature_video_paths[0]
            bg_input_args = ["-stream_loop", "-1", "-i", bg_path]
            shortest_flag = ["-shortest"]

        # ── 4 & 5. Overlay audio + apply filters ──────────────────────── #
        apply_resize = width > 0 and height > 0
        vf_parts: list[str] = []
        if apply_resize:
            vf_parts.append(
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            )
        if darken > 0:
            vf_parts.append(f"eq=brightness=-{darken:.2f}")

        overlay_args = [
            *bg_input_args,
            "-i", combined_audio,
            *shortest_flag,
            "-map", "0:v:0", "-map", "1:a:0",
        ]
        if vf_parts:
            overlay_args += ["-vf", ",".join(vf_parts), "-c:v", "libx264", "-c:a", "aac"]
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

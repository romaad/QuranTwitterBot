"""
Video production module.

Downloads verse audio files, concatenates them with ffmpeg, then overlays
the combined audio on a nature background to produce a single MP4 that
can be uploaded to X (Twitter).

When multiple background clips are provided they are joined with an
xfade (cross-fade) transition so the final background is a smooth montage
that fills the audio duration.  A configurable darkening filter is applied
so overlaid text remains readable.

Arabic verse text (and its English translation) is burned into the video as
SRT subtitles timed to each verse's audio duration, using timing data supplied
by the caller (derived from the Quran API's ``audio_segments`` field, or
computed via ffprobe as a fallback).

Requirements: ffmpeg and ffprobe must be available on PATH.
"""
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


@dataclass
class VerseTiming:
    """Start and end position of a single verse within the concatenated audio."""

    arabic: str
    english: str
    start_ms: int   # milliseconds from the start of the combined audio
    end_ms: int     # exclusive end time in milliseconds


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
    verse_texts: "list[tuple[str, str]] | None" = None,
    verse_segments: "list[list] | None" = None,
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
    5. If *verse_texts* is provided, compute per-verse timing (from
       *verse_segments* API data when available, otherwise via ffprobe) and
       burn SRT subtitles (Arabic + English) into the video.
    6. Write the final MP4 to *output_path*.

    Parameters
    ----------
    nature_video_paths:
        One or more local video file paths used as the background.
        A plain string is treated as a single-element list.
    darken:
        Brightness reduction applied to the background (0.0 = none,
        positive values darken; default 0.15).
    verse_texts:
        Optional parallel list of ``(arabic, english)`` tuples, one per URL
        in *audio_urls*.  When provided, each verse's text is burned into the
        video as an SRT subtitle at the correct timestamp.
    verse_segments:
        Optional API timing data, one entry per URL in *audio_urls*.  Each
        entry is a list of ``[word_idx, start_ms, end_ms]`` triples as
        returned by ``quran_api.Verse.audio_segments``.  Used to compute
        verse duration without extra ffprobe calls; ffprobe is used as a
        fallback for any verse whose segments list is empty.

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

        # ── 4. Build SRT subtitles (optional) ────────────────────────── #
        srt_path: str | None = None
        if verse_texts:
            timings = compute_verse_timings(audio_files, verse_texts, verse_segments)
            srt_path = os.path.join(work_dir, "subs.srt")
            _build_subtitle_file(timings, srt_path)

        # ── 5. Overlay audio + apply filters ──────────────────────────── #
        apply_resize = width > 0 and height > 0
        vf_parts: list[str] = []
        if apply_resize:
            vf_parts.append(
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            )
        if darken > 0:
            vf_parts.append(f"eq=brightness=-{darken:.2f}")
        if srt_path:
            # Escape backslashes and colons for the ffmpeg subtitles filter
            escaped = srt_path.replace("\\", "\\\\").replace(":", "\\:")
            vf_parts.append(f"subtitles={escaped}")

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


def _build_subtitle_file(timings: "list[VerseTiming]", srt_path: str) -> None:
    """Write an SRT subtitle file from *timings* to *srt_path*.

    Each entry shows the Arabic verse text on the first line and the English
    translation on the second line.
    """
    with open(srt_path, "w", encoding="utf-8") as fh:
        for idx, vt in enumerate(timings, 1):
            start = _ms_to_srt_time(vt.start_ms)
            end = _ms_to_srt_time(vt.end_ms)
            fh.write(f"{idx}\n{start} --> {end}\n{vt.arabic}\n{vt.english}\n\n")


def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT timestamp ``HH:MM:SS,mmm``."""
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1_000
    ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def compute_verse_timings(
    audio_files: list[str],
    verse_texts: list[tuple[str, str]],
    verse_segments: list[list] | None = None,
) -> list[VerseTiming]:
    """Compute per-verse start/end times for the concatenated audio.

    Parameters
    ----------
    audio_files:
        Ordered list of downloaded verse MP3 paths.
    verse_texts:
        Parallel list of ``(arabic_text, english_text)`` tuples.
    verse_segments:
        Optional API timing data per verse: each entry is a list of
        ``[word_idx, start_ms, end_ms]`` triples (as returned by
        ``quran_api.Verse.audio_segments``).  When non-empty for a verse, the
        last segment's ``end_ms`` is used as the verse duration; otherwise
        ffprobe is used as a fallback.

    Returns a :class:`VerseTiming` list aligned with *audio_files*.
    """
    timings: list[VerseTiming] = []
    offset_ms = 0
    for i, (audio_path, (arabic, english)) in enumerate(
        zip(audio_files, verse_texts)
    ):
        segs = (verse_segments[i] if verse_segments and i < len(verse_segments) else [])
        if segs:
            duration_ms = max(seg[2] for seg in segs)
        else:
            duration_ms = int(_get_audio_duration(audio_path) * 1000)
        timings.append(
            VerseTiming(
                arabic=arabic,
                english=english,
                start_ms=offset_ms,
                end_ms=offset_ms + duration_ms,
            )
        )
        offset_ms += duration_ms
    return timings


def _run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with the given argument list, raising on non-zero exit."""
    cmd = ["ffmpeg", "-y"] + args
    log.debug("ffmpeg command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )

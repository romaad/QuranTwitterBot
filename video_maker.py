import textwrap
import math
import importlib.util

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
import time
from dataclasses import dataclass
from typing import Any, cast

import requests
from config import config
from pexels import PexelsClient
from quran_api import get_verses_by_ruku

_SECRETS_SPEC = importlib.util.spec_from_file_location(
    "quranbot_secrets",
    os.path.join(os.path.dirname(__file__), "secrets.py"),
)
if _SECRETS_SPEC is None or _SECRETS_SPEC.loader is None:
    raise ImportError("Unable to load local secrets.py")
_SECRETS_MODULE = importlib.util.module_from_spec(_SECRETS_SPEC)
_SECRETS_SPEC.loader.exec_module(_SECRETS_MODULE)
Secrets = cast(Any, _SECRETS_MODULE).Secrets

log = logging.getLogger(__name__)


@dataclass
class VerseTiming:
    """Start and end position of a single verse within the concatenated audio."""

    arabic: str
    english: str
    start_ms: int  # milliseconds from the start of the combined audio
    end_ms: int  # exclusive end time in milliseconds


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
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
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

    Each source clip keeps its natural duration (no loop/forced equal split).
    Clips are consumed in order until the target timeline is filled; extra
    clips may be unused.  The resulting file is written to *work_dir* and its
    path is returned.
    """
    n = len(paths)
    target_w = config.video_width if config.video_width > 0 else 1080
    target_h = config.video_height if config.video_height > 0 else 1920
    log.info("Building xfade background from %d clip(s)", n)

    # Keep the fade short relative to per-clip time to avoid artefacts
    fade_dur = min(1.0, total_duration / max(n * 4, 1))

    clip_durations = [max(0.1, _get_audio_duration(p)) for p in paths]
    selected_paths: list[str] = []
    selected_durations: list[float] = []
    timeline = 0.0
    for p, d in zip(paths, clip_durations):
        if not selected_paths:
            timeline = d
        else:
            timeline += d - fade_dur
        selected_paths.append(p)
        selected_durations.append(d)
        if timeline >= total_duration:
            break

    # Inputs: use selected clips at full natural duration
    cmd: list[str] = []
    for p in selected_paths:
        cmd += ["-i", p]

    # filter_complex: normalize per clip, then chain xfade filters
    filters: list[str] = []
    for i in range(len(selected_paths)):
        # xfade requires all streams to share size/fps/SAR/pixel format.
        filters.append(
            f"[{i}:v]"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"fps=30,format=yuv420p,setsar=1,"
            f"setpts=PTS-STARTPTS"
            f"[cv{i}]"
        )

    prev = "cv0"
    running_duration = selected_durations[0]
    for i in range(1, len(selected_paths)):
        offset = max(0.0, running_duration - fade_dur)
        out = f"xfv{i}"
        filters.append(
            f"[{prev}][cv{i}]xfade=transition=fade:duration={fade_dur:.3f}:"
            f"offset={offset:.3f}[{out}]"
        )
        prev = out
        running_duration = running_duration + selected_durations[i] - fade_dur

    bg_path = os.path.join(work_dir, "background.mp4")
    _run_ffmpeg(
        [
            *cmd,
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{prev}]",
            "-t",
            f"{total_duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            bg_path,
        ],
        step_name="build-xfade-background",
    )
    return bg_path


def build_video(
    audio_urls: list[str] | None = None,
    nature_video_paths: list[str] | str | None = None,
    output_path: str | None = None,
    width: int = 0,
    height: int = 0,
    darken: float = 0.15,
    verse_texts: list[tuple[str, str]] | None = None,
    verse_segments: list[list[list[int]]] | None = None,
    *,
    ruku_number: int | None = None,
    verse_limit: int | None = None,
    output_dir: str | None = None,
    pexels_query: str | None = None,
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
    if ruku_number is not None:
        return _build_video_from_ruku(
            ruku_number=ruku_number,
            output_path=output_path,
            nature_video_paths=nature_video_paths,
            width=width,
            height=height,
            darken=darken,
            verse_limit=verse_limit,
            output_dir=output_dir,
            pexels_query=pexels_query,
        )

    if not audio_urls:
        raise ValueError("audio_urls must not be empty")
    if nature_video_paths is None:
        raise ValueError("nature_video_paths must be provided")
    if output_path is None:
        raise ValueError("output_path must be provided")

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
        _run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-c",
                "copy",
                combined_audio,
            ],
            step_name="concat-audio",
        )

        # ── 3. Build background video ─────────────────────────────────── #
        if len(nature_video_paths) > 1:
            audio_duration = _get_audio_duration(combined_audio)
            bg_path = _build_xfade_background(
                nature_video_paths, audio_duration, work_dir
            )
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
            srt_path = os.path.join(work_dir, "subs.ass")
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
            vf_parts.append(f"ass={escaped}:fontsdir=/home/ramadan/.fonts")

        overlay_args = [
            *bg_input_args,
            "-i",
            combined_audio,
            *shortest_flag,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
        ]
        if vf_parts:
            overlay_args += [
                "-vf",
                ",".join(vf_parts),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
            ]
        else:
            overlay_args += ["-c:v", "copy", "-c:a", "aac"]
        overlay_args.append(output_path)
        _run_ffmpeg(overlay_args, step_name="overlay-audio-video")

        log.info("Video produced: %s", output_path)
        return output_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _build_video_from_ruku(
    ruku_number: int,
    output_path: str | None,
    nature_video_paths: list[str] | str | None,
    width: int,
    height: int,
    darken: float,
    verse_limit: int | None,
    output_dir: str | None,
    pexels_query: str | None,
) -> str:
    """Build a video directly from a ruku number."""
    log.info("Fetching verses for ruku %d", ruku_number)
    verses = get_verses_by_ruku(
        ruku_number,
        config.translation_id,
        config.recitation_id,
    )
    if verse_limit is not None:
        verses = verses[:verse_limit]
    if not verses:
        raise ValueError(f"No verses found for ruku {ruku_number}")

    if output_path is None:
        if output_dir is None:
            output_dir = os.path.join(os.getcwd(), "example_output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "example_video.mp4")

    if nature_video_paths is None:
        pexels_key = Secrets.from_env().pexels_api_key
        if not pexels_key:
            raise ValueError(
                "Set PEXELS_API_KEY or provide nature_video_paths when building from ruku"
            )
        queries = config.nature_video_queries

        with tempfile.TemporaryDirectory(prefix="quran_example_bg_") as bg_dir:
            bg_video_paths: list[str] = []
            for i, _ in enumerate(verses):
                query = pexels_query or queries[i % len(queries)]
                bg_video_path = os.path.join(bg_dir, f"nature_bg_{i:03d}.mp4")
                log.info(
                    "Fetching background video %d/%d to %s",
                    i + 1,
                    len(verses),
                    bg_video_path,
                )
                PexelsClient(pexels_key).fetch_video(query, bg_video_path)
                bg_video_paths.append(bg_video_path)

            return build_video(
                audio_urls=[v.audio_url for v in verses],
                nature_video_paths=bg_video_paths,
                output_path=output_path,
                width=width if width > 0 else config.video_width,
                height=height if height > 0 else config.video_height,
                darken=darken if darken != 0.15 else config.video_darken,
                verse_texts=[(v.arabic, v.english) for v in verses],
                verse_segments=[
                    cast(list[list[int]], cast(Any, v).audio_segments) for v in verses
                ],
            )

    return build_video(
        audio_urls=[v.audio_url for v in verses],
        nature_video_paths=nature_video_paths,
        output_path=output_path,
        width=width if width > 0 else config.video_width,
        height=height if height > 0 else config.video_height,
        darken=darken if darken != 0.15 else config.video_darken,
        verse_texts=[(v.arabic, v.english) for v in verses],
        verse_segments=[
            cast(list[list[int]], cast(Any, v).audio_segments) for v in verses
        ],
    )


def _build_subtitle_file(timings: list[VerseTiming], ass_path: str) -> None:
    """Write an ASS subtitle file from *timings* to *ass_path*."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Arabic,DigitalKhatt New Madina,{arabic_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,1.5,0,2,40,40,{arabic_margin_v},1
Style: English,Arial,{english_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,1,0,2,40,40,{english_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(
        arabic_font_size=config.subtitle_arabic_font_size,
        english_font_size=config.subtitle_english_font_size,
        arabic_margin_v=config.subtitle_arabic_margin_v,
        english_margin_v=config.subtitle_english_margin_v,
    )

    usable_width = max(200, config.video_width - (2 * config.subtitle_side_margin))
    arabic_wrap_chars = max(
        50,
        int(usable_width / max(1, config.subtitle_arabic_font_size * 0.85)),
    )
    english_wrap_chars = max(
        50,
        int(usable_width / max(1, config.subtitle_english_font_size * 0.55)),
    )

    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(header)
        for vt in timings:
            duration_ms = vt.end_ms - vt.start_ms

            # Split verses into subtitle chunks.
            arabic_words = vt.arabic.split()
            english_words = vt.english.split()

            # Build Arabic chunks that fit a single subtitle line width.
            max_arabic_words = max(1, config.subtitle_max_arabic_words)
            arabic_chunks: list[str] = []
            i = 0
            while i < len(arabic_words):
                chunk_words: list[str] = []
                chunk_chars = 0
                while i < len(arabic_words) and len(chunk_words) < max_arabic_words:
                    next_word = arabic_words[i]
                    # Estimate width by characters excluding spaces.
                    next_chars = chunk_chars + len(next_word)
                    if chunk_words and next_chars > arabic_wrap_chars:
                        break
                    chunk_words.append(next_word)
                    chunk_chars = next_chars
                    i += 1

                if not chunk_words:
                    # Ensure forward progress even for a single very long token.
                    chunk_words = [arabic_words[i]]
                    i += 1

                arabic_chunks.append(" ".join(chunk_words))

            num_chunks = max(1, len(arabic_chunks))

            chunk_duration = duration_ms // num_chunks

            english_chunk_size = math.ceil(len(english_words) / num_chunks)

            for chunk_index in range(num_chunks):
                chunk_start = vt.start_ms + chunk_index * chunk_duration
                chunk_end = (
                    vt.start_ms + (chunk_index + 1) * chunk_duration
                    if chunk_index < num_chunks - 1
                    else vt.end_ms
                )

                start_str = _ms_to_ass_time(chunk_start)
                end_str = _ms_to_ass_time(chunk_end)

                ar_chunk = arabic_chunks[chunk_index]
                en_chunk = " ".join(
                    english_words[
                        chunk_index
                        * english_chunk_size : (chunk_index + 1)
                        * english_chunk_size
                    ]
                )

                # Arabic is intentionally kept on one line; chunks are width-constrained above.
                ar_wrapped = ar_chunk
                en_wrapped = "\\N".join(
                    textwrap.wrap(en_chunk, width=english_wrap_chars)
                )

                fh.write(
                    f"Dialogue: 0,{start_str},{end_str},Arabic,,0,0,0,,{ar_wrapped}\n"
                )
                fh.write(
                    f"Dialogue: 0,{start_str},{end_str},English,,0,0,0,,{en_wrapped}\n"
                )


def _ms_to_ass_time(ms: int) -> str:
    """Convert milliseconds to ASS timestamp ``H:MM:SS.cc``."""
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1_000
    cs = (ms % 1_000) // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def compute_verse_timings(
    audio_files: list[str],
    verse_texts: list[tuple[str, str]],
    verse_segments: list[list[list[int]]] | None = None,
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
    for i, (audio_path, (arabic, english)) in enumerate(zip(audio_files, verse_texts)):
        segs = verse_segments[i] if verse_segments and i < len(verse_segments) else []
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


def _run_ffmpeg(args: list[str], step_name: str = "ffmpeg") -> None:
    """Run ffmpeg with the given argument list, raising on non-zero exit."""
    cmd = ["ffmpeg", "-y"] + args
    log.info("Starting ffmpeg step: %s", step_name)
    log.debug("ffmpeg command: %s", " ".join(cmd))
    start = time.monotonic()
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        elapsed = time.monotonic() - start
        log.error("ffmpeg step failed: %s (%.2fs)", step_name, elapsed)
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    elapsed = time.monotonic() - start
    log.info("Finished ffmpeg step: %s (%.2fs)", step_name, elapsed)


if __name__ == "__main__":
    __import__("main").main()

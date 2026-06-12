import textwrap
import math
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
    nature_video_paths: list[str] | str,
    output_path: str,
    width: int = 0,
    height: int = 0,
    darken: float = 0.15,
    verse_texts: list[tuple[str, str]] | None = None,
    verse_segments: list[list[list[int]]] | None = None,
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


def _build_subtitle_file(timings: list[VerseTiming], ass_path: str) -> None:
    """Write an ASS subtitle file from *timings* to *ass_path*."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Arabic,DigitalKhatt New Madina,40,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,1.5,0,8,40,40,650,1
Style: English,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,1,0,8,40,40,500,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(header)
        for vt in timings:
            duration_ms = vt.end_ms - vt.start_ms
            
            # Split long verses into chunks (around 6-8 words max per chunk for Arabic)
            arabic_words = vt.arabic.split()
            english_words = vt.english.split()
            
            # Use smaller chunks for Arabic (max 8 words)
            num_chunks = max(1, math.ceil(len(arabic_words) / 8))
            
            chunk_duration = duration_ms // num_chunks
            
            arabic_chunk_size = math.ceil(len(arabic_words) / num_chunks)
            english_chunk_size = math.ceil(len(english_words) / num_chunks)
            
            for i in range(num_chunks):
                chunk_start = vt.start_ms + i * chunk_duration
                chunk_end = vt.start_ms + (i + 1) * chunk_duration if i < num_chunks - 1 else vt.end_ms
                
                start_str = _ms_to_ass_time(chunk_start)
                end_str = _ms_to_ass_time(chunk_end)
                
                ar_chunk = " ".join(arabic_words[i * arabic_chunk_size : (i + 1) * arabic_chunk_size])
                en_chunk = " ".join(english_words[i * english_chunk_size : (i + 1) * english_chunk_size])
                
                # We can add explicit line breaks using ASS \N tag
                ar_wrapped = "\\N".join(textwrap.wrap(ar_chunk, width=30))
                en_wrapped = "\\N".join(textwrap.wrap(en_chunk, width=45))
                
                fh.write(f"Dialogue: 0,{start_str},{end_str},Arabic,,0,0,0,,{ar_wrapped}\n")
                fh.write(f"Dialogue: 0,{start_str},{end_str},English,,0,0,0,,{en_wrapped}\n")


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

if __name__ == "__main__":
    import os
    import sys
    from secrets import Secrets
    from dotenv import load_dotenv
    load_dotenv()
    from config import config
    from quran_api import get_verses_by_ruku
    from pexels import PexelsClient
    import logging
    
    logging.basicConfig(level=logging.DEBUG)

    # We just want to build a small example video. Let's grab ruku 1 (Al-Fatihah)
    print("Fetching verses for Ruku 1...")
    verses = get_verses_by_ruku(1)
    
    # We only take the first two verses to make it quick
    verses = verses[:2]
    
    # Fallback to get PEXELS_API_KEY from env if Secrets.from_env() fails due to missing Twitter keys
    pexels_key = os.environ.get('PEXELS_API_KEY')
    if not pexels_key:
        print("PEXELS_API_KEY is not set. Please add it to .env")
        sys.exit(1)
        
    # config is already imported
    
    client = PexelsClient(pexels_key)
    
    example_dir = os.path.join(os.getcwd(), "example_output")
    os.makedirs(example_dir, exist_ok=True)
    
    bg_video_path = os.path.join(example_dir, "nature_bg.mp4")
    print(f"Fetching background video to {bg_video_path}...")
    client.fetch_video("nature", bg_video_path)
    
    audio_urls = [v.audio_url for v in verses]
    verse_texts = [(v.arabic, v.english) for v in verses]
    verse_segments = [v.audio_segments for v in verses]
    
    output_video = os.path.join(example_dir, "example_video.mp4")
    print(f"Building example video at {output_video}...")
    
    build_video(
        audio_urls=audio_urls,
        nature_video_paths=[bg_video_path],
        output_path=output_video,
        width=config.video_width,
        height=config.video_height,
        darken=config.video_darken,
        verse_texts=verse_texts,
        verse_segments=verse_segments
    )
    
    print(f"Example video successfully created at {output_video}")

#!/usr/bin/env python3
"""ffmpeg side of the pipeline: measure media, detect silence, render the cut file.

Everything here shells out to ffmpeg/ffprobe — no python media libraries. Regions in and out are
always "(start, end) seconds", the same interchange format the rest of magcut speaks.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from magcut.regions import parse_silencedetect

# Same encoder profile as magpress "screencast" — smallest file that still looks clean on a
# screen recording. Cutting cannot be done with -c copy: keyframes sit seconds apart, so a
# stream copy would move every cut to the nearest one.
NVENC_ARGS = ["-c:v", "h264_nvenc", "-rc", "vbr", "-cq", "28", "-preset", "p6",
              "-spatial-aq", "1", "-temporal-aq", "1", "-rc-lookahead", "20"]
X264_ARGS = ["-c:v", "libx264", "-crf", "28", "-preset", "fast"]
AUDIO_ARGS = ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]


def video_encoder() -> list[str]:
    """NVENC when the GPU is reachable, x264 otherwise (no driver, or all NVENC sessions busy)."""
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", "nullsrc=s=64x64:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
                           capture_output=True, text=True)
    if probe.returncode == 0:
        return NVENC_ARGS
    print("NVENC unavailable — falling back to libx264 (slower)", file=sys.stderr)
    return X264_ARGS


def run(cmd: list[str], what: str) -> str:
    """Run a command, return its stderr; abort with its own message if it fails."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"{what} failed:\n{proc.stderr.strip()[-2000:]}")
    return proc.stderr


def duration(media: Path) -> float:
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=nw=1:nk=1", str(media)], capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        sys.exit(f"cannot read duration of {media} — not a media file?")
    return float(proc.stdout.strip())


def silences(media: Path, noise_db: float, min_dur: float) -> list[tuple[float, float]]:
    """Silent regions per ffmpeg silencedetect. Inverted, this is also the 'loud' region list."""
    stderr = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(media),
                  "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
                 "silence detection")
    return parse_silencedetect(stderr)


def keep_expr(keep: list[tuple[float, float]]) -> str:
    """A select() expression matching any of the kept regions, as a BALANCED sum tree.

    "a+b+c+..." written flat dies at 100 terms: ffmpeg's expression parser guards its own stack
    with a depth counter and returns ENOMEM ("Cannot allocate memory") past it. Pairing the terms
    up — ((a+b)+(c+d)) — makes the depth log2(n) instead of n, so thousands of regions parse fine.
    """
    terms = [f"between(t,{s:.3f},{e:.3f})" for s, e in keep]
    while len(terms) > 1:
        terms = [f"({terms[i]}+{terms[i + 1]})" if i + 1 < len(terms) else terms[i]
                 for i in range(0, len(terms), 2)]
    return terms[0]


def render(media: Path, keep: list[tuple[float, float]], out: Path) -> None:
    """Write `out` holding only the kept regions, concatenated in order."""
    if not keep:
        sys.exit("nothing would be left — refusing to render an empty file")
    expr = keep_expr(keep)
    # a filter script file, not -filter_complex: with hundreds of regions the expression easily
    # outgrows the command line
    graph = (f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];"
             f"[0:a]aselect='{expr}',asetpts=N/SR/TB[a]")
    with tempfile.NamedTemporaryFile("w", suffix=".filter", encoding="utf-8") as fh:
        fh.write(graph)
        fh.flush()
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y",
                               "-i", str(media), "-filter_complex_script", fh.name, "-map", "[v]",
                               "-map", "[a]", *video_encoder(), *AUDIO_ARGS, str(out)])
    if proc.returncode != 0:
        out.unlink(missing_ok=True)  # ffmpeg leaves a 0-byte file behind on failure
        sys.exit("rendering failed — see the ffmpeg output above")

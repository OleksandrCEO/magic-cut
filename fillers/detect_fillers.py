#!/usr/bin/env python3
"""Detect loud "filler" regions — voiced audio with no transcribed word.

Silence detection is amplitude-based and cannot catch hesitation vowels ("е-е",
"а-а"): those are normal-volume sounds. This finds them by intersecting two views
of the audio:
  * LOUD regions  — audio above the loudness gate (inverse of ffmpeg silencedetect)
  * WORD regions  — intervals covered by a transcribed word (faster-whisper)
A stretch that is loud but has NO word over it, lasting >= --min-filler, is almost
certainly a filler / hesitation sound. Output is "<start> <end>" seconds per line —
feed it straight into ../silence_cut.py --silences (which pads and splits them).

Only LOUD no-word regions are reported; silent pauses are left to the silence pass,
so the two tools split the work with no double-counting.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys


def detect_silences(media: str, noise: float, gate_gap: float) -> list[tuple[float, float]]:
    """Silent intervals via ffmpeg (fine gate to segment loud vs quiet)."""
    cmd = ["ffmpeg", "-hide_banner", "-i", media, "-af",
           f"silencedetect=noise={noise}dB:d={gate_gap}", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", proc.stderr)]
    return list(zip(starts, ends, strict=False))


def transcribe_words(media: str, model_size: str, language: str, device: str,
                     compute_type: str) -> tuple[list[tuple[float, float]], float]:
    """Word intervals + media duration from faster-whisper (word_timestamps=True)."""
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(media, language=language, word_timestamps=True)
    words: list[tuple[float, float]] = []
    for seg in segments:
        for w in seg.words or []:
            words.append((w.start, w.end))
    return words, float(info.duration)


def complement(intervals: list[tuple[float, float]], start: float,
               end: float) -> list[tuple[float, float]]:
    """Gaps within [start, end] not covered by the given intervals."""
    gaps: list[tuple[float, float]] = []
    cur = start
    for a, b in sorted(intervals):
        if a > cur:
            gaps.append((cur, min(a, end)))
        cur = max(cur, b)
        if cur >= end:
            break
    if cur < end:
        gaps.append((cur, end))
    return [(a, b) for a, b in gaps if b > a]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", help="source audio/video file")
    ap.add_argument("-o", "--out", help="write regions here (default: stdout)")
    ap.add_argument("--noise", type=float, default=-20.0, help="loudness gate dB (default -20)")
    ap.add_argument("--gate-gap", type=float, default=0.1,
                    help="min silence used to segment loud regions (default 0.1s)")
    ap.add_argument("--min-filler", type=float, default=0.35,
                    help="min loud-no-word duration to report (default 0.35s)")
    ap.add_argument("--model", default="large-v3", help="faster-whisper model (default large-v3)")
    ap.add_argument("--language", default="uk", help="language code (default uk)")
    ap.add_argument("--device", default="cuda", help="cuda or cpu (default cuda)")
    ap.add_argument("--compute-type", default="float16",
                    help="float16 / int8_float16 / int8 (default float16)")
    args = ap.parse_args()

    silences = detect_silences(args.media, args.noise, args.gate_gap)
    words, duration = transcribe_words(
        args.media, args.model, args.language, args.device, args.compute_type)

    loud = complement(silences, 0.0, duration)
    fillers: list[tuple[float, float]] = []
    for a, b in loud:
        covering = [(ws, we) for ws, we in words if we > a and ws < b]
        fillers.extend(
            (ga, gb) for ga, gb in complement(covering, a, b) if gb - ga >= args.min_filler
        )

    body = "".join(f"{a:.3f} {b:.3f}\n" for a, b in fillers)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(body)
        print(f"{len(fillers)} filler regions -> {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(body)
        print(f"{len(fillers)} filler regions", file=sys.stderr)


if __name__ == "__main__":
    main()

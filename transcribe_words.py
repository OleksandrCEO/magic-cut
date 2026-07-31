#!/usr/bin/env python3
"""Transcribe media with faster-whisper and dump word-level timings as JSON.

This is the EXPENSIVE half of the detection pipeline: one GPU pass over the
media, producing a stable artefact. Turning that artefact into a regions file
for silence_cut.py is a separate, cheap step (see words_to_regions.py) that can
be re-run with different thresholds without touching the GPU again.

The same JSON also carries the segment texts, so subtitles or a transcript can
be generated later from the identical pass — no second transcription.

Output format:
  {
    "media": "/path/to/video.mp4",
    "duration": 2701.4,          # seconds of audio, as whisper measured it
    "language": "uk",
    "model": "large-v3",
    "vad": true,
    "words":    [{"w": "слово", "s": 1.234, "e": 1.470, "p": 0.98}, ...],
    "segments": [{"s": 0.0, "e": 4.12, "t": "Ціле речення."}, ...]
  }

Timestamps are absolute seconds from the start of the media file — the same
time base silence_cut.py expects for its regions.

Needs: faster-whisper with a working CUDA/cuDNN environment (the MagType
devShell provides one).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media", help="path to the audio/video file")
    ap.add_argument("--out", default=None,
                    help="output JSON (default: <media>.words.json next to the media)")
    ap.add_argument("--model", default="large-v3",
                    help="faster-whisper model name or local path (default large-v3)")
    ap.add_argument("--model-dir", default=None,
                    help="cache directory for downloaded models (default: HF cache in $HOME)")
    ap.add_argument("--language", default=None,
                    help="force language code, e.g. uk (default: autodetect from first 30 s)")
    ap.add_argument("--device", default="cuda", help="cuda or cpu (default cuda)")
    ap.add_argument("--compute-type", default="float16",
                    help="float16 | int8_float16 | int8 | float32 (default float16)")
    ap.add_argument("--beam-size", type=int, default=5, help="decoding beam width (default 5)")
    ap.add_argument("--no-vad", dest="vad", action="store_false",
                    help="disable the Silero VAD pre-filter (it suppresses hallucinated "
                         "words in long pauses; on by default)")
    args = ap.parse_args()

    # imported late so that --help stays instant and does not load CUDA
    from faster_whisper import WhisperModel

    media = Path(args.media)
    if not media.is_file():
        sys.exit(f"media not found: {media}")
    out = Path(args.out) if args.out else media.with_suffix(media.suffix + ".words.json")

    t0 = time.monotonic()
    model = WhisperModel(args.model, device=args.device,
                         compute_type=args.compute_type, download_root=args.model_dir)

    segments, info = model.transcribe(
        str(media),
        language=args.language,
        beam_size=args.beam_size,
        word_timestamps=True,
        vad_filter=args.vad,
    )
    print(f"language={info.language} (p={info.language_probability:.2f})  "
          f"duration={info.duration:.1f}s", file=sys.stderr)

    # `segments` is a generator: decoding happens while we iterate
    words: list[dict[str, object]] = []
    segs: list[dict[str, object]] = []
    for seg in segments:
        segs.append({"s": round(seg.start, 3), "e": round(seg.end, 3), "t": seg.text.strip()})
        for w in seg.words or ():
            text = w.word.strip()
            if not text:
                continue
            words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3),
                          "p": round(w.probability, 3)})
        done = 100 * seg.end / info.duration if info.duration else 0
        print(f"\r  {done:5.1f}%  {len(words)} words", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    if not words:
        sys.exit("ABORT (not written): no words recognised — wrong language or silent track?")

    payload = {
        "media": str(media.resolve()),
        "duration": round(info.duration, 3),
        "language": info.language,
        "model": args.model,
        "vad": args.vad,
        "words": words,
        "segments": segs,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    elapsed = time.monotonic() - t0
    speed = info.duration / elapsed if elapsed else 0
    print(f"{out}")
    print(f"  words: {len(words)}  segments: {len(segs)}")
    print(f"  media {info.duration:.1f}s in {elapsed:.0f}s  ({speed:.1f}x realtime)")


if __name__ == "__main__":
    main()

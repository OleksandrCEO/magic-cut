#!/usr/bin/env python3
"""magcut — cut silence (and hesitation sounds) out of a video, or split a kdenlive timeline.

  magcut video.mp4              silence only          -> video-edited.mp4
  magcut video.mp4 --fillers    silence + "е-е-е"     -> video-edited.mp4  (needs whisper/GPU)
  magcut project.kdenlive       split the timeline instead of rendering (kdenlive/ add-on)

Pauses always come from ffmpeg silencedetect, never from the transcript: measured on real
material, amplitude finds more pauses with tighter borders (README §2). The transcript is only
pulled in for hesitation sounds, which are loud and therefore invisible to amplitude gating.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from magcut import media as mediatools
from magcut.regions import DEFAULT_GAP, DEFAULT_PAD, find_voiced_fillers, invert, merge

LOUD_NOISE_DB = -35.0  # finer threshold than the pause pass: a filler is loud, only wordless
LOUD_MIN_DUR = 0.15


def hesitations(video: Path, duration: float, language: str | None, model: str) -> list[tuple[float, float]]:
    """Loud stretches that start no word. Reuses <video>.words.json if it is already there."""
    from magcut.transcribe import transcribe

    words_json = video.with_suffix(video.suffix + ".words.json")
    if words_json.is_file():
        print(f"reusing transcript {words_json.name} (delete it to re-transcribe)", file=sys.stderr)
    else:
        transcribe(video, words_json, model_name=model, language=language)
    words = json.loads(words_json.read_text(encoding="utf-8"))["words"]
    loud = invert(mediatools.silences(video, LOUD_NOISE_DB, LOUD_MIN_DUR), duration)
    return find_voiced_fillers(words, loud, min_filler=0.3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="video file, or a .kdenlive project (handled by the add-on)")
    ap.add_argument("--fillers", action="store_true",
                    help="also cut hesitation sounds ('е-е-е') — transcribes the video first")
    ap.add_argument("--noise", type=float, default=-20.0, help="silence threshold in dB (default -20)")
    ap.add_argument("--min-silence", type=float, default=DEFAULT_GAP,
                    help=f"shortest silence worth cutting (default {DEFAULT_GAP}s)")
    ap.add_argument("--pad", type=float, default=DEFAULT_PAD,
                    help=f"seconds of pause kept each side of a cut (default {DEFAULT_PAD:.2f})")
    ap.add_argument("--language", default=None, help="force transcript language, e.g. uk (--fillers only)")
    ap.add_argument("--model", default="large-v3", help="whisper model (--fillers only)")
    ap.add_argument("--out", default=None, help="output file (default: <input>-edited.mp4 alongside)")
    args, rest = ap.parse_known_args()

    source = Path(args.input)
    if not source.is_file():
        sys.exit(f"not a file: {source}")

    if source.suffix == ".kdenlive":
        script = Path(__file__).resolve().parent.parent / "kdenlive" / "cut-silences.sh"
        os.execv(str(script), [str(script), str(source), *sys.argv[2:]])  # noqa: S606 — fixed path
    if rest:
        ap.error(f"unknown arguments: {' '.join(rest)}")

    out = Path(args.out) if args.out else source.with_name(f"{source.stem}-edited.mp4")
    if out.resolve() == source.resolve():
        sys.exit("refusing to overwrite the source file — pass a different --out")

    duration = mediatools.duration(source)
    cuts = mediatools.silences(source, args.noise, args.min_silence)
    print(f"silence : {len(cuts):4d}  {sum(e - s for s, e in cuts):8.1f}s", file=sys.stderr)
    if args.fillers:
        voiced = hesitations(source, duration, args.language, args.model)
        print(f"fillers : {len(voiced):4d}  {sum(e - s for s, e in voiced):8.1f}s", file=sys.stderr)
        cuts += voiced

    # shrink every cut inwards so a pause becomes short instead of disappearing; regions too
    # short to survive that are not worth cutting at all
    cuts = [(s + args.pad, e - args.pad) for s, e in merge(cuts) if e - s > 2 * args.pad]
    keep = invert(cuts, duration)
    removed = sum(e - s for s, e in cuts)
    print(f"cutting : {len(cuts):4d}  {removed:8.1f}s of {duration:.1f}s "
          f"({100 * removed / duration:.0f}%)  ->  {duration - removed:.1f}s", file=sys.stderr)

    mediatools.render(source, keep, out)
    print(f"{out}")
    subprocess.run(["notify-send", "-i", "video-x-generic", "MagCut",
                    f"{out.name}\n{duration:.0f}s → {duration - removed:.0f}s"], check=False)


if __name__ == "__main__":
    main()

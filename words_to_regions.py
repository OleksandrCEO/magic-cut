#!/usr/bin/env python3
"""Turn a *.words.json transcript into a regions file for silence_cut.py.

This is the CHEAP half of the pipeline: pure stdlib, milliseconds per run, so
thresholds can be re-tuned as many times as needed without touching the GPU.
Input comes from transcribe_words.py, output is the plain "<start> <end>" per
line format silence_cut.py already reads.

Two kinds of regions are produced:

  * PAUSES — stretches with no recognised word for at least --gap seconds.
    Strictly better than ffmpeg silencedetect for pauses that are NOISY but
    wordless: breathing, mouse clicks, keyboard, room tone. Amplitude gating
    cannot see those; a transcript can.

  * FILLERS — words matching a hesitation pattern ("е-е-е", "мм"). These ARE
    loud speech, so amplitude gating cannot see them either.

Both land in the same output; silence_cut.py pads each region inwards, so a
short pause is kept around every cut instead of a hard splice.

Usage:
  python3 words_to_regions.py video.mp4.words.json > video.silences
  python3 silence_cut.py project.kdenlive --silences video.silences --in-place
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# Hesitation SOUNDS only. Real filler WORDS ("ну", "типу", "коротше") are ordinary vocabulary
# as well, so cutting them blind would mangle sentences — put those in your own --fillers file.
DEFAULT_FILLERS: tuple[str, ...] = (r"[еэe]{2,}", r"[аa]{2,}", r"[мm]{2,}", r"ем+", r"хм+", r"ух")

DEFAULT_GAP = 0.66  # same default as the amplitude pass, so both agree on "this is a pause"


def normalize(word: str) -> str:
    """Lowercase, drop punctuation and dashes: 'Е-е-е,' -> 'еее'."""
    return "".join(c for c in word.casefold() if unicodedata.category(c)[0] in "LN")


def load_patterns(spec: str | None) -> list[re.Pattern[str]]:
    """--fillers is either a path to a newline list or a comma-separated inline list."""
    if spec is None:
        raw: list[str] = list(DEFAULT_FILLERS)
    elif Path(spec).is_file():
        raw = [ln.strip() for ln in Path(spec).read_text(encoding="utf-8").splitlines()]
    else:
        raw = [p.strip() for p in spec.split(",")]
    return [re.compile(p) for p in raw if p and not p.startswith("#")]


def find_pauses(words: list[dict], duration: float, gap: float,
                min_prob: float = 0.0) -> list[tuple[float, float]]:
    """Wordless stretches >= gap, including before the first and after the last word.

    Words below min_prob are not treated as evidence of speech. Low confidence usually means
    a smeared BOUNDARY, not a missing word: a quiet word right after a pause gets a start time
    reaching back into the silence, and that one word hides the whole pause. Note the trade-off —
    the word is real, so its opening moment lands inside the region. The engine's --pad shrinks
    every region inwards, which covers it; with --delete, verify before trusting it.
    """
    regions: list[tuple[float, float]] = []
    prev_end = 0.0
    for w in words:
        if w["p"] < min_prob:
            continue
        if w["s"] - prev_end >= gap:
            regions.append((prev_end, w["s"]))
        prev_end = max(prev_end, w["e"])  # max(): whisper occasionally emits overlapping words
    if duration - prev_end >= gap:
        regions.append((prev_end, duration))
    return regions


def find_fillers(words: list[dict], patterns: list[re.Pattern[str]]) -> tuple[list[tuple[float, float]], dict[str, int]]:
    """Words whose normalized form fully matches a filler pattern, plus a per-word hit count."""
    regions: list[tuple[float, float]] = []
    hits: dict[str, int] = {}
    for w in words:
        norm = normalize(w["w"])
        if norm and any(p.fullmatch(norm) for p in patterns):
            regions.append((w["s"], w["e"]))
            hits[norm] = hits.get(norm, 0) + 1
    return regions, hits


def read_loud(path: str, duration: float) -> list[tuple[float, float]]:
    """Loud regions = the inverse of ffmpeg silencedetect output."""
    raw = Path(path).read_text(encoding="utf-8")
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", raw)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", raw)]
    loud: list[tuple[float, float]] = []
    prev = 0.0
    for s, e in sorted(zip(starts, ends, strict=False)):
        if s > prev:
            loud.append((prev, s))
        prev = max(prev, e)
    if duration > prev:
        loud.append((prev, duration))
    return loud


def find_voiced_fillers(words: list[dict], loud: list[tuple[float, float]],
                        min_filler: float, stretch: float = 2.0) -> list[tuple[float, float]]:
    """Loud stretches that START no word — hesitation vowels ("е-е-е", "м-м").

    Whisper does not transcribe hesitation sounds at all: it stretches the NEIGHBOURING word
    over them, so "is a word covering this?" is always true and proves nothing. What stays
    true is that no word BEGINS inside the filler.

    Two filters keep ordinary speech out. The duration floor drops short loud syllables. The
    stretch factor drops long-but-normal words: a filler hides inside a word that is abnormally
    SLOW per character ("ми" at 1.17 s/char), never inside one that is merely long
    ("аплодисменти" at 0.115 s/char, right at the median).
    """
    word_starts = [w["s"] for w in words]
    rates = sorted((w["e"] - w["s"]) / max(len(normalize(w["w"])), 1) for w in words)
    typical = rates[len(rates) // 2] if rates else 0.0

    fillers: list[tuple[float, float]] = []
    for a, b in loud:
        if b - a < min_filler or any(a <= s <= b for s in word_starts):
            continue
        host = next((w for w in words if w["s"] <= a and w["e"] >= b), None)
        if host and typical:
            rate = (host["e"] - host["s"]) / max(len(normalize(host["w"])), 1)
            if rate < stretch * typical:
                continue  # the host word genuinely takes that long — a slow syllable, not a filler
        fillers.append((a, b))
    return fillers


def merge(regions: list[tuple[float, float]], join: float = 0.0) -> list[tuple[float, float]]:
    """Sort and coalesce overlapping/adjacent regions (a filler sitting next to a pause)."""
    merged: list[list[float]] = []
    for start, end in sorted(regions):
        if merged and start <= merged[-1][1] + join:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words_json", help="transcript produced by transcribe_words.py")
    ap.add_argument("--out", default=None, help="output regions file (default: stdout)")
    ap.add_argument("--gap", type=float, default=DEFAULT_GAP,
                    help=f"shortest wordless stretch counted as a pause (default {DEFAULT_GAP}s)")
    ap.add_argument("--fillers", default=None,
                    help="file with one regex per line, or an inline comma-separated list. "
                         f"Default: {','.join(DEFAULT_FILLERS)}")
    ap.add_argument("--loud", default=None,
                    help="ffmpeg silencedetect output for the SAME media — enables detection of "
                         "hesitation SOUNDS ('е-е-е'), which whisper never transcribes. "
                         "Produce it with: ffmpeg -i MEDIA -af silencedetect=noise=-35dB:d=0.15 -f null -")
    ap.add_argument("--min-filler", type=float, default=0.3,
                    help="shortest loud wordless stretch counted as a filler (default 0.3s); "
                         "below this it is usually just a syllable inside a long word")
    ap.add_argument("--stretch", type=float, default=2.0,
                    help="a filler must sit in a word at least this many times slower per character "
                         "than the median word (default 2.0); guards long-but-normal words")
    ap.add_argument("--min-prob", type=float, default=0.0,
                    help="ignore words below this confidence when looking for pauses — they are "
                         "usually hallucinations inside silence (try 0.3). Fillers are unaffected.")
    ap.add_argument("--no-pauses", dest="pauses", action="store_false", help="fillers only")
    ap.add_argument("--no-fillers", dest="do_fillers", action="store_false", help="pauses only")
    ap.add_argument("--join", type=float, default=0.0,
                    help="merge regions closer than this to each other (default 0)")
    args = ap.parse_args()

    data = json.loads(Path(args.words_json).read_text(encoding="utf-8"))
    words: list[dict] = data["words"]
    duration = float(data["duration"])
    if not words:
        sys.exit("transcript holds no words — nothing to derive")

    regions: list[tuple[float, float]] = []
    if args.pauses:
        pauses = find_pauses(words, duration, args.gap, args.min_prob)
        regions += pauses
        print(f"pauses  : {len(pauses):4d}  {sum(e - s for s, e in pauses):8.1f}s", file=sys.stderr)
    if args.do_fillers:
        fillers, hits = find_fillers(words, load_patterns(args.fillers))
        regions += fillers
        print(f"fillers : {len(fillers):4d}  {sum(e - s for s, e in fillers):8.1f}s", file=sys.stderr)
        for word, count in sorted(hits.items(), key=lambda kv: -kv[1]):
            print(f"            {count:4d}x {word}", file=sys.stderr)
    if args.loud:
        voiced = find_voiced_fillers(words, read_loud(args.loud, duration), args.min_filler, args.stretch)
        regions += voiced
        print(f"voiced  : {len(voiced):4d}  {sum(e - s for s, e in voiced):8.1f}s  (loud, no word starts)",
              file=sys.stderr)
        for s, e in voiced:
            print(f"            {s:7.2f}-{e:7.2f}  ({e - s:.2f}s)", file=sys.stderr)

    regions = merge(regions, args.join)
    cut = sum(e - s for s, e in regions)
    print(f"total   : {len(regions):4d}  {cut:8.1f}s of {duration:.1f}s "
          f"({100 * cut / duration:.0f}% marked, before padding)", file=sys.stderr)

    text = "".join(f"{s:.3f} {e:.3f}\n" for s, e in regions)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()

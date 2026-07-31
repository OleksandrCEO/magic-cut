#!/usr/bin/env python3
"""Self-check: transcript -> regions derivation.

Run: python3 tests/test_regions.py   (stdlib only, no framework — works from any directory)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from magcut.regions import (find_fillers, find_pauses, find_voiced_fillers,  # noqa: E402
                            load_patterns, merge, normalize, read_loud)


def w(text: str, start: float, end: float) -> dict:
    return {"w": text, "s": start, "e": end, "p": 0.9}


WORDS = [w("Привіт", 1.0, 1.5), w("е-е-е,", 1.6, 2.1), w("почнемо", 4.0, 4.6), w("А", 4.7, 4.9)]


def test_normalize_strips_punctuation_and_case() -> None:
    assert normalize("Е-е-е,") == "еее"
    assert normalize("«слово»") == "слово"


def test_pauses_include_head_and_tail() -> None:
    # gap 0.66: head 0..1.0, the 2.1..4.0 hole and the 4.9..6.0 tail all qualify
    assert find_pauses(WORDS, duration=6.0, gap=0.66) == [(0.0, 1.0), (2.1, 4.0), (4.9, 6.0)]
    assert find_pauses(WORDS, duration=6.0, gap=1.5) == [(2.1, 4.0)]  # only the long hole survives


def test_min_prob_ignores_words_with_smeared_boundaries() -> None:
    # "Ну" is a REAL word, but its start time (0.5) reaches back into the silence and hides
    # the pause; low p is the signal that the boundary — not the word — is unreliable
    smeared = [w("Ну", 0.5, 1.0) | {"p": 0.1}, w("почали", 3.0, 3.5)]
    assert find_pauses(smeared, duration=4.0, gap=0.66, min_prob=0.0) == [(1.0, 3.0)]
    assert find_pauses(smeared, duration=4.0, gap=0.66, min_prob=0.3) == [(0.0, 3.0)]


def test_no_default_filler_patterns() -> None:
    # whisper never transcribes hesitation sounds, so a built-in pattern list would only pretend
    # to work; the caller must name filler WORDS explicitly
    assert find_fillers(WORDS, load_patterns(None)) == ([], {})


def test_explicit_pattern_matches_normalized_word() -> None:
    # a comma inside the quantifier must survive — this is why there is no separator char
    regions, hits = find_fillers(WORDS, load_patterns([r"[еэe]{2,}"]))
    assert regions == [(1.6, 2.1)], regions   # "А" is a word, not a hesitation — must survive
    assert hits == {"еее": 1}


def test_inline_filler_list() -> None:
    regions, _ = find_fillers(WORDS, load_patterns(["почнемо"]))
    assert regions == [(4.0, 4.6)], regions


# measured on real material: whisper stretches a neighbouring word over the hesitation sound
VOICED = [
    w("ми", 1.46, 3.80),            # 1.17 s/char — 11x the median, hides an "е-е-е"
    w("продовжуємо", 3.80, 4.64),   # 0.076 s/char — normal
    w("аплодисменти", 23.37, 24.75),  # 0.115 s/char — long word, but normal pace
]


def test_voiced_filler_found_inside_a_stretched_word() -> None:
    loud = [(2.05, 2.62)]  # loud, and no word starts inside it
    assert find_voiced_fillers(VOICED, loud, min_filler=0.3) == [(2.05, 2.62)]


def test_voiced_filler_rejects_long_but_normal_word() -> None:
    # a loud island inside "аплодисменти" is a syllable, not a filler — the word is not slow
    assert find_voiced_fillers(VOICED, [(24.06, 24.72)], min_filler=0.3) == []


def test_voiced_filler_respects_duration_floor_and_word_starts() -> None:
    assert find_voiced_fillers(VOICED, [(2.05, 2.20)], min_filler=0.3) == []      # too short
    assert find_voiced_fillers(VOICED, [(3.50, 4.20)], min_filler=0.3) == []      # a word starts here


def test_read_loud_inverts_silencedetect() -> None:
    raw = "[silencedetect] silence_start: 1.0\n[silencedetect] silence_end: 2.5\n"
    path = "/tmp/claude-1000/-home-config/240b2840-a745-4269-a648-b78a6157e501/scratchpad/_sil.txt"
    open(path, "w", encoding="utf-8").write(raw)
    assert read_loud(path, duration=4.0) == [(0.0, 1.0), (2.5, 4.0)]


def test_merge_coalesces_touching_regions() -> None:
    assert merge([(3.0, 4.0), (0.0, 1.0), (0.9, 2.0)]) == [(0.0, 2.0), (3.0, 4.0)]
    assert merge([(0.0, 1.0), (1.2, 2.0)], join=0.5) == [(0.0, 2.0)]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")

#!/usr/bin/env python3
"""Self-check: each clip must be cut ONLY by the silences of its own media.

Run: python3 test_silence_cut.py   (stdlib only, no framework)
"""
from __future__ import annotations

import re

from silence_cut import producer_media, render_playlist, split_entry

XML = """
 <chain id="chain0"><property name="resource">/m/A.mp4</property></chain>
 <chain id="chain1"><property name="resource">/m/B.mp4</property></chain>
 <producer id="producer0"><property name="resource">black</property></producer>
"""
ENTRIES = [  # both clips are 0..9.9s (100 frames @10fps) of two DIFFERENT files
    ("00:00:00.000", "00:00:09.900", "chain0", ""),
    ("00:00:00.000", "00:00:09.900", "chain1", ""),
]


def test_producer_media() -> None:
    assert producer_media(XML) == {"chain0": "/m/A.mp4", "chain1": "/m/B.mp4", "producer0": "black"}


def test_regions_are_per_media() -> None:
    media = producer_media(XML)
    by_media = {"/m/A.mp4": [(20, 40)], "/m/B.mp4": [(70, 90)]}  # frames @10fps
    body, pieces = render_playlist(
        ENTRIES, False, lambda p: by_media.get(media.get(p, ""), []),
        fps=10.0, pad=0, edge=3, min_entry_frames=0, counter=[0], delete=False)
    cuts = re.findall(r'in="([^"]+)" out="([^"]+)" producer="(\w+)"', body)
    assert [c for c in cuts if c[2] == "chain0"] == [
        ("00:00:00.000", "00:00:01.900", "chain0"),
        ("00:00:02.000", "00:00:04.000", "chain0"),
        ("00:00:04.100", "00:00:09.900", "chain0")], cuts
    assert [c for c in cuts if c[2] == "chain1"] == [
        ("00:00:00.000", "00:00:06.900", "chain1"),
        ("00:00:07.000", "00:00:09.000", "chain1"),
        ("00:00:09.100", "00:00:09.900", "chain1")], cuts
    assert sum(o - i + 1 for cl in pieces for i, o, _r in cl) == 200, "timeline length must be preserved"


def test_unkeyed_regions_apply_everywhere() -> None:
    body, _ = render_playlist(
        ENTRIES, False, lambda _p: [(20, 40)],
        fps=10.0, pad=0, edge=3, min_entry_frames=0, counter=[0], delete=True)
    assert body.count("<entry") == 4, body  # both clips lost their silence piece


def test_split_entry_skips_edges_and_short_regions() -> None:
    assert split_entry(0, 99, [(1, 5)], pad=0, edge=3) == [(0, 99, False)]      # too close to the edge
    assert split_entry(0, 99, [(40, 42)], pad=5, edge=3) == [(0, 99, False)]    # nothing left after padding


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")

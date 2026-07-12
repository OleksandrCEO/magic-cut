#!/usr/bin/env python3
"""Isolate time regions as separate clips in a kdenlive (MLT) project.

Reads a list of time regions in seconds — usually detected silences, but ANY
region source works (e.g. filler-word / "voiced-but-no-word" intervals from a
transcriber) — and splits the timeline clips so each region becomes its own clip
you can review and delete. Audio and video are split identically and re-linked
via AVSplit groups. Nothing is removed; total timeline length is preserved.

The region list may be either:
  * two floats per line:  "<start_seconds> <end_seconds>"
  * raw ffmpeg silencedetect output (lines with silence_start:/silence_end:)

Assumptions (single-source A/V project, as produced by kdenlive for one clip):
  * audio track  = <playlist id=AUDIO_PLAYLIST> (entries reference an audio chain)
  * video track  = <playlist id=VIDEO_PLAYLIST> (identical in/out list)
  * A/V pairs grouped as AVSplit on track ids GROUP_TRACK_IDS
Adjust the constants below if your project layout differs.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.dom.minidom

AUDIO_PLAYLIST = "playlist2"
VIDEO_PLAYLIST = "playlist4"
GROUP_TRACK_IDS = (1, 2)
DEFAULT_PAD_SECONDS = 1 / 6  # pause kept each side when --pad is omitted; ~5 @30fps, 2 @10fps


def read_fps(text: str) -> float:
    """Read frame rate from the <profile> element (falls back to 30)."""
    num = re.search(r'frame_rate_num="(\d+)"', text)
    den = re.search(r'frame_rate_den="(\d+)"', text)
    if num and den:
        return int(num.group(1)) / int(den.group(1))
    return 30.0


def tc_to_frames(tc: str, fps: float) -> int:
    """'HH:MM:SS.mmm' -> frame index (nearest frame)."""
    h, m, rest = tc.split(":")
    seconds = int(h) * 3600 + int(m) * 60 + float(rest)
    return round(seconds * fps)


def frames_to_tc(f: int, fps: float) -> str:
    total_ms = round(f / fps * 1000)
    h, total_ms = divmod(total_ms, 3600000)
    m, total_ms = divmod(total_ms, 60000)
    s, ms = divmod(total_ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def load_regions(path: str, fps: float) -> list[tuple[int, int]]:
    """Parse a regions file into a list of (start_frame, end_frame)."""
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()

    if "silence_start" in raw or "silence_end" in raw:
        starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", raw)]
        ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", raw)]
        if len(starts) != len(ends):
            sys.exit(f"unbalanced silences: {len(starts)} starts vs {len(ends)} ends")
        pairs = list(zip(starts, ends, strict=True))
    else:
        pairs = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            a, b = line.split()[:2]
            pairs.append((float(a), float(b)))

    return [(round(a * fps), round(b * fps)) for a, b in pairs]


def split_entry(
    in_f: int, out_f: int, regions: list[tuple[int, int]],
    pad: int, edge: int,
) -> list[tuple[int, int, bool]]:
    """Split [in_f, out_f] at contained regions, keeping `pad` frames each side.

    Returns (piece_in, piece_out, is_region) tuples covering the range with no
    gaps/overlaps; the middle `is_region` pieces are the deletable ones.
    """
    inside = sorted(
        (s, e) for s, e in regions
        if s >= in_f + edge and e <= out_f - edge and e > s
    )
    pieces: list[tuple[int, int, bool]] = []
    cur = in_f
    for s, e in inside:
        s_pad = s + pad
        e_pad = e - pad
        if e_pad <= s_pad or s_pad <= cur:  # too short after padding / overlaps
            continue
        pieces.append((cur, s_pad - 1, False))  # keep + leading pause pad
        pieces.append((s_pad, e_pad, True))      # isolated region (deletable)
        cur = e_pad + 1
    pieces.append((cur, out_f, False))
    return pieces


def parse_entries(block: str) -> list[tuple[str, str]]:
    return re.findall(r'<entry in="([^"]+)" out="([^"]+)" producer="[^"]+"', block)


def entry_producer(block: str) -> str:
    m = re.search(r'<entry [^>]*producer="([^"]+)"', block)
    if m is None:
        sys.exit("no <entry> with a producer found in playlist")
    return m.group(1)


def render_playlist(
    entries: list[tuple[str, str]], producer: str, with_audio_prop: bool,
    regions: list[tuple[int, int]], fps: float, pad: int, edge: int,
    min_entry_frames: int,
) -> tuple[str, list[list[tuple[int, int, bool]]]]:
    lines: list[str] = []
    if with_audio_prop:
        lines.append('  <property name="kdenlive:audio_track">1</property>')
    all_pieces: list[list[tuple[int, int, bool]]] = []
    for in_str, out_str in entries:
        in_f, out_f = tc_to_frames(in_str, fps), tc_to_frames(out_str, fps)
        pieces = (
            split_entry(in_f, out_f, regions, pad, edge)
            if out_f - in_f + 1 > min_entry_frames
            else [(in_f, out_f, False)]
        )
        all_pieces.append(pieces)
        for i, (pin, pout, _region) in enumerate(pieces):
            a = in_str if i == 0 else frames_to_tc(pin, fps)
            b = out_str if i == len(pieces) - 1 else frames_to_tc(pout, fps)
            lines.append(f'  <entry in="{a}" out="{b}" producer="{producer}">')
            lines.append('   <property name="kdenlive:id">4</property>')
            lines.append('  </entry>')
    return "\n".join(lines), all_pieces


def build_groups(all_pieces: list[list[tuple[int, int, bool]]]) -> str:
    """One AVSplit group per final clip, keyed by its timeline start position."""
    positions: list[int] = []
    pos = 0
    for pieces in all_pieces:
        for pin, pout, _region in pieces:
            positions.append(pos)
            pos += pout - pin + 1
    ta, tb = GROUP_TRACK_IDS
    groups = [
        "    {\n"
        '        "children": [\n'
        f'            {{\n                "data": "{ta}:{p}:-1",\n'
        '                "leaf": "clip",\n                "type": "Leaf"\n            },\n'
        f'            {{\n                "data": "{tb}:{p}:-1",\n'
        '                "leaf": "clip",\n                "type": "Leaf"\n            }\n'
        '        ],\n        "type": "AVSplit"\n    }'
        for p in positions
    ]
    return "[\n" + ",\n".join(groups) + "\n]\n"


def find_block(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.DOTALL)
    if m is None:
        sys.exit(f"pattern not found: {pattern}")
    return m.group(0)


def replace_playlist(text: str, pid: str, body: str) -> str:
    pat = re.compile(rf'(<playlist id="{pid}">\n).*?(\n </playlist>)', re.DOTALL)
    return pat.sub(lambda m: m.group(1) + body + m.group(2), text, count=1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="path to the .kdenlive file")
    ap.add_argument("--silences", "--regions", dest="regions", required=True,
                    help="regions file (two floats per line, or ffmpeg silencedetect output)")
    out = ap.add_mutually_exclusive_group(required=True)
    out.add_argument("--out", help="write result to this file")
    out.add_argument("--in-place", action="store_true", help="edit the project file in place")
    ap.add_argument("--pad", type=int, default=None,
                    help="frames of pause kept each side (default: ~1/6 s per project fps)")
    ap.add_argument("--edge-margin", type=int, default=3, help="frames kept clear of clip edges (default 3)")
    ap.add_argument("--min-entry", type=float, default=0.0,
                    help="only split clips longer than this many seconds (default 0 = all)")
    ap.add_argument("--fps", type=float, default=0.0, help="override project frame rate")
    args = ap.parse_args()

    with open(args.project, encoding="utf-8") as fh:
        text = fh.read()

    fps = args.fps or read_fps(text)
    pad = args.pad if args.pad is not None else max(1, round(DEFAULT_PAD_SECONDS * fps))
    regions = load_regions(args.regions, fps)
    min_entry_frames = round(args.min_entry * fps)

    a_block = find_block(rf'<playlist id="{AUDIO_PLAYLIST}">.*?</playlist>', text)
    v_block = find_block(rf'<playlist id="{VIDEO_PLAYLIST}">.*?</playlist>', text)
    a_entries, v_entries = parse_entries(a_block), parse_entries(v_block)
    if a_entries != v_entries:
        sys.exit("audio/video entry lists differ — aborting")

    a_body, a_pieces = render_playlist(
        a_entries, entry_producer(a_block), True, regions, fps,
        pad, args.edge_margin, min_entry_frames)
    v_body, v_pieces = render_playlist(
        v_entries, entry_producer(v_block), False, regions, fps,
        pad, args.edge_margin, min_entry_frames)
    if a_pieces != v_pieces:
        sys.exit("audio/video split mismatch — aborting")

    text = replace_playlist(text, AUDIO_PLAYLIST, a_body)
    text = replace_playlist(text, VIDEO_PLAYLIST, v_body)
    groups = build_groups(a_pieces)
    text = re.sub(
        r'(<property name="kdenlive:sequenceproperties.groups">)\[.*?\]\n(\s*</property>)',
        lambda m: m.group(1) + groups + m.group(2), text, count=1, flags=re.DOTALL)

    # invariants + XML validation BEFORE writing anything to disk
    orig_total = sum(tc_to_frames(o, fps) - tc_to_frames(i, fps) + 1 for i, o in a_entries)
    new_total = sum(pout - pin + 1 for pieces in a_pieces for pin, pout, _s in pieces)
    if orig_total != new_total:
        sys.exit(f"ABORT (not written): timeline length changed {orig_total}->{new_total}")
    try:
        xml.dom.minidom.parseString(text.encode("utf-8"))
    except Exception as exc:
        sys.exit(f"ABORT (not written): result is not well-formed XML: {exc}")

    dest = args.project if args.in_place else args.out
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(text)

    n_orig, n_new = len(a_entries), sum(len(p) for p in a_pieces)
    n_region = sum(1 for p in a_pieces for _pin, _pout, s in p if s)
    print(f"{dest}")
    print(f"  clips: {n_orig} -> {n_new}  (+{n_new - n_orig})")
    print(f"  isolated regions: {n_region}")
    print(f"  timeline length {orig_total} frames — unchanged")


if __name__ == "__main__":
    main()

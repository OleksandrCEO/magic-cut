#!/usr/bin/env python3
"""Self-check: the select() expression handed to ffmpeg.

Run: python3 tests/test_media.py   (needs ffmpeg on PATH — it parses the expression for real)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from magcut.media import keep_expr  # noqa: E402


def test_expression_holds_every_region() -> None:
    expr = keep_expr([(0.0, 1.5), (3.25, 4.0)])
    assert "between(t,0.000,1.500)" in expr
    assert "between(t,3.250,4.000)" in expr
    assert keep_expr([(1.0, 2.0)]) == "between(t,1.000,2.000)"


def test_expression_stays_shallow() -> None:
    """Nesting must grow like log2(n): ffmpeg's parser gives up past a depth of 100."""
    depth, worst = 0, 0
    for char in keep_expr([(i, i + 0.5) for i in range(500)]):
        depth += (char == "(") - (char == ")")
        worst = max(worst, depth)
    assert worst < 20, f"nesting depth {worst} is close to the ffmpeg limit"


def test_ffmpeg_accepts_hundreds_of_regions() -> None:
    """The regression itself: 140 regions used to abort with ENOMEM before rendering anything."""
    expr = keep_expr([(i * 2.0, i * 2.0 + 1.0) for i in range(300)])
    with tempfile.NamedTemporaryFile("w", suffix=".filter", encoding="utf-8") as fh:
        fh.write(f"[0:a]aselect='{expr}',asetpts=N/SR/TB[a]")
        fh.flush()
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                               "-i", "sine=d=1", "-filter_complex_script", fh.name,
                               "-map", "[a]", "-f", "null", "-"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr.strip()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")

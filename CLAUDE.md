# magic-cut

Python 3.13, **stdlib only** everywhere except `magcut/transcribe.py` (faster-whisper + CUDA). Packaged with Nix
(`flake.nix` + `package.nix`); runtime deps of the packaged command are ffmpeg + python3 only.

## Architecture

Detection and application are separate halves, joined by one text format:

- `magcut/transcribe.py` — media → `*.words.json`. Expensive GPU pass, run once per video.
- `magcut/regions.py` — `*.words.json` → regions. Cheap, stdlib, re-run freely to re-tune thresholds.
- `kdenlive/silence_cut.py` — regions → split `.kdenlive` timeline (MLT XML, text-level rewriting, no XML DOM building).
  This is the only consumer that exists; rendering cut video with ffmpeg is still manual (README §3).
- `kdenlive/cut-silences.sh` — `ffmpeg silencedetect` + call the engine. The `magcut` command wraps this script.
- `tests/` — plain `assert` self-checks, no framework.

**Region interchange format:** `"<start> <end>"` seconds per line, absolute from media start. Every producer writes it,
every consumer reads it. Adding a new detector means emitting this format — never a new one.

## Commands

```bash
python3 tests/test_regions.py && python3 tests/test_kdenlive.py   # run after any change
nix develop                                                        # only needed for transcribe.py (CUDA)
```

No linter/typechecker is configured. See README.md for user-facing usage and flags.

## Rules

- Keep `magcut/regions.py` and `kdenlive/silence_cut.py` **stdlib-only** — `package.nix` ships them without pip deps.
- Type-annotate everything; docstrings explain *why* a heuristic is shaped that way (measured behaviour, not theory).
- Every non-trivial detection change gets an assert case in the matching `tests/test_*.py`.
- `silence_cut.py` validates XML and timeline length before writing — never bypass that check.
- Track layout is fixed by constants at the top of `silence_cut.py` (`AUDIO_PLAYLIST`, `VIDEO_PLAYLIST`,
  `GROUP_TRACK_IDS`). Other layouts are out of scope; don't add config for them.

## Gotchas

- **Whisper never transcribes hesitation sounds** ("е-е-е"): it stretches the neighbouring word over them. Word-list
  matching cannot find them — only the `--loud` path (loud stretch where no word *starts*) does. `DEFAULT_FILLERS` is
  empty on purpose.
- **Don't use the transcript for pauses** — `ffmpeg silencedetect` finds more and with tighter borders (measured;
  stronger whisper models are *worse* here). Transcript is for fillers and text.
- Word timings carry ±0.1–0.2 s error, compensated by the engine's `--pad`. Never default `--pad` to 0.
- `package.nix` ships only the kdenlive path (`magcut` command + KDE service menu); `transcribe.py` lives in the
  devShell instead, because faster-whisper + CUDA cannot go into a lightweight package.

`docs/claude.md` is a guide on writing this file, not project docs.

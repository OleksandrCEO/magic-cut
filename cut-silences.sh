#!/usr/bin/env bash
#
# Detect silences in a kdenlive project's source media and split the timeline so
# each silence becomes its own deletable clip. Nothing is removed; you review and
# delete in kdenlive.
#
# Needs ffmpeg + python3 on PATH. Packaged form: the `magcut` command from
# default.nix wraps this with those deps (and adds the right-click service menu).
#
# Usage:
#   ./cut-silences.sh PROJECT.kdenlive [options]
#
# Options:
#   --media PATH        source audio/video (default: first media resource in the project)
#   --noise DB          silence threshold in dB, e.g. -20 (default -20)
#   --min-silence SEC   minimum silence duration to cut (default 0.66)
#   --pad FR            frames of pause kept each side (default: ~1/6 s per project fps, i.e. 5 @30fps, 2 @10fps)
#   --min-entry SEC     only split clips longer than this (default 0 = all; use 30 for a fresh full pass)
#   --delete            drop the silences and close the gaps (shortens the timeline) instead of isolating
#   --in-place          edit the project file directly (default)
#   --out FILE          write to a separate file instead
#
# Examples:
#   ./cut-silences.sh workflowy.silence-cut.kdenlive                 # in-place, -20dB
#   ./cut-silences.sh project.kdenlive --noise -25 --min-entry 30 --out cut.kdenlive
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

PROJECT="${1:-}"
[ -n "$PROJECT" ] && [ -f "$PROJECT" ] || { echo "usage: $0 PROJECT.kdenlive [options]" >&2; exit 1; }
shift

MEDIA=""; NOISE="-20"; MINSIL="0.66"; PAD=""; MINENTRY="0"; OUTMODE="--in-place"; OUTFILE=""; DELETE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --media)       MEDIA="$2"; shift 2 ;;
    --noise)       NOISE="$2"; shift 2 ;;
    --min-silence) MINSIL="$2"; shift 2 ;;
    --pad)         PAD="$2"; shift 2 ;;
    --min-entry)   MINENTRY="$2"; shift 2 ;;
    --delete)      DELETE="--delete"; shift ;;
    --in-place)    OUTMODE="--in-place"; shift ;;
    --out)         OUTMODE="--out"; OUTFILE="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

# Resolve source media from the project if not given (first resource that is a real file).
if [ -z "$MEDIA" ]; then
  MEDIA="$(grep -oE '<property name="resource">[^<]+\.(mp4|mkv|mov|m4a|wav|webm|avi)' "$PROJECT" \
             | sed -E 's/.*<property name="resource">//' | head -1 || true)"
fi
[ -n "$MEDIA" ] && [ -f "$MEDIA" ] || { echo "source media not found (pass --media PATH): '$MEDIA'" >&2; exit 1; }

REGIONS="$(mktemp --suffix=.silences)"
trap 'rm -f "$REGIONS"' EXIT

echo "detecting silences: noise=${NOISE}dB min=${MINSIL}s  <-  $MEDIA"
ffmpeg -hide_banner -i "$MEDIA" -af "silencedetect=noise=${NOISE}dB:d=${MINSIL}" -f null - 2>&1 \
  | grep -E "silence_(start|end)" > "$REGIONS" || true
echo "  found $(grep -c silence_end "$REGIONS" || echo 0) silence intervals"

ARGS=(python3 "$SCRIPT_DIR/silence_cut.py" "$PROJECT" --silences "$REGIONS" --min-entry "$MINENTRY")
[ -n "$PAD" ] && ARGS+=(--pad "$PAD")   # else engine uses its fps-aware default
[ -n "$DELETE" ] && ARGS+=(--delete)
if [ "$OUTMODE" = "--out" ]; then ARGS+=(--out "$OUTFILE"); else ARGS+=(--in-place); fi
"${ARGS[@]}"

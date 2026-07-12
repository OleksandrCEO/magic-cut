#!/usr/bin/env bash
#
# Detect voiced "filler" sounds (Е/А hesitations — loud but with no transcribed
# word) and print them as "<start> <end>" seconds, ready for silence_cut.py.
#
# Standalone: uses THIS folder's own flake (faster-whisper + CUDA), completely
# independent of the MagType project. First run compiles the env (slow); after
# that it is cached.
#
# Usage:
#   ./detect-fillers.sh MEDIA [options]           # options pass through to detect_fillers.py
#   ./detect-fillers.sh video.mp4 -o fillers.txt
#   ./detect-fillers.sh video.mp4 --model medium --min-filler 0.4 -o fillers.txt
#
# Then apply the regions to the project with the sibling silence tool:
#   ../silence_cut.py project.kdenlive --silences fillers.txt --in-place
set -euo pipefail

DIR="$(dirname "$(readlink -f "$0")")"
exec nix develop "$DIR" --command python3 "$DIR/detect_fillers.py" "$@"

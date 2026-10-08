#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 3 ]]; then
  echo "Usage: $0 mix.wav bass.wav metrics.txt" >&2
  exit 2
fi
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
: > "$3"
for label in bass mix; do
  if [[ "$label" == bass ]]; then source="$2"; else source="$1"; fi
  ffmpeg -v error -y -stream_loop -1 -i "$source" -t 300 \
    -c:a pcm_s16le "$scratch/${label}_300.wav"
  if [[ "$label" == bass ]]; then durations=(30 60 180 300); else durations=(300); fi
  for seconds in "${durations[@]}"; do
    ffmpeg -v error -y -i "$scratch/${label}_300.wav" -t "$seconds" \
      -c:a pcm_s16le "$scratch/input.wav"
    printf 'source=%s duration=%s ' "$label" "$seconds" >> "$3"
    "$project_dir/build/timestretch" "$scratch/input.wav" "$scratch/output.wav" \
      --speed 0.50 --phase-locking on --transient on --adaptive-time-map on \
      --precise-anchoring on --stereo-coherence on --multiresolution on --chunked on >> "$3"
    rm -f "$scratch/input.wav" "$scratch/output.wav"
  done
done

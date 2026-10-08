#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
directory="$project_dir/results/phase5/off_regression"
mkdir -p "$directory"
: > "$directory/comparison.txt"
for label in mix bass; do
  for speed in 0.75 0.50; do
    id="${speed/./}"
    output="$directory/${label}_${id}_off.wav"
    "$project_dir/build/timestretch" "/Users/taro252/Downloads/${label}.wav" "$output" \
      --speed "$speed" --phase-locking on --transient on \
      --adaptive-time-map on --precise-anchoring on --stereo-coherence on \
      --multiresolution off >/dev/null
    "$project_dir/build/wav_compare" \
      "$project_dir/results/phase4/real/${label}_${id}_phase4.wav" "$output" \
      >> "$directory/comparison.txt"
    rm "$output"
  done
done

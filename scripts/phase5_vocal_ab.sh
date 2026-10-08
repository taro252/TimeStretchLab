#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
source="${1:-/Users/taro252/Downloads/vocal.wav}"
output="${2:-$project_dir/results/phase5/vocal}"
prefix="${3:-vocal}"
mkdir -p "$output"
ffmpeg -v error -y -ss 60 -i "$source" -t 30 \
  -c:a pcm_f32le "$output/input_30s.wav"
: > "$output/processing_metrics.txt"
for speed in 0.75 0.50; do
  id="${speed/./}"
  for phase in 4 5; do
    options=()
    if [[ "$phase" == 5 ]]; then options+=(--multiresolution on)
    else options+=(--multiresolution off); fi
    "$project_dir/build/timestretch" "$output/input_30s.wav" \
      "$output/${prefix}_${id}_phase${phase}.wav" --speed "$speed" --phase-locking on \
      --transient on --adaptive-time-map on --precise-anchoring on \
      --stereo-coherence on "${options[@]}" >> "$output/processing_metrics.txt"
  done
done
"$project_dir/build/wav_metrics" "$output"/"${prefix}"_*_phase*.wav > "$output/stereo_metrics.txt"
: > "$output/spectral_metrics.txt"
for speed in 0.75 0.50; do
  id="${speed/./}"
  for phase in 4 5; do
    "$project_dir/build/stereo_spectral_metrics" "$output/input_30s.wav" \
      "$output/${prefix}_${id}_phase${phase}.wav" "$speed" \
      >> "$output/spectral_metrics.txt"
  done
done

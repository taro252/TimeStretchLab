#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 && $# != 3 ]]; then
  echo "Usage: $0 mix.wav bass.wav [output_dir]" >&2
  exit 2
fi
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
tool="$project_dir/build/timestretch"
output_dir="${3:-$project_dir/results/phase35/real}"
if [[ ! -x "$tool" ]]; then
  echo "Build timestretch first: cmake --build build" >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg is required for same-gain audition excerpts" >&2
  exit 1
fi
mkdir -p "$output_dir/audition"
printf 'category,speed,phase,input,output\n' > "$output_dir/manifest.csv"
: > "$output_dir/processing_metrics.txt"
inputs=("$1" "$2")
labels=(mix bass)
for index in "${!inputs[@]}"; do
  input="${inputs[index]}"
  label="${labels[index]}"
  if [[ ! -f "$input" ]]; then echo "Missing input WAV: $input" >&2; exit 1; fi
  for speed in 0.75 0.50; do
    speed_label="${speed/./}"
    if [[ "$speed" == 0.75 ]]; then excerpt_start=80; excerpt_duration=40
    else excerpt_start=120; excerpt_duration=60; fi
    phase35="$output_dir/${label}_${speed_label}_phase35.wav"
    "$tool" "$input" "$phase35" --speed "$speed" --phase-locking on \
      --transient on --adaptive-time-map on \
      >> "$output_dir/processing_metrics.txt"
    phase2="$project_dir/results/phase2/real/stems/${label}_${speed_label}_on.wav"
    phase3="$project_dir/results/phase3/real/${label}_${speed_label}_on.wav"
    for phase in 2 3 35; do
      case "$phase" in
        2) source="$phase2" ;;
        3) source="$phase3" ;;
        35) source="$phase35" ;;
      esac
      if [[ ! -f "$source" ]]; then echo "Missing AB baseline: $source" >&2; exit 1; fi
      printf '%s,%s,%s,%s,%s\n' "$label" "$speed" "$phase" "$input" "$source" \
        >> "$output_dir/manifest.csv"
      ffmpeg -v error -y -ss "$excerpt_start" -i "$source" -t "$excerpt_duration" \
        -af volume=0.4 -c:a pcm_f32le \
        "$output_dir/audition/${label}_${speed_label}_phase${phase}.wav"
    done
  done
done

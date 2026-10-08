#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 && $# != 3 ]]; then
  echo "Usage: $0 mix.wav bass.wav [output_dir]" >&2
  exit 2
fi
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
tool="$project_dir/build/timestretch"
output_dir="${3:-$project_dir/results/phase37/real}"
if [[ ! -x "$tool" ]]; then echo "Build timestretch first" >&2; exit 1; fi
if ! command -v ffmpeg >/dev/null; then echo "ffmpeg is required" >&2; exit 1; fi
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
    phase37="$output_dir/${label}_${speed_label}_phase37.wav"
    "$tool" "$input" "$phase37" --speed "$speed" --phase-locking on \
      --transient on --adaptive-time-map on --precise-anchoring on \
      >> "$output_dir/processing_metrics.txt"
    phase35="$project_dir/results/phase35/real/${label}_${speed_label}_phase35.wav"
    for phase in 35 37; do
      case "$phase" in
        35) source="$phase35" ;;
        37) source="$phase37" ;;
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

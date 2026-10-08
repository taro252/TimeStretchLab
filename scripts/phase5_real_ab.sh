#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 && $# != 3 ]]; then
  echo "Usage: $0 mix.wav bass.wav [output_dir]" >&2; exit 2
fi
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
output_dir="${3:-$project_dir/results/phase5/real}"
tool="$project_dir/build/timestretch"
if [[ ! -x "$tool" ]]; then echo "Build timestretch first" >&2; exit 1; fi
if ! command -v ffmpeg >/dev/null; then echo "ffmpeg is required" >&2; exit 1; fi
mkdir -p "$output_dir/audition"
printf 'category,speed,phase,input,output\n' > "$output_dir/manifest.csv"
: > "$output_dir/processing_metrics.txt"
inputs=("$1" "$2")
labels=(mix bass)
for index in "${!inputs[@]}"; do
  input="${inputs[index]}"; label="${labels[index]}"
  if [[ ! -f "$input" ]]; then echo "Missing input WAV: $input" >&2; exit 1; fi
  for speed in 0.75 0.50; do
    id="${speed/./}"
    if [[ "$speed" == 0.75 ]]; then excerpt_start=80; excerpt_duration=40
    else excerpt_start=120; excerpt_duration=60; fi
    phase4="$project_dir/results/phase4/real/${label}_${id}_phase4.wav"
    phase5="$output_dir/${label}_${id}_phase5.wav"
    if [[ ! -f "$phase4" ]]; then echo "Missing Phase 4 baseline: $phase4" >&2; exit 1; fi
    "$tool" "$input" "$phase5" --speed "$speed" --phase-locking on \
      --transient on --adaptive-time-map on --precise-anchoring on \
      --stereo-coherence on --multiresolution on >> "$output_dir/processing_metrics.txt"
    for phase in 4 5; do
      if [[ "$phase" == 4 ]]; then source="$phase4"; else source="$phase5"; fi
      printf '%s,%s,%s,%s,%s\n' "$label" "$speed" "$phase" "$input" "$source" \
        >> "$output_dir/manifest.csv"
      ffmpeg -v error -y -ss "$excerpt_start" -i "$source" -t "$excerpt_duration" \
        -af volume=0.4 -c:a pcm_f32le \
        "$output_dir/audition/${label}_${id}_phase${phase}.wav"
    done
  done
done

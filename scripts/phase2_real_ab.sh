#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 4 && $# != 5 && $# != 6 && $# != 7 ]]; then
  echo "Usage: $0 mix.wav bass.wav guitar.wav piano.wav vocal.wav drums.wav [output_dir]" >&2
  echo "   or: $0 bass.wav vocal.wav instrument.wav full_mix.wav [output_dir]" >&2
  exit 2
fi

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
tool="$project_dir/build/timestretch"
if [[ $# == 6 || $# == 7 ]]; then
  inputs=("$1" "$2" "$3" "$4" "$5" "$6")
  labels=(mix bass guitar piano vocal drums)
  output_dir="${7:-$project_dir/results/phase2/real/stems}"
else
  inputs=("$1" "$2" "$3" "$4")
  labels=(bass vocal instrument full_mix)
  output_dir="${5:-$project_dir/results/phase2/real}"
fi
if [[ ! -x "$tool" ]]; then
  echo "Build timestretch first: cmake --build build" >&2
  exit 1
fi

for input in "${inputs[@]}"; do
  if [[ ! -f "$input" ]]; then
    echo "Missing input WAV: $input" >&2
    exit 1
  fi
done
mkdir -p "$output_dir"
printf 'category,speed,phase_locking,input,output\n' > "$output_dir/manifest.csv"
: > "$output_dir/processing_metrics.txt"
for index in "${!inputs[@]}"; do
  input="${inputs[index]}"
  label="${labels[index]}"
  for speed in 0.75 0.50; do
    speed_label="${speed/./}"
    for locking in off on; do
      output="$output_dir/${label}_${speed_label}_${locking}.wav"
      printf '%s speed=%s phase_locking=%s\n' "$label" "$speed" "$locking" \
        >> "$output_dir/processing_metrics.txt"
      "$tool" "$input" "$output" --speed "$speed" --phase-locking "$locking" \
        >> "$output_dir/processing_metrics.txt"
      printf '%s,%s,%s,%s,%s\n' "$label" "$speed" "$locking" "$input" "$output" \
        >> "$output_dir/manifest.csv"
    done
  done
done

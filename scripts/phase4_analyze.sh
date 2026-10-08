#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
real="$project_dir/results/phase4/real"
baseline="$project_dir/results/phase37/real"
tool="$project_dir/build"
"$tool/wav_metrics" \
  /Users/taro252/Downloads/mix.wav /Users/taro252/Downloads/bass.wav \
  "$baseline/mix_075_phase37.wav" "$real/mix_075_phase4.wav" \
  "$baseline/mix_050_phase37.wav" "$real/mix_050_phase4.wav" \
  "$baseline/bass_075_phase37.wav" "$real/bass_075_phase4.wav" \
  "$baseline/bass_050_phase37.wav" "$real/bass_050_phase4.wav" \
  > "$real/stereo_metrics.txt"
: > "$real/spectral_metrics.txt"
for label in mix bass; do
  for speed in 0.75 0.50; do
    id="${speed/./}"
    for phase in 37 4; do
      if [[ "$phase" == 37 ]]; then output="$baseline/${label}_${id}_phase37.wav"
      else output="$real/${label}_${id}_phase4.wav"; fi
      "$tool/stereo_spectral_metrics" "/Users/taro252/Downloads/${label}.wav" \
        "$output" "$speed" >> "$real/spectral_metrics.txt"
    done
  done
done
"$tool/bass_pitch_metrics" /Users/taro252/Downloads/bass.wav \
  "$baseline/bass_075_phase37.wav" "$real/bass_075_phase4.wav" \
  "$baseline/bass_050_phase37.wav" "$real/bass_050_phase4.wav" \
  > "$real/pitch_metrics.txt"
"$tool/wav_metrics" "$real"/audition/*.wav > "$real/audition_metrics.txt"

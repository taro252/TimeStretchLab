#!/usr/bin/env python3
"""Aggregate exact synthesis-frame phase traces by listening region."""
import csv
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / 'results/phase33'
REGIONS = {
    'drums_attack': ('drums', 48000, 3.77, 4.02),
    'drums_tail': ('drums', 48000, 4.05, 4.35),
    'mix_busy': ('mix', 44100, 2.9, 4.2),
    'mix_quiet': ('mix', 44100, 4.2, 4.8),
    'pink_tail': ('pink_decay', 48000, 0.92, 1.28),
    'single_drum_attack': ('single_drum', 48000, 0.75, 0.95),
    'single_drum_tail': ('single_drum', 48000, 0.92, 1.28),
}


def median(rows, column):
    return float(np.median([float(row[column]) for row in rows])) if rows else ''


def main():
    summary = []
    for region, (source, rate, begin, end) in REGIONS.items():
        for mode in ('baseline', 'no_lock', 'no_reset', 'no_propagation'):
            for resolution in ('low', 'mid', 'high'):
                path = OUT / 'trace' / f'{source}_{mode}_025' / f'{resolution}.csv'
                with path.open(newline='') as stream:
                    all_rows = list(csv.DictReader(stream))
                selected = [row for row in all_rows
                            if begin * rate <= int(row['inputSample']) < end * rate]
                valid = [row for row in selected if int(row['validBins']) > 0]
                summary.append(dict(region=region, source=source, mode=mode,
                                    resolution=resolution, frames=len(selected),
                                    reset_frames=sum(int(row['reset']) for row in selected),
                                    valid_frames=len(valid),
                                    synthesis_hop_median=median(selected, 'synthesisHop'),
                                    analysis_phase_residual_median=median(valid, 'analysisPhaseResidualRms'),
                                    output_phase_residual_median=median(valid, 'outputPhaseResidualRms'),
                                    peak_phase_residual_median=median(valid, 'peakOutputPhaseResidualRms'),
                                    owner_change_fraction_median=median(valid, 'ownerChangeFraction'),
                                    owner_changed_phase_residual_median=median(valid, 'changedOwnerResidualRms'),
                                    owner_stable_phase_residual_median=median(valid, 'stableOwnerResidualRms')))
    with (OUT / 'phase_summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(summary)
    print(f'{len(summary)} phase-region summaries')


if __name__ == '__main__':
    main()

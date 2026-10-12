#!/usr/bin/env python3
"""Event-position analysis without changing Phase 37 PCM or detector events."""
import csv
import statistics
import subprocess

import numpy as np

from phase32_study import read
from phase37_study import ROOT, SOURCES
from phase38_burst_diagnostic import OUT, event_rows, map_points, mono_energy, energy

SPEEDS = ('1.10', '1.25', '1.50', '1.75', '2.00')
SOURCES_TO_MEASURE = ('mix', 'drums', 'vocal', 'guitar', 'bass')


def local_peak(power, center, radius):
    first = max(0, round(center - radius))
    last = min(len(power), round(center + radius))
    if last <= first:
        return first, 0.
    index = first + int(np.argmax(power[first:last]))
    return index, float(np.sqrt(power[index]))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    anchors = []
    for source in SOURCES_TO_MEASURE:
        path = SOURCES[source]
        rate, original = read(path)
        input_power = mono_energy(original)
        for speed in SPEEDS:
            for mode in 'AB':
                x, y = map_points(path, speed, mode)
                events = event_rows(path, speed, mode)
                rate, output = read(ROOT / 'results/phase37/raw' /
                                    f'{source}_{mode}_{speed.replace(".", "")}.wav')
                output_power = mono_energy(output)
                anchors.append(dict(source=source, speed=speed, mode=mode,
                    events=len(events), confident=sum(e['anchor_confident']=='1' for e in events),
                    fallback=sum(e['anchor_confident']=='0' for e in events),
                    max_peak_anchor_error=max((abs(int(e['mapped_peak_sample'])-
                        int(e['ideal_output_sample'])) for e in events), default=0)))
                for event_id, event in enumerate(events):
                    input_frame = int(event['peak_frame']) * 1024
                    input_peak, input_level = local_peak(input_power, input_frame,
                                                          rate * .035)
                    ideal = input_peak / float(speed)
                    mapped = float(np.interp(input_peak, x, y))
                    # Two analyses: a naive global-ratio location and the
                    # position corresponding to the actual input crest.
                    observed, output_level = local_peak(output_power, mapped,
                                                          rate * .04)
                    if observed < rate * .06 or observed + rate * .06 >= len(output):
                        continue
                    rows.append(dict(source=source, speed=speed, mode=mode,
                        event=event_id, anchor_confident=event['anchor_confident'],
                        event_input_peak_frame=event['peak_frame'],
                        actual_input_crest=input_peak,
                        ideal_output_crest=round(ideal),
                        mapped_output_crest=round(mapped),
                        observed_output_crest=observed,
                        input_crest_level=input_level,
                        output_crest_level=output_level,
                        observed_minus_ideal_ms=(observed-ideal)*1000/rate,
                        observed_minus_mapped_ms=(observed-mapped)*1000/rate,
                        mapped_minus_ideal_ms=(mapped-ideal)*1000/rate,
                        mapped_20ms_energy=energy(output_power,mapped,20,rate),
                        observed_20ms_energy=energy(output_power,observed,20,rate),
                        pre_echo_5to40ms_energy=energy(output_power,
                            observed-rate*.04,35,rate),
                        post_50ms_energy=energy(output_power,observed,50,rate)))
    for name, values in (('real_events.csv', rows), ('real_anchors.csv', anchors)):
        with (OUT/name).open('w', newline='') as file:
            writer=csv.DictWriter(file, fieldnames=values[0], lineterminator='\n')
            writer.writeheader(); writer.writerows(values)
    summaries=[]
    for source in SOURCES_TO_MEASURE:
        for speed in SPEEDS:
            for mode in 'AB':
                sample=[r for r in rows if r['source']==source and
                        r['speed']==speed and r['mode']==mode]
                summaries.append(dict(source=source,speed=speed,mode=mode,
                    events=len(sample),
                    median_abs_ideal_offset_ms=statistics.median(abs(
                        r['observed_minus_ideal_ms']) for r in sample),
                    median_abs_map_offset_ms=statistics.median(abs(
                        r['observed_minus_mapped_ms']) for r in sample),
                    median_peak=statistics.median(r['output_crest_level'] for r in sample),
                    median_mapped_20ms_energy=statistics.median(
                        r['mapped_20ms_energy'] for r in sample),
                    median_pre_echo_5to40ms_energy=statistics.median(
                        r['pre_echo_5to40ms_energy'] for r in sample)))
    with (OUT/'real_summary.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=summaries[0],lineterminator='\n')
        writer.writeheader();writer.writerows(summaries)
    print(f'{len(rows)} real event positions, {len(anchors)} anchor summaries')


if __name__ == '__main__':
    main()

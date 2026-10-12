#!/usr/bin/env python3
"""PCM safety, stereo and fixed-gain audition for the Phase 40 planners."""
import csv
import hashlib
from pathlib import Path

import numpy as np
from phase32_study import read, wav

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase40"
AUDITION = OUT / "audition_guarded"
AUDITION.mkdir(parents=True, exist_ok=True)


def stereo(audio):
    if audio.ndim!=2 or audio.shape[1]!=2:
        return float("nan"), float("nan")
    left = audio[:, 0].astype(np.float64)
    right = audio[:, 1].astype(np.float64)
    mid = (left+right)*.5
    side = (left-right)*.5
    ratio = float(np.sqrt(np.mean(side*side))/max(np.sqrt(np.mean(mid*mid)), 1e-20))
    correlation = float(np.corrcoef(left, right)[0, 1]) if left.std() and right.std() else float("nan")
    return ratio, correlation


rows = []
for case in csv.DictReader((OUT / "comparison.csv").open(newline="")):
    if case["reference"]!="match":
        continue
    source, initial, target, planner = (case[key] for key in ("source", "from", "to", "planner"))
    name = f"{source}_{initial.replace('.', '')}_to_{target.replace('.', '')}_{planner}"
    rate, audio = read(OUT / f"{name}.wav")
    if audio.ndim==1:
        audio=audio[:, None]
    initial_audio = OUT / f"{source}_{initial.replace('.', '')}_fixed.wav"
    _, previous = read(initial_audio)
    if previous.ndim==1:
        previous=previous[:, None]
    reported_applied = int(case["applied_output"])
    applied = min(max(1,reported_applied),len(audio)-1)
    before = audio[max(0, applied-rate//10):applied]
    after = audio[applied:min(len(audio), applied+rate//10)]
    boundary = float(np.max(np.abs(audio[applied]-audio[applied-1])))
    region = audio[max(0,applied-rate//5):min(len(audio),applied+rate//5)]
    differences = np.abs(np.diff(region.astype(np.float64),axis=0))
    ratio_before, corr_before = stereo(before)
    ratio_after, corr_after = stereo(after)
    rows.append(dict(source=source, **{"from":initial}, to=target, planner=planner,
                     frames=len(audio), finite=int(np.isfinite(audio).all()),
                     applied_after_eos=int(reported_applied>=len(audio)),
                     peak=float(np.max(np.abs(audio))),
                     published_prefix_equal=int(np.array_equal(
                         audio[:int(case["published"])],
                         previous[:int(case["published"])])),
                     boundary_derivative=boundary,
                     local_derivative_p99=float(np.percentile(differences,99)),
                     side_mid_before=ratio_before, side_mid_after=ratio_after,
                     correlation_before=corr_before, correlation_after=corr_after))

with (OUT / "diagnostics.csv").open("w",newline="") as file:
    writer=csv.DictWriter(file,fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

blind = []
for source in ("mix", "drums", "vocal"):
    for initial,target in (("1.00", "2.00"),("0.40", "2.00")):
        identity = f"{source}_{initial.replace('.', '')}_to_{target.replace('.', '')}"
        pair = []
        for planner in "AC":
            rate, audio = read(OUT / f"{identity}_{planner}.wav")
            pair.append(np.atleast_2d(audio) if audio.ndim==2 else audio[:,None])
        comparison = next(case for case in csv.DictReader(
            (OUT / "comparison.csv").open(newline="")) if
            case["source"]==source and case["from"]==initial and
            case["to"]==target and case["planner"]=="C")
        request = int(comparison["requested_output"])
        start = max(0,request-rate//2)
        stop = min(*(len(audio) for audio in pair),request+rate*4)
        labels = ("A", "B") if hashlib.sha256(identity.encode()).digest()[0]&1 else ("B", "A")
        for planner,audio,label in zip("AC",pair,labels):
            path = AUDITION / f"{identity}_{label}.wav"
            wav(path,np.asarray(audio[start:stop]*np.float32(.40),dtype=np.float32),rate)
            blind.append(dict(set=identity,display=label,planner=planner,
                              fixed_gain=0.40,input_source=source,
                              output_start=start,output_end=stop))

with (OUT / "blind_key_guarded.csv").open("w",newline="") as file:
    writer=csv.DictWriter(file,fieldnames=list(blind[0]))
    writer.writeheader()
    writer.writerows(blind)
print(len(rows),"diagnostics;",len(blind),"fixed-gain audition clips")

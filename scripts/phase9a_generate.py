#!/usr/bin/env python3
"""Generate fixed mono Phase 9A source, unity, and Phase 5.3/9A A/B WAVs."""
import csv
import argparse
import pathlib
import subprocess
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase9a"
SOURCE = ROOT / "results/phase7"
BUILD = ROOT / "build"
RATE = 48000
SECTIONS = [f"{voice}_{index}" for voice in ("female", "male") for index in (1, 2, 3)]

def run(args, input_bytes=None):
    return subprocess.run(args, input=input_bytes, capture_output=True,
                          text=input_bytes is None, check=True).stdout

def fields(line):
    return dict(item.split("=", 1) for item in line.strip().split())

def create_sources():
    OUT.mkdir(parents=True, exist_ok=True)
    for section in SECTIONS:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(SOURCE / f"{section}_input.wav"),
             "-ac", "1", "-c:a", "pcm_f32le", str(OUT / f"{section}_input.wav")])
    n=RATE*6
    t=np.arange(n)/RATE
    phase=np.cumsum(2*np.pi*165*np.exp2(16*np.sin(2*np.pi*5.5*t)/1200)/RATE)
    vowel=np.zeros(n)
    for harmonic in range(1,20):
        frequency=165*harmonic
        formant=(np.exp(-0.5*((frequency-(650+100*t/6))/210)**2)+
                 0.7*np.exp(-0.5*((frequency-1300)/300)**2)+0.1)/harmonic
        vowel+=0.13*formant*np.sin(harmonic*phase)
    rng=np.random.default_rng(9)
    for name, signal in (("pure_vowel", vowel),
                         ("breathy_vowel", vowel+0.015*rng.normal(size=n))):
        raw=np.asarray(signal,dtype="<f4").tobytes()
        run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE),
             "-ac", "1", "-i", "-", "-c:a", "pcm_f32le",
             str(OUT / f"{name}_input.wav")],raw)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--stage",choices=("unity","stretch"),required=True)
    args=parser.parse_args()
    if args.stage=="unity":create_sources()
    unity=[]
    all_names=["pure_vowel", "breathy_vowel", *SECTIONS]
    for name in all_names if args.stage=="unity" else ():
        source=OUT/f"{name}_input.wav"
        output=OUT/f"{name}_100_phase9a.wav"
        diagnostics=OUT/"diagnostics"/f"{name}_100" if name in (
            "pure_vowel", "breathy_vowel", "female_1", "male_1") else None
        cmd=[str(BUILD/"sinusoidal_residual_stretch"),str(source),str(output),
             "--speed","1.0"]
        if diagnostics:cmd += ["--diagnostics",str(diagnostics)]
        detail=fields(run(cmd))
        unity.append({"name":name,"input":str(source),"output":str(output),**detail})
        print("unity",name,detail,flush=True)
    if args.stage=="unity":
        with (OUT/"unity_manifest.csv").open("w",newline="") as file:
            writer=csv.DictWriter(file,fieldnames=unity[0].keys(),lineterminator="\n")
            writer.writeheader();writer.writerows(unity)
        return
    rows=[]
    for name in all_names:
        source=OUT/f"{name}_input.wav"
        for speed,code in ((0.75,"075"),(0.50,"050")):
            baseline=OUT/f"{name}_{code}_phase53.wav"
            pv=[str(BUILD/"timestretch"),str(source),str(baseline),
                "--speed",str(speed),"--phase-locking","on", "--partial-tracking","off",
                "--pvsola","off", "--transient","on", "--adaptive-time-map","on",
                "--precise-anchoring","on", "--stereo-coherence","off",
                "--quality","high", "--chunked","on"]
            baseline_detail=fields(run(pv))
            output=OUT/f"{name}_{code}_phase9a.wav"
            diagnostics=OUT/"diagnostics"/f"{name}_{code}" if name in (
                "pure_vowel","breathy_vowel","female_1","male_1") else None
            cmd=[str(BUILD/"sinusoidal_residual_stretch"),str(source),str(output),
                 "--speed",str(speed)]
            if diagnostics:cmd += ["--diagnostics",str(diagnostics)]
            detail=fields(run(cmd))
            rows.append({"name":name,"speed":speed,"input":str(source),
                         "phase53":str(baseline),"phase9a":str(output),
                         "phase53CpuSeconds":baseline_detail.get("cpu_seconds",""),
                         "phase53PeakRssBytes":baseline_detail.get("max_rss_bytes",""),
                         **detail})
            print(name,speed,detail,flush=True)
    with (OUT/"manifest.csv").open("w",newline="") as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator="\n")
        writer.writeheader();writer.writerows(rows)

if __name__=="__main__":main()

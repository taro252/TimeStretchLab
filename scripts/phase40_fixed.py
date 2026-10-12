#!/usr/bin/env python3
"""Recheck all frozen fixed-speed references without modifying earlier results."""
import csv
import hashlib
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"results/phase40"
rows=[]
for reference in csv.DictReader((ROOT/"results/phase39/fixed.csv").open(newline="")):
    source,speed=reference["source"],reference["speed"]
    key=round(float(speed)*100)
    source_path=(ROOT/f"results/phase12/golden/input/{source}.wav" if
                 key in (50,60,70,75,80) else
                 ROOT/f"results/phase31/input/{source}.wav")
    output=OUT/"fixed"/f"{source}_{key:03d}.wav"
    output.parent.mkdir(exist_ok=True)
    run=subprocess.run([str(ROOT/"build/phase39_sim"),str(source_path),str(output),
                        speed,"-","512",str(OUT/"plans"/f"fixed_{source}_{key:03d}.csv"),
                        "2048","C"],cwd=ROOT,text=True,capture_output=True)
    h=hashlib.sha256(output.read_bytes()).hexdigest() if run.returncode==0 else ""
    rows.append(dict(source=source,speed=speed,
                     result="match" if h==reference["reference_sha256"] else "mismatch",
                     output_sha256=h,reference_sha256=reference["reference_sha256"],
                     error=run.stderr.strip()))
    print(source,speed,rows[-1]["result"],flush=True)
with (OUT/"fixed.csv").open("w",newline="") as file:
    writer=csv.DictWriter(file,fieldnames=list(rows[0]))
    writer.writeheader();writer.writerows(rows)

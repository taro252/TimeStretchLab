#!/usr/bin/env python3
"""Write equal-gain, unclipped A/B/C audition WAVs; raw DSP stays untouched."""
import csv
import hashlib
from pathlib import Path
import sys

import numpy as np


GAIN=0.5


def hash_file(path):
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda:source.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def copy_with_gain(source,destination):
    size=source.stat().st_size
    if size<44 or (size-44)%8:
        raise ValueError(f"Expected stereo float32 WAV: {source}")
    samples=(size-44)//4
    with source.open("rb") as input_file,destination.open("wb") as output_file:
        header=input_file.read(44)
        if header[:4]!=b"RIFF" or header[8:12]!=b"WAVE":
            raise ValueError(f"Invalid RIFF header: {source}")
        output_file.write(header)
        output_file.truncate(size)
    raw=np.memmap(source,dtype="<f4",mode="r",offset=44,shape=(samples,))
    output=np.memmap(destination,dtype="<f4",mode="r+",offset=44,shape=(samples,))
    for start in range(0,samples,262144):
        stop=min(start+262144,samples)
        output[start:stop]=raw[start:stop]*np.float32(GAIN)
    output.flush()
    return float(np.max(np.abs(raw))),float(np.max(np.abs(output)))


def main():
    root=Path(sys.argv[1]).resolve()
    phase23=root/"results/phase23"
    golden=root/"results/phase12/golden/raw"
    rows=[]
    for name in ("mix","vocal","bass","drums","guitar","click","sine"):
        destination=phase23/"audition"/name
        destination.mkdir(parents=True,exist_ok=True)
        for label,mode in (("A_fixed_050","050"),("B_fixed_075","075"),
                           ("C_switch","switch")):
            if mode=="switch":
                source=phase23/"raw"/f"{name}_switch.wav"
            elif name in ("click","sine"):
                source=phase23/"baseline"/f"{name}_{mode}.wav"
            else:
                source=golden/f"{name}_{mode}.wav"
            output=destination/f"{label}.wav"
            output.unlink(missing_ok=True)
            rawPeak,auditionPeak=copy_with_gain(source,output)
            if auditionPeak>=1.0:
                raise RuntimeError(f"Audition clip risk: {output}")
            rows.append((name,label,str(source.relative_to(root)),GAIN,rawPeak,
                         auditionPeak,hash_file(output)))
        if name in ("drums","click"):
            source=phase23/"raw"/f"{name}_switch_on.wav"
            output=destination/"C_switch_on.wav"
            output.unlink(missing_ok=True)
            rawPeak,auditionPeak=copy_with_gain(source,output)
            if auditionPeak>=1.0:
                raise RuntimeError(f"Audition clip risk: {output}")
            rows.append((name,"C_switch_on",str(source.relative_to(root)),GAIN,
                         rawPeak,auditionPeak,hash_file(output)))
    with (phase23/"audition_manifest.csv").open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("source","file","raw_source","gain","raw_peak",
                         "audition_peak","sha256"))
        writer.writerows(rows)
    print(f"Created {len(rows)} equal-gain audition WAVs; peak < 1.0")


if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""Fast, dependency-free fixed/variable Phase 23 DSP regression."""
import array
import filecmp
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def run(args):
    output=subprocess.run(args,check=True,text=True,capture_output=True).stdout
    return dict(line.split("=",1) for line in output.splitlines() if "=" in line)


def make_sine(path):
    samples=array.array("f")
    for i in range(48000*3):
        phase=2*math.pi*437.3*i/48000
        samples.extend((0.2*math.sin(phase),0.2*math.sin(phase+math.pi/4)))
    payload=samples.tobytes()
    with path.open("wb") as output:
        output.write(b"RIFF"+struct.pack("<I",36+len(payload))+b"WAVE")
        output.write(b"fmt "+struct.pack("<IHHIIHH",16,3,2,48000,48000*8,8,32))
        output.write(b"data"+struct.pack("<I",len(payload)))
        output.write(payload)


def main():
    phase13,phase23=(str(Path(arg).resolve()) for arg in sys.argv[1:3])
    with tempfile.TemporaryDirectory(prefix="phase23_smoke_") as temp:
        directory=Path(temp)
        source=directory/"sine.wav"
        make_sine(source)
        for mode,speed in (("050","0.50"),("075","0.75")):
            golden=directory/f"golden_{mode}.wav"
            candidate=directory/f"candidate_{mode}.wav"
            run([phase13,str(source),str(golden),"8192",speed])
            run([phase23,str(source),str(candidate),mode,
                 str(directory/f"{mode}.csv")])
            if not filecmp.cmp(golden,candidate,shallow=False):
                raise RuntimeError(f"Fixed {mode} differs from Phase 13")
        variable=directory/"variable.wav"
        info=run([phase23,str(source),str(variable),"switch",
                  str(directory/"switch.csv"),"72000","8192"])
        alternative=directory/"variable_16384.wav"
        run([phase23,str(source),str(alternative),"switch",
             str(directory/"switch_16384.csv"),"72000","16384"])
        if not filecmp.cmp(variable,alternative,shallow=False):
            raise RuntimeError("Variable output depends on WAV block size")
        committed=int(info["committed_output"])
        with variable.open("rb") as left,(directory/"golden_050.wav").open("rb") as right:
            left.seek(44)
            right.seek(44)
            if left.read(committed*8)!=right.read(committed*8):
                raise RuntimeError("Published audio prefix changed")
        with variable.open("rb") as stream:
            stream.seek(44)
            values=array.array("f")
            values.frombytes(stream.read())
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError("Non-finite variable DSP sample")
        print("Phase 23: 2/2 fixed WAVs byte identical; committed prefix exact; "
              "8192/16384 blocks identical; all samples finite")


if __name__=="__main__":
    main()

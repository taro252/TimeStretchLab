"""Serial frozen oracle, then one native host; run from the repository root.

Build the host separately using the final native-test library/configuration
and phase61_callback_heap_probe. This recipe deliberately does not build source,
re-freeze the reference, change CMake, or run two audio hosts concurrently.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
import struct
import subprocess

FROZEN_SHA = "de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def wav_format(path):
    # Small RIFF metadata reader also accepts IEEE Float32 and extensible WAV.
    with path.open("rb") as stream:
        riff, _, wave_id = struct.unpack("<4sI4s", stream.read(12))
        require(riff == b"RIFF" and wave_id == b"WAVE", "RIFF WAVE required")
        fmt = data_bytes = None
        while True:
            block = stream.read(8)
            if not block:
                break
            require(len(block) == 8, "truncated WAV chunk")
            label, size = struct.unpack("<4sI", block)
            if label == b"fmt ":
                require(size >= 16, "short WAV fmt")
                fmt = struct.unpack("<HHIIHH", stream.read(16))
                stream.seek(size - 16, 1)
            elif label == b"data":
                require(data_bytes is None, "multiple data chunks unsupported")
                data_bytes = size
                stream.seek(size, 1)
            else:
                stream.seek(size, 1)
            stream.seek(size % 2, 1)
        require(fmt is not None and data_bytes is not None, "missing WAV metadata")
        _, channels, rate, _, alignment, bits = fmt
        require(channels in (1, 2) and rate in (44100, 48000), "format: mono/stereo 44.1/48 kHz")
        require(alignment and data_bytes % alignment == 0, "non-integral WAV frames")
        return {"channels": channels, "rate": rate, "bits": bits, "frames": data_bytes // alignment}


def run(command, logfile, timeout):
    with logfile.open("x") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    require(result.returncode == 0, f"exit={result.returncode}: {logfile}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--oracle-manifest", type=Path, required=True,
                        help="existing frozen manifest; retained, never rewritten")
    parser.add_argument("--preset", choices=("candidate", "baseline"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    host, source, oracle, manifest_path, output = [p.resolve() for p in
        (args.host, args.input, args.oracle, args.oracle_manifest, args.output)]
    require(sha(oracle) == FROZEN_SHA, "frozen binary SHA differs")
    frozen_manifest = json.loads(manifest_path.read_text())
    require(frozen_manifest["binary_sha256"] == FROZEN_SHA, "frozen manifest binary SHA differs")
    # Check actual archived source bytes. Never replace the frozen DSP with
    # current product DSP or re-freeze a differently linked binary.
    require(frozen_manifest.get("source_sha256") and frozen_manifest.get("host_source_sha256"),
            "frozen manifest lacks source identities")
    compile_command = next(row["command"] for row in frozen_manifest["commands"]
                           if row["name"] == "compile")
    legacy_source = Path(compile_command[compile_command.index("-c") + 1])
    require(legacy_source.is_file() and sha(legacy_source) == frozen_manifest["source_sha256"],
            "BLOCKED: archived frozen DSP source absent or SHA differs")
    root = Path.cwd()
    sys.path.insert(0,str(root / "scripts"))
    from phase62_evidence import source_manifest
    source_before = source_manifest(root)
    frozen_host = root / "src/prototype/Phase61SeekReference.cpp"
    require(sha(frozen_host) == frozen_manifest["host_source_sha256"],
            "BLOCKED: frozen host source SHA differs; restore archived original source separately")
    require(not output.exists(), "new output directory required")
    info = wav_format(source)
    require(info["frames"] >= info["rate"] * 9, "input needs at least 9 seconds")
    output.mkdir(parents=True)
    report = {"suite": "phase62_clear_final_PCM", "expected": 1, "executed": 0,
              "status": "INCOMPLETE", "preset": args.preset, "input": str(source),
              "input_sha256": sha(source), "host": str(host), "host_sha256": sha(host),
              "oracle": str(oracle), "oracle_sha256": FROZEN_SHA,
              "oracle_manifest": str(manifest_path), "oracle_manifest_sha256": sha(manifest_path),
              "frozen_source_sha256": frozen_manifest["source_sha256"],
              "frozen_host_source_sha256": frozen_manifest["host_source_sha256"],
              "WAV": info, "input_A": 0, "input_B": info["rate"] * 8,
              "comparison": "frozen fixed75 old/new RAW; independent Clear linear equation",
              "natural_period_correction": "separate existing gate; NOT_RUN_IN_THIS_HOST",
              "observer": "pre-mainMixer", "mixer_gain": "NOT_RUN", "physical_loopback": "NOT_RUN",
              "RT_deadline_approval": "NOT_ASSESSED", "commands": [], "source_before": source_before,
              "architectures": {str(p): subprocess.check_output(["lipo","-archs",str(p)],text=True).strip() for p in [host,oracle]}}
    require(all(value=="arm64" for value in report["architectures"].values()),"arm64 host/reference required")
    (output / "EXPECTED.json").write_text(json.dumps(report, indent=2) + "\n")
    try:
        raw = output / "frozen_fixed75.f32"
        command = [str(oracle), str(source), "750000", args.preset, str(raw), "0", str(report["input_B"])]
        report["commands"].append(command)
        (output / "COMMANDS.json").write_text(json.dumps(report["commands"],indent=2)+"\n")
        run(command, output / "frozen_fixed75.log", 600)
        rows = [json.loads(line) for line in (output / "frozen_fixed75.log").read_text().splitlines()
                if line.startswith("{")]
        require(len(rows) == 1, "oracle final JSON missing or duplicated")
        reference = rows[0]
        require(reference["input_frames"] == info["frames"] and reference["rate"] == info["rate"]
                and reference["channels"] == info["channels"], "oracle input identity differs")
        raw_sha = sha(raw)
        require(reference["sha256"] == raw_sha, "oracle RAW SHA differs")
        require(raw.stat().st_size == reference["output_frames"] * info["channels"] * 4,
                "oracle RAW frame count differs")
        oa, ob = reference["positions"]
        require(oa == 0 and ob > 96000, "oracle Map range invalid for this fixture")
        with raw.open("rb") as stream:
            while block := stream.read(1 << 20):
                require(len(block)%4==0 and all(math.isfinite(v[0]) for v in struct.iter_unpack("<f",block)),"nonfinite or unaligned frozen RAW")
        report["fixed_RAW_sha256"] = raw_sha
        report["independent_Map_OA_OB"] = [oa, ob]
        report["oracle_result"] = reference
        command = [str(host), str(source), args.preset, str(output / "native"), str(raw),
                   str(oa), str(ob), str(oracle), raw_sha]
        report["commands"].append(command)
        (output / "COMMANDS.json").write_text(json.dumps(report["commands"],indent=2)+"\n")
        (output / "NATIVE_EXPECTED.json").write_text(json.dumps(report,indent=2)+"\n")
        require(source_manifest(root)["sha256"]==source_before["sha256"],"source changed before native run")
        run(command, output / "native.log", 180)
        result = json.loads((output / "native" / "SUMMARY.json").read_text())
        require(result["expected"] == result["executed"] == 1 and result["status"] == "PASS",
                "native final count/status missing")
        require(result["independent_DSP_RAW_and_final_PCM"] == "PASS", "independent comparison missing")
        require(source_manifest(root)["sha256"]==source_before["sha256"],"source changed during native run")
        report["source_after"] = source_manifest(root)["sha256"]
        report["executed"] = 1
        report["status"] = "PASS"
        report["native_result"] = result
        report["artifacts_sha256"] = {str(p.relative_to(output)): sha(p)
            for p in sorted((output / "native").iterdir()) if p.is_file()}
    except Exception as error:
        report["status"] = "INCOMPLETE" if isinstance(error,subprocess.TimeoutExpired) else "FAIL"
        report["reason"] = str(error)
        raise
    finally:
        (output / "SUMMARY.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()

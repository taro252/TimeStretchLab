"""凍結参照の現在の実体だけを再照合する。ビルド・PCM生成・音声実行はしない。

再実行:
  python3 -B results/phase62_e5_review/recipes/verify_references.py --output NEW_REPORT.json
既存の報告を上書きせず、過去PCM比較の件数を今回の実施数へ移さない。
"""
import argparse
import datetime
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DYNAMIC = "bb22efcbd27f999e8ffe85bbe3f03e20895be3f2"
FIXED = "ec087019626d9ff0d9f157245729b74ddb6847d7"
CAPTURED_SHA = "1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818"
LOGICAL_SHA = "64c4e98611fdf19d673daf58b051a4b992228096eeacd7dc23891b678f1ea5b9"
FIXED_SHA = "de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748"
INPUT_SHA = "789d4c159e35b4c133a17913ad5a9c47b85970185e5d86b074d146afc1bb311e"
INVENTORY_SHA = "86888a27d23b01019adeb8131c92a60eb3c5c87e293cd1bd5697c14a1bbb27c4"
PINNED_MANIFESTS = {
    "references/DYNAMIC_SOURCE_PROVENANCE.json": "9f8f9a81b4e2c111e31c7f1d9e625e09bc4ad9c25f8de76a317d5fef976f9293",
    "references/FIXED_SOURCE_PROVENANCE.json": "abf48d368e907fab2fd6d6557e1e1417b457d00f114275cf0335422c8caf4630",
    "references/DYNAMIC_SOURCE_FILES.json": "b16bb096582495884b6946c728157eb3925601aa52c0474e08dfaeee795519bc",
}
CHECK_IDS = [
    "recorded_manifest_identities",
    "dynamic_523_sources_git_and_sha",
    "dynamic_four_frozen_drivers",
    "dynamic_two_frozen_include_copies",
    "dynamic_four_frozen_libraries",
    "dynamic_four_stored_binaries",
    "fixed_ec087_legacy_source",
    "fixed_unchanged_host_and_freeze_driver",
    "fixed_stored_binary",
    "mandatory_mix_input",
]


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(path, expected=None):
    path = path.resolve()
    with path.open("rb") as stream:
        value = hashlib.file_digest(stream, "sha256").hexdigest()
    row = {"path": str(path), "bytes": path.stat().st_size, "sha256": value}
    if expected is not None:
        row["expected_sha256"] = expected
        need(value == expected, f"SHA不一致: {path}; expected={expected}; actual={value}")
    return row


def read(path):
    return json.loads(path.read_text())


def git(root, *args):
    process = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if process.returncode:
        raise FileNotFoundError(
            "Git参照を読めない: " + " ".join(args) + "; " +
            process.stderr.decode(errors="replace").strip()
        )
    return process.stdout


def verify(root):
    old = root / "results/phase62_finish"
    dynamic_dir = root / "build/phase59_frozen/rebuilt_reference_v3"
    fixed_dir = root / "build/phase61/oracle_release_v1"
    drivers = root / "results/phase59/reference_driver_sources"
    rows = []
    details = {}

    def check(name, action):
        try:
            details[name] = action()
            rows.append({"id": name, "status": "PASS"})
        except (FileNotFoundError, PermissionError) as error:
            rows.append({"id": name, "status": "BLOCKED", "reason": str(error)})
        except Exception as error:
            rows.append({"id": name, "status": "FAIL", "reason": str(error)})

    def manifests():
        records = [identity(old / name, sha) for name, sha in PINNED_MANIFESTS.items()]
        records += [
            identity(dynamic_dir / "manifest.json", PINNED_MANIFESTS["references/DYNAMIC_SOURCE_PROVENANCE.json"]),
            identity(fixed_dir / "manifest.json", PINNED_MANIFESTS["references/FIXED_SOURCE_PROVENANCE.json"]),
        ]
        dp = read(old / "references/DYNAMIC_SOURCE_PROVENANCE.json")
        fp = read(old / "references/FIXED_SOURCE_PROVENANCE.json")
        frozen = read(root / "results/phase59/FROZEN_REFERENCE.json")
        captured = read(root / "results/phase59/CAPTURED_REFERENCE.json")
        need(dp["baseline"] == frozen["baseline_head"] == captured["baseline_head"] == DYNAMIC,
             "動的参照の基準commit不一致")
        need(fp["source_commit"] == FIXED and fp["binary_sha256"] == FIXED_SHA,
             "固定参照のcommit/binary識別不一致")
        need(dp["binary_sha256"] == {"dynamic_reference": LOGICAL_SHA, "captured_reference": CAPTURED_SHA},
             "動的provenanceのbinary識別不一致")
        need(captured["binary_sha256"] == CAPTURED_SHA and frozen["dynamic_reference_sha256"] == LOGICAL_SHA,
             "Phase59の記録済みbinary識別不一致")
        need(all(command["exit"] == 0 for command in dp["commands"] + fp["commands"]),
             "過去ビルド来歴に非0終了")
        need(frozen["library_sha256"] == captured["library_sha256"], "動的ライブラリの記録不一致")
        return {"files": records,
                "phase59_document": identity(root / "docs/PHASE59_TRANSITION_EXACTNESS.md"),
                "phase59_frozen_manifest": identity(root / "results/phase59/FROZEN_REFERENCE.json"),
                "phase59_captured_manifest": identity(root / "results/phase59/CAPTURED_REFERENCE.json")}

    def source_inventory():
        recorded = read(old / "references/DYNAMIC_SOURCE_FILES.json")
        selected = ["CMakeLists.txt", "src", "tests", "scripts", "examples"]
        entries = git(root, "ls-tree", "-r", "-z", DYNAMIC, "--", *selected).split(b"\0")
        expected = {}
        for entry in entries:
            if not entry:
                continue
            meta, name = entry.split(b"\t", 1)
            mode, kind, blob = meta.decode().split()
            need(kind == "blob" and mode in ("100644", "100755"), "未対応の凍結source種別")
            expected[name.decode()] = blob
        names = [row["path"] for row in recorded]
        need(len(names) == len(set(names)) == len(expected) == 523, "必須523sourceの件数/重複不一致")
        need(set(names) == set(expected), "記録済みsource集合と基準Git tree集合が不一致")
        baseline = dynamic_dir / "baseline"
        actual_names = {p.relative_to(baseline).as_posix() for p in baseline.rglob("*") if p.is_file()}
        need(actual_names == set(expected), "保存済みbaselineに欠落または追加source")
        actual = []
        for name in sorted(expected):
            data = (baseline / name).read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            actual.append({"path": name, "git_blob": expected[name], "actual_git_blob": blob,
                           "sha256": digest(data), "PASS": blob == expected[name]})
        need(all(row["PASS"] for row in actual), "保存済みbaselineと基準Git blobの不一致")
        need(actual == recorded, "保存済みsource SHA一覧が過去manifestと不一致")
        inventory = digest(json.dumps(actual, sort_keys=True).encode())
        need(inventory == INVENTORY_SHA, "動的source一覧SHA不一致")
        return {"commit": DYNAMIC, "source_root": str(baseline), "expected_files": 523,
                "verified_files": len(actual), "source_inventory_sha256": inventory,
                "inventory_hash_recipe": "sha256(json.dumps(全523検査行, sort_keys=True).encode())",
                "recorded_inventory": identity(old / "references/DYNAMIC_SOURCE_FILES.json")}

    def frozen_drivers():
        dp = read(old / "references/DYNAMIC_SOURCE_PROVENANCE.json")
        captured = read(root / "results/phase59/CAPTURED_REFERENCE.json")
        frozen = read(root / "results/phase59/FROZEN_REFERENCE.json")
        need(set(dp["driver_sources"]) == {
            "Phase59Reference.cpp", "Phase59CapturedReference.cpp",
            "Phase59ReplaySupport.h", "Phase59PlanningContract.h"}, "凍結driver必須集合不一致")
        need(dp["driver_sources"]["Phase59CapturedReference.cpp"] == captured["driver_source_sha256"],
             "captured driver記録不一致")
        need(all(dp["driver_sources"][name] == sha for name, sha in frozen["frozen_driver_sha256"].items()),
             "logical driver記録不一致")
        return {"files": [identity(drivers / name, sha) for name, sha in sorted(dp["driver_sources"].items())]}

    def include_copies():
        dp = read(old / "references/DYNAMIC_SOURCE_PROVENANCE.json")
        return {"files": [identity(dynamic_dir / "driver_include/prototype" / name, dp["driver_sources"][name])
                          for name in ("Phase59PlanningContract.h", "Phase59ReplaySupport.h")]}

    def libraries():
        frozen = read(root / "results/phase59/FROZEN_REFERENCE.json")
        need(len(frozen["library_sha256"]) == 4, "凍結ライブラリ必須4件が不足")
        return {"files": [identity(root / "build/phase59_frozen" / name, sha)
                          for name, sha in sorted(frozen["library_sha256"].items())]}

    def dynamic_binaries():
        return {"files": [identity(directory / name, sha)
                          for directory in (root / "build/phase59_frozen", dynamic_dir)
                          for name, sha in (("captured_reference", CAPTURED_SHA),
                                            ("dynamic_reference", LOGICAL_SHA))]}

    def fixed_source():
        fp = read(old / "references/FIXED_SOURCE_PROVENANCE.json")
        data = git(root, "show", FIXED + ":src/prototype/Phase36StreamingSpeedEngine.cpp")
        need(digest(data) == fp["source_sha256"], "ec087 Git source SHA不一致")
        row = identity(fixed_dir / "Phase36Legacy.cpp", fp["source_sha256"])
        need((fixed_dir / "Phase36Legacy.cpp").read_bytes() == data, "固定Legacy sourceの全byte不一致")
        return {"commit": FIXED, "git_source": "src/prototype/Phase36StreamingSpeedEngine.cpp",
                "source_files_verified": 1, "file": row,
                "scope": "固定側はmanifestが指定する旧Phase36単一翻訳単位の照合。ec087全treeを凍結したとは主張しない。"}

    def fixed_host_driver():
        fp = read(old / "references/FIXED_SOURCE_PROVENANCE.json")
        return {"files": [
            identity(root / "src/prototype/Phase61SeekReference.cpp", fp["host_source_sha256"]),
            identity(root / "scripts/phase61_freeze_reference.py", fp["driver_sha256"])],
            "scope": "保存済みhost/凍結recipeの内容識別のみ。現在の共有DSPを参照へリンク/再生成しない。"}

    check(CHECK_IDS[0], manifests)
    check(CHECK_IDS[1], source_inventory)
    check(CHECK_IDS[2], frozen_drivers)
    check(CHECK_IDS[3], include_copies)
    check(CHECK_IDS[4], libraries)
    check(CHECK_IDS[5], dynamic_binaries)
    check(CHECK_IDS[6], fixed_source)
    check(CHECK_IDS[7], fixed_host_driver)
    check(CHECK_IDS[8], lambda: identity(fixed_dir / "phase61_frozen_reference", FIXED_SHA))
    check(CHECK_IDS[9], lambda: identity(root / "results/phase31/input/mix.wav", INPUT_SHA))
    need([row["id"] for row in rows] == CHECK_IDS, "監査ID集合/順序不一致")
    status = "FAIL" if any(row["status"] == "FAIL" for row in rows) else (
        "BLOCKED" if any(row["status"] == "BLOCKED" for row in rows) else "PASS")
    return {
        "schema": 1, "suite": "phase62_e5_frozen_reference_identity_audit",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": status, "run_complete": True, "expected": len(CHECK_IDS), "executed": len(rows),
        "passed": sum(row["status"] == "PASS" for row in rows),
        "required_ids": CHECK_IDS, "checks": rows, "details": details,
        "dynamic_commit": DYNAMIC, "fixed_commit": FIXED,
        "dynamic_source_inventory_sha256": details.get(CHECK_IDS[1], {}).get("source_inventory_sha256"),
        "previous_verification": identity(old / "REFERENCE_VERIFIED.json"),
        "recipe": identity(Path(__file__)),
        "scope": "今回新たに読取り実行した凍結source/driver/library/binary/入力の同一性監査だけ。",
        "reference_rebuilt": False, "product_source_used_for_reference": False,
        "pcm_or_audio_executed": False, "new_pcm_cases": 0,
        "old_result_counts_relabelled": False, "local_overall_go": False,
        "completion_marker": "PHASE62_REFERENCE_IDENTITY_AUDIT_COMPLETE" if status == "PASS" else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    need(not output.exists(), "既存報告を上書きしない。未使用の--outputを指定してください: " + str(output))
    report = verify(args.root.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("status", "expected", "executed", "passed", "new_pcm_cases")}))
    return 0 if report["status"] == "PASS" else 4 if report["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

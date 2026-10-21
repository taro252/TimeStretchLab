#!/usr/bin/env python3
"""修正前比較版の保存実体だけを読む。ビルド・PCM・音声実行は行わない。

python3 -B results/phase62_e5_review/recipes/audit_baseline.py --output /tmp/baseline-audit-new.json
既存の監査結果は上書きしない。ソースのbyte列を出力する先は作らない。
"""
import argparse
import collections
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

E5 = "e5dc91675723b7163b10cc3ea2323710033caeaa"
INVENTORY = "31ba1ae56c5489e9e557ad96340be75a49c1c96b35d26f2cd776e78329666802"
NATIVE = "43cf4637898625f7d117f81885f46280ab51e16a6c1d9b78be62352bbebd406b"
CACHE04 = "cea0f508457098b12c0e98928fb8cd239c3129ff71f02e578f06374007f110c3"
HELPER = "tests/Phase62PlayingLedgerNative.cpp"
HELPER_SHA = "20439b87c5b259283dd8ce2e427bb2b55436e551ebf09f15591ecae878005955"
HELPER_INPUT = "a58e27e61565db02493f66f480d66d73944b47a33b0eb088c3f5ab05f3693198"
REPLACEMENTS = [
    (",ProgressiveControlTestHooks engineHooks={}", ""),
    ("options.controlTestHooks=engineHooks.event?engineHooks:ProgressiveControlTestHooks{&gate,WorkerGate::event};",
     "options.controlTestHooks={&gate,WorkerGate::event};"),
]
PINNED = {
    "BASELINE_EXPECTED.json": "77a2b09483aee7f8c58ee5cd53f80002374141c9529ed379a8fb1c6cd09c1418",
    "BASELINE_EXECUTION.json": "84913ecf5b8a725e74bf2ab05fe3c745c5859e3c3a9bd57cebbdf1d269b8490e",
    "instrumented_baseline_source/SOURCE.json": "06d287eb9706d4e3dd702e369327f05cf78904c2cd0970982304ccb6fa2b5bcb",
    "instrumented_baseline_source/FINAL_BASELINE_FILES.json": "2ef195197f55d5571ba1f0cc6e53cba6c12bfdbcaf92cd6752e971523b6ac912",
    "baseline_recovery/RECOVERY_AUDIT.json": "cc7662b2cb8647b8b17edeb5cf5cf03e6bd810fc31ce373c2eb253dbb2b94b34",
    "baseline_cache_candidate_04/old_new_transaction.json": "876dfe09224ef435e9602d5cbf3322c03c44f9f4385ec7351844cc73ff60bc0b",
}
# 各行は元EXPECTED / SUMMARY / checks.jsonlのSHA。旧FAILを新PASSに付け替えない。
HISTORY = {
    "baseline_a1_cancel_candidate_01": (
        "72c122cf1a0aa3a25c7a7d0cdc6dcc512230b394e2445b433b15b17d13ae8f80",
        "83e9951b6e94e7568f5f52255d7b7d56f1d9714ad725c3a9a6e6c34f54a6f2ad",
        "ff00233dd8ceaa88d5d8030afece90f064af3ae620d131e4a76de0ac0549dd7b"),
    "baseline_a1_started_candidate_01": (
        "59c1d80e0585821181dba8b1811a6dd120acfb377ddd0c7d5f9d678914a3f3e0",
        "dbf76c58e0f2b1cf7c34b58df1869a21ee4844b58efe9b3f2d7d85283d7faca7",
        "3df8dcefe98f2c51036232f51c88761edd67ee8e82967a388788e710d7eb46b9"),
    "baseline_a2_initial_supply_candidate_01": (
        "2ad2710b054d8c13207eb83b58c15ba0244bcb8401638adfe5b3d3a7b8b15ab5",
        "abf142a77457b00312d5a42c56a1b0713cba15e2e8cb543e320d3b32c56f46c2",
        "be39040710b1d7303ac176dc88f998b065d38018d38c226942e9d47ba0fc293f"),
    "baseline_b_internal4096_candidate_01": (
        "acd97d9186c91fd5d3ade294aa9ac41631b141c20f6c1c0062e356ffb95a2f57",
        "fd27f11382fc54952a1e1abc0d98ba676af1177ee6fd6c0bba1434665dfa7155",
        "3f1092574b22d094fa4f44c245ad200030da50856804f901a3de069a00e02163"),
    "baseline_cache_candidate_01": (
        "46be9e8c096ea259103e5acadf334eb5b6193f14bd279c752d856a710b296880",
        "84e15da30adcdffd0226ee014acc26ad304d9056bac2bbe0fb1e6090da93b953",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    "baseline_cache_candidate_02": (
        "58a428310e7aa070282d90b9a35ef8652c86131ad95fad3bdbb6ee3b0def3e46",
        "6860ee1e8386a6209d91f4d9fac0ebc8e949cda2d4dccf3bfdc44fb154f01b6b",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    "baseline_cache_candidate_03": (
        "76458bb4f85665320d3ef40dbcc59d1ff1e75575632e4c45217cad889d5d69ee",
        "0bafaaa4d3e89e5db7042754f5dd08721ac783104633096c52633b34fd2f71d5",
        "5d0cf999bd7078ff710afd4440bd84ff9aba504b5be193ed18738d639fa03dd6"),
    "baseline_cache_candidate_04": (
        "b811f3647a6fad15c0d44f838ffab7b15d1eabfe68091801c5b6ee2a431a3041",
        "0bafaaa4d3e89e5db7042754f5dd08721ac783104633096c52633b34fd2f71d5",
        "5d0cf999bd7078ff710afd4440bd84ff9aba504b5be193ed18738d639fa03dd6"),
}
COMMON = ["phase58_realtime", "phase57_synthesis", "phase59_transition",
          "phase56_incremental", "phase39_variable", "phase36_variable",
          "phase24_variable", "timestretch_core"]


class MissingMaterial(Exception):
    pass


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    if not path.is_file():
        raise MissingMaterial(str(path))
    return path.read_bytes()


def audit(root):
    base = root / "build/phase62_e5_review_20261021_01"
    saved = base / "instrumented_baseline_source"

    def identity(path, expected=None):
        data = read(path)
        sha = digest(data)
        need(expected is None or sha == expected, "SHA不一致: " + str(path))
        return dict(path=path.relative_to(root).as_posix(), bytes=len(data), sha256=sha)

    manifests = [identity(base / p, sha) for p, sha in PINNED.items()]
    expected = json.loads(read(base / "BASELINE_EXPECTED.json"))
    rows = expected["source"]["files"]
    inventory = {r["path"]: r["sha256"] for r in rows}
    need(expected["base"] == E5 and len(rows) == len(inventory) == 732, "基点/732件一覧不一致")
    need(digest(json.dumps(rows, sort_keys=True).encode()) == expected["source"]["sha256"] == INVENTORY,
         "ソース一覧SHA不一致")
    need(len(expected["jobs"]) == 4 and expected["binary"]["sha256"] == NATIVE,
         "A1/A2/Bの元4実行/binary記録不一致")

    final_rows = json.loads(read(saved / "FINAL_BASELINE_FILES.json"))
    final = [identity(saved / r["path"], r["sha256"]) for r in final_rows]
    need(len(final_rows) == 8 and all(inventory[r["path"]] == r["sha256"] for r in final_rows),
         "保存最終8件と31ba一覧の不一致")
    initial = json.loads(read(saved / "SOURCE.json"))
    mismatches = [dict(path=r["path"], initial_sha256=r["sha256"],
                       saved_sha256=identity(saved / r["path"])["sha256"])
                  for r in initial["files"] if digest(read(saved / r["path"])) != r["sha256"]]
    need(initial["base"] == E5 and len(initial["files"]) == 7 and
         {r["path"] for r in mismatches} == {
             "src/platform/macos/ProgressiveMacPlaybackEngine.mm",
             "src/platform/macos/ProgressiveMacPlaybackEngine.h",
             "tests/Phase62WorkerTransactionTests.cpp"}, "初期7行の既知不一致が変化")

    # byte候補はメモリー内だけで構成。保存済み復元ファイルとの完全一致も確認する。
    helper_input = read(root / HELPER)
    need(digest(helper_input) == HELPER_INPUT, "2差分復元の入力版が変化")
    candidate = helper_input
    for old, new in REPLACEMENTS:
        need(candidate.count(old.encode()) == 1, "復元置換は各1箇所必要")
        candidate = candidate.replace(old.encode(), new.encode())
    recovered = base / "baseline_recovery/Phase62PlayingLedgerNative.cpp"
    need(digest(candidate) == inventory[HELPER] == HELPER_SHA and candidate == read(recovered),
         "復元helperのbyte/SHA不一致")

    restored = {}
    missing = []
    for path, sha in inventory.items():
        candidates = [(root / path, "worktree"), (saved / path, "saved_final")]
        if path == HELPER:
            candidates.insert(0, (recovered, "recovered_helper"))
        provider = next(((p, kind) for p, kind in candidates
                         if p.is_file() and digest(p.read_bytes()) == sha), None)
        if provider:
            p, kind = provider
            restored[path] = dict(path=path, sha256=sha, restore_kind=kind,
                                  restore_from=p.relative_to(root).as_posix())
            continue
        result = subprocess.run(["git", "cat-file", "blob", E5 + ":" + path],
                                cwd=root, capture_output=True, check=False)
        if result.returncode == 0 and digest(result.stdout) == sha:
            restored[path] = dict(path=path, sha256=sha, restore_kind="git_blob",
                                  restore_from=E5 + ":" + path)
        else:
            missing.append(dict(path=path, expected_sha256=sha))
    need({r["path"] for r in missing} == {
        "tests/Phase62PartialMixNative.cpp", "tests/Phase62PreparationFaultNative.cpp"},
        "既知の実依存外2件以外に未回収ソース")

    def closure(targets, count):
        paths, evidence = set(), []
        for target in targets:
            directory = base / "baseline_build/CMakeFiles" / (target + ".dir")
            dependencies = sorted(directory.rglob("*.o.d"))
            if not dependencies:
                raise MissingMaterial("依存記録なし: " + str(directory))
            for p in dependencies:
                evidence.append(identity(p))
                paths.update(re.findall(re.escape(str(root)) + r"/([^\s\\]+)", read(p).decode()))
            evidence.extend(identity(directory / name) for name in ("flags.make", "link.txt"))
        need(len(paths) == count and paths <= restored.keys(), "依存件数/完全復元不一致")
        return dict(expected_files=count, verified_files=len(paths), targets=targets,
                    source_paths=sorted(paths), dependency_and_build_records=evidence)

    native = closure(["phase62_adoption_review_native", "macos_progressive_playback_engine",
                      "phase61_callback_heap_probe"] + COMMON, 122)
    cache = closure(["phase62_worker_transaction_tests"] + COMMON, 104)
    native["binary"] = identity(base / "baseline_build/phase62_adoption_review_native", NATIVE)
    need(native["binary"]["bytes"] == expected["binary"]["bytes"] == 1134512, "native bytes不一致")
    cache["binary"] = identity(base / "baseline_build/phase62_worker_transaction_tests", CACHE04)
    cache["runtime_source_binding"] = "BLOCKED_MISSING_RECORD"
    cache["source_relation"] = "関連104件を31ba期待byteで構成できる。当時の実行sourceが31baだったとは認定しない。"

    historical = []
    for name, hashes in HISTORY.items():
        files = [identity(base / name / leaf, sha) for leaf, sha in
                 zip(("EXPECTED.json", "SUMMARY.json", "checks.jsonl"), hashes)]
        exp = json.loads(read(base / name / "EXPECTED.json"))
        summary = json.loads(read(base / name / "SUMMARY.json"))
        is_native = not name.startswith("baseline_cache_")
        if is_native:
            need(exp["source_list_sha256"] == INVENTORY and exp["binary_sha256"] == NATIVE,
                 "元native実行のsource/binary接続不一致")
        else:
            need(not any("source" in k or "driver" in k for k in exp), "cacheの元記録の範囲が変化")
        need(summary["status"] == ("PASS" if name == "baseline_a1_cancel_candidate_01" else "FAIL"),
             "過去の成否変更")
        historical.append(dict(run=name, original_status=summary["status"],
                               original_summary=summary, original_binary_sha256=exp["binary_sha256"],
                               recorded_source_inventory_sha256=exp.get("source_list_sha256"),
                               original_artifacts=files))
    executions = json.loads(read(base / "BASELINE_EXECUTION.json"))
    need([r["exit"] for r in executions] == [0, 1, 1, 1], "元実行exit不一致")
    for row in executions:
        row["log_identity"] = identity(root / row["log"])
    need(json.loads(read(base / "baseline_cache_candidate_04/EXPECTED.json"))["binary_sha256"] == CACHE04,
         "cache04の元binary SHA不一致")
    observed = json.loads(read(base / "baseline_cache_candidate_04/old_new_transaction.json"))
    need(observed == dict(old_id=1, new_id=2, deadline_decision_id=1, new_observed_id=2,
                          state="Rejected", reason=0), "cache04旧完了汚染の保存事実不一致")
    union = set(native["source_paths"]) | set(cache["source_paths"])
    return dict(
        schema=1, status="PASS", meaning="保存実体の読取監査が成立。過去の機能試験は再実行していない。",
        scope="A1/A2/B保存binaryと依存122件、cache04保存binaryと関連104件の限定監査。",
        base_commit=E5, source_inventory_sha256=INVENTORY, original_manifests=manifests,
        source_inventory=dict(expected_files=732, recoverable_files=len(restored),
                              restore_counts=dict(collections.Counter(r["restore_kind"] for r in restored.values())),
                              unrecovered_outside_both_binary_dependencies=missing),
        initial_source_manifest=dict(rows=7, mismatches_with_saved_bytes=mismatches,
                                     meaning="初期SOURCE.jsonは後の保存8ファイルを表さない。"),
        final_saved_sources=final,
        helper_recovery=dict(input_sha256=HELPER_INPUT, output=identity(recovered, HELPER_SHA),
                             replacements=[dict(old_utf8=a, new_utf8=b, occurrences=1) for a, b in REPLACEMENTS],
                             byte_recipe_replayed_in_memory=True, source_bytes_written_by_this_audit=False),
        native_A1_A2_B=native, cache04=cache,
        restorable_dependency_sources=[restored[p] for p in sorted(union)],
        historical_runs=historical, original_execution_records=executions,
        cache04_original_old_new_transaction=observed,
        missing_old_cache_binaries=dict(runs=["01", "02", "03"],
                                       scope="現在のbaseline_build共有パスは04のbyte。旧3版はこの監査で復元しない。"),
        new_execution_counts=dict(rebuild=0, pcm=0, audio=0, historical_runs_relabelled=0),
        limits=["732件の完全なソース凍結ではない。未回収PartialMix/Fault2件は両binaryの依存外。",
                "cache04のsource/driver識別子と4jobへの接続は元記録にない。この不足は埋めない。",
                "依存122/104件は現在残るコンパイラー依存記録から列挙。cache04実行時source接続の代用にはしない。",
                "nativeは外部dylibにも依存する。その当時SHAは元EXPECTEDにないため実行環境全体の凍結とは認定しない。"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("既存の監査結果は上書きしません: " + str(args.output))
    try:
        report = audit(args.root.resolve())
    except MissingMaterial as error:
        report = dict(schema=1, status="BLOCKED", reason="保存素材がない: " + str(error))
    except (ValueError, KeyError, OSError) as error:
        report = dict(schema=1, status="FAIL", reason=str(error))
    report["audited_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report["recipe"] = dict(path=str(Path(__file__).resolve()), sha256=digest(Path(__file__).read_bytes()))
    with args.output.open("x") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(dict(status=report["status"], output=str(args.output)), ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

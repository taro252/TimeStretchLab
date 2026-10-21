"""修正Fの統合用ドラフト。旧証拠は変更せず、完全性と出所を別に判定する。"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

CONFIGURATIONS = ["Release", "Debug"]
STAGES = ["configure", "build", "ctest"]
SCHEMA = 2


class EvidenceError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise EvidenceError(message)


def read(path):
    return json.loads(Path(path).read_text())


def identity(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def exact_ids(expected, actual, label):
    need(isinstance(expected, list) and bool(expected), label + ": empty/missing expected IDs")
    need(all(isinstance(x, str) and bool(x) for x in expected), label + ": invalid expected ID")
    need(len(expected) == len(set(expected)), label + ": duplicate expected IDs")
    need(isinstance(actual, list) and all(isinstance(x, str) and x for x in actual), label + ": invalid actual IDs")
    need(len(actual) == len(set(actual)), label + ": duplicate actual IDs")
    need(set(expected) == set(actual), label + ": missing/unexpected IDs")


def count(value, label):
    need(type(value) is int and value >= 0, label + ": invalid/missing integer")
    return value


def file_record(record, directory=None):
    need(isinstance(record, dict), "missing artifact identity")
    path = Path(record.get("path", ""))
    need(str(path) not in ("", "."), "missing artifact path")
    if not path.is_absolute():
        need(directory is not None, "relative artifact without directory")
        path = Path(directory) / path
    if directory is not None:
        need(path.resolve().is_relative_to(Path(directory).resolve()), "artifact escapes evidence directory")
    actual = identity(path)
    need(type(record.get("bytes")) is int and record["bytes"] == actual["bytes"], "artifact size differs: " + str(path))
    need(record.get("sha256") == actual["sha256"], "artifact SHA differs: " + str(path))
    return path


def junit(path, expected_names):
    root = ET.parse(path).getroot()
    need(root.tag in ("testsuite", "testsuites"), "unsupported JUnit root")
    cases = root.findall(".//testcase")
    exact_ids(expected_names, [c.get("name") for c in cases], "CTest test names")
    need(bool(cases), "zero CTest cases")
    for suite in root.iter():
        if suite.tag not in ("testsuite", "testsuites"):
            continue
        if "tests" in suite.attrib:
            need(suite.get("tests", "").isdigit(), "invalid JUnit tests counter")
            need(int(suite.get("tests")) == len(suite.findall(".//testcase")), "JUnit tests counter mismatch")
        for key in ("failures", "errors", "skipped", "disabled"):
            if key in suite.attrib:
                need(suite.get(key) == "0", "nonzero JUnit " + key)
    for case in cases:
        need(case.get("status") == "run", "CTest case not run/skipped/disabled")
        need(not any(child.tag in ("failure", "error", "skipped") for child in case.iter()), "JUnit failing/skipped case")
        seconds = float(case.get("time", "nan"))
        need(math.isfinite(seconds) and seconds >= 0, "invalid JUnit test duration")
    return {"expected": len(expected_names), "executed": len(cases), "test_ids": sorted(c.get("name") for c in cases),
            "failures": 0, "errors": 0, "skipped": 0, "disabled": 0, "junit": identity(path)}


def stage_log(path, stage, names, targets):
    text = Path(path).read_text()
    need(bool(text.strip()), "empty stage log")
    if stage == "configure":
        need(all(token in text for token in ("-- Configuring done", "-- Generating done", "-- Build files have been written to:")), "incomplete configure log")
        need(not re.search(r"^CMake Error", text, re.M), "configure error")
    elif stage == "build":
        for target in targets:
            need(re.search(r"Built target " + re.escape(target) + r"\s*$", text, re.M), "missing built target: " + target)
    elif stage == "ctest":
        passed = re.findall(r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(\S+)\s+\.{2,}\s+Passed\s+[\d.]+\s+sec\s*$", text, re.M)
        exact_ids(names, passed, "CTest log passed names")
        need(f"100% tests passed, 0 tests failed out of {len(names)}" in text, "missing CTest complete success statistic")
        need("Total Test time (real) =" in text, "CTest final timing missing")


def rows_complete(expected_ids, rows, expected_count, executed_count, require_timeout_fields=True):
    """全rows系suiteで共用。件数はSUMMARY自身の宣言だけを信用しない。"""
    need(isinstance(rows, list), "missing rows")
    exact_ids(expected_ids, [r.get("id") for r in rows], "stage/job IDs")
    need(count(expected_count, "expected") == len(expected_ids), "expected count differs from immutable plan")
    need(count(executed_count, "executed") == len(rows), "executed count differs from rows")
    for row in rows:
        need(row.get("status") == "PASS", "non-PASS row: " + row["id"])
        need(type(row.get("exit")) is int and row["exit"] == 0, "exit not measured zero: " + row["id"])
        if require_timeout_fields:
            need(row.get("timed_out") is False and row.get("interrupted") is False, "timeout/interruption fields missing or set")
        else:
            need(not row.get("timed_out") and not row.get("timeout") and not row.get("interrupted"), "legacy timeout/interruption")
        if "expected" in row or "executed" in row:
            need(count(row.get("expected"), "row expected") == count(row.get("executed"), "row executed") > 0, "nested case count mismatch/zero")
    return len(rows)


def gate_plan(expected):
    need(expected.get("configurations") == CONFIGURATIONS, "Release/Debug configuration set missing")
    names = expected.get("ctest_names")
    exact_ids(names, names, "expected CTest names")
    need(count(expected.get("ctest_per_configuration"), "ctest_per_configuration") == len(names), "expected CTest count mismatch")
    targets = expected.get("targets")
    exact_ids(targets, targets, "expected build targets")
    return [stage + "_" + cfg for cfg in CONFIGURATIONS for stage in STAGES], names, targets


def command_plan(by_id, directory, names, targets):
    for cfg in CONFIGURATIONS:
        c = by_id["configure_" + cfg].get("command", [])
        need(c and c[0] == "cmake" and "-S" in c and "-B" in c and "-DCMAKE_BUILD_TYPE=" + cfg in c and
             "-DCMAKE_OSX_ARCHITECTURES=arm64" in c and "-DBUILD_TESTING=ON" in c, "configure command mismatch")
        build_dir = c[c.index("-B") + 1]
        need(by_id["build_" + cfg].get("command") == ["cmake", "--build", build_dir, "--target", *targets, "-j2"], "build target/command mismatch")
        wanted = ["ctest", "--test-dir", build_dir, "-R", "^(" + "|".join(names) + ")$", "--parallel", "1", "--output-on-failure", "--output-junit", str(directory.resolve() / ("ctest_" + cfg + ".xml"))]
        need(by_id["ctest_" + cfg].get("command") == wanted, "CTest command mismatch")


def strict_gates(directory, summary_override=None):
    directory = Path(directory)
    expected = read(directory / "EXPECTED.json")
    summary = read(directory / "SUMMARY.json") if summary_override is None else summary_override
    need(expected.get("schema") == summary.get("schema") == SCHEMA, "new schema missing/unsupported")
    need(expected.get("suite") == summary.get("suite") == "phase62_deterministic_gates", "suite mismatch")
    need(isinstance(expected.get("run_id"), str) and bool(expected["run_id"]) and expected["run_id"] == summary.get("run_id"), "run identity missing/mismatch")
    need(summary.get("run_complete") is True and summary.get("status") == "PASS", "missing final completion marker")
    need(summary.get("expected_sha256") == identity(directory / "EXPECTED.json")["sha256"], "EXPECTED identity mismatch")
    need(summary.get("source_unchanged") is True, "source not verified unchanged")
    source = expected.get("provenance", {}).get("source_inventory_sha256")
    need(isinstance(source, str) and re.fullmatch(r"[0-9a-f]{64}", source), "source inventory identity missing")
    need(summary.get("source_inventory_sha256") == source, "result source mismatch")
    source_file = file_record(expected.get("provenance", {}).get("source_manifest"), directory)
    need(read(source_file).get("sha256") == source, "saved source inventory mismatch")
    ids, names, targets = gate_plan(expected)
    plans = expected.get("stages")
    need(isinstance(plans, list), "immutable stage plan missing")
    exact_ids(ids, [x.get("id") for x in plans], "expected mandatory stage IDs")
    need(count(expected.get("expected_stage_count"), "expected_stage_count") == len(ids), "plan count mismatch")
    rows_complete(ids, summary.get("rows"), summary.get("expected_stage_count"), summary.get("executed_stage_count"))
    by_id = {x["id"]: x for x in plans}
    command_plan(by_id, directory, names, targets)
    measured = {}
    executed_binaries = {}
    test_runtimes = {}
    for row in summary["rows"]:
        plan = by_id[row["id"]]
        stage, cfg = row["id"].split("_", 1)
        need(plan.get("stage") == row.get("stage") == stage and plan.get("configuration") == row.get("configuration") == cfg, "stage/configuration mismatch")
        need(isinstance(plan.get("command"), list) and bool(plan["command"]) and row.get("command") == plan["command"], "stage command missing/mismatch")
        stage_log(file_record(row.get("log"), directory), stage, names, targets)
        if stage == "ctest":
            measured[cfg] = junit(file_record(row.get("junit"), directory), names)
            need(row.get("expected") == measured[cfg]["expected"] and row.get("executed") == measured[cfg]["executed"], "CTest result count mismatch")
            before, after, archives = row.get("binary_before"), row.get("binary_after"), row.get("binary_archives")
            need(isinstance(before, dict) and isinstance(after, dict) and isinstance(archives, dict), "executed binary identities missing")
            exact_ids(targets, list(before), "pre-CTest binaries")
            exact_ids(targets, list(after), "post-CTest binaries")
            exact_ids(targets, list(archives), "preserved binaries")
            for target in targets:
                need(before[target] == after[target], "binary changed during CTest: " + target)
                file_record(archives[target], directory)
                need(before[target].get("sha256") == archives[target]["sha256"] and before[target].get("bytes") == archives[target]["bytes"], "preserved/executed binary mismatch")
            executed_binaries[cfg] = {target: {"sha256": before[target]["sha256"], "bytes": before[target]["bytes"],
                "executed_path": before[target]["path"], "preserved": archives[target]} for target in targets}
            inventory = read(file_record(row.get("test_inventory"), directory))
            commands = {x.get("name"): x.get("command") for x in inventory.get("tests", [])}
            exact_ids(names, [x.get("name") for x in inventory.get("tests", [])], "CTest runtime inventory IDs")
            runtime_before, runtime_after, runtime_archives = row.get("runtime_before"), row.get("runtime_after"), row.get("runtime_archives")
            need(all(isinstance(x, dict) for x in (runtime_before, runtime_after, runtime_archives)), "CTest interpreter/executable identities missing")
            for records in (runtime_before, runtime_after, runtime_archives):
                exact_ids(names, list(records), "CTest runtime executable IDs")
            for name in names:
                need(isinstance(commands[name], list) and commands[name], "CTest runtime command missing")
                need(runtime_before[name] == runtime_after[name], "runtime binary changed during CTest")
                need(runtime_before[name].get("path") == str(Path(commands[name][0]).resolve()), "runtime command/binary mismatch")
                file_record(runtime_archives[name], directory)
                need(runtime_before[name].get("sha256") == runtime_archives[name]["sha256"] and
                     runtime_before[name].get("bytes") == runtime_archives[name]["bytes"], "runtime archive mismatch")
            test_runtimes[cfg] = {name: dict(command=commands[name], executed=runtime_before[name], preserved=runtime_archives[name]) for name in names}
    return {"schema": SCHEMA, "suite": expected["suite"], "run_id": expected["run_id"], "status": "PASS",
            "run_complete": True, "expected_stage_ids": ids, "executed_stage_ids": sorted(x["id"] for x in summary["rows"]),
            "expected_stages": len(ids), "executed_stages": len(summary["rows"]), "configurations": measured,
            "measured_counts": {cfg: measured[cfg]["executed"] for cfg in CONFIGURATIONS},
            "source_inventory_sha256": source, "expected": identity(directory / "EXPECTED.json"),
            "executed_binaries": executed_binaries, "reference_scope": expected.get("reference_scope", "NOT_ASSERTED_BY_THIS_GATE"),
            "test_runtimes": test_runtimes,
            "summary": identity(directory / "SUMMARY.json"), "local_overall_go": False}


def audit_legacy_gates(directory, pins):
    """明示的な旧schema監査。run_completeを推定/追記しない。"""
    directory = Path(directory)
    for name, saved in pins["files"].items():
        current = identity(directory / name)
        need(current["sha256"] == saved["sha256"] and current["bytes"] == saved["bytes"], "legacy original SHA differs: " + name)
    expected, summary = read(directory / "EXPECTED.json"), read(directory / "SUMMARY.json")
    need("schema" not in expected and "run_complete" not in summary, "not the declared legacy schema")
    ids, names, targets = gate_plan(expected)
    rows = summary.get("rows")
    rows_complete(ids, rows, len(ids), len(rows or []), require_timeout_fields=False)
    by_id = {row["id"]: row for row in rows}
    command_plan(by_id, directory, names, targets)
    measured = {}
    for cfg in CONFIGURATIONS:
        configure, build, ctest = [by_id[stage + "_" + cfg] for stage in STAGES]
        c = configure.get("command", [])
        need(c and c[0] == "cmake" and "-S" in c and "-B" in c and "-DCMAKE_BUILD_TYPE=" + cfg in c, "legacy configure command mismatch")
        build_dir = c[c.index("-B") + 1]
        need(build.get("command") == ["cmake", "--build", build_dir, "--target", *targets, "-j2"], "legacy build target/command mismatch")
        command = ctest.get("command", [])
        wanted = ["ctest", "--test-dir", build_dir, "-R", "^(" + "|".join(names) + ")$", "--parallel", "1", "--output-on-failure", "--output-junit", str(directory.resolve() / ("ctest_" + cfg + ".xml"))]
        need(command == wanted, "legacy CTest command mismatch")
        for stage in STAGES:
            stage_log(directory / (stage + "_" + cfg + ".log"), stage, names, targets)
        measured[cfg] = junit(directory / ("ctest_" + cfg + ".xml"), names)
        need(ctest.get("verified") is True and ctest.get("expected") == ctest.get("executed") == measured[cfg]["executed"], "legacy CTest row/JUnit mismatch")
    return {"schema": SCHEMA, "suite": "phase62_legacy_deterministic_gate_audit", "status": "INCOMPLETE",
            "execution_completeness": "PASS", "original_schema": "legacy rows-only; no run_complete marker",
            "expected_stage_ids": ids, "executed_stage_ids": sorted(by_id), "expected_stages": len(ids), "executed_stages": len(rows),
            "configurations": measured, "measured_counts": {cfg: measured[cfg]["executed"] for cfg in CONFIGURATIONS},
            "source_inventory_sha256": expected["source"]["sha256"], "original_files": pins["files"],
            "binary_provenance": "NOT_RECORDED_IN_ORIGINAL_EXPECTED; current rebuilt binaries are not substituted",
            "reference_provenance": "NOT_RECORDED_IN_ORIGINAL_EXPECTED; no inferred oracle SHA",
            "current_source_approval": False, "local_overall_go": False,
            "missing": ["original executed binary-to-source identity is not recorded by this legacy gate"]}


def legacy_declared_ids(expected):
    """旧rows suiteでEXPECTEDに元から存在するIDだけを使う。SUMMARYから補わない。"""
    for key in ("commands", "jobs"):
        rows = expected.get(key)
        if isinstance(rows, list) and rows and all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in rows):
            ids = [x["id"] for x in rows]
            exact_ids(ids, ids, "legacy declared IDs")
            return ids
    raise EvidenceError("legacy EXPECTED has no explicit ID plan; requires a reviewed per-suite adapter/certificate")


def audit_legacy_rows(expected, summary):
    """汎用の完全性監査だけ。個々のPCM/故障条件の意味までは承認しない。"""
    ids = legacy_declared_ids(expected)
    declared = expected.get("expected_programs", expected.get("expected"))
    need(type(declared) is int and declared == len(ids), "legacy EXPECTED count missing/mismatch")
    exp = summary.get("expected_programs", summary.get("expected"))
    done = summary.get("executed_programs", summary.get("executed"))
    rows_complete(ids, summary.get("rows"), exp, done, require_timeout_fields=False)
    return {"row_completeness": "PASS", "expected_ids": sorted(ids), "actual_ids": sorted(r["id"] for r in summary["rows"]),
            "expected": len(ids), "executed": len(summary["rows"]), "per_case_semantics": "NOT_ASSESSED", "local_overall_go": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("strict", "legacy"))
    p.add_argument("directory", type=Path)
    p.add_argument("--pins", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    need(not args.output.exists(), "refusing to overwrite an audit")
    try:
        if args.mode == "legacy":
            need(args.pins is not None, "explicit legacy provenance pins required")
            result = audit_legacy_gates(args.directory, read(args.pins))
        else:
            result = strict_gates(args.directory)
    except (ValueError, OSError, ET.ParseError) as error:
        result = {"schema": SCHEMA, "status": "FAIL", "reason": str(error), "local_overall_go": False}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    # A successful scoped component must not turn INCOMPLETE into exit zero.
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

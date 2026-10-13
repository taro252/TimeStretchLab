#!/usr/bin/env python3
"""Bounded A/B study. Exit 2: quality failure; exit 3: execution/evidence error."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('AUDIO_QUALITY', 'MEASUREMENT_QUALITY', 'CSV_INTEGRITY', 'METRIC_INTEGRITY',
            'PCM_CORRECTNESS', 'CONFIG_VALIDITY', 'NATIVE_STABILITY_VERDICT')


def inspect_condition(output, code, expected=4):
    """Validate aggregate and individual records, fail closed."""
    errors = []
    if code not in (0, 2): errors.append(f'child_exit:{code}')
    try:
        aggregate = json.loads((output / 'comparison_summary.json').read_text())
        if aggregate['all_runs'] != expected: errors.append('incomplete_run_count')
        if aggregate['NATIVE_QUALITY'] not in ('PASS', 'FAIL', 'INDETERMINATE'):
            errors.append('invalid_aggregate_verdict')
        records = list((output / 'runs').glob('*/comparison.json'))
        if len(records) != expected: errors.append('missing_individual_results')
        qualities = []
        for path in records:
            row = json.loads(path.read_text())
            if any(row.get(k) not in ('PASS', 'FAIL', 'INDETERMINATE') for k in REQUIRED):
                errors.append(f'missing_or_invalid_verdict:{path.parent.name}')
            if not all((path.parent / k).is_file() for k in
                       ('callbacks.csv','workers.csv','workers.csv.guard.csv','replay.csv','csv_integrity.json')):
                errors.append(f'missing_csv:{path.parent.name}')
            all_pass=all(row.get(k)=='PASS' for k in REQUIRED)
            if row.get('NATIVE_STABILITY_VERDICT')=='PASS' and not all_pass:
                errors.append(f'cached_pass_with_invalid_evidence:{path.parent.name}')
            qualities.append('FAIL' if any(row.get(k)=='FAIL' for k in
                             ('AUDIO_QUALITY','PCM_CORRECTNESS','NATIVE_STABILITY_VERDICT'))
                             else 'PASS' if all_pass else 'INDETERMINATE')
        quality = ('FAIL' if 'FAIL' in qualities else 'INDETERMINATE' if 'INDETERMINATE' in qualities else 'PASS')
        if aggregate['NATIVE_QUALITY'] != quality: errors.append('aggregate_disagrees_with_records')
        if (code == 0) != (aggregate['NATIVE_QUALITY'] == 'PASS'):
            errors.append('child_exit_disagrees_with_quality')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        errors.append(f'evidence_error:{type(exc).__name__}:{exc}'); quality = 'INDETERMINATE'
    if errors and quality!='FAIL': quality='INDETERMINATE'
    return dict(process_exit=code, quality=quality, structural_errors=errors,
                EXPERIMENT_EXECUTION='ERROR' if errors else 'COMPLETE')


def run_conditions(base, conditions, execute=None):
    base = Path(base); base.mkdir(parents=True, exist_ok=True)
    if (base / 'batch_result.json').exists() or (base / 'conditions.json').exists():
        raise FileExistsError('Use a fresh output directory; retained evidence is never overwritten')
    results = []
    for source, minutes in conditions:
        name = f'{source}{minutes}_stress'; output = base / name
        command = [sys.executable, str(ROOT/'scripts/phase48_study.py'), '--output', str(output),
                   '--source',source,'--minutes',str(minutes),'--orders','AB,BA']
        print('CONDITION_BEGIN',name,flush=True)
        try:
            with (base / f'{name}.log').open('x') as log:
                code = (subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                       timeout=minutes*960+600).returncode if execute is None else execute(output,log))
            result = inspect_condition(output,code)
        except (OSError,subprocess.SubprocessError) as exc:
            result = dict(process_exit=None,quality='INDETERMINATE',EXPERIMENT_EXECUTION='ERROR',
                          structural_errors=[f'child_execution:{exc}'])
        results.append(dict(condition=name,**result))
        (base/'conditions.json').write_text(json.dumps(results,indent=2))
        print('CONDITION_END',results[-1],flush=True)
        if result['structural_errors']: break
    execution = 'COMPLETE' if len(results)==len(conditions) and all(
        r['EXPERIMENT_EXECUTION']=='COMPLETE' for r in results) else 'ERROR'
    quality = ('FAIL' if any(r['quality']=='FAIL' for r in results) else 'PASS' if execution=='COMPLETE'
               and all(r['quality']=='PASS' for r in results) else 'INDETERMINATE')
    code = 3 if execution!='COMPLETE' else 0 if quality=='PASS' else 2
    result = dict(EXPERIMENT_EXECUTION=execution,AUDIO_QUALITY=quality,exit_code=code,
                  completed_conditions=len(results),planned_conditions=len(conditions),results=results)
    (base/'batch_result.json').write_text(json.dumps(result,indent=2))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'results/phase50/long')
    args=parser.parse_args();result=run_conditions(args.output,[('drums',5),('drums',10),('mix',5)])
    print(f"EXPERIMENT_EXECUTION={result['EXPERIMENT_EXECUTION']} AUDIO_QUALITY={result['AUDIO_QUALITY']}",flush=True)
    return result['exit_code']
if __name__=='__main__': sys.exit(main())

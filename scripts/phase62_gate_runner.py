"""run_final_gates_v7.pyの置換候補。ドラフト作成中には実行しない。"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from phase62_aggregation import (CONFIGURATIONS, STAGES, SCHEMA, strict_gates,
                                  identity, junit, stage_log, exact_ids)

NAMES = ['phase59_certified_planning','phase59_request_control','phase61_contract','phase61_checkpoint',
         'phase61_safety','phase61_output_transition','phase61_pipeline_sync','paused_speed_pipeline',
         'phase62_loop','phase62_render','phase62_fix_safety','phase62_evidence','phase62_fix_reuse',
         'phase62_fix_period','phase62_fix_checkpoint','phase62_dynamic_boundary','phase62_loop_speed_ledger','phase62_finish_evidence',
         'phase62_history_invariant','phase62_descriptor_invariant']
TARGETS = ['phase59_tests','phase59_control_tests','phase61_contract_tests','phase61_checkpoint_tests',
           'phase61_safety_tests','phase61_output_transition_tests','phase61_pipeline_sync_tests',
           'paused_speed_pipeline_tests','phase62_loop_tests','phase62_render_tests','phase62_fix_safety_tests',
           'phase62_fix_reuse_tests','phase62_fix_render_tests','phase62_fix_checkpoint_tests',
           'phase62_dynamic_boundary_tests','phase62_native_tests','paused_speed_loop_tests','phase62_loop_speed_ledger_tests',
           'phase62_history_invariant_tests','phase62_descriptor_invariant_tests']


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--build-base', type=Path, required=True)
    p.add_argument('--release-build', type=Path, help='既存Release領域を再利用。必須stage/target集合は不変')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root, base, out = [x.resolve() for x in (args.root, args.build_base, args.output)]
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(root / 'scripts'))
    from phase62_evidence import source_manifest
    builds={cfg:(args.release_build.resolve() if cfg=='Release' and args.release_build else base/cfg.lower()) for cfg in CONFIGURATIONS}
    source = source_manifest(root)
    save(out / 'SOURCE.json', source)
    stages = []
    for cfg in CONFIGURATIONS:
        build = builds[cfg]
        commands = {
            'configure': ['cmake','-S',str(root),'-B',str(build),'-DCMAKE_BUILD_TYPE='+cfg,
                          '-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON'],
            'build': ['cmake','--build',str(build),'--target',*TARGETS,'-j2'],
            'ctest': ['ctest','--test-dir',str(build),'-R','^('+'|'.join(NAMES)+')$',
                      '--parallel','1','--output-on-failure','--output-junit',str(out / ('ctest_'+cfg+'.xml'))],
        }
        for stage in STAGES:
            stages.append(dict(id=stage+'_'+cfg,stage=stage,configuration=cfg,command=commands[stage],
                               timeout_seconds=3600 if stage=='ctest' else 1800))
    expected = dict(schema=SCHEMA,suite='phase62_deterministic_gates',run_id=str(uuid.uuid4()),
                    expected_stage_count=len(stages),stages=stages,configurations=CONFIGURATIONS,
                    ctest_names=NAMES,ctest_per_configuration=len(NAMES),targets=TARGETS,
                    provenance=dict(source_inventory_sha256=source['sha256'],source_manifest=identity(out/'SOURCE.json')),
                    references=[],reference_scope='This gate asserts deterministic CTest results; it does not assert an external frozen DSP oracle comparison.')
    save(out/'EXPECTED.json',expected)
    summary = dict(schema=SCHEMA,suite=expected['suite'],run_id=expected['run_id'],run_complete=False,
                   status='INCOMPLETE',expected_sha256=identity(out/'EXPECTED.json')['sha256'],
                   source_inventory_sha256=source['sha256'],source_unchanged=False,
                   expected_stage_count=len(stages),executed_stage_count=0,rows=[],local_overall_go=False)
    save(out/'SUMMARY.json',summary)
    try:
        for plan in stages:
            if source_manifest(root)['sha256'] != source['sha256']:
                raise RuntimeError('source changed before '+plan['id'])
            row = {k:plan[k] for k in ['id','stage','configuration','command']}
            row.update(exit=None,status='INCOMPLETE',timed_out=False,interrupted=False)
            binaries = {}
            if plan['stage']=='ctest':
                build = builds[plan['configuration']]
                archive = out / 'executed_binaries' / plan['configuration'];archive.mkdir(parents=True)
                for target in TARGETS:
                    binaries[target]=identity(build/target)
                    shutil.copy2(build/target,archive/target)
                row.update(binary_before=binaries,binary_archives={t:identity(archive/t) for t in TARGETS})
                inventory_command=['ctest','--test-dir',str(build),'-R','^('+'|'.join(NAMES)+')$','--show-only=json-v1']
                inventory=json.loads(subprocess.check_output(inventory_command,text=True,timeout=30))
                exact_ids(NAMES,[x.get('name') for x in inventory.get('tests',[])],'CTest runtime discovery')
                save(out/('ctest_inventory_'+plan['configuration']+'.json'),inventory)
                row['test_inventory']=identity(out/('ctest_inventory_'+plan['configuration']+'.json'))
                row['runtime_before']={x['name']:identity(x['command'][0]) for x in inventory['tests']}
                runtime_archive=archive/'runtimes';runtime_archive.mkdir()
                for x in inventory['tests']:shutil.copy2(x['command'][0],runtime_archive/x['name'])
                row['runtime_archives']={x['name']:identity(runtime_archive/x['name']) for x in inventory['tests']}
            log = out/(plan['id']+'.log');started=time.monotonic()
            try:
                with log.open('w') as stream:
                    row['exit']=subprocess.run(plan['command'],stdout=stream,stderr=subprocess.STDOUT,
                                               timeout=plan['timeout_seconds']).returncode
            except subprocess.TimeoutExpired:
                row['timed_out']=True
            except KeyboardInterrupt:
                row['interrupted']=True
            row.update(seconds=time.monotonic()-started,log=identity(log))
            if row['exit']==0 and not row['timed_out'] and not row['interrupted']:
                try:
                    stage_log(log,plan['stage'],NAMES,TARGETS)
                    if plan['stage']=='ctest':
                        result=junit(out/('ctest_'+plan['configuration']+'.xml'),NAMES)
                        row.update(expected=len(NAMES),executed=result['executed'],junit=result['junit'],test_ids=result['test_ids'])
                        row['binary_after']={t:identity(builds[plan['configuration']]/t) for t in TARGETS}
                        row['runtime_after']={x['name']:identity(x['command'][0]) for x in inventory['tests']}
                        if row['binary_before']!=row['binary_after']:raise RuntimeError('binary changed during CTest')
                        if row['runtime_before']!=row['runtime_after']:raise RuntimeError('CTest interpreter/executable changed during CTest')
                    row['status']='PASS'
                except (ValueError,OSError,RuntimeError,ET.ParseError) as error:
                    row.update(status='FAIL',reason=str(error))
            elif row['exit'] is not None:
                row['status']='FAIL'
            summary['rows'].append(row);summary['executed_stage_count']=len(summary['rows'])
            save(out/'SUMMARY.json',summary)
            if row['status']!='PASS':break
        summary['source_unchanged']=source_manifest(root)['sha256']==source['sha256']
        candidate=dict(summary,run_complete=True,status='PASS')
        # Validate the complete candidate in memory before publishing its marker.
        strict_gates(out,summary_override=candidate)
        summary=candidate
    except (ValueError,OSError,RuntimeError,KeyboardInterrupt,ET.ParseError,subprocess.SubprocessError) as error:
        summary.update(status='INCOMPLETE',run_complete=False,reason=str(error))
    save(out/'SUMMARY.json',summary)
    print(json.dumps({k:summary[k] for k in ['suite','run_id','run_complete','status','expected_stage_count','executed_stage_count']}))
    return 0 if summary['status']=='PASS' else 2


if __name__=='__main__':
    raise SystemExit(main())

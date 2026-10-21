"""小さい合成保存物だけで集計の負例を検査する。configure/build/audioを起動しない。"""
import copy
import argparse
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase62_aggregation import (CONFIGURATIONS, STAGES, EvidenceError, audit_legacy_gates,
                                  audit_legacy_rows, identity, read, strict_gates)
from phase62_gate_runner import NAMES, TARGETS

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
PINS=ROOT/'results/phase62_finish/aggregation/LEGACY_PROVENANCE.json'
OLD=ROOT/'build/phase62_dynamic_20261020/final_gates_v7'


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def fixture(path):
    path.mkdir(parents=True,exist_ok=False)
    source='a'*64;save(path/'SOURCE.json',dict(sha256=source,files=[]))
    expected=dict(schema=2,suite='phase62_deterministic_gates',run_id='synthetic-negative-test-fixture',
                  configurations=CONFIGURATIONS,ctest_names=NAMES,ctest_per_configuration=len(NAMES),
                  targets=TARGETS,expected_stage_count=6,stages=[],
                  provenance=dict(source_inventory_sha256=source,source_manifest=identity(path/'SOURCE.json')))
    summary=dict(schema=2,suite=expected['suite'],run_id=expected['run_id'],run_complete=True,status='PASS',
                 source_inventory_sha256=source,source_unchanged=True,expected_stage_count=6,executed_stage_count=6,rows=[])
    for cfg in CONFIGURATIONS:
        build=path/'fake_build'/cfg;build.mkdir(parents=True)
        archive=path/'executed_binaries'/cfg;archive.mkdir(parents=True)
        before,archives={},{}
        for target in TARGETS:
            (build/target).write_bytes(b'fixture-only-no-executable\n')
            shutil.copy2(build/target,archive/target)
            before[target]=identity(build/target);archives[target]=identity(archive/target)
        xml=path/('ctest_'+cfg+'.xml')
        root=ET.Element('testsuite',tests=str(len(NAMES)),failures='0',skipped='0',disabled='0')
        for name in NAMES:ET.SubElement(root,'testcase',name=name,classname=name,status='run',time='0.01')
        ET.ElementTree(root).write(xml)
        commands={
            'configure':['cmake','-S','/synthetic/never-executed','-B',str(build),'-DCMAKE_BUILD_TYPE='+cfg,'-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON'],
            'build':['cmake','--build',str(build),'--target',*TARGETS,'-j2'],
            'ctest':['ctest','--test-dir',str(build),'-R','^('+'|'.join(NAMES)+')$','--parallel','1','--output-on-failure','--output-junit',str(xml)],
        }
        for stage in STAGES:
            key=stage+'_'+cfg;plan=dict(id=key,stage=stage,configuration=cfg,command=commands[stage]);expected['stages'].append(plan)
            log=path/(key+'.log')
            if stage=='configure':text='-- Configuring done\n-- Generating done\n-- Build files have been written to: '+str(build)+'\n'
            elif stage=='build':text=''.join('[100%] Built target '+target+'\n' for target in TARGETS)
            else:text=''.join(f'{i+1}/{len(NAMES)} Test #{i+1}: {name} ....... Passed 0.01 sec\n' for i,name in enumerate(NAMES))+f'100% tests passed, 0 tests failed out of {len(NAMES)}\nTotal Test time (real) = 0.16 sec\n'
            log.write_text(text)
            row=dict(plan,exit=0,status='PASS',timed_out=False,interrupted=False,log=identity(log))
            if stage=='ctest':
                inventory=dict(tests=[dict(name=name,command=[str(build/TARGETS[i]),'--synthetic-only',name]) for i,name in enumerate(NAMES)])
                inventory_path=path/('ctest_inventory_'+cfg+'.json');save(inventory_path,inventory)
                runtimes={name:copy.deepcopy(before[TARGETS[i]]) for i,name in enumerate(NAMES)}
                runtime_archives={name:copy.deepcopy(archives[TARGETS[i]]) for i,name in enumerate(NAMES)}
                row.update(expected=len(NAMES),executed=len(NAMES),junit=identity(xml),binary_before=before,binary_after=copy.deepcopy(before),binary_archives=archives,
                           test_inventory=identity(inventory_path),runtime_before=runtimes,runtime_after=copy.deepcopy(runtimes),runtime_archives=runtime_archives)
            summary['rows'].append(row)
    save(path/'EXPECTED.json',expected)
    summary['expected_sha256']=identity(path/'EXPECTED.json')['sha256'];save(path/'SUMMARY.json',summary)
    return expected,summary


def old_predicate(summary):
    passed=bool(summary.get('rows')) and all(row.get('status')=='PASS' for row in summary['rows'])
    if 'expected_programs' in summary:passed &= summary.get('executed_programs')==len(summary['rows'])==summary['expected_programs']
    elif 'executed' in summary:passed &= summary.get('expected')==summary.get('executed')==len(summary['rows'])
    passed &= all(row.get('expected')==row.get('executed') for row in summary['rows'] if 'executed' in row and 'expected' in row)
    return passed


def mutate_xml(path,summary,change):
    file=path/'ctest_Debug.xml';tree=ET.parse(file);change(tree.getroot());tree.write(file)
    next(r for r in summary['rows'] if r['id']=='ctest_Debug')['junit']=identity(file)


def run(results=None,summary_path=None):
    results=HERE/'negative_results' if results is None else results.resolve()
    summary_path=HERE/'NEGATIVE_SUMMARY.json' if summary_path is None else summary_path.resolve()
    if summary_path.exists():raise RuntimeError('refusing an existing summary')
    results.mkdir(exist_ok=False)
    cases=[]
    def test(name,mutation,positive=False):
        p=results/name;expected,summary=fixture(p)
        mutation(p,expected,summary)
        save(p/'EXPECTED.json',expected)
        # Mutations update identities so semantic failures cannot hide behind a
        # trivial stale hash. The dedicated hash test changes this again below.
        summary['expected_sha256']=identity(p/'EXPECTED.json')['sha256']
        if name=='expected_sha_mismatch':summary['expected_sha256']='0'*64
        save(p/'SUMMARY.json',summary)
        try:
            certificate=strict_gates(p);accepted=certificate['status']=='PASS';reason='complete fixture'
        except (ValueError,OSError,ET.ParseError,KeyError) as error:
            accepted=False;reason=str(error)
        passed=accepted==positive
        cases.append(dict(id=name,status='PASS' if passed else 'FAIL',expected_accepted=positive,actual_accepted=accepted,reason=reason))
    test('complete_positive_control',lambda p,e,s:None,positive=True)
    test('interrupted_marker_false',lambda p,e,s:s.update(run_complete=False))
    test('missing_completion_marker',lambda p,e,s:s.pop('run_complete'))
    test('missing_schema',lambda p,e,s:s.pop('schema'))
    test('configure_only',lambda p,e,s:s.update(rows=s['rows'][:1],executed_stage_count=1))
    test('Release_only',lambda p,e,s:s.update(rows=s['rows'][:3],executed_stage_count=3))
    test('Debug_ctest_missing',lambda p,e,s:s.update(rows=s['rows'][:-1],executed_stage_count=5))
    test('duplicate_stage_id',lambda p,e,s:s['rows'].__setitem__(5,copy.deepcopy(s['rows'][2])))
    test('missing_stage_identity_field',lambda p,e,s:s['rows'][0].pop('configuration'))
    test('missing_exit',lambda p,e,s:s['rows'][0].pop('exit'))
    test('bool_exit_is_not_integer_zero',lambda p,e,s:s['rows'][0].update(exit=False))
    test('timeout_with_false_PASS',lambda p,e,s:s['rows'][2].update(timed_out=True))
    test('interruption_with_false_PASS',lambda p,e,s:s['rows'][2].update(interrupted=True))
    test('missing_timeout_field',lambda p,e,s:s['rows'][2].pop('timed_out'))
    test('configure_nonzero_exit',lambda p,e,s:s['rows'][0].update(exit=1))
    test('summary_count_forged_one',lambda p,e,s:s.update(expected_stage_count=1,executed_stage_count=1,rows=s['rows'][:1]))
    test('expected_Debug_removed',lambda p,e,s:e.update(configurations=['Release'],stages=e['stages'][:3],expected_stage_count=3))
    test('zero_tests',lambda p,e,s:mutate_xml(p,s,lambda root:root.clear()))
    test('skipped',lambda p,e,s:mutate_xml(p,s,lambda root:ET.SubElement(root.find('testcase'),'skipped')))
    test('failure',lambda p,e,s:mutate_xml(p,s,lambda root:ET.SubElement(root.find('testcase'),'failure')))
    test('error',lambda p,e,s:mutate_xml(p,s,lambda root:ET.SubElement(root.find('testcase'),'error')))
    test('duplicate_test_name',lambda p,e,s:mutate_xml(p,s,lambda root:root.findall('testcase')[1].set('name',NAMES[0])))
    test('JUnit_header_wrong',lambda p,e,s:mutate_xml(p,s,lambda root:root.set('tests',str(len(NAMES)+1))))
    test('test_disabled_status',lambda p,e,s:mutate_xml(p,s,lambda root:root.find('testcase').set('status','notrun')))
    test('missing_JUnit',lambda p,e,s:(p/'ctest_Debug.xml').unlink())
    test('source_changed',lambda p,e,s:s.update(source_unchanged=False))
    test('source_identity_mismatch',lambda p,e,s:s.update(source_inventory_sha256='0'*64))
    test('expected_sha_mismatch',lambda p,e,s:None)
    test('binary_identity_missing',lambda p,e,s:s['rows'][2].pop('binary_before'))
    test('runtime_interpreter_identity_missing',lambda p,e,s:s['rows'][2].pop('runtime_before'))
    test('binary_changed_during_run',lambda p,e,s:s['rows'][2]['binary_after'][TARGETS[0]].update(sha256='0'*64))
    test('build_log_truncated',lambda p,e,s:truncate_log(p,s,'build_Release'))
    test('ctest_log_truncated',lambda p,e,s:truncate_log(p,s,'ctest_Debug'))
    minimal={'rows':[{'id':'configure_Release','status':'PASS','exit':0}],'local_overall_go':False}
    save(results/'OLD_FALSE_PASS_REPRODUCTION.json',dict(summary=minimal,old_predicate_pass=old_predicate(minimal),
         old_manifest_copied_counts={'Release':16,'Debug':16},note='Exact vulnerable predicate copied from the pinned old assembler; no legacy evidence overwritten.'))
    legacy=audit_legacy_gates(OLD,read(PINS));save(results/'LEGACY_AUDIT.json',legacy)
    legacy_partial=copy.deepcopy(read(OLD/'SUMMARY.json'));legacy_partial['rows']=legacy_partial['rows'][:1]
    # Even when not subject to the new marker, the declared original six-stage
    # set is mandatory. This check exercises the common row predicate directly.
    from phase62_aggregation import rows_complete
    try:rows_complete(legacy['expected_stage_ids'],legacy_partial['rows'],6,1,require_timeout_fields=False);rejected=False
    except EvidenceError:rejected=True
    cases.append(dict(id='legacy_configure_only_exact_set_rejected',status='PASS' if rejected else 'FAIL',actual_accepted=not rejected))
    strata=ROOT/'build/phase62_dynamic_20261020/final_dynamic_strata'
    expected,original=read(strata/'EXPECTED.json'),read(strata/'SUMMARY.json')
    audit_legacy_rows(expected,original)
    duplicate=copy.deepcopy(original);duplicate['rows'][-1]=copy.deepcopy(duplicate['rows'][0])
    try:audit_legacy_rows(expected,duplicate);rejected=False
    except EvidenceError:rejected=True
    cases.append(dict(id='other_suite_duplicate_id_rejected',status='PASS' if rejected else 'FAIL',old_predicate_pass=old_predicate(duplicate),actual_accepted=not rejected))
    cli_path=results/'LEGACY_CLI.json'
    cli=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/phase62_aggregation.py'),'legacy',str(OLD),
        '--pins',str(PINS),'--output',str(cli_path)],capture_output=True,text=True)
    cli_result=read(cli_path)
    valid=cli.returncode==2 and cli_result.get('status')=='INCOMPLETE' and cli_result.get('execution_completeness')=='PASS'
    cases.append(dict(id='INCOMPLETE_legacy_cli_exit_nonzero',status='PASS' if valid else 'FAIL',exit=cli.returncode,
                      execution_completeness=cli_result.get('execution_completeness'),overall_status=cli_result.get('status')))
    save(results/'CASES.json',cases)
    summary=dict(suite='phase62_aggregation_negative_tests',expected=36,executed=len(cases),
                 passed=sum(x['status']=='PASS' for x in cases),failed=sum(x['status']!='PASS' for x in cases),
                 negative_cases=35,positive_controls=1,legacy_execution_status=legacy['execution_completeness'],
                 legacy_provenance_status=legacy['status'],source_mode='synthetic fixture + pinned original logs/JUnit; no products executed',
                 status='PASS' if len(cases)==36 and all(x['status']=='PASS' for x in cases) else 'FAIL',local_overall_go=False)
    save(summary_path,summary);print(json.dumps(summary,ensure_ascii=False))
    return 0 if summary['status']=='PASS' else 2


def truncate_log(path,summary,key):
    file=path/(key+'.log');file.write_text(file.read_text().splitlines()[0]+'\n')
    next(r for r in summary['rows'] if r['id']==key)['log']=identity(file)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--summary',type=Path)
    args=parser.parse_args();raise SystemExit(run(args.output,args.summary))

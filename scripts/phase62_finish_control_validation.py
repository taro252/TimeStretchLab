"""Phase62外部台帳の局所試験。実出力は常に直列で、完全なID集合を検査する。"""
import argparse
import json
import subprocess
from pathlib import Path
from phase62_evidence import identity, source_manifest, verify_architecture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd();out = args.output.resolve();out.mkdir()
    build = args.build.resolve();input = args.input.resolve()
    native = build/'phase62_loop_speed_ledger_native';unit = build/'phase62_loop_speed_ledger_tests'
    source = source_manifest(root)
    ids = ['initial_duplicate_no_slot', 'ready_before_resume', 'started_history_immutable',
           'all_replaced_receipts_retained', 'limit_before_side_effects_duplicate_and_repause',
           'stale_context_reason', 'stop_terminalizes_without_rewriting_past', 'owners_retired']
    jobs = [dict(id='unit4096', command=[str(unit)], count=10)]
    for preset,limit,kind in [('candidate',6,'external'), ('baseline',6,'external'),
                              ('candidate',4096,'external'), ('baseline',6,'stopped')]:
        name = f'{preset}_{limit}_{kind}'
        command = [str(native),str(input),preset,str(out/name),str(limit)]
        if kind=='stopped':command.append('stopped')
        jobs.append(dict(id=name,command=command,count=8))
    write = lambda name,data:(out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    architecture = verify_architecture([unit,native]);assert architecture['PASS']
    write('EXPECTED.json',dict(schema=1,suite='loop_speed_ledger',source=source,
        binary=[identity(unit),identity(native)],input=identity(input),architecture=architecture,
        stage_ids=[job['id'] for job in jobs],native_case_ids=ids,expected_programs=len(jobs),
        expected_checks=sum(job['count'] for job in jobs),commands=jobs,serial_audio=True))
    rows=[]
    for job in jobs:
        assert source_manifest(root)['sha256']==source['sha256']
        timed=False;log=out/(job['id']+'.log')
        with log.open('w') as stream:
            try:code=subprocess.run(job['command'],stdout=stream,stderr=subprocess.STDOUT,timeout=180).returncode
            except subprocess.TimeoutExpired:code=None;timed=True
        valid=code==0;executed=0
        if job['id']=='unit4096':
            result=json.loads(log.read_text()) if valid else {}
            executed=result.get('executed',0);valid &= result.get('expected')==executed==10 and result.get('PASS') is True
        else:
            folder=out/job['id'];path=folder/'SUMMARY.json'
            result=json.loads(path.read_text()) if path.exists() else {}
            checks=[json.loads(line) for line in (folder/'checks.jsonl').read_text().splitlines()] if (folder/'checks.jsonl').exists() else []
            executed=len(checks)
            valid &= result.get('schema')==1 and result.get('run_complete') is True and result.get('status')=='PASS'
            valid &= result.get('expected')==result.get('executed')==executed==8
            valid &= sorted(row.get('id','') for row in checks)==sorted(ids) and all(row.get('status')=='PASS' for row in checks)
        valid &= source_manifest(root)['sha256']==source['sha256']
        rows.append(dict(id=job['id'],status='INCOMPLETE' if timed else 'PASS' if valid else 'FAIL',
                         exit=code,expected=job['count'],executed=executed,log=identity(log)))
        complete=len(rows)==len(jobs)
        write('SUMMARY.json',dict(schema=1,run_complete=complete,expected_programs=len(jobs),executed_programs=len(rows),
            expected_checks=sum(j['count'] for j in jobs),executed_checks=sum(r['executed'] for r in rows),rows=rows,
            status='PASS' if complete and all(r['status']=='PASS' for r in rows) else 'INCOMPLETE',local_overall_go=False))
        print(job['id'],rows[-1]['status'],flush=True)
        if not valid:return 1
    return 0


if __name__=='__main__':raise SystemExit(main())

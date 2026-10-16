"""容量中断を保持し、未完了の動的行列を同じ条件・参照で別保存先へ再実行する。"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from phase57_study import ROOT, sha


def main():
    out = ROOT/'results/phase59_fix/validation_recovery_final'
    data = ROOT/'build/phase59_fix_artifacts/validation_recovery_final'
    out.mkdir(); data.mkdir()
    frozen = ROOT/'build/phase59_fix_artifacts/final'
    expected = json.loads((ROOT/'results/phase59_fix/FINAL_CANDIDATE.json').read_text())
    manifest = dict(reason='dynamic_longが1件一致後、既存4GiB停止基準で中断。PCM不一致ではない。',
                    original_log=str(ROOT/'build/phase59_fix_artifacts/validation_final/dynamic_long.log'),
                    original_log_sha256=sha(ROOT/'build/phase59_fix_artifacts/validation_final/dynamic_long.log'),
                    frozen=str(frozen), driver_sha256=sha(Path(__file__)),
                    admission_free_bytes=4*1024**3+512*1024**2,
                    trial_floor_bytes=4*1024**3, conditions_reduced=False)
    (out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    rows=[]
    for name, script, suite, binary in (
        ('dynamic_long', 'phase59_study.py', 'long', 'phase59_check'),
        ('incremental_chunks', 'phase59_incremental_study.py', 'chunks', 'phase59_progressive_replay'),
        ('incremental_formats', 'phase59_incremental_study.py', 'formats', 'phase59_progressive_replay')):
        while shutil.disk_usage(ROOT).free < manifest['admission_free_bytes']:
            (out/'waiting.json').write_text(json.dumps(dict(stage=name, free_bytes=shutil.disk_usage(ROOT).free,
                                                           needed_bytes=manifest['admission_free_bytes'], unix=time.time()))+'\n')
            time.sleep(15)
        command=[sys.executable, '-B', str(ROOT/'scripts'/script), '--suite', suite,
                 '--binary', str(frozen/binary), '--output', str(data/name)]
        start=time.time()
        with (data/(name+'.log')).open('x') as log:
            process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        result=data/name/'summary.json'
        row=dict(name=name, command=command, exit=process.returncode, wall_s=time.time()-start,
                 result=json.loads(result.read_text()) if result.exists() else None,
                 log=str(data/(name+'.log')))
        rows.append(row);(out/'driver.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(name, process.returncode, flush=True)
        assert row['exit']==0 and row['result']['PASS'], 'Recovery failed; all evidence retained'
    initial=ROOT/'results/phase59_fix/validation_final'
    while not (initial/'summary.json').exists():time.sleep(15)
    original=json.loads((initial/'summary.json').read_text())
    initial_rows=json.loads((initial/'driver.json').read_text())
    failures=[r for r in initial_rows if r['exit']]
    assert len(failures)==1 and failures[0]['name']=='dynamic_long', failures
    assert original['fixed58_pcm_sessions']==6216 and original['fixed57_pcm_sessions']==51344
    assert all(sha(ROOT/path)==digest for path,digest in expected['source_sha256'].items())
    effective_rows=[r for r in initial_rows if r['exit']==0]+rows
    total=sum(r['result']['pcm_sessions'] for r in effective_rows if r['name'].startswith(('dynamic_','incremental_')))
    assert total==1140, total
    ledger=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in data.rglob('*') if p.is_file()]
    (out/'artifacts.json').write_text(json.dumps(ledger,indent=2)+'\n')
    effective=dict(original, PASS=True, failures=[], stages=len(effective_rows), dynamic_pcm_sessions=total,
                   initial_attempt_summary=str(initial/'summary.json'),
                   initial_attempt_summary_sha256=sha(initial/'summary.json'),
                   interruption_retained=True, interruption_was_pcm_mismatch=False,
                   recovery_manifest=str(out/'manifest.json'), recovery_artifacts=str(out/'artifacts.json'),
                   complete_matrix_conditions_unchanged=True)
    (out/'summary.json').write_text(json.dumps(effective,indent=2)+'\n')
    (initial/'effective_summary.json').write_text(json.dumps(effective,indent=2)+'\n')
    print('effective full quality PASS',total,6216,51344,flush=True)


if __name__=='__main__':main()

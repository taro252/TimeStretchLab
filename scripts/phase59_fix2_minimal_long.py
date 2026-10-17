"""自分の音声試験の休止後と85.821秒を超える固定PCM連続再生を区別する。"""
import json
import shutil
import subprocess
import time
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha
from phase59_fix2_minimal import analyze


def main():
    # OS解析によるCPU/メモリ負荷を自分で重ねない。
    for name in ['legacy_old_math','legacy_current','legacy_synced']:
        while not (OUT/('LEGACY_TRACE_ANALYSIS_'+name+'.json')).exists():time.sleep(1)
    out=OUT/'minimal_long';out.mkdir();data=ROOT/'build/phase59_fix2_artifacts/minimal_long';data.mkdir()
    binary=data/'sourcenode_frozen';shutil.copy2(ROOT/'build/phase59_fix2_sourcenode',binary)
    manifest=dict(binary=str(binary),binary_sha256=sha(binary),
                  scope='短尺休止後起動と90秒途中再生。休止は自分の試験のみであり、他アプリを含む装置idleの証明ではない。',
                  plan=[dict(mode='direct',seconds=2,own_audio_quiet_seconds=30),
                        dict(mode='direct',seconds=90,own_audio_quiet_seconds=0),
                        dict(mode='fifo',seconds=90,own_audio_quiet_seconds=0)])
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    rows=[]
    for i,case in enumerate(manifest['plan']):
        if shutil.disk_usage(ROOT).free<8*1024**3:raise RuntimeError('Disk floor reached')
        time.sleep(case['own_audio_quiet_seconds'])
        folder=data/f'{i}_{case["mode"]}'
        command=[str(binary),case['mode'],'candidate',str(case['seconds']),str(folder)]
        with (data/(folder.name+'.log')).open('x') as log:
            p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=case['seconds']+30)
        row=dict(case=case,command=command,exit=p.returncode,**analyze(folder));row['PASS']=p.returncode==0
        rows.append(row);(out/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
        print(case,'exit',p.returncode,'sample',row['summary']['sample_errors'],flush=True)
    summary=dict(sessions=len(rows),passed=sum(r['PASS'] for r in rows),
                 direct_clock_discontinuities=sum(len(r['clock_jumps']) for r in rows if r['case']['mode']=='direct'),
                 fifo_clock_discontinuities=sum(len(r['clock_jumps']) for r in rows if r['case']['mode']=='fifo'),
                 physical_audio_continuity_verified=False,failures_preserved=True)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()

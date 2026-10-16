"""最終固定実行体で全190動的条件と固定・EOS・旧製品を直列に実行する。"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from phase57_study import ROOT,sha


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--frozen',type=Path,required=True)
    parser.add_argument('--tag',default='final');args=parser.parse_args();frozen=args.frozen.resolve()
    for name in ('validation_'+args.tag,'checks_'+args.tag):
        prerequisite=ROOT/'results/phase59_fix'/name/'summary.json'
        if name.startswith('validation_') and prerequisite.with_name('effective_summary.json').exists():
            prerequisite=prerequisite.with_name('effective_summary.json')
        assert prerequisite.exists() and json.loads(prerequisite.read_text())['PASS'],str(prerequisite)
    # 実機開始前に圧縮・照合を完了し、成功PCMの作業領域を再利用可能にする。
    subprocess.run([sys.executable,'-B','scripts/phase59_fix_archive_success.py','--tag',args.tag],cwd=ROOT,check=True)
    out=ROOT/'results/phase59_fix'/('device_'+args.tag);out.mkdir()
    data=ROOT/'build/phase59_fix_artifacts'/('device_'+args.tag);data.mkdir();history=[]
    expected={str(p):sha(p) for p in frozen.iterdir() if p.is_file()}
    (out/'manifest.json').write_text(json.dumps(dict(frozen=str(frozen),binary_sha256=expected,
        serial_audio=True,minimum_free_bytes=2*1024**3,driver_sha256=sha(Path(__file__))),indent=2)+'\n')
    def run(name,command):
        if shutil.disk_usage(ROOT).free<2*1024**3:raise RuntimeError('Disk floor reached')
        command=list(map(str,command));start=time.time()
        with (data/(name+'.log')).open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        folder=data/name;summary=folder/'summary.json'
        row=dict(name=name,command=command,exit=p.returncode,wall_s=time.time()-start,
                 log=str(data/(name+'.log')),result=json.loads(summary.read_text()) if summary.exists() else None)
        history.append(row);(out/'driver.json').write_text(json.dumps(history,indent=2)+'\n');print(name,p.returncode,flush=True)
        return row
    for suite in ('normal','load','lifecycle','burst','materials','long'):
        name='dynamic_'+suite
        run(name,[sys.executable,'-B','scripts/phase59_native_validation.py','--suite',suite,'--output',data/name,
                  '--binary',frozen/'phase59_native','--minimum-free-gib','2'])
    for preset in ('candidate','baseline'):
        for speed in (400000,1000000,2000000):
            for cpu in (0,2):
                name=f'fixed_{preset}_{speed}_cpu{cpu}'
                run(name,[sys.executable,'-B','scripts/phase58_fix_repeat.py','--output',data/name,'--binary',frozen/'phase58_native',
                    '--repeats','3','--speed',speed,'--preset',preset,'--cpu',cpu,'--extra=--worker=workgroup',
                    '--extra=--resident-input=on','--extra=--profile=block','--extra=--sample-thread=on'])
    # 既知の固定長尺失敗条件は独立セッションで3反復する。
    work=data/'fixed_working';work.mkdir()
    sources=[ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav',ROOT/'results/phase56/long/chain_300s.wav']
    fixed=[]
    for source in sources:
        for preset in ('candidate','baseline'):
            raw=work/'reference.f32';oracle=ROOT/'build/phase58_frozen/product_reference'
            command=[str(oracle),str(source),'2000000',preset,str(raw)]
            result=subprocess.run(command,capture_output=True,text=True,check=True,timeout=1800);reference=json.loads(result.stdout)
            assert sha(raw)==reference['pcm_sha256']
            repeats=3 if source==sources[0] else 1
            for repeat in range(repeats):
                name=f'fixed_long_{source.parent.name}_{preset}_{repeat}'
                row=run(name,[frozen/'phase59_fix_fixed_probe',source,'2000000',preset,raw,reference['output_frames'],reference['pcm_sha256'],
                    data/name,'normal','0','2','0','0','0','--worker=workgroup','--resident-input=on','--profile=block','--sample-thread=on'])
                row['reference_command']=command;row['reference']=reference;row['input_sha256']=sha(source)
                row['PASS']=row['exit']==0 and bool((row['result'] or {}).get('pcm_complete_exact'))
                if not row['PASS']:shutil.copy2(raw,data/name/'failure_reference.f32')
                fixed.append(row);(out/'fixed_long_rows.json').write_text(json.dumps(fixed,indent=2)+'\n')
    # 同じプロセスでEOS完了後に次のengine/sessionを作る。閾値は通常試験と同じ。
    source=ROOT/'results/phase59/native_smoke_v2/inputs/boundary_float_stereo_48000.wav'
    for preset in ('candidate','baseline'):
        raw=work/'eos_reference.f32';oracle=ROOT/'build/phase58_frozen/product_reference'
        reference=json.loads(subprocess.check_output([str(oracle),str(source),'2000000',preset,str(raw)],text=True))
        assert sha(raw)==reference['pcm_sha256']
        name='eos_repeat_'+preset
        row=run(name,[frozen/'phase58_native',source,'2000000',preset,raw,reference['output_frames'],reference['pcm_sha256'],data/name,
                  'repeat','0','0','0','0','0','--sessions=20','--worker=workgroup','--resident-input=on','--profile=block','--sample-thread=on'])
        sessions=[json.loads(p.read_text()) for p in sorted((data/name).glob('session_*/summary.json'))]
        row['result']=dict(PASS=row['exit']==0 and len(sessions)==20 and all(s['PASS'] and s['pcm_complete_exact'] for s in sessions),
                           sessions=len(sessions),passed=sum(bool(s['PASS']) for s in sessions),
                           pcm_complete_exact=sum(bool(s['pcm_complete_exact']) for s in sessions))
        with (data/name/'summary.json').open('x') as file:file.write(json.dumps(row['result'],indent=2)+'\n')
        if not row['result']['PASS']:shutil.copy2(raw,data/name/'failure_reference.f32')
        (out/'driver.json').write_text(json.dumps(history,indent=2)+'\n')
    # このdriverは別の新規build/保存先を使用し、旧バイナリを保持する。
    run('legacy_product',[sys.executable,'-B','scripts/phase59_fix_legacy.py','--tag',args.tag,'--build-probe'])
    assert all(sha(path)==digest for path,digest in expected.items()),'Frozen artifact changed'
    dynamic=[r for r in history if r['name'].startswith('dynamic_')]
    assert sum(r['result']['sessions'] for r in dynamic if r['result'])==190
    summary=dict(PASS=all(r['exit']==0 and (r['result'] is None or bool(r['result'].get('PASS'))) for r in history)
                 and all(r['PASS'] for r in fixed),history=history,
                 dynamic_sessions=sum(r['result']['sessions'] for r in dynamic if r['result']),
                 dynamic_passed=sum(r['result']['passed'] for r in dynamic if r['result']),
                 fixed_long_sessions=len(fixed),fixed_long_passed=sum(r['PASS'] for r in fixed))
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return 0 if summary['PASS'] else 2


if __name__=='__main__':raise SystemExit(main())

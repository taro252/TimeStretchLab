"""固定済み実行体と起動時刻プローブを同じ入力で直列比較する。"""
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT, sha
from phase59_native_validation import compare_pcm, wav_info


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--repeats', type=int, default=20)
    args = parser.parse_args()
    assert 0 < args.repeats <= 200
    out = ROOT / 'results/phase59_fix/startup_before'
    data = ROOT / 'build/phase59_fix_artifacts/startup_before'
    out.mkdir(); data.mkdir(); rows = []
    source = ROOT / 'results/phase59/native_smoke_v2/inputs/boundary_float_stereo_48000.wav'
    requests = ROOT / 'results/phase59/native_smoke_v2/case_000/requests.csv'
    reference = ROOT / 'build/phase59_frozen/captured_reference'
    versions = [('phase58_fix', ROOT / 'build/phase58_fix_frozen/candidate_v3_native', False),
                ('phase59_v7', ROOT / 'build/phase59_frozen/native_v7', True),
                ('phase59_final', ROOT / 'build/phase59_frozen/final/phase59_native', True),
                ('startup_probe', ROOT / 'build/phase59_fix_startup_probe', True)]
    meta = wav_info(source)
    fixed_raw = data / 'fixed_reference.f32'
    command = [str(ROOT / 'build/phase58_frozen/product_reference'), str(source), '500000', 'candidate', str(fixed_raw)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    fixed = json.loads(result.stdout); assert sha(fixed_raw) == fixed['pcm_sha256']
    manifest = dict(repeats=args.repeats, preset='candidate', initial_speed=500000,
        input=str(source), input_sha256=sha(source), metadata=meta, requests=str(requests), requests_sha256=sha(requests),
        binaries={label:dict(path=str(binary),sha256=sha(binary)) for label,binary,_ in versions},
        reference_sha256=sha(reference), artifact_directory=str(data), minimum_free_bytes=1024**3,
        expected_next_working_bytes=32*1024**2, comparison='固定58Fixと動的59は要求列が異なる。起動要求前の同じ初期速度・入力・SourceNode構成を比較し、PCMは各自の同一計画参照で照合。')
    (out / 'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    # 版ごとの時間帯偏りを減らすため、各反復内で全版を順に実行する。
    for repeat in range(args.repeats):
        for label,binary,dynamic in versions:
            if shutil.disk_usage(ROOT).free < manifest['minimum_free_bytes'] + manifest['expected_next_working_bytes']:
                raise RuntimeError('空き容量下限に達したため未開始条件を中断')
            folder=data/f'{repeat:03d}_{label}'; capture=data/'capture.f32'; replay=data/'reference.f32'
            command=[str(binary),str(source),'500000','candidate',
                'capture' if dynamic else str(fixed_raw),str(int(meta['frames']*2.5)+2) if dynamic else str(fixed['output_frames']),
                '-' if dynamic else fixed['pcm_sha256'],str(folder),'normal','0','0','0','0','0',
                '--worker=workgroup','--resident-input=on','--profile=block','--sample-thread=on']
            if dynamic:command += ['--capture-path='+str(capture),'--speed-requests='+str(requests)]
            start=time.time()
            with (data/f'{repeat:03d}_{label}.log').open('x') as log:
                result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=60)
            summary=json.loads((folder/'summary.json').read_text())
            callbacks=list(csv.DictReader((folder/'callbacks.csv').open()))
            row=dict(repeat=repeat,label=label,command=command,exit=result.returncode,native=summary,
                callback_prefix=callbacks[:8],wall_s=time.time()-start,free_bytes=shutil.disk_usage(ROOT).free)
            if dynamic:
                command=[str(reference),str(source),'500000','candidate',str(folder),str(replay),str(folder/'reference')]
                result=subprocess.run(command,capture_output=True,text=True,timeout=120)
                (folder/'reference.log').write_text(result.stdout+result.stderr)
                row['reference_exit']=result.returncode
                if result.returncode==0:
                    row['reference']=json.loads((folder/'reference.json').read_text())
                    row['pcm']=compare_pcm(capture,replay,0,replay.stat().st_size,meta['channels'],bool(summary['eos']),folder)
                else:row['pcm']=dict(PASS=False,reason='reference_failed')
            else:row['pcm']=dict(PASS=bool(summary['pcm_complete_exact']))
            if (folder/'startup.csv').exists():row['startup']=list(csv.DictReader((folder/'startup.csv').open()))
            row['clock_pass']=all(summary[k]==0 for k in ['host_missing','host_backwards','host_cadence_errors','sample_errors','hal_misses'])
            row['PASS']=bool(summary['PASS']) and row['pcm']['PASS']
            if not row['PASS'] and dynamic:
                for source_file,name in [(capture,'failure_capture.f32'),(replay,'failure_reference.f32')]:
                    if source_file.exists():shutil.copy2(source_file,folder/name)
            row['artifacts']=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in folder.rglob('*') if p.is_file()]
            rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
            print(repeat,label,'PASS' if row['PASS'] else 'FAIL','clock',row['clock_pass'],flush=True)
    summary=dict(sessions=len(rows),passed=sum(r['PASS'] for r in rows),clock_failures=sum(not r['clock_pass'] for r in rows),
        by_version={label:dict(sessions=sum(r['label']==label for r in rows),passed=sum(r['label']==label and r['PASS'] for r in rows),
            clock_failures=sum(r['label']==label and not r['clock_pass'] for r in rows)) for label,_,_ in versions},
        original_failures_preserved=True,root_cause_identified=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()

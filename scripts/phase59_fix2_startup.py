"""C固定・D動的要求なし・E動的要求ありを同じ入力・装置で比較する。"""
import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha
from phase59_native_validation import compare_pcm, wav_info


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--tag',default='');parser.add_argument('--binary-dir',type=Path,default=ROOT/'build')
    args=parser.parse_args();assert 1<=args.repeats<=30
    name='startup_cde'+('_'+args.tag if args.tag else '')
    out=OUT/name;out.mkdir();data=ROOT/'build/phase59_fix2_artifacts'/name;data.mkdir()
    source=ROOT/'results/phase59/native_smoke_v2/inputs/boundary_float_stereo_48000.wav'
    requests=ROOT/'results/phase59/native_smoke_v2/case_000/requests.csv'
    empty=data/'no_requests.csv';empty.write_text('at_output,target_micros\n')
    meta=wav_info(source);raw=data/'fixed_reference.f32'
    oracle=ROOT/'build/phase58_frozen/product_reference'
    reference=json.loads(subprocess.check_output([str(oracle),str(source),'500000','candidate',str(raw)],text=True))
    assert sha(raw)==reference['pcm_sha256']
    frozen={}
    for name in ['phase59_fix2_fixed_probe','phase59_fix2_dynamic_probe']:
        target=data/name;shutil.copy2(args.binary_dir/name,target);frozen[name]=dict(path=str(target),sha256=sha(target))
    manifest=dict(input=str(source),input_sha256=sha(source),requests=str(requests),requests_sha256=sha(requests),
                  fixed_reference=reference,reference_binary_sha256=sha(oracle),binaries=frozen,repeats=args.repeats,
                  initial_speed=500000,preset='candidate',window_seconds=1.2,serial_audio=True,
                  comparison='同じ初期速度・入力・SourceNode形式。Cは固定、Dは要求0件、Eは元のPhase59要求列。PCMは独立旧参照で接頭部を照合。')
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    rows=[]
    for repeat in range(args.repeats):
        for label,dynamic,request_file in [('C_fixed',False,None),('D_dynamic_no_request',True,empty),('E_dynamic_requests',True,requests)]:
            folder=data/f'{repeat}_{label}';capture=folder.with_suffix('.capture.f32');replay=folder.with_suffix('.reference.f32')
            binary=data/('phase59_fix2_dynamic_probe' if dynamic else 'phase59_fix2_fixed_probe')
            command=[str(binary),str(source),'500000','candidate','capture' if dynamic else str(raw),
                     str(int(meta['frames']*2.5)+2) if dynamic else str(reference['output_frames']),
                     '-' if dynamic else reference['pcm_sha256'],str(folder),'normal','1.2','0','0','0','0',
                     '--worker=workgroup','--resident-input=on','--profile=block','--sample-thread=on','--output-notify=on']
            if dynamic:command += ['--capture-path='+str(capture),'--speed-requests='+str(request_file)]
            with (data/(folder.name+'.log')).open('x') as log:
                result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=90)
            summary=json.loads((folder/'summary.json').read_text())
            if dynamic:
                reference_command=[str(ROOT/'build/phase59_frozen/captured_reference'),str(source),'500000','candidate',str(folder),str(replay),str(folder/'reference')]
                with (folder/'reference.log').open('x') as log:
                    replay_result=subprocess.run(reference_command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=180)
                pcm=compare_pcm(capture,replay,0,replay.stat().st_size,meta['channels'],bool(summary['eos']),folder) if replay_result.returncode==0 else dict(PASS=False)
            else:pcm=dict(PASS=bool(summary['pcm_prefix_exact']),complete=bool(summary['pcm_complete_exact']))
            callback_rows=list(csv.DictReader((folder/'callbacks.csv').open()));jumps=[]
            for a,b in zip(callback_rows,callback_rows[1:]):
                if a['epoch']!=b['epoch'] or not(int(a['flags'])&int(b['flags'])&1):continue
                error=float(b['sample_time'])-float(a['sample_time'])-int(a['requested'])
                if abs(error)>2:jumps.append(dict(previous=a,current=b,extra_frames=error,initial_pair=int(b['sequence'])==2))
            row=dict(label=label,repeat=repeat,command=command,exit=result.returncode,native=summary,pcm=pcm,clock_jumps=jumps,
                     callback_prefix=callback_rows[:5],PASS=result.returncode==0 and bool(pcm['PASS']))
            rows.append(row);(out/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            print(repeat,label,result.returncode,'sample',summary['sample_errors'],'pcm',pcm['PASS'],flush=True)
    summary=dict(sessions=len(rows),passed=sum(r['PASS'] for r in rows),
                 clock_discontinuities=sum(len(r['clock_jumps']) for r in rows),failures_preserved=True,
                 by_configuration={label:dict(sessions=sum(r['label']==label for r in rows),passed=sum(r['label']==label and r['PASS'] for r in rows)) for label in ['C_fixed','D_dynamic_no_request','E_dynamic_requests']},
                 startup_root_cause_identified=False)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()

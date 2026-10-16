"""Compare preserved and rebuilt legacy device executables after heavy work ends."""
import datetime
import json
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT,sha

out=ROOT/'results/phase58_fix/legacy_device';out.mkdir(exist_ok=False)
source=ROOT/'results/phase31/input/mix.wav';rows=[]
binaries={label:ROOT/path for label,path in (('original','build/phase58_fix_frozen/phase54_native'),('rebuilt','build/phase54_native'))}
(out/'manifest.json').write_text(json.dumps(dict(input=str(source),input_sha256=sha(source),
    binaries={k:dict(path=str(p),sha256=sha(p)) for k,p in binaries.items()},
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    scope='Existing Phase54 fixed EOS and dynamic lifecycle regression; new Phase58 Fix is not linked'),indent=2)+'\n')
for label,binary in binaries.items():
    for mode in ('eos','smoke'):
        for preset in ('candidate','baseline'):
            folder=out/f'{label}_{mode}_{preset}'
            cmd=[str(binary),str(source),preset,'2.0',str(folder),mode,'64']
            start=time.monotonic();at=datetime.datetime.now(datetime.timezone.utc).isoformat()
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
            (out/(folder.name+'.log')).write_text(p.stdout+p.stderr)
            path=folder/'summary.txt';values={}
            if path.exists():values=dict(x.split('=',1) for x in path.read_text().splitlines() if '=' in x)
            rows.append(dict(label=label,mode=mode,preset=preset,command=cmd,start_utc=at,elapsed_s=time.monotonic()-start,
                exit=p.returncode,summary=values,PASS=p.returncode==0 and all(values.get(k)=='PASS' for k in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','PCM_CORRECTNESS','VERDICT'))))
            (out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n');print(folder.name,p.returncode,flush=True)
s=dict(PASS=all(r['PASS'] for r in rows),executions=len(rows),passed=sum(r['PASS'] for r in rows),failed=sum(not r['PASS'] for r in rows))
(out/'summary.json').write_text(json.dumps(s,indent=2)+'\n');print(s,flush=True)
raise SystemExit(0 if s['PASS'] else 2)

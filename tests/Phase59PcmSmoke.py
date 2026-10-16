"""Regression smoke only; independent baseline references are used by the full study."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture

def call(command):
    p=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=240)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)

reference,check,replay,captured=map(Path,sys.argv[1:])
with tempfile.TemporaryDirectory(prefix='phase59_pcm_') as temporary:
    root=Path(temporary);source=root/'boundary.wav';fixture(source,48000,2,3,'boundary',4)
    for initial,targets in [(400000,[410000,2000000,400000]),(490000,[500000,490000]),(2000000,[1990000,400000])]:
        for preset in ('candidate','baseline'):
            folder=root/f'{initial}_{preset}';folder.mkdir();schedule=folder/'requests.csv';schedule.write_text('at_output,target_micros\n'+''.join(f'{16384+i*32768},{s}\n' for i,s in enumerate(targets)))
            raw=folder/'reference.f32';ref=folder/'reference';actual=folder/'actual'
            call([reference,source,initial,preset,schedule,raw,ref]);call([check,source,initial,preset,schedule,raw,ref,actual,'5003'])
            assert json.loads(actual.with_suffix('.json').read_text())['PASS']
    schedule=root/'incremental.csv';schedule.write_text('at_output,target_micros\n16384,500000\n65536,490000\n')
    for chunk in ('1024','7168','8192','32768','131072','5003','irregular'):
        folder=root/('chunk_'+chunk);folder.mkdir();actual=folder/'actual.f32';expected=folder/'expected.f32'
        call([replay,source,490000,'candidate',schedule,actual,folder/'replay',chunk]);call([captured,source,490000,'candidate',folder/'replay',expected,folder/'reference'])
        assert actual.read_bytes()==expected.read_bytes(),'Progressive PCM bits differ'
        assert (folder/'replay/dynamic_map.nodes.bin').read_bytes()==(folder/'reference.nodes.bin').read_bytes()
print('PASS 6 logical full-bit cases, 7 progressive chunks; state/plan/density/map/PCM')

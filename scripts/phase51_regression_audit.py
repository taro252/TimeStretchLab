#!/usr/bin/env python3
"""Read-only frozen evidence audit; copies are not regenerated references."""
import csv,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase51'
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--regenerate',action='store_true');args=parser.parse_args()
    rows=[]
    for manifest in ('results/phase12/golden/manifest.csv','results/phase28/golden/manifest.csv'):
        for entry in csv.DictReader((ROOT/manifest).open()):
            if entry['speed'] not in ('0.50','0.60','0.70','0.75','0.80'):continue
            golden=ROOT/entry['output_path'];stream=ROOT/f'results/phase36/raw/golden_{entry["name"]}_{entry["speed"].replace(".","")}.wav'
            actual=sha(golden);copy=sha(stream);assert actual==copy==entry['output_sha256']
            regenerated=None
            if args.regenerate:
                path=OUT/'golden_rebuilt'/f'{entry["name"]}_{entry["speed"].replace(".","")}.wav';path.parent.mkdir(exist_ok=True)
                if path.exists():raise ValueError('Fresh regenerated WAV required')
                result=subprocess.run([str(ROOT/'build/phase51_sim'),str(ROOT/entry['input_path']),str(path),entry['speed'],'-','512'],capture_output=True,text=True,timeout=120)
                path.with_suffix('.log').write_text(result.stdout+result.stderr)
                assert result.returncode==0 and sha(path)==actual
                regenerated=str(path)
            rows.append(dict(source=entry['name'],speed=entry['speed'],sha256=actual,match=True,new_build_waveform=regenerated))
    assert len(rows)==25
    (OUT/'golden_audit.json').write_text(json.dumps(rows,indent=2))
    # Compare current tracked evidence byte-for-byte with the Phase50 commit.
    protected=[]
    files=subprocess.check_output(['git','ls-tree','-r','--name-only','9933773','results'],cwd=ROOT,text=True).splitlines()
    for name in files:
        if not any(name.startswith('results/phase'+phase+'/') for phase in ('12','28','34','37','41','42','43','44','45','46','47','48','49','50')):continue
        previous=subprocess.check_output(['git','rev-parse','9933773:'+name],cwd=ROOT,text=True).strip()
        current=subprocess.check_output(['git','hash-object',name],cwd=ROOT,text=True).strip()
        assert previous==current,name;protected.append(dict(path=name,git_blob_sha=previous))
    (OUT/'protected_evidence.json').write_text(json.dumps(protected,indent=2));print('Golden25 read-only match; tracked older evidence unchanged:',len(protected))
if __name__=='__main__':main()

"""Read-only review of Phase 53 evidence and frozen assets; fresh output only."""
import argparse
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path
from phase53_sessions import ROOT, verify_run

BASE = '233c773bbc77e5824c36134915f68d6d3a0d581e'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def audit():
    golden = []
    for phase in ('phase12', 'phase28'):
        with (ROOT/f'results/{phase}/golden/manifest.csv').open() as stream:
            for row in csv.DictReader(stream):
                if row['speed'] in ('0.50', '0.60', '0.70', '0.75', '0.80'):
                    actual = sha(ROOT/row['output_path'])
                    golden.append(dict(path=row['output_path'], sha256=actual, match=actual==row['output_sha256']))
    protected = json.loads((ROOT/'results/phase51/protected_wav_audit.json').read_text())['rows']
    wavs = [dict(path=row['path'], match=sha(ROOT/row['path'])==row['sha256']) for row in protected]
    tracked = []
    for entry in subprocess.check_output(['git', 'ls-tree', '-rz', BASE, 'results'], cwd=ROOT).split(b'\0'):
        if not entry: continue
        meta, name = entry.split(b'\t', 1)
        mode, _, expected = meta.split()
        path = ROOT/os.fsdecode(name)
        data = os.fsencode(os.readlink(path)) if mode==b'120000' else path.read_bytes()
        actual = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        tracked.append(dict(path=os.fsdecode(name), match=actual==expected.decode()))
    tag = subprocess.check_output(['git', 'rev-parse', 'phase53-handoff^{commit}'], cwd=ROOT, text=True).strip()
    return dict(baseline=BASE, handoff_tag=tag, tag_unchanged=tag==BASE,
                golden=golden, protected_wavs=wavs, tracked_artifacts=tracked,
                PASS=len(golden)==25 and tag==BASE and all(row['match'] for rows in (golden,wavs,tracked) for row in rows))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    before = {str(path.relative_to(ROOT)):sha(path) for path in (ROOT/'results/phase53').rglob('*') if path.is_file()}
    trials = []
    incomplete = []
    for batch in sorted((ROOT/'results/phase53/native').iterdir()):
        folders = sorted(batch.glob('*/summary.txt'))
        if not folders: incomplete.append(str(batch.relative_to(ROOT)))
        for summary in folders:
            folder = summary.parent
            original = json.loads((folder/'validation.json').read_text())
            refs = {'.':folder/'reference_sessions/final.wav'}
            for closed in folder.glob('closed_session_*'):
                refs[closed.name] = folder/'reference_sessions'/(closed.name+'.wav')
            result = verify_run(folder, ROOT/f"results/phase53/input/{original['source']}_{int(original['seconds'])}s.wav",
                                original['exit'], reference_override=refs, original=original)
            result['case'] = str(folder.relative_to(ROOT))
            result['original_verdict'] = original.get('VERDICT')
            trials.append(result)
    after = {str(path.relative_to(ROOT)):sha(path) for path in (ROOT/'results/phase53').rglob('*') if path.is_file()}
    review = dict(trials=trials, trial_count=len(trials), session_count=sum(len(r['sessions']) for r in trials),
                  PASS=sum(r['VERDICT']=='PASS' for r in trials), FAIL=sum(r['VERDICT']!='PASS' for r in trials),
                  source_files_before=before, source_files_after=after, source_unchanged=before==after,
                  incomplete_capture_batches=incomplete)
    (args.output/'saved_native_review.json').write_text(json.dumps(review, indent=2)+'\n')
    assets = audit()
    (args.output/'protected_assets.json').write_text(json.dumps(assets, indent=2)+'\n')
    print(json.dumps(dict(trials=review['trial_count'], sessions=review['session_count'],
                         PASS=review['PASS'], FAIL=review['FAIL'], source_unchanged=review['source_unchanged'],
                         golden=len(assets['golden']), protected_wavs=len(assets['protected_wavs']),
                         tracked_artifacts=len(assets['tracked_artifacts']), assets_PASS=assets['PASS'])))
    return 0 if trials and not review['FAIL'] and before==after and assets['PASS'] else 2


if __name__=='__main__':
    raise SystemExit(main())

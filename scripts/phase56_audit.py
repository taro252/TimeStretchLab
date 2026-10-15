"""Read-only custody check against Phase55 HEAD, including ignored Golden WAVs."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '14d30be6a7a2dc164eead5a5d747c60fba806b49'
parser = argparse.ArgumentParser(__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Fresh output required')
tree = subprocess.check_output(['git', 'ls-tree', '-r', BASE], cwd=ROOT, text=True)
rows = []
for line in tree.splitlines():
    metadata, name = line.split('\t', 1)
    if name == 'CMakeLists.txt':  # only existing tracked file intentionally edited
        continue
    path = ROOT / name
    digest = hashlib.sha1()
    if path.is_symlink():
        data = os.readlink(path).encode()
        digest.update(f'blob {len(data)}\0'.encode() + data)
    elif path.is_file():
        digest.update(f'blob {path.stat().st_size}\0'.encode())
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    rows.append(dict(path=name, PASS=path.exists() and digest.hexdigest() == metadata.split()[2]))
golden = []
for phase in ('phase12', 'phase28'):
    with (ROOT / f'results/{phase}/golden/manifest.csv').open() as stream:
        for row in csv.DictReader(stream):
            path = ROOT / row['output_path']
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            golden.append(dict(path=row['output_path'], expected=row['output_sha256'], actual=actual,
                               PASS=actual == row['output_sha256']))
tag = subprocess.check_output(['git', 'rev-parse', 'phase53-handoff^{}'], cwd=ROOT, text=True).strip()
result = dict(baseline=BASE, checked=len(rows), golden_checked=len(golden),
              handoff_tag=tag, PASS=all(r['PASS'] for r in rows + golden)
              and tag == '233c773bbc77e5824c36134915f68d6d3a0d581e', tracked=rows, golden=golden)
args.output.write_text(json.dumps(result, indent=2) + '\n')
print(f"Protected tracked {sum(r['PASS'] for r in rows)}/{len(rows)}, Golden {sum(r['PASS'] for r in golden)}/{len(golden)}")
raise SystemExit(0 if result['PASS'] else 2)

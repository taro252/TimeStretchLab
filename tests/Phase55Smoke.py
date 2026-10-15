"""Dedicated deterministic dependency test; no writes to existing evidence."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='phase55_smoke_') as temp:
    subprocess.run([sys.executable, '-B', str(root / 'scripts/phase55_study.py'),
                    '--binary', sys.argv[1], '--suite', 'smoke',
                    '--output', str(Path(temp) / 'evidence')], check=True)

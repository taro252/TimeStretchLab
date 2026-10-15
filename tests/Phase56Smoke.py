"""Use the standalone frozen oracle on Release; the unchanged current one-shot
binary is also usable for Debug smoke because no legacy source was changed."""
from pathlib import Path
import subprocess
import sys
import tempfile
root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='phase56_smoke_') as temp:
    subprocess.run([sys.executable, '-B', str(root / 'scripts/phase56_study.py'),
                    '--suite', 'smoke', '--output', str(Path(temp) / 'evidence'),
                    '--binary', sys.argv[1], '--reference', sys.argv[2]], check=True)

"""Bounded deterministic state test; audio quality uses the independent study."""
import subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture
with tempfile.TemporaryDirectory(prefix='phase61_fast_state_',dir=ROOT/'build') as folder:
    source=Path(folder)/'boundary.wav'
    fixture(source,48000,2,3,'boundary',2)
    subprocess.run([str(Path(sys.argv[1]).resolve()),str(source)],check=True)

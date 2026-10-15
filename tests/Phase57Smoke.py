"""Integration smoke; explicit oracle supplied by the build/test invocation."""
from pathlib import Path
import subprocess,sys,tempfile
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='phase57_smoke_') as temp:
    subprocess.run([sys.executable,'-B',str(root/'scripts/phase57_study.py'),'--suite','smoke','--output',str(Path(temp)/'results'),'--binary',sys.argv[1],'--reference',sys.argv[2]],check=True)

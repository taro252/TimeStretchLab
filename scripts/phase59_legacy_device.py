"""Keep historical legacy device regression logic; redirect only its output."""
from pathlib import Path
from phase57_study import ROOT
source=ROOT/'scripts/phase58_fix_legacy_device.py'
code=source.read_text().replace("out=ROOT/'results/phase58_fix/legacy_device'","out=ROOT/'results/phase59/device_final/legacy_product'")
assert code!=source.read_text()
exec(compile(code,str(source),'exec'),{'__name__':'__main__','__file__':str(source)})

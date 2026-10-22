"""入力を新しい作業先へ復元する。期待SHA不一致時は必須素材として使用しない。"""
import argparse,json,shutil,sys,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture
from phase62_evidence import identity
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--mono-source',type=Path,default=Path('/Users/taro252/Docker/merodoa/build/phase62-native-loop/native-bridge/fixture-48000-1ch.wav'));a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);rows=[]
mono=a.output/'artificial_48000_mono_6s.wav';expected='ce21edd20991206d32bef0f45c6025025f90639be37ed8408261961f718bf1c2'
assert identity(a.mono_source)['sha256']==expected;shutil.copy2(a.mono_source,mono);assert identity(mono)['sha256']==expected;rows.append(dict(file=identity(mono),restored_from=identity(a.mono_source),method='既存Merodoa人工fixtureのbyte保持コピー。無い場合はBLOCKED、簡易別素材へ置換しない'))
block=a.output/'recipe_2s.wav';fixture(block,48000,2,1,'boundary',2.)
with wave.open(str(block),'rb') as f:params=f.getparams();data=f.readframes(f.getnframes())
long=a.output/'same_300s_48000_2_pcm16.wav'
with wave.open(str(long),'wb') as f:
 f.setparams(params)
 for _ in range(150):f.writeframesraw(data)
assert identity(long)['sha256']=='f44e0a246945fd35b3853c5e2988b9b87f739f496fbd57839ccc4ef481cd28b0';rows.append(dict(file=identity(long),block=identity(block),repeats=150,recipe_source=identity(ROOT/'scripts/phase62_fix_additional.py'),fixture_source=identity(ROOT/'scripts/phase57_study.py')))
(a.output/'MANIFEST.json').write_text(json.dumps(dict(status='PASS',run_complete=True,expected=2,executed=2,rows=rows),ensure_ascii=False,indent=2)+'\n');print('input restoration 2/2 PASS')

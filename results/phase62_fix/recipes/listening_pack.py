import sys,json,time,math
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';OUT=F/'listening_pack';Q=F/'evidence/release_quality'
sys.path.insert(0,str(R/'scripts'));from phase62_evidence import Ledger,aggregate,identity,source_manifest
from phase62_fix_quality import NAMES
if len(sys.argv)>1:
 import numpy as np
 from phase55_study import write_wav
 name=sys.argv[1];capture=Q/name;folder=OUT/name;folder.mkdir();meta=json.loads((capture/'capture.json').read_text());metrics=json.loads((capture/'metrics.json').read_text());assert metrics['PASS'] and metrics['bit_exact'] and metrics['finite']
 length=meta['period_frames'];channels=meta['channels'];rate=meta['rate'];periods=math.ceil(10*rate/length);rows={}
 for kind,src in [('raw','raw.f32'),('processed','processed.f32')]:
  allPcm=np.fromfile(capture/src,dtype='<f4').reshape(-1,channels);steady=allPcm[length:2*length];assert len(steady)==length and np.isfinite(steady).all()
  data=np.tile(steady,(periods,1))*np.float32(.5);path=folder/(kind+'_gain05.wav');write_wav(path,int(rate),channels,3,data.astype('<f4').tobytes());rows[kind]=identity(path)
 result=dict(PASS=True,source_capture=identity(capture/'capture.json'),source_metrics=identity(capture/'metrics.json'),WAV=rows,source='verified second steady cycle, repeated without temporal overlap or added silence',period_frames=length,repeats=periods,seconds=periods*length/rate,gain=.5,rate=rate,channels=channels,subjective_listening=None,acoustic_capture=False,real_recorded_piano=False if name.startswith('piano_synthetic') else None)
 (folder/'LISTENING.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');raise SystemExit(0)
keys=[f'{name}_{duration}_2000000_{preset}' for name in NAMES for duration in ('long','100ms') for preset in ('candidate','baseline')]
cases=[dict(id=name,kind='json_pass',result=name+'/LISTENING.json',required=[name+'/LISTENING.json',name+'/raw_gain05.wav',name+'/processed_gain05.wav']) for name in keys]
while not (F/'fd_lifetime/SUMMARY.json').is_file():time.sleep(5)
ledger=Ledger(OUT,cases,dict(source=source_manifest(R),driver=identity(__file__),purpose='minimum 10-second raw/processed listening pairs; technical preparation only; subjective judgment remains untested'))
for name in keys:ledger.run(name,[sys.executable,'-B',__file__,name],cwd=R,timeout=120,inputs=[Q/name/'capture.json',Q/name/'metrics.json',Q/name/'raw.f32',Q/name/'processed.f32'])
r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)

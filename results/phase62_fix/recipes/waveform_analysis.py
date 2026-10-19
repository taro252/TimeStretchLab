"""参照適合済みPCMの局所差分、左右定位、1秒文脈の帯域量。主観承認ではない。"""
import json,sys,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity
F=ROOT/'build/phase62_fix/run_01/final_v9';OUT=F/'waveform_analysis';Q=F/'evidence/release_quality'
names=('mix','bass','drums','guitar','vocal','sine','low_sustain','stereo_phase','impulse_train','piano_synthetic','silence')
keys=[f'{name}_{duration}_{speed}_{preset}' for duration,speeds in [('long',(400000,500000,750000,1000000,1500000,2000000)),('100ms',(400000,2000000))] for name in names for speed in speeds for preset in ('candidate','baseline')]
def arrays(key):
 import numpy as np
 folder=Q/key;m=json.loads((folder/'capture.json').read_text());ch=m['channels'];length=m['period_frames'];rate=int(m['rate'])
 raw=np.fromfile(folder/'raw.f32',dtype='<f4').reshape(-1,ch);processed=np.fromfile(folder/'processed.f32',dtype='<f4').reshape(-1,ch)
 assert len(raw)==len(processed)==m['cycles']*length and length>=512
 return m,raw[:length].astype(float),processed[length:2*length].astype(float),rate

def measure(key):
 import numpy as np
 m,raw,processed,rate=arrays(key);length=len(raw);i=np.arange(-rate//2,rate//2)%length;x=raw[i];y=processed[i];ch=x.shape[1]
 finite=all(np.isfinite(v).all() for v in (x,y));win=np.hanning(len(x));freq=np.fft.rfftfreq(len(x),1/rate)
 specx=np.abs(np.fft.rfft(x*win[:,None],axis=0))**2;specy=np.abs(np.fft.rfft(y*win[:,None],axis=0))**2
 db=lambda a,b:None if a<=0 else float(10*np.log10(max(b,1e-300)/a))
 bands=[]
 for lo,hi in ((20,200),(200,4000),(4000,rate/2)):
  mask=(freq>=lo)&(freq<hi);a=specx[mask].sum(axis=0);b=specy[mask].sum(axis=0);bands.append(dict(hz=[lo,hi],raw=a.tolist(),processed=b.tolist(),change_db=[db(u,v) for u,v in zip(a,b)]))
 rms=lambda v:np.sqrt(np.mean(v*v,axis=0));a=rms(x);b=rms(y)
 stereo=None
 if ch==2:
  corr=lambda v:None if np.std(v[:,0])==0 or np.std(v[:,1])==0 else float(np.corrcoef(v[:,0],v[:,1])[0,1])
  stereo=dict(raw_lr_db=None if min(a)<=0 else float(20*np.log10(a[1]/a[0])),processed_lr_db=None if min(b)<=0 else float(20*np.log10(b[1]/b[0])),raw_correlation=corr(x),processed_correlation=corr(y))
 tones=[];t=np.arange(len(x))/rate
 for hz in (55,437.3):
  osc=np.exp(-2j*np.pi*hz*t)*win;u=(x*osc[:,None]).sum(axis=0);v=(y*osc[:,None]).sum(axis=0)
  phase=lambda z:None if ch!=2 or min(np.abs(z))<1e-20 else float(np.angle(z[1]*np.conj(z[0])))
  tones.append(dict(hz=hz,raw_amplitude=(2*np.abs(u)/win.sum()).tolist(),processed_amplitude=(2*np.abs(v)/win.sum()).tolist(),raw_lr_phase_radians=phase(u),processed_lr_phase_radians=phase(v)))
 narrow=np.arange(-rate//100,rate//100)%length;xx=raw[narrow];yy=processed[narrow]
 parent=json.loads((Q/key/'metrics.json').read_text());result=dict(PASS=bool(parent['PASS'] and finite),finite=bool(finite),period_frames=length,source_rate=rate,context='1 second, verified steady period extended on both sides of B/A; not acoustic recording',fft_resolution_hz=rate/len(x),raw_seam_jump=(raw[0]-raw[-1]).tolist(),processed_seam_jump=(processed[0]-processed[-1]).tolist(),raw_slope_jump=((raw[1]-raw[0])-(raw[-1]-raw[-2])).tolist(),processed_slope_jump=((processed[1]-processed[0])-(processed[-1]-processed[-2])).tolist(),local20ms_raw_max_diff=np.max(np.abs(np.diff(xx,axis=0)),axis=0).tolist(),local20ms_processed_max_diff=np.max(np.abs(np.diff(yy,axis=0)),axis=0).tolist(),bands=bands,stereo=stereo,tones=tones,subjective_approved=False,raw=identity(Q/key/'raw.f32'),processed=identity(Q/key/'processed.f32'),reference_metrics=identity(Q/key/'metrics.json'))
 (OUT/(key+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');return int(not result['PASS'])

def figure():
 import numpy as np
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 plt.rcParams['font.family']=['Hiragino Sans','DejaVu Sans'];fig,axes=plt.subplots(4,2,figsize=(12,9),layout='constrained')
 for row,name in enumerate(('low_sustain','stereo_phase','drums','impulse_train')):
  for col,(duration,speed) in enumerate((('long',400000),('100ms',2000000))):
   key=f'{name}_{duration}_{speed}_candidate';m,raw,proc,rate=arrays(key);n=rate//20;idx=np.arange(-n,n)%len(raw);t=np.arange(-n,n)/rate*1000;ax=axes[row,col]
   ax.plot(t,raw[idx,0]*.5,color='#999999',linewidth=.8,label='RAW');ax.plot(t,proc[idx,0]*.5,color='#1765c1',linewidth=.8,label='周期維持後');ax.axvline(0,color='#222222',linewidth=.5);ax.set_title(f'{name}: {duration}, {speed/1e6:.2f}x');ax.grid(alpha=.2);ax.set_xlabel('境界からの時間 (ms)');ax.set_ylabel('出力 (0.5倍)')
 axes[0,0].legend();fig.suptitle('境界前後の波形：検証済み定常周期の延長。実音響録音ではない。');fig.savefig(OUT/'waveform_comparison.png',dpi=160);plt.close(fig)
 (OUT/'FIGURE.json').write_text(json.dumps(dict(PASS=True,matplotlib=matplotlib.__version__,artifact=identity(OUT/'waveform_comparison.png')) ,indent=2)+'\n');return 0
if len(sys.argv)>1:raise SystemExit(figure() if sys.argv[1]=='--figure' else measure(sys.argv[1]))
cases=[dict(id=k,kind='json_pass',required=[k+'.json'],result=k+'.json') for k in keys];cases.append(dict(id='figure',kind='json_pass',required=['FIGURE.json','waveform_comparison.png'],result='FIGURE.json'))
frozen=source_manifest(ROOT);ledger=Ledger(OUT,cases,dict(source=frozen,driver=identity(__file__),purpose='品質の追加計測。主観PASSや音響loopbackではない'))
while not (F/'sandbox_evidence/SUMMARY.json').is_file():time.sleep(5)
if source_manifest(ROOT)['sha256']!=frozen['sha256']:raise SystemExit('SOURCE CHANGED')
for key in [*keys,'figure']:
 ok=ledger.run(key,[sys.executable,'-B',__file__,'--figure' if key=='figure' else key],cwd=ROOT,timeout=300);print(key,ledger.rows[key]['status'],flush=True)
ledger.save();r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)

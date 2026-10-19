"""同じ周期Lの補正案を比較する。ゼロ終端案は未実装、主観承認ではない。"""
import sys,json,time,math
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';OUT=F/'boundary_methods';sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import Ledger,aggregate,identity,source_manifest
from phase62_fix_quality import NAMES
keys=[f'{name}_{duration}_{speed}_{preset}' for duration,speeds in [('long',(400000,500000,750000,1000000,1500000,2000000)),('100ms',(400000,2000000))] for name in [*NAMES,'piano_real'] for speed in speeds for preset in ('candidate','baseline')]
selected=['impulse_train_100ms_400000_candidate','bass_long_1000000_baseline','low_sustain_long_400000_candidate','stereo_phase_100ms_2000000_candidate','drums_long_2000000_candidate','piano_real_long_2000000_candidate']
def arrays(key):
 import numpy as np
 q=F/('piano_quality' if key.startswith('piano_real_') else 'evidence/release_quality')/key
 m=json.loads((q/'capture.json').read_text());metrics=json.loads((q/'metrics.json').read_text());assert metrics['PASS'] and metrics['finite'] and metrics['bit_exact']
 length=m['period_frames'];ch=m['channels'];raw=np.fromfile(q/'raw.f32',dtype='<f4').reshape(-1,ch)[:length];current=np.fromfile(q/'processed.f32',dtype='<f4').reshape(-1,ch)[length:2*length];assert raw.shape==current.shape and len(raw)==length
 n=m['boundary_frames'];j=np.arange(n,dtype=np.float32);t=(j+np.float32(1))/np.float32(n);tail=np.float32(1)-t*t*(np.float32(3)-np.float32(2)*t);x=np.float32(1)-j/np.float32(n);head=np.float32(1)-x*x*(np.float32(3)-np.float32(2)*x)
 zero=raw.copy();zero[-n:]*=tail[:,None];zero[:n]*=head[:,None];zero[-1]=np.float32(0);zero[0]=np.float32(0)
 assert zero[n:-n].tobytes()==raw[n:-n].tobytes() and current[n:-n].tobytes()==raw[n:-n].tobytes()
 return q,m,raw,current,zero

def measure(key):
 import numpy as np
 from phase55_study import write_wav
 q,m,raw,current,zero=arrays(key);rate=int(m['rate']);length=len(raw);rms=lambda v:np.sqrt(np.mean(v.astype(np.float64)**2,axis=0));windows=[]
 for ms in (10,25,100):
  width=int(rate*ms/2000);i=np.arange(-width,width)%length;a=rms(raw[i]);row=dict(milliseconds=ms,raw_rms=a.tolist())
  for name,values in [('current',current),('zero_taper_proposal',zero)]:
   b=rms(values[i]);row[name]=dict(rms=b.tolist(),change_db=[None if x==0 or y==0 else float(20*np.log10(y/x)) for x,y in zip(a,b)],full_window_energy_removed=[bool(x>0 and y==0) for x,y in zip(a,b)])
  windows.append(row)
 result=dict(PASS=bool(all(np.isfinite(v).all() for v in (raw,current,zero))),purpose='comparison artifact integrity only; not acoustic or subjective approval',period_frames=length,boundary_frames=m['boundary_frames'],rate=rate,windows=windows,peak_gain05={name:float(np.max(np.abs(v)))*.5 for name,v in [('raw',raw),('current',current),('zero_taper_proposal',zero)]},seam_jump={name:(v[0]-v[-1]).tolist() for name,v in [('raw',raw),('current',current),('zero_taper_proposal',zero)]},current_implemented=True,zero_taper_proposal_implemented=False,intentional_zero_endpoints_per_boundary=2,global_gain=.5,subjective_listening=None,source_metrics=identity(q/'metrics.json'),WAV={})
 if key in selected:
  folder=OUT/key;folder.mkdir();periods=math.ceil(10*rate/length)
  for name,v in [('raw',raw),('current',current),('zero_taper_proposal',zero)]:
   path=folder/(name+'_gain05.wav');data=np.tile(v,(periods,1))*np.float32(.5);write_wav(path,rate,m['channels'],3,data.astype('<f4').tobytes());result['WAV'][name]=identity(path)
 (OUT/(key+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');return int(not result['PASS'])

def figure():
 import numpy as np
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 plt.rcParams['font.family']=['Hiragino Sans','DejaVu Sans'];fig,axes=plt.subplots(6,2,figsize=(12,18),layout='constrained')
 for row,key in enumerate(selected):
  q,m,raw,current,zero=arrays(key);rate=int(m['rate']);n=rate//20;i=np.arange(-n,n)%len(raw);t=np.arange(-n,n)/rate*1000;ax=axes[row,0]
  for name,v,color in [('RAW',raw,'#999999'),('現行',current,'#1765c1'),('ゼロ終端案',zero,'#d77610')]:ax.plot(t,v[i,0]*.5,label=name,color=color,linewidth=.8)
  ax.axvline(0,color='#444444',linewidth=.5);ax.grid(alpha=.2);ax.set_title(key);ax.set_xlabel('B/Aからの時間 (ms)');ax.set_ylabel('出力ゲイン0.5')
  data=json.loads((OUT/(key+'.json')).read_text());ax=axes[row,1];x=np.arange(3)
  for offset,name,color in [(-.18,'current','#1765c1'),(.18,'zero_taper_proposal','#d77610')]:
   vals=[w[name]['change_db'][0] for w in data['windows']];ax.bar(x+offset,[float('nan') if v is None else v for v in vals],width=.35,color=color,label=name)
  ax.set_xticks(x,['10ms','25ms','100ms']);ax.set_ylabel('RAW比 RMS変化 (dB)');ax.grid(axis='y',alpha=.2)
 axes[0,0].legend();fig.suptitle('周期Lを保つ方式の比較。ゼロ終端案は未実装・試聴未承認。');fig.savefig(OUT/'boundary_method_comparison.png',dpi=150);plt.close(fig)
 (OUT/'FIGURE.json').write_text(json.dumps(dict(PASS=True,artifact=identity(OUT/'boundary_method_comparison.png'),prototype_only=True),indent=2)+'\n');return 0
if len(sys.argv)>1:raise SystemExit(figure() if sys.argv[1]=='--figure' else measure(sys.argv[1]))
cases=[dict(id=k,kind='json_pass',result=k+'.json',required=[k+'.json']+[k+'/'+name+'_gain05.wav' for name in ('raw','current','zero_taper_proposal')] if k in selected else [k+'.json']) for k in keys]
cases.append(dict(id='figure',kind='json_pass',result='FIGURE.json',required=['FIGURE.json','boundary_method_comparison.png']))
while not (F/'inside_seek/SUMMARY.json').is_file():time.sleep(5)
ledger=Ledger(OUT,cases,dict(source=source_manifest(R),driver=identity(__file__),purpose='time-preserving endpoint correction vs proposed scalar taper; no default engine change, no subjective approval'))
for key in [*keys,'figure']:
 ledger.run(key,[sys.executable,'-B',__file__,'--figure' if key=='figure' else key],cwd=R,timeout=120);print(key,ledger.rows[key]['status'],flush=True)
r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)

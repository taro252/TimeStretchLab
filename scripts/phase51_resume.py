"""Stable case identities and append-only evidence. Completed/unsupported never rerun."""
import hashlib,json
from pathlib import Path
KEYS=('label','lead','stock','dose','callback','stress','at','drain')
def identity(case):
    data={k:case[k] for k in KEYS}
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
def matrix():
    rows=[dict(label=l,lead=lead,stock=lead,dose=d,callback=512,stress=False,at=216000,drain=False)
          for d in (200,250,300,350) for l,lead in [('A',12288),('B',14336),('C',16384)]]
    rows += [dict(label='C',lead=16384,stock=16384,dose=300,callback=n,stress=True,at=648000,drain=False) for n in (64,128,256,1024)]
    rows += [dict(label='A',lead=12288,stock=8192,dose=250,callback=512,stress=True,at=300000,drain=True),
             dict(label='C',lead=16384,stock=12288,dose=300,callback=512,stress=True,at=300000,drain=True),
             dict(label='C',lead=16384,stock=16384,dose=300,callback=512,stress=True,at=648000,drain=False)]
    return rows

def reconcile(output,expected, input_sha=None):
    output=Path(output);manifest=json.loads((output/'manifest.json').read_text())
    cases=list(manifest['matrix'])
    # Explicit migration of Phase50's recorded supplementary nineteenth case.
    if len(cases)!=len(expected):
        supplement=json.loads((output/'resume_manifest.json').read_text())['supplemental_native_condition']
        if len(cases)!=18 or len(expected)!=19 or supplement['ordinal']!=19:
            raise ValueError('Manifest case set changed')
        cases.append({k:supplement[k] for k in KEYS})
    if cases!=expected or (input_sha is not None and manifest['input_sha256']!=input_sha):
        raise ValueError('Manifest/input conditions changed; resume refused')
    ids=[identity(c) for c in cases]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate manifest case ID')
    states={i:dict(ordinal=n+1,case_id=i,case=c,status='NOT_RUN',result=None) for n,(i,c) in enumerate(zip(ids,cases))}
    seen=set()
    for file,kind in [('summary.json','result'),('unsupported.json','unsupported')]:
        path=output/file
        if not path.exists():continue
        for row in json.loads(path.read_text()):
            n=int(row['ordinal'])-1
            if n<0 or n>=len(cases) or any(row[k]!=cases[n][k] for k in KEYS):
                raise ValueError('Saved case/ordinal differs from manifest')
            key=identity(row)
            if key in seen:raise ValueError('Duplicate saved case ID')
            seen.add(key)
            if kind=='unsupported':status='UNSUPPORTED'
            elif row.get('FAULT_DETECTION')=='PASS' and all(row.get(k)=='PASS' for k in ('MEASUREMENT_QUALITY','CSV_INTEGRITY','METRIC_INTEGRITY','PCM_CORRECTNESS','CONFIG_VALIDITY')):
                status='COMPLETED' # Intentional AUDIO_QUALITY=FAIL remains in result.
            else:status='FAILED'
            states[key].update(status=status,result=row)
    for path in sorted((output/'case_events').glob('*/started.json')):
        key=path.parent.name
        if key not in states:raise ValueError('Journal case not in manifest')
        started=json.loads(path.read_text())
        if started.get('case_id')!=key or started.get('case')!=states[key]['case']:
            raise ValueError('Started journal differs from manifest')
        end=path.parent/'finished.json'
        if key in seen:raise ValueError('Duplicate case registration')
        if not end.exists():states[key]['status']='RETRY_REQUIRED'
        else:
            event=json.loads(end.read_text())
            if event['case_id']!=key:raise ValueError('Journal identity mismatch')
            if event.get('status') not in ('COMPLETED','UNSUPPORTED','FAILED','RETRY_REQUIRED'):
                raise ValueError('Invalid saved terminal status')
            states[key].update(status=event['status'],result=event.get('result'))
        seen.add(key)
    if set(states)!=set(ids):raise ValueError('Resume case set changed')
    return list(states.values())

def register(output,case):
    key=identity(case);path=Path(output)/'case_events'/key
    path.mkdir(parents=True,exist_ok=False)
    with (path/'started.json').open('x') as f:json.dump(dict(case_id=key,case=case),f,indent=2)
    return path

def finish(path,status,result):
    if status not in ('COMPLETED','UNSUPPORTED','FAILED','RETRY_REQUIRED'):raise ValueError('Invalid terminal status')
    with (Path(path)/'finished.json').open('x') as f:json.dump(dict(case_id=Path(path).name,status=status,result=result),f,indent=2,allow_nan=False)

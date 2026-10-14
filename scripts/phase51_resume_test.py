#!/usr/bin/env python3
import hashlib,json,tempfile
from pathlib import Path
from phase51_resume import matrix,reconcile,register,finish
cases=matrix()
with tempfile.TemporaryDirectory() as directory:
    out=Path(directory)
    (out/'manifest.json').write_text(json.dumps(dict(matrix=cases[:18],input_sha256='source')))
    rows=[dict(ordinal=i+1,**c,FAULT_DETECTION='PASS',AUDIO_QUALITY='FAIL' if i==16 else 'PASS',
               **dict.fromkeys(('MEASUREMENT_QUALITY','CSV_INTEGRITY','METRIC_INTEGRITY','PCM_CORRECTNESS','CONFIG_VALIDITY'),'PASS'))
          for i,c in enumerate(cases) if i<12 or i>=16]
    (out/'summary.json').write_text(json.dumps(rows))
    unsupported=[dict(ordinal=i+1,**cases[i],status='UNSUPPORTED_DEVICE_QUANTUM') for i in range(12,16)]
    (out/'unsupported.json').write_text(json.dumps(unsupported))
    (out/'resume_manifest.json').write_text(json.dumps(dict(supplemental_native_condition=rows[-1])))
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.json')}
    states=reconcile(out,cases,'source')
    assert {r['ordinal'] for r in states if r['status']=='COMPLETED'}==set(range(1,13))|{17,18,19}
    assert {r['ordinal'] for r in states if r['status']=='UNSUPPORTED'}=={13,14,15,16}
    assert not any(r['status']=='NOT_RUN' for r in states)
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.json')}
    changed=[dict(c) for c in cases];changed[0]['dose']=201
    for candidate,sha in [(changed,'source'),(cases,'changed_source')]:
        try:reconcile(out,candidate,sha)
        except ValueError:pass
        else:raise AssertionError('Changed manifest/input accepted')
    (out/'summary.json').write_text(json.dumps(rows+[rows[-1]]))
    try:reconcile(out,cases)
    except ValueError:pass
    else:raise AssertionError('Duplicate registration accepted')
    (out/'summary.json').write_text('[]');(out/'unsupported.json').write_text('[]')
    path=register(out,cases[0]);assert reconcile(out,cases)[0]['status']=='RETRY_REQUIRED'
    finish(path,'FAILED',{});assert reconcile(out,cases)[0]['status']=='FAILED'
    try:register(out,cases[0])
    except FileExistsError:pass
    else:raise AssertionError('Re-registration accepted')
print('Resume ordinals/unsupported/duplicates/manifest/crash recovery PASS')

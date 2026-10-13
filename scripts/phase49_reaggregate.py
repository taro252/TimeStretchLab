#!/usr/bin/env python3
"""Re-evaluate old logs in new directories and verify old statistics exactly."""
import hashlib,json,shutil
from pathlib import Path
from phase48_metrics import measure,save_summaries
root=Path(__file__).resolve().parents[1]
out=root/'results/phase49/reaggregate';out.mkdir(parents=True,exist_ok=True)
audits=[]
for group in ('study','confirmation_drums5_normal'):
    destination=out/group;destination.mkdir(exist_ok=True);new_rows=[]
    for original in sorted((root/'results/phase48'/group/'runs').glob('*')):
        old=json.loads((original/'comparison.json').read_text());row=json.loads((original/'result.json').read_text())
        copied=destination/'runs'/original.name;copied.mkdir(parents=True,exist_ok=False)
        file_hashes={}
        for name in ('callbacks.csv','workers.csv','workers.csv.guard.csv','replay.csv','playback.log','csv_integrity.json','result.json'):
            source=original/name;file_hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest();shutil.copyfile(source,copied/name)
        context={k:old[k] for k in ('ordinal','round','order','disk_free_before_bytes')}
        new=measure(row,copied,context);differences=[]
        for key in ('dsp_wall_s_ms','dsp_cpu_s_ms','cycle_wall_s_ms','cycle_cpu_s_ms','publication_interval_s_ms','callback_wall_ms'):
            for stat in ('count','max','p95','p99'):
                if new[key][stat]!=old[key][stat]:differences.append(key+'.'+stat)
        for key in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','CSV_INTEGRITY','PCM_CORRECTNESS','CONFIG_VALIDITY','NATIVE_STABILITY_VERDICT'):
            if new[key]!=old[key]:differences.append(key)
        assert not differences and new['METRIC_INTEGRITY']=='PASS',(original,differences)
        assert all(hashlib.sha256((original/name).read_bytes()).hexdigest()==h for name,h in file_hashes.items())
        audits.append(dict(run=original.name,METRIC_INTEGRITY=new['METRIC_INTEGRITY'],old_statistics_identical=True,original_file_hashes=file_hashes,original_unmodified=True))
        new_rows.append(new)
    save_summaries(destination,new_rows)
(out/'verification.json').write_text(json.dumps(dict(runs=len(audits),checks=audits),indent=2))
print(f'Old statistics unchanged: {len(audits)}/16, original logs untouched')

"""Resource-gated trace recording. Never count one storage pool's free bytes twice."""
import json
import os
import plistlib
import signal
import subprocess
import time
import resource
from pathlib import Path

GIB=1024**3


def volume(path):
    path=Path(path).resolve();path.mkdir(parents=True,exist_ok=True)
    stat=os.stat(path);fs=os.statvfs(path)
    info={}
    try:
        p=subprocess.run(['diskutil','info','-plist',str(path)],capture_output=True,timeout=1)
        if p.returncode==0:info=plistlib.loads(p.stdout)
    except (OSError,ValueError,subprocess.TimeoutExpired):pass
    pool=info.get('APFSContainerReference') or info.get('APFSContainerUUID') or str(stat.st_dev)
    return dict(path=str(path),device=stat.st_dev,pool=str(pool),total=fs.f_blocks*fs.f_frsize,
        free=fs.f_bavail*fs.f_frsize,apfs=info.get('FilesystemType')=='apfs' if info else 'unavailable',volume_uuid=info.get('VolumeUUID'))


def grouped(volumes):
    groups={}
    for item in volumes:
        group=groups.setdefault(item['pool'],dict(pool=item['pool'],free=item['free'],total=item['total'],paths=[]))
        group['free']=min(group['free'],item['free']);group['total']=min(group['total'],item['total']);group['paths'].append(item['path'])
    return list(groups.values())


def estimate(volumes,seconds,evidence):
    groups=grouped(volumes)
    # Initial envelope is based on Phase46 measured ktrace/package sizes.
    # Finish/export overhead is intentionally reserved before starting.
    temporary=evidence['max_temporary_bytes']+seconds*evidence['growth_bytes_per_second']
    output=temporary;xml=evidence['max_xml_bytes']
    requirements={g['pool']:0 for g in groups}
    requirements[volumes[0]['pool']]+=output+xml
    requirements[volumes[1]['pool']]+=temporary
    if len(volumes)>2:requirements[volumes[2]['pool']]+=temporary # Unverified TMPDIR fallback, conservatively separate cost.
    budgets=[]
    for g in groups:
        reserve=int(g['total']*.05) # OS/storage policy, not an empirical trace-size assumption.
        growth=int(requirements[g['pool']]*1.25)
        budgets.append(dict(g,reserve=reserve,required_growth=growth,required_free=reserve+growth,
            allowed=g['free']>=reserve+growth))
    return dict(allowed=all(g['allowed'] for g in budgets),groups=budgets,seconds=seconds,
        evidence=evidence,temporary_estimate=temporary,output_estimate=output,xml_estimate=xml)


def size(path):
    total=0
    for file in Path(path).rglob('*'):
        try:
            if file.is_file():total+=file.stat().st_size
        except OSError:pass
    return total


def record(command,path,temporary,default_temporary,seconds,evidence,prepared_volumes=None):
    path=Path(path);temporary=Path(temporary);default_temporary=Path(default_temporary)
    selected=prepared_volumes or [volume(path.parent),volume(temporary)]
    # xctrace's service may ignore TMPDIR. Until measured, monitor its usual temp volume too.
    if prepared_volumes is None and default_temporary.resolve()!=temporary.resolve():selected.append(volume(default_temporary))
    selected=[volume_fast(v) for v in selected]
    plan=estimate(selected,seconds,evidence)
    (path.parent/'storage_plan.json').write_text(json.dumps(plan,indent=2))
    if not plan['allowed']:
        return dict(STORAGE_STATUS='START_REFUSED',record_exit=None,reason='insufficient_record_finish_export_budget',plan=plan)
    env=dict(os.environ,TMPDIR=str(temporary.resolve())+'/')
    before={str(f) for folder in (temporary,default_temporary) for f in folder.glob('instruments*')}
    start=time.monotonic();samples=[];stage='RECORDING';reason='time_limit';requested_stop=False
    log_path=path.parent/'xctrace.log'
    with log_path.open('x') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        deadline=start+seconds+30;stop_at=None;last_free={g['pool']:g['free'] for g in plan['groups']}
        last_at=start;peak_rate={g['pool']:0 for g in plan['groups']}
        while process.poll() is None:
            now=time.monotonic();current=grouped([volume_fast(v) for v in selected])
            for group in current:
                pool=group['pool'];delta=max(0,last_free[pool]-group['free'])
                rate=delta/max(.01,now-last_at);peak_rate[pool]=max(peak_rate[pool],rate)
                budget=next(g for g in plan['groups'] if g['pool']==pool)
                # Predict headroom needed while the recorder reacts and finalizes.
                impending=group['free']<budget['reserve']+int(peak_rate[pool]*10)+int(plan['output_estimate']*.5)
                if impending and not requested_stop:
                    reason='capacity_projection';process.send_signal(signal.SIGINT);requested_stop=True;stage='STOP_REQUESTED';stop_at=now
                samples.append(dict(elapsed_s=now-start,pool=pool,free=group['free'],observed_rate=rate,peak_rate=peak_rate[pool],stage=stage))
                last_free[pool]=group['free']
            last_at=now
            if not requested_stop and now>=deadline:
                reason='record_or_finalize_timeout';process.send_signal(signal.SIGINT);requested_stop=True;stage='STOP_REQUESTED';stop_at=now
            elif requested_stop and stage=='STOP_REQUESTED' and now-stop_at>15:
                process.terminate();stage='TERMINATED';stop_at=now
            elif requested_stop and stage=='TERMINATED' and now-stop_at>5:
                process.kill();stage='KILLED';stop_at=now
            time.sleep(.25)
        code=process.wait()
    after=[volume_fast(v) for v in selected]
    new_temp=[]
    for folder in (temporary,default_temporary):
        for file in folder.glob('instruments*'):
            if str(file) not in before:
                try:new_temp.append(dict(path=str(file),bytes=file.stat().st_size))
                except OSError:pass
    status='NORMAL_EXIT' if code==0 and not requested_stop else 'PARTIAL_STOP' if code==0 else 'ABNORMAL_EXIT'
    result=dict(STORAGE_STATUS=status,record_exit=code,stop_reason=reason,stop_requested=requested_stop,
        elapsed_s=time.monotonic()-start,after=after,new_temporary_files=new_temp,package_bytes=size(path),samples=samples,plan=plan,
        child_peak_rss_bytes=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    (path.parent/'storage_monitor.json').write_text(json.dumps(result,indent=2))
    return result


def volume_fast(info):
    fs=os.statvfs(info['path'])
    return dict(info,free=fs.f_bavail*fs.f_frsize)

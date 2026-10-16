"""Serial physical audio sessions and frozen full-analysis live Phase39/36 replay."""
import argparse,array,bisect,csv,hashlib,json,math,shutil,struct,subprocess,time
from pathlib import Path
from phase57_study import ROOT,fixture,sha

def wav_info(path):
    with Path(path).open('rb') as f:
        if f.read(4)!=b'RIFF':raise ValueError('RIFF required')
        f.read(4)
        if f.read(4)!=b'WAVE':raise ValueError('WAVE required')
        fmt=None;data=None
        while header:=f.read(8):
            if len(header)!=8:break
            kind,size=struct.unpack('<4sI',header);at=f.tell()
            if kind==b'fmt ':fmt=struct.unpack('<HHIIHH',f.read(16))
            if kind==b'data':data=(at,size)
            f.seek(at+size+(size%2))
        if not fmt or not data:raise ValueError('WAV chunks missing')
        encoding,channels,rate,_,align,bits=fmt
        return dict(encoding=encoding,channels=channels,rate=rate,bits=bits,frames=data[1]//align,data_offset=data[0],data_bytes=data[1])

def compare_pcm(captured,reference,offset,expected_bytes,channels,eos,evidence):
    actual_bytes=captured.stat().st_size
    if actual_bytes>expected_bytes or (eos and actual_bytes!=expected_bytes):
        return dict(PASS=False,reason='output_length',actual_bytes=actual_bytes,reference_bytes=expected_bytes)
    digest=hashlib.sha256();position=0
    with captured.open('rb') as a,reference.open('rb') as b:
        b.seek(offset)
        while block:=a.read(1<<20):
            want=b.read(len(block));digest.update(block)
            if block!=want:
                for i in range(0,min(len(block),len(want)),4):
                    if block[i:i+4]!=want[i:i+4]:
                        sample=(position+i)//4
                        failure=dict(PASS=False,frame=sample//channels,channel=sample%channels,actual_bits=struct.unpack('<I',block[i:i+4])[0],reference_bits=struct.unpack('<I',want[i:i+4])[0])
                        (evidence/'first_mismatch.json').write_text(json.dumps(failure,indent=2)+'\n');return failure
                return dict(PASS=False,reason='reference_truncated')
            position+=len(block)
    return dict(PASS=True,complete=eos,frames=actual_bytes//(channels*4),pcm_sha256=digest.hexdigest(),reference_frames=expected_bytes//(channels*4))

def run(args):
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'inputs').mkdir();(out/'working').mkdir()
    binary=args.binary.resolve();reference=ROOT/'build/phase59_frozen/captured_reference';fixed=ROOT/'build/phase58_frozen/product_reference'
    path=out/'inputs/boundary_float_stereo_48000.wav';fixture(path,48000,2,3,'boundary',4)
    sources=[path];cases=[]
    patterns=[(500000,[(16384,1500000),(49152,400000),(69632,990000)]),
        (400000,[(16384,410000),(32768,420000),(65536,2000000),(67584,400000)]),
        (2000000,[(16384,1990000),(32768,400000)]),
        (490000,[(16384,500000),(49152,510000),(73728,490000)]),
        (990000,[(16384,1000000),(32768,1010000),(49152,1000000),(65536,990000)])]
    repeats=1 if args.suite=='smoke' else 3
    if args.suite=='burst':
        speeds=(list(range(400000,2000001,10000))*7)[:1023]+[1500000]
        for repeat in range(3):
            for preset in ('candidate','baseline'):cases.append(dict(input=path,initial=500000,requests=[(16384,s) for s in speeds],preset=preset,mode='normal',window=0,cpu=0,memory=0,repeat=repeat))
    elif args.suite=='materials':
        for kind in ('drums','mix'):
            source=ROOT/'results/phase31/input'/(kind+'.wav');sources.append(source)
            for repeat in range(3):
                for preset in ('candidate','baseline'):
                    for initial,requests in [(400000,[(16384,2000000),(65536,490000),(69632,1010000)]),(500000,[(16384,1500000)])]:
                        cases.append(dict(input=source,initial=initial,requests=requests,preset=preset,mode='normal',window=0,cpu=0,memory=0,repeat=repeat))
        for repeat in range(3):
            for preset in ('candidate','baseline'):
                cases.append(dict(input=path,initial=2000000,requests=[(89088,400000)],preset=preset,mode='normal',window=0,cpu=0,memory=0,repeat=repeat))
    elif args.suite in ('smoke','normal','load','lifecycle'):
        for repeat in range(repeats):
            for preset in ('candidate','baseline'):
                for index,(initial,requests) in enumerate(patterns[:1] if args.suite=='smoke' else patterns):
                    mode='pause' if args.suite=='lifecycle' and index%2==0 else 'normal'
                    window=.8 if args.suite=='lifecycle' and index%2 else 0
                    if args.suite=='lifecycle' and index==0:requests=[(16384,1500000),(18432,400000),(20480,990000),(25088,500000)]
                    conditions=[(2,0),(0,128),(2,128)] if args.suite=='load' else [(0,0)]
                    for cpu,memory in conditions:cases.append(dict(input=path,initial=initial,requests=requests,preset=preset,mode=mode,window=window,cpu=cpu,memory=memory,repeat=repeat))
    elif args.suite=='long':
        boundary=ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav'
        mix=ROOT/'results/phase31/input/mix.wav';meta=wav_info(mix);long=out/'inputs/mix_repeated_300s.wav'
        with mix.open('rb') as source:source.seek(meta['data_offset']);data=source.read(meta['data_bytes'])
        from phase55_study import write_wav
        target=meta['rate']*300*meta['channels']*(meta['bits']//8)
        write_wav(long,meta['rate'],meta['channels'],meta['encoding'],(data*math.ceil(target/len(data)))[:target])
        sources += [boundary,long]
        for source in (boundary,long):
            for preset in ('candidate','baseline'):
                cases.append(dict(input=source,initial=400000 if preset=='candidate' else 2000000,
                    requests=[(16384,2000000 if preset=='candidate' else 1000000),(262144,1500000)],preset=preset,mode='normal',window=0,
                    cpu=2 if (source==long and preset=='candidate') or (source==boundary and preset=='baseline') else 0,memory=128 if source==long and preset=='candidate' else 0,repeat=0))
    else:raise ValueError(args.suite)
    manifest=dict(suite=args.suite,driver_source_sha256=sha(Path(__file__)),binary=str(binary),binary_sha256=sha(binary),reference=str(reference),reference_sha256=sha(reference),fixed_reference_sha256=sha(fixed),
        inputs=[dict(path=str(p),sha256=sha(p),metadata=wav_info(p)) for p in sources],cases=len(cases),serial_audio=True,
        comparison='callback raw PCMを事前確保領域に保存し、停止後に実際のFrontierで変更前の全曲解析＋Phase39/42/50/36動的経路へ再現。全計画を前もって与えるPhase35参照と区別。')
    environment=[]
    for command in [['sysctl','vm.swapusage'],['vm_stat'],['uptime']]:
        p=subprocess.run(command,capture_output=True,text=True)
        environment.append(dict(command=command,exit=p.returncode,stdout=p.stdout,stderr=p.stderr))
    (out/'environment.json').write_text(json.dumps(environment,indent=2)+'\n')
    manifest['system_context']='environment.json（各群の音声開始前に取得。全期間の連続システム負荷計測ではない）'
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    rows=[]
    for index,case in enumerate(cases):
        if shutil.disk_usage(ROOT).free<4*1024**3:raise RuntimeError('Disk floor reached')
        folder=out/f'case_{index:03d}';folder.mkdir();schedule=folder/'requests.csv'
        schedule.write_text('at_output,target_micros\n'+''.join(f'{at},{s}\n' for at,s in case['requests']))
        meta=wav_info(case['input']);cap=math.ceil(meta['frames']*2.5)+2;capture=out/'working/capture.f32';ref=out/'working/reference.bin'
        command=[str(binary),str(case['input']),str(case['initial']),case['preset'],'capture',str(cap),'-',str(folder/'native'),case['mode'],str(case['window']),str(case['cpu']),str(case['memory']),'0','0',
            '--worker=workgroup','--resident-input=on','--profile=block','--sample-thread=on','--capture-path='+str(capture),'--speed-requests='+str(schedule)]
        started=time.time()
        with (folder/'native.log').open('x') as log:p=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=cap/meta['rate']*2+120)
        row={**{k:str(v) if isinstance(v,Path) else v for k,v in case.items()},'command':command,'native_exit':p.returncode,'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(started))}
        summary=folder/'native/summary.json'
        if summary.exists():row['native']=json.loads(summary.read_text())
        if not row.get('native',{}).get('callback_calls'):
            row['PASS']=False;row['no_audio_measurement']=True;rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n');print(args.suite,index+1,'NO_AUDIO',flush=True);continue
        d=row['native'];plans=list(csv.DictReader((folder/'native/plans.csv').open()))
        reference_command=[str(reference),str(case['input']),str(case['initial']),case['preset'],str(folder/'native'),str(ref),str(folder/'reference_live')]
        a=subprocess.run(reference_command,capture_output=True,text=True,timeout=1800);(folder/'reference.log').write_text(a.stdout+a.stderr);row['reference_command']=reference_command;row['reference_exit']=a.returncode
        if a.returncode:
            row['PASS']=False;rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n');shutil.copy2(capture,folder/'failure_capture.f32');print(args.suite,index+1,'REFERENCE_FAIL',flush=True);continue
        offset,size=0,ref.stat().st_size
        row['reference']=json.loads((folder/'reference_live.json').read_text())
        assert sha(ref)==row['reference']['pcm_sha256']
        row['pcm']=compare_pcm(capture,ref,offset,size,meta['channels'],bool(d['eos']),folder)
        row['callback_pcm_sha256']=sha(capture)
        row['generated_callback_sha_equal']=row['callback_pcm_sha256']==d['pcm_sha256'] if d['eos'] else None
        if d['eos'] and not row['generated_callback_sha_equal']:row['pcm']['PASS']=False;row['pcm']['reason']='generated/callback SHA differs'
        expected_nodes=[n[0] for n in struct.iter_unpack('<q',(folder/'reference_live.nodes.bin').read_bytes())]
        actual_nodes=(folder/'native/dynamic_map.nodes.bin').read_bytes();expected_prefix=b''.join(struct.pack('<q',n) for n in expected_nodes[:len(actual_nodes)//8])
        row['map_prefix_bit_exact']=bool(expected_nodes) and actual_nodes==expected_prefix
        row['map_complete_bit_exact']=bool(d['eos']) and row['map_prefix_bit_exact'] and len(actual_nodes)//8==len(expected_nodes)
        row['completion_nodes_exact']=all(int(p['ramp_end_frame'])<len(expected_nodes) and expected_nodes[int(p['ramp_end_frame'])]==int(p['completion_output']) for p in plans)
        operations=list(csv.DictReader((folder/'native/speeds.csv').open()));callbacks=list(csv.DictReader((folder/'native/callbacks.csv').open()))
        row['applied_operations']=len(plans);row['operation_states']=[op['state'] for op in operations];row['operation_timings']=[]
        for op in operations:
            if float(op['applied_s'])<0:continue
            def reached(bound):
                for callback in callbacks:
                    if int(callback['received']) and int(callback['output_before'])+int(callback['received'])>=int(bound):
                        return dict(sequence=int(callback['sequence']),end_ns=int(callback['end_ns']),output_after=int(callback['output_before'])+int(callback['received']))
                return None
            row['operation_timings'].append(dict(id=int(op['id']),request_to_map_apply_s=float(op['applied_s'])-float(op['accepted_s']),
                plan_cpu_s=float(op['plan_cpu_s']),plan_wall_s=float(op['plan_wall_s']),apply_presented=reached(op['applied_output']),completion_presented=reached(op['completion_output'])))
        invariant_keys=['missing_frames','missing_calls','rejected_writes','callback_deadlines','callback_formats','hal_misses','host_missing','host_backwards','host_cadence_errors','sample_errors','callback_cpp_allocations','realtime_cpp_new_calls','workgroup_deadline_misses','callback_records_dropped','worker_profile_dropped','thread_sample_errors','workgroup_policy_errors','workgroup_join_errors','workgroup_restore_errors','workgroup_interval_errors','workgroup_query_errors','workgroup_wait_errors','workgroup_wake_errors']
        row['zero_invariants']={key:d.get(key) for key in invariant_keys}
        row['transition_exercised']=len(plans)>0
        realtime_blocks=[b for b in csv.DictReader((folder/'native/worker.csv').open()) if b['realtime']=='1']
        starts=[float(b['start_s']) for b in realtime_blocks];observed=[];covered=set()
        for sample in csv.DictReader((folder/'native/thread_samples.csv').open()):
            block_index=bisect.bisect_right(starts,float(sample['before_s']))-1
            if block_index>=0 and float(sample['after_s'])<=float(realtime_blocks[block_index]['published_s']) and sample['result']=='0':
                observed.append(sample);covered.add(block_index)
        row['realtime_policy_sampling']=dict(samples=len(observed),blocks_with_samples=len(covered),realtime_blocks=len(realtime_blocks),
            policies=sorted({int(s['policy']) for s in observed}),priorities=sorted({int(s['current_priority']) for s in observed}),
            observed_realtime_class=all(int(s['policy'])==2 and int(s['current_priority'])>=64 for s in observed),
            scope='標本の前後が同じRT生成ブロック内に入るものだけ。未観測ブロックをRunningとして埋めない。')
        row['conditions_valid']=(d.get('device_id')==72 and d.get('device_rate')==48000 and d.get('device_buffer_frames')==512
            and d.get('workgroup_observed_priority')==97 and d.get('workgroup_active_after_stop')==0 and d.get('resident_input_bytes',0)>0
            and d.get('borrowed_snapshot_owners',4)<=3 and d.get('transition_map_owners',4)<=3
            and d.get('workgroup_joins')==d.get('workgroup_leaves')==d.get('workgroup_restores') and row['realtime_policy_sampling']['observed_realtime_class'])
        row['PASS']=bool(d['PASS']) and row['pcm']['PASS'] and row['map_prefix_bit_exact'] and (not d['eos'] or row['map_complete_bit_exact']) and row['reference']['frontiers_exact'] and row['completion_nodes_exact'] and row['conditions_valid'] and all(d.get(key)==0 for key in invariant_keys)
        row['wall_s']=time.time()-started;row['capture_bytes']=capture.stat().st_size;row['reference_bytes']=ref.stat().st_size
        row['working_bytes']=sum(p.stat().st_size for p in (out/'working').rglob('*') if p.is_file());assert row['working_bytes']<=512*1024**2
        row['retained_evidence_bytes']=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file());row['disk_free_bytes']=shutil.disk_usage(ROOT).free
        rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n');print(args.suite,index+1,'/',len(cases),'PASS' if row['PASS'] else 'FAIL','applied',len(plans),flush=True)
        if not row['PASS']:
            shutil.copy2(capture,folder/'failure_capture.f32');shutil.copy2(ref,folder/'failure_reference.bin')
            row['retained_evidence_bytes']=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
            (out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
    assert sha(binary)==manifest['binary_sha256'] and sha(reference)==manifest['reference_sha256']
    summary=dict(PASS=all(r['PASS'] for r in rows),attempts=len(rows),sessions=sum(bool(r.get('native',{}).get('callback_calls')) for r in rows),passed=sum(r['PASS'] for r in rows),failed=sum(not r['PASS'] for r in rows),
        full_pcm_sessions=sum(bool(r.get('pcm',{}).get('PASS') and r.get('native',{}).get('eos')) for r in rows),prefix_sessions=sum(bool(r.get('pcm',{}).get('PASS') and not r.get('native',{}).get('eos')) for r in rows),applied_operations=sum(r.get('applied_operations',0) for r in rows))
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True);return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--suite',choices=['smoke','normal','load','lifecycle','long','burst','materials'],required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--binary',type=Path,default=ROOT/'build/phase59_native');raise SystemExit(0 if run(parser.parse_args())['PASS'] else 2)

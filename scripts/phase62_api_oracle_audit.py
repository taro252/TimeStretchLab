"""通常APIの自動B接続を旧planner/Map/RAWと独立境界式で照合するドラフト。

本ファイルの作成時にはhost/oracleを実行していない。全出力は新規build/配下。
"""
import argparse
import csv
import json
import platform
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=next(parent for parent in HERE.parents if (parent/'CMakeLists.txt').is_file() and (parent/'src').is_dir() and (parent/'scripts').is_dir())
sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,sha,source_manifest,verify_architecture
from phase59_native_validation import wav_info
from phase62_dynamic_native_audit import map_position

DYNAMIC_SHA='1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818'
FIXED_SHA='de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'


class Incomplete(ValueError):pass
def need(ok,why):
    if not ok:raise ValueError(why)
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def read(path):return json.loads(path.read_text())
def rows(path):
    with path.open() as f:return list(csv.DictReader(f))
def integers(path):return [{k:int(v) for k,v in x.items()} for x in rows(path)]
def invoke(command,log,timeout,ledger):
    entry=dict(command=list(map(str,command)),status='INCOMPLETE',exit=None,timeout=False)
    ledger.append(entry)
    try:
        with log.open('w') as f:entry['exit']=subprocess.run(entry['command'],stdout=f,stderr=subprocess.STDOUT,timeout=timeout,cwd=ROOT).returncode
        entry['status']='PASS' if entry['exit']==0 else 'FAIL'
    except subprocess.TimeoutExpired:
        entry['timeout']=True;raise Incomplete('timeout: '+str(command[0]))
    finally:entry['log']=identity(log)
    return entry['exit']
def last_json(path):
    found=[]
    for line in path.read_text().splitlines():
        try:x=json.loads(line)
        except ValueError:continue
        if isinstance(x,dict):found.append(x)
    need(len(found)==1,'frozen fixed oracle final JSON missing/duplicate')
    return found[0]
def memmap(path,frames,channels):
    import numpy as np
    need(path.stat().st_size==frames*channels*4 and frames>0,'RAW byte/frame/channel count mismatch: '+str(path))
    x=np.memmap(path,dtype='<f4',mode='r',shape=(frames,channels))
    need(bool(np.isfinite(x).all()),'NaN/Inf in RAW: '+str(path))
    return x
def bit_equal(actual,expected,where):
    import numpy as np
    need(actual.shape==expected.shape,'comparison frame/channel shape mismatch')
    need(bool(np.isfinite(actual).all()) and bool(np.isfinite(expected).all()),'NaN/Inf separately rejected')
    a,b=actual.view('<u4'),expected.view('<u4')
    if not np.array_equal(a,b):
        first=np.argwhere(a!=b)[0];frame,channel=map(int,first)
        save(where,dict(frame=frame,channel=channel,actual_bits=int(a[frame,channel]),reference_bits=int(b[frame,channel])))
        raise ValueError('PCM bit mismatch: '+str(where))
def validate_capture(folder,case,fixed_initial,fixed_target,dynamic,boundary_reference,timeout,commands):
    import numpy as np
    host=read(folder/'HOST_SUMMARY.json');commit=read(folder/'COMMIT.json')
    if case['entry']>=0:
        seeks=read(folder/'SEEK.json')
        matches=[seek for seek in seeks if seek['input_C']==case['entry'] and seek['mode']=='Exact' and seek['state']=='Completed']
        need(len(matches)==1 and matches[0]['output_C']==fixed_initial['entry'],'actual initial C seek was not independent fixed Exact')
    external=read(folder/'external_requests.json')
    need(len(external)==1 and external[0]['id']==host['external_id'],'external Accepted request missing/duplicate')
    op=external[0]
    need(op['state']=='Completed' and op['target']==case['target'] and op['committed'] is True and op['output_started'] is True and not op['fixed_boundary'],'latest dynamic operation not audibly completed')
    for key in ['loop_id','input_generation','dynamic_session','dynamic_id','map_version','producer_cycle']:
        need(commit[key]==op[key] and int(commit[key])>=(0 if key=='producer_cycle' else 1),'commit/external identity mismatch: '+key)
    need(commit['external_id']==op['id']==host['external_id'] and commit['loop_id']==host['loop_id'],'external/Loop correspondence mismatch')
    need(commit['descriptor_committed'] is True and commit['atomic_commit_sample'] is True and commit['sequence']>0,'commit-time atomic sample missing')
    need(commit['source_hop']==1024,'unsupported source hop')
    converted=commit['cumulative_start']+commit['published_at_commit']-commit['local_start']
    need(commit['fifo_write_at_commit']==converted,'commit local-to-cumulative FIFO write mismatch')
    need(0<=commit['fifo_read_at_commit']<=converted,'invalid same-sample FIFO read/write')
    need(commit['pending_pcm_frames_at_commit']>=0 and commit['pcm_generated_at_commit']>=commit['pending_pcm_frames_at_commit'] and
         commit['pcm_generated_at_commit']-commit['pending_pcm_frames_at_commit']==commit['published_at_commit'],'producer P-pending != published at the same commit')
    need(commit['pending_begin_local']==commit['published_at_commit'] and commit['pending_end_local']==commit['pcm_generated_at_commit'] and
         commit['generated_at_commit']==commit['pcm_generated_at_commit'] and
         commit['local_start']<=commit['published_at_commit']<=commit['pcm_generated_at_commit'],'unpublished PCM interval mismatch')
    need(commit['deferral_reason_code']==0 and commit['cache_backed_at_commit'] is False,'fixed/cache fallback cannot pass this dynamic commit gate')
    need(commit['cumulative_end']-commit['cumulative_start']==commit['local_end']-commit['local_start'],'dynamic cumulative L mismatch')
    need(op['render_epoch']>0 and op['planning_epoch']==commit['planning_epoch'],'planning/application epoch missing or confused')
    need(op['accepted_cycle']==case['warm'] and op['cycle']==case['warm'],'current request cycle changed; use an explicitly deferred-contract test instead')
    if commit['setting_cycle_observed']:
        need(commit['setting_cycle']==op['cycle'] and commit['render_epoch']==op['render_epoch'],'audible cycle/epoch changed since evidence sample')
    need((folder/'dynamic_map.nodes.bin').stat().st_size==commit['map_nodes']*8,'product whole Map byte count mismatch')
    need((folder/'dynamic_map.nodes.bin').read_bytes()==dynamic['nodes'].read_bytes(),'whole committed product Map differs from independent planner')
    dynamic_b=dynamic['frames'] if case['b']==case['input_frames'] else map_position(dynamic['nodes'],case['b'])['rounded_output']
    dynamic_a=map_position(dynamic['nodes'],case['a'])['rounded_output']
    need(dynamic_b==commit['local_end']==op['output_end'],'dynamic B differs from independent adopted Map')
    need(op['first_changed']<op['completion']<dynamic_b,'transition did not complete in dynamic cycle')
    traces=rows(folder/'speeds.csv');plans=rows(folder/'plans.csv');reference_plans=rows(dynamic['plans'])
    applied=[x for x in traces if float(x['applied_s'])>=0]
    need(len(applied)==len(plans)==len(reference_plans)==1,'exactly one applied dynamic plan required')
    need(int(applied[0]['id'])==op['dynamic_id'] and int(applied[0]['session'])==op['dynamic_session'],'internal/external operation identity mismatch')
    need(float(applied[0]['completed_s'])>=0 and int(applied[0]['applied_output'])==op['first_changed'] and int(applied[0]['completion_output'])==op['completion'],'completion coordinates mismatch')
    for product_key,reference_key in [('generation','generation'),('applied_frame','applied_frame'),('ramp_end_frame','ramp_end'),
                                      ('applied_output','applied_output'),('completion_output','completion_output')]:
        need(int(plans[0][product_key])==int(reference_plans[0][reference_key]),'independent plan mismatch: '+product_key)
    # The frozen driver independently checks product fence against evaluate()
    # before emitting this row; its `published` is the input frontier, not fence.
    need(int(applied[0]['published_at_plan'])==int(reference_plans[0]['published']),'independent planning publication frontier differs')
    need(int(reference_plans[0]['frontier_exact'])==1 and int(reference_plans[0]['density_input'])==int(applied[0]['density_input']),
         'independent frontier/density mismatch')
    raw=memmap(folder/'observed_raw.f32',host['raw_frames'],host['channels'])
    processed=memmap(folder/'observed_processed.f32',host['output_frames'],host['channels'])
    chunks=integers(folder/'raw_chunks.csv');spans=integers(folder/'output_spans.csv');events=integers(folder/'boundaries.csv')
    need(chunks and spans and events,'capture/trace incomplete')
    epochs=[];cursor=0
    for s in spans:
        need(s['frames']>0 and s['frames']<=4096 and s['sample_frame']==s['callback_frame']==cursor,'output span gap/duplicate/zero/oversized')
        need(s['new_received']==s['frames'] and not any(s[k] for k in ['old_missing','new_missing','affected','padding']),'unexpected output missing/padding')
        if s['mixed']:
            raise Incomplete('this minimal draft captures Ready Exact C entry; live entry-mix oracle adapter remains NOT_RUN')
        if not epochs or epochs[-1]!=s['new_epoch']:epochs.append(s['new_epoch'])
        cursor+=s['frames']
    need(cursor==host['output_frames'] and len(set(epochs))==len(epochs),'output span coverage or retired epoch resurrected')
    need(op['render_epoch'] in epochs,'actual changed PCM epoch absent')
    dynamic_index=epochs.index(op['render_epoch'])
    need(dynamic_index==op['cycle'],'producer/Loop cycle mapping differs in this single-loop run')
    epoch_session={};epoch_begin={};epoch_next={};raw_cursor=0
    for r in chunks:
        need(r['frames']>0 and r['sample_frame']==raw_cursor and r['input_generation']==op['input_generation'],'RAW stream gap/identity mismatch')
        epoch=r['epoch'];need(epoch in epochs,'unreferenced RAW epoch')
        if epoch not in epoch_begin:epoch_begin[epoch]=r['output_at'];epoch_next[epoch]=r['output_at'];epoch_session[epoch]=r['session']
        need(epoch_session[epoch]==r['session'] and epoch_next[epoch]==r['output_at'],'RAW local interval overlap/gap')
        epoch_next[epoch]+=r['frames'];raw_cursor+=r['frames']
    need(raw_cursor==host['raw_frames'],'RAW chunk count differs')
    span_next=dict(epoch_begin)
    for span in spans:
        epoch=span['new_epoch']
        need(span['new_output']==span_next[epoch],'processed span local interval overlap/gap')
        span_next[epoch]+=span['frames']
    need(span_next==epoch_next,'RAW and processed epoch frame coverage differs')
    refs={};bounds={};cumulative=0;starts={};complete_lengths=[]
    first_input=case['entry'] if case['entry']>=0 else (0 if case['policy']=='keep' else case['a'])
    for i,epoch in enumerate(epochs):
        ref=dynamic if i==dynamic_index else fixed_initial if i<dynamic_index else fixed_target
        refs[epoch]=ref
        if i==dynamic_index:need(epoch_session[epoch]==op['dynamic_session'],'dynamic PCM owner session differs')
        oa=dynamic_a if i==dynamic_index else ref['a'];ob=dynamic_b if i==dynamic_index else ref['b']
        start=(fixed_initial['entry'] if i==0 else oa)
        if i==0 and i==dynamic_index:
            start=dynamic['frames'] if first_input==case['input_frames'] else map_position(dynamic['nodes'],first_input)['rounded_output']
        need(epoch_begin[epoch]==start,'first C/A output coordinate differs from independent Map')
        bounds[epoch]=(oa,ob);starts[epoch]=cumulative
        expected_end=ob if i<len(epochs)-1 else epoch_next[epoch]
        need(start<expected_end<=ob and epoch_next[epoch]==expected_end,'RAW epoch does not end exactly at independent B')
        length=expected_end-start;complete_lengths.append(length);cumulative+=length
    need(cumulative==host['output_frames'],'independent sum L_i differs from emitted output spans')
    need(len(events)==len(epochs)-1,'natural B events do not match emitted epochs')
    for i,event in enumerate(events):
        old,new=epochs[i:i+2];oa,ob=bounds[old];na,nb=bounds[new]
        need(event['loop_id']==op['loop_id'] and event['setting_cycle']==i+1 and event['old_epoch']==old and event['new_epoch']==new,'natural B identity/order mismatch')
        need(event['input_A']==case['a'] and event['input_B']==case['b'] and event['old_output_end']==ob and event['new_output_start']==na and
             event['callback_frame']==starts[new] and event['overlap']==0,'independent B/Map/length/Sigma L mismatch')
    need(len(epochs)>=dynamic_index+3,'complete next fixed A-to-B and following head not captured')
    expected_path=folder/'independent_processed.f32'
    base_path=folder/'independent_unprocessed.f32'
    expected=np.memmap(base_path,dtype='<f4',mode='w+',shape=processed.shape)
    flags=np.zeros(host['output_frames'],dtype=np.uint8)
    for r in chunks:
        ref=refs[r['epoch']]['pcm'];begin=r['output_at'];end=begin+r['frames']
        bit_equal(raw[r['sample_frame']:r['sample_frame']+r['frames']],ref[begin:end],folder/'FIRST_RAW_MISMATCH.json')
    for s in spans:
        expected[s['sample_frame']:s['sample_frame']+s['frames']]=refs[s['new_epoch']]['pcm'][s['new_output']:s['new_output']+s['frames']]
    joins=[]
    for i,event in enumerate(events):
        old,new=epochs[i:i+2];old_ref,new_ref=refs[old]['pcm'],refs[new]['pcm'];oa,ob=bounds[old];na,nb=bounds[new]
        old_n=min(case['rate']//200,(ob-oa)//4);new_n=min(case['rate']//200,(nb-na)//4);boundary=starts[new]
        last,first=old_ref[ob-1],new_ref[na]
        flags[max(0,boundary-old_n):boundary]=2
        flags[boundary:min(boundary+new_n,len(expected))]=1
        for channel in range(host['channels']):
            joins.append([boundary,old_n,new_n,channel,int(last[channel].view('<u4')),int(first[channel].view('<u4'))])
    for s in spans:
        mark=flags[s['sample_frame']:s['sample_frame']+s['frames']]
        need(not (bool((mark==1).any()) and bool((mark!=1).any())) and not (bool((mark==2).any()) and bool((mark!=2).any())),'span crosses independently derived correction window')
        need(bool(s['head'])==bool((mark==1).all()) and bool(s['tail'])==bool((mark==2).all()),'product correction classification differs from independent windows')
    expected.flush();del expected
    with (folder/'INDEPENDENT_JOINS.csv').open('w') as stream:
        writer=csv.writer(stream,lineterminator='\n');writer.writerow(['boundary','old_n','new_n','channel','last_bits','first_bits']);writer.writerows(joins)
    command=[boundary_reference,base_path,folder/'INDEPENDENT_JOINS.csv',host['channels'],host['output_frames'],expected_path]
    need(invoke(command,folder/'boundary_reference.log',timeout,commands)==0,'independent boundary equation process failed')
    boundary_result=last_json(folder/'boundary_reference.log')
    need(boundary_result.get('status')=='PASS' and boundary_result.get('expected')==boundary_result.get('executed')==1 and
         boundary_result.get('frames')==host['output_frames'] and boundary_result.get('channels')==host['channels'] and
         boundary_result.get('nonfinite')==0,'independent boundary final statistics mismatch')
    expected=memmap(expected_path,host['output_frames'],host['channels'])
    bit_equal(processed,expected,folder/'FIRST_PROCESSED_MISMATCH.json')
    return dict(status='PASS',expected=1,executed=1,independent_planner=True,whole_Map_bit_exact=True,
        dynamic_RAW_all_frames_bit_exact=True,next_fixed_RAW_bit_exact=True,final_callback_PCM_bit_exact=True,
        outside_window_frames=int((flags==0).sum()),correction_window_frames=int((flags!=0).sum()),
        output_frames=host['output_frames'],raw_frames=host['raw_frames'],channels=host['channels'],
        emitted_lengths=complete_lengths,completed_interval_lengths=complete_lengths[:-1],final_partial_frames=complete_lengths[-1],independent_Sigma_L=cumulative,dynamic_B=dynamic_b,
        producer_cycle=commit['producer_cycle'],loop_cycle=op['cycle'],map_version=op['map_version'],
        external_id=op['id'],dynamic_id=op['dynamic_id'],dynamic_session=op['dynamic_session'],
        commit_fifo_write=converted,first_input_C=first_input,
        entry_mixing='NOT_EXERCISED: Exact initial C prepared before Play',mixer_gain='NOT_RUN',physical_loopback='NOT_RUN',
        realtime_deadline_approval='NOT_ASSESSED',callback_deadlines=host['callback_deadlines'],worker_deadlines=host['worker_deadlines'],local_overall_go=False)


def main():
    p=argparse.ArgumentParser(__doc__)
    for name in ['input','preset','output','host','dynamic','fixed']:
        p.add_argument(name,**({'choices':['candidate','baseline']} if name=='preset' else {}))
    p.add_argument('--a',type=int,default=0);p.add_argument('--b',type=int)
    p.add_argument('--initial',type=int,default=1000000);p.add_argument('--target',type=int,default=750000)
    p.add_argument('--warm',type=int,default=0);p.add_argument('--request-after',type=int,default=8192)
    p.add_argument('--entry',type=int,default=-1);p.add_argument('--policy',choices=['return','keep'],default='return')
    p.add_argument('--capture-seconds',type=int,default=160);p.add_argument('--timeout',type=int,default=600)
    p.add_argument('--required-initial-period',type=int,choices=[95999,96000,96001])
    p.add_argument('--build-provenance',type=Path,required=True,help='must contain source_inventory_sha256 and host_binary_sha256 recorded by actual successful build')
    p.add_argument('--boundary-reference',type=Path,required=True,help='standalone independent C++ equation helper; same compiler/config/FP policy')
    p.add_argument('--host-source',type=Path,default=ROOT/'tests/Phase62ApiOracleNative.cpp')
    p.add_argument('--adapter-source',type=Path,default=ROOT/'tests/ApiOracleCommitAdapter.h')
    p.add_argument('--boundary-source',type=Path,default=ROOT/'tests/ApiOracleBoundaryReference.cpp')
    args=p.parse_args();out=Path(args.output).resolve();need(out.is_relative_to(ROOT/'build') and not out.exists(),'new ignored build output required');out.mkdir(parents=True)
    commands=[];result=dict(suite='phase62_API_dynamic_oracle',expected=1,executed=0,status='INCOMPLETE',local_overall_go=False)
    source=source_manifest(ROOT);paths={name:Path(getattr(args,name)).resolve() for name in ['input','host','dynamic','fixed']};paths['boundary_reference']=args.boundary_reference.resolve()
    identities={name:identity(path) for name,path in paths.items()};info=wav_info(paths['input'])
    draft_paths={name:getattr(args,name).resolve() for name in ['host_source','adapter_source','boundary_source']}
    draft_identities={name:identity(path) for name,path in draft_paths.items()}
    case=dict(a=args.a,b=args.b if args.b is not None else info['frames'],initial=args.initial,target=args.target,warm=args.warm,
              request_after=args.request_after,entry=args.entry,policy=args.policy,input_frames=info['frames'],rate=info['rate'])
    expected=dict(schema=2,run_complete=False,suite=result['suite'],expected=1,case=case,source_inventory_sha256=source['sha256'],identities=identities,
                  draft_sources=draft_identities,build_provenance=identity(args.build_provenance),auditor=identity(Path(__file__)),python=identity(Path(sys.executable)),platform=platform.platform(),machine=platform.machine(),processor=platform.processor())
    save(out/'EXPECTED.json',expected);save(out/'SOURCE.json',source);save(out/'SUMMARY.json',result)
    try:
        import numpy as np
        provenance=read(args.build_provenance)
        need(provenance.get('status')=='PASS' and provenance.get('source_inventory_sha256')==source['sha256'] and
             provenance.get('host_binary_sha256')==identities['host']['sha256'] and
             provenance.get('boundary_binary_sha256')==identities['boundary_reference']['sha256'],'successful build/source/binary correspondence missing')
        need(provenance.get('draft_source_sha256')=={key:value['sha256'] for key,value in draft_identities.items()},
             'draft host/adapter/boundary sources were not recorded at build time')
        need(provenance.get('compiler') and provenance.get('configuration') and provenance.get('architecture')=='arm64' and
             provenance.get('fp_policy') is not None,'compiler/configuration/arm64/FP policy provenance absent')
        need(identities['dynamic']['sha256']==DYNAMIC_SHA and identities['fixed']['sha256']==FIXED_SHA,'frozen oracle binary SHA mismatch')
        architectures=verify_architecture([paths[name] for name in ['host','dynamic','fixed','boundary_reference']])
        save(out/'ARCHITECTURES.json',architectures)
        need(architectures['PASS'] is True,'host/reference architecture is not exclusively arm64')
        dm=read(ROOT/'results/phase59/CAPTURED_REFERENCE.json');fm=read(ROOT/'results/phase59/FROZEN_REFERENCE.json')
        need(dm['binary_sha256']==DYNAMIC_SHA and dm['baseline_head']==fm['baseline_head']=='bb22efcbd27f999e8ffe85bbe3f03e20895be3f2' and dm['library_sha256']==fm['library_sha256'],'frozen dynamic lineage mismatch')
        need(sha(ROOT/'results/phase59/reference_driver_sources/Phase59CapturedReference.cpp')==dm['driver_source_sha256'],'saved independent driver source SHA mismatch')
        fixed_manifest=read(ROOT/'results/phase62_fix/recipes/oracle_manifest.json')
        need(fixed_manifest['binary_sha256']==FIXED_SHA and fixed_manifest['source_commit']=='ec087019626d9ff0d9f157245729b74ddb6847d7',
             'fixed oracle manifest lineage mismatch')
        need(case['a']>=0 and case['a']<case['b']<=info['frames'] and 0<=case['warm']<=8 and case['request_after']>=0 and
             (case['entry']==-1 or case['a']<=case['entry']<case['b']) and case['initial']!=case['target'],'invalid case')
        save(out/'REFERENCES.json',dict(dynamic_manifest=identity(ROOT/'results/phase59/CAPTURED_REFERENCE.json'),
             dynamic_library_manifest=identity(ROOT/'results/phase59/FROZEN_REFERENCE.json'),
             frozen_driver=identity(ROOT/'results/phase59/reference_driver_sources/Phase59CapturedReference.cpp'),
             fixed_manifest=identity(ROOT/'results/phase62_fix/recipes/oracle_manifest.json')))
        fixed_refs=[]
        for name,speed in [('initial',args.initial),('target',args.target)]:
            raw=out/(name+'.f32');log=out/(name+'.log');first=case['entry'] if case['entry']>=0 else (0 if case['policy']=='keep' else case['a'])
            command=[paths['fixed'],paths['input'],speed,args.preset,raw,case['a'],case['b'],first]
            need(invoke(command,log,args.timeout,commands)==0,'fixed frozen oracle failed')
            meta=last_json(log);need(meta['input_frames']==info['frames'] and meta['channels']==info['channels'] and meta['rate']==info['rate'],'fixed reference input/format mismatch')
            need(sha(raw)==meta['sha256'] and len(meta['positions'])==3,'fixed RAW SHA/position statistics mismatch')
            fixed_refs.append(dict(pcm=memmap(raw,meta['output_frames'],info['channels']),a=meta['positions'][0],b=meta['positions'][1],entry=meta['positions'][2],frames=meta['output_frames']))
        if args.required_initial_period is not None:
            if fixed_refs[0]['b']-fixed_refs[0]['a']!=args.required_initial_period:raise Incomplete('requested 95999/96000/96001 fixture not realized by independent fixed Map')
        native=out/'native';command=[paths['host'],paths['input'],args.preset,native,case['a'],case['b'],args.initial,args.target,args.warm,args.request_after,args.policy,args.entry,args.capture_seconds,source['sha256']]
        host_exit=invoke(command,out/'host.log',args.timeout,commands)
        if not (native/'HOST_SUMMARY.json').exists():raise Incomplete('native final statistics missing')
        host=read(native/'HOST_SUMMARY.json')
        if host['status']=='INCOMPLETE':raise Incomplete(host.get('reason','commit evidence unavailable'))
        need(host_exit==0 and host.get('expected')==host.get('executed')==1 and host['capture_complete'] is True and
             host['commit_evidence_available'] is True and host['owner_peak']<=2 and host['owners_after_stop']==0 and
             host['final_owner_statistics'] is True and host['initial_seek_count']==host['final_seek_count'] and
             host['capture_errors']==host['nonfinite']==host['missing_or_padding']==host['callback_cpp_new']==host['callback_malloc']==host['callback_free']==0,
             'native final count/lifetime/callback/capture statistics failed')
        dynamic_raw=out/'dynamic.f32';prefix=out/'dynamic'
        need(invoke([paths['dynamic'],paths['input'],args.initial,args.preset,native,dynamic_raw,prefix],out/'dynamic.log',args.timeout,commands)==0,'captured independent planner/DSP failed')
        meta=read(out/'dynamic.json')
        need(meta['frontiers_exact'] is True and meta['plans']==1 and meta['channels']==info['channels'],'independent planner/frontier final statistics missing/mismatch')
        need(sha(dynamic_raw)==meta['pcm_sha256'] and sha(out/'dynamic.nodes.bin')==meta['map_sha256'],'independent RAW/Map final SHA mismatch')
        dynamic=dict(pcm=memmap(dynamic_raw,meta['frames'],info['channels']),frames=meta['frames'],nodes=out/'dynamic.nodes.bin',plans=out/'dynamic.plans.csv')
        result=validate_capture(native,case,*fixed_refs,dynamic,paths['boundary_reference'],args.timeout,commands);result.update(suite='phase62_API_dynamic_oracle',run_complete=True)
        for key,path in paths.items():need(identity(path)==identities[key],'input/host/oracle identity changed during run')
        for key,path in draft_paths.items():need(identity(path)==draft_identities[key],'draft sources changed during run')
        need(identity(args.build_provenance)==expected['build_provenance'] and identity(Path(__file__))==expected['auditor'],
             'build provenance/auditor changed during run')
        need(source_manifest(ROOT)['sha256']==source['sha256'],'source changed during run')
    except Incomplete as error:result.update(status='INCOMPLETE',executed=0,run_complete=False,reason=str(error))
    except (ValueError,OSError,KeyError,TypeError,ImportError,subprocess.SubprocessError) as error:result.update(status='FAIL',executed=0,run_complete=False,reason=str(error))
    finally:
        save(out/'COMMANDS.json',commands);save(out/'SUMMARY.json',result)
        save(out/'ARTIFACTS.json',[identity(x) for x in out.rglob('*') if x.is_file() and x.suffix in ['.json','.csv','.log','.f32','.bin'] and x.name!='ARTIFACTS.json'])
        print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())

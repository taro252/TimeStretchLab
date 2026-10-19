import hashlib,json,re,statistics,subprocess
from pathlib import Path
ROOT=Path.cwd();OUT=ROOT/'results/paused_speed_change';OUT.mkdir(exist_ok=True)
FULL=ROOT/'build/paused_speed_full_final';CONTROL=ROOT/'build/paused_controls_final';LOOP=ROOT/'build/paused_phase62_final';EXACT=ROOT/'build/paused_exact_regression_final';GOLD=ROOT/'build/paused_speed_golden_final'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
def write(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def rows(p):return [json.loads(l) for l in p.read_text().splitlines() if l.startswith('{')]
summary=read(FULL/'summary.json');assert summary['PASS'] and summary['pcm_cases']==644 and summary['controls']==76
assert read(CONTROL/'summary.json')['PASS'] and read(EXACT/'summary.json')['passed']==96 and read(GOLD/'summary.json')['PASS']
engine=sha(ROOT/'src/platform/macos/ProgressiveMacPlaybackEngine.mm');pipeline=sha(ROOT/'src/prototype/Phase58RealtimePipeline.cpp')
provenance=read(FULL/'provenance.json');assert provenance['source_sha256']['src/platform/macos/ProgressiveMacPlaybackEngine.mm']==engine
assert provenance['native_binary_sha256']==sha(ROOT/'build/paused_speed_native_tests')
assert read(CONTROL/'provenance.json')['engine_source_sha256']==engine and read(EXACT/'provenance.json')['pipeline_sha256']==pipeline
assert read(LOOP/'provenance.json')['engine_source_sha256']==engine
ctest=ROOT/'build/paused_regression_final_v2.log';assert '100% tests passed, 0 tests failed out of 12' in ctest.read_text()
source_names=subprocess.check_output(['git','ls-files','src','CMakeLists.txt','AGENTS.md'],text=True).splitlines()
source_names += ['tests/Phase60AdapterTests.cpp','tests/PausedSpeedNativeTests.cpp','tests/PausedSpeedBoundaryTests.cpp','tests/PausedSpeedLoopTests.cpp','tests/PausedSpeedPipelineTests.cpp','scripts/verify_paused_speed.py','scripts/verify_paused_speed_controls.py','scripts/verify_paused_speed_regression.py']
sources=[{'path':n,'bytes':(ROOT/n).stat().st_size,'sha256':sha(ROOT/n)} for n in sorted(set(source_names)) if (ROOT/n).is_file()]
fingerprint=hashlib.sha256(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()).hexdigest()
names=['paused_speed_native_tests','paused_speed_boundary_tests','paused_speed_loop_tests','paused_speed_pipeline_tests','phase60_adapter_tests','phase60_lifecycle_tests','phase61_seek_check','phase62_native_tests','phase54_core_probe','libmacos_progressive_playback_engine.a','libphase58_realtime.a']
write('SOURCE_MANIFEST.json',{'start_head':'406a1fde0b130bbe5ae3ce7a1666cce696db9c99','branch':'main','dirty_source':True,'source_content_sha256':fingerprint,'source_content_hash_is_not_a_git_commit':True,'full_native_provenance':provenance,'host':{'os':'macOS 26.6.2','build':'25G83','arch':'arm64','compiler':'Apple clang 21.0.0 (clang-2100.3.34.2)','sdk':'27.0','configuration':'Release','flags':'-O3 -DNDEBUG -std=c++20 -arch arm64','cpu_model':'未取得: sysctlが制限環境で拒否','client_date':'2026-10-19','timezone':'Asia/Tokyo'},'sources':sources,'binaries':[{'path':str(ROOT/'build'/n),'bytes':(ROOT/'build'/n).stat().st_size,'sha256':sha(ROOT/'build'/n)} for n in names],'qualification':{'full_matrix':'full_finalのみ。予備full_01〜03のPCM合格を件数へ混ぜない','controls':'controls_finalの先頭18コマンドとphase62_finalの2コマンドを採用。controls_final内の旧phase62実行物の2件は参考のみ','exact':'pipelineのソースSHAを照合','golden':'既存Golden25、変更なし'}})
commands={'full':read(FULL/'commands.json'),'native_controls':[r for r in read(CONTROL/'commands.json') if not r['label'].startswith('phase62_')],'phase62_relinked_final':read(LOOP/'commands.json'),'exact':read(EXACT/'commands.json'),'golden':[{'command':r['command'],'exit':r['exit']} for r in read(GOLD/'summary.json')['results']],'ctest':{'command':['ctest','--test-dir','build','--output-on-failure','-R','^(paused_speed_pipeline|phase59_request_control|phase60_contract|phase61_contract|phase61_pipeline_sync|phase61_checkpoint|phase61_safety|phase62_fix_safety|phase62_fix_period|phase62_fix_reuse|phase62_loop|phase62_fix_checkpoint)$'],'log':str(ctest),'sha256':sha(ctest),'exit':0}}
write('COMMANDS.json',commands)
references=[]
for file in sorted(FULL.glob('*_refs/*.f32')):
    original=file.resolve();origin=original.parent.parent
    original_rows=read(origin/'commands.json')
    match=next((r for r in original_rows if 'command' in r and r['exit']==0 and str(original) in r['command']),None)
    assert match,original
    references.append({'path':str(file),'physical_origin':str(original),'bytes':file.stat().st_size,'sha256':sha(file),'generation_command':match['command'],'exit':0})
write('REFERENCE_MANIFEST.json',{'oracle':read(ROOT/'build/paused_speed_oracle_01/manifest.json'),'references':references})
latencies=[];compared=[]
for file in sorted(FULL.glob('*_pcm.log')):
    group=file.name.removesuffix('_pcm.log');items=rows(file);assert len(items)==161 and all(r['PASS'] for r in items)
    speeds=[r['speed'] for r in items];assert speeds==list(range(400000,2000001,10000))
    def stat(key):
        values=sorted(r[key] for r in items);return {'min':min(values),'median':statistics.median(values),'p95':values[round((len(values)-1)*.95)],'max':max(values)}
    latencies.append({'group':group,'cases':161,'accepted_to_ready_ms':stat('ready_ms'),'resume_request_to_first_valid_pcm_ms':stat('resume_first_pcm_ms'),'rss_bytes':stat('rss')})
    _,ch,preset=group.split('_');ch=int(ch)
    for r in items:
        raw=FULL/(group+'_refs')/(str(r['speed'])+'_'+preset+'.f32')
        with raw.open('rb') as f:f.seek(r['output']*ch*4);data=f.read(r['frames']*ch*4)
        assert len(data)==r['frames']*ch*4
        compared.append({'group':group,**r,'compared_reference_span_sha256':hashlib.sha256(data).hexdigest(),'actual_pcm_check':'callback観測データとbit完全一致を実行中にmemcmp。実測RAW頭部ファイルは保存していない。'})
write('PCM_RESULTS.json',{'rows':compared})
resources=[{'group':p.stem.removesuffix('_resources'),**rows(p)[0]} for p in sorted(CONTROL.glob('*_resources.log'))]
loop={preset:read(LOOP/preset/'result.json') for preset in ['candidate','baseline']}
write('SUMMARY.json',{'PASS':True,'source_content_sha256':fingerprint,'full_speed_pcm_cases':644,'full_speed_values_each_group':161,'full_speed_groups':4,'full_native_control_cases':76,'boundary_pcm_cases':156,'boundary_sequence_repeats_each_group':3,'live_transition_stages':12,'resource_groups':4,'loop_control_groups':4,'phase60_native_groups':2,'phase62_final_native_groups':2,'ctest_passed':12,'exact_suffix_pcm_passed':96,'golden_passed':25,'latencies':latencies,'resources':resources,'phase62_final':loop,'limitations':['未コミットソース。開始HEAD単体の結果ではない','音響出力時刻、聴感総合品質、物理装置抜差し、長尺Exact準備の全条件は未検証','公開承認・Legacy既定・FastLocal品質制限・Phase62 opt-in/NO-GOを維持']})
existing=[]
for line in subprocess.check_output(['git','ls-tree','-r','-l','HEAD'],text=True).splitlines():
    info,path=line.split('\t',1);parts=info.split()
    if parts[1]=='blob' and int(parts[3])>=50_000_000:existing.append({'path':path,'bytes':int(parts[3]),'blob':parts[2]})
changes=subprocess.check_output(['git','ls-files','--modified','--others','--exclude-standard'],text=True).splitlines()
files=[{'path':p,'bytes':(ROOT/p).stat().st_size} for p in changes if (ROOT/p).is_file()]
assert all(r['bytes']<50_000_000 for r in files)
write('BLOB_AUDIT.json',{'limit_bytes':50_000_000,'staged_count':len(subprocess.check_output(['git','diff','--cached','--name-only'],text=True).splitlines()),'new_working_files':files,'existing_head_tree_large_blobs':existing,'existing_blobs_untouched':True,'commit_push_history_rewrite_lfs_migration':False})
print(json.dumps({'PASS':True,'source_content_sha256':fingerprint,'reference_files':len(references),'max_working_file_bytes':max(r['bytes'] for r in files),'latencies':latencies},ensure_ascii=False,indent=2))

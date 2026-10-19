import json,sys,subprocess,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity
OUT=ROOT/'build/phase62_fix/run_01/final_v9';RELEASE=(OUT/'release').resolve();DEBUG=(OUT/'debug').resolve();python=sys.executable
bundled='/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3'
cases=[];jobs=[]
def plan(name,cmd,result):
 cases.append(dict(id=name,kind='json_pass',required=[name+'/'+result],result=name+'/'+result));jobs.append((name,cmd))
for config,build in [('Release',RELEASE),('Debug',DEBUG)]:
 name=config.lower()+'_ctest';plan(name,[python,'-B','scripts/phase62_verify.py','--suite','ctest','--configuration',config,'--build',str(build),'--output',str(OUT/'evidence'/name)],'summary.json')
for suite in ['exact','golden','pcm','pcm161','native','controls','long','step1']:
 name='release_'+suite;plan(name,[python,'-B','scripts/phase62_verify.py','--suite',suite,'--build',str(RELEASE),'--output',str(OUT/'evidence'/name)],'summary.json')
for suite in ['offline','short','longA','clock','deadline']:
 name='release_'+suite;plan(name,[python,'-B','scripts/phase62_fix_additional.py','--suite',suite,'--build',str(RELEASE),'--output',str(OUT/'evidence'/name)],'SUMMARY.json')
name='release_quality';plan(name,[bundled,'-B','scripts/phase62_fix_quality.py','--build',str(RELEASE),'--output',str(OUT/'evidence'/name)],'SUMMARY.json')
for suite in ['native','controls','long']:
 name='debug_'+suite;plan(name,[python,'-B','scripts/phase62_verify.py','--suite',suite,'--configuration','Debug','--build',str(DEBUG),'--output',str(OUT/'evidence'/name)],'summary.json')
name='release_cli';plan(name,[python,'-B','scripts/phase62_cli_smoke.py','--host',str(RELEASE/'phase62_loop_play'),'--input',str(ROOT/'build/phase62/run_01/native_release/boundary_48000_2_1.wav'),'--output',str(OUT/'evidence'/name)],'summary.json')
for name,reason in [('current_cycle_dynamic_speed','動的Mapとbounded B確定の統合が未実装。フラグ変更だけでは代替しない'),('different_speed_independent_capture','異速度境界の独立DSP付き最終キャプチャ試験は未実装'),('subjective_listening','ユーザーの試聴承認なし'),('acoustic_loopback','物理的音響ループバック測定装置を使用していない'),('merodoa_tcc_bookmark','Merodoa本体変更は対象外。実アプリのTCC拒否・期限切れbookmark未実施')]:cases.append(dict(id=name,kind='exit',reason=reason))
unaffected=['release_ctest','debug_ctest','release_exact','release_golden','release_pcm','release_pcm161','release_native']
cases=[case for case in cases if case['id'] not in unaffected];jobs=[job for job in jobs if job[0] not in unaffected]
audit_cases=[dict(id='dependency_audit',kind='json_pass',required=['dependency_audit.json'],result='dependency_audit.json'),dict(id='dependency_audit_after_main',kind='json_pass',required=['dependency_audit_after_main.json'],result='dependency_audit_after_main.json')]
cases=[audit_cases[0],*cases,audit_cases[1]];jobs=[('dependency_audit',[python,'-B',OUT/'dependency_audit.py']),*jobs,('dependency_audit_after_main',[python,'-B',OUT/'dependency_audit.py','--after'])]
frozen=source_manifest(ROOT);ledger=Ledger(OUT/'evidence',cases,dict(source=frozen,driver=identity(__file__),build_release=str(RELEASE),build_debug=str(DEBUG),unaffected_evidence_source='final_v8; original SHA retained; see dependency_audit'))
for name in unaffected:(OUT/'evidence'/name).symlink_to('../../final_v8/evidence/'+name,target_is_directory=True)
for case in cases:
 if 'reason' in case:ledger.rows[case['id']]['reasons']=[case['reason']]
ledger.save()
for name,cmd in jobs:
 print(time.strftime('%F %T'),name,'START',flush=True)
 ok=ledger.run(name,cmd,cwd=ROOT,timeout=14400)
 print(time.strftime('%F %T'),name,ledger.rows[name]['status'],flush=True)
 if source_manifest(ROOT)['sha256']!=frozen['sha256']:
  print('SOURCE CHANGED; remaining cases not run',flush=True);break
result=aggregate(OUT/'evidence');(OUT/'FINAL_AGGREGATE.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
print(result['counts'],flush=True)

import sys,json,subprocess,time,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_gates';out.mkdir();source=source_manifest(ROOT);rows=[]
names=['phase59_certified_planning','phase59_request_control','phase61_contract','phase61_checkpoint','phase61_safety','phase61_output_transition','phase61_pipeline_sync','paused_speed_pipeline','phase62_loop','phase62_render','phase62_fix_safety','phase62_evidence','phase62_fix_reuse','phase62_fix_period','phase62_fix_checkpoint','phase62_dynamic_boundary']
targets=['phase59_tests','phase59_control_tests','phase61_contract_tests','phase61_checkpoint_tests','phase61_safety_tests','phase61_output_transition_tests','phase61_pipeline_sync_tests','paused_speed_pipeline_tests','phase62_loop_tests','phase62_render_tests','phase62_fix_safety_tests','phase62_fix_reuse_tests','phase62_fix_render_tests','phase62_fix_checkpoint_tests','phase62_dynamic_boundary_tests','phase62_native_tests','paused_speed_loop_tests']
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,ctest_names=names,ctest_per_configuration=16,configurations=['Release','Debug'],targets=targets),indent=2)+'\n')
def run(key,command,timeout=1800):
    if source_manifest(ROOT)['sha256']!=source['sha256']:raise RuntimeError('source changed')
    start=time.time();timed=False
    with (out/(key+'.log')).open('w') as stream:
        try:code=subprocess.run(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,timeout=timeout).returncode
        except subprocess.TimeoutExpired:code=None;timed=True
    row=dict(id=key,command=list(map(str,command)),exit=code,status='INCOMPLETE' if timed else 'PASS' if code==0 else 'FAIL',seconds=time.time()-start);rows.append(row)
    (out/'SUMMARY.json').write_text(json.dumps(dict(rows=rows,local_overall_go=False),indent=2)+'\n');print(key,row['status'],flush=True);return row
for configuration,build in [('Release',base/'release'),('Debug',base/'debug')]:
    if run('configure_'+configuration,['cmake','-S',ROOT,'-B',build,'-DCMAKE_BUILD_TYPE='+configuration,'-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON'])['status']!='PASS':continue
    if run('build_'+configuration,['cmake','--build',build,'--target',*targets,'-j2'])['status']!='PASS':continue
    xml=out/('ctest_'+configuration+'.xml');row=run('ctest_'+configuration,['ctest','--test-dir',build,'-R','^('+'|'.join(names)+')$','--parallel','1','--output-on-failure','--output-junit',xml],3600)
    actual=ET.parse(xml).getroot().findall('.//testcase') if xml.exists() else []
    valid=len(actual)==len(names) and sorted(t.get('name') for t in actual)==sorted(names) and not any(t.find(tag) is not None for t in actual for tag in ['failure','error','skipped'])
    row.update(expected=16,executed=len(actual),verified=valid)
    if not valid:row['status']='FAIL'
    (out/'SUMMARY.json').write_text(json.dumps(dict(rows=rows,local_overall_go=False),indent=2)+'\n')

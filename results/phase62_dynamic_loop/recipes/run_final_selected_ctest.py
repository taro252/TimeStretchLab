import sys,json,subprocess,xml.etree.ElementTree as ET,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_boundary_ctest';out.mkdir();source=source_manifest(ROOT);names=['phase62_fix_safety','phase62_dynamic_boundary'];jobs=[]
for config in ['release','debug']:
 build=base/config;xml=out/(config+'.xml');command=list(map(str,['ctest','--test-dir',build,'-R','^('+'|'.join(names)+')$','--parallel','1','--output-on-failure','--output-junit',xml]));jobs.append(dict(configuration=config,command=command,xml=str(xml),binaries=[identity(build/name) for name in ['phase62_fix_safety_tests','phase62_dynamic_boundary_tests']]))
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,expected_programs=2,ctest_names=names,ctest_per_configuration=2,jobs=jobs),indent=2)+'\n');rows=[]
for job in jobs:
 assert source_manifest(ROOT)['sha256']==source['sha256'];start=time.time()
 with (out/(job['configuration']+'.log')).open('w') as log:code=subprocess.run(job['command'],stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
 tests=ET.parse(job['xml']).getroot().findall('.//testcase') if Path(job['xml']).exists() else []
 valid=code==0 and sorted(t.get('name') for t in tests)==sorted(names) and not any(t.find(tag) is not None for t in tests for tag in ['failure','error','skipped'])
 rows.append(dict(configuration=job['configuration'],exit=code,status='PASS' if valid else 'FAIL',expected=2,executed=len(tests),seconds=time.time()-start));(out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=2,executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(job['configuration'],rows[-1]['status'],flush=True)

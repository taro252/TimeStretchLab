"""測定完了後に実行。全原本のSHA manifestとGit向け小indexを分ける。"""
import hashlib,json,os,sys,time,subprocess
from pathlib import Path
ROOT=Path.cwd();RUN=ROOT/'build/phase62_fix/run_01';F=RUN/'final_v9';OUT=ROOT/'results/phase62_fix';FULL=RUN/'ARTIFACTS_ALL.json'
sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
assert all((F/name/'SUMMARY.json').is_file() for name in ('listening_pack','piano_quality','piano_waveform','piano_listening_pack','clock_startup_extended','inside_seek','boundary_methods')),'測定・解析完了前には採用しない'
assert (F/'ORIGINAL_PHASE62_AUDIT.json').is_file() and (F/'figure_repair/SUMMARY.json').is_file()
expected=json.loads((F/'FROZEN_SOURCE.json').read_text());assert source_manifest(ROOT)==expected,'最終source変更'
rows=[]
for p in sorted(RUN.rglob('*')):
 if p==FULL:continue
 if p.is_symlink():
  value=os.readlink(p);rows.append(dict(path=str(p.relative_to(RUN)),type='symlink',target=value,bytes=len(os.fsencode(value)),sha256=hashlib.sha256(os.fsencode(value)).hexdigest()));continue
 if p.is_dir():continue
 before=p.stat()
 with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 after=p.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),str(p)+' changed during hashing'
 rows.append(dict(path=str(p.relative_to(RUN)),type='file',bytes=after.st_size,sha256=digest))
FULL.write_text(json.dumps(dict(schema=1,root=str(RUN),entries=len(rows),total_bytes=sum(r['bytes'] for r in rows),files=rows),indent=2)+'\n')
important_names={'EXPECTED.json','LEDGER.json','SUMMARY.json','summary.json','BUILD_PROVENANCE.json','FROZEN_SOURCE.json','ENVIRONMENT.json','START_STATE.json','INTERRUPTION.json','DEVICE_RESTORE_AFTER_CRASH.json','CLOCK_STARTUP_ANALYSIS.json','PRODUCTION_SOURCE_UNCHANGED.json','PAIR_COMPARISON.json','INPUT_RECIPE.json','INPUTS.json','APP_RESULT.json','SIGNATURE.json','LAUNCH.json','RUN_CONTEXT.json','GRANTS.json','DENIED.json','FIGURE.json','DEVICE_IDENTITY.json','INTERRUPTED_AGGREGATE.json','BUFFER_RESTORE.json','COMMAND.json','dependency_audit.json','dependency_audit_after_main.json','dependency_audit_after_sandbox.json','QUALITY_RATE_FINDING.json','ANALYSIS.json','inside_seek.json','inside_reference.json','FAILURE_ANALYSIS.json','ORIGINAL_PHASE62_AUDIT.json','PLOT_DEPENDENCIES.json'}
important=[]
for row in rows:
 p=Path(row['path']);name=p.name
 if name in important_names or p.suffix in ('.py','.ips') or name.endswith('.tar.gz') or name.endswith('_device.json') or (name=='clock_anomaly_window.jsonl' and row['bytes']) or (name.startswith('phase') and not p.suffix) or name=='waveform_comparison.png':important.append(row)
index=dict(schema=1,root=str(RUN),full_manifest=identity(FULL),full_entries=len(rows),full_total_bytes=sum(r['bytes'] for r in rows),important_entries=len(important),files=important,restore='RESTORE.md。大容量の原本はこのroot全体を保存し、full manifestで照合する。')
(OUT/'ARTIFACT_MANIFEST.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
changed=set(subprocess.check_output(['git','diff','--name-only','HEAD','-z'],cwd=ROOT).split(b'\0'))|set(subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=ROOT).split(b'\0'))
changes=[]
for encoded in sorted(v for v in changed if v):
 path=os.fsdecode(encoded);p=ROOT/path
 if path=='results/phase62_fix/CHANGED_FILES.json':continue
 old=subprocess.run(['git','show','HEAD:'+path],cwd=ROOT,capture_output=True)
 changes.append(dict(path=path,old_sha256=hashlib.sha256(old.stdout).hexdigest() if old.returncode==0 else None,new=identity(p) if p.is_file() else None))
(OUT/'CHANGED_FILES.json').write_text(json.dumps(dict(base_head='d25433c88a1bae83b89168a26f1c6c9d8053a644',self_excluded='CHANGED_FILES.json',files=changes),indent=2)+'\n')
print(dict(entries=len(rows),important=len(important),bytes=index['full_total_bytes'],source_unchanged=True),flush=True)

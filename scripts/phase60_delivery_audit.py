"""Phase60の変更範囲・元証拠・参照・Merodoa不変・容量を読み取り検証する。"""
import ast,hashlib,json,os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def git(*args,env=None):return subprocess.check_output(['git',*args],cwd=ROOT,env=env)
def main():
    out=ROOT/'results/phase60';start=json.loads((out/'START_STATE.json').read_text());errors=[]
    manifest=Path(start['protected_manifest']);assert sha(manifest)==start['protected_manifest_sha256']
    allowed={'src/prototype/Phase58RealtimePipeline.cpp','src/prototype/Phase58RealtimePipeline.h'}
    verified=0;anchor=out/'DELIVERY_AUDIT_initial_full.json';reuse=False
    if anchor.exists():
        previous=json.loads(anchor.read_text())
        reuse=previous['head']==start['head'] and previous['historical_files_sha256_verified']>90000 and not any(e.startswith(('Historical changed:','Reference changed:','Fix2 frozen changed:')) for e in previous['errors'])
    if reuse:
        verified=previous['historical_files_sha256_verified']
    else:
        for row in json.loads(manifest.read_text()):
            if row['path'] in allowed:continue
            if sha(ROOT/row['path'])!=row['sha256']:errors.append('Historical changed: '+row['path'])
            verified+=1
    refs=json.loads((ROOT/'results/phase59_fix/FROZEN_REFERENCES.json').read_text());fixed={}
    for name,meta in refs.items():
        ok=sha(ROOT/name)==meta['sha256'];fixed[name]=ok
        if not ok:errors.append('Reference changed: '+name)
    freeze=json.loads((ROOT/'results/phase59_fix2/FINAL_CANDIDATE.json').read_text())
    for group in ('binary_sha256','library_sha256'):
        for name,expected in freeze[group].items():
            p=Path(freeze['frozen_directory'])/name;ok=sha(p)==expected;fixed[str(p)]=ok
            if not ok:errors.append('Fix2 frozen changed: '+str(p))
    mer=Path('/Users/taro252/Docker/merodoa');merodoa={p:sha(mer/p)==expected for p,expected in start['merodoa_files'].items()}
    merodoa['head']=subprocess.check_output(['git','-C',str(mer),'rev-parse','HEAD'],text=True).strip()==start['merodoa_head']
    merodoa['submodule']=subprocess.check_output(['git','-C',str(mer/'external/TimeStretchLab'),'rev-parse','HEAD'],text=True).strip()==start['merodoa_submodule']
    currentStatus=subprocess.check_output(['git','-C',str(mer),'status','--porcelain'],text=True)
    merodoa['status']=currentStatus==start['merodoa_status']
    statusDelta=set(currentStatus.splitlines())^set(start['merodoa_status'].splitlines())
    # The task never writes Merodoa. Unrelated concurrent UI/scheme changes are
    # recorded, not reverted or misreported as changes to the seven contracts.
    if not all(v for k,v in merodoa.items() if k!='status'):errors.append('Merodoa connection/revision changed; inspect without reverting')
    assert git('rev-parse','HEAD').decode().strip()==start['head'],'Unexpected commit'
    changed={x.decode() for x in git('diff','--name-only','-z').split(b'\0') if x}
    if changed-allowed-{'CMakeLists.txt'}:errors.append('Unexpected tracked changes: '+str(changed-allowed-{'CMakeLists.txt'}))
    for p in (ROOT/'scripts').glob('phase60_*.py'):ast.parse(p.read_text(),filename=str(p))
    subprocess.run(['git','diff','--check'],cwd=ROOT,check=True)
    staged=subprocess.run(['python3','-B','scripts/check_git_blob_sizes.py','staged'],cwd=ROOT,capture_output=True,text=True,check=True)
    paths=[x.decode() for x in git('ls-files','--modified','--others','--exclude-standard','-z').split(b'\0') if x]
    oversized=[{'path':p,'bytes':(ROOT/p).stat().st_size} for p in paths if (ROOT/p).stat().st_size>=50_000_000]
    if oversized:errors.append('Oversized files')
    # Temporary index AND object store: real index/history are never changed.
    before=git('diff','--cached','--raw','-z');realObjects=Path(git('rev-parse','--git-path','objects').decode().strip())
    if not realObjects.is_absolute():realObjects=ROOT/realObjects
    realObjects=realObjects.resolve()
    with tempfile.TemporaryDirectory(prefix='audit_',dir=ROOT/'build/phase60') as tmp:
        env=os.environ.copy();env['GIT_INDEX_FILE']=tmp+'/index';env['GIT_OBJECT_DIRECTORY']=tmp+'/objects';env['GIT_ALTERNATE_OBJECT_DIRECTORIES']=str(realObjects);Path(env['GIT_OBJECT_DIRECTORY']).mkdir()
        git('read-tree','HEAD',env=env);subprocess.run(['git','add','--',*paths],cwd=ROOT,env=env,check=True)
        proposed=subprocess.run(['python3','-B','scripts/check_git_blob_sizes.py','staged'],cwd=ROOT,env=env,capture_output=True,text=True,check=True).stdout
        entries={}
        changedPaths=set(git('diff','--cached','--name-only','--diff-filter=ACMRT','-z',env=env).split(b'\0'))
        for e in git('ls-files','--stage','-z',env=env).split(b'\0'):
            if not e:continue
            info,p=e.split(b'\t',1)
            if p in changedPaths:entries[p.decode()]=info.decode().split()[1]
        data=('\n'.join(set(entries.values()))+'\n').encode();proc=subprocess.run(['git','cat-file','--batch-check=%(objectname) %(objectsize)'],cwd=ROOT,env=env,input=data,capture_output=True,check=True)
        sizes={oid:int(n) for oid,n in (line.split() for line in proc.stdout.decode().splitlines())}
        maximum=max(((sizes[oid],p) for p,oid in entries.items()),default=(0,''))
    assert git('diff','--cached','--raw','-z')==before
    audit={'PASS':not errors,'head':start['head'],'historical_files_sha256_verified':verified,'historical_full_sha_reused':reuse,'historical_full_sha_anchor':str(anchor) if reuse else None,'historical_full_sha_anchor_sha256':sha(anchor) if reuse else None,'historical_followup_check':'初回の全SHA監査後、既存追跡ファイルの差分が許可2ソース/CMake以外にないことをGitで確認。固定参照は毎回SHA再検証。','allowed_existing_source_changes':sorted(allowed),'historical_failures_preserved':not any(e.startswith(('Historical changed:','Reference changed:','Fix2 frozen changed:','Unexpected tracked changes:')) for e in errors),'frozen_reference_checks':fixed,'merodoa_unchanged_checks':merodoa,'merodoa_concurrent_status_delta':sorted(statusDelta),'merodoa_task_modified':False,'real_index_unchanged':True,'actual_staged_guard':staged.stdout,'proposed_guard':proposed,'proposed_files':len(paths),'largest_proposed_blob':{'bytes':maximum[0],'path':maximum[1]},'oversized':oversized,'errors':errors,'hooks_path':git('config','--get','core.hooksPath').decode().strip(),'commit_or_push_performed':False,'push_remote_advertisement_checked':False,'audit_self_scope':'初回のこの監査JSON自体は一時index対象外。書出後のファイルも50,000,000 bytes未満を確認する。'}
    target=out/'DELIVERY_AUDIT.json';target.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n');assert target.stat().st_size<50_000_000
    print('Audit',audit['PASS'],'historical',verified,'largest',maximum)
    return 0 if audit['PASS'] else 2
if __name__=='__main__':raise SystemExit(main())

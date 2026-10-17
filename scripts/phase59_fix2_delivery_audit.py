"""旧証拠と固定候補を照合し、一時indexだけで新規blobを検査する。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


def git(*args,env=None,data=None):
    return subprocess.run(['git',*args],cwd=ROOT,env=env,input=data,capture_output=True,check=True).stdout


def main():
    start=json.loads((OUT/'START_STATE.json').read_text())
    assert sha(start['protected_manifest'])==start['protected_manifest_sha256']
    protected=json.loads(Path(start['protected_manifest']).read_text())
    prior=json.loads((ROOT/'results/phase59_fix/ARTIFACT_INDEX.json').read_text())['files']
    references=json.loads((OUT/'PROTECTED_REFERENCES.json').read_text())
    records={r['path']:r for r in protected+prior+references['golden']+start['evidence']+start['binaries']}
    for name,r in references['references'].items():records[str(ROOT/name)]=dict(path=str(ROOT/name),**r)
    bad=[]
    for name,r in records.items():
        path=Path(name)
        if not path.exists() or path.stat().st_size!=r['bytes'] or sha(path)!=r['sha256']:bad.append(name)
    assert not bad,('Historical evidence changed',bad)
    frozen=json.loads((OUT/'FINAL_CANDIDATE.json').read_text());checks={}
    for name,digest in frozen['source_sha256'].items():checks[name]=sha(ROOT/name)==digest
    for field in ('binary_sha256','library_sha256'):
        for name,digest in frozen[field].items():checks[str(Path(frozen['frozen_directory'])/name)]=sha(Path(frozen['frozen_directory'])/name)==digest
    assert all(checks.values()),[k for k,v in checks.items() if not v]
    saved=Path(frozen['frozen_directory'])/'source'
    assert sha(ROOT/'CMakeLists.txt')==sha(saved/'CMakeLists.txt')
    assert all(sha(r['path'])==r['sha256'] for r in frozen['file_manifest'])
    assert not git('diff','--name-only','HEAD','--','results').strip(),'Tracked historical result changed'
    assert not git('diff','--name-only','HEAD','--','tests/reference').strip()
    paths=set(git('diff','--name-only','-z','HEAD').split(b'\0'))|set(git('ls-files','--others','--exclude-standard','-z').split(b'\0'));paths.discard(b'')
    proposed=[]
    for raw in sorted(paths):
        path=ROOT/os.fsdecode(raw)
        if path.exists() or path.is_symlink():
            size=path.lstat().st_size;assert size<50_000_000,(str(path),size)
            proposed.append(dict(path=os.fsdecode(raw),bytes=size))
    before=git('diff','--cached','--raw','-z');common=Path(os.fsdecode(git('rev-parse','--path-format=absolute','--git-common-dir')).strip())
    with tempfile.TemporaryDirectory(prefix='phase59_fix2_git_audit_') as temp:
        temp=Path(temp);objects=temp/'objects';objects.mkdir()
        env={**os.environ,'GIT_INDEX_FILE':str(temp/'index'),'GIT_OBJECT_DIRECTORY':str(objects),'GIT_ALTERNATE_OBJECT_DIRECTORIES':str(common/'objects')}
        git('read-tree','HEAD',env=env)
        git('add','--pathspec-from-file=-','--pathspec-file-nul',env=env,data=b'\0'.join(sorted(paths))+b'\0')
        check=subprocess.run([sys.executable,'-B','scripts/check_git_blob_sizes.py','staged'],cwd=ROOT,env=env,capture_output=True,text=True)
        assert check.returncode==0,check.stdout+check.stderr
        staged=[]
        for line in git('ls-files','--stage','-z',env=env).split(b'\0'):
            if not line:continue
            info,name=line.split(b'\t',1)
            if name not in paths:continue
            mode,oid,stage=info.decode().split()
            if mode=='160000':continue
            size=int(git('cat-file','-s',oid,env=env));assert size<50_000_000
            staged.append(dict(path=os.fsdecode(name),blob=oid,bytes=size))
    assert before==git('diff','--cached','--raw','-z')
    actual=subprocess.run([sys.executable,'-B','scripts/check_git_blob_sizes.py','staged'],cwd=ROOT,capture_output=True,text=True)
    history=subprocess.run([sys.executable,'-B','scripts/check_git_blob_sizes.py','history','--base','origin/main','--tip','HEAD'],cwd=ROOT,capture_output=True,text=True)
    assert actual.returncode==history.returncode==0
    diff=subprocess.run(['git','diff','--check'],cwd=ROOT,capture_output=True,text=True);assert diff.returncode==0,diff.stdout+diff.stderr
    result=dict(PASS=True,head=git('rev-parse','HEAD').decode().strip(),branch=git('branch','--show-current').decode().strip(),
        historical_evidence_files_verified=len(records),historical_failures_preserved=True,final_candidate_checks=checks,
        real_index_unchanged=True,actual_staged_check=actual.stdout,proposed_index_check=check.stdout,proposed_blobs=staged,
        local_outgoing_history_check=history.stdout,network_remote_refs_checked=False,
        hooks_path=git('config','--local','--get','core.hooksPath').decode().strip(),
        commits_created=0,pushes=0,history_rewritten=False,lfs_migration=False,diff_check_pass=True,
        scope='検査用index/objectは/tmpのみ。既存Git objectは読み取りだけ。Push先の最新広告refはPush時のpre-pushで検査する。')
    (OUT/'GIT_DELIVERY_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('audit PASS; historical',len(records),'proposed',len(staged),'actual index unchanged',flush=True)


if __name__=='__main__':main()

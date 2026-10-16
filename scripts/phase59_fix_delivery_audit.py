"""旧証拠・固定参照と、実indexを変更しない提案内容のblob検査。コミット/Pushしない。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from phase57_study import ROOT,sha


def git(*args,env=None,data=None):
    return subprocess.run(['git',*args],cwd=ROOT,env=env,input=data,capture_output=True,check=True).stdout


def main():
    out=ROOT/'results/phase59_fix'
    old=json.loads((out/'FROZEN_REFERENCES.json').read_text())
    frozen=json.loads((out/'FINAL_CANDIDATE.json').read_text())
    checks={}
    for path,record in old.items():checks[path]=sha(ROOT/path)==record['sha256']
    assert all(checks.values()),'Historical reference changed'
    start=json.loads((out/'START_STATE.json').read_text())
    large=[]
    for entry in start['historical_large_tracked_files']:
        path=ROOT/entry['path'];preserved=path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256']
        large.append({**entry,'preserved_at_delivery':preserved});assert preserved
    assert all(sha(ROOT/path)==digest for path,digest in frozen['source_sha256'].items())
    saved_source=Path(frozen['frozen_directory'])/'source'
    build_inputs={str(p.relative_to(saved_source)):sha(ROOT/p.relative_to(saved_source))==sha(p)
                  for p in saved_source.rglob('*') if p.is_file()}
    assert all(build_inputs.values()),'Frozen build input changed'
    assert not git('diff','--name-only','HEAD','--','results').strip(),'Historical tracked result changed'
    paths=set(git('diff','--name-only','-z','HEAD').split(b'\0'))|set(git('ls-files','--others','--exclude-standard','-z').split(b'\0'))
    paths.discard(b'')
    proposed=[]
    for raw in sorted(paths):
        name=os.fsdecode(raw);path=ROOT/name
        if path.exists() or path.is_symlink():
            size=path.lstat().st_size;assert size<50_000_000,(name,size)
            proposed.append(dict(path=name,working_bytes=size))
    actual_index_before=git('diff','--cached','--raw','-z')
    common=Path(os.fsdecode(git('rev-parse','--path-format=absolute','--git-common-dir')).strip())
    with tempfile.TemporaryDirectory(prefix='phase59_fix_git_audit_') as temporary:
        temporary=Path(temporary);objects=temporary/'objects';objects.mkdir()
        env={**os.environ,'GIT_INDEX_FILE':str(temporary/'index'),'GIT_OBJECT_DIRECTORY':str(objects),
             'GIT_ALTERNATE_OBJECT_DIRECTORIES':str(common/'objects')}
        git('read-tree','HEAD',env=env)
        git('add','--pathspec-from-file=-','--pathspec-file-nul',env=env,data=b'\0'.join(sorted(paths))+b'\0')
        validation=subprocess.run([sys.executable,'-B','scripts/check_git_blob_sizes.py','staged'],cwd=ROOT,env=env,capture_output=True,text=True)
        assert validation.returncode==0,validation.stdout+validation.stderr
        staged=[]
        for line in git('ls-files','--stage','-z',env=env).split(b'\0'):
            if not line:continue
            info,name=line.split(b'\t',1)
            if name not in paths:continue
            mode,oid,stage=info.decode().split()
            if mode=='160000':continue
            size=int(git('cat-file','-s',oid,env=env))
            staged.append(dict(path=os.fsdecode(name),blob=oid,bytes=size));assert size<50_000_000
    assert git('diff','--cached','--raw','-z')==actual_index_before,'Real index changed'
    actual=subprocess.run([sys.executable,'-B','scripts/check_git_blob_sizes.py','staged'],cwd=ROOT,capture_output=True,text=True)
    history=subprocess.run([sys.executable,'-B','scripts/check_git_blob_sizes.py','history','--base','origin/main','--tip','HEAD'],cwd=ROOT,capture_output=True,text=True)
    assert actual.returncode==history.returncode==0
    result=dict(PASS=True,head=git('rev-parse','HEAD').decode().strip(),branch=git('branch','--show-current').decode().strip(),
        historical_reference_checks=checks,historical_large_files=large,historical_tracked_results_unchanged=True,
        final_source_209_unchanged=True,real_index_unchanged=True,actual_staged_check=actual.stdout,
        frozen_build_input_checks=build_inputs,script_sha256=sha(Path(__file__)),
        proposed_index_check=validation.stdout,proposed_blobs=staged,working_files=proposed,
        local_outgoing_history_check=history.stdout,network_remote_refs_checked=False,
        hooks_path=git('config','--local','--get','core.hooksPath').decode().strip(),
        commits_created=0,pushes=0,history_rewritten=False,lfs_migration=False,
        scope='提案内容は/tmpの専用index/object storeと既存objectsの読取り専用参照で検査。実index/object storeへ追加しない。Push時の広告ref確認は実際のpre-pushで別途実施する。')
    (out/'GIT_DELIVERY_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('delivery audit PASS',len(staged),'proposed blobs; actual index unchanged',flush=True)


if __name__=='__main__':main()

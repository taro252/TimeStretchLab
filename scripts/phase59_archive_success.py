"""Lossless storage compaction of this phase's verified, inactive artifacts."""
import gzip,hashlib,json,os,shutil,subprocess,tarfile,time
from pathlib import Path
from phase57_study import ROOT,sha

def main():
    out=ROOT/'results/phase59';pause=json.loads((out/'storage_pause_final.json').read_text());assert pause['audio_quiescent']
    assert json.loads((out/'regression_final/summary.json').read_text())['PASS']
    assert json.loads((out/'eos_pending_final/summary.json').read_text())['PASS']
    archive=ROOT/'build/phase59_archives';archive.mkdir(exist_ok=False)
    records=[];before=shutil.disk_usage(ROOT).free
    def untracked(path):
        tracked=subprocess.check_output(['git','ls-files','--',str(path.relative_to(ROOT))],cwd=ROOT,text=True)
        assert not tracked,'Never remove tracked evidence: '+str(path)
    def commit_record(record):
        records.append(record);(out/'STORAGE_COMPACTION.json').write_text(json.dumps(dict(free_before=before,records=records,free_now=shutil.disk_usage(ROOT).free),indent=2,ensure_ascii=False)+'\n')
    # Keep exact binaries/objects as a verified archive, including the Debug
    # cache and exported XML. Frozen references and the original trace remain.
    for source,label in [(ROOT/'build/phase59_debug','passed_debug_build'),(ROOT/'build/phase59_frozen/startup_trace_v1_xml','derived_trace_xml')]:
        untracked(source);inventory={}
        for p in source.rglob('*'):
            if p.is_symlink():inventory[str(p.relative_to(source))]=dict(symlink=os.readlink(p))
            elif p.is_file():inventory[str(p.relative_to(source))]=dict(bytes=p.stat().st_size,sha256=sha(p))
        destination=archive/(label+'.tar.gz')
        with tarfile.open(destination,'w:gz',compresslevel=5) as tar:tar.add(source,arcname=source.name)
        with tarfile.open(destination,'r:gz') as tar:
            for name,record in inventory.items():
                item=tar.getmember(source.name+'/'+name)
                if 'symlink' in record:assert item.issym() and item.linkname==record['symlink']
                else:
                    digest=hashlib.sha256()
                    with tar.extractfile(item) as f:
                        for block in iter(lambda:f.read(1<<20),b''):digest.update(block)
                    assert digest.hexdigest()==record['sha256'] and item.size==record['bytes']
        commit_record(dict(kind='lossless_directory_archive',source=str(source),archive=str(destination),archive_sha256=sha(destination),inventory=inventory,
            restore='tar -xzf '+str(destination)+' -C '+str(source.parent),verified=True))
        shutil.rmtree(source)
    # Only successful raw comparison workspaces, with a persisted full hash and
    # exact reference invocation, are released. Case/failure files stay intact.
    suites=[*list((out/'quality_final').glob('*')),out/'all161_v1',out/'all161_v2',out/'priority_v1']
    for suite in suites:
        summary=suite/'summary.json';rows=suite/'rows.jsonl'
        if not summary.exists() or not rows.exists() or not json.loads(summary.read_text()).get('PASS'):continue
        last=json.loads(rows.read_text().splitlines()[-1])
        for path in (suite/'working').glob('*'):
            if path.suffix not in ('.f32',):continue
            untracked(path)
            expected=(last.get('actual',{}) if path.name.startswith('actual') else last.get('reference',{})).get('pcm_sha256')
            if expected is None:continue
            digest=sha(path);assert digest==expected,(path,digest,expected)
            command=last.get('command') if path.name.startswith('actual') else last.get('reference_command')
            assert command and str(path) in command
            commit_record(dict(kind='successful_reusable_pcm_workspace',source=str(path),bytes=path.stat().st_size,sha256=digest,
                case_manifest=str(rows),reproduce_command=command,verified=True))
            path.unlink()
    # Detailed regression rows are complete success evidence; preserve every
    # byte in gzip and keep summaries/manifests directly readable.
    for source in sorted(out.glob('regression_*/**/rows.jsonl')):
        summary=source.parent/'summary.json'
        if not summary.exists() or not json.loads(summary.read_text()).get('PASS'):continue
        untracked(source);digest=sha(source);destination=source.with_suffix(source.suffix+'.gz')
        assert not destination.exists()
        with source.open('rb') as a,gzip.open(destination,'wb',compresslevel=5) as b:shutil.copyfileobj(a,b,1<<20)
        restored=hashlib.sha256()
        with gzip.open(destination,'rb') as f:
            for block in iter(lambda:f.read(1<<20),b''):restored.update(block)
        assert restored.hexdigest()==digest
        commit_record(dict(kind='lossless_regression_rows',source=str(source),bytes=source.stat().st_size,sha256=digest,
            archive=str(destination),archive_bytes=destination.stat().st_size,archive_sha256=sha(destination),verified=True))
        source.unlink()
    (out/'STORAGE_COMPACTION.json').write_text(json.dumps(dict(PASS=True,free_before=before,free_after=shutil.disk_usage(ROOT).free,records=records),indent=2,ensure_ascii=False)+'\n')
    print('Reclaimed bytes',shutil.disk_usage(ROOT).free-before,'free',shutil.disk_usage(ROOT).free,flush=True)
if __name__=='__main__':main()

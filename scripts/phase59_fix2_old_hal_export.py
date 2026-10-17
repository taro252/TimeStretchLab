"""旧トレースのAPFSコピーからHALサーバー情報を追加抽出する。新規記録なし。"""
import json
import shutil
import subprocess
from phase59_fix2_start_state import ROOT, OUT, sha
from phase58_fix_trace_analyze import table,number,complete_export


def main():
    source=ROOT/'build/phase59_fix_artifacts/final_long_trace/focused.trace'
    destination=ROOT/'build/phase59_fix2_artifacts/old_hal_readcopy';destination.mkdir()
    index=json.loads((ROOT/'results/phase59_fix/ARTIFACT_INDEX.json').read_text())
    expected={r['path']:r for r in index['files'] if r['path'].startswith(str(source)+'/')}
    originals=[]
    for path in sorted(source.rglob('*')):
        if not path.is_file():continue
        digest=sha(path);record=expected.get(str(path));assert record and record['bytes']==path.stat().st_size and record['sha256']==digest,str(path)
        originals.append(dict(path=str(path),bytes=path.stat().st_size,sha256=digest))
    assert shutil.disk_usage(ROOT).free>12*1024**3
    copied=destination/'focused.trace'
    subprocess.run(['/bin/cp','-cR',str(source),str(copied)],check=True)
    exports=[];findings=[]
    for schema in ('audio-hal-poi','audio-hal-zero-timestamp','audio-hal-zero-timestamp-jitter'):
        path=destination/(schema+'.xml');command=['xcrun','xctrace','export','--input',str(copied),'--xpath','/trace-toc/run[@number="1"]/data/table[@schema="'+schema+'"]']
        with path.open('x') as file,(destination/(schema+'.log')).open('x') as log:
            result=subprocess.run(command,cwd=ROOT,stdout=file,stderr=log,timeout=240)
        assert result.returncode==0 and complete_export(path),schema
        assert path.stat().st_size<1024**3
        rows=table(path);near=[]
        for row in rows:
            times=[number(row,k,-1) for k in ('timestamp','start','time') if k in row]
            if any(2.92e9<=t<=3.02e9 for t in times):near.append(row)
        exports.append(dict(schema=schema,command=command,path=str(path),bytes=path.stat().st_size,sha256=sha(path),rows=len(rows)))
        findings.append(dict(schema=schema,near_overload=near))
        print(schema,'rows',len(rows),'near',len(near),flush=True)
    assert all(sha(r['path'])==r['sha256'] for r in originals),'Original trace changed'
    (OUT/'OLD_HAL_SERVER_REVIEW.json').write_text(json.dumps(dict(original_sha_verified_against_previous_index=True,
        original_files=originals,readcopy=str(copied),exports=exports,findings=findings,
        scope='旧85.821秒事象のtrace 2.92〜3.02秒。元bundleは変更せずAPFSコピーをexport。データがない項目は正常な装置切替の証拠にしない。'),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()

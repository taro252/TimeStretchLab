"""Fix専用の保存先で既存の全PCM条件を実行する。実機試験とは同時実行しない。"""
import argparse
import concurrent.futures
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from phase57_study import ROOT, sha


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--tag', default='final')
    parser.add_argument('--frozen', type=Path, required=True)
    args = parser.parse_args()
    frozen = args.frozen.resolve()
    data = ROOT/'build/phase59_fix_artifacts'/('validation_'+args.tag)
    data.mkdir()
    out = ROOT/'results/phase59_fix'/('validation_'+args.tag)
    out.mkdir()
    binaries = {str(p.relative_to(ROOT)): sha(p) for p in frozen.iterdir() if p.is_file()}
    source_hashes = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT/'src').rglob('*') if p.is_file()}
    manifest = dict(artifact_directory=str(data), frozen_directory=str(frozen),
                    binaries=binaries, source_sha256=source_hashes,
                    driver_sha256=sha(Path(__file__)), parallel_performance_claim=False,
                    minimum_free_bytes=2*1024**3,
                    scope='全条件を維持。Phase57だけ入力形式で分割。性能と実時間判定は別の直列実機試験。')
    (out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    rows = []
    lock = threading.Lock()

    def run(name, command):
        if shutil.disk_usage(ROOT).free < manifest['minimum_free_bytes']:
            raise RuntimeError('Disk floor reached')
        command = list(map(str, command))
        start = time.time()
        with (data/(name+'.log')).open('x') as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        folder = data/name
        summary = folder/'summary.json'
        row = dict(name=name, command=command, exit=result.returncode, wall_s=time.time()-start,
                   log=str(data/(name+'.log')), result=json.loads(summary.read_text()) if summary.exists() else None)
        with lock:
            rows.append(row)
            (out/'driver.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n')
            print(name, 'exit', result.returncode, flush=True)
        if result.returncode:
            raise RuntimeError('Validation failed: '+name)
        return row

    def dynamic():
        for suite in ('priority', 'all161', 'materials', 'long'):
            name='dynamic_'+suite
            run(name, [sys.executable, '-B', 'scripts/phase59_study.py', '--suite', suite,
                       '--binary', frozen/'phase59_check', '--output', data/name])
        for suite in ('chunks', 'formats'):
            name='incremental_'+suite
            run(name, [sys.executable, '-B', 'scripts/phase59_incremental_study.py', '--suite', suite,
                       '--binary', frozen/'phase59_progressive_replay', '--output', data/name])

    def fixed():
        # この既存driverはbuild/phase58_checkを使用する。開始/終了のSHAで固定する。
        check=ROOT/'build/phase58_check'
        check_sha=sha(check)
        assert check_sha == sha(frozen/'phase58_check')
        original=ROOT/'scripts/phase58_fix_study.py'
        source=original.read_text()
        assert source.count('raw.unlink()')==1
        driver=data/'phase58_fix_retaining_driver.py'
        driver.write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT/'scripts'))+')\n'+
                          source.replace('raw.unlink()', "raw.unlink() if case['PASS'] else None"))
        for suite in ('short', 'all_speeds', 'long'):
            name='fixed58_'+suite
            run(name, [sys.executable, '-B', driver, '--suite', suite,
                       '--output', data/name])
        assert sha(check)==check_sha

    def phase57():
        original=ROOT/'scripts/phase57_study.py'
        source=original.read_text()
        marker="formats=[(48000,2,3)] if args.suite=='smoke' else [(r,c,e) for r in (44100,48000) for c in (1,2) for e in (1,3)]"
        assert source.count(marker)==1
        formats=[(r,c,e) for r in (44100,48000) for c in (1,2) for e in (1,3)]
        driver_folder=data/'partition_drivers';driver_folder.mkdir()
        for suite in ('stage1', 'stage2', 'long', 'natural', 'rejections'):
            selections=formats if suite in ('stage1','stage2') else ['all']
            def partition(selection):
                label='_'.join(map(str,selection)) if isinstance(selection,tuple) else selection
                text=source.replace(marker,'formats='+repr([selection])) if isinstance(selection,tuple) else source
                assert text.count('tempfile.TemporaryDirectory(')==1
                # PCM不一致時も参照原本を保持。条件・比較ループは変更しない。
                prelude=('import contextlib, tempfile, shutil\n'
                         '@contextlib.contextmanager\n'
                         'def retain_failure_directory(**kwargs):\n'
                         '    folder=tempfile.mkdtemp(**kwargs)\n'
                         '    try: yield folder\n'
                         '    except BaseException: raise\n'
                         '    else: shutil.rmtree(folder)\n')
                text=prelude+text.replace('tempfile.TemporaryDirectory(', 'retain_failure_directory(').replace("dir=ROOT/'build'",'dir=Path('+repr(str(data))+')')
                driver=driver_folder/(suite+'_'+label+'.py')
                driver.write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT/'scripts'))+')\n'+text)
                name='fixed57_'+suite+'_'+label
                command=[sys.executable,'-B',driver,'--suite',suite,'--binary',frozen/'phase57_check','--output',data/name]
                if suite=='stage2': command+=['--prerequisite',out/'fixed57_stage1.json']
                return run(name,command)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                parts=list(pool.map(partition,selections))
            result=dict(PASS=all(r['result']['PASS'] for r in parts),
                        pcm_sessions=sum(r['result']['pcm_sessions'] for r in parts),
                        matched_rejections=sum(r['result']['matched_rejections'] for r in parts),
                        cases=sum(r['result']['cases'] for r in parts), partitions=parts,
                        original_driver_sha256=sha(original))
            (out/('fixed57_'+suite+'.json')).write_text(json.dumps(result,indent=2)+'\n')
            assert result['PASS']

    # 互いに独立したPCM比較を並行する。途中失敗時も実行済み証拠を保存する。
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(work) for work in (dynamic,fixed,phase57)]
        failures=[]
        for future in futures:
            try: future.result()
            except Exception as error: failures.append(str(error))
    assert all(sha(ROOT/path)==digest for path,digest in source_hashes.items()), 'Source changed'
    assert all(sha(ROOT/path)==digest for path,digest in binaries.items()), 'Frozen binary changed'
    ledger=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in data.rglob('*') if p.is_file()]
    (out/'artifacts.json').write_text(json.dumps(ledger,indent=2)+'\n')
    result=dict(PASS=not failures, failures=failures, stages=len(rows),
                dynamic_pcm_sessions=sum(r['result']['pcm_sessions'] for r in rows if r['result'] and (r['name'].startswith('dynamic_') or r['name'].startswith('incremental_'))),
                fixed58_pcm_sessions=sum(r['result']['pcm_sessions'] for r in rows if r['result'] and r['name'].startswith('fixed58_')),
                fixed57_pcm_sessions=sum(r['result']['pcm_sessions'] for r in rows if r['result'] and r['name'].startswith('fixed57_')),
                artifact_manifest=str(out/'artifacts.json'))
    if not failures:
        assert result['dynamic_pcm_sessions']==1140
        assert result['fixed58_pcm_sessions']==6216
        assert result['fixed57_pcm_sessions']==51344
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return 0 if result['PASS'] else 2


if __name__=='__main__':raise SystemExit(main())

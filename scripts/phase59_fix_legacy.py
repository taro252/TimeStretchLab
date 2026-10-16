"""旧製品を同じ操作で比較し、診断実行体だけに公開履歴と時計の較正を加える。"""
import argparse
import csv
import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT, sha


def probe(data):
    # 共有ヘッダーの構造体サイズが変わった場合も全リンク対象を一致させる。
    with (data/'dependencies_build.log').open('x') as log:
        subprocess.run(['cmake','--build',str(ROOT/'build'),'--target','phase54_native','-j3'],
                       cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    original=ROOT/'src/playback/Phase54NativeStudy.cpp'
    text=original.read_text()
    changes={
        'cfg.verifyRawPcm=true;':'cfg.verifyRawPcm=true;cfg.detailedDiagnostics=true;',
        'bool silent=argc>7;WavStreamReader':
        'bool silent=argc>7&&std::string(argv[7])=="silent";const unsigned loadThreads=argc>7&&std::string(argv[7])=="--cpu=2"?2:0;LegacyLoad load(loadThreads);WavStreamReader',
        'std::string hash;};':'std::string hash;std::vector<prototype::Phase39BlockProfile> workers;};',
        'e.rawPcmSha()});':'e.rawPcmSha(),e.workerProfiles()});',
        'elapsed_s,operation,id,state\\n':'elapsed_s,operation,id,state,mach_before,mach_after,steady_after\\n',
        'requested,wanted,received,output,fifo\\n':'requested,wanted,received,output,fifo,last_publication_mach_ns\\n',
        "<<r.raw.fifoBefore<<'\\n';":"<<r.raw.fifoBefore<<','<<r.raw.lastPublicationNs<<'\\n';",
        'std::uint64_t id=0;bool ok=true;':'std::uint64_t id=0;bool ok=true;const auto actionMach=machNs();',
        "<<name(e.getPlaybackState())<<'\\n';":"<<name(e.getPlaybackState())<<','<<actionMach<<','<<machNs()<<','<<steadyNs()<<'\\n';",
        'std::size_t index=0;double currentInitial=speed;bool timedOut=false;':
        'struct Control {std::uint64_t mach,steady,session,published,consumed,fifo;};std::vector<Control> controls;controls.reserve(16384);std::size_t controlDropped=0;\n std::size_t index=0;double currentInitial=speed;bool timedOut=false;',
        'while(true){auto elapsed=':'while(true){if(controls.size()<16384){auto d=e.getPlaybackDiagnostics();controls.push_back({machNs(),steadyNs(),d.session,d.producedFrames,d.consumedFrames,d.fifoAvailable});}else ++controlDropped;auto elapsed=',
        'csv.commit();callbackRows+=':
        'csv.commit();std::ofstream workerCsv(out/("worker_"+std::to_string(i)+".csv"));workerCsv<<"output_start,start_mach_ns,published_mach_ns,wall_s,cpu_s,cycle_wall_s,cycle_cpu_s,fifo_wait_s,publication_frames,fifo_before,fifo_after,thread_id\\n";for(const auto& w:g.workers)workerCsv<<std::setprecision(17)<<w.outputStart<<\',\'<<w.startMachNs<<\',\'<<w.publishedMachNs<<\',\'<<w.chunkWallSeconds<<\',\'<<w.chunkCpuSeconds<<\',\'<<w.fullCycleWallSeconds<<\',\'<<w.fullCycleCpuSeconds<<\',\'<<w.fifoWaitSeconds<<\',\'<<w.publicationFrames<<\',\'<<w.fifoBeforeWrite<<\',\'<<w.fifoAfterWrite<<\',\'<<w.threadId<<\'\\n\';callbackRows+=',
        'auto seeks=e.seekHistory();':
        'std::ofstream controlFile(out/"control.csv");controlFile<<"mach_ns,steady_ns,session,published,consumed,fifo\\n";for(const auto& c:controls)controlFile<<c.mach<<\',\'<<c.steady<<\',\'<<c.session<<\',\'<<c.published<<\',\'<<c.consumed<<\',\'<<c.fifo<<\'\\n\';\n auto seeks=e.seekHistory();',
        '<<"\\nmode="<<mode':
        '<<"\\ncpu_load_threads="<<loadThreads<<"\\ncontrol_dropped="<<controlDropped<<"\\nbridge_steady_ns="<<nativeEnd.bridgeSteadyNs<<"\\nbridge_mach_ns="<<nativeEnd.bridgeMachNs<<"\\nbridge_uncertainty_ns="<<nativeEnd.bridgeUncertaintyNs<<"\\nmode="<<mode'
    }
    for old,new in changes.items():
        assert text.count(old)==1,(old,text.count(old))
        text=text.replace(old,new)
    text=('#include <mach/mach_time.h>\n'+text).replace('int main(int argc,char**argv)',
        'std::uint64_t machNs(){mach_timebase_info_data_t t{};mach_timebase_info(&t);return std::uint64_t(static_cast<long double>(mach_absolute_time())*t.numer/t.denom);}\n'
        'std::uint64_t steadyNs(){return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();}\n'
        'struct LegacyLoad {std::atomic<bool> stop{false};std::vector<std::thread> threads;explicit LegacyLoad(unsigned count){for(unsigned i=0;i<count;++i)threads.emplace_back([this]{volatile double v=.1;while(!stop.load()){for(unsigned i=0;i<10000;++i)v=std::sin(v+.001);}});}~LegacyLoad(){stop=true;for(auto& t:threads)t.join();}};\n'
        'int main(int argc,char**argv)')
    source=data/'legacy_probe.cpp';source.write_text(text)
    link=shlex.split((ROOT/'build/CMakeFiles/phase54_native.dir/link.txt').read_text())
    object_at=next(i for i,v in enumerate(link) if v.endswith('.o'))
    link[object_at:object_at+1]=['-std=c++20','-I'+str(ROOT/'src'),str(source)]
    binary=data/'legacy_probe';link[link.index('-o')+1]=str(binary)
    with (data/'build.log').open('x') as log:subprocess.run(link,cwd=ROOT/'build',stdout=log,stderr=subprocess.STDOUT,check=True)
    return binary,dict(original_sha256=sha(original),generated_source_sha256=sha(source),command=link,
                       link_input_sha256={str((ROOT/'build'/p).resolve()):sha(ROOT/'build'/p) for p in link if p.endswith(('.o','.a'))},
                       diagnostic_changes='通常側の時計較正・16384件上限の公開位置標本・停止後の既存worker profile書出し。音声コールバック、FIFO、DSP算術、操作列は不変。')


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--tag',required=True)
    parser.add_argument('--build-probe',action='store_true');parser.add_argument('--probe',type=Path)
    parser.add_argument('--repeats',type=int,default=1);parser.add_argument('--long',action='store_true');args=parser.parse_args()
    assert 1<=args.repeats<=20
    out=ROOT/'results/phase59_fix'/('legacy_'+args.tag);out.mkdir()
    data=ROOT/'build/phase59_fix_artifacts'/('legacy_'+args.tag);data.mkdir()
    binary,recipe=probe(data) if args.build_probe else (args.probe.resolve(),{})
    versions={'original':ROOT/'build/phase58_fix_frozen/phase54_native',
              'phase59_before':ROOT/'build/phase59_frozen/final/phase54_native','probe':binary}
    source=ROOT/'results/phase31/input/mix.wav'
    manifest=dict(input=str(source),input_sha256=sha(source),recipe=recipe,repeats=args.repeats,driver_sha256=sha(Path(__file__)),
                  binaries={k:dict(path=str(v),sha256=sha(v)) for k,v in versions.items()})
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    rows=[];plan=[]
    for repeat in range(args.repeats):
        for label,executable in versions.items():
            for mode in ('smoke','eos'):
                for preset in ('candidate','baseline'):
                    plan.append((repeat,label,executable,mode,preset,source,0))
    if args.long:
        long_source=ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav'
        long_plan=[]
        for cpu in (0,2):
            for preset in ('candidate','baseline'):long_plan.append((0,'probe_long_cpu'+str(cpu),binary,'eos',preset,long_source,cpu))
        plan=long_plan+plan
    for repeat,label,executable,mode,preset,selected,cpu in plan:
                    if shutil.disk_usage(ROOT).free<2*1024**3:raise RuntimeError('Disk floor reached')
                    folder=data/f'{repeat}_{label}_{mode}_{preset}'
                    command=[str(executable),str(selected),preset,'2.0',str(folder),mode,'64']
                    if cpu:command+=['--cpu=2']
                    started=time.time()
                    with (data/(folder.name+'.log')).open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=300)
                    values={}
                    if (folder/'summary.txt').exists():values=dict(x.split('=',1) for x in (folder/'summary.txt').read_text().splitlines() if '=' in x)
                    row=dict(label=label,repeat=repeat,mode=mode,preset=preset,input=str(selected),input_sha256=sha(selected),cpu=cpu,command=command,exit=p.returncode,wall_s=time.time()-started,summary=values,
                             PASS=p.returncode==0 and all(values.get(k)=='PASS' for k in ('AUDIO_QUALITY','MEASUREMENT_QUALITY','PCM_CORRECTNESS','VERDICT')))
                    row['artifacts']=[dict(path=str(f),bytes=f.stat().st_size,sha256=sha(f)) for f in folder.rglob('*') if f.is_file()]
                    rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
                    print(folder.name,p.returncode,'missing',values.get('missing_frames'),flush=True)
    summary=dict(PASS=all(r['PASS'] for r in rows),sessions=len(rows),passed=sum(r['PASS'] for r in rows),
                 missing_frames=sum(int(r['summary'].get('missing_frames',0)) for r in rows))
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return 0 if summary['PASS'] else 2


if __name__=='__main__':raise SystemExit(main())

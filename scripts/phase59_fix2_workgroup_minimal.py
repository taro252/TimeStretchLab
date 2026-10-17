"""同じFIFO固定PCMで、共有Workgroupの昇格だけを追加する対照実験。"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha
from phase59_fix2_minimal import analyze


def build():
    frozen=ROOT/'build/phase59_fix2_artifacts/final'
    original=frozen/'source/src/platform/macos/Phase59Fix2SourceNode.mm'
    text=original.read_text()
    def replace(old,new):
        nonlocal text
        assert text.count(old)==1,(old,text.count(old))
        text=text.replace(old,new)
    replace('#include "dsp/Phase14PlaybackPipeline.h"', '#include "dsp/Phase14PlaybackPipeline.h"\n#include "prototype/Phase58FixRealtimeWorker.h"')
    replace('thread_local bool inCallback=false;', 'thread_local bool inCallback=false,inGroupWorker=false;\nstd::atomic<std::uint64_t> workerNew{0};')
    replace('void noteNew(){if(inCallback)callbackNew.fetch_add(1,std::memory_order_relaxed);}',
            'void noteNew(){if(inCallback)callbackNew.fetch_add(1,std::memory_order_relaxed);if(inGroupWorker)workerNew.fetch_add(1,std::memory_order_relaxed);}')
    replace('std::unique_ptr<ts::Phase14AudioFifo> fifo;', 'std::unique_ptr<ts::Phase14AudioFifo> fifo;\nstd::unique_ptr<ts::prototype::phase58::RealtimeWorkerSupport> group;\nstd::atomic<bool> arm{false},armed{false},groupError{false};')
    replace('std::filesystem::create_directories(out);Context c;',
            'const bool groupMode=argc>5&&std::string(argv[5])=="workgroup";if(groupMode&&(mode!="fifo"||seconds<.5))throw std::invalid_argument("Group needs FIFO and prefill");\nstd::filesystem::create_directories(out);Context c;')
    replace('if(argc>5){c.notify.resize', 'if(argc>5&&std::string(argv[5])=="notify"){c.notify.resize')
    replace('if(c.fifo)worker=std::thread', 'c.group=std::make_unique<ts::prototype::phase58::RealtimeWorkerSupport>(true,48000);\nif(c.fifo)worker=std::thread')
    replace('while(!stop.load(std::memory_order_acquire)&&pos<c.total){const auto count=',
            'while(!stop.load(std::memory_order_acquire)&&pos<c.total){\nif(c.group&&c.arm.load()&&!c.armed.load()){if(!c.group->promote()){c.groupError=true;break;}inGroupWorker=true;c.armed=true;}\nconst auto count=')
    replace('ready=true;std::this_thread::sleep_for(std::chrono::microseconds(100));continue;',
            'ready=true;if(c.group)c.group->waitForSignal();else std::this_thread::sleep_for(std::chrono::microseconds(100));continue;')
    replace('WriteRow r;r.begin=mach_absolute_time();',
            'if(c.group&&c.group->active()&&!c.group->beginInterval()){c.groupError=true;break;}WriteRow r;r.begin=mach_absolute_time();')
    replace('if(writeCount<writes.size())writes[writeCount++]=r;',
            'if(writeCount<writes.size())writes[writeCount++]=r;if(c.group&&c.group->active()&&!c.group->finishInterval()){c.groupError=true;break;}')
    replace('if(c.fifo->available()>=lead||pos==c.total)ready=true;\n        }});',
            'if(c.fifo->available()>=lead||pos==c.total)ready=true;\n        }if(c.group){if(!c.group->demote())c.groupError=true;inGroupWorker=false;}});')
    replace('mark("worker_ready");',
            'mark("worker_ready");if(groupMode){c.arm=true;c.group->signal();const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);while(!c.armed&&!c.groupError&&std::chrono::steady_clock::now()<until)std::this_thread::sleep_for(std::chrono::microseconds(100));if(!c.armed||c.groupError)throw std::runtime_error("Group arm failed");mark("workgroup_armed");}')
    replace('const bool pass=!timeout',
            'const auto metrics=c.group?c.group->metrics():ts::prototype::phase58::RealtimeWorkerMetrics{};\nconst bool groupGood=!c.group||(!c.groupError&&!metrics.active&&metrics.joins==metrics.leaves&&metrics.leaves==metrics.restores&&!metrics.deadlineMisses&&!metrics.policyErrors&&!metrics.joinErrors&&!metrics.restoreErrors&&!metrics.intervalErrors&&!metrics.queryErrors&&!metrics.waitErrors&&!metrics.wakeErrors);\nconst bool pass=groupGood&&!workerNew&&!timeout')
    replace(r'\"workgroup_applicable\":false}',
            r'\"workgroup_adapter_available\":true,\"workgroup_enabled\":"<<groupMode<<",\"workgroup_joins\":"<<metrics.joins<<",\"workgroup_leaves\":"<<metrics.leaves<<",\"workgroup_restores\":"<<metrics.restores<<",\"workgroup_deadline_misses\":"<<metrics.deadlineMisses<<",\"workgroup_policy\":"<<metrics.observedPolicy<<",\"workgroup_priority\":"<<metrics.observedPriority<<",\"workgroup_worker_cpp_new\":"<<workerNew.load()<<"}')
    root=ROOT/'build/phase59_fix2_artifacts/workgroup_minimal';root.mkdir(exist_ok=True)
    attempt=1
    while (root/f'build_{attempt}').exists():attempt+=1
    data=root/f'build_{attempt}';data.mkdir();source=data/'sourcenode.mm';source.write_text(text)
    binary=data/'sourcenode';libraries=[frozen/'libphase58_realtime.a',frozen/'libtimestretch_core.a']
    command=['/usr/bin/c++','-arch','arm64','-std=c++20','-O3','-DNDEBUG','-fobjc-arc','-I'+str(frozen/'source/src'),str(source),*map(str,libraries),
             '-framework','AVFoundation','-framework','Foundation','-framework','CoreAudio','-framework','AudioToolbox','-framework','Accelerate','-o',str(binary)]
    with (data/'compile.log').open('x') as log:subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    manifest=dict(source_template=str(original),source_template_sha256=sha(original),generated_source=str(source),generated_source_sha256=sha(source),
                  command=command,binary=str(binary),binary_sha256=sha(binary),library_sha256={str(p):sha(p) for p in libraries},
                  hypothesis='元の初回異常窓では合成advanceなし。同じFIFO固定PCM・Workgroupアダプタ・2ms待機で、昇格/参加の有無だけを比較。DSP/解析/TimeMapは実行しない。',
                  period_seconds=2048/48000,computation_seconds=.9*2048/48000,
                  scope='研究用の独立対照。製品の昇格時期や品質ゲートを変更する修正ではない。')
    with (OUT/'WORKGROUP_MINIMAL_BUILD.json').open('x') as f:json.dump(manifest,f,ensure_ascii=False,indent=2);f.write('\n')
    return manifest


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--run',action='store_true');parser.add_argument('--rebuild',action='store_true');parser.add_argument('--repeats',type=int,default=10);args=parser.parse_args()
    manifest_path=OUT/'WORKGROUP_MINIMAL_BUILD.json'
    if args.rebuild and manifest_path.exists():
        revision=1
        while (OUT/f'WORKGROUP_MINIMAL_BUILD_prior_{revision}.json').exists():revision+=1
        manifest_path.rename(OUT/f'WORKGROUP_MINIMAL_BUILD_prior_{revision}.json')
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else build()
    binary=Path(manifest['binary']);assert sha(binary)==manifest['binary_sha256']
    if not args.run:return
    assert 1<=args.repeats<=30
    out=OUT/'workgroup_minimal';out.mkdir();data=ROOT/'build/phase59_fix2_artifacts/workgroup_minimal/trials';data.mkdir()
    rows=[]
    for repeat in range(args.repeats):
        for group in [False,True]:
            folder=data/f'{repeat}_{"group" if group else "normal"}'
            command=[str(binary),'fifo','candidate','2',str(folder)]+(['workgroup'] if group else [])
            with (data/(folder.name+'.log')).open('x') as log:result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=45)
            row=dict(repeat=repeat,workgroup=group,command=command,exit=result.returncode,**analyze(folder))
            row['PASS']=result.returncode==0 and row['summary']['PASS'];rows.append(row)
            (out/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            print(repeat,'workgroup',group,'pass',row['PASS'],'clock',len(row['clock_jumps']),flush=True)
    summary=dict(sessions=len(rows),passed=sum(r['PASS'] for r in rows),
                 by_workgroup={str(g):dict(sessions=sum(r['workgroup']==g for r in rows),passed=sum(r['workgroup']==g and r['PASS'] for r in rows),
                     clock_jumps=sum(len(r['clock_jumps']) for r in rows if r['workgroup']==g)) for g in [False,True]},
                 dsp_invoked=False,root_cause_identified=False,failures_preserved=True)
    with (out/'summary.json').open('x') as f:json.dump(summary,f,ensure_ascii=False,indent=2);f.write('\n')


if __name__=='__main__':main()

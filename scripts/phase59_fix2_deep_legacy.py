"""固定済み製品ソースの別ビルドで、生成後の確認・公開・待機を分離する。"""
import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


HELPER = r'''
#include <mach/mach.h>
#include <array>
#include <cstdio>
namespace {
constexpr std::size_t supplyCapacity=65536;
struct SupplyEvent {std::uint64_t before=0,after=0,tid=0,owner=0,kind=0,logical=0,frames=0,read=0,write=0,cpu=0;};
struct SupplySample {std::uint64_t before=0,after=0,tid=0,owner=0,user=0,system=0;int result=-1,state=-1,policy=-1,priority=-1,base=-1;};
struct SupplySlot {std::atomic<bool> live{false};std::atomic<std::uint64_t> tid{0},owner{0};std::atomic<mach_port_t> port{MACH_PORT_NULL};};
std::array<SupplyEvent,supplyCapacity> supplyEvents{};
std::array<SupplySample,supplyCapacity> supplySamples{};
std::array<SupplySlot,64> supplySlots{};
std::atomic<std::size_t> supplyCount{0},supplySampleCount{0},supplySlotCount{0},supplyDropped{0},supplySampleDropped{0};
std::atomic<bool> supplyEnabled{false};thread_local int supplySlot=-1;
std::uint64_t supplyCpu(){timespec t{};clock_gettime(CLOCK_THREAD_CPUTIME_ID,&t);return std::uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;}
void supplyRecord(const void* owner,ts::Phase14AudioFifo& fifo,unsigned kind,std::size_t logical,std::size_t frames){
    if(!supplyEnabled.load(std::memory_order_relaxed))return;
    const auto before=mach_absolute_time();const auto index=supplyCount.fetch_add(1);
    if(index>=supplyCapacity){++supplyDropped;return;}
    auto& e=supplyEvents[index];e.before=before;pthread_threadid_np(nullptr,&e.tid);e.owner=reinterpret_cast<std::uintptr_t>(owner);
    e.kind=kind;e.logical=logical;e.frames=frames;e.read=fifo.readPosition();e.write=fifo.writePosition();e.cpu=supplyCpu();e.after=mach_absolute_time();
}
struct SupplyScope {
    const void* owner;ts::Phase14AudioFifo& fifo;unsigned kind;std::size_t logical,frames;bool enabled;
    SupplyScope(const void* o,ts::Phase14AudioFifo& f,unsigned k,std::size_t l,std::size_t n,bool on=true):owner(o),fifo(f),kind(k),logical(l),frames(n),enabled(on){if(enabled)supplyRecord(owner,fifo,kind,logical,frames);}
    ~SupplyScope(){if(enabled)supplyRecord(owner,fifo,kind+1,logical,frames);}
};
struct SupplyWorker {
    const void* owner;ts::Phase14AudioFifo& fifo;
    SupplyWorker(const void* o,ts::Phase14AudioFifo& f):owner(o),fifo(f){
        if(!supplyEnabled)return;pthread_setname_np("TSL legacy PCM");const auto index=supplySlotCount.fetch_add(1);if(index>=supplySlots.size()){++supplyDropped;return;}
        supplySlot=index;auto& s=supplySlots[index];std::uint64_t tid=0;pthread_threadid_np(nullptr,&tid);s.tid=tid;s.owner=reinterpret_cast<std::uintptr_t>(owner);s.port=pthread_mach_thread_np(pthread_self());s.live=true;
        supplyRecord(owner,fifo,1,0,0);
    }
    ~SupplyWorker(){supplyRecord(owner,fifo,2,0,0);if(supplySlot>=0)supplySlots[supplySlot].live=false;supplySlot=-1;}
};
}
extern "C" void phase59Fix2PrepareSupply(){
    for(auto* p:{reinterpret_cast<volatile unsigned char*>(supplyEvents.data()),reinterpret_cast<volatile unsigned char*>(supplySamples.data())}){
        const auto bytes=p==reinterpret_cast<volatile unsigned char*>(supplyEvents.data())?sizeof(supplyEvents):sizeof(supplySamples);for(std::size_t i=0;i<bytes;++i)p[i]=0;
    }supplyEnabled=true;
}
extern "C" void phase59Fix2SampleSupply(){
    for(auto& slot:supplySlots){if(!slot.live.load())continue;const auto index=supplySampleCount.fetch_add(1);if(index>=supplyCapacity){++supplySampleDropped;return;}
        auto& r=supplySamples[index];r.before=mach_absolute_time();r.tid=slot.tid;r.owner=slot.owner;thread_extended_info_data_t info{};mach_msg_type_number_t count=THREAD_EXTENDED_INFO_COUNT;
        r.result=thread_info(slot.port,THREAD_EXTENDED_INFO,reinterpret_cast<thread_info_t>(&info),&count);
        if(r.result==KERN_SUCCESS){r.user=info.pth_user_time;r.system=info.pth_system_time;r.state=info.pth_run_state;r.policy=info.pth_policy;r.priority=info.pth_curpri;r.base=info.pth_priority;}
        r.after=mach_absolute_time();
    }
}
extern "C" void phase59Fix2ExportSupply(const char* folder){
    supplyEnabled=false;mach_timebase_info_data_t tb{};mach_timebase_info(&tb);
    std::ofstream events(std::string(folder)+"/supply_events.csv");events<<"before_ticks,after_ticks,thread,owner,kind,logical,frames,read,write,cpu_ns\n";
    for(std::size_t i=0;i<std::min(supplyCount.load(),supplyCapacity);++i){const auto& e=supplyEvents[i];events<<e.before<<','<<e.after<<','<<e.tid<<','<<e.owner<<','<<e.kind<<','<<e.logical<<','<<e.frames<<','<<e.read<<','<<e.write<<','<<e.cpu<<'\n';}
    std::ofstream samples(std::string(folder)+"/supply_samples.csv");samples<<"before_ticks,after_ticks,thread,owner,result,state,policy,priority,base,user_ns,system_ns\n";
    for(std::size_t i=0;i<std::min(supplySampleCount.load(),supplyCapacity);++i){const auto& r=supplySamples[i];samples<<r.before<<','<<r.after<<','<<r.tid<<','<<r.owner<<','<<r.result<<','<<r.state<<','<<r.policy<<','<<r.priority<<','<<r.base<<','<<r.user<<','<<r.system<<'\n';}
    events.flush();samples.flush();std::ofstream meta(std::string(folder)+"/supply_status.json");meta<<"{\"events\":"<<supplyCount<<",\"samples\":"<<supplySampleCount<<",\"event_dropped\":"<<supplyDropped<<",\"sample_dropped\":"<<supplySampleDropped<<",\"event_export_ok\":"<<events.good()<<",\"sample_export_ok\":"<<samples.good()<<",\"timebase_numer\":"<<tb.numer<<",\"timebase_denom\":"<<tb.denom<<"}\n";
}
'''


def build():
    frozen=ROOT/'build/phase59_fix2_artifacts/final';base=ROOT/'build/phase59_fix2_artifacts/deep_legacy'
    base.mkdir(exist_ok=True);attempt=1
    while (base/f'build_{attempt}').exists():attempt+=1
    data=base/f'build_{attempt}';data.mkdir();source=data/'source';source.mkdir();build_dir=data/'build'
    shutil.copytree(frozen/'source/src',source/'src');shutil.copytree(ROOT/'tests',source/'tests');shutil.copytree(ROOT/'examples',source/'examples');shutil.copy2(frozen/'source/CMakeLists.txt',source/'CMakeLists.txt')
    path=source/'src/prototype/Phase39PlaybackPipeline.cpp';text=path.read_text()
    def replace(old,new):
        nonlocal text
        assert text.count(old)==1,(old,text.count(old));text=text.replace(old,new)
    replace('namespace ts::prototype {',HELPER+'\nnamespace ts::prototype {')
    replace('worker_=std::thread([this] {','worker_=std::thread([this] {\nSupplyWorker supplyLifetime(this,fifo_);')
    replace('const auto pcmReady=enableProfile_?machNs():0;', 'SupplyScope supplyPublish(this,fifo_,30,produced_.load(),frames);\nconst auto pcmReady=enableProfile_?machNs():0;')
    # Exactly two validation sites exist in this file: publication and feed.
    needle='if(preparedInput_&&preparedInput_->validate)preparedInput_->validate();'
    assert text.count(needle)==2
    first=text.index(needle);text=text[:first]+text[first:].replace(needle,'{SupplyScope check(this,fifo_,32,produced_.load(),frames);'+needle+'}',1)
    last=text.rindex(needle);text=text[:last]+text[last:].replace(needle,'{SupplyScope check(this,fifo_,22,generatedPcmFrames_.load(),frames);'+needle+'}',1)
    replace('const auto feed=[&](const float*const* data,std::size_t frames,const std::function<void()>& poll){',
            'const auto feed=[&](const float*const* data,std::size_t frames,const std::function<void()>& poll){\nSupplyScope supplyFeed(this,fifo_,20,generatedPcmFrames_.load(),frames);')
    replace('while (!stop_.load(std::memory_order_acquire) &&\n                       (fifo_.free()<frames',
            '{SupplyScope supplyWait(this,fifo_,40,produced_.load(),frames);\nwhile (!stop_.load(std::memory_order_acquire) &&\n                       (fifo_.free()<frames')
    replace('if (stop_.load(std::memory_order_acquire)) throw Stopped{};\n                const auto waited=',
            '}\nif (stop_.load(std::memory_order_acquire)) throw Stopped{};\n                const auto waited=')
    replace('if (!fifo_.write(data,frames)) throw std::runtime_error("Phase 39 FIFO overflow");',
            '{SupplyScope supplyWrite(this,fifo_,50,produced_.load(),frames);if (!fifo_.write(data,frames)) throw std::runtime_error("Phase 39 FIFO overflow");}')
    path.write_text(text)
    commands=[['cmake','-S',str(source),'-B',str(build_dir),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64'],
              ['cmake','--build',str(build_dir),'--target','phase54_native','-j2']]
    for i,command in enumerate(commands):
        with (data/f'build_{i}.log').open('x') as log:subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    text=(ROOT/'build/phase59_fix2_artifacts/legacy_diagnostic_build/legacy_probe.cpp').read_text()
    text='extern "C" void phase59Fix2PrepareSupply();\nextern "C" void phase59Fix2SampleSupply();\nextern "C" void phase59Fix2ExportSupply(const char*);\n'+text
    needle=' MacPlaybackEngine e;';assert text.count(needle)==1
    text=text.replace(needle,' struct SupplyExport {std::string folder;explicit SupplyExport(std::string p):folder(std::move(p)){phase59Fix2PrepareSupply();}~SupplyExport(){phase59Fix2ExportSupply(folder.c_str());}} supplyExport(out.string());\n MacPlaybackEngine e;')
    needle='while(true){if(controls.size()';assert text.count(needle)==1
    text=text.replace(needle,'while(true){phase59Fix2SampleSupply();if(controls.size()')
    generated=data/'probe.cpp';generated.write_text(text)
    link=shlex.split((build_dir/'CMakeFiles/phase54_native.dir/link.txt').read_text());at=next(i for i,p in enumerate(link) if p.endswith('.o'))
    link[at:at+1]=['-std=c++20','-I'+str(source/'src'),str(generated)];binary=data/'legacy_deep_probe';link[link.index('-o')+1]=str(binary)
    with (data/'probe_compile.log').open('x') as log:subprocess.run(link,cwd=build_dir,stdout=log,stderr=subprocess.STDOUT,check=True)
    manifest=dict(binary=str(binary),binary_sha256=sha(binary),commands=commands+[link],source_directory=str(source),generated_probe_sha256=sha(generated),
                  modified_source_sha256=sha(path),original_source_sha256=sha(frozen/'source/src/prototype/Phase39PlaybackPipeline.cpp'),
                  event_capacity=65536,sample_capacity=65536,observer_brackets=True,
                  stages={'1':'worker begin','2':'worker end','20/21':'engine PCM sink entry / feed return','22/23':'feed input validation','30/31':'publication entry/return','32/33':'publication input validation','40/41':'FIFO wait','50/51':'FIFO write'},
                  scope='固定候補は変更せず別ソース・別リンクで構築。mainの既存制御ループから自分のworkerのMach状態を標本化。RUNNING標本は連続CPU実行の証明ではない。',
                  exports_after_engine_destructor=True,math_changes=False,
                  source_sha256={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()})
    with (OUT/'DEEP_LEGACY_BUILD.json').open('x') as f:json.dump(manifest,f,ensure_ascii=False,indent=2);f.write('\n')
    return manifest


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--run',action='store_true');parser.add_argument('--rebuild',action='store_true');parser.add_argument('--repeats',type=int,default=3);args=parser.parse_args()
    file=OUT/'DEEP_LEGACY_BUILD.json'
    if args.rebuild and file.exists():
        revision=1
        while (OUT/f'DEEP_LEGACY_BUILD_prior_{revision}.json').exists():revision+=1
        file.rename(OUT/f'DEEP_LEGACY_BUILD_prior_{revision}.json')
    manifest=json.loads(file.read_text()) if file.exists() else build()
    if not args.run:return
    assert 1<=args.repeats<=10
    out=OUT/'legacy_deep';out.mkdir();data=ROOT/'build/phase59_fix2_artifacts/deep_legacy/trials';data.mkdir()
    binary=Path(manifest['binary']);assert sha(binary)==manifest['binary_sha256'];rows=[]
    for repeat in range(args.repeats):
        for preset in ['candidate','baseline']:
            folder=data/f'{repeat}_{preset}';command=[str(binary),str(ROOT/'results/phase31/input/mix.wav'),preset,'2.0',str(folder),'smoke','64']
            with (data/(folder.name+'.log')).open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=300)
            values=dict(line.split('=',1) for line in (folder/'summary.txt').read_text().splitlines() if '=' in line)
            status=json.loads((folder/'supply_status.json').read_text())
            row=dict(repeat=repeat,preset=preset,label='deep_current',mode='smoke',command=command,exit=p.returncode,summary=values,supply_status=status,PASS=p.returncode==0,
                     measurement_complete=bool(status['event_export_ok'] and status['sample_export_ok'] and not status['event_dropped'] and not status['sample_dropped']))
            rows.append(row);(out/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            print(repeat,preset,p.returncode,'missing',values['missing_frames'],'events',status['events'],flush=True)
    summary=dict(sessions=len(rows),passed=sum(r['PASS'] for r in rows),measurement_complete=all(r['measurement_complete'] for r in rows),missing_frames=sum(int(r['summary']['missing_frames']) for r in rows),historical_failures_preserved=True)
    with (out/'summary.json').open('x') as f:json.dump(summary,f,ensure_ascii=False,indent=2);f.write('\n')


if __name__=='__main__':main()

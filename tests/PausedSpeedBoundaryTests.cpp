// Reuse the native recorder and assertions, with an explicit reciprocal sequence.
#define main pausedIncludedMain
#include "PausedSpeedNativeTests.cpp"
#undef main
static unsigned fileDescriptors(){std::vector<proc_fdinfo> entries(4096);const int bytes=proc_pidinfo(getpid(),PROC_PIDLISTFDS,0,entries.data(),int(entries.size()*sizeof(proc_fdinfo)));check(bytes>0,"FD query");return unsigned(bytes)/sizeof(proc_fdinfo);}
static unsigned threadCount(){thread_act_array_t threads=nullptr;mach_msg_type_number_t count=0;check(task_threads(mach_task_self(),&threads,&count)==KERN_SUCCESS,"thread query");for(unsigned i=0;i<count;++i)mach_port_deallocate(mach_task_self(),threads[i]);vm_deallocate(mach_task_self(),reinterpret_cast<vm_address_t>(threads),count*sizeof(thread_t));return count;}
static void preparationResources(const std::filesystem::path& input,Preset preset){
    WavStreamReader wav(input);Gate gate;ProgressiveMacPlaybackEngine e;ProgressiveOptions options;options.preset=preset;options.controlTestHooks={&gate,Gate::event};
    e.prepare(input,options);state(e,State::Ready);e.stop();const auto baselineFds=fileDescriptors();const auto baselineThreads=threadCount();
    e.prepare(input,options);state(e,State::Ready);seek(e,wav.frames()/2+17);
    wait([&]{return !e.getPlaybackDiagnostics().retiringPipeline;});const auto old=e.getPlaybackDiagnostics();const auto oldThreads=threadCount();const auto oldFds=fileDescriptors();
    gate.armed=true;const auto replaced=request(e,.75);wait([&]{return gate.entered.load();});
    const auto preparingThreads=threadCount(),preparingFds=fileDescriptors();const auto during=e.getPlaybackDiagnostics();
    check(preparingThreads<=oldThreads+2&&preparingFds==oldFds,"preparing epoch exceeded worker/FD bound");
    check(e.play()&&e.getStateSnapshot().resumePending&&e.pause(),"resource gate API/cancel responsiveness");
    const auto id=request(e,1.0);check(e.stoppedSpeedHistory()[e.stoppedSpeedHistory().size()-2].id==replaced,"replacement correlation");gate.release=true;ready(e,id,old.renderEpoch,old.consumedFrames);
    wait([&]{return !e.getPlaybackDiagnostics().retiringPipeline;});const auto settled=e.getPlaybackDiagnostics();
    std::this_thread::sleep_for(std::chrono::milliseconds(300));const auto idle=e.getPlaybackDiagnostics();
    check(idle.renderEpoch==settled.renderEpoch&&idle.archivedEpochCount==settled.archivedEpochCount&&idle.consumedFrames==settled.consumedFrames&&!e.getStateSnapshot().resumePending,"post-ready rebuild/output loop");
    const auto stopAt=std::chrono::steady_clock::now();e.stop();const auto stopMs=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-stopAt).count();
    check(fileDescriptors()==baselineFds,"preparation cancel lease leak");
    std::cout<<"{\"case\":\"preparation_resources\",\"old_threads\":"<<oldThreads<<",\"preparing_threads\":"<<preparingThreads<<",\"old_fds\":"<<oldFds<<",\"preparing_fds\":"<<preparingFds<<",\"preparing_rss\":"<<during.rssBytes<<",\"ready_rss\":"<<settled.rssBytes<<",\"prepare_cpu_s\":"<<settled.processCpuS-old.processCpuS<<",\"idle_cpu_300ms_s\":"<<idle.processCpuS-settled.processCpuS<<",\"stop_ms\":"<<stopMs<<",\"released_fds\":"<<fileDescriptors()<<",\"baseline_fds\":"<<baselineFds<<",\"released_threads\":"<<threadCount()<<",\"baseline_threads\":"<<baselineThreads<<",\"PASS\":true}"<<std::endl;
}
static void transitionStages(const std::filesystem::path& input,const std::filesystem::path& refs,Preset preset){
    WavStreamReader wav(input);using Stage=phase59::OperationState;
    for(auto wanted:{Stage::Pending,Stage::Submitted,Stage::Applied}){
        bool observed=false;
        for(unsigned attempt=0;attempt<5&&!observed;++attempt){
            Capture capture(wav.channels());ProgressiveOptions options;options.preset=preset;options.observerContext=&capture;options.observeEpochPcm=Capture::raw;options.observeOutputPcm=Capture::output;
            ProgressiveMacPlaybackEngine e;e.prepare(input,options);state(e,State::Ready);capture.epoch=e.getStateSnapshot().renderEpoch;check(e.play(),"stage initial play");wait([&]{return capture.count.load()>=2048;});
            const auto old=request(e,.65);Stage found=Stage::Pending;const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
            while(std::chrono::steady_clock::now()<deadline){
                const auto history=e.operationHistory();check(!history.empty()&&history.back().id==old,"live speed correlation");found=history.back().state;
                if(found==wanted){observed=true;break;}
                if(found==Stage::Applied||found==Stage::Completed||found==Stage::Rejected||found==Stage::Cancelled)break;
                std::this_thread::sleep_for(std::chrono::microseconds(100));
            }
            if(!observed){e.stop();continue;}
            check(e.pause(),"pause live transition");capture.reset();auto op=ready(e,request(e,1.25));capture.epoch=op.renderEpoch;check(e.resume(),"stage resume");wait([&]{return capture.count.load()>=2048;});check(e.pause(),"stage final pause");
            std::ifstream raw(refs/("1250000_"+std::string(preset==Preset::Candidate?"candidate":"baseline")+".f32"),std::ios::binary);raw.seekg(op.outputStartFrame*wav.channels()*4);
            std::vector<float> expected(capture.count*wav.channels());check(bool(raw.read(reinterpret_cast<char*>(expected.data()),expected.size()*4)),"stage reference");check(!std::memcmp(expected.data(),capture.pcm.data(),expected.size()*4)&&!capture.errors,"old operation revived/RAW mismatch");
            const auto historical=*e.getStateSnapshot().stoppedSpeed;
            check(e.resume(),"historical resume");request(e,1.5);check(e.pause(),"historical pause");
            seek(e,wav.frames()/2+17);
            const auto afterSeek=e.getStateSnapshot();check(afterSeek.stoppedSpeed&&afterSeek.stoppedSpeed->id==historical.id&&afterSeek.stoppedSpeed->readyNs==historical.readyNs&&afterSeek.stoppedSpeed->state==StoppedSpeedState::ReadyForResume,"played preparation resurrected by seek");
            capture.reset();capture.epoch=afterSeek.renderEpoch;check(e.resume(),"resume after live speed and seek");wait([&]{return capture.count.load()>=2048;});check(e.pause(),"historical final pause");
            std::ifstream newer(refs/("1500000_"+std::string(preset==Preset::Candidate?"candidate":"baseline")+".f32"),std::ios::binary);newer.seekg(capture.start*wav.channels()*4);expected.resize(capture.count*wav.channels());check(bool(newer.read(reinterpret_cast<char*>(expected.data()),expected.size()*4))&&!std::memcmp(expected.data(),capture.pcm.data(),expected.size()*4),"latest live speed lost after paused seek");
            e.stop();std::cout<<"{\"case\":\"pause_live_transition\",\"observed_at_pause_call\":\""<<phase59::name(found)<<"\",\"attempt\":"<<attempt<<",\"input\":"<<op.resumeInputFrame<<",\"PASS\":true}"<<std::endl;
        }
        check(observed,std::string("live stage not observed: ")+phase59::name(wanted));
    }
}
int main(int argc,char** argv){if(argc!=4&&argc!=5)return 1;int result=1;std::thread owner([&]{try{
    const std::filesystem::path input=argv[1],refs=argv[2];const auto preset=std::string(argv[3])=="candidate"?Preset::Candidate:Preset::Baseline;
    if(argc==5){if(std::string(argv[4])=="resources")preparationResources(input,preset);else transitionStages(input,refs,preset);result=0;return;}
    WavStreamReader wav(input);Capture capture(wav.channels());ProgressiveOptions options;options.preset=preset;options.observerContext=&capture;options.observeEpochPcm=Capture::raw;options.observeOutputPcm=Capture::output;
    ProgressiveMacPlaybackEngine e;e.prepare(input,options);state(e,State::Ready);
    capture.epoch=e.getStateSnapshot().renderEpoch;check(e.play(),"resource warm play");wait([&]{return capture.count.load()>=2048;});check(e.pause(),"resource warm pause");e.stop();
    const auto baselineFds=fileDescriptors();const auto baselineThreads=threadCount();
    e.prepare(input,options);state(e,State::Ready);
    for(unsigned repeat=0;repeat<3;++repeat)for(unsigned speed:{400000,2000000,400000,2000000,490000,500000,490000,500000,990000,1000000,1010000,1000000,990000}){
        seek(e,wav.frames()/2+17);const auto frozen=e.getCurrentPlaybackPosition();check(frozen.inputFrame.has_value(),"boundary target");
        capture.reset();const auto before=e.getPlaybackDiagnostics();auto op=ready(e,request(e,speed/1e6),before.renderEpoch,before.consumedFrames);
        check(op.resumeInputFrame==*frozen.inputFrame,"boundary input drift");capture.epoch=op.renderEpoch;
        const auto called=std::chrono::steady_clock::now();check(e.getPlaybackState()==State::Paused?e.resume():e.play(),"boundary resume");wait([&]{return capture.count.load()>=2048;});check(e.pause(),"boundary pause");
        check(!capture.errors&&capture.start==op.outputStartFrame&&capture.session==op.session&&capture.generation==op.inputGeneration,"boundary PCM span");
        const auto path=refs/(std::to_string(speed)+"_"+(preset==Preset::Candidate?"candidate":"baseline")+".f32");std::ifstream raw(path,std::ios::binary);raw.seekg(capture.start*wav.channels()*4);
        std::vector<float> expected(capture.count*wav.channels());check(bool(raw.read(reinterpret_cast<char*>(expected.data()),expected.size()*4)),"boundary reference");check(!std::memcmp(expected.data(),capture.pcm.data(),expected.size()*4),"boundary RAW mismatch");
        const auto d=e.getPlaybackDiagnostics();check(!d.missingFrames&&!d.rejectedWrites,"boundary supply");
        std::cout<<"{\"repeat\":"<<repeat<<",\"speed\":"<<speed<<",\"frames\":"<<capture.count<<",\"input\":"<<op.resumeInputFrame<<",\"output\":"<<capture.start<<",\"ready_ms\":"<<double(op.readyNs-op.acceptedNs)/1e6<<",\"resume_first_pcm_ms\":"<<double(capture.firstNs.load()-std::chrono::duration_cast<std::chrono::nanoseconds>(called.time_since_epoch()).count())/1e6<<",\"fd_count\":"<<fileDescriptors()<<",\"threads\":"<<threadCount()<<",\"rss\":"<<d.rssBytes<<",\"cpu_s\":"<<d.processCpuS<<",\"PASS\":true}"<<std::endl;
    }e.stop();check(fileDescriptors()==baselineFds,"source lease/FD leak after stop");
    std::cout<<"{\"case\":\"released_resources\",\"fd_count\":"<<fileDescriptors()<<",\"baseline_fd_count\":"<<baselineFds<<",\"threads\":"<<threadCount()<<",\"baseline_threads\":"<<baselineThreads<<",\"PASS\":true}"<<std::endl;result=0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';}});owner.join();return result;}

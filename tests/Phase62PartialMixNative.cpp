// D04: 実音声callbackの部分混合中に、公開APIで置換/Clear/Stopする。
// callbackでは値の観測だけを行い、待機は一切行わない。
#define PHASE62_PLAYING_LEDGER_NO_MAIN 1
#include "Phase62PlayingLedgerNative.cpp"
#include <CoreAudio/CoreAudio.h>

namespace {
struct BufferUnavailable:std::runtime_error {using std::runtime_error::runtime_error;};
struct DeviceBufferScope {
    AudioDeviceID device=0;UInt32 original=0,selected=0;bool changed=false,restored=false;
    static AudioObjectPropertyAddress address(){return {kAudioDevicePropertyBufferFrameSize,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};}
    UInt32 read()const{
        UInt32 value=0,bytes=sizeof(value);auto property=address();
        const auto status=AudioObjectGetPropertyData(device,&property,0,nullptr,&bytes,&value);
        if(status!=noErr)throw BufferUnavailable("装置buffer読取り失敗 OSStatus="+std::to_string(status));
        return value;
    }
    DeviceBufferScope(){
        UInt32 bytes=sizeof(device);AudioObjectPropertyAddress property{kAudioHardwarePropertyDefaultOutputDevice,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
        const auto status=AudioObjectGetPropertyData(kAudioObjectSystemObject,&property,0,nullptr,&bytes,&device);
        if(status!=noErr||!device)throw BufferUnavailable("既定出力装置の取得失敗 OSStatus="+std::to_string(status));
        original=read();
    }
    void configure(){
        auto property=address();Boolean settable=false;const auto query=AudioObjectIsPropertySettable(device,&property,&settable);
        if(query!=noErr||!settable)throw BufferUnavailable("装置bufferを変更できない OSStatus="+std::to_string(query));
        std::string failures;
        for(const UInt32 target:{64u,128u}){
            changed=true;const auto status=AudioObjectSetPropertyData(device,&property,0,nullptr,sizeof(target),&target);
            auto actual=read();const auto deadline=Tick::now()+std::chrono::seconds(1);
            while(status==noErr&&actual!=target&&Tick::now()<deadline){std::this_thread::sleep_for(std::chrono::milliseconds(10));actual=read();}
            if(status==noErr&&actual==target){selected=actual;return;}
            failures+=" requested="+std::to_string(target)+" actual="+std::to_string(actual)+" OSStatus="+std::to_string(status);
        }
        throw BufferUnavailable("64/128frameの実装置bufferを確保できない:"+failures);
    }
    bool restore()noexcept{
        if(restored||!changed){restored=true;return true;}
        auto property=address();const auto status=AudioObjectSetPropertyData(device,&property,0,nullptr,sizeof(original),&original);
        UInt32 actual=0;OSStatus query=noErr;const auto deadline=Tick::now()+std::chrono::seconds(1);
        do{UInt32 bytes=sizeof(actual);query=AudioObjectGetPropertyData(device,&property,0,nullptr,&bytes,&actual);if(status!=noErr||query!=noErr||actual==original)break;std::this_thread::sleep_for(std::chrono::milliseconds(10));}while(Tick::now()<deadline);
        restored=status==noErr&&query==noErr&&actual==original;return restored;
    }
    ~DeviceBufferScope(){restore();}
};
struct LiveMix {
    std::uint64_t newEpoch=0,oldEpoch=0,callbackFrame=0;
    std::size_t frames=0,offset=0,mixed=0,length=0,newReceived=0,oldReceived=0;
    bool partial()const noexcept{return mixed&&offset+mixed>0&&offset+mixed<length;}
};
struct FirstMixEvidence {
    LiveMix span;std::size_t channels=0,stored=0;
    std::array<std::array<std::uint32_t,128>,2> bits{};
};
struct PartialCapture {
    NativeCapture native;
    ts::prototype::phase59::ValueMailbox<LiveMix> latest;
    ts::prototype::phase59::ValueMailbox<FirstMixEvidence> first;
    bool firstWritten=false; // 音声callbackだけが書く。
    explicit PartialCapture(std::size_t channels):native(channels){}
    static void raw(void* context,const float*const* pcm,std::size_t frames,std::size_t at,std::uint64_t generation,std::uint64_t epoch,std::uint64_t session)noexcept{
        NativeCapture::raw(&static_cast<PartialCapture*>(context)->native,pcm,frames,at,generation,epoch,session);
    }
    static void output(void* context,const float*const* pcm,const ProgressiveOutputSpan& span)noexcept{
        auto& capture=*static_cast<PartialCapture*>(context);NativeCapture::output(&capture.native,pcm,span);
        if(!span.mixedFrames)return;
        const LiveMix value{span.newEpoch,span.oldEpoch,span.callbackFrame,span.frames,span.transitionOffset,span.mixedFrames,span.transitionLength,span.newReceivedFrames,span.oldReceivedFrames};
        if(value.partial()&&!capture.firstWritten){
            FirstMixEvidence evidence;evidence.span=value;evidence.channels=capture.native.audit.channels;evidence.stored=std::min<std::size_t>(span.frames,128);
            for(std::size_t channel=0;channel<evidence.channels;++channel)for(std::size_t frame=0;frame<evidence.stored;++frame)evidence.bits[channel][frame]=std::bit_cast<std::uint32_t>(pcm[channel][frame]);
            capture.first.publish(evidence);capture.firstWritten=true;
        }
        capture.latest.publish(value);
    }
};
struct PartialHooks {
    WorkerGate preparation;
    PartialCapture* capture=nullptr;
    ProgressiveControlTestPoint expected=ProgressiveControlTestPoint::PartialMixStopDecision;
    bool decision=false;LiveMix atDecision;
    static void event(void* context,ProgressiveControlTestPoint point)noexcept{
        auto& hooks=*static_cast<PartialHooks*>(context);
        if(point==hooks.expected){
            // Engineが実Startedかつatomic cursor部分混合を確認した通常側接続点。
            // mutex内なので記録のみ。EngineのAPI、待機、I/Oを呼ばない。
            if(!hooks.decision){hooks.atDecision=hooks.capture->latest.read().value_or(LiveMix{});hooks.decision=true;}
            return;
        }
        WorkerGate::event(&hooks.preparation,point);
    }
};
const char* decisionName(const std::string& mode){return mode=="replace"?"PartialMixReplaceDecision":mode=="clear"?"PartialMixClearDecision":"PartialMixStopDecision";}
ProgressiveControlTestPoint decisionPoint(const std::string& mode){return mode=="replace"?ProgressiveControlTestPoint::PartialMixReplaceDecision:mode=="clear"?ProgressiveControlTestPoint::PartialMixClearDecision:ProgressiveControlTestPoint::PartialMixStopDecision;}
void saveMix(std::ostream& file,const LiveMix& sample){
    file<<"{\"new_epoch\":"<<sample.newEpoch<<",\"old_epoch\":"<<sample.oldEpoch<<",\"callback_frame\":"<<sample.callbackFrame<<",\"frames\":"<<sample.frames<<",\"transition_offset\":"<<sample.offset
        <<",\"mixed_frames\":"<<sample.mixed<<",\"transition_length\":"<<sample.length<<",\"cursor_after\":"<<sample.offset+sample.mixed<<",\"new_received\":"<<sample.newReceived<<",\"old_received\":"<<sample.oldReceived<<'}';
}
struct PartialAttempt {
    PartialCapture capture;PartialHooks hooks;FinalLedgerSink finalAudit;
    std::unique_ptr<ProgressiveMacPlaybackEngine> engine=std::make_unique<ProgressiveMacPlaybackEngine>();
    std::filesystem::path folder;std::vector<std::uint64_t> ids;
    std::string missedReason;
    std::uint64_t loopID=0;unsigned rate=0,deviceBuffer=0;
    PartialAttempt(const std::filesystem::path& input,Preset preset,const std::filesystem::path& out,const std::string& mode,unsigned selected):capture(ts::WavStreamReader(input).channels()),folder(out),deviceBuffer(selected){
        require(std::filesystem::create_directory(folder),"fresh partial attempt directory required");
        ts::WavStreamReader reader(input);rate=reader.sampleRate();require(reader.frames()>=std::size_t(rate)*9,"partial mix fixture needs >=9s");
        hooks.capture=&capture;hooks.expected=decisionPoint(mode);
        ProgressiveOptions options;options.preset=preset;options.initialSpeed=1;options.allowExperimentalLoops=true;options.callbackRecordLimit=8192;
        options.observerContext=&capture;options.observeEpochPcm=PartialCapture::raw;options.observeOutputPcm=PartialCapture::output;
        options.controlTestHooks={&hooks,PartialHooks::event};options.finalLoopSpeedAuditContext=&finalAudit;options.receiveFinalLoopSpeedAudit=FinalLedgerSink::receive;
        options.allocationHooks={[]()noexcept{callbackNew=0;callbackCounting=true;phase61_heap_begin();},[]()noexcept{phase61_heap_end();hostCallbackCppNew.fetch_add(callbackNew,std::memory_order_relaxed);callbackCounting=false;},[]()noexcept{return callbackNew;}};
        require(engine->prepare(input,options),"partial prepare rejected");until([&]{return engine->getPlaybackState()==State::Ready&&engine->getPlaybackDiagnostics().pipeline.analysisDone;},"partial normal final Ready");
        require(engine->getNativeDiagnostics().deviceBufferFrames==selected,"実engineが選択した装置bufferと不一致");
        require(engine->play(),"partial initial play");until([&]{return capture.native.frames.load()>=rate/5;},"partial initial PCM");
    }
    ~PartialAttempt(){hooks.preparation.released=true;if(engine)engine->stop();}
    void healthy(){require(!hooks.preparation.expired,"partial normal-worker gate expired");require(ph58::RealtimePipeline::executionOwnerCounts().peak<=2,"partial third execution owner");if(engine&&engine->getPlaybackState()==State::Failed)throw std::runtime_error(engine->getPlaybackDiagnostics().error);}
    template<class P> void until(P predicate,const char* reason){const auto end=Tick::now()+std::chrono::seconds(90);while(!predicate()){healthy();require(Tick::now()<end,reason);std::this_thread::sleep_for(std::chrono::milliseconds(1));}healthy();}
    progressive::LoopContext context(){const auto state=engine->getStateSnapshot();return {state.inputGeneration,state.session,state.renderEpoch};}
    progressive::LoopSpeedOperation row(std::uint64_t id){const auto result=engine->loopSpeedOperation(id);require(result.has_value(),"partial external ID missing");return *result;}
    void accepted(const progressive::LoopSpeedReceipt& receipt){require(receipt.accepted&&!receipt.duplicate&&receipt.id&&receipt.code==Code::Accepted,"partial expected fresh Accepted ID");require(std::find(ids.begin(),ids.end(),receipt.id)==ids.end(),"partial duplicate receipt ID");ids.push_back(receipt.id);}
    void exactIds(const std::vector<progressive::LoopSpeedOperation>& operations,bool terminal){
        std::set<std::uint64_t> expected(ids.begin(),ids.end()),actual;require(expected.size()==ids.size(),"partial duplicate Accepted set");
        for(const auto& op:operations){require(actual.insert(op.id).second,"partial duplicate ledger ID");if(terminal)require(progressive::terminal(op.state),"partial nonterminal Accepted ID");}
        require(actual==expected,"partial Accepted/ledger ID set mismatch");
    }
    void stopAndSave(bool qualified,const std::string& mode,std::uint64_t oldID,std::uint64_t latestID,const LiveMix& observed,const FirstMixEvidence& first){
        // StopでFailedをStoppedへ上書きする前に、一般の製品故障を検査する。
        // 故障や品質違反を競合窓の取り逃しとして再試行しない。
        healthy();
        if(engine->getPlaybackState()!=State::Stopped)engine->stop();healthy();
        const auto final=engine->loopSpeedHistory();exactIds(final,true);
        const auto diagnostics=engine->getPlaybackDiagnostics();const auto loop=engine->getLoopSnapshot();
        require(!diagnostics.missingFrames&&!diagnostics.underrunCalls&&!diagnostics.rejectedWrites&&!loop.failurePaddingFrames&&!loop.outputAffectedFrames,"partial operation corrupted PCM supply");
        require(!capture.native.audit.errors&&!capture.native.audit.nonfinite,"partial RAW/mix arithmetic or NaN/Inf");
        require(diagnostics.callbackCppNew&&!*diagnostics.callbackCppNew&&!hostCallbackCppNew.load()&&!phase61_heap_allocations()&&!phase61_heap_frees(),"partial callback allocation/free");
        const auto owners=ph58::RealtimePipeline::executionOwnerCounts();require(owners.peak<=2&&!owners.alive,"partial owner leak/peak");
        for(const auto& epoch:engine->closedEpochs())require(epoch.pipeline.finalDataAvailable,"partial retired epoch not joined");
        if(qualified){
            const auto previous=row(oldID);
            require(previous.state==(mode=="stop"?LS::Cancelled:LS::Completed)&&previous.outputStarted&&previous.firstPcmObservedNs&&previous.session&&previous.renderEpoch==first.span.newEpoch,
                    "partial old ID lost correct terminal kind or prior PCM/start identity");
            require(previous.state!=LS::Replaced&&!previous.noChange,"partial adopted old ID rewritten as Replaced/NoOp");
            if(mode=="stop")require(!previous.reason.empty()&&!previous.completedNs,"partial Stop lacks cancellation reason or falsely completed");
            else require(previous.completedNs&&previous.fixedBoundary,"partial fixed entry did not complete after actual PCM");
            if(mode=="replace"){const auto newest=row(latestID);require(newest.state==LS::Completed&&newest.outputStarted&&newest.firstPcmObservedNs&&newest.speedMicros==1250000,"partial replacement latest ID lost actual Completed PCM");}
            require(first.span.partial()&&observed.partial()&&hooks.atDecision.partial()&&hooks.atDecision.newEpoch==first.span.newEpoch&&first.stored&&first.span.newReceived&&first.span.oldReceived,"partial cursor or preceding real PCM evidence missing");
        }
        writePhase62Trace(folder/"callbacks.jsonl",engine->loopCallbackRecords());
        {std::ofstream file(folder/"terminal_ledger.jsonl");for(const auto& op:final)file<<operationJson(op)<<'\n';require(bool(file),"partial terminal ledger write");}
        {std::ofstream file(folder/"partial_pcm.json");file<<"{\"observed\":";saveMix(file,observed);file<<",\"first\":";saveMix(file,first.span);file<<",\"decision\":";saveMix(file,hooks.atDecision);file<<",\"decision_hook\":"<<ph58::jsonString(decisionName(mode))<<",\"actual_Started_partial_decision\":"<<(hooks.decision?"true":"false")<<",\"channels\":"<<first.channels<<",\"stored_frames\":"<<first.stored<<",\"prior_output_float_bits\":[";
            for(std::size_t channel=0;channel<first.channels;++channel){file<<(channel?",[":"[");for(std::size_t frame=0;frame<first.stored;++frame)file<<(frame?",":"")<<first.bits[channel][frame];file<<']';}file<<"]}\n";require(bool(file),"partial PCM evidence write");}
        engine.reset();require(finalAudit.complete(),"partial final audit not delivered");exactIds(finalAudit.operations,true);
        require(finalAudit.operations.size()==final.size(),"partial final sink count mismatch");for(std::size_t i=0;i<final.size();++i)require(operationJson(final[i])==operationJson(finalAudit.operations[i]),"partial destructor changed final history");finalAudit.save(folder/"sink.jsonl");
        const auto frames=capture.native.frames.load();std::this_thread::sleep_for(std::chrono::milliseconds(50));require(capture.native.frames.load()==frames&&!ph58::RealtimePipeline::executionOwnerCounts().alive,"partial stopped PCM revival");
        std::ofstream summary(folder/"SUMMARY.json");summary<<"{\"run_complete\":true,\"status\":"<<ph58::jsonString(qualified?"PASS":"MISSED_WINDOW")<<",\"missed_reason\":"<<ph58::jsonString(missedReason)<<",\"partial_decision\":"<<(qualified?"true":"false")<<",\"Accepted_IDs\":[";for(std::size_t i=0;i<ids.size();++i)summary<<(i?",":"")<<ids[i];summary<<"],\"owner_peak\":"<<owners.peak<<",\"owners_alive\":0,\"device_buffer\":"<<deviceBuffer<<",\"callback_gate\":false,\"fault_ordering_test\":true,\"RT_deadline_approval\":\"NOT_ASSESSED\"}\n";require(bool(summary),"partial summary write");
    }
    bool run(const std::string& mode){
        // workerのjob選択前に外部IDを束縛する。音声callbackはそのまま進む。
        hooks.preparation.arm(ProgressiveControlTestPoint::LoopJobDispatch);
        const auto range=engine->requestLoopRange(0,std::uint64_t(rate)*8,context());require(range.accepted,"partial ReturnToA rejected");loopID=range.id;
        until([&]{return hooks.preparation.entered.load();},"partial pre-dispatch gate missing");
        const auto old=engine->requestLoopSpeed(.75,context());accepted(old);
        hooks.preparation.released=true;
        // leftを1ms間隔で待つと、通常threadの再スケジュールだけで約5msの
        // 一度限りの窓を逃す。callbackは止めず、解放直後から値を観測する。
        // この短い窓ではEngine mutexを照会せず、実observerの固定値だけ読む。
        LiveMix observed;const auto end=Tick::now()+std::chrono::seconds(20);
        do{
            if(auto sample=capture.latest.read()){
                observed=*sample;
                if(sample->partial())break;
                // 最終mixed spanまで進んだ場合、このentryの部分窓は再来しない。
                if(sample->mixed&&sample->offset+sample->mixed>=sample->length){missedReason="final_mix_completed_before_observation";break;}
            }
            if(Tick::now()>=end){missedReason="observation_timeout";break;}
            std::this_thread::yield();
        }while(true);
        if(!observed.partial()){
            // 取り逃しは合格に数えない。正常な停止・退役と全IDを監査して保存し、
            // mainの有限8回の再試行へ戻す。全試行失敗は従来通りFAIL。
            const auto first=capture.first.read().value_or(FirstMixEvidence{});
            stopAndSave(false,mode,old.id,0,observed,first);return false;
        }
        require(observed.frames<=128&&observed.frames<observed.length&&observed.length==rate/200,"device callback did not preserve a strict partial mix");
        const auto evidence=capture.first.read();require(evidence.has_value()&&evidence->span.partial(),"first partial PCM sample absent");
        const auto stamp=capture.native.observed[observed.newEpoch%64].read();require(stamp&&stamp->epoch==observed.newEpoch&&stamp->session&&stamp->generation,"partial new PCM identity absent");
        const progressive::LoopContext actual{stamp->generation,stamp->session,observed.newEpoch};std::uint64_t latestID=0;
        if(mode=="replace"){const auto latest=engine->requestLoopSpeed(1.25,actual);if(latest.accepted&&!latest.duplicate){accepted(latest);latestID=latest.id;}else require(!hooks.decision,"actual partial replacement was rejected");}
        else if(mode=="clear"){const auto receipt=engine->requestClearLoop(loopID,actual);require(receipt.accepted||!hooks.decision,"actual partial Clear rejected");}
        else engine->stop();
        const bool qualified=hooks.decision&&hooks.atDecision.partial()&&hooks.atDecision.newEpoch==observed.newEpoch;
        if(qualified&&mode!="stop"){
            until([&]{return progressive::terminal(row(old.id).state);},"partial adopted old ID terminal deadline");require(row(old.id).state==LS::Completed,"partial adopted ID did not Complete");
            if(mode=="replace"){
                require(latestID,"partial replacement receipt missing");until([&]{return progressive::terminal(row(latestID).state);},"partial latest replacement deadline");require(row(latestID).state==LS::Completed,"partial latest replacement failed");
            }else until([&]{return !engine->getLoopSnapshot().clearPending&&!engine->getLoopSnapshot().enabled&&!engine->getPlaybackDiagnostics().pipeline.loopReuse.enabled;},"partial Clear continuation not completed");
        }
        stopAndSave(qualified,mode,old.id,latestID,observed,*evidence);return qualified;
    }
};
}

int main(int argc,char** argv){
    if(argc!=5){std::cerr<<"replace|clear|stop INPUT candidate|baseline NEW_OUTPUT_DIR\n";return 2;}
    int result=1;std::thread owner([&]{std::filesystem::path out;std::unique_ptr<DeviceBufferScope> buffer;bool owned=false;std::string error,status="FAIL";unsigned attempts=0;bool complete=false;
        try{
            const std::string mode=argv[1],presetName=argv[3];require(mode=="replace"||mode=="clear"||mode=="stop","partial mode");require(presetName=="candidate"||presetName=="baseline","partial preset");
            const auto input=std::filesystem::absolute(argv[2]);out=std::filesystem::absolute(argv[4]);require(std::filesystem::create_directories(out),"fresh partial output required");owned=true;
            {std::ofstream expected(out/"EXPECTED.json");expected<<"{\"schema\":1,\"suite\":\"phase62_partial_mix_native\",\"mode\":"<<ph58::jsonString(mode)<<",\"preset\":"<<ph58::jsonString(presetName)<<",\"expected\":1,\"expected_IDs\":[\"D04_"<<presetName<<'_'<<mode<<"\"],\"expected_Accepted_receipts_per_qualified_attempt\":"<<(mode=="replace"?2:1)<<",\"max_attempts\":8,\"input_sha256\":"<<ph58::jsonString(fileHash(input))<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::absolute(argv[0])))<<",\"real_CoreAudio\":true,\"callback_gate\":false,\"independent_DSP\":false}\n";require(bool(expected),"partial expected write");}
            buffer=std::make_unique<DeviceBufferScope>();buffer->configure();
            phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* memory=allocate(37);release(memory);phase61_heap_end();require(phase61_heap_allocations()&&phase61_heap_frees(),"partial heap detector self-test");phase61_heap_reset();hostCallbackCppNew=0;
            for(unsigned attempt=1;attempt<=8&&!complete;++attempt){attempts=attempt;PartialAttempt fixture(input,presetName=="candidate"?Preset::Candidate:Preset::Baseline,out/("attempt_"+std::to_string(attempt)),mode,buffer->selected);complete=fixture.run(mode);}
            require(complete,"有限8回の試行で部分混合中の実操作を確定できない");require(buffer->restore(),"装置bufferを元のframe数へ復元できない");status="PASS";result=0;
        }catch(const BufferUnavailable& e){error=e.what();status="BLOCKED";result=4;}
        catch(const std::exception& e){error=e.what();result=1;}
        const bool restored=!buffer||buffer->restore();if(!restored){status="FAIL";result=1;error+=" 装置buffer復元失敗";}
        if(owned){std::ofstream summary(out/"SUMMARY.json");summary<<"{\"schema\":1,\"suite\":\"phase62_partial_mix_native\",\"run_complete\":"<<(complete&&result==0?"true":"false")<<",\"status\":"<<ph58::jsonString(status)<<",\"expected\":1,\"executed\":"<<(complete?1:0)<<",\"executed_IDs\":[";
            if(complete)summary<<ph58::jsonString(std::string("D04_")+argv[3]+"_"+argv[1]);
            summary<<"],\"completion_marker\":"<<ph58::jsonString(result==0?"PHASE62_PARTIAL_MIX_COMPLETE":"")<<",\"attempts\":"<<attempts<<",\"device\":"<<(buffer?buffer->device:0)<<",\"original_buffer\":"<<(buffer?buffer->original:0)<<",\"selected_buffer\":"<<(buffer?buffer->selected:0)<<",\"buffer_restored\":"<<(restored?"true":"false")<<",\"reason\":"<<ph58::jsonString(error)<<",\"callback_gate\":false,\"RT_deadline_approval\":\"NOT_ASSESSED\"}\n";
            summary.flush();if(!summary){result=1;std::cerr<<"partial最終summaryの保存失敗\n";}summary.close();std::ifstream file(out/"SUMMARY.json");std::cout<<file.rdbuf();}
        if(!error.empty())std::cerr<<error<<'\n';
    });owner.join();return result;
}

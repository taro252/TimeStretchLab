#define PHASE62_PLAYING_LEDGER_NO_MAIN
#include "Phase62PlayingLedgerNative.cpp"
int main(int argc,char** argv){
 if(argc!=5)return 2;int code=1;std::thread worker([&]{std::unique_ptr<LedgerFixture> f;const std::filesystem::path out=argv[4];try{
  const std::string mode=argv[1];require(mode=="initial_return_clear"||mode=="initial_started_clear"||mode=="committed_preparing"||mode=="manual_seek"||mode=="ready"||mode=="started_no_pcm","mode");require(std::filesystem::create_directories(out),"fresh output required");
  std::ofstream plan(out/"EXPECTED.json");plan<<"{\"schema\":2,\"expected\":2,\"expected_IDs\":[\"paused_Clear_contract\",\"normal_supply_and_owner_cap\"],\"mode\":"<<ph58::jsonString(mode)<<",\"binary_sha256\":"<<ph58::jsonString(fileHash(std::filesystem::absolute(argv[0])))<<",\"input_sha256\":"<<ph58::jsonString(fileHash(argv[2]))<<",\"callback_gate\":false}\n";plan.close();
  phase61_heap_reset();phase61_heap_begin();void*(*volatile allocate)(std::size_t)=std::malloc;void(*volatile release)(void*)=std::free;auto* probe=allocate(37);release(probe);phase61_heap_end();require(phase61_heap_allocations()&&phase61_heap_frees(),"heap detector");phase61_heap_reset();
  f=std::make_unique<LedgerFixture>(argv[2],std::string(argv[3])=="baseline"?Preset::Baseline:Preset::Candidate,out,std::vector<std::string>{"paused_Clear_contract","normal_supply_and_owner_cap"},4096);
  if(mode=="initial_return_clear"||mode=="initial_started_clear"){
   f->engine->stop();f->prepare(argv[2]);require(f->engine->play(),"normal play before Loop");firstPcm(*f->engine);
   f->gate.arm(mode=="initial_started_clear"?ProgressiveControlTestPoint::SwitchStartedOrDone:ProgressiveControlTestPoint::SeekPreparationStarted);const auto loop=f->engine->requestLoopRange(0,f->b,f->context());require(loop.accepted,"new initial ReturnToA");f->loopID=loop.id;
   f->until([&]{return f->gate.entered.load();},"initial ReturnToA normal gate");require(!f->engine->getLoopSnapshot().initialPositionComplete,"initial Loop adopted too early");
   const auto id=f->request("initial pending75",.75).id;require(f->engine->requestClearLoop(f->loopID,f->context()).accepted,"initial pending Clear");
   f->saveLedger("after_Clear_ledger.jsonl");if(mode=="initial_return_clear")require(f->row(id).state==LS::Cancelled&&!f->row(id).clearContinuation,"initial pending speed left nonterminal without continuation");else require(f->engine->getLoopSnapshot().clearPending,"Started initial Loop Clear lost continuation");f->releaseGate();
   const auto frames=f->capture().frames.load();f->until([&]{return f->capture().frames.load()>frames+2048&&!f->engine->getPlaybackDiagnostics().retiringPipeline;},"normal output after initial Clear");
   if(mode=="initial_started_clear"){f->until([&]{return !f->engine->getLoopSnapshot().clearPending;},"Started initial Clear completion");f->completed(id);}
   const auto l=f->engine->getLoopSnapshot();require(!l.enabled&&!l.clearPending&&!l.cycles,"cancelled initial Loop revived/counts");if(mode=="initial_return_clear")require(!l.initialPositionComplete,"unstarted initial Loop adopted");
   f->initialSeeks=f->engine->seekHistory().size();f->exactIds(true);f->saveLedger("terminal_ledger.jsonl");f->pass("paused_Clear_contract");f->qualityAndOwnership();f->pass("normal_supply_and_owner_cap");
   std::ofstream result(out/"SUMMARY.json");result<<"{\"schema\":2,\"run_complete\":true,\"status\":\"PASS\",\"expected\":2,\"executed\":2,\"owner_peak\":"<<ph58::RealtimePipeline::executionOwnerCounts().peak<<",\"owners_after_stop\":0,\"callback_gate\":false,\"independent_PCM\":false}\n";code=0;return;
  }
  if(mode=="committed_preparing")f->commit75();require(f->engine->pause(),"initial pause");
  std::uint64_t id=0;bool startedWindow=mode!="started_no_pcm";
  if(mode=="ready"||mode=="started_no_pcm"){
   for(unsigned attempt=0;attempt<(mode=="ready"?1u:8u);++attempt){const auto r=f->request("paused preparation",attempt%2?1.26:1.25);id=r.id;f->until([&]{return f->row(id).state==LS::ReadyForResume;},"paused Ready");if(mode=="ready")break;
    const auto before=f->capture().frames.load();require(f->engine->resume(),"window Resume");require(f->engine->pause(),"window rePause");const auto op=f->row(id);if(f->capture().frames.load()==before&&op.outputStarted&&!op.firstPcmObservedNs){startedWindow=true;break;}
   }
  }else{f->gate.arm(ProgressiveControlTestPoint::SeekPreparationStarted);id=f->request("125 paused preparing",1.25).id;f->until([&]{return f->gate.entered.load();},"paused normal gate");}
  const auto c=f->engine->getCurrentPlaybackPosition().inputFrame;require(c.has_value(),"fixed C");const auto frames=f->capture().frames.load();const auto cycles=f->engine->getLoopSnapshot().cycles;
  require(f->engine->requestClearLoop(f->loopID,f->context()).accepted,"Paused Clear");require(!f->engine->getLoopSnapshot().enabled,"Clear enabled");
  if(mode=="manual_seek"){
   const auto ctx=f->context();const auto receipt=f->engine->requestSeekToInputFrame(f->rate*2,ctx.inputGeneration,ctx.renderEpoch);require(receipt.accepted,"seek replaces Clear");++f->initialSeeks;
   require(f->row(id).state==LS::Cancelled&&f->row(id).reason.find(std::to_string(receipt.id))!=std::string::npos,"Clear transfer left pending after seek");f->releaseGate();
   f->until([&]{for(const auto& s:f->engine->seekHistory())if(s.id==receipt.id)return s.state==progressive::SeekState::Completed;return false;},"manual seek Ready");require(f->engine->getCurrentPlaybackPosition().inputFrame==f->rate*2,"manual seek C");
  }else{
   if(mode=="committed_preparing"){require(f->engine->resume()&&f->engine->getStateSnapshot().resumePending,"Clear resume intent not held");require(f->capture().frames.load()==frames,"old PCM emitted before Clear preparation");f->releaseGate();
    f->until([&]{return !f->engine->getLoopSnapshot().clearPending;},"Clear completion publication");require(f->engine->getPlaybackState()==State::Playing&&!f->engine->getStateSnapshot().resumePending,"Clear completed before retained Resume start");}
   else{
    f->until([&]{return !f->engine->getLoopSnapshot().clearPending&&!f->engine->getPlaybackDiagnostics().retiringPipeline;},"Paused Clear Ready without Resume");
    require(f->engine->getPlaybackState()==State::Paused&&f->capture().frames.load()==frames&&f->engine->getCurrentPlaybackPosition().inputFrame==c&&f->engine->getLoopSnapshot().cycles==cycles,"Paused Clear advanced C/output/cycle");
    if(mode=="ready"||startedWindow)require(f->row(id).state==LS::ReadyForResume,"Clear latest preparation not Ready");
    require(f->engine->getLoopSnapshot().pausedClearDiscardedFrames>0&&f->engine->getLoopSnapshot().pausedClearInputFrame==*c,"Paused Clear dedicated discard/C audit missing");require(f->engine->resume(),"Clear Resume");
   }
   f->until([&]{return f->capture().frames.load()>frames+2048;},"Clear latest PCM");
   if(mode=="ready"||mode=="committed_preparing"||startedWindow){f->completed(id);require(f->row(id).clearContinuation&&f->row(id).outputStarted,"Clear latest ID destination/start lost");}
  }
  f->engine->stop();f->exactIds(true);f->saveLedger("terminal_ledger.jsonl");
  if(!startedWindow){f->qualityAndOwnership();std::ofstream result(out/"SUMMARY.json");result<<"{\"schema\":2,\"run_complete\":true,\"status\":\"INCOMPLETE\",\"expected\":2,\"executed\":1,\"reason\":\"8回の自然な開始で未PCM窓を観測できず。callbackをゲートしない\"}\n";code=3;return;}
  f->pass("paused_Clear_contract");f->qualityAndOwnership();f->pass("normal_supply_and_owner_cap");std::ofstream result(out/"SUMMARY.json");result<<"{\"schema\":2,\"run_complete\":true,\"status\":\"PASS\",\"expected\":2,\"executed\":2,\"owner_peak\":"<<ph58::RealtimePipeline::executionOwnerCounts().peak<<",\"owners_after_stop\":0,\"callback_gate\":false,\"independent_PCM\":false}\n";code=0;
 }catch(const std::exception& error){if(f){f->gate.released=true;if(f->engine){f->engine->stop();f->saveLedger("failure_ledger.jsonl");}}std::cerr<<error.what()<<'\n';std::ofstream result(out/"SUMMARY.json");result<<"{\"schema\":2,\"run_complete\":false,\"status\":\"FAIL\",\"expected\":2,\"executed\":0,\"reason\":"<<ph58::jsonString(error.what())<<"}\n";}});worker.join();return code;
}

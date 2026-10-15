#include "prototype/Phase36SynthesisCore.h"
namespace ts::prototype {
using namespace synthesis_detail;
Phase36StreamingSpeedEngine::Phase36StreamingSpeedEngine(StretchConfig config)
    : config_(std::move(config)) {
    // Phase 13 analysis is speed independent; its validator covers the
    // frozen 0.50x branch while this isolated prototype permits 0.40x.
    auto validation=config_;
    validation.timeRatio=2.0;
    Phase13StreamingEngine validated(validation);
    if (config_.enablePartialTracking || config_.enablePVSOLA)
        throw std::invalid_argument("Phase 36 supports Experimental 3500 only");
}

Phase13Result Phase36StreamingSpeedEngine::process(
    const std::filesystem::path& input,const Phase13TransientAnalysis& analysis,
    TimeMap map,std::size_t outputFrames,std::size_t chunkSize,
    const PreparedSink& preparedSink,const UpdateHook& update,
    std::vector<std::pair<std::size_t,bool>> modeChanges,
    const ProfileHook& profileHook,std::ostream* componentCsv,
    std::size_t probeFirst,std::size_t probeLast,bool recordFrameHistory,const std::function<void()>& initialized) {
    std::ostream* stageTrace=nullptr;
    std::size_t probeInputSample=0;
    if (!preparedSink || map.empty() || map.sourceHop()!=1024 ||
        chunkSize<1024 || chunkSize>65536)
        throw std::invalid_argument("Invalid Phase 24 process request");
    WavStreamReader reader(input);
    if (reader.frames()!=analysis.inputFrames() ||
        reader.channels()!=static_cast<std::size_t>(config_.channels) ||
        reader.sampleRate()!=config_.sampleRate)
        throw std::invalid_argument("Analyzed WAV metadata differs from Phase 24 input");
    if (reader.frames()==0 || outputFrames==0)
        throw std::invalid_argument("Phase 24 requires nonempty audio");
    auto detection=makeDetection(analysis,config_,map);
    WorkProfile workProfile;
    WorkProfile* profile=profileHook ? &workProfile : nullptr;
    Phase13Result phase13;
    for (auto* group:{&phase13.stages.fft,&phase13.stages.phase,
                     &phase13.stages.ifft,&phase13.stages.ola}) group->fill(hashSeed);
    phase13.stages.lowFir=hashSeed;
    phase13.stages.highFir=hashSeed;
    phase13.stages.fir=hashSeed;
    auto& result=phase13.processing;
    result.inputFrames=reader.frames();
    result.outputFrames=outputFrames;
    result.chunkSize=chunkSize;
    result.timeMapHash=hashSeed;
    for (const auto start:map.starts()) {
        result.timeMapHash^=static_cast<std::uint64_t>(start);
        result.timeMapHash*=1099511628211ULL;
    }
    result.transientCount=detection.transientCount;
    result.eventCount=detection.eventCount;
    result.anchoredEventCount=detection.anchoredCount;
    result.maxAnchorErrorSamples=detection.anchorError;

    // One instance per resolution persists across the whole input. The
    // crossover filters likewise retain their overlap and FFT block position.
    std::array<std::unique_ptr<ResolutionStream>,3> resolution;
    resolution[1]=std::make_unique<ResolutionStream>(input,config_,4096,1024,
        detection,true,outputFrames,modeChanges,phase13.stages,1,stageTrace,probeInputSample,profile,
        recordFrameHistory);
    resolution[0]=std::make_unique<ResolutionStream>(input,config_,8192,2048,
        detection,false,outputFrames,modeChanges,phase13.stages,0,stageTrace,probeInputSample,profile,
        recordFrameHistory);
    resolution[2]=std::make_unique<ResolutionStream>(input,config_,1024,256,
        detection,false,outputFrames,modeChanges,phase13.stages,2,stageTrace,probeInputSample,profile,
        recordFrameHistory);
    for (const auto& item:resolution)
        result.olaRingSamples+=item->olaSize()*reader.channels();
    MultiResolutionCrossover filters(config_.sampleRate,config_.lowCrossoverHz,
                                     config_.highCrossoverHz);
    std::vector<std::unique_ptr<LiveStreamingFIR>> lowFilters,highFilters;
    for (std::size_t c=0;c<reader.channels();++c) {
        lowFilters.emplace_back(std::make_unique<LiveStreamingFIR>(filters.lowFilter(),outputFrames,profile));
        highFilters.emplace_back(std::make_unique<LiveStreamingFIR>(filters.highFilter(),outputFrames,profile));
    }
    result.firRingSamples=(lowFilters[0]->ringSize()+highFilters[0]->ringSize())*
        reader.channels();
    std::vector<std::vector<float>> chunk(reader.channels(),std::vector<float>(chunkSize));
    std::vector<const float*> pointers(reader.channels());
    for (std::size_t c=0;c<reader.channels();++c) pointers[c]=chunk[c].data();
    if(initialized)initialized();
    for (std::size_t start=0;start<outputFrames;start+=chunkSize) {
        if (profile) workProfile={};
        const auto count=std::min(chunkSize,outputFrames-start);
        for (std::size_t i=0;i<count;++i) for (std::size_t c=0;c<reader.channels();++c) {
            const auto high=resolution[2]->get(c,start+i);
            const auto lowFiltered=lowFilters[c]->next(start+i,[&](std::size_t n) {
                return resolution[0]->get(c,n)-resolution[1]->get(c,n);
            });
            const auto highFiltered=highFilters[c]->next(start+i,[&](std::size_t n) {
                return resolution[1]->get(c,n)-resolution[2]->get(c,n);
            });
            hashFloat(phase13.stages.lowFir,lowFiltered);
            hashFloat(phase13.stages.highFir,highFiltered);
            float value=high;
            value+=lowFiltered;
            value+=highFiltered;
            chunk[c][i]=value;
            if (componentCsv && start+i>=probeFirst && start+i<probeLast)
                *componentCsv<<start+i<<','<<c<<','
                    <<resolution[0]->get(c,start+i)<<','
                    <<resolution[1]->get(c,start+i)<<','<<high<<','
                    <<lowFiltered<<','<<highFiltered<<','<<value<<'\n';
            hashFloat(phase13.stages.fir,value);
            result.peak=std::max(result.peak,std::abs(value));
            if (stageTrace && c+1==reader.channels() && (start+i)%256==0 &&
                std::llabs(static_cast<long long>(start+i)-
                           std::llround(map.outputPositionForInputSample(
                               double(probeInputSample))))<=131072)
                *stageTrace<<"fir,-1,-1,-1,"<<start+i<<",,,,,"
                           <<phase13.stages.lowFir<<','<<phase13.stages.highFir<<','
                           <<phase13.stages.fir<<'\n';
        }
        const auto poll=[&] {
            if (!update || start+count>=outputFrames) return;
            {
                Frontier frontier;
                frontier.preparedOutput=start+count;
                for (std::size_t r=0;r<3;++r) {
                    frontier.nextInput[r]=resolution[r]->firstUnprocessedInputSample();
                    frontier.lastProcessedInput[r]=resolution[r]->lastProcessedInputSample();
                    frontier.finalizedOla[r]=resolution[r]->finalizedOlaSample();
                    if (recordFrameHistory) {
                        resolution[r]->copyFrameHistory(frontier.recentFrameInput[r],
                            frontier.recentFrameOutput[r],frontier.recentFrameCount[r]);
                        frontier.actualWeightSample[r]=frontier.finalizedOla[r];
                        frontier.actualWeight[r]=resolution[r]->diagnosticOlaWeight();
                    }
                }
                frontier.firstUnprocessedFirSource={
                    lowFilters[0]->firstUnprocessedSourceSample(),
                    highFilters[0]->firstUnprocessedSourceSample()};
                update(frontier,detection.map,outputFrames,modeChanges);
            }
            if (outputFrames<start+count || outputFrames>
                static_cast<std::size_t>(std::ceil(reader.frames()*2.5))+2)
                throw std::runtime_error("Invalid live output length");
            for (auto& item:resolution) item->setOutputLength(outputFrames);
            for (auto& item:lowFilters) item->setOutputLength(outputFrames);
            for (auto& item:highFilters) item->setOutputLength(outputFrames);
        };
        preparedSink(pointers.data(),count,poll);
        if (profile) profileHook(start,workProfile);
    }
    result.outputFrames=outputFrames;
    result.timeMapHash=hashSeed;
    for (const auto value:detection.map.starts()) {
        result.timeMapHash^=static_cast<std::uint64_t>(value);
        result.timeMapHash*=1099511628211ULL;
    }
    result.averageCoherenceWeight=resolution[1]->averageCoherenceWeight();
    return phase13;
}
}

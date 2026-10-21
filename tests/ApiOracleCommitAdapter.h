#pragma once
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include <optional>
#include <vector>

// One bounded, immutable producer-side commit sample, copied by the NORMAL
// control thread while the source owner still lives. This is not another DSP.
// The product must record FIFO cursors at commit, not when this getter is polled.
struct ApiOracleCommitEvidence {
    bool atomicCommitSample=false,settingCycleObserved=false;
    std::string operationStateAtSample;
    std::uint64_t sequence=0,externalID=0,loopID=0,inputGeneration=0;
    std::uint64_t dynamicSession=0,planningRenderEpoch=0,renderEpoch=0,settingCycle=0;
    ts::prototype::phase58::LoopTransitionSnapshot descriptor;
    std::uint64_t fifoReadAtCommit=0,fifoWriteAtCommit=0;
    std::size_t pendingBeginLocal=0,pendingEndLocal=0;
    int sourceHop=1024;
    std::vector<long long> mapNodes;
};

// Integration point: define PHASE62_API_ORACLE_PRODUCT_EVIDENCE only after the
// product's bounded normal-thread getter is available. Adapt this single body
// to its final type/name. A missing getter cannot silently pass a Map/FIFO gate.
inline std::optional<ApiOracleCommitEvidence> readApiOracleCommit(
    ts::playback::ProgressiveMacPlaybackEngine& engine,std::uint64_t externalID){
#ifdef PHASE62_API_ORACLE_PRODUCT_EVIDENCE
    const auto source=engine.loopSpeedPcmEvidence(externalID);if(!source)return {};
    ApiOracleCommitEvidence result;
    const auto& op=source->operation;const auto& d=source->commit;
    result.atomicCommitSample=d.state==ts::prototype::phase58::LoopTransitionState::Committed&&d.auditSequence>0;
    result.sequence=d.auditSequence;result.externalID=op.id;result.loopID=op.loopID;result.inputGeneration=op.inputGeneration;
    result.dynamicSession=op.dynamicSession;result.planningRenderEpoch=op.planningRenderEpoch;
    result.renderEpoch=op.renderEpoch;result.settingCycle=op.cycle;result.settingCycleObserved=op.outputStarted;
    result.operationStateAtSample=ts::playback::progressive::name(op.state);result.descriptor=d;
    result.fifoReadAtCommit=d.fifoReadAtCommit;result.fifoWriteAtCommit=d.fifoWriteAtCommit;
    // 動的確定の未公開PCMは [P-pending,P)。固定B延期を動的確定と混同しない。
    if(d.pendingPcmFramesAtCommit>d.pcmGeneratedAtCommit)return {};
    result.pendingBeginLocal=d.pcmGeneratedAtCommit-d.pendingPcmFramesAtCommit;
    result.pendingEndLocal=d.pcmGeneratedAtCommit;
    result.sourceHop=source->map.sourceHop();result.mapNodes=source->map.starts();return result;
#else
    (void)engine;(void)externalID;return {};
#endif
}

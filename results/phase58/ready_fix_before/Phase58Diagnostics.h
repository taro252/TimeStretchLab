#pragma once
#include "prototype/Phase58RealtimePipeline.h"
#include <iomanip>
#include <ostream>
namespace ts::prototype::phase58 {
inline std::string jsonString(const std::string& s){std::string out="\"";for(unsigned char c:s){if(c=='\"'||c=='\\'){out+='\\';out+=char(c);}else if(c=='\n')out+="\\n";else if(c=='\r')out+="\\r";else if(c=='\t')out+="\\t";else if(c>=32)out+=char(c);}return out+'\"';}
inline void writeDiagnostics(std::ostream& out,const Diagnostics& d){
    out<<std::setprecision(17);const auto n=[&](const char* k,auto v){out<<",\""<<k<<"\":"<<v;};
    n("session",d.session);n("analysis_thread",d.analysisThread);n("dsp_thread",d.dspThread);n("snapshot_version",d.snapshotVersion);
    n("input_frames",d.inputFrames);n("received_input",d.receivedInput);n("generated_frames",d.generated);n("published_frames",d.published);n("consumed_frames",d.consumed);n("output_frames",d.outputFrames);
    n("input_at_first_pcm",d.inputAtFirstPcm);n("input_at_ready",d.inputAtReady);n("non_eos_published",d.nonEosPublished);
    n("source_snapshot_bytes",d.sourceSnapshotBytes);n("analysis_worker_cpu_s",d.analysisWorkerCpuS);
    n("fifo_high_water",d.fifoHighWater);n("snapshot_peak_bytes",d.snapshotPeakBytes);n("snapshot_copy_bytes",d.snapshotCopyBytes);
    n("missing_frames",d.missingFrames);n("missing_calls",d.missingCalls);n("max_consecutive_missing",d.maxConsecutiveMissing);n("rejected_writes",d.rejectedWrites);n("analysis_waits",d.analysisWaits);
    n("verified_s",d.verifiedS);n("identified_s",d.identifiedS);n("analysis_start_s",d.analysisStartS);n("first_event_s",d.firstEventS);n("first_map_s",d.firstMapS);
    n("first_generated_s",d.firstGeneratedS);n("first_published_s",d.firstPublishedS);n("ready_s",d.readyS);n("analysis_done_s",d.analysisDoneS);
    n("analysis_cpu_s",d.analysisCpuS);n("dsp_cpu_s",d.dspCpuS);n("max_dsp_wall_s",d.maxDspWallS);n("analysis_wait_s",d.analysisWaitS);n("backpressure_wait_s",d.backpressureWaitS);
    n("dsp_worker_cpu_s",d.dspWorkerCpuS);n("max_dsp_cpu_s",d.maxDspCpuS);n("max_publication_gap_s",d.maxPublicationGapS);n("worker_profile_records",d.workerProfileRecords);n("worker_profile_dropped",d.workerProfileDropped);
    n("dsp_original_path_validation",false);n("max_dsp_validation_wall_s","null");n("max_dsp_validation_cpu_s","null");
    n("analysis_qos",d.analysisQos);n("dsp_qos",d.dspQos);n("analysis_done",d.analysisDone);n("dsp_done",d.dspDone);n("cancelled",d.cancelled);n("failed",d.failed);
    n("input_sha256",jsonString(d.inputSha256));n("pcm_sha256",jsonString(d.pcmSha256));n("error",jsonString(d.error));
}
}

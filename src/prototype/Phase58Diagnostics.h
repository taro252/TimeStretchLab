#pragma once
#include "prototype/Phase58RealtimePipeline.h"
#include <iomanip>
#include <ostream>
namespace ts::prototype::phase58 {
inline std::string jsonString(const std::string& s){std::string out="\"";for(unsigned char c:s){if(c=='\"'||c=='\\'){out+='\\';out+=char(c);}else if(c=='\n')out+="\\n";else if(c=='\r')out+="\\r";else if(c=='\t')out+="\\t";else if(c>=32)out+=char(c);}return out+'\"';}
inline void writeDiagnostics(std::ostream& out,const Diagnostics& d){
    out<<std::setprecision(17);const auto n=[&](const char* k,auto v){out<<",\""<<k<<"\":"<<v;};
    const auto final=[&](const char* k,auto v){n(k,d.finalDataAvailable?std::to_string(v):"null");};
    n("lifecycle",int(d.lifecycle));n("final_data_available",d.finalDataAvailable);
    n("session",d.session);n("analysis_thread",d.analysisThread);n("dsp_thread",d.dspThread);n("snapshot_version",d.snapshotVersion);
    n("input_frames",d.inputFrames);n("received_input",d.receivedInput);n("generated_frames",d.generated);n("published_frames",d.published);n("consumed_frames",d.consumed);n("output_frames",d.outputFrames);
    n("input_at_first_pcm",d.inputAtFirstPcm);n("input_at_ready",d.inputAtReady);n("non_eos_published",d.nonEosPublished);
    n("source_snapshot_bytes",d.sourceSnapshotBytes);final("analysis_worker_cpu_s",d.analysisWorkerCpuS);
    n("resident_input_bytes",d.residentInputBytes);n("resident_ready_s",d.residentReadyS);final("borrowed_snapshot_owners",d.borrowedSnapshotOwners);n("rendering_requested",d.renderingRequested);
    n("input_samples_prevalidated",d.inputSamplesPrevalidated);
    n("dynamic_transitions",d.dynamicTransitions);n("transition_operations",d.transitionOperations);final("transition_map_owners",d.transitionMapOwners);
    n("transition_history",d.transitionHistory);n("transition_map_peak_bytes",d.transitionMapPeakBytes);n("transition_plan_attempts",d.transitionPlanAttempts);
    n("transition_stale_replans",d.transitionStaleReplans);n("transition_analysis_deferrals",d.transitionAnalysisDeferrals);
    n("transition_plan_cpu_s",d.transitionPlanCpuS);n("transition_plan_wall_s",d.transitionPlanWallS);
    const auto& rt=d.scheduling;
    n("workgroup_enabled",rt.enabled);n("workgroup_policy_measured",rt.policyMeasured);n("workgroup_active_after_stop",rt.active);
    n("workgroup_promotions",rt.promotions);n("workgroup_joins",rt.joins);n("workgroup_leaves",rt.leaves);n("workgroup_restores",rt.restores);
    n("workgroup_created_ticks",rt.createdTicks);n("workgroup_policy_applied_ticks",rt.policyAppliedTicks);n("workgroup_joined_ticks",rt.joinedTicks);n("workgroup_left_ticks",rt.leftTicks);n("workgroup_restored_ticks",rt.restoredTicks);
    n("workgroup_interval_starts",rt.intervalStarts);n("workgroup_interval_finishes",rt.intervalFinishes);n("workgroup_deadline_misses",rt.deadlineMisses);
    n("workgroup_policy_errors",rt.policyErrors);n("workgroup_join_errors",rt.joinErrors);n("workgroup_restore_errors",rt.restoreErrors);n("workgroup_interval_errors",rt.intervalErrors);n("workgroup_query_errors",rt.queryErrors);
    n("workgroup_wait_calls",rt.waitCalls);n("workgroup_wait_errors",rt.waitErrors);n("workgroup_wake_errors",rt.wakeErrors);
    n("workgroup_observed_policy",rt.policyMeasured?std::to_string(rt.observedPolicy):"null");n("workgroup_observed_priority",rt.policyMeasured?std::to_string(rt.observedPriority):"null");
    n("workgroup_restored_policy",rt.restores?std::to_string(rt.restoredPolicy):"null");n("workgroup_last_error",rt.lastError);n("workgroup_error_stage",rt.errorStage);
    n("workgroup_period_s",rt.enabled?std::to_string(rt.periodS):"null");n("workgroup_computation_s",rt.enabled?std::to_string(rt.computationS):"null");n("workgroup_max_interval_s",rt.intervalStarts?std::to_string(rt.maxIntervalS):"null");
    n("realtime_cpp_allocations_measured",d.realtimeAllocationsMeasured);n("realtime_cpp_new_calls",d.realtimeAllocationsMeasured?std::to_string(d.realtimeNewCalls):"null");
    n("fifo_high_water",d.fifoHighWater);n("analysis_storage_measured",d.analysisDone);
    if(d.analysisDone){n("snapshot_peak_bytes",d.snapshotPeakBytes);n("snapshot_copy_bytes",d.snapshotCopyBytes);}else{n("snapshot_peak_bytes","null");n("snapshot_copy_bytes","null");}
    n("missing_frames",d.missingFrames);n("missing_calls",d.missingCalls);n("max_consecutive_missing",d.maxConsecutiveMissing);n("rejected_writes",d.rejectedWrites);n("analysis_waits",d.analysisWaits);
    n("verified_s",d.verifiedS);n("identified_s",d.identifiedS);n("analysis_start_s",d.analysisStartS);n("first_event_s",d.firstEventS);n("first_map_s",d.firstMapS);
    n("first_generated_s",d.firstGeneratedS);n("first_published_s",d.firstPublishedS);n("ready_s",d.readyS);n("analysis_done_s",d.analysisDoneS);
    n("analysis_cpu_measured",d.analysisDone);if(d.analysisDone)n("analysis_cpu_s",d.analysisCpuS);else n("analysis_cpu_s","null");n("dsp_cpu_s",d.dspCpuS);n("max_dsp_wall_s",d.maxDspWallS);n("analysis_wait_s",d.analysisWaitS);n("backpressure_wait_s",d.backpressureWaitS);
    final("dsp_worker_cpu_s",d.dspWorkerCpuS);n("max_dsp_cpu_s",d.maxDspCpuS);n("max_publication_gap_s",d.maxPublicationGapS);final("worker_profile_records",d.workerProfileRecords);final("worker_profile_dropped",d.workerProfileDropped);
    final("detail_records",d.detailRecords);final("detail_dropped",d.detailDropped);n("dsp_allocations_measured",d.dspAllocationsMeasured);
    n("dsp_cpp_new_calls",d.dspAllocationsMeasured?std::to_string(d.dspNewCalls):"null");
    n("analysis_qos_class",d.analysisQosClass);n("dsp_qos_class",d.dspQosClass);
    n("analysis_qos_relative_priority",d.analysisQosRelativePriority);n("dsp_qos_relative_priority",d.dspQosRelativePriority);
    n("analysis_qos_queried",d.analysisQosQueried);n("dsp_qos_queried",d.dspQosQueried);
    n("thread_sampling_requested",d.threadSamplingRequested);final("thread_samples",d.threadSamples);final("thread_samples_dropped",d.threadSamplesDropped);final("thread_sample_errors",d.threadSampleErrors);
    n("sampler_cpu_s",d.finalDataAvailable&&d.threadSamplingRequested?std::to_string(d.samplerCpuS):"null");
    n("dsp_original_path_validation",false);n("max_dsp_validation_wall_s","null");n("max_dsp_validation_cpu_s","null");
    n("analysis_qos",d.analysisQos);n("dsp_qos",d.dspQos);n("analysis_done",d.analysisDone);n("dsp_done",d.dspDone);n("cancelled",d.cancelled);n("failed",d.failed);
    n("input_sha256",jsonString(d.inputSha256));n("pcm_sha256",jsonString(d.pcmSha256));n("error",jsonString(d.error));
}
}

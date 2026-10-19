#pragma once
#include <fstream>
#include <iomanip>
#include <cmath>
// Normal owner only, after callback quiescence. No callback-side formatting.
inline void writePhase62Trace(const std::filesystem::path& path,const std::vector<ts::playback::ProgressiveCallbackRecord>& rows){
    std::ofstream f(path);f<<std::setprecision(17);
    for(const auto& row:rows){const auto& c=row.callback;const auto& e=row.clock;
        f<<"{\"callback\":{\"sequence\":"<<c.sequence<<",\"clock_epoch\":"<<c.epoch<<",\"start_ns\":"<<c.startNs<<",\"end_ns\":"<<c.endNs<<",\"io_end_ns\":"<<c.ioEndNs<<",\"host_ns\":"<<c.hostNs<<",\"host_ticks\":"<<c.hostTicks<<",\"sample_time\":";
        if(std::isfinite(c.sampleTime))f<<c.sampleTime;else f<<"null";
        f<<",\"flags\":"<<c.timestampFlags<<",\"rate_scalar\":";if(std::isfinite(c.rateScalar))f<<c.rateScalar;else f<<"null";
        f<<",\"requested\":"<<c.requested<<"},\"mach_numer\":"<<row.machNumer<<",\"mach_denom\":"<<row.machDenom<<",\"source_rate\":"<<row.sourceRate<<",\"device_rate\":"<<row.deviceRate<<",\"previous_frames\":"<<row.previousFrames<<",\"render_epoch\":"<<row.renderEpoch<<",\"speed_request_id\":"<<row.speedRequestID<<",\"route_changes\":"<<row.routeChanges;
        f<<",\"clock\":{\"host_missing\":"<<e.hostMissing<<",\"host_backwards\":"<<e.hostBackwards<<",\"cadence\":"<<e.cadenceError<<",\"sample\":"<<e.sampleError<<",\"hal\":"<<e.halWindowMiss<<",\"offset\":"<<e.offsetOutlier<<"},\"old_missing\":"<<row.oldMissingFrames<<",\"new_missing\":"<<row.newMissingFrames<<",\"affected\":"<<row.outputAffectedFrames<<",\"padding\":"<<row.failurePaddingFrames<<",\"pause_silence\":"<<row.pauseSilenceFrames<<",\"spans\":[";
        for(std::size_t i=0;i<row.spanCount;++i){if(i)f<<',';const auto& s=row.spans[i];
            f<<"{\"callback_frame\":"<<s.callbackFrame<<",\"frames\":"<<s.frames<<",\"new_epoch\":"<<s.newEpoch<<",\"old_epoch\":"<<s.oldEpoch<<",\"new_output\":"<<s.newOutputOffset<<",\"old_output\":"<<s.oldOutputOffset<<",\"new_received\":"<<s.newReceivedFrames<<",\"old_received\":"<<s.oldReceivedFrames<<",\"old_missing\":"<<s.oldMissingFrames<<",\"new_missing\":"<<s.newMissingFrames<<",\"affected\":"<<s.outputAffectedFrames<<",\"padding\":"<<s.failurePaddingFrames<<",\"unrendered_failure\":"<<s.unrenderedFailure<<",\"periodic\":"<<s.periodicBoundary<<",\"period_frames\":"<<s.periodFrames<<",\"period_offset\":"<<s.periodOffset<<",\"boundary_frames\":"<<s.boundaryFrames<<"}";
        }f<<"]}\n";
    }
}

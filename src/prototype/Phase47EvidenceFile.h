#pragma once
#include <filesystem>
#include <fstream>
#include <cstdlib>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
#include <stdexcept>
#include <string>

namespace ts::prototype {
// Control-thread only. Failed writes keep a partial artifact and never publish
// a final filename. No instances are created in the audio callback.
class Phase47EvidenceFile {
public:
    explicit Phase47EvidenceFile(const std::filesystem::path& final)
        : final_(final),partial_(final.string()+".partial") {
        if (std::filesystem::exists(final_)) throw std::runtime_error("Evidence already exists: "+final_.string());
        stream_.exceptions(std::ios::failbit|std::ios::badbit);
        stream_.open(partial_,std::ios::out|std::ios::trunc);
    }
    std::ostream& stream() { return stream_; }
    void commit() {
        inject("write");
        stream_.flush();inject("flush");
        stream_.close();inject("close");
        int fd=::open(partial_.c_str(),O_RDONLY);
        if (fd<0) throw std::runtime_error("Evidence reopen failed");
        const int synced=::fsync(fd);const int closed=::close(fd);
        if (synced || closed) throw std::runtime_error("Evidence fsync/close failed");
        // link() is an atomic no-overwrite publication on this filesystem.
        if (::link(partial_.c_str(),final_.c_str())!=0) throw std::runtime_error("Evidence publication failed");
        if (::unlink(partial_.c_str())!=0) throw std::runtime_error("Evidence partial unlink failed");
        int parent=::open(final_.parent_path().empty() ? "." : final_.parent_path().c_str(),O_RDONLY);
        if (parent<0) throw std::runtime_error("Evidence directory open failed");
        const int directorySync=::fsync(parent);const int directoryClose=::close(parent);
        if (directorySync || directoryClose) throw std::runtime_error("Evidence directory sync failed");
    }
private:
    void inject(const char* stage) {
        if (const char* fault=std::getenv("PHASE47_IO_FAILURE_STAGE");fault && std::string(fault)==stage)
            throw std::runtime_error(std::string("Injected evidence I/O failure: ")+stage);
    }
    std::filesystem::path final_,partial_;
    std::ofstream stream_;
};
}

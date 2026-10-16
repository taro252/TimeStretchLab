#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <utility>

namespace ts::prototype::phase58 {
// One normal publisher owns three leases. One realtime reader borrows them.
// The reader neither changes a shared_ptr count nor frees snapshot/page storage.
template<class Snapshot> class BorrowedSnapshotMailbox {
    static constexpr unsigned none=3;
    std::array<std::shared_ptr<const Snapshot>,3> owners_{};
    std::atomic<std::uint64_t> published_{none};
    std::atomic<unsigned> hazard_{none},current_{none};
    std::uint64_t version_=0; // Publisher only.
public:
    static constexpr std::uint64_t initialTag=none;
    class Lease {
        BorrowedSnapshotMailbox* mailbox_;
        const Snapshot* value_;
        std::uint64_t tag_;
        friend class BorrowedSnapshotMailbox;
        Lease(BorrowedSnapshotMailbox* mailbox,const Snapshot* value,std::uint64_t tag)
            :mailbox_(mailbox),value_(value),tag_(tag){}
    public:
        Lease(const Lease&)=delete;
        Lease& operator=(const Lease&)=delete;
        Lease(Lease&& other)noexcept:mailbox_(std::exchange(other.mailbox_,nullptr)),value_(other.value_),tag_(other.tag_){}
        ~Lease(){if(mailbox_)mailbox_->hazard_.store(none);}
        const Snapshot* get()const noexcept{return value_;}
        std::uint64_t tag()const noexcept{return tag_;}
        // Call only after the synthesis engine has stopped using its old view.
        // The committed pointer remains valid until the next committed lease.
        void commit()noexcept{
            if(!mailbox_)return;
            mailbox_->current_.store(unsigned(tag_&3));
            mailbox_->hazard_.store(none);
            mailbox_=nullptr;
        }
    };
    bool tryPublish(std::shared_ptr<const Snapshot>& value){
        if(!value)throw std::invalid_argument("Missing snapshot lease");
        const auto published=unsigned(published_.load()&3);
        // The order matters: the reader publishes current before clearing its
        // hazard. Sequential consistency and the full version tag prevent ABA.
        const auto hazard=hazard_.load();const auto current=current_.load();
        for(unsigned slot=0;slot<owners_.size();++slot){
            if(slot==published||slot==hazard||slot==current)continue;
            owners_[slot]=std::move(value); // Destruction stays on this normal thread.
            published_.store((++version_<<2)|slot);
            return true;
        }
        return false;
    }
    std::optional<Lease> acquire(std::uint64_t seenTag)noexcept{
        for(unsigned attempt=0;attempt<4;++attempt){
            const auto tag=published_.load();
            if(tag==initialTag||tag==seenTag)return {};
            const auto slot=unsigned(tag&3);hazard_.store(slot);
            if(published_.load()!=tag){hazard_.store(none);continue;}
            return Lease(this,owners_[slot].get(),tag);
        }
        return {};
    }
    std::size_t ownerCount()const{ // Publisher or joined threads only.
        std::size_t count=0;for(const auto& owner:owners_)count+=bool(owner);return count;
    }
};
}

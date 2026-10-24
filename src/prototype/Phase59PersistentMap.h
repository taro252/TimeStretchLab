#pragma once
#include "prototype/Phase56ImmutableSeries.h"
#include "dsp/TimeMap.h"
#include <iterator>
#include <compare>
#include <cmath>

namespace ts::prototype::phase59 {
// The publication mailbox pins the roots. The prebuilt raw-page index gives
// DSP reads two pointer lookups without shared_ptr operations or allocation.
// Whole-vector export is explicit normal-thread work, preserving old TimeMap.
class PersistentMap {
    phase56::ImmutableSeries<long long> nodes_;
    phase56::ImmutableSeries<TransientEvent> events_;
    std::vector<const long long*> pages_;
    int hop_=1024;
    void indexPages(){
        constexpr auto width=phase56::ImmutableSeries<long long>::pageWidth;
        pages_.reserve((nodes_.size()+width-1)/width);
        for(std::size_t i=0;i<(nodes_.size()+width-1)/width;++i)pages_.push_back(nodes_.borrowedPageData(i));
    }
public:
    class Nodes {
        const PersistentMap* map_;
    public:
        struct Iterator {
            using iterator_category=std::random_access_iterator_tag;
            using value_type=long long;using difference_type=std::ptrdiff_t;
            using pointer=const long long*;using reference=const long long&;
            const PersistentMap* map=nullptr;difference_type i=0;
            reference operator*()const{return map->nodeAt(std::size_t(i));}
            reference operator[](difference_type n)const{return *(*this+n);}
            Iterator& operator++(){++i;return *this;}Iterator operator++(int){auto r=*this;++*this;return r;}
            Iterator& operator--(){--i;return *this;}Iterator operator--(int){auto r=*this;--*this;return r;}
            Iterator& operator+=(difference_type n){i+=n;return *this;}
            Iterator& operator-=(difference_type n){i-=n;return *this;}
            friend Iterator operator+(Iterator a,difference_type n){return a+=n;}
            friend Iterator operator+(difference_type n,Iterator a){return a+=n;}
            friend Iterator operator-(Iterator a,difference_type n){return a-=n;}
            friend difference_type operator-(Iterator a,Iterator b){return a.i-b.i;}
            bool operator==(const Iterator&)const=default;
            auto operator<=>(const Iterator& b)const{return i<=>b.i;}
        };
        explicit Nodes(const PersistentMap& map):map_(&map){}
        std::size_t size()const noexcept{return map_->nodes_.size();}
        std::size_t capacity()const noexcept{return size();}
        bool empty()const noexcept{return !size();}
        const long long& operator[](std::size_t i)const{return map_->nodeAt(i);}
        const long long& at(std::size_t i)const{return map_->nodeAt(i);}
        const long long& back()const{return (*this)[size()-1];}
        Iterator begin()const{return {map_,0};}Iterator end()const{return {map_,std::ptrdiff_t(size())};}
        bool operator==(const Nodes& b)const{return size()==b.size()&&std::equal(begin(),end(),b.begin());}
    };
    PersistentMap()=default;
    PersistentMap(phase56::ImmutableSeries<long long> n,phase56::ImmutableSeries<TransientEvent> e,int hop=1024)
        :nodes_(std::move(n)),events_(std::move(e)),hop_(hop){indexPages();}
    PersistentMap(const TimeMap& source){*this=source;}
    PersistentMap& operator=(const TimeMap& source){
        auto ledger=std::make_shared<phase56::MemoryLedger>(4*1024*1024);ledger->owner=ledger;
        phase56::ImmutableSeries<long long> n;
        phase56::ImmutableSeries<TransientEvent> e;
        *this=PersistentMap(n.extend(source.starts(),source.starts().size(),ledger),
            e.extend(source.events(),source.events().size(),ledger),source.sourceHop());return *this;
    }
    const long long& nodeAt(std::size_t i)const{
        if(i>=nodes_.size())throw std::out_of_range("Unpublished persistent map node");
        constexpr auto width=phase56::ImmutableSeries<long long>::pageWidth;
        return pages_[i/width][i%width];
    }
    Nodes starts()const noexcept{return Nodes(*this);}
    const auto& nodeSeries()const noexcept{return nodes_;}
    const auto& eventSeries()const noexcept{return events_;}
    std::size_t indexBytes()const noexcept{return pages_.capacity()*sizeof(const long long*);}
    int sourceHop()const noexcept{return hop_;}
    bool empty()const noexcept{return !nodes_.size();}
    double outputPositionForInputSample(double input)const{
        if(empty()||!std::isfinite(input)||input<0)throw std::invalid_argument("Invalid persistent map position");
        const auto n=starts();if(n.size()==1)return n[0];
        const double fractional=input/hop_;const auto left=std::min(static_cast<std::size_t>(fractional),n.size()-2);
        const double local=fractional-left;
        return n[left]+local*double(n[left+1]-n[left]);
    }
    TimeMap materialize()const{
        const auto n=starts();std::vector<long long> nodes(n.begin(),n.end());
        std::vector<TransientEvent> events;events.reserve(events_.size());
        for(std::size_t i=0;i<events_.size();++i)events.push_back(events_.borrowedAt(i));
        return TimeMap(hop_,std::move(nodes),std::move(events));
    }
};
}

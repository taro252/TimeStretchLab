#pragma once
#include <algorithm>
#include <array>
#include <atomic>
#include <memory>
#include <stdexcept>
#include <vector>
#include <utility>
namespace ts::prototype::phase56 {
// Accounted payload/object budget, not allocator overhead or process RSS.
struct MemoryLedger {
    std::atomic<std::size_t> live{0},peak{0},copied{0};std::size_t limit;
    explicit MemoryLedger(std::size_t n):limit(n){}
    template<class T,class... A> std::shared_ptr<T> make(A&&... args) {
        const auto before=live.fetch_add(sizeof(T));
        if(before>limit||sizeof(T)>limit-before){live.fetch_sub(sizeof(T));throw std::bad_alloc();}
        auto high=peak.load();while(high<before+sizeof(T)&&!peak.compare_exchange_weak(high,before+sizeof(T))){}
        auto self=owner.lock();
        T* value=nullptr;
        try {value=new T(std::forward<A>(args)...);}catch(...){live.fetch_sub(sizeof(T));throw;}
        return std::shared_ptr<T>(value,[self](T* p){delete p;self->live.fetch_sub(sizeof(T));});
    }
    std::weak_ptr<MemoryLedger> owner;
};
// Persistent binary page index: bounded path copy (16 nodes) per changed page.
// A published page is never mutated, even while a reader retains old snapshots.
template<class T> class ImmutableSeries {
    static constexpr std::size_t width=64,depth=16;
    struct Page {std::array<T,width> values{};};
    struct Node {std::shared_ptr<const Node> left,right;std::shared_ptr<const Page> page;};
    std::shared_ptr<const Node> root_;std::size_t size_=0;
    static std::shared_ptr<const Node> replace(const std::shared_ptr<const Node>& old,
        std::size_t key,unsigned level,std::shared_ptr<const Page> page,const std::shared_ptr<MemoryLedger>& m){
        auto n=old?m->make<Node>(*old):m->make<Node>();m->copied.fetch_add(sizeof(Node));
        if(!level)n->page=std::move(page);
        else if(key&(std::size_t(1)<<(level-1)))n->right=replace(n->right,key,level-1,std::move(page),m);
        else n->left=replace(n->left,key,level-1,std::move(page),m);
        return n;
    }
    std::shared_ptr<const Page> pageAt(std::size_t key)const{
        auto n=root_;for(unsigned level=depth;level&&n;--level)
            n=key&(std::size_t(1)<<(level-1))?n->right:n->left;
        return n?n->page:nullptr;
    }
public:
    std::size_t size()const noexcept{return size_;}
    const T& at(std::size_t i)const{if(i>=size_)throw std::out_of_range("Unpublished series index");return pageAt(i/width)->values[i%width];}
    ImmutableSeries extend(const std::vector<T>& source,std::size_t end,const std::shared_ptr<MemoryLedger>& m)const{
        if(end<size_||end>source.size()||end>width*(std::size_t(1)<<depth))throw std::out_of_range("Series extent");
        auto result=*this;
        while(result.size_<end){
            const auto key=result.size_/width,offset=result.size_%width;
            auto old=result.pageAt(key);auto page=old?m->make<Page>(*old):m->make<Page>();
            m->copied.fetch_add(sizeof(Page));
            const auto n=std::min(width-offset,end-result.size_);
            std::copy_n(source.begin()+result.size_,n,page->values.begin()+offset);
            result.root_=replace(result.root_,key,depth,std::move(page),m);result.size_+=n;
        }
        return result;
    }
};
}

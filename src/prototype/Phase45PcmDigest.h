#pragma once
#include <CommonCrypto/CommonDigest.h>
#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
namespace ts::prototype {
class Phase45PcmDigest {
public:
    Phase45PcmDigest() { CC_SHA256_Init(&context_); }
    void update(const void* data,std::size_t bytes) {
        CC_SHA256_Update(&context_,data,static_cast<CC_LONG>(bytes));
    }
    std::string finish() {
        std::array<unsigned char,CC_SHA256_DIGEST_LENGTH> digest{};
        CC_SHA256_Final(digest.data(),&context_);
        std::string result;result.reserve(digest.size()*2);
        constexpr char hex[]="0123456789abcdef";
        for (const auto byte:digest) { result+=hex[byte>>4];result+=hex[byte&15]; }
        return result;
    }
private:
    CC_SHA256_CTX context_{};
};
}

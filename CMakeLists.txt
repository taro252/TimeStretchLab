cmake_minimum_required(VERSION 3.21)
project(TimeStretchLab VERSION 0.1 LANGUAGES CXX)

if(NOT APPLE)
    message(FATAL_ERROR "Phase 1 requires Apple Accelerate")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_library(ACCELERATE_FRAMEWORK Accelerate REQUIRED)
add_library(timestretch_core
    src/audio/WavReader.cpp
    src/audio/WavWriter.cpp
    src/dsp/FFTAccelerate.cpp
    src/dsp/STFT.cpp
    src/dsp/OverlapAdd.cpp
    src/dsp/PhaseVocoder.cpp
    src/dsp/PhaseLocker.cpp
    src/dsp/TransientDetector.cpp
    src/dsp/TimeStretchEngine.cpp
)
target_include_directories(timestretch_core PUBLIC src)
target_link_libraries(timestretch_core PUBLIC ${ACCELERATE_FRAMEWORK})
target_compile_options(timestretch_core PRIVATE -Wall -Wextra -Wpedantic)

add_executable(timestretch src/main.cpp)
target_link_libraries(timestretch PRIVATE timestretch_core)

add_executable(wav_metrics src/wav_metrics.cpp)
target_link_libraries(wav_metrics PRIVATE timestretch_core)

add_executable(wav_compare src/wav_compare.cpp)
target_link_libraries(wav_compare PRIVATE timestretch_core)

include(CTest)
if(BUILD_TESTING)
    add_executable(phase1_tests tests/Phase1Tests.cpp)
    target_link_libraries(phase1_tests PRIVATE timestretch_core)
    add_test(NAME phase1 COMMAND phase1_tests)

    add_executable(phase1_validation tests/Phase1Validation.cpp)
    target_link_libraries(phase1_validation PRIVATE timestretch_core)
    add_test(NAME phase1_validation COMMAND phase1_validation)

    add_executable(phase2_tests tests/Phase2Tests.cpp)
    target_link_libraries(phase2_tests PRIVATE timestretch_core)
    add_test(NAME phase2 COMMAND phase2_tests ${CMAKE_SOURCE_DIR}/results/phase1)

    add_executable(phase3_tests tests/Phase3Tests.cpp)
    target_link_libraries(phase3_tests PRIVATE timestretch_core)
    add_test(NAME phase3 COMMAND phase3_tests ${CMAKE_SOURCE_DIR}/results/phase2)
endif()

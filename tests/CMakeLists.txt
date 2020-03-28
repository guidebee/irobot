cmake_minimum_required(VERSION 3.12)
project(tests)

find_package(Catch2 CONFIG REQUIRED)

SET(TEST_SOURCE ${COMMON_SOURCES}
        all_tests.cpp
        test_buffer_util.cpp
        test_cbuf.cpp
        test_cli.cpp
        test_control_msg.cpp
        test_str_util.cpp
        test_queue.cpp)
add_executable(all_tests ${TEST_SOURCE})

target_link_libraries(all_tests PRIVATE Catch2::Catch2 FFmpeg)
target_link_libraries(all_tests PRIVATE SDL2::SDL2 SDL2::SDL2main)

if (WIN32)
    target_link_libraries(all_tests PRIVATE wsock32 ws2_32)
    install(TARGETS all_tests
            RUNTIME DESTINATION ${CMAKE_BINARY_DIR})
endif ()
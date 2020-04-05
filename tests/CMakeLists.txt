cmake_minimum_required(VERSION 3.12)
project(tests)

set(APP_TARGET all_tests)
find_package(Catch2 CONFIG REQUIRED)

SET(TEST_SOURCE ${COMMON_SOURCES}
        all_tests.cpp
        test_buffer_util.cpp
        test_cbuf.cpp
        test_cli.cpp
        test_control_msg.cpp
        test_str_util.cpp
        test_json.cpp
        test_opencv.cpp
        test_queue.cpp)
add_executable(${APP_TARGET} ${TEST_SOURCE})

target_link_libraries(${APP_TARGET} PRIVATE Catch2::Catch2 FFmpeg)
target_link_libraries(${APP_TARGET} PRIVATE SDL2::SDL2 SDL2::SDL2main)
target_link_libraries(${APP_TARGET} PRIVATE ${OpenCV_LIBS})
target_link_libraries(${APP_TARGET} PRIVATE nlohmann_json nlohmann_json::nlohmann_json)

if (WIN32)
    target_link_libraries(${APP_TARGET} PRIVATE wsock32 ws2_32)
    install(TARGETS ${APP_TARGET}
            RUNTIME DESTINATION ${CMAKE_CURRENT_BINARY_DIR})
endif ()
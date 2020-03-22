cmake_minimum_required(VERSION 3.12)

if (DEFINED ENV{VCPKG_ROOT} AND NOT DEFINED CMAKE_TOOLCHAIN_FILE)
    set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
            CACHE STRING "")
endif ()
set(VCPKG_TARGET_TRIPLET $ENV{VCPKG_DEFAULT_TRIPLET} CACHE INTERNAL "" FORCE)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS "-D__STDC_CONSTANT_MACROS")


project(Android_iRobot)

# -------------------------------------------------------------
# library dependencies
find_package(SDL2 CONFIG REQUIRED)
find_package(OpenCV REQUIRED)
add_subdirectory(src/libs)

# -------------------------------------------------------------
include_directories(${CMAKE_HOME_DIRECTORY}/src)
SET(COMMON_SOURCES ${CMAKE_HOME_DIRECTORY}/src/common.cpp)

# -------------------------------------------------------------
# utility functions
function(APP name)
    set(APP_TARGET ${name})
    add_executable(${APP_TARGET} ${COMMON_SOURCES}
            ${CMAKE_HOME_DIRECTORY}/src/${APP_TARGET}.cpp)
    target_link_libraries(${APP_TARGET} PRIVATE FFmpeg)
    target_link_libraries(${APP_TARGET} PRIVATE SDL2::SDL2 SDL2::SDL2main)
    target_link_libraries(${APP_TARGET} PRIVATE ${OpenCV_LIBS})

    if (WIN32)
        install(TARGETS ${name}
                RUNTIME DESTINATION ${CMAKE_BINARY_DIR})
    endif ()

endfunction(APP)

# -------------------------------------------------------------
# project sub directories
add_subdirectory(apps)
add_subdirectory(docs)
add_subdirectory(tests)












cmake_minimum_required(VERSION 3.12)
project(FFmpeg)

add_library(FFmpeg INTERFACE)

if (WIN32)
    set(FFMPEG_ROOT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/ffmpeg_x64-windows")

    find_path(AVCODEC_INCLUDE_DIR libavcodec/avcodec.h HINTS "${FFMPEG_ROOT_DIR}/include")
    find_library(AVCODEC_LIBRARY avcodec HINTS "${FFMPEG_ROOT_DIR}/lib")

    find_path(AVFORMAT_INCLUDE_DIR libavformat/avformat.h HINTS "${FFMPEG_ROOT_DIR}/include")
    find_library(AVFORMAT_LIBRARY avformat HINTS "${FFMPEG_ROOT_DIR}/lib")

    find_path(AVUTIL_INCLUDE_DIR libavutil/avutil.h HINTS "${FFMPEG_ROOT_DIR}/include")
    find_library(AVUTIL_LIBRARY avutil HINTS "${FFMPEG_ROOT_DIR}/lib")

    find_path(AVDEVICE_INCLUDE_DIR libavdevice/avdevice.h HINTS "${FFMPEG_ROOT_DIR}/include")
    find_library(AVDEVICE_LIBRARY avdevice HINTS "${FFMPEG_ROOT_DIR}/lib")

    find_path(SWSCALE_INCLUDE_DIR libswscale/swscale.h HINTS "${FFMPEG_ROOT_DIR}/include")
    find_library(SWSCALE_LIBRARY swscale HINTS "${FFMPEG_ROOT_DIR}/lib")

    find_path(AVFILTER_INCLUDE_DIR libavfilter/avfilter.h HINTS "${FFMPEG_ROOT_DIR}/include")
    find_library(AVFILTER_LIBRARY avfilter HINTS "${FFMPEG_ROOT_DIR}/lib")

    find_path(SWRESAMPLE_INCLUDE_DIR libswresample/swresample.h HINTS "${FFMPEG_ROOT_DIR}/include")
    find_library(SWRESAMPLE_LIBRARY swresample HINTS "${FFMPEG_ROOT_DIR}/lib")

    target_include_directories(FFmpeg INTERFACE
            ${AVCODEC_INCLUDE_DIR}
            ${AVFORMAT_INCLUDE_DIR}
            ${AVUTIL_INCLUDE_DIR}
            ${AVDEVICE_INCLUDE_DIR}
            ${SWSCALE_INCLUDE_DIR}
            ${AVFILTER_INCLUDE_DIR}
            ${SWRESAMPLE_INCLUDE_DIR}
    )

    target_link_libraries(FFmpeg INTERFACE
            ${AVCODEC_LIBRARY}
            ${AVFORMAT_LIBRARY}
            ${AVUTIL_LIBRARY}
            ${AVDEVICE_LIBRARY}
            ${SWSCALE_LIBRARY}
            ${AVFILTER_LIBRARY}
            ${SWRESAMPLE_LIBRARY}
    )
else ()
    # Linux/macOS: use system FFmpeg dev packages via pkg-config
    # (e.g. `apt install libavcodec-dev libavformat-dev libavutil-dev
    #  libavdevice-dev libswscale-dev libavfilter-dev libswresample-dev`)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(FFMPEG_PC REQUIRED IMPORTED_TARGET
            libavcodec
            libavformat
            libavutil
            libavdevice
            libswscale
            libavfilter
            libswresample
    )

    target_link_libraries(FFmpeg INTERFACE PkgConfig::FFMPEG_PC)
endif ()

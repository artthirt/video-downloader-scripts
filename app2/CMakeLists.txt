cmake_minimum_required(VERSION 3.16)
project(M3U8Downloader VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/Bin)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

# Find Qt6
find_package(Qt6 COMPONENTS Core Gui Widgets Svg REQUIRED)

# Windows: vcpkg.exe export ffmpeg --raw
# copy vcpkg-export-... to ./vcpkg-ffmpeg
list(APPEND CMAKE_PREFIX_PATH "${CMAKE_SOURCE_DIR}/vcpkg-ffmpeg/installed/x64-windows")

# Find FFmpeg via vcpkg or system
# vcpkg install ffmpeg[avcodec,avformat,avutil,swresample,swscale]:x64-windows
find_package(FFMPEG REQUIRED
    COMPONENTS
        avcodec
        avformat
        avutil
        swresample
        swscale
)

set(SOURCES
    main.cpp
    mainwindow.h
    ffmpegdecoder.h
    mainwindow.cpp
    ffmpegdecoder.cpp
    combowithplaceholder.h combowithplaceholder.cpp
    mainwindow.ui
    resources/icons.qrc
)

add_executable(${PROJECT_NAME} WIN32 MACOSX_BUNDLE
    ${SOURCES}
    filehistorycombo.h filehistorycombo.cpp
)

target_include_directories(${PROJECT_NAME} PRIVATE ${FFMPEG_INCLUDE_DIRS})

target_link_directories(${PROJECT_NAME} PRIVATE ${FFMPEG_LIBRARY_DIRS})

target_link_libraries(${PROJECT_NAME} PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::Svg
    ${FFMPEG_LIBRARIES}
)

# Windows specific
if(WIN32)
    target_compile_definitions(${PROJECT_NAME} PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
    
    # Copy FFmpeg DLLs to output directory
    # add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    #     COMMAND ${CMAKE_COMMAND} -E copy_if_different
    #         $<TARGET_RUNTIME_DLLS:${PROJECT_NAME}>
    #         $<TARGET_FILE_DIR:${PROJECT_NAME}>/
    # )
endif()

set_target_properties(${PROJECT_NAME} PROPERTIES
    WIN32_EXECUTABLE TRUE
    MACOSX_BUNDLE TRUE
)

install(TARGETS ${PROJECT_NAME}
    BUNDLE DESTINATION .
    RUNTIME DESTINATION bin
)

# CPack
set(CPACK_PACKAGE_NAME "M3U8 Downloader")
set(CPACK_PACKAGE_VERSION ${PROJECT_VERSION})
set(CPACK_GENERATOR "ZIP;NSIS")
include(CPack)

if(WIN32)

    set(runtime_dlls $<TARGET_RUNTIME_DLLS:${PROJECT_NAME}>)
    list(REMOVE_DUPLICATES runtime_dlls)

    add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${runtime_dlls}
            $<TARGET_FILE_DIR:${PROJECT_NAME}>
        COMMAND_EXPAND_LISTS)

    add_custom_command( TARGET ${PROJECT_NAME} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy
            $<TARGET_RUNTIME_DLLS:${PROJECT_NAME}>
            $<TARGET_FILE_DIR:${PROJECT_NAME}>
        # COMMAND ${CMAKE_COMMAND} -E copy_if_different
        #     ${OpenCV_DIR}/../bin/opencv_videoio_msmf${OCV_VER}_64.dll
        #     $<TARGET_FILE_DIR:${PROJECT_NAME}>
        # COMMAND ${CMAKE_COMMAND} -E copy_if_different
        #     $<TARGET_FILE:Qt${QT_VERSION_MAJOR}::QTgaPlugin>
        #     $<TARGET_FILE_DIR:${PROJECT_NAME}>/imageformats/
        COMMAND_EXPAND_LISTS)
endif()

get_filename_component(QT_BIN_DIR "${Qt6Core_DIR}/../../../bin" ABSOLUTE)
message(STATUS "-- qt: ${QT_BIN_DIR} --")

if(WIN32)
    add_custom_command( TARGET ${PROJECT_NAME} POST_BUILD
      COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:${PROJECT_NAME}>/platforms
      COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:${PROJECT_NAME}>/styles/
      COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:${PROJECT_NAME}>/iconengines/
      COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:${PROJECT_NAME}>/imageformats/
      COMMAND ${CMAKE_COMMAND} -E copy_if_different
          ${QT_BIN_DIR}/../plugins/platforms/qwindows.dll
          $<TARGET_FILE_DIR:${PROJECT_NAME}>/platforms
      COMMAND ${CMAKE_COMMAND} -E copy_if_different
          ${QT_BIN_DIR}/../plugins/platforms/qwindowsd.dll
          $<TARGET_FILE_DIR:${PROJECT_NAME}>/platforms
      # COMMAND ${CMAKE_COMMAND} -E copy_if_different
      #     $<TARGET_FILE:Qt${QT_VERSION_MAJOR}::QWindowsIntegrationPlugin>
      #     $<TARGET_FILE_DIR:${PROJECT_NAME}>/platforms/
      # COMMAND ${CMAKE_COMMAND} -E copy_if_different
      #     $<TARGET_FILE:Qt${QT_VERSION_MAJOR}::QModernWindowsStylePlugin>
      #     $<TARGET_FILE_DIR:${PROJECT_NAME}>/styles/
      # COMMAND ${CMAKE_COMMAND} -E copy_if_different
      #     $<TARGET_FILE:Qt${QT_VERSION_MAJOR}::QSvgPlugin>
      #     $<TARGET_FILE_DIR:${PROJECT_NAME}>/imageformats/
      # COMMAND ${CMAKE_COMMAND} -E copy_if_different
      #     $<TARGET_FILE:Qt${QT_VERSION_MAJOR}::QJpegPlugin>
      #     $<TARGET_FILE_DIR:${PROJECT_NAME}>/imageformats/
      # COMMAND ${CMAKE_COMMAND} -E copy_if_different
      #     $<TARGET_FILE:Qt${QT_VERSION_MAJOR}::QTiffPlugin>
      #     $<TARGET_FILE_DIR:${PROJECT_NAME}>/imageformats/
      COMMAND_EXPAND_LISTS)
endif()
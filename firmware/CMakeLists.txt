cmake_minimum_required(VERSION 3.13...3.27)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
# Pico SDK source uses GNU C extensions such as `asm`; keep the project in GNU C11 mode.
set(CMAKE_C_EXTENSIONS ON)

set(PICO_BOARD_HEADER_DIRS "${CMAKE_CURRENT_LIST_DIR}/boards")
set(PICO_BOARD waveshare_rp2350_touch_amoled_2.41 CACHE STRING "Board definition")

# pico_sdk_import.cmake resolves PICO_SDK_PATH before project().
include(pico_sdk_import.cmake)

file(READ "${CMAKE_CURRENT_LIST_DIR}/../VERSION" RPD_RELEASE_VERSION)
string(STRIP "${RPD_RELEASE_VERSION}" RPD_RELEASE_VERSION)
string(REGEX MATCH "^([0-9]+)\\.([0-9]+)\\.([0-9]+)(\\.dev[0-9]+)?$"
    RPD_RELEASE_VERSION_FORMAT "${RPD_RELEASE_VERSION}")
if (NOT RPD_RELEASE_VERSION_FORMAT)
    message(FATAL_ERROR "VERSION must contain a release or development version such as 1.2.17 or 1.2.17.dev0")
endif()
set(RPD_RELEASE_VERSION_CORE "${CMAKE_MATCH_1}.${CMAKE_MATCH_2}.${CMAKE_MATCH_3}")

project(rp2350_remote_display_firmware VERSION "${RPD_RELEASE_VERSION_CORE}" LANGUAGES C CXX ASM)

pico_sdk_init()

if (NOT TARGET tinyusb_device)
    message(FATAL_ERROR
        "TinyUSB device support is unavailable. Initialize the required Pico SDK submodule, for example: git submodule update --init lib/tinyusb")
endif()

set(RPD_UNIFONT_ASSET "${CMAKE_CURRENT_LIST_DIR}/assets/unifont_all-17.0.04.bin")
if (NOT EXISTS "${RPD_UNIFONT_ASSET}")
    message(FATAL_ERROR "The committed GNU Unifont binary asset is missing: ${RPD_UNIFONT_ASSET}")
endif()
file(TO_CMAKE_PATH "${RPD_UNIFONT_ASSET}" RPD_UNIFONT_ASM_PATH)
configure_file(
    "${CMAKE_CURRENT_LIST_DIR}/firmware/builtin_font_data.S.in"
    "${CMAKE_CURRENT_BINARY_DIR}/builtin_font_data.S"
    @ONLY
)

# USB bcdDevice contains four BCD digits. The project convention packs a one-digit
# major, one-digit minor, and one- or two-digit patch release into that field.
# For example, project version 1.2.17.dev0 maps to USB release code 0x1217.
string(REGEX MATCH "^([0-9])\\.([0-9])\\.([0-9][0-9]?)$"
    RPD_RELEASE_VERSION_BCD_FORMAT "${RPD_RELEASE_VERSION_CORE}")
if (NOT RPD_RELEASE_VERSION_BCD_FORMAT)
    message(FATAL_ERROR
        "VERSION must use one-digit major/minor and a one- or two-digit patch release for USB bcdDevice encoding")
endif()
set(RPD_USB_BCD_MAJOR "${CMAKE_MATCH_1}")
set(RPD_USB_BCD_MINOR "${CMAKE_MATCH_2}")
set(RPD_USB_BCD_PATCH "${CMAKE_MATCH_3}")
string(LENGTH "${RPD_USB_BCD_PATCH}" RPD_USB_BCD_PATCH_LENGTH)
if (RPD_USB_BCD_PATCH_LENGTH EQUAL 1)
    set(RPD_USB_BCD_PATCH "0${RPD_USB_BCD_PATCH}")
endif()
set(RPD_USB_BCD_DEVICE_DEFAULT "0x${RPD_USB_BCD_MAJOR}${RPD_USB_BCD_MINOR}${RPD_USB_BCD_PATCH}")

set(RPD_SYS_CLOCK_KHZ 250000 CACHE STRING
    "RP2350 system clock in kHz (use 150000 as a conservative fallback)")
set(RPD_PSRAM_MAX_SCK_HZ 133000000 CACHE STRING
    "PSRAM target ceiling in Hz (use 109000000 for the data-sheet limit)")
set(RPD_USB_VID 0xCAFE CACHE STRING "USB vendor ID as a C integer literal")
set(RPD_USB_PID 0x4010 CACHE STRING "USB product ID as a C integer literal")
set(RPD_USB_BCD_DEVICE "${RPD_USB_BCD_DEVICE_DEFAULT}" CACHE STRING
    "USB bcdDevice release code derived from VERSION" FORCE)

if (NOT RPD_SYS_CLOCK_KHZ MATCHES "^[0-9]+$")
    message(FATAL_ERROR "RPD_SYS_CLOCK_KHZ must be an integer number of kHz")
endif()
if (RPD_SYS_CLOCK_KHZ LESS 120000 OR RPD_SYS_CLOCK_KHZ GREATER 250000)
    message(FATAL_ERROR "RPD_SYS_CLOCK_KHZ must be between 120000 and 250000 kHz")
endif()
message(STATUS "RP2350 system clock: ${RPD_SYS_CLOCK_KHZ} kHz")
if (NOT RPD_PSRAM_MAX_SCK_HZ MATCHES "^[0-9]+$")
    message(FATAL_ERROR "RPD_PSRAM_MAX_SCK_HZ must be an integer number of Hz")
endif()
if (RPD_PSRAM_MAX_SCK_HZ LESS 50000000 OR RPD_PSRAM_MAX_SCK_HZ GREATER 133000000)
    message(FATAL_ERROR "RPD_PSRAM_MAX_SCK_HZ must be between 50000000 and 133000000 Hz")
endif()
message(STATUS "PSRAM target ceiling: ${RPD_PSRAM_MAX_SCK_HZ} Hz")
if (RPD_PSRAM_MAX_SCK_HZ GREATER 109000000)
    message(WARNING
        "The default PSRAM target is performance-tuned above the 109 MHz data-sheet limit. "
        "Use -DRPD_PSRAM_MAX_SCK_HZ=109000000 if stability is preferred.")
endif()

add_executable(rp2350_remote_display
    firmware/main.c
    firmware/remote_protocol.c
    firmware/rtc_pcf85063.c
    firmware/renderer.c
    firmware/builtin_font.c
    ${CMAKE_CURRENT_BINARY_DIR}/builtin_font_data.S
    firmware/resource_cache.c
    firmware/usb_descriptors.c

    drivers/waveshare/board/DEV_Config.c
    drivers/waveshare/qspi/qspi_pio.c
    drivers/waveshare/amoled/AMOLED_2in41.c
    drivers/waveshare/touch/FT6336U.c

    drivers/psram/rp_pico_alloc.c
    drivers/psram/tlsf/tlsf.c
)

# Generates qspi.pio.h into the build directory. It is intentionally not tracked.
pico_generate_pio_header(rp2350_remote_display
    ${CMAKE_CURRENT_LIST_DIR}/drivers/waveshare/qspi/qspi.pio
)

target_include_directories(rp2350_remote_display PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/firmware
    ${CMAKE_CURRENT_LIST_DIR}/drivers/waveshare/board
    ${CMAKE_CURRENT_LIST_DIR}/drivers/waveshare/qspi
    ${CMAKE_CURRENT_LIST_DIR}/drivers/waveshare/amoled
    ${CMAKE_CURRENT_LIST_DIR}/drivers/waveshare/touch
    ${CMAKE_CURRENT_LIST_DIR}/drivers/psram
    ${CMAKE_CURRENT_LIST_DIR}/drivers/psram/tlsf
    ${CMAKE_CURRENT_BINARY_DIR}
)

target_compile_definitions(rp2350_remote_display PRIVATE
    RPD_SYS_CLOCK_KHZ=${RPD_SYS_CLOCK_KHZ}u
    RPD_PSRAM_MAX_SCK_HZ=${RPD_PSRAM_MAX_SCK_HZ}u
    RPD_USB_VID=${RPD_USB_VID}u
    RPD_USB_PID=${RPD_USB_PID}u
    RPD_USB_BCD_DEVICE=${RPD_USB_BCD_DEVICE}u
)

target_compile_options(rp2350_remote_display PRIVATE
    -Wall
    -Wextra
    -Wshadow
    -Wformat=2
)

if (CMAKE_BUILD_TYPE STREQUAL "Release" OR CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")
    target_compile_options(rp2350_remote_display PRIVATE -O2)
endif()

target_link_libraries(rp2350_remote_display PRIVATE
    pico_stdlib
    tinyusb_device
    tinyusb_board
    hardware_adc
    hardware_dma
    hardware_gpio
    hardware_i2c
    hardware_pio
    hardware_pwm
    hardware_spi
    hardware_watchdog
    hardware_clocks
    hardware_flash
    hardware_exception
    hardware_sync
    pico_flash
    pico_unique_id
)

pico_set_program_name(rp2350_remote_display "RP2350 Remote Display")
pico_set_program_version(rp2350_remote_display "${RPD_RELEASE_VERSION}")
pico_enable_stdio_uart(rp2350_remote_display 0)
pico_enable_stdio_usb(rp2350_remote_display 0)
pico_add_extra_outputs(rp2350_remote_display)

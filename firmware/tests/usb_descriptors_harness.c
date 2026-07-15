#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "tusb.h"
#include "pico/unique_id.h"

static uint8_t captured_rhport;
static tusb_control_request_t const *captured_request;
static void *captured_buffer;
static uint16_t captured_length;

bool tud_control_xfer(uint8_t rhport,
                      tusb_control_request_t const *request,
                      void *buffer,
                      uint16_t length)
{
    captured_rhport = rhport;
    captured_request = request;
    captured_buffer = buffer;
    captured_length = length;
    return true;
}

void pico_get_unique_board_id_string(char *id_out, uint len)
{
    const char serial[] = "0011223344556677";
    assert(len >= sizeof(serial));
    memcpy(id_out, serial, sizeof(serial));
}

/* Include the production descriptor implementation in this translation unit so
 * the harness checks the exact byte arrays compiled into the firmware. */
#include "../firmware/usb_descriptors.c"

static uint16_t read_u16_le(uint8_t const *bytes)
{
    return (uint16_t)(bytes[0] | ((uint16_t)bytes[1] << 8));
}

static uint32_t read_u32_le(uint8_t const *bytes)
{
    return (uint32_t)bytes[0] |
           ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16) |
           ((uint32_t)bytes[3] << 24);
}

static void test_single_vendor_interface(void)
{
    tusb_desc_device_t const *device =
        (tusb_desc_device_t const *)tud_descriptor_device_cb();
    uint8_t const *configuration = tud_descriptor_configuration_cb(0u);

    assert(device->bLength == 18u);
    assert(device->bDescriptorType == TUSB_DESC_DEVICE);
    assert(device->bcdUSB == 0x0210u);
    assert(device->bDeviceClass == 0u);
    assert(device->bNumConfigurations == 1u);

    assert(configuration[0] == 9u);
    assert(configuration[1] == TUSB_DESC_CONFIGURATION);
    assert(read_u16_le(&configuration[2]) == sizeof(configuration_descriptor));
    assert(configuration[4] == 1u);
    assert(configuration[9] == 9u);
    assert(configuration[10] == TUSB_DESC_INTERFACE);
    assert(configuration[11] == 0u);
    assert(configuration[13] == 2u);
    assert(configuration[14] == TUSB_CLASS_VENDOR_SPECIFIC);
    assert(configuration[18] == 7u);
    assert(configuration[19] == TUSB_DESC_ENDPOINT);
    assert(configuration[20] == 0x01u);
    assert(configuration[21] == TUSB_XFER_BULK);
    assert(read_u16_le(&configuration[22]) == 64u);
    assert(configuration[25] == 7u);
    assert(configuration[26] == TUSB_DESC_ENDPOINT);
    assert(configuration[27] == 0x81u);
    assert(configuration[28] == TUSB_XFER_BULK);
    assert(read_u16_le(&configuration[29]) == 64u);
}

static void test_bos_platform_capability(void)
{
    static uint8_t const microsoft_platform_uuid[] = {
        0xDFu, 0x60u, 0xDDu, 0xD8u, 0x89u, 0x45u, 0xC7u, 0x4Cu,
        0x9Cu, 0xD2u, 0x65u, 0x9Du, 0x9Eu, 0x64u, 0x8Au, 0x9Fu,
    };
    uint8_t const *bos = tud_descriptor_bos_cb();

    assert(sizeof(bos_descriptor) == 33u);
    assert(bos[0] == 5u);
    assert(bos[1] == TUSB_DESC_BOS);
    assert(read_u16_le(&bos[2]) == sizeof(bos_descriptor));
    assert(bos[4] == 1u);
    assert(bos[5] == 28u);
    assert(bos[6] == TUSB_DESC_DEVICE_CAPABILITY);
    assert(bos[7] == DEVICE_CAPABILITY_PLATFORM);
    assert(memcmp(&bos[9], microsoft_platform_uuid, sizeof(microsoft_platform_uuid)) == 0);
    assert(read_u32_le(&bos[25]) == 0x06030000u);
    assert(read_u16_le(&bos[29]) == sizeof(ms_os_20_descriptor));
    assert(bos[31] == RPD_MS_OS_20_VENDOR_CODE);
    assert(bos[32] == 0u);
}

static void test_ms_os_20_single_function_descriptor_set(void)
{
    static uint8_t const expected_name[] = {
        'D', 0, 'e', 0, 'v', 0, 'i', 0, 'c', 0, 'e', 0,
        'I', 0, 'n', 0, 't', 0, 'e', 0, 'r', 0, 'f', 0,
        'a', 0, 'c', 0, 'e', 0, 'G', 0, 'U', 0, 'I', 0,
        'D', 0, 's', 0, 0, 0,
    };
    static uint8_t const expected_guid[] = {
        '{', 0, '7', 0, '0', 0, 'A', 0, '0', 0, '5', 0, '9', 0,
        '7', 0, 'B', 0, '-', 0, 'D', 0, '8', 0, 'E', 0, '4', 0,
        '-', 0, '4', 0, '5', 0, '8', 0, '0', 0, '-', 0, '8', 0,
        '2', 0, '0', 0, '1', 0, '-', 0, '7', 0, '3', 0, 'B', 0,
        '3', 0, 'B', 0, '5', 0, 'E', 0, '4', 0, '7', 0, '5', 0,
        '8', 0, '1', 0, '}', 0, 0, 0, 0, 0,
    };
    uint8_t const *descriptor = ms_os_20_descriptor;

    assert(sizeof(ms_os_20_descriptor) == 0xA2u);
    assert(read_u16_le(&descriptor[0]) == 10u);
    assert(read_u16_le(&descriptor[2]) == MS_OS_20_SET_HEADER_DESCRIPTOR);
    assert(read_u32_le(&descriptor[4]) == 0x06030000u);
    assert(read_u16_le(&descriptor[8]) == sizeof(ms_os_20_descriptor));

    /* A non-composite device uses a device-level compatible-ID feature with
     * no configuration/function subset headers. */
    assert(read_u16_le(&descriptor[10]) == 20u);
    assert(read_u16_le(&descriptor[12]) == MS_OS_20_FEATURE_COMPATBLE_ID);
    assert(memcmp(&descriptor[14], "WINUSB\0\0", 8u) == 0);
    for (size_t index = 22u; index < 30u; ++index) {
        assert(descriptor[index] == 0u);
    }

    assert(read_u16_le(&descriptor[30]) == 132u);
    assert(read_u16_le(&descriptor[32]) == MS_OS_20_FEATURE_REG_PROPERTY);
    assert(read_u16_le(&descriptor[34]) == 7u);
    assert(read_u16_le(&descriptor[36]) == sizeof(expected_name));
    assert(memcmp(&descriptor[38], expected_name, sizeof(expected_name)) == 0);
    assert(read_u16_le(&descriptor[80]) == sizeof(expected_guid));
    assert(memcmp(&descriptor[82], expected_guid, sizeof(expected_guid)) == 0);
}

static void test_vendor_request_routing(void)
{
    tusb_control_request_t request = {
        .bmRequestType = 0xC0u,
        .bRequest = RPD_MS_OS_20_VENDOR_CODE,
        .wValue = 0u,
        .wIndex = 7u,
        .wLength = UINT16_MAX,
    };

    captured_buffer = NULL;
    captured_length = 0u;
    assert(tud_vendor_control_xfer_cb(1u, CONTROL_STAGE_SETUP, &request));
    assert(captured_rhport == 1u);
    assert(captured_request == &request);
    assert(captured_buffer == ms_os_20_descriptor);
    assert(captured_length == sizeof(ms_os_20_descriptor));

    request.wIndex = 6u;
    assert(!tud_vendor_control_xfer_cb(1u, CONTROL_STAGE_SETUP, &request));
    request.wIndex = 7u;
    request.bmRequestType = 0x40u;
    assert(!tud_vendor_control_xfer_cb(1u, CONTROL_STAGE_SETUP, &request));
    assert(tud_vendor_control_xfer_cb(1u, 2u, &request));
}

int main(void)
{
    test_single_vendor_interface();
    test_bos_platform_capability();
    test_ms_os_20_single_function_descriptor_set();
    test_vendor_request_routing();
    puts("USB descriptor harness passed");
    return 0;
}

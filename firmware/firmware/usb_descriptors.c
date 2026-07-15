#include "tusb.h"

#include <stdint.h>
#include <string.h>

#include "pico/unique_id.h"

#include "usb_descriptors.h"

enum {
    ITF_NUM_VENDOR = 0,
    ITF_NUM_TOTAL,
};

#define EPNUM_VENDOR_OUT 0x01u
#define EPNUM_VENDOR_IN  0x81u
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_VENDOR_DESC_LEN)

/*
 * Windows 8.1 and later can bind WinUSB without an INF file when a device
 * exposes a Microsoft OS 2.0 descriptor set from its BOS descriptor. Keep the
 * vendor code private to USB enumeration; the display protocol still uses the
 * two bulk endpoints below.
 */
#define RPD_MS_OS_20_VENDOR_CODE 0x20u
#define RPD_MS_OS_20_DESC_LEN    0xA2u
#define RPD_BOS_TOTAL_LEN        (TUD_BOS_DESC_LEN + TUD_BOS_MICROSOFT_OS_DESC_LEN)

static const tusb_desc_device_t device_descriptor = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0210,
    .bDeviceClass = 0x00,
    .bDeviceSubClass = 0x00,
    .bDeviceProtocol = 0x00,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = RPD_USB_VID,
    .idProduct = RPD_USB_PID,
    .bcdDevice = RPD_USB_BCD_DEVICE,
    .iManufacturer = 0x01,
    .iProduct = 0x02,
    .iSerialNumber = 0x03,
    .bNumConfigurations = 0x01,
};

static const uint8_t configuration_descriptor[] = {
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    TUD_VENDOR_DESCRIPTOR(ITF_NUM_VENDOR, 4, EPNUM_VENDOR_OUT, EPNUM_VENDOR_IN, 64),
};

static const uint8_t bos_descriptor[] = {
    TUD_BOS_DESCRIPTOR(RPD_BOS_TOTAL_LEN, 1),
    TUD_BOS_MS_OS_20_DESCRIPTOR(RPD_MS_OS_20_DESC_LEN, RPD_MS_OS_20_VENDOR_CODE),
};

_Static_assert(sizeof(bos_descriptor) == RPD_BOS_TOTAL_LEN,
               "BOS descriptor length is incorrect");

/*
 * Microsoft OS 2.0 descriptor set for this non-composite device. The compatible
 * ID asks Windows to load WinUSB. DeviceInterfaceGUIDs gives applications a
 * stable interface class to enumerate without a project-specific INF file.
 *
 * Project interface GUID: {70A0597B-D8E4-4580-8201-73B3B5E47581}
 */
static const uint8_t ms_os_20_descriptor[] = {
    /* Set header: Windows 8.1+, total descriptor-set length. */
    U16_TO_U8S_LE(0x000A), U16_TO_U8S_LE(MS_OS_20_SET_HEADER_DESCRIPTOR),
    U32_TO_U8S_LE(0x06030000), U16_TO_U8S_LE(RPD_MS_OS_20_DESC_LEN),

    /* Device-level compatible ID descriptor: WINUSB. */
    U16_TO_U8S_LE(0x0014), U16_TO_U8S_LE(MS_OS_20_FEATURE_COMPATBLE_ID),
    'W', 'I', 'N', 'U', 'S', 'B', 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,

    /* Registry property: DeviceInterfaceGUIDs (REG_MULTI_SZ). */
    U16_TO_U8S_LE(0x0084), U16_TO_U8S_LE(MS_OS_20_FEATURE_REG_PROPERTY),
    U16_TO_U8S_LE(0x0007), U16_TO_U8S_LE(0x002A),
    'D', 0x00, 'e', 0x00, 'v', 0x00, 'i', 0x00, 'c', 0x00,
    'e', 0x00, 'I', 0x00, 'n', 0x00, 't', 0x00, 'e', 0x00,
    'r', 0x00, 'f', 0x00, 'a', 0x00, 'c', 0x00, 'e', 0x00,
    'G', 0x00, 'U', 0x00, 'I', 0x00, 'D', 0x00, 's', 0x00,
    0x00, 0x00,
    U16_TO_U8S_LE(0x0050),
    '{', 0x00, '7', 0x00, '0', 0x00, 'A', 0x00, '0', 0x00,
    '5', 0x00, '9', 0x00, '7', 0x00, 'B', 0x00, '-', 0x00,
    'D', 0x00, '8', 0x00, 'E', 0x00, '4', 0x00, '-', 0x00,
    '4', 0x00, '5', 0x00, '8', 0x00, '0', 0x00, '-', 0x00,
    '8', 0x00, '2', 0x00, '0', 0x00, '1', 0x00, '-', 0x00,
    '7', 0x00, '3', 0x00, 'B', 0x00, '3', 0x00, 'B', 0x00,
    '5', 0x00, 'E', 0x00, '4', 0x00, '7', 0x00, '5', 0x00,
    '8', 0x00, '1', 0x00, '}', 0x00, 0x00, 0x00, 0x00, 0x00,
};

_Static_assert(sizeof(ms_os_20_descriptor) == RPD_MS_OS_20_DESC_LEN,
               "Microsoft OS 2.0 descriptor length is incorrect");

static const char *string_descriptors[] = {
    (const char[]){0x09, 0x04},
    "RP2350",
    "RP2350 Remote Display",
    NULL, /* Stable board ID, generated in tud_descriptor_string_cb(). */
    "Display transport",
};

const uint8_t *tud_descriptor_device_cb(void)
{
    return (const uint8_t *)&device_descriptor;
}

const uint8_t *tud_descriptor_configuration_cb(uint8_t index)
{
    (void)index;
    return configuration_descriptor;
}

const uint8_t *tud_descriptor_bos_cb(void)
{
    return bos_descriptor;
}

bool tud_vendor_control_xfer_cb(uint8_t rhport,
                                uint8_t stage,
                                tusb_control_request_t const *request)
{
    if (stage != CONTROL_STAGE_SETUP) {
        return true;
    }
    if (request->bmRequestType_bit.direction != TUSB_DIR_IN ||
        request->bmRequestType_bit.type != TUSB_REQ_TYPE_VENDOR ||
        request->bmRequestType_bit.recipient != TUSB_REQ_RCPT_DEVICE ||
        request->bRequest != RPD_MS_OS_20_VENDOR_CODE ||
        request->wValue != 0x0000u ||
        request->wIndex != 0x0007u) {
        return false;
    }
    return tud_control_xfer(rhport,
                            request,
                            (void *)(uintptr_t)ms_os_20_descriptor,
                            (uint16_t)sizeof(ms_os_20_descriptor));
}

const uint16_t *tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
    static uint16_t descriptor[32];
    (void)langid;

    uint8_t length = 0;
    if (index == 0) {
        descriptor[1] = 0x0409;
        length = 1;
    } else {
        if (index >= TU_ARRAY_SIZE(string_descriptors)) {
            return NULL;
        }

        char serial[PICO_UNIQUE_BOARD_ID_SIZE_BYTES * 2u + 1u];
        const char *ascii = string_descriptors[index];
        if (index == 3u) {
            pico_get_unique_board_id_string(serial, (uint)sizeof(serial));
            ascii = serial;
        }
        if (ascii == NULL) {
            return NULL;
        }
        while (ascii[length] != '\0' && length < (TU_ARRAY_SIZE(descriptor) - 1u)) {
            descriptor[1u + length] = (uint8_t)ascii[length];
            ++length;
        }
    }

    descriptor[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2u * length + 2u));
    return descriptor;
}

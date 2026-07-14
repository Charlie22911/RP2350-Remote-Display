#include "tusb.h"

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

static const tusb_desc_device_t device_descriptor = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
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

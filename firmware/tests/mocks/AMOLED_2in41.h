#ifndef RPD_TEST_AMOLED_2IN41_H
#define RPD_TEST_AMOLED_2IN41_H

#include <stdbool.h>
#include <stdint.h>

typedef uint16_t UWORD;
typedef enum {
    AMOLED_2IN41_TRANSFER_IDLE = 0,
    AMOLED_2IN41_TRANSFER_ACTIVE = 1,
    AMOLED_2IN41_TRANSFER_COMPLETE = 2,
    AMOLED_2IN41_TRANSFER_ERROR = 3,
} AMOLED_2IN41_TRANSFER_STATUS;

void AMOLED_2IN41_SetBrightness(uint8_t brightness);
bool AMOLED_2IN41_TransferActive(void);
AMOLED_2IN41_TRANSFER_STATUS AMOLED_2IN41_PollTransfer(void);
void AMOLED_2IN41_CancelTransfer(void);
bool AMOLED_2IN41_BeginFullWidthRows(uint32_t start_y, uint32_t end_y, const UWORD *image);

#endif

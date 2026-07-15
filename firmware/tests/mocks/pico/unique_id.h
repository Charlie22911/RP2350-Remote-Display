#ifndef RPD_TEST_MOCK_PICO_UNIQUE_ID_H
#define RPD_TEST_MOCK_PICO_UNIQUE_ID_H

#include <stddef.h>

typedef unsigned int uint;

#define PICO_UNIQUE_BOARD_ID_SIZE_BYTES 8u

void pico_get_unique_board_id_string(char *id_out, uint len);

#endif

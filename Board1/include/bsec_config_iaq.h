#pragma once

#include <stdint.h>

const uint8_t bsec_config_iaq[] = {
  #include "bsec_iaq.txt"
};
const uint32_t bsec_config_iaq_len = sizeof(bsec_config_iaq);

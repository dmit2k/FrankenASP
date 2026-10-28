#ifndef FRANKENASP_CFG2_H
#define FRANKENASP_CFG2_H

/* Independent ASP2 CFG2/TLV decoder. No Bionic, vendor ABI or Python dependency. */
#include <stddef.h>
#include <stdint.h>

#define CFG2_MAX_BYTES 8192u
#define CFG2_MAX_TLVS 64u
#define CFG2_MAX_MIC 16u
#define CFG2_MAX_REF 8u
#define CFG2_MAX_CODENAME 32u
#define CFG2_MAX_PCM_PAYLOAD 262144u

typedef enum cfg2_error {
    CFG2_OK = 0,
    CFG2_ERR_ARGUMENT,
    CFG2_ERR_HEADER,
    CFG2_ERR_LENGTH,
    CFG2_ERR_FLAGS,
    CFG2_ERR_TLV,
    CFG2_ERR_REQUIRED,
    CFG2_ERR_STREAM,
    CFG2_ERR_PLATFORM,
    CFG2_ERR_GAIN
} cfg2_error;

typedef struct cfg2_stream {
    uint16_t channels;
    uint16_t frames;
    uint32_t rate;
    uint8_t format;
    uint8_t full_bits;
    uint8_t alignment;
    uint8_t valid_bits;
} cfg2_stream;

typedef struct cfg2_platform {
    uint8_t present;
    uint8_t detection; /* 1 confirmed, 2 inferred */
    uint8_t codename_length;
    char codename[CFG2_MAX_CODENAME + 1u]; /* owned, NUL-terminated */
} cfg2_platform;

typedef struct cfg2_gain {
    uint8_t present; /* absent TLV distinct from explicit NONE */
    uint8_t encoding;
    uint8_t availability; /* 0 NONE, 1 COMPLETE, 2 PARTIAL */
    uint8_t provenance;
    uint8_t applied_to_pcm; /* always 0 in v1 */
    uint16_t mic_channels;
    uint32_t present_mask;
    int64_t coefficients[CFG2_MAX_MIC]; /* owned, captured-slot order */
} cfg2_gain;

typedef struct cfg2_descriptor {
    uint32_t stream_flags;
    uint32_t mic_bytes;
    uint32_t ref_bytes;
    cfg2_stream mic;
    cfg2_stream ref;
    cfg2_platform platform;
    cfg2_gain gain;
} cfg2_descriptor;

/*
 * Validate exactly n bytes; reject trailing bytes and old fixed 40-byte CFG2.
 * On failure, *out is completely zeroed (no partly validated state).
 * No pointers into the input are stored; no allocation and no I/O.
 */
cfg2_error cfg2_decode(const uint8_t *bytes, size_t n, cfg2_descriptor *out);
const char *cfg2_error_string(cfg2_error error);

#endif

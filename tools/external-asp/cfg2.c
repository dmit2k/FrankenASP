#include "cfg2.h"

#ifdef ASP2_BIONIC
#include "platform.h"
#else
#include <string.h>
#endif

static uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t rd64(const uint8_t *p)
{
    return (uint64_t)rd32(p) | ((uint64_t)rd32(p + 4) << 32);
}

static cfg2_error decode_stream(const uint8_t *p, size_t n, cfg2_stream *s)
{
    if (n != 16u || rd32(p + 12) != 0u)
        return CFG2_ERR_STREAM;
    s->channels = rd16(p);
    s->frames = rd16(p + 2);
    s->rate = rd32(p + 4);
    s->format = p[8];
    s->full_bits = p[9];
    s->alignment = p[10];
    s->valid_bits = p[11];
    return CFG2_OK;
}

static cfg2_error check_stream(const cfg2_stream *s, uint16_t limit, uint32_t *len)
{
    uint8_t width;
    uint64_t payload;
    if (s->channels < 1u || s->channels > limit ||
        s->rate < 8000u || s->rate > 192000u ||
        s->rate % 50u != 0u || (uint32_t)s->frames != s->rate / 50u)
        return CFG2_ERR_STREAM;
    if (s->format == 1u)
        width = 16u;
    else if (s->format == 2u)
        width = 32u;
    else
        return CFG2_ERR_STREAM;
    if (s->valid_bits < 2u || s->valid_bits > width || s->alignment > 1u ||
        s->full_bits != (uint8_t)(s->alignment ? width - 1u : s->valid_bits - 1u))
        return CFG2_ERR_STREAM;
    payload = (uint64_t)s->frames * (uint64_t)s->channels * (uint64_t)(width / 8u);
    if (payload > CFG2_MAX_PCM_PAYLOAD)
        return CFG2_ERR_STREAM;
    *len = (uint32_t)payload;
    return CFG2_OK;
}

static cfg2_error decode_platform(const uint8_t *p, size_t n, cfg2_platform *platform)
{
    size_t i;
    uint8_t count;
    if (n < 4u || p[0] != 1u || (p[1] != 1u && p[1] != 2u) ||
        p[3] != 0u)
        return CFG2_ERR_PLATFORM;
    count = p[2];
    if (count == 0u || count > CFG2_MAX_CODENAME || n != 4u + (size_t)count)
        return CFG2_ERR_PLATFORM;
    for (i = 0; i < count; i++) {
        uint8_t x = p[4u + i];
        if (!((x >= 'a' && x <= 'z') || (x >= '0' && x <= '9') ||
              x == '-' || x == '_'))
            return CFG2_ERR_PLATFORM;
    }
    platform->present = 1u;
    platform->detection = p[1];
    platform->codename_length = count;
    memcpy(platform->codename, p + 4, count);
    platform->codename[count] = '\0';
    return CFG2_OK;
}

static cfg2_error decode_gain(const uint8_t *p, size_t n,
                              uint16_t mic_channels, cfg2_gain *gain)
{
    uint8_t encoding, availability, provenance;
    uint32_t mask, all;
    size_t i, expected;
    if (n < 16u || rd16(p) != 1u || p[5] != 0u || rd32(p + 12) != 0u ||
        mic_channels == 0u || mic_channels > CFG2_MAX_MIC ||
        rd16(p + 6) != mic_channels)
        return CFG2_ERR_GAIN;
    encoding = p[2];
    availability = p[3];
    provenance = p[4];
    mask = rd32(p + 8);
    all = (UINT32_C(1) << mic_channels) - UINT32_C(1);
    if ((mask & ~all) != 0u)
        return CFG2_ERR_GAIN;
    if (availability == 0u) {
        if (encoding != 0u || provenance != 0u || mask != 0u || n != 16u)
            return CFG2_ERR_GAIN;
    } else if (availability == 1u || availability == 2u) {
        expected = 16u + 8u * (size_t)mic_channels;
        if (encoding != 1u || provenance != 1u || n != expected ||
            (availability == 1u && mask != all) ||
            (availability == 2u && (mask == 0u || mask == all)))
            return CFG2_ERR_GAIN;
        for (i = 0u; i < mic_channels; i++) {
            uint64_t value = rd64(p + 16u + 8u * i);
            if ((mask & (UINT32_C(1) << i)) != 0u) {
                /* Restrict to positive normalized signed-32 Q30; no signed cast of
                 * arbitrary input, sign-extension or shifting signed data. */
                if (value == 0u || value > (uint64_t)INT32_MAX)
                    return CFG2_ERR_GAIN;
                gain->coefficients[i] = (int64_t)value;
            } else if (value != 0u) {
                return CFG2_ERR_GAIN;
            }
        }
    } else {
        return CFG2_ERR_GAIN;
    }
    gain->present = 1u;
    gain->encoding = encoding;
    gain->availability = availability;
    gain->provenance = provenance;
    gain->mic_channels = mic_channels;
    gain->present_mask = mask;
    return CFG2_OK;
}

cfg2_error cfg2_decode(const uint8_t *bytes, size_t n, cfg2_descriptor *out)
{
    cfg2_descriptor result;
    size_t pos, count = 0u;
    uint16_t previous = 0u;
    uint8_t have_mic = 0u, have_ref = 0u;

    if (out == NULL)
        return CFG2_ERR_ARGUMENT;
    memset(out, 0, sizeof(*out));
    memset(&result, 0, sizeof(result));
    if (bytes == NULL)
        return CFG2_ERR_ARGUMENT;
    if (n < 16u)
        return CFG2_ERR_HEADER;
    if (memcmp(bytes, "CFG2", 4u) != 0 || rd16(bytes + 4) != 2u ||
        rd16(bytes + 6) != 16u)
        return CFG2_ERR_HEADER;
    if (rd32(bytes + 8) < 16u || rd32(bytes + 8) > CFG2_MAX_BYTES ||
        n != (size_t)rd32(bytes + 8))
        return CFG2_ERR_LENGTH;
    result.stream_flags = rd32(bytes + 12);
    if (result.stream_flags != 1u && result.stream_flags != 7u)
        return CFG2_ERR_FLAGS;

    pos = 16u;
    while (pos < n) {
        uint16_t typ, flags;
        uint32_t value_length;
        const uint8_t *value;
        cfg2_error err = CFG2_OK;
        if (n - pos < 8u)
            return CFG2_ERR_TLV;
        typ = rd16(bytes + pos);
        flags = rd16(bytes + pos + 2u);
        value_length = rd32(bytes + pos + 4u);
        pos += 8u;
        count++;
        if (count > CFG2_MAX_TLVS || typ == 0u || typ == UINT16_MAX ||
            typ <= previous || (flags & (uint16_t)~1u) != 0u)
            return CFG2_ERR_TLV;
        previous = typ;
        /* No untrusted addition, cast, or pointer arithmetic before bound check. */
        if ((uint64_t)value_length > (uint64_t)(n - pos))
            return CFG2_ERR_TLV;
        value = bytes + pos;
        pos += (size_t)value_length;
        switch (typ) {
        case 0x0001u:
            if (flags != 1u)
                return CFG2_ERR_REQUIRED;
            err = decode_stream(value, value_length, &result.mic);
            have_mic = 1u;
            break;
        case 0x0002u:
            if (flags != 1u)
                return CFG2_ERR_REQUIRED;
            err = decode_stream(value, value_length, &result.ref);
            have_ref = 1u;
            break;
        case 0x0003u:
            if (flags != 0u)
                return CFG2_ERR_PLATFORM;
            err = decode_platform(value, value_length, &result.platform);
            break;
        case 0x0101u:
            if (flags != 0u)
                return CFG2_ERR_GAIN;
            err = decode_gain(value, value_length, result.mic.channels, &result.gain);
            break;
        default:
            if (flags == 1u)
                return CFG2_ERR_REQUIRED;
            break;
        }
        if (err != CFG2_OK)
            return err;
    }
    if (!have_mic || !have_ref)
        return CFG2_ERR_REQUIRED;
    if (check_stream(&result.mic, CFG2_MAX_MIC, &result.mic_bytes) != CFG2_OK)
        return CFG2_ERR_STREAM;
    if (result.ref.channels == 0u) {
        if (result.ref.channels != 0u || result.ref.frames != 0u ||
            result.ref.rate != 0u || result.ref.format != 0u ||
            result.ref.full_bits != 0u || result.ref.alignment != 0u ||
            result.ref.valid_bits != 0u || result.stream_flags != 1u)
            return CFG2_ERR_STREAM;
    } else {
        if (result.stream_flags != 7u ||
            check_stream(&result.ref, CFG2_MAX_REF, &result.ref_bytes) != CFG2_OK ||
            (uint64_t)result.mic_bytes + (uint64_t)result.ref_bytes > CFG2_MAX_PCM_PAYLOAD)
            return CFG2_ERR_STREAM;
    }
    *out = result;
    return CFG2_OK;
}

const char *cfg2_error_string(cfg2_error error)
{
    switch (error) {
    case CFG2_OK: return "ok";
    case CFG2_ERR_ARGUMENT: return "argument";
    case CFG2_ERR_HEADER: return "header";
    case CFG2_ERR_LENGTH: return "length";
    case CFG2_ERR_FLAGS: return "flags";
    case CFG2_ERR_TLV: return "tlv";
    case CFG2_ERR_REQUIRED: return "required";
    case CFG2_ERR_STREAM: return "stream";
    case CFG2_ERR_PLATFORM: return "platform";
    case CFG2_ERR_GAIN: return "gain";
    default: return "unknown";
    }
}

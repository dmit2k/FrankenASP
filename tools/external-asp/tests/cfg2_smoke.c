/* Standalone native C11 tests (ASan/UBSan target); synthetic vectors only. */
#include "../cfg2.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct expected {
    const char *filename;
    uint32_t flags, mic_len, ref_len;
    uint16_t mic_ch, ref_ch;
    uint8_t platform, detection, availability;
    uint32_t mask;
    const char *board;
    int64_t coeffs[4];
};

static const struct expected cases[] = {
    {"generic_1mic_noref.cfg2", 1, 640, 0, 1, 0, 0, 0, 0, 0, "", {0}},
    {"athena_4mic_2ref.cfg2", 7, 30720, 7680, 4, 2, 0, 0, 0, 0, "", {0}},
    {"athena_confirmed_complete_4mic.cfg2", 7, 30720, 7680, 4, 2,
     1, 1, 1, 15, "athena", {0x42000000LL, 0x3c000000LL, 0x48000000LL, 0x30000000LL}},
    {"unknown_inferred_partial_4mic.cfg2", 7, 30720, 7680, 4, 2,
     1, 2, 2, 5, "lab_future_7", {0x38000000LL, 0, 0x44000000LL, 0}},
    {"explicit_none_1mic.cfg2", 1, 640, 0, 1, 0, 0, 0, 0, 0, "", {0}},
    {"platform_only_1mic.cfg2", 1, 640, 0, 1, 0, 1, 2, 0, 0, "lab_board-3", {0}}
};

static void fail(const char *why)
{
    fprintf(stderr, "FAIL: %s\n", why);
    exit(1);
}
static int zero(const cfg2_descriptor *out)
{
    const unsigned char *p = (const unsigned char *)out;
    size_t i;
    for (i = 0; i < sizeof(*out); i++)
        if (p[i] != 0u)
            return 0;
    return 1;
}
static uint32_t rng = UINT32_C(0xdeadb00b);
static uint32_t next_random(void)
{
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return rng;
}

int main(int argc, char **argv)
{
    uint8_t input[CFG2_MAX_BYTES + 1u], mut[CFG2_MAX_BYTES + 1u];
    size_t k, probes = 0u, rejected = 0u, accepted = 0u;
    if (argc != 2)
        fail("expected one fixture directory argument");
    for (k = 0; k < sizeof(cases)/sizeof(cases[0]); k++) {
        char path[4096];
        size_t n, cut, iteration;
        const struct expected *e = &cases[k];
        cfg2_descriptor desc, second;
        FILE *fp;
        if (snprintf(path, sizeof(path), "%s/%s", argv[1], e->filename) >= (int)sizeof(path))
            fail("long fixture path");
        fp = fopen(path, "rb");
        if (!fp)
            fail("cannot open synthetic fixture");
        n = fread(input, 1, sizeof(input), fp);
        if (ferror(fp) || !feof(fp)) {
            /* Files are tiny; a full-size read must consume the whole file. */
            fclose(fp);
            fail("fixture too large");
        }
        if (fclose(fp) != 0 || n < 16u || n > CFG2_MAX_BYTES)
            fail("fixture size");
        memset(&desc, 0xa5, sizeof(desc));
        if (cfg2_decode(input, n, &desc) != CFG2_OK)
            fail("golden rejected");
        if (desc.stream_flags != e->flags || desc.mic_bytes != e->mic_len ||
            desc.ref_bytes != e->ref_len || desc.mic.channels != e->mic_ch ||
            desc.ref.channels != e->ref_ch || desc.platform.present != e->platform ||
            desc.platform.detection != e->detection ||
            desc.gain.availability != e->availability || desc.gain.present_mask != e->mask ||
            strcmp(desc.platform.codename, e->board) != 0 ||
            desc.gain.present != (uint8_t)(e->availability != 0u || e->mask != 0u ||
                strcmp(e->filename, "explicit_none_1mic.cfg2") == 0))
            fail("decoded golden metadata mismatch");
        {
            size_t i;
            for (i = 0u; i < 16u; i++) {
                int64_t value = i < 4u ? e->coeffs[i] : 0;
                if (desc.gain.coefficients[i] != value)
                    fail("captured-slot Q30 mismatch");
            }
        }
        /* Owned POD descriptor: mutating packet after parsing must not change it. */
        memcpy(mut, input, n);
        if (cfg2_decode(mut, n, &second) != CFG2_OK ||
            memcmp(&second, &desc, sizeof(desc)) != 0)
            fail("determinism");
        memset(mut, 0xff, n);
        if (second.mic.channels != e->mic_ch ||
            strcmp(second.platform.codename, e->board) != 0)
            fail("owned storage");
        accepted++;
        /* Prefix truncation of each header/body byte, including n=0. */
        for (cut = 0; cut < n; cut++) {
            cfg2_error err;
            memset(&second, 0xa5, sizeof(second));
            err = cfg2_decode(input, cut, &second);
            probes++;
            if (err == CFG2_OK || !zero(&second))
                fail("prefix accepted or leaked partial output");
            rejected++;
        }
        for (iteration = 0; iteration < 5000u; iteration++) {
            size_t j, mutations;
            cfg2_error err;
            memcpy(mut, input, n);
            mutations = 1u + (size_t)(next_random() % 8u);
            for (j = 0; j < mutations; j++) {
                size_t p = (size_t)(next_random() % (uint32_t)n);
                mut[p] = (uint8_t)next_random();
            }
            memset(&second, 0xa5, sizeof(second));
            err = cfg2_decode(mut, n, &second);
            probes++;
            if (err != CFG2_OK) {
                if (!zero(&second))
                    fail("mutated input leaked output");
                rejected++;
            } else {
                accepted++;
                if (second.mic.channels < 1u || second.mic.channels > 16u ||
                    second.mic_bytes > CFG2_MAX_PCM_PAYLOAD ||
                    (uint64_t)second.mic_bytes + second.ref_bytes > CFG2_MAX_PCM_PAYLOAD)
                    fail("mutated input accepted invalid stream");
            }
        }
        printf("PASS %s golden + prefixes + 5000 hostile mutations\n", e->filename);
    }
    printf("PASS C11 native probes=%zu accepted=%zu rejected=%zu\n", probes, accepted, rejected);
    return 0;
}

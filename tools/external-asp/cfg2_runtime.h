#ifndef ASP_CFG2_RUNTIME_H
#define ASP_CFG2_RUNTIME_H
#include "core.h"
#include "cfg2.h"

/* Shared immutable session/FIFO; factory Calibrator alone applies mic gain. */
struct cfg2_runtime {
 cfg2_descriptor session; /* immutable captured-slot metadata */
 struct bridge bridge;
 i64 logical_gain[4]; /* explicit map association only; never multiplied */
 int high, accepted, terminal;
};
cfg2_error cfg2_read_fd(int fd,cfg2_descriptor *out);
int cfg2_parse_map(const char *text,int *out,int channels);
/* init accepts only a descriptor returned successfully by cfg2_decode/read_fd. */
int cfg2_runtime_init(struct cfg2_runtime *,const cfg2_descriptor *,const struct profile *);
int cfg2_runtime_step(struct cfg2_runtime *,const u8 *,const u8 *,int *,i16[320],u64 *);
#endif

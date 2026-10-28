#ifndef ASP_CORE_H
#define ASP_CORE_H
#include "platform.h"
#define MIC_BYTES 30720
#define REF_BYTES 7680
struct profile {int mic[4],ref[2],experiment;};
struct bridge {
 struct profile profile;
 i32 quantum[768*6] __attribute__((aligned(16))); i16 mono[640];
 u32 native_count,mono_count,max_native,max_mono;
 u64 sequence,emitted,quanta,frames;
};
struct dsp {void *lib,*pipeline; int initialized;};
u16 le16(const u8*); u32 le32(const u8*); u64 le64(const u8*);
void put16(u8*,u16); void put32(u8*,u32); void put64(u8*,u64);
int parse_profile(const char*,struct profile*,char[256]);
int prepare_frame(const struct profile*,const u8*,const u8*,u32,int,i32[6]);
int bridge_step_aligned(struct bridge*,const u8*,const u8*,int,int*,i16[320],u64*);
int dsp_open(struct dsp*); int dsp_process(struct dsp*,const i32*,i16*); int dsp_close(struct dsp*);
extern struct dsp factory;
#endif

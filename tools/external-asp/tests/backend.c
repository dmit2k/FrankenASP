/* Synthetic deterministic probe ONLY; never linked into external-asp factory build. */
#include "core.h"
struct dsp factory;
static u64 count;
int dsp_open(struct dsp*d){(void)d;count=0;return 0;}
int dsp_process(struct dsp*d,const i32*in,i16*out){
 (void)d;
 const char*fault=getenv("ASP2_TEST_FAULT");
 if(fault&&!strcmp(fault,"crash")&&count==20)_exit(17);
 if(fault&&!strcmp(fault,"fatal")&&count==20)return -1;
 if(fault&&!strcmp(fault,"hang")&&count==20)for(;;)pause();
 for(int j=0;j<128;j++)out[j]=(i16)(in[j*36]>>8);
 count++;return 0;
}
int dsp_close(struct dsp*d){(void)d;return 0;}

/* Every converted MIC/REF word influences output; no Q30 or vendor calls. */
#include "core.h"
struct dsp factory;
static u64 count;
static int fault;
int dsp_open(struct dsp *d){
 (void)d;count=0;
 const char *s=getenv("ASP2_TEST_FAULT");
 fault=s&&!strcmp(s,"fatal")?1:s&&!strcmp(s,"crash")?2:s&&!strcmp(s,"hang")?3:0;
 return 0;
}
int dsp_process(struct dsp *d,const i32 *in,i16 *out){
 (void)d;
 if(count==20){
  if(fault==1)return -1;
  if(fault==2)_exit(17);
  if(fault==3)for(;;)pause();
 }
 for(int j=0;j<128;j++){
  u32 hash=2166136261u;
  for(int k=0;k<36;k++)hash=(hash^(u32)in[j*36+k])*16777619u;
  out[j]=(i16)(u16)((hash>>16)^hash);
 }
 count++;return 0;
}
int dsp_close(struct dsp *d){(void)d;return 0;}

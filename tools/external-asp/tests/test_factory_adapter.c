/* Full ABI-bound numerical replay, lifecycle failures and bounded stress. */
#include "../cfg2_runtime.h"
#include "mock_vendor.h"
#include <stdio.h>
#include <limits.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);return 1;}}while(0)
static struct cfg2_runtime s;
static u8 mic[MIC_BYTES],refpcm[REF_BYTES];
static struct factory_adapter a;
static i32 native[768*6];
static i16 output[320];
static const struct factory_abi abi={asp_init,asp_create_pipeline,asp_set_ext_ref_sync_status,
                                    asp_process,asp_destroy_pipeline,asp_deinit};
static int closed(unsigned pipelines,unsigned initialized){
 CHECK(factory_adapter_close(&a)==0);
 CHECK(factory_adapter_close(&a)==0);
 CHECK(mock_seen.destroy==pipelines&&mock_seen.deinit==initialized&&!mock_seen.violations);
 return 0;
}
int main(int argc,char **argv){
 CHECK(argc==2);
 u8 raw[8192];cfg2_descriptor c;
 FILE *f=fopen(argv[1],"rb");CHECK(f);
 usize n=fread(raw,1,sizeof raw,f);CHECK(!ferror(f)&&fclose(f)==0);
 CHECK(cfg2_decode(raw,n,&c)==CFG2_OK);
 struct profile p={{0,1,2,3},{0,1},1};
 unsigned cases=0;
 const i32 values[]={-8388608,-257,-1,0,1,257,8388607};
 /* Construct byte input and expected signed words independently of prepare_frame. */
 for(int i=0;i<4;i++)for(int j=0;j<4;j++)for(int k=0;k<4;k++)for(int l=0;l<4;l++){
  if(i==j||i==k||i==l||j==k||j==l||k==l)continue;
  p.mic[0]=i;p.mic[1]=j;p.mic[2]=k;p.mic[3]=l;
  for(int swap=0;swap<2;swap++)for(int high=0;high<2;high++)for(int v=0;v<7;v++){
   p.ref[0]=swap;p.ref[1]=1-swap;
   c.mic.alignment=(u8)high;c.mic.full_bits=high?31:23;
   const i32 captured[4]={values[v],-257,8388607,-8388608};
   for(int d=0;d<4;d++)c.gain.coefficients[d]=(i64)(d+1)*123456789;
   CHECK(cfg2_runtime_init(&s,&c,&p)==0);
   for(int d=0;d<4;d++)CHECK(s.logical_gain[d]==c.gain.coefficients[p.mic[d]]);
   for(unsigned frame=0;frame<1920;frame++){
    for(int d=0;d<4;d++)put32(mic+frame*16+d*4,(u32)(high?(i64)captured[d]*256+frame%256:captured[d]));
    put16(refpcm+frame*4,0x8000);put16(refpcm+frame*4+2,0x7fff);
   }
   CHECK(dsp_open(&factory)==0);
   int ready=9;u64 origin=0;
   CHECK(cfg2_runtime_step(&s,mic,refpcm,&ready,output,&origin)==0);
   CHECK(!ready&&origin==~(u64)0&&s.bridge.quanta==2&&s.bridge.native_count==384);
   CHECK(mock_seen.process==2&&mock_seen.last_stamp.sec==0&&mock_seen.last_stamp.nsec==8000000);
   for(int frame=0;frame<768;frame++){
    for(int d=0;d<4;d++)CHECK(mock_seen.last_input[frame*6+d]==captured[p.mic[d]]);
    CHECK(mock_seen.last_input[frame*6+4]==(swap?2147418112:INT32_MIN));
    CHECK(mock_seen.last_input[frame*6+5]==(swap?INT32_MIN:2147418112));
   }
   s.bridge.sequence++;
   CHECK(cfg2_runtime_step(&s,mic,refpcm,&ready,output,&origin)==0&&ready&&origin==0);
   CHECK(s.bridge.quanta==5&&s.bridge.native_count==0);
   CHECK(dsp_close(&factory)==0&&dsp_close(&factory)==0);
   CHECK(mock_seen.destroy==1&&mock_seen.deinit==1&&!mock_seen.violations);
   CHECK(!strcmp(mock_seen.order,"ICRPDX"));
   cases++;
  }
 }
 for(unsigned missing=0;missing<6;missing++){
  struct factory_abi bad=abi;
  switch(missing){case 0:bad.init=NULL;break;case 1:bad.create=NULL;break;
   case 2:bad.ref_sync=NULL;break;case 3:bad.process=NULL;break;
   case 4:bad.destroy=NULL;break;default:bad.deinit=NULL;break;}
  mock_reset("",0);CHECK(factory_adapter_open(&a,&bad)!=0);
  CHECK(closed(0,0)==0&&mock_seen.init==0);
 }
 const char *startup[]={"init","create","ref"};
 for(unsigned j=0;j<3;j++){
  mock_reset(startup[j],0);CHECK(factory_adapter_open(&a,&abi)!=0);
  CHECK(closed(j==2,j!=0)==0);
 }
 const char *faults[]={"process","partial-in","partial-out","input-before","input-after",
                       "input-mutate","output-before","output-after"};
 for(unsigned j=0;j<sizeof faults/sizeof faults[0];j++){
  mock_reset(faults[j],1);CHECK(factory_adapter_open(&a,&abi)==0);
  CHECK(factory_adapter_process(&a,native,output)==0);
  memset(output,0x55,256);
  CHECK(factory_adapter_process(&a,native,output)!=0&&a.terminal);
  for(int t=0;t<128;t++)CHECK(output[t]==0x5555);
  CHECK(factory_adapter_process(&a,native,output)!=0&&mock_seen.process==2);
  CHECK(closed(1,1)==0);
 }
 mock_reset("destroy",0);CHECK(factory_adapter_open(&a,&abi)==0);
 CHECK(factory_adapter_close(&a)!=0&&factory_adapter_close(&a)==0);
 CHECK(mock_seen.destroy==1&&mock_seen.deinit==1&&!mock_seen.violations);
 mock_reset("",0);CHECK(factory_adapter_open(&a,&abi)==0);
 a.stamp.sec=INT32_MAX;a.stamp.nsec=992000000;
 CHECK(factory_adapter_process(&a,native,output)!=0&&mock_seen.process==0&&a.terminal);
 CHECK(closed(1,1)==0);
 mock_reset("",0);CHECK(factory_adapter_open(&a,&abi)==0);
 factory_cancelled=1;CHECK(factory_adapter_process(&a,native,output)!=0&&mock_seen.process==0);
 factory_cancelled=0;CHECK(closed(1,1)==0);
 /* LOW24 invalid values at either end of the tick are terminal without PCM. */
 c.mic.alignment=0;c.mic.full_bits=23;
 for(int late=0;late<2;late++){
  CHECK(cfg2_runtime_init(&s,&c,&p)==0&&dsp_open(&factory)==0);
  memset(mic,0,sizeof mic);
  put32(mic+(late?MIC_BYTES-4:0),(u32)(late?-8388609:8388608));
  int ready=1;u64 origin=0;
  CHECK(cfg2_runtime_step(&s,mic,refpcm,&ready,output,&origin)!=0&&!ready&&origin==~(u64)0&&s.terminal);
  CHECK(mock_seen.process==(late?2u:0u));
  CHECK(dsp_close(&factory)==0);
 }
 CHECK(cfg2_runtime_init(&s,&c,&p)==0&&dsp_open(&factory)==0);
 s.bridge.sequence=~(u64)0/320-1;
 {int ready=1;u64 origin=0;
  CHECK(cfg2_runtime_step(&s,mic,refpcm,&ready,output,&origin)!=0&&s.terminal&&!ready&&origin==~(u64)0);
  CHECK(mock_seen.process==0&&dsp_close(&factory)==0);
 }
 /* Exact 20ms/8ms schedule and timestamps across seconds for 100k ticks. */
 memset(mic,0,sizeof mic);memset(refpcm,0,sizeof refpcm);
 CHECK(cfg2_runtime_init(&s,&c,&p)==0&&dsp_open(&factory)==0);
 for(u64 tick=0;tick<100000;tick++){
  int ready;u64 origin;
  CHECK(cfg2_runtime_step(&s,mic,refpcm,&ready,output,&origin)==0);
  CHECK(ready==(tick!=0)&&origin==(tick?(tick-1)*320:~(u64)0));
  CHECK(s.bridge.quanta==(tick+1)*5/2&&s.bridge.native_count==((tick+1)%2)*384);
  s.bridge.sequence++;
 }
 CHECK(mock_seen.process==250000&&!mock_seen.violations&&s.bridge.frames==192000000);
 CHECK(dsp_close(&factory)==0);
 printf("PASS factory ABI numerical cases=%u; 24x2x2x7; lifecycle/faults/guards; timestamps; 100000 FIFO ticks/250000 quanta\n",cases);
 return 0;
}

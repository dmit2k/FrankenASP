/* Independent sample-ID oracle across 192 million native frames.
 * Synthetic backend only. IDs originate in input, not fabricated in bridge. */
#include "core.h"
static struct bridge b;
static u8 m[MIC_BYTES],r[REF_BYTES];static i16 out[320];
static i16 marker(u64 n){n^=n>>17;n*=0x9e3779b185ebca87ULL;n^=n>>29;return (i16)n;}
int main(void){
 for(int j=0;j<4;j++)b.profile.mic[j]=j;
 b.profile.ref[0]=0;b.profile.ref[1]=1;
 if(dsp_open(&factory))return 1;
 for(u64 tick=0;tick<100000;tick++){
  for(u32 f=0;f<1920;f++){
   u64 sample=tick*320+f/6;
   for(u32 ch=0;ch<4;ch++)put32(m+(f*4+ch)*4,(u32)((i32)marker(sample+ch*991)*256));
   put16(r+f*4,(u16)marker(tick*1920+f));put16(r+f*4+2,(u16)marker(tick*1920+f+123));
  }
  int ready;u64 origin;
  if(bridge_step_aligned(&b,m,r,0,&ready,out,&origin))return 2;
  if((!tick&&ready)||(tick&&!ready))return 3;
  if(tick){
   if(origin!=(tick-1)*320)return 4;
   for(int j=0;j<320;j++)if(out[j]!=marker((tick-1)*320+(u32)j))return 5;
  }
  if(b.quanta!=(tick+1)*1920/768||b.frames!=(tick+1)*1920||b.native_count!=(tick+1)*1920%768)return 6;
  b.sequence++;
 }
 if(b.quanta!=250000||b.emitted!=31999680||b.mono_count!=320||b.native_count||b.max_native!=384||b.max_mono!=320)return 7;
 return dsp_close(&factory)?8:0;
}

#include "core.h"
u16 le16(const u8*p){return (u16)(p[0]|(u16)p[1]<<8);}
u32 le32(const u8*p){return (u32)p[0]|(u32)p[1]<<8|(u32)p[2]<<16|(u32)p[3]<<24;}
u64 le64(const u8*p){return (u64)le32(p)|(u64)le32(p+4)<<32;}
void put16(u8*p,u16 v){p[0]=(u8)v;p[1]=(u8)(v>>8);}
void put32(u8*p,u32 v){for(int j=0;j<4;j++)p[j]=(u8)(v>>(j*8));}
void put64(u8*p,u64 v){put32(p,(u32)v);put32(p+4,(u32)(v>>32));}
static int map(const char*s,int*dst,int count){
 unsigned seen=0;
 for(int j=0;j<count;j++){
  int v=s[2*j]-'0';if(v<0||v>=count||(seen&(1u<<v)))return -1;
  if(s[2*j+1]!=(j==count-1?'\n':','))return -1;
  seen|=1u<<v;dst[j]=v;
 }
 return 0;
}
int parse_profile(const char*path,struct profile*p,char manifest[256]){
 char b[512]={0};int fd=secure_open(path,0);if(fd<0)return -1;
 long n=0;
 for(;;){long r=read(fd,b+n,(usize)(sizeof b-1-(usize)n));
  if(r<0&&errno==4)continue;
  if(r<0){close(fd);return -1;}
  if(!r)break;
  n+=r;if(n>=(long)sizeof b-1){close(fd);return -1;}
 }
 close(fd);if(n<=0)return -1;
 for(long j=0;j<n;j++)if(!b[j])return -1;
 b[n]=0;
 const char*prefix="ASP2-ATHENA-OFFLINE-V1\nmic=";usize k=strlen(prefix);
 if((usize)n<k+12||memcmp(b,prefix,k))return -1;
 if(map(b+k,p->mic,4))return -1;
 k+=8;
 if(memcmp(b+k,"ref=",4))return -1;
 k+=4;
 if(map(b+k,p->ref,2))return -1;
 k+=4;
 const char*middle="calibration=libasp-unverified\nmanifest=";usize m=strlen(middle);
 if((usize)n<k+m+2||memcmp(b+k,middle,m))return -1;
 k+=m;usize len=(usize)n-k-1;
 if(len==0||len>254||b[n-1]!='\n')return -1;
 memcpy(manifest,b+k,len);manifest[len]=0;
 if(manifest[0]!='/')return -1;
 p->experiment=1;return 0;
}
int prepare_frame(const struct profile*p,const u8*m,const u8*r,u32 f,int high,i32 out[6]){
 for(int d=0;d<4;d++){
  i32 v=(i32)le32(m+(f*4+(u32)p->mic[d])*4);
  if(high)v=v>>8;
  if(v < -8388608||v>8388607)return -1;
  out[d]=v;
 }
 for(int d=0;d<2;d++)out[4+d]=(i32)(i16)le16(r+(f*2+(u32)p->ref[d])*2)*65536;
 return 0;
}
_Static_assert((-257>>8)==-2,"arithmetic signed shift required");
int bridge_step_aligned(struct bridge*b,const u8*m,const u8*r,int high,int*ready,i16 out[320],u64*origin){
 for(u32 f=0;f<1920;f++){
  if(prepare_frame(&b->profile,m,r,f,high,b->quantum+b->native_count*6))return -1;
  b->native_count++;b->frames++;
  if(b->native_count==768){
   if(b->mono_count+128>640)return -1;
   if(dsp_process(&factory,b->quantum,b->mono+b->mono_count))return -1;
   b->mono_count+=128;b->native_count=0;b->quanta++;
  }
 }
 if(b->native_count>b->max_native)b->max_native=b->native_count;
 *ready=b->mono_count>=320;*origin=~(u64)0;
 if(*ready){
  memcpy(out,b->mono,640);b->mono_count-=320;
  for(u32 j=0;j<b->mono_count;j++)b->mono[j]=b->mono[j+320];
  *origin=b->emitted;b->emitted+=320;
 }
 if(b->mono_count>b->max_mono)b->max_mono=b->mono_count;
 if((*ready&&b->sequence==0)||(!*ready&&b->sequence!=0))return -1;
 return 0;
}

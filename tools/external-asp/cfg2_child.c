/* F1-A: native OFFLINE synthetic child. Never linked with factory.c or Bionic. */
#include "cfg2_runtime.h"
#ifndef ASP2_TEST_BACKEND
#error "CFG2 child requires the synthetic backend"
#endif
#ifdef ASP2_BIONIC
#error "F1-A is host-native only"
#endif
static struct cfg2_runtime runtime;
static u8 mic[MIC_BYTES],refpcm[REF_BYTES];
static i16 pcm[320];
static int ack(int accept,int code,const char *message){
 u8 h[12]={0};memcpy(h,"ACK2",4);h[4]=accept?1:2;h[5]=1;
 put16(h+6,(u16)code);put16(h+8,(u16)strlen(message));
 return exact_write(1,h,12)||exact_write(1,message,(u32)strlen(message));
}
static int reply(int type,int code,u64 origin,const char *message){
 u8 h[32]={0},data[640];memcpy(h,"RSP2",4);h[4]=(u8)type;h[5]=code?1:0;
 put16(h+6,(u16)code);put16(h+8,(u16)strlen(message));
 put64(h+12,runtime.bridge.sequence);put64(h+20,origin);put32(h+28,type==1?640:0);
 if(exact_write(1,h,32)||exact_write(1,message,(u32)strlen(message)))return -1;
 if(type==1){
  for(int j=0;j<320;j++)put16(data+2*j,(u16)pcm[j]);
  return exact_write(1,data,640);
 }
 return 0;
}
static void terminated(int sig){(void)sig;_exit(0);}
int main(int argc,char **argv){
 struct profile p={{0,1,2,3},{0,1},1};cfg2_descriptor c;
 int selected=(argc==2||argc==4)&&!strcmp(argv[1],"--offline-synthetic-cfg2");
 signal(SIGTERM,terminated);signal(SIGINT,terminated);signal(SIGPIPE,terminated);
 if(selected&&argc==4&&(cfg2_parse_map(argv[2],p.mic,4)||cfg2_parse_map(argv[3],p.ref,2)))selected=0;
 /* All resource initialization precedes HELLO. No profile or metadata I/O. */
 int opened=selected&&dsp_open(&factory)==0;
 if(exact_write(1,"ASP2",4))goto done;
 if(!selected||!opened){ack(0,524,"Offline synthetic mode unavailable");goto done;}
 cfg2_error err=cfg2_read_fd(0,&c);
 if(err!=CFG2_OK){ack(0,522,"Invalid CFG2 session");goto done;}
 if(cfg2_runtime_init(&runtime,&c,&p)){ack(0,522,"Unsupported synthetic factory session");goto done;}
 const char *diag="CFG2 accepted: synthetic only; confirmed platform; MIC4 REF2; complete Q30 metadata; PCM gain authority none; explicit identity or CLI maps\n";
 if(exact_write(2,diag,(u32)strlen(diag)))goto done;
 if(ack(1,299,"Synthetic only; factory qualification unavailable"))goto done;
 for(;;){
  u8 h[20];int rd=exact_read(0,h,20);
  if(rd==0)break;
  if(rd!=1||memcmp(h,"INP2",4)||le64(h+4)!=runtime.bridge.sequence||
     le32(h+12)!=runtime.session.mic_bytes||le32(h+16)!=runtime.session.ref_bytes){
   reply(3,523,~(u64)0,"Invalid immutable input framing");break;
  }
  if(exact_read(0,mic,MIC_BYTES)!=1||exact_read(0,refpcm,REF_BYTES)!=1){
   reply(3,523,~(u64)0,"Truncated input payload");break;
  }
  int ready;u64 origin;
  if(cfg2_runtime_step(&runtime,mic,refpcm,&ready,pcm,&origin)){
   reply(3,503,~(u64)0,"Synthetic processing failed");break;
  }
  if(reply(ready?1:2,0,origin,""))break;
  runtime.bridge.sequence++;
 }
done:
 return dsp_close(&factory)?2:0;
}

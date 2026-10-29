/* One CFG2/TLV wire loop, separately bound to Bionic factory or native mock. */
#include "cfg2_runtime.h"
#include "factory_adapter.h"
#if defined(ASP2_FACTORY_MOCK) && !defined(ASP2_TEST_BACKEND)
#error "Factory mock child requires the offline test backend"
#endif
static struct cfg2_runtime runtime;
static u8 mic[MIC_BYTES],refpcm[REF_BYTES];
static i16 pcm[320];
static int wire=1;
static int ack(int accept,int code,const char *message){
 u8 h[12]={0};memcpy(h,"ACK2",4);h[4]=accept?1:2;h[5]=1;
 put16(h+6,(u16)code);put16(h+8,(u16)strlen(message));
 return exact_write(wire,h,12)||exact_write(wire,message,(u32)strlen(message));
}
static int reply(int type,int code,u64 origin,const char *message){
 u8 h[32]={0},data[640];memcpy(h,"RSP2",4);h[4]=(u8)type;h[5]=code?1:0;
 put16(h+6,(u16)code);put16(h+8,(u16)strlen(message));
 put64(h+12,runtime.bridge.sequence);put64(h+20,origin);put32(h+28,type==1?640:0);
 if(exact_write(wire,h,32)||exact_write(wire,message,(u32)strlen(message)))return -1;
 if(type==1){
  for(int j=0;j<320;j++)put16(data+2*j,(u16)pcm[j]);
  return exact_write(wire,data,640);
 }
 return 0;
}
static void terminated(int sig){(void)sig;factory_cancelled=1;close(0);}
#ifdef ASP2_FACTORY_REAL
/* Explicit captured-slot routing, fixed trusted path; no physical-order guess.
 * Read once before init/HELLO. No gain values or mutable mid-session profile. */
static int channel_map(struct profile *p){
 char b[64]={0};
 const char prefix[]="ASP2-CHANNEL-MAP-V1\nmic=";
 int fd=secure_open("/factory/channel-map",0);
 if(fd<0)return -1;
 long n=0;
 for(;;){
  long k=read(fd,b+n,sizeof b-1-(usize)n);
  if(k<0&&errno==4)continue;
  if(k<0){close(fd);return -1;}
  if(!k)break;
  n+=k;if(n>=(long)sizeof b-1){close(fd);return -1;}
 }
 close(fd);
 usize off=sizeof prefix-1;
 if(n!=(long)(off+16)||memcmp(b,prefix,off)||b[off+7]!='\n'||
    memcmp(b+off+8,"ref=",4)||b[off+15]!='\n')return -1;
 b[off+7]=0;b[off+15]=0;
 return cfg2_parse_map(b+off,p->mic,4)||cfg2_parse_map(b+off+12,p->ref,2);
}
#endif
int main(int argc,char **argv){
 struct profile p={{0,1,2,3},{0,1},1};cfg2_descriptor c;
#ifdef ASP2_FACTORY_REAL
 (void)argv;
 int selected=argc==1&&channel_map(&p)==0;
#else
 int selected=(argc==2||argc==4)&&!strcmp(argv[1],"--offline-factory-mock-cfg2");
#endif
 wire=dup(1);
 if(wire<0)return 2;
 if(dup2(2,1)<0){close(wire);return 2;}
 signal(SIGTERM,terminated);signal(SIGINT,terminated);signal(SIGPIPE,terminated);
#ifdef ASP2_FACTORY_MOCK
 if(selected&&argc==4&&(cfg2_parse_map(argv[2],p.mic,4)||cfg2_parse_map(argv[3],p.ref,2)))selected=0;
#endif
 /* All resource initialization precedes HELLO. No profile or metadata I/O. */
 int opened=selected&&!factory_cancelled&&dsp_open(&factory)==0;
#ifdef ASP2_FACTORY_REAL
 /* A missing/failed genuine backend exits without a false ready HELLO. */
 if(!opened){
  const char *why="Factory startup failed before HELLO\n";
  (void)exact_write(2,why,(u32)strlen(why));goto done;
 }
#endif
 if(exact_write(wire,"ASP2",4))goto done;
 if(!selected||!opened){ack(0,576,"Offline factory mock mode unavailable");goto done;}
 cfg2_error err=cfg2_read_fd(0,&c);
 if(err!=CFG2_OK){ack(0,570,"Invalid CFG2 session");goto done;}
 if(cfg2_runtime_init(&runtime,&c,&p)){ack(0,573,"Unsupported offline factory session");goto done;}
#ifdef ASP2_FACTORY_MOCK
 const char *diag="CFG2 accepted: experimental factory mock, unqualified; confirmed platform; MIC4 REF2; complete Q30 metadata; Q30 metadata only; future gain authority vendor Calibrator; explicit identity or CLI maps\n";
 if(exact_write(2,diag,(u32)strlen(diag)))goto done;
 if(ack(1,291,"Experimental factory mock; unqualified"))goto done;
#else
 const char *diag="CFG2 accepted: ARM32 Bionic factory; MIC4 REF2; complete Q30 metadata only; gain authority factory Calibrator; explicit captured-slot maps\n";
 if(exact_write(2,diag,(u32)strlen(diag))||ack(1,250,"Factory configuration accepted"))goto done;
#endif
 int reported_processing=0;
 for(;;){
  u8 h[20];int rd=exact_read(0,h,20);
  if(rd==0||factory_cancelled)break;
  if(rd!=1||memcmp(h,"INP2",4)||le64(h+4)!=runtime.bridge.sequence||
     le32(h+12)!=runtime.session.mic_bytes||le32(h+16)!=runtime.session.ref_bytes){
   reply(3,571,~(u64)0,"Invalid immutable input framing");break;
  }
  if(exact_read(0,mic,MIC_BYTES)!=1||exact_read(0,refpcm,REF_BYTES)!=1){
   reply(3,574,~(u64)0,"Truncated input payload");break;
  }
  int ready;u64 origin;
  if(cfg2_runtime_step(&runtime,mic,refpcm,&ready,pcm,&origin)){
   if(!factory_cancelled)reply(3,550,~(u64)0,"Factory processing failed");
   break;
  }
  if(factory_cancelled)break;
  /* One ready transition, not a STATE on every 20-ms PCM frame. */
  int started=ready&&!reported_processing;
  if(reply(ready?1:2,started?251:0,origin,started?"Factory processing started":""))break;
  if(started)reported_processing=1;
  runtime.bridge.sequence++;
 }
done:
 {int rc=dsp_close(&factory);close(wire);
#ifdef ASP2_FACTORY_REAL
  if(!opened)return 2;
#endif
  return rc?2:0;
 }
}

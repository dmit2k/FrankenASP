/* Native numerical/mapping/ownership checks; all inputs are synthetic. */
#include "../cfg2_runtime.h"
#include <stdio.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);return 1;}}while(0)
static struct cfg2_runtime s;
int main(int argc,char **argv){
 u8 raw[8192],m[16],r[4],saved[16];cfg2_descriptor c;
 struct profile p={{0,1,2,3},{0,1},1};
 CHECK(argc==2);
 FILE *fp=fopen(argv[1],"rb");CHECK(fp);
 usize n=fread(raw,1,sizeof raw,fp);CHECK(!ferror(fp)&&fclose(fp)==0);
 CHECK(cfg2_decode(raw,n,&c)==CFG2_OK);
 cfg2_descriptor expected=c;
 CHECK(dsp_open(&factory)==0);
 unsigned cases=0;
 for(int a=0;a<4;a++)for(int b=0;b<4;b++)for(int d=0;d<4;d++)for(int e=0;e<4;e++){
  if(a==b||a==d||a==e||b==d||b==e||d==e)continue;
  p.mic[0]=a;p.mic[1]=b;p.mic[2]=d;p.mic[3]=e;
  for(int swap=0;swap<2;swap++)for(int high=0;high<2;high++){
   p.ref[0]=swap;p.ref[1]=1-swap;
   c=expected;c.mic.alignment=(u8)high;c.mic.full_bits=high?31:23;
   CHECK(cfg2_runtime_init(&s,&c,&p)==0);
   for(int j=0;j<4;j++)CHECK(s.logical_gain[j]==c.gain.coefficients[p.mic[j]]);
   CHECK(!memcmp(&s.session,&c,sizeof c));
   /* Caller metadata and maps have no mutable aliases in accepted state. */
   cfg2_descriptor snap=s.session;struct profile maps=s.bridge.profile;
   c.gain.coefficients[0]=1;p.mic[0]=99;
   CHECK(!memcmp(&snap,&s.session,sizeof snap)&&!memcmp(&maps,&s.bridge.profile,sizeof maps));
   p.mic[0]=a;
   const i32 values[]={-8388608,-257,-1,0,1,257,8388607};
   for(unsigned v=0;v<sizeof values/sizeof values[0];v++){
    i32 captured[4]={values[v],-257,8388607,-8388608},out[6];
    for(int j=0;j<4;j++)put32(m+j*4,(u32)(high?(i64)captured[j]*256:captured[j]));
    put16(r,0x8000);put16(r+2,0x7fff);memcpy(saved,m,sizeof m);
    CHECK(prepare_frame(&s.bridge.profile,m,r,0,s.high,out)==0);
    for(int j=0;j<4;j++)CHECK(out[j]==captured[p.mic[j]]);
    CHECK(out[4]==(swap?2147418112:(-2147483647-1)));
    CHECK(out[5]==(swap?(-2147483647-1):2147418112));
    CHECK(!memcmp(saved,m,sizeof m)&&le16(r)==0x8000&&le16(r+2)==0x7fff);
    cases++;
   }
  }
 }
 c=expected;p=(struct profile){{0,1,2,3},{0,1},1};
 for(int bad=-1;bad<=4;bad+=5){p.mic[0]=bad;CHECK(cfg2_runtime_init(&s,&c,&p)!=0&&!s.accepted);}
 p.mic[0]=1;CHECK(cfg2_runtime_init(&s,&c,&p)!=0&&!s.accepted);
 p.mic[0]=0;p.ref[1]=0;CHECK(cfg2_runtime_init(&s,&c,&p)!=0&&!s.accepted);
 p.ref[1]=1;CHECK(cfg2_runtime_init(&s,&c,&p)==0);
 /* Sequence overflow fails before processing and latches terminal state. */
 s.bridge.sequence=~(u64)0/320-1;
 int ready=1;u64 origin=0;i16 out[320];
 CHECK(cfg2_runtime_step(&s,m,r,&ready,out,&origin)!=0&&s.terminal&&!ready&&origin==~(u64)0);
 s.bridge.sequence=0;CHECK(cfg2_runtime_step(&s,m,r,&ready,out,&origin)!=0);
 int map[4]={9,9,9,9};
 CHECK(cfg2_parse_map("2,0,3,1",map,4)==0&&map[0]==2&&map[3]==1);
 CHECK(cfg2_parse_map("0,0,2,3",map,4)!=0&&map[0]==2);
 CHECK(cfg2_parse_map("0,1,2",map,4)!=0);
 CHECK(cfg2_parse_map("0,1,2,4",map,4)!=0);
 CHECK(cfg2_parse_map("1,0",map,2)==0);
 CHECK(dsp_close(&factory)==0);
 printf("PASS CFG2 numerical cases=%u; all 24 MIC x 2 REF x LOW/HIGH; Q30 metadata association; owned session; terminal overflow\n",cases);
 return 0;
}

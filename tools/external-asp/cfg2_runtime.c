#include "cfg2_runtime.h"

cfg2_error cfg2_read_fd(int fd,cfg2_descriptor *out){
 u8 packet[CFG2_MAX_BYTES];u32 n,flags;
 if(!out)return CFG2_ERR_ARGUMENT;
 memset(out,0,sizeof *out);
 /* No variable allocation; validate all envelope fields before reading body. */
 if(exact_read(fd,packet,16)!=1)return CFG2_ERR_HEADER;
 if(memcmp(packet,"CFG2",4)||le16(packet+4)!=2||le16(packet+6)!=16)return CFG2_ERR_HEADER;
 n=le32(packet+8);flags=le32(packet+12);
 if(n<16||n>CFG2_MAX_BYTES)return CFG2_ERR_LENGTH;
 if(flags!=1&&flags!=7)return CFG2_ERR_FLAGS;
 if(exact_read(fd,packet+16,n-16)!=1)return CFG2_ERR_LENGTH;
 return cfg2_decode(packet,n,out);
}
int cfg2_parse_map(const char *text,int *out,int channels){
 int tmp[4];unsigned seen=0;
 if(!text||!out||(channels!=4&&channels!=2)||strlen(text)!=(usize)(channels*2-1))return -1;
 for(int d=0;d<channels;d++){
  int s=text[d*2]-'0';
  if(s<0||s>=channels||(seen&(1u<<s))||(d+1<channels&&text[d*2+1]!=','))return -1;
  tmp[d]=s;seen|=1u<<s;
 }
 memcpy(out,tmp,(usize)channels*sizeof *out);return 0;
}
static int permutation(const int *m,int n){
 unsigned seen=0;
 for(int d=0;d<n;d++){
  if(m[d]<0||m[d]>=n||(seen&(1u<<m[d])))return -1;
  seen|=1u<<m[d];
 }
 return 0;
}
int cfg2_runtime_init(struct cfg2_runtime *s,const cfg2_descriptor *c,const struct profile *p){
 if(!s)return -1;
 memset(s,0,sizeof *s);
 if(!c||!p||permutation(p->mic,4)||permutation(p->ref,2))return -1;
 /* Decoder validity alone is insufficient for this deliberately narrow mode.
  * Codename is routing metadata, never asset or factory qualification. */
 if(!c->platform.present||c->platform.detection!=1||
    c->platform.codename_length!=6||memcmp(c->platform.codename,"athena",7))return -1;
 if(c->stream_flags!=7||c->mic_bytes!=MIC_BYTES||c->ref_bytes!=REF_BYTES||
    c->mic.channels!=4||c->mic.frames!=1920||c->mic.rate!=96000||
    c->mic.format!=2||c->mic.valid_bits!=24||
    !((c->mic.alignment==0&&c->mic.full_bits==23)||(c->mic.alignment==1&&c->mic.full_bits==31))||
    c->ref.channels!=2||c->ref.frames!=1920||c->ref.rate!=96000||
    c->ref.format!=1||c->ref.valid_bits!=16||c->ref.full_bits!=15||c->ref.alignment!=0)return -1;
 if(!c->gain.present||c->gain.availability!=1||c->gain.encoding!=1||
    c->gain.provenance!=1||c->gain.applied_to_pcm||c->gain.mic_channels!=4||
    c->gain.present_mask!=15)return -1;
 for(int d=0;d<4;d++)if(c->gain.coefficients[d]<=0||c->gain.coefficients[d]>2147483647LL)return -1;
 s->session=*c;s->bridge.profile=*p;s->high=c->mic.alignment;
 for(int d=0;d<4;d++)s->logical_gain[d]=c->gain.coefficients[p->mic[d]];
 s->accepted=1;return 0;
}
int cfg2_runtime_step(struct cfg2_runtime *s,const u8 *m,const u8 *r,int *ready,i16 out[320],u64 *origin){
 if(!s||!s->accepted||s->terminal||!m||!r||!ready||!out||!origin)return -1;
 *ready=0;*origin=~(u64)0;
 if(s->bridge.sequence>=~(u64)0/320-1||
    bridge_step_aligned(&s->bridge,m,r,s->high,ready,out,origin)){
  s->terminal=1;*ready=0;*origin=~(u64)0;return -1;
 }
 return 0;
}

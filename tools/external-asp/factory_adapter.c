#include "factory_adapter.h"
#include <stdalign.h>
#include <stdint.h>
#ifdef ASP2_FACTORY_MOCK
struct dsp factory;
static struct factory_adapter active;
#endif
volatile sig_atomic_t factory_cancelled;
int factory_adapter_close(struct factory_adapter *a){
 int rc=0;
 if(!a||a->closed)return 0;
 a->closed=1;
 if(a->pipeline){
  void *p=a->pipeline;a->pipeline=NULL;
  if(a->abi.destroy(p))rc=-1;
 }
 if(a->initialized){a->initialized=0;a->abi.deinit();}
 return rc;
}
int factory_adapter_open(struct factory_adapter *a,const struct factory_abi *v){
 if(!a)return -1;
 memset(a,0,sizeof *a);
 if(!v||!v->init||!v->create||!v->ref_sync||!v->process||!v->destroy||!v->deinit){
  a->terminal=1;return -1;
 }
 a->abi=*v;
 if(a->abi.init()){a->terminal=1;return -1;}
 a->initialized=1;
 a->pipeline=a->abi.create(0,4,6,96000,1,1,16000);
 if(!a->pipeline||a->abi.ref_sync(a->pipeline,2)){
  a->terminal=1;(void)factory_adapter_close(a);return -1;
 }
 return 0;
}
static int intact(const u8 *p,usize n){
 for(usize j=0;j<n;j++)if(p[j]!=0xa5)return 0;
 return 1;
}
int factory_adapter_process(struct factory_adapter *a,const i32 in[768*6],i16 out[128]){
 struct {alignas(16) u8 pre[32];alignas(16) i32 data[768*6];u8 post[32];} input;
 struct {alignas(16) u8 pre[32];alignas(16) i16 data[128];u8 post[32];} output;
 if(!a||!in||!out||a->terminal||a->closed||!a->pipeline||factory_cancelled)return -1;
 /* Reject before process or timestamp arithmetic can overflow signed timespec32. */
 if(a->stamp.sec<0||a->stamp.nsec<0||a->stamp.nsec>=1000000000||
    (a->stamp.sec==INT32_MAX&&a->stamp.nsec>=992000000)){
  a->terminal=1;return -1;
 }
 memset(&input,0xa5,sizeof input);memcpy(input.data,in,sizeof input.data);
 memset(&output,0xa5,sizeof output);memset(output.data,0,sizeof output.data);
 u32 ni=768,no=128;
 int rc=a->abi.process(a->pipeline,input.data,&ni,output.data,&no,0,a->stamp);
 if(rc||factory_cancelled||ni!=768||no!=128||
    !intact(input.pre,32)||!intact(input.post,32)||
    !intact(output.pre,32)||!intact(output.post,32)||
    memcmp(input.data,in,sizeof input.data)){
  a->terminal=1;return -1;
 }
 memcpy(out,output.data,sizeof output.data);
 a->stamp.nsec+=8000000;
 if(a->stamp.nsec>=1000000000){a->stamp.sec++;a->stamp.nsec-=1000000000;}
 return 0;
}
#ifdef ASP2_FACTORY_MOCK
int dsp_open(struct dsp *d){
 int rc=factory_adapter_open(&active,offline_mock_abi());
 d->initialized=!rc;return rc;
}
int dsp_process(struct dsp *d,const i32 *in,i16 *out){
 (void)d;return factory_adapter_process(&active,in,out);
}
int dsp_close(struct dsp *d){
 d->initialized=0;return factory_adapter_close(&active);
}

#endif

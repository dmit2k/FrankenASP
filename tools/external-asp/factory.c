/* ARM32/Bionic binding only. Lifecycle and buffer checks live in the adapter. */
#include "factory_adapter.h"
#ifndef ASP2_FACTORY_REAL
#error "Use the separate mock target for offline ABI fault injection"
#endif
static struct factory_adapter active;
struct dsp factory;
static int symbol(void *lib,const char *name,void *fn,usize size){
 void *address=dlsym(lib,name);
 if(!address||size!=sizeof address)return -1;
 memcpy(fn,&address,size);return 0;
}
int dsp_open(struct dsp *d){
 struct factory_abi v;
 memset(&v,0,sizeof v);
 d->lib=dlopen("/vendor/lib/libasp.so",2);
 if(!d->lib)return -1;
 /* Resolve every export before the first vendor initialization call. */
 if(symbol(d->lib,"asp_init",&v.init,sizeof v.init)||
    symbol(d->lib,"asp_create_pipeline",&v.create,sizeof v.create)||
    symbol(d->lib,"asp_set_ext_ref_sync_status",&v.ref_sync,sizeof v.ref_sync)||
    symbol(d->lib,"asp_process",&v.process,sizeof v.process)||
    symbol(d->lib,"asp_destroy_pipeline",&v.destroy,sizeof v.destroy)||
    symbol(d->lib,"asp_deinit",&v.deinit,sizeof v.deinit))return -1;
 int rc=factory_adapter_open(&active,&v);
 d->initialized=!rc;return rc;
}
int dsp_process(struct dsp *d,const i32 *in,i16 *out){
 (void)d;return factory_adapter_process(&active,in,out);
}
int dsp_close(struct dsp *d){
 int rc=factory_adapter_close(&active);
 d->initialized=0;
 if(d->lib){if(dlclose(d->lib))rc=-1;d->lib=NULL;}
 return rc;
}

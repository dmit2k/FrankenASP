/* Independent test ABI implementation: no vendor code/assets/loader. */
#include "mock_vendor.h"
#include <stdio.h>
#include <stdint.h>
struct mock_observation mock_seen;
static const char *fault="";
static u64 at=20;
static int live,created,synced,token;
static unsigned order_count;
static struct factory_abi table;
void mock_reset(const char *s,u64 n){
 memset(&mock_seen,0,sizeof mock_seen);
 fault=s?s:"";at=n;live=created=synced=0;order_count=0;
}
static void event(char c){
 if(order_count<sizeof mock_seen.order-1)mock_seen.order[order_count++]=c;
}
static int is(const char *s){return !strcmp(fault,s);}
static int violation(void){mock_seen.violations++;return -1;}
i32 asp_init(void){
 event('I');mock_seen.init++;
 if(getenv("ASP2_MOCK_CHATTER")){puts("Mock vendor stdout chatter");fflush(stdout);}
 if(live)return violation();
 if(is("init"))return -1;
 live=1;return 0;
}
void *asp_create_pipeline(u32 a,u32 b,u32 c,u32 d,u32 e,u32 f,u32 g){
 event('C');mock_seen.create++;
 if(!live||created||a!=0||b!=4||c!=6||d!=96000||e!=1||f!=1||g!=16000){
  (void)violation();return NULL;
 }
 if(is("create"))return NULL;
 created=1;return &token;
}
i32 asp_set_ext_ref_sync_status(void *p,i32 status){
 event('R');mock_seen.ref++;
 if(!created||synced||p!=&token||status!=2)return violation();
 if(is("ref"))return -1;
 synced=1;return 0;
}
i32 asp_process(void *p,const void *src,u32 *ni,void *dst,u32 *no,i32 flags,struct asp_time32 stamp){
 mock_seen.process++;
 if(mock_seen.process==1)event('P');
 u64 q=mock_seen.quanta;
 if(!live||!created||!synced||p!=&token||!ni||!no||*ni!=768||*no!=128||flags||
    (uintptr_t)src%16||(uintptr_t)dst%16||
    stamp.sec!=(i32)(q/125)||stamp.nsec!=(i32)((q%125)*8000000))return violation();
 mock_seen.last_stamp=stamp;memcpy(mock_seen.last_input,src,sizeof mock_seen.last_input);
 if(q==at){
  if(is("fatal")||is("process"))return -1;
  if(is("crash"))_exit(17);
  if(is("hang")){while(!factory_cancelled)pause();return -1;}
  if(is("partial-in"))*ni=767;
  if(is("partial-out"))*no=127;
  /* Intentional in-object canary writes, never outside adapter allocation. */
  if(is("input-before"))((u8 *)(uintptr_t)src)[-1]=0;
  if(is("input-after"))((u8 *)(uintptr_t)src)[768*6*4]=0;
  if(is("input-mutate"))((u8 *)(uintptr_t)src)[0]^=1;
  if(is("output-before"))((u8 *)dst)[-1]=0;
  if(is("output-after"))((u8 *)dst)[256]=0;
 }
 /* Each group of 6 native frames yields one S16. Every input word matters.
  * Unsigned modulo arithmetic is specified; no calibration multiplication. */
 const i32 *words=src;
 for(unsigned sample=0;sample<128;sample++){
  u32 v=2166136261u;
  for(unsigned word=sample*36;word<(sample+1)*36;word++)v=(v^(u32)words[word])*16777619u;
  u16 bits=(u16)(v^(v>>16));
  ((i16 *)dst)[sample]=bits<32768?(i16)bits:(i16)((i32)bits-65536);
 }
 mock_seen.quanta++;return 0;
}
i32 asp_destroy_pipeline(void *p){
 event('D');mock_seen.destroy++;
 if(!created||p!=&token)return violation();
 created=synced=0;return is("destroy")?-1:0;
}
void asp_deinit(void){
 event('X');mock_seen.deinit++;
 if(!live||created)(void)violation();
 live=0;
 if(getenv("ASP2_MOCK_TRACE"))fprintf(stderr,
  "MOCK lifecycle=%s init=%u create=%u ref=%u process=%u destroy=%u deinit=%u violations=%u\n",
  mock_seen.order,mock_seen.init,mock_seen.create,mock_seen.ref,mock_seen.process,
  mock_seen.destroy,mock_seen.deinit,mock_seen.violations);
}
const struct factory_abi *offline_mock_abi(void){
 const char *s=getenv("ASP2_TEST_FAULT"),*n=getenv("ASP2_MOCK_FAIL_AT");
 mock_reset(s,n?strtoull(n,NULL,10):20);
 table=(struct factory_abi){asp_init,asp_create_pipeline,asp_set_ext_ref_sync_status,
                           asp_process,asp_destroy_pipeline,asp_deinit};
 if(is("missing-init"))table.init=NULL;
 if(is("missing-create"))table.create=NULL;
 if(is("missing-ref"))table.ref_sync=NULL;
 if(is("missing-process"))table.process=NULL;
 if(is("missing-destroy"))table.destroy=NULL;
 if(is("missing-deinit"))table.deinit=NULL;
 return &table;
}

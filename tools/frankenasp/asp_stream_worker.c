/* Research-only native ARM32/Bionic ASP streaming worker.
 * The library is never copied into the research executable: original /vendor/lib/libasp.so
 * and user's own Android 9 Bionic runtime are loaded on the device.
 * The constructor runs before sh-native starts; binary stdin/stdout carry fixed 8 ms quanta.
 * No Android services, microphones, networking or device state are opened here.
 */
typedef unsigned int u32;
typedef int i32;
typedef unsigned char u8;
struct ts32 { i32 sec, nsec; };
_Static_assert(sizeof(void*) == 4, "requires 32-bit Bionic");
_Static_assert(sizeof(struct ts32) == 8, "Android 9 timespec ABI");
typedef i32 (*init_fn)(void);
typedef void (*deinit_fn)(void);
typedef void *(*create_fn)(u32,u32,u32,u32,u32,u32,u32);
typedef i32 (*destroy_fn)(void*);
typedef i32 (*ref_fn)(void*,i32);
typedef i32 (*process_fn)(void*,const void*,u32*,void*,u32*,i32,struct ts32);
extern void *dlopen(const char*,int);
extern void *dlsym(void*,const char*);
extern const char *dlerror(void);
extern long read(int,void*,unsigned long);
extern long write(int,const void*,unsigned long);
extern char *getenv(const char*);
extern int clock_gettime(int,struct ts32*);
#define IN_FRAMES 768
#define IN_BYTES (IN_FRAMES*6*4)
#define OUT_FRAMES 128
#define OUT_BYTES (OUT_FRAMES*2)
static i32 in_pcm[IN_FRAMES*6] __attribute__((aligned(16)));
static u8 out_pcm[OUT_BYTES+32] __attribute__((aligned(16)));
static int read_exact_or_eof(u8 *p,u32 n) {
    u32 done=0;
    while(done<n) {
        long rc=read(0,p+done,n-done);
        if(rc<0)return -1;
        if(!rc)return done==0?0:-2;
        done+=(u32)rc;
    }
    return 1;
}
static int write_exact(const u8 *p,u32 n) {
    u32 done=0;
    while(done<n) {
        long rc=write(1,p+done,n-done);
        if(rc<=0)return -1;
        done+=(u32)rc;
    }
    return 0;
}
static void error(const char *s) {
    unsigned long n=0;
    while(s[n])n++;
    (void)write(2,s,n);
}
__attribute__((constructor))
static void stream(void) {
    char *active=getenv("TECHO5_ASP_STREAM");
    if(!active || active[0]!='1')return;
    void *lib=dlopen("/vendor/lib/libasp.so",2);
    if(!lib){error("asp: dlopen failed\n");return;}
    init_fn init=(init_fn)dlsym(lib,"asp_init");
    deinit_fn deinit=(deinit_fn)dlsym(lib,"asp_deinit");
    create_fn create=(create_fn)dlsym(lib,"asp_create_pipeline");
    destroy_fn destroy=(destroy_fn)dlsym(lib,"asp_destroy_pipeline");
    ref_fn set_ref=(ref_fn)dlsym(lib,"asp_set_ext_ref_sync_status");
    process_fn process=(process_fn)dlsym(lib,"asp_process");
    if(!init||!deinit||!create||!destroy||!set_ref||!process) {
        error("asp: missing export\n");return;
    }
    if(init()!=0){error("asp: init failed\n");return;}
    void *pipeline=create(0,4,6,96000,1,1,16000);
    if(!pipeline){error("asp: create pipeline failed\n");deinit();return;}
    if(set_ref(pipeline,2)!=0){error("asp: ref sync status failed\n");destroy(pipeline);deinit();return;}
    struct ts32 stamp={0,0};
    (void)clock_gettime(1,&stamp);
    if(write_exact((const u8*)"ASPREADY",8)){destroy(pipeline);deinit();return;}
    for(;;) {
        int got=read_exact_or_eof((u8*)in_pcm,IN_BYTES);
        if(got==0)break;
        if(got!=1){error("asp: short input\n");break;}
        for(u32 i=OUT_BYTES;i<sizeof(out_pcm);i++)out_pcm[i]=0xa5;
        u32 ni=IN_FRAMES,no=OUT_FRAMES;
        int rc=process(pipeline,in_pcm,&ni,out_pcm,&no,0,stamp);
        if(rc||ni!=IN_FRAMES||no!=OUT_FRAMES){error("asp: processing failed\n");break;}
        for(u32 i=OUT_BYTES;i<sizeof(out_pcm);i++)if(out_pcm[i]!=0xa5){
            error("asp: output buffer overrun\n");goto stop;
        }
        if(write_exact(out_pcm,OUT_BYTES)){error("asp: output write failed\n");break;}
        stamp.nsec+=8000000;
        if(stamp.nsec>=1000000000){stamp.nsec-=1000000000;stamp.sec++;}
    }
stop:
    destroy(pipeline);
    deinit();
}

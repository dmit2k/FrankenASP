/* Factory-facing entry point. Admission is closed until independently qualified.
 * The only wire configuration is CFG2/TLV; no vendor runtime is opened here. */
#include "cfg2_runtime.h"
static int ack(int code,const char *message){
 u8 h[12]={0};memcpy(h,"ACK2",4);h[4]=2;h[5]=1;
 put16(h+6,(u16)code);put16(h+8,(u16)strlen(message));
 return exact_write(1,h,12)||exact_write(1,message,(u32)strlen(message));
}
static void terminated(int sig){(void)sig;_exit(0);}
int main(int argc,char **argv){
 cfg2_descriptor session;
 (void)argc;(void)argv;
 signal(SIGTERM,terminated);signal(SIGINT,terminated);signal(SIGPIPE,terminated);
 if(exact_write(1,"ASP2",4))return 2;
 if(cfg2_read_fd(0,&session)!=CFG2_OK){
  return ack(570,"Invalid CFG2 session")?2:0;
 }
 return ack(575,"Factory production qualification unavailable")?2:0;
}

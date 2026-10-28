/* Link-wrap only in test executable: real pipes with short syscalls and EINTR. */
#include "platform.h"
extern long __real_read(int,void*,usize);
extern long __real_write(int,const void*,usize);
static u32 reads,writes;
long __wrap_read(int fd,void*p,usize n){if(++reads%17==0){errno=4;return -1;}return __real_read(fd,p,n>7?7:n);}
long __wrap_write(int fd,const void*p,usize n){if(++writes%19==0){errno=4;return -1;}return __real_write(fd,p,n>7?7:n);}

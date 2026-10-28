#define _GNU_SOURCE
/* Fault injection lives only in the offline test binary, never owner API. */
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <unistd.h>
int __real_fstat(int,struct stat *);
ssize_t __real_pread(int,void *,size_t,off_t);
ssize_t __real_write(int,const void *,size_t);
int __real_memfd_create(const char *,unsigned int);
static unsigned stats,reads,writes;
int __wrap_fstat(int fd,struct stat *s) {
 int rc=__real_fstat(fd,s);const char *at=getenv("AF_UID_AT");
 if(!rc&&at&&++stats==(unsigned)strtoul(at,NULL,10))s->st_uid++;
 return rc;
}
ssize_t __wrap_pread(int fd,void *p,size_t n,off_t offset) {
 const char *fault=getenv("AF_READ");
 if(fault&&!strcmp(fault,"fail")){errno=EIO;return -1;}
 if(fault&&!strcmp(fault,"short")){
  if(++reads%3==1){errno=EINTR;return -1;}
  if(n>17)n=17;
 }
 return __real_pread(fd,p,n,offset);
}
ssize_t __wrap_write(int fd,const void *p,size_t n) {
 const char *fault=getenv("AF_WRITE");
 if(fault&&!strcmp(fault,"fail")){errno=ENOSPC;return -1;}
 if(fault&&!strcmp(fault,"short")){
  if(++writes%3==1){errno=EINTR;return -1;}
  if(n>19)n=19;
 }
 return __real_write(fd,p,n);
}
int __wrap_memfd_create(const char *name,unsigned int flags) {
 if(getenv("AF_MEMFD")){errno=EMFILE;return -1;}
 return __real_memfd_create(name,flags);
}

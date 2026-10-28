#define _GNU_SOURCE
#include "closure.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
void ac_sha256(const unsigned char *,size_t,unsigned char[32]);
#ifdef AC_TESTING
struct pause_at {const char *event,*path;int fired;};
static void pause_hook(const char *event,const char *path,int fd,void *arg) {
 struct pause_at *p=arg;
 if(!p->fired&&!strcmp(p->event,event)&&!strcmp(p->path,path)) {
  p->fired=1;printf("PAUSED %s %s fd=%d\n",event,path,fd);fflush(stdout);
  if(getchar()!='\n')_exit(91);
 }
}
#endif
static int fdcount(void) {
 DIR *d=opendir("/proc/self/fd");if(!d)return -1;
 int count=0;struct dirent *de;
 while((de=readdir(d)))if(strcmp(de->d_name,".")&&strcmp(de->d_name,".."))count++;
 closedir(d);return count;
}
static int consume(struct ac_closure *c) {
 if(ac_count(c)>AC_MAX_FILES||ac_path(c,ac_count(c)))return -1;
 for(size_t i=0;i<ac_count(c);i++) {
  const char *path=ac_path(c,i);if(!path)return -1;
  struct ac_identity id;unsigned char hash[32];
  if(ac_identity(c,i,&id))return -1;
  unsigned char *data=malloc(id.bytes);if(!data)return -1;
  if(ac_read(c,i,0,data,id.bytes)){free(data);return -1;}
  ac_sha256(data,id.bytes,hash);free(data);
  if(memcmp(hash,id.sha256,32))return -1;
#ifdef AC_TESTING
  int fd=ac_test_snapshot_fd(c,i);
  int seals=fcntl(fd,F_GET_SEALS);
  if(seals!=(F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL))return -1;
  errno=0;
  if(pwrite(fd,"X",1,0)!=-1||errno!=EPERM)return -1;
  if(ftruncate(fd,0)!=-1||errno!=EPERM)return -1;
#endif
  printf("ASSET %s %" PRIu64 ":%" PRIu64 " %zu ",path,id.device,id.inode,id.bytes);
  for(size_t j=0;j<32;j++)printf("%02x",hash[j]);
  puts("");
 }
 if(ac_read(c,AC_MAX_FILES,0,NULL,0)!=-1||ac_read(c,0,SIZE_MAX,NULL,0)!=-1)return -1;
 return 0;
}
int main(int argc,char **argv) {
 int repeats=1,production=0;
#ifdef AC_TESTING
 struct pause_at pause={"never","",0};
#endif
 if(argc==2&&!strcmp(argv[1],"--production-owner"))production=1;
 else if(argc==3&&!strcmp(argv[1],"--repeat")) {
  char *end;long n=strtol(argv[2],&end,10);
  if(*end||n<1||n>2000)return 90;
  repeats=(int)n;
 }
#ifdef AC_TESTING
 else if(argc==4&&!strcmp(argv[1],"--pause")){pause.event=argv[2];pause.path=argv[3];}
#endif
 else if(argc!=1)return 90;
 struct stat cwd_before,cwd_after;
 if(stat(".",&cwd_before))return 95;
 int before=fdcount(),failures=0;enum ac_error last=AC_OK;
 for(int i=0;i<repeats;i++) {
  struct ac_closure *c=NULL;
#ifdef AC_TESTING
  last=production?ac_open(4,&c):ac_test_open(4,geteuid(),pause_hook,&pause,&c);
#else
  (void)production;last=ac_open(4,&c);
#endif
  if(last){if(c)return 92;failures++;}
  else if(repeats==1&&consume(c)){ac_close(&c);return 93;}
  ac_close(&c);ac_close(&c);
 }
 int after=fdcount();
 if(stat(".",&cwd_after)||cwd_before.st_dev!=cwd_after.st_dev||cwd_before.st_ino!=cwd_after.st_ino)return 95;
 printf("RESULT %s repeats=%d failures=%d fd=%d:%d\n",ac_error_string(last),repeats,failures,before,after);
 if(before<0||after!=before)return 94;
 return failures?20+(int)last:0;
}

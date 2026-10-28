#include "platform.h"
/* Android ARM stat64 mode16/uid24 offsets; independently guest-tested.
 * Root/current owner only; no group/world write and no symlink component. */
static int checked(int fd,int directory){
 u32 mode,uid;
#ifdef ASP2_BIONIC
 u8 s[128] __attribute__((aligned(8)));
 if(fstat64(fd,s))return -1;
 memcpy(&mode,s+16,4);memcpy(&uid,s+24,4);
#else
 struct stat s;if(fstat(fd,&s))return -1;mode=(u32)s.st_mode;uid=(u32)s.st_uid;
#endif
 if((mode&022)||(uid!=0&&uid!=geteuid()))return -1;
 return (mode&0170000)==(directory?0040000:0100000)?0:-1;
}
int secure_open(const char*path,int directory){
 char part[256];usize n=strlen(path);
 if(n<2||n>=sizeof part||path[0]!='/')return -1;
 for(usize j=0;j<n;j++)if(path[j]=='/'&&path[j+1]=='.'&&(path[j+2]=='/'||path[j+2]==0||(path[j+2]=='.'&&(path[j+3]=='/'||path[j+3]==0))))return -1;
 memcpy(part,path,n+1);
 for(usize i=1;i<=n;i++)if(part[i]=='/'||part[i]==0){
  char saved=part[i];part[i]=0;
  if(i==1||part[i-1]=='/')return -1;
  int dir=saved?1:directory;
  int fd=open(part,ASP_NOFOLLOW|524288|(dir?ASP_DIRECTORY:0));part[i]=saved;
  if(fd<0)return -1;
  if(checked(fd,dir)){close(fd);return -1;}
  if(!saved)return fd;
  close(fd);
 }
 return -1;
}
int exact_read(int fd,void*dst,u32 n){
 u8*p=dst;u32 done=0;
 while(done<n){long r=read(fd,p+done,n-done);
  if(r<0&&errno==4)continue;
  if(r<0)return -1;
  if(!r)return done?-1:0;
  done+=(u32)r;
 }
 return 1;
}
int exact_write(int fd,const void*src,u32 n){
 const u8*p=src;u32 done=0;
 while(done<n){long r=write(fd,p+done,n-done);
  if(r<0&&errno==4)continue;
  if(r<=0)return -1;
  done+=(u32)r;
 }
 return 0;
}

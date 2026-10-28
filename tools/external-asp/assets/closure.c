#define _GNU_SOURCE
#include "closure.h"
#include <dirent.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

void ac_sha256(const unsigned char *, size_t, unsigned char[32]);
static const char *const dirs[] = {
 "etc", "lib", "lib/rootfs", "lib/rootfs/system", "lib/rootfs/system/bin",
 "lib/rootfs/system/lib", "lib/rootfs/vendor", "lib/rootfs/vendor/etc",
 "lib/rootfs/vendor/lib", "lib/rootfs/opt", "lib/rootfs/opt/external-asp"
};
static const char *const files[] = {
 "etc/profile.conf",
 "lib/rootfs/opt/external-asp/offline-child.elf",
 "lib/rootfs/system/bin/linker",
 "lib/rootfs/system/lib/libfixture-base.so",
 "lib/rootfs/vendor/etc/fixture.conf",
 "lib/rootfs/vendor/etc/optional.conf",
 "lib/rootfs/vendor/lib/libfixture-top.so"
};
#define ND (sizeof dirs / sizeof dirs[0])
#define NF (sizeof files / sizeof files[0])
struct blob { int source, snapshot; struct stat stat; size_t size; unsigned char hash[32]; };
struct ac_closure {
 int root, directory[ND]; struct stat root_stat, dir_stat[ND];
 struct blob manifest, file[NF]; size_t total, count; unsigned present;
 uid_t owner;
#ifdef AC_TESTING
 ac_hook hook; void *hook_arg;
#endif
};
static void hook(struct ac_closure *c, const char *event, const char *path, int fd) {
#ifdef AC_TESTING
 if(c->hook)c->hook(event,path,fd,c->hook_arg);
#else
 (void)c;(void)event;(void)path;(void)fd;
#endif
}
static enum ac_error checked(int fd, uid_t owner, int directory, struct stat *s) {
 if(fstat(fd,s))return AC_IO;
 if(s->st_uid!=owner || (s->st_mode & 07022))return AC_POLICY;
 if(directory) {
  if(!S_ISDIR(s->st_mode) || !(s->st_mode&S_IXUSR))return AC_POLICY;
 } else if(!S_ISREG(s->st_mode) || s->st_nlink!=1 || !(s->st_mode&S_IRUSR))return AC_POLICY;
 return AC_OK;
}
static int same(const struct stat *a,const struct stat *b) {
 return a->st_dev==b->st_dev && a->st_ino==b->st_ino && a->st_size==b->st_size &&
 a->st_uid==b->st_uid && a->st_gid==b->st_gid && a->st_mode==b->st_mode &&
 a->st_nlink==b->st_nlink && a->st_mtim.tv_sec==b->st_mtim.tv_sec &&
 a->st_mtim.tv_nsec==b->st_mtim.tv_nsec && a->st_ctim.tv_sec==b->st_ctim.tv_sec &&
 a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
}
static int readall(int fd, unsigned char *p,size_t n) {
 size_t done=0;
 while(done<n){ssize_t r=pread(fd,p+done,n-done,(off_t)done);
  if(r<0&&errno==EINTR)continue;
  if(r<=0)return -1;
  done+=(size_t)r;
 }
 return 0;
}
static int writeall(int fd,const unsigned char *p,size_t n) {
 size_t done=0;
 while(done<n){ssize_t r=write(fd,p+done,n-done);
  if(r<0&&errno==EINTR)continue;
  if(r<=0)return -1;
  done+=(size_t)r;
 }
 return 0;
}
/* Each child is one literal allowlisted component, relative to its pinned parent. */
static int parent(struct ac_closure *c,const char *path,const char **base) {
 const char *slash=strrchr(path,'/');
 if(!slash){*base=path;return c->root;}
 size_t n=(size_t)(slash-path);*base=slash+1;
 for(size_t i=0;i<ND;i++)if(strlen(dirs[i])==n&&!memcmp(dirs[i],path,n))return c->directory[i];
 return -1;
}
static enum ac_error snapshot(struct ac_closure *c,const char *path,struct blob *b,size_t cap) {
 const char *base;int p=parent(c,path,&base);struct stat after;
 b->source=openat(p,base,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
 if(b->source<0)return AC_IO;
 hook(c,"file-open",path,b->source);
 enum ac_error e=checked(b->source,c->owner,0,&b->stat);if(e)return e;
 if(b->stat.st_size<=0 || (uint64_t)b->stat.st_size>cap)return AC_LIMIT;
 b->size=(size_t)b->stat.st_size;
 if(b->size>AC_TOTAL_CAP-c->total)return AC_LIMIT;
 unsigned char *data=malloc(b->size);if(!data)return AC_MEMORY;
 if(readall(b->source,data,b->size)){free(data);return AC_IO;}
 if(fstat(b->source,&after)||!same(&b->stat,&after)){free(data);return AC_CHANGED;}
 ac_sha256(data,b->size,b->hash);
 b->snapshot=memfd_create("asp2-offline-asset",MFD_CLOEXEC|MFD_ALLOW_SEALING);
 if(b->snapshot<0){free(data);return AC_IO;}
 int fail=writeall(b->snapshot,data,b->size);free(data);
 if(fail || fcntl(b->snapshot,F_ADD_SEALS,F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL)<0)return AC_IO;
 c->total+=b->size;
 hook(c,"snapshot",path,b->source);
 return AC_OK;
}
static void release_blob(struct blob *b) {
 if(b->source>=0)close(b->source);
 if(b->snapshot>=0)close(b->snapshot);
}
void ac_close(struct ac_closure **pc) {
 if(!pc||!*pc)return;
 struct ac_closure *c=*pc;*pc=NULL;
 for(size_t i=0;i<NF;i++)release_blob(&c->file[i]);
 release_blob(&c->manifest);
 for(size_t i=0;i<ND;i++)if(c->directory[i]>=0)close(c->directory[i]);
 if(c->root>=0)close(c->root);
 free(c);
}
static int file_index(const char *s) {
 for(size_t i=0;i<NF;i++)if(!strcmp(s,files[i]))return (int)i;
 return -1;
}
/* Lowercase ASCII only; reject NULs by length, not strlen of untrusted bytes. */
static int path_valid(const unsigned char *s,size_t n) {
 if(!n||n>=AC_MAX_PATH||s[0]=='/'||s[n-1]=='/')return 0;
 size_t component=0;
 for(size_t i=0;i<n;i++) {
  unsigned char b=s[i];
  if(b=='/'){if(!component)return 0;component=0;continue;}
  if(!((b>='a'&&b<='z')||(b>='0'&&b<='9')||b=='-'||b=='_'||b=='.'))return 0;
  component++;
  if(component>80)return 0;
 }
 /* Empty/dot/dotdot and any non-allowlisted path are rejected below. */
 return 1;
}
static enum ac_error manifest(struct ac_closure *c) {
 unsigned char text[4096];unsigned required=0;char previous[AC_MAX_PATH]={0};
 if(c->manifest.size>sizeof text||readall(c->manifest.snapshot,text,c->manifest.size))return AC_MANIFEST;
 for(size_t i=0;i<NF;i++)if(i!=5)required|=1u<<i;
 size_t pos=0;
 while(pos<c->manifest.size) {
  size_t end=pos;while(end<c->manifest.size&&text[end]!='\n')end++;
  if(end==c->manifest.size||end-pos<67||text[pos+64]!=' '||text[pos+65]!=' ')return AC_MANIFEST;
  unsigned char hash[32];
  for(size_t j=0;j<64;j++) {
   unsigned char ch=text[pos+j];int v=ch>='0'&&ch<='9'?ch-'0':ch>='a'&&ch<='f'?ch-'a'+10:-1;
   if(v<0)return AC_MANIFEST;
   if(!(j%2))hash[j/2]=(unsigned char)(v<<4);else hash[j/2]|=(unsigned char)v;
  }
  size_t len=end-pos-66;char path[AC_MAX_PATH];
  if(!path_valid(text+pos+66,len))return AC_MANIFEST;
  memcpy(path,text+pos+66,len);path[len]=0;
  int ix=file_index(path);
  if(ix<0||strcmp(previous,path)>=0||(c->present&(1u<<ix)))return AC_MANIFEST;
  strcpy(previous,path);
  enum ac_error e=snapshot(c,path,&c->file[ix],ix==0?256:AC_FILE_CAP);if(e)return e;
  if(memcmp(hash,c->file[ix].hash,32))return AC_HASH;
  c->present|=1u<<ix;c->count++;
  if(c->count>AC_MAX_FILES)return AC_LIMIT;
  pos=end+1;
 }
 return (c->present&required)==required?AC_OK:AC_MANIFEST;
}
static enum ac_error profile(struct ac_closure *c) {
 static const char expected[]="ASP2-FD4-OFFLINE-V1\nplatform=athena\nbackend=synthetic\nfactory_admission=disabled\nmanifest=etc/assets.sha256\n";
 unsigned char b[256];
 if(c->file[0].size!=sizeof expected-1||readall(c->file[0].snapshot,b,sizeof expected-1)||memcmp(b,expected,sizeof expected-1))return AC_PROFILE;
 return AC_OK;
}
static int known_child(const char *dir,const char *name,const char *full) {
 (void)dir;(void)name;
 if(!strcmp(full,"etc/assets.sha256"))return 1;
 if(file_index(full)>=0)return 1;
 for(size_t i=0;i<ND;i++)if(!strcmp(dirs[i],full))return 1;
 return 0;
}
static enum ac_error enumerate(struct ac_closure *c) {
 /* Scan every pinned etc/lib directory, including empty required directories.
  * bin is host launcher territory, intentionally outside asset closure. */
 for(size_t i=0;i<ND;i++) {
  int fd=openat(c->directory[i],".",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
  if(fd<0)return AC_IO;
  DIR *d=fdopendir(fd);if(!d){close(fd);return AC_IO;}
  enum ac_error err=AC_OK;struct dirent *de;size_t count=0;
  for(;;) {
   errno=0;de=readdir(d);
   if(!de){if(errno)err=AC_IO;break;}
   if(!strcmp(de->d_name,".")||!strcmp(de->d_name,".."))continue;
   if(++count>ND+NF+1){err=AC_LIMIT;break;}
   size_t n=strlen(dirs[i]),m=strlen(de->d_name);char full[AC_MAX_PATH];
   if(n+1+m>=sizeof full){err=AC_POLICY;break;}
   memcpy(full,dirs[i],n);full[n]='/';memcpy(full+n+1,de->d_name,m+1);
   if(!known_child(dirs[i],de->d_name,full)){err=AC_POLICY;break;}
   int ix=file_index(full);
   if(ix>=0&&!(c->present&(1u<<ix))){err=AC_MANIFEST;break;}
   /* Verify names still reference pinned inodes; no new files are consumed. */
   struct stat s;const struct stat *want=NULL;
   if(!strcmp(full,"etc/assets.sha256"))want=&c->manifest.stat;
   if(ix>=0)want=&c->file[ix].stat;
   for(size_t j=0;j<ND;j++)if(!strcmp(full,dirs[j]))want=&c->dir_stat[j];
   if(!want||fstatat(c->directory[i],de->d_name,&s,AT_SYMLINK_NOFOLLOW)||!same(want,&s)){err=AC_CHANGED;break;}
  }
  closedir(d);if(err)return err;
 }
 return AC_OK;
}
static int bounds(size_t n,uint64_t offset,uint64_t length) {
 return offset<=n&&length<=n-offset;
}
struct elf_info {char interp[80];char needed[8][80];size_t count;};
/* Deliberately narrow native Linux ELF64/LE/x86_64 parser. Never dlopen/ldd. */
static enum ac_error elf(const struct blob *b,struct elf_info *out) {
 unsigned char *data=malloc(b->size);if(!data)return AC_MEMORY;
 enum ac_error result=AC_ELF;Elf64_Ehdr h;Elf64_Phdr ph[32];
 memset(out,0,sizeof *out);
 if(readall(b->snapshot,data,b->size)||b->size<sizeof h)goto done;
 memcpy(&h,data,sizeof h);
 if(memcmp(h.e_ident,ELFMAG,SELFMAG)||h.e_ident[EI_CLASS]!=ELFCLASS64||
 h.e_ident[EI_DATA]!=ELFDATA2LSB||h.e_ident[EI_VERSION]!=EV_CURRENT||
 h.e_version!=EV_CURRENT||h.e_machine!=EM_X86_64||(h.e_type!=ET_DYN&&h.e_type!=ET_EXEC)||
 h.e_ehsize!=sizeof h||h.e_phentsize!=sizeof ph[0]||!h.e_phnum||h.e_phnum>32||
 !bounds(b->size,h.e_phoff,(uint64_t)h.e_phnum*sizeof ph[0]))goto done;
 memcpy(ph,data+h.e_phoff,(size_t)h.e_phnum*sizeof ph[0]);
 int dyn=-1;uint64_t strings=0,strsize=0;uint64_t needs[8];size_t nneed=0;
 for(size_t i=0;i<h.e_phnum;i++) {
  if(!bounds(b->size,ph[i].p_offset,ph[i].p_filesz))goto done;
  if(ph[i].p_type==PT_INTERP) {
   size_t n=(size_t)ph[i].p_filesz;
   if(out->interp[0]||n<2||n>sizeof out->interp||data[ph[i].p_offset+n-1]||
    memchr(data+ph[i].p_offset,0,n-1))goto done;
   memcpy(out->interp,data+ph[i].p_offset,n);
  }
  if(ph[i].p_type==PT_DYNAMIC){if(dyn>=0)goto done;dyn=(int)i;}
 }
 if(dyn<0)goto done;
 Elf64_Phdr *dp=&ph[dyn];int terminated=0,seenstr=0,seensize=0;
 if(dp->p_filesz%sizeof(Elf64_Dyn)||dp->p_filesz/sizeof(Elf64_Dyn)>256)goto done;
 for(size_t i=0;i<dp->p_filesz/sizeof(Elf64_Dyn);i++) {
  Elf64_Dyn d;memcpy(&d,data+dp->p_offset+i*sizeof d,sizeof d);
  if(d.d_tag==DT_NULL){terminated=1;break;}
  if(d.d_tag==DT_RPATH||d.d_tag==DT_RUNPATH||d.d_tag==DT_AUDIT||d.d_tag==DT_DEPAUDIT||d.d_tag==DT_FILTER||d.d_tag==DT_AUXILIARY)goto done;
  if(d.d_tag==DT_STRTAB){if(seenstr++)goto done;strings=d.d_un.d_ptr;}
  if(d.d_tag==DT_STRSZ){if(seensize++)goto done;strsize=d.d_un.d_val;}
  if(d.d_tag==DT_NEEDED){if(nneed==8)goto done;needs[nneed++]=d.d_un.d_val;}
 }
 if(!terminated||!seenstr||!seensize||!strsize)goto done;
 uint64_t off=0;int found=0;
 for(size_t i=0;i<h.e_phnum;i++)if(ph[i].p_type==PT_LOAD&&strings>=ph[i].p_vaddr) {
  uint64_t delta=strings-ph[i].p_vaddr;
  if(delta<=ph[i].p_filesz&&strsize<=ph[i].p_filesz-delta){
   if(found++)goto done;
   off=ph[i].p_offset+delta;
  }
 }
 if(!found||!bounds(b->size,off,strsize))goto done;
 for(size_t i=0;i<nneed;i++) {
  if(needs[i]>=strsize)goto done;
  const unsigned char *s=data+off+needs[i];size_t avail=(size_t)(strsize-needs[i]);
  const unsigned char *end=memchr(s,0,avail);if(!end)goto done;
  size_t n=(size_t)(end-s);if(!n||n>=80||!path_valid(s,n)||memchr(s,'/',n))goto done;
  memcpy(out->needed[i],s,n);out->needed[i][n]=0;
  for(size_t j=0;j<i;j++)if(!strcmp(out->needed[i],out->needed[j]))goto done;
 }
 out->count=nneed;result=AC_OK;
done:
 free(data);return result;
}
static enum ac_error dependencies(struct ac_closure *c) {
 const size_t indices[]={1,2,3,6};struct elf_info info[4];
 for(size_t i=0;i<4;i++){
  enum ac_error e=elf(&c->file[indices[i]],&info[i]);if(e)return e;
  if(i==0){if(strcmp(info[i].interp,"/system/bin/linker"))return AC_ELF;}
  else if(info[i].interp[0])return AC_ELF;
  for(size_t n=0;n<info[i].count;n++) {
   size_t matches=0;
   for(size_t j=2;j<4;j++) {
    const char *base=strrchr(files[indices[j]],'/')+1;
    if(!strcmp(base,info[i].needed[n]))matches++;
   }
   if(matches!=1)return AC_ELF;
  }
 }
 /* All four ELFs are inspected, so transitive and cyclic edges are bounded. */
 return AC_OK;
}
static enum ac_error open_impl(int rootfd,uid_t uid,
#ifdef AC_TESTING
 ac_hook callback,void *arg,
#endif
 struct ac_closure **out) {
 if(!out)return AC_ARGUMENT;
 *out=NULL;if(rootfd<0)return AC_ARGUMENT;
 struct ac_closure *c=calloc(1,sizeof *c);if(!c)return AC_MEMORY;
 c->root=-1;c->manifest.source=c->manifest.snapshot=-1;c->owner=uid;
 for(size_t i=0;i<ND;i++)c->directory[i]=-1;
 for(size_t i=0;i<NF;i++)c->file[i].source=c->file[i].snapshot=-1;
#ifdef AC_TESTING
 c->hook=callback;c->hook_arg=arg;
#endif
 enum ac_error e=AC_IO;
 c->root=fcntl(rootfd,F_DUPFD_CLOEXEC,5);if(c->root<0)goto fail;
 e=checked(c->root,uid,1,&c->root_stat);if(e)goto fail;
 hook(c,"root","",c->root);
 for(size_t i=0;i<ND;i++) {
  const char *base;int p=parent(c,dirs[i],&base);
  c->directory[i]=openat(p,base,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
  if(c->directory[i]<0){e=AC_IO;goto fail;}
  e=checked(c->directory[i],uid,1,&c->dir_stat[i]);if(e)goto fail;
  hook(c,"directory",dirs[i],c->directory[i]);
 }
 e=snapshot(c,"etc/assets.sha256",&c->manifest,4096);if(e)goto fail;
 e=manifest(c);if(e)goto fail;
 e=profile(c);if(e)goto fail;
 e=enumerate(c);if(e)goto fail;
 e=dependencies(c);if(e)goto fail;
 hook(c,"ready","",c->root);
 *out=c;return AC_OK;
fail:
 ac_close(&c);return e;
}
enum ac_error ac_open(int rootfd,struct ac_closure **out) {
 return open_impl(rootfd,0,
#ifdef AC_TESTING
 NULL,NULL,
#endif
 out);
}
static int slot(const struct ac_closure *,size_t);
#ifdef AC_TESTING
enum ac_error ac_test_open(int fd,uid_t uid,ac_hook callback,void *arg,struct ac_closure **out) {
 return open_impl(fd,uid,callback,arg,out);
}
int ac_test_snapshot_fd(const struct ac_closure *c,size_t i) {
 int n=slot(c,i);return n<0?-1:c->file[n].snapshot;
}
#endif
size_t ac_count(const struct ac_closure *c){return c?c->count:0;}
static int slot(const struct ac_closure *c,size_t index) {
 if(!c||index>=c->count)return -1;
 for(size_t i=0;i<NF;i++)if(c->present&(1u<<i)) {
  if(!index)return (int)i;
  index--;
 }
 return -1;
}
const char *ac_path(const struct ac_closure *c,size_t i) {
 int n=slot(c,i);return n<0?NULL:files[n];
}
int ac_identity(const struct ac_closure *c,size_t i,struct ac_identity *out) {
 int n=slot(c,i);if(n<0||!out)return -1;
 const struct blob *b=&c->file[n];
 out->device=(uint64_t)b->stat.st_dev;out->inode=(uint64_t)b->stat.st_ino;
 out->bytes=b->size;memcpy(out->sha256,b->hash,32);return 0;
}
int ac_read(const struct ac_closure *c,size_t i,size_t offset,void *out,size_t n) {
 int ix=slot(c,i);
 if(ix<0||(!out&&n)||offset>c->file[ix].size||n>c->file[ix].size-offset)return -1;
 size_t done=0;
 while(done<n){ssize_t r=pread(c->file[ix].snapshot,(unsigned char *)out+done,n-done,(off_t)(offset+done));
  if(r<0&&errno==EINTR)continue;
  if(r<=0)return -1;
  done+=(size_t)r;
 }
 return 0;
}
const char *ac_error_string(enum ac_error e) {
 static const char *const text[]={"ok","argument","io","policy","limit","manifest","hash","profile","changed","elf","memory"};
 return (unsigned)e<sizeof text/sizeof text[0]?text[e]:"unknown";
}

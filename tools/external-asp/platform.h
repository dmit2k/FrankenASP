#ifndef ASP_PLATFORM_H
#define ASP_PLATFORM_H
#ifdef ASP2_BIONIC
typedef unsigned char u8; typedef unsigned short u16; typedef unsigned int u32;
typedef unsigned long long u64; typedef signed short i16; typedef signed int i32;
typedef signed long long i64; typedef unsigned int usize;
typedef int sig_atomic_t;
#define SIGINT 2
#define SIGPIPE 13
#define SIGTERM 15
#define NULL ((void *)0)
extern long read(int,void*,unsigned long); extern long write(int,const void*,unsigned long);
extern int pause(void); extern int dup(int); extern int dup2(int,int); extern int fcntl(int,int,...);
extern int open(const char*,int,...); extern int close(int);
extern void *memcpy(void*,const void*,usize); extern void *memset(void*,int,usize);
extern int memcmp(const void*,const void*,usize); extern usize strlen(const char*);
extern int strcmp(const char*,const char*); extern char *getenv(const char*);
extern void *dlopen(const char*,int); extern void *dlsym(void*,const char*); extern int dlclose(void*);
extern int *__errno(void);
#define errno (*__errno())
extern int fstat64(int,void*); extern unsigned int geteuid(void);
extern void (*signal(int,void(*)(int)))(int); extern void _exit(int);
_Static_assert(sizeof(void*)==4,"ARM32 only");
#else
#include <stdint.h>
#include <stddef.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <signal.h>
#include <string.h>
#include <errno.h>
#include <stdlib.h>
#include <dlfcn.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;
typedef int16_t i16; typedef int32_t i32; typedef int64_t i64; typedef size_t usize;
#endif
#ifdef ASP2_BIONIC
#define ASP_DIRECTORY 16384
#define ASP_NOFOLLOW 32768
#else
#define ASP_DIRECTORY 65536
#define ASP_NOFOLLOW 131072
#endif
struct asp_time32 {i32 sec,nsec;};
_Static_assert(sizeof(struct asp_time32)==8,"timespec32 by value");
int secure_open(const char*,int);
int exact_read(int,void*,u32);
int exact_write(int,const void*,u32);
int file_sha256(const char*,u8*);
void sha256_bytes(const u8*,usize,u8*);
#endif

#ifndef ASP_ASSET_CLOSURE_H
#define ASP_ASSET_CLOSURE_H
#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>
/* Linux native offline component. Caller exclusively owns FD4 during open.
 * No paths, ENV owner override, loader execution or factory admission. */
#define AC_MAX_FILES 8
#define AC_MAX_PATH 160
#define AC_FILE_CAP (1024u * 1024u)
#define AC_TOTAL_CAP (4u * 1024u * 1024u)
struct ac_closure;
struct ac_identity { uint64_t device, inode; size_t bytes; unsigned char sha256[32]; };
enum ac_error { AC_OK, AC_ARGUMENT, AC_IO, AC_POLICY, AC_LIMIT, AC_MANIFEST,
                AC_HASH, AC_PROFILE, AC_CHANGED, AC_ELF, AC_MEMORY };
/* Output is NULL on failure; rootfd is borrowed, never closed or repositioned. */
enum ac_error ac_open(int rootfd, struct ac_closure **out);
void ac_close(struct ac_closure **closure);
size_t ac_count(const struct ac_closure *closure);
const char *ac_path(const struct ac_closure *closure, size_t index);
int ac_identity(const struct ac_closure *, size_t, struct ac_identity *);
/* Copies only sealed snapshot bytes; no filesystem re-resolution. */
int ac_read(const struct ac_closure *, size_t, size_t offset, void *, size_t);
const char *ac_error_string(enum ac_error);
#ifdef AC_TESTING
/* Compile-time-only seam. Never linked into the production-owner binary. */
typedef void (*ac_hook)(const char *event, const char *path, int fd, void *arg);
enum ac_error ac_test_open(int, uid_t, ac_hook, void *, struct ac_closure **);
int ac_test_snapshot_fd(const struct ac_closure *, size_t);
#endif
#endif

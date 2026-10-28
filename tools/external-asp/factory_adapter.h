#ifndef ASP_FACTORY_ADAPTER_H
#define ASP_FACTORY_ADAPTER_H
#include "core.h"
#if defined(ASP2_FACTORY_MOCK) == defined(ASP2_FACTORY_REAL)
#error "Select exactly one factory binding"
#endif
#if defined(ASP2_FACTORY_REAL) && !defined(ASP2_BIONIC)
#error "Real factory binding requires ARM32 Bionic"
#endif
/* Independently declared opaque ABI seam; no gain argument.
 * The vendor Calibrator is the sole calibration execution authority.
 * Captured-slot Q30 is never passed as an external multiplier. */
struct factory_abi {
 i32 (*init)(void);
 void *(*create)(u32,u32,u32,u32,u32,u32,u32);
 i32 (*ref_sync)(void *,i32);
 i32 (*process)(void *,const void *,u32 *,void *,u32 *,i32,struct asp_time32);
 i32 (*destroy)(void *);
 void (*deinit)(void);
};
struct factory_adapter {
 struct factory_abi abi;
 void *pipeline;
 struct asp_time32 stamp;
 int initialized,terminal,closed;
};
extern volatile sig_atomic_t factory_cancelled;
#ifdef ASP2_FACTORY_MOCK
const struct factory_abi *offline_mock_abi(void);
#endif
int factory_adapter_open(struct factory_adapter *,const struct factory_abi *);
int factory_adapter_process(struct factory_adapter *,const i32[768*6],i16[128]);
int factory_adapter_close(struct factory_adapter *);
#endif

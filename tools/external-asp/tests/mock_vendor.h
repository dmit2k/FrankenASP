#ifndef OFFLINE_MOCK_VENDOR_H
#define OFFLINE_MOCK_VENDOR_H
#include "../factory_adapter.h"
struct mock_observation {
 unsigned init,create,ref,process,destroy,deinit,violations;
 u64 quanta;
 i32 last_input[768*6];
 struct asp_time32 last_stamp;
 char order[64];
};
extern struct mock_observation mock_seen;
void mock_reset(const char *,u64);
i32 asp_init(void);
void *asp_create_pipeline(u32,u32,u32,u32,u32,u32,u32);
i32 asp_set_ext_ref_sync_status(void *,i32);
i32 asp_process(void *,const void *,u32 *,void *,u32 *,i32,struct asp_time32);
i32 asp_destroy_pipeline(void *);
void asp_deinit(void);
#endif

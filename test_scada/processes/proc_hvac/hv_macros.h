#ifndef HV_MACROS_H
#define HV_MACROS_H

#include "scf_tag.h"
#include "scf_const.h"

/* Process-local flowing macros (in a header so the call-graph macro
 * collector can see them). Each is single-level => followed to a
 * direct framework call. hv_ctx is defined in hv_zones.c. */
extern TagCtx hv_ctx;

/* injects &hv_ctx as arg1; zone->arg2, v->arg3 */
#define HV_SET_TEMP(zone, v)  scf_tag_write(&hv_ctx, (zone), (v))
/* injects &hv_ctx and literal 0 */
#define HV_ZERO(zone)         scf_tag_write(&hv_ctx, (zone), 0)
/* forwards to a direct config-clear */
#define HV_CLEAR(id)          scf_cfg_clear((id))
/* injects the shared context; reads into buf */
#define HV_READ(zone, buf)    scf_tag_read(&hv_ctx, (zone), (buf))

#endif /* HV_MACROS_H */

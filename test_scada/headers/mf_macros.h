#ifndef MF_MACROS_H
#define MF_MACROS_H

#include "scf_tag.h"
#include "scf_const.h"

/* ============================================================
 * Macros for the macro_flow module. Live in a HEADER because the
 * call-graph macro collector only reads .h files.
 *
 * IMPORTANT analyzer behaviour (documented on purpose):
 *  - A function-like macro is followed only ONE hop, to the first
 *    call it expands to. So a SINGLE-level macro that forwards
 *    directly to a framework API IS followed; a CHAINED macro
 *    (macro -> macro -> api) resolves only to the intermediate
 *    macro and stops (edge case to demonstrate the limitation).
 * ============================================================ */

extern TagCtx g_mf_ctx;

/* single-level, WORKS: expands directly to scf_tag_write.
 * injects &g_mf_ctx as arg1 and literal 0 as arg3; pid -> arg2. */
#define MF_ZERO(pid)      scf_tag_write(&g_mf_ctx, (pid), 0)

/* single-level, WORKS: injects &g_mf_ctx as arg1; pid->arg2, v->arg3. */
#define MF_SET2(pid, v)   scf_tag_write(&g_mf_ctx, (pid), (v))

/* CHAINED, resolves only to MF_SET2 then stops (does NOT reach
 * scf_tag_write through the analyzer). */
#define MF_SET(pid, v)    MF_SET2((pid), (v))

#endif /* MF_MACROS_H */

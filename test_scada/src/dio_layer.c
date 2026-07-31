/*
 * dio_layer.c - DIO pointer-getter indirection layer (test-tracer fixture)
 *
 * This module demonstrates:
 * (a) Selection among multiple calls to the same API via the CONSIDER-THIS-CALL marker
 * (b) Parameter flow (fno from caller -> scf_tag_open arg2)
 * (c) Macro-expanded calls (TAG_OPEN_RD, TAG_SNAPSHOT)
 */

#include "app.h"
#include "scf_tag.h"
#include "scf_const.h"

/* ====================================================================
 * GROUND TRUTH
 *
 * DioGetPtr(int fno):
 *   - Calls scf_tag_open 3 times; tracer selects the one marked
 *     with the CONSIDER-THIS-CALL annotation
 *   - arg2 = fno (parameter value from caller)
 *   - When called as DioGetPtr(PT_TANK_LEVEL=0x1003), arg2 resolves to 0x1003
 *   - type = OPENF  launch_via = FORK (from init_subsystems)
 *
 * dio_prime_cache(int fno) -> dio_lookup(int fno):
 *   - dio_lookup calls TAG_SNAPSHOT(fno, buf) macro
 *   - Macro expands to: scf_tag_read(&g_snap_ctx, fno, buf)
 *   - Tracer sees: scf_tag_read with arg1=&g_snap_ctx, arg2=fno
 *   - type = READF  arg2_resolved = fno (parameter)
 *
 * Direct scf_tag_read(&rc, PT_PRESSURE, buf):
 *   - Direct call in dio_prime_cache
 *   - arg2 = PT_PRESSURE = 0x1006
 *   - type = READF
 *
 * ==================================================================== */

/*
 * DioGetPtr - pointer-getter layer for tag operations.
 *
 * Returns a pointer to the opened tag context. Demonstrates call-site
 * selection when the same API is invoked multiple times in one function.
 * The CONSIDER-THIS-CALL annotation directs the tracer to the
 * point-id from the caller (fno parameter).
 */
void *DioGetPtr(int fno)
{
    static TagCtx c_a, c_b, c_c;
    void *p;

    /* Sibling call 1: PT_PUMP_SPEED — ignored by tracer */
    (void)scf_tag_open(&c_a, PT_PUMP_SPEED, SCF_READ_LOCK);

    /* Sibling call 2: TAG_OPEN_RD macro expansion — ignored by tracer */
    (void)TAG_OPEN_RD(&c_b, PT_MOTOR_TEMP);

    /* Selected call: arg2 is the fno parameter (caller's value) */
    p = scf_tag_open(&c_c, fno, SCF_WRITE_LOCK);  /*CONSIDER THIS CALL*/

    return p;
}

/*
 * dio_lookup - file-local helper for snapshot reads.
 *
 * Uses the TAG_SNAPSHOT macro which injects &g_snap_ctx as the
 * leading context argument. The point_id (fno) becomes arg2 after
 * macro expansion.
 */
static int dio_lookup(int fno)
{
    char buf[32];

    /* Macro-expanded call: TAG_SNAPSHOT -> scf_tag_read(&g_snap_ctx, fno, buf) */
    return TAG_SNAPSHOT(fno, buf);
}

/*
 * dio_prime_cache - prepare cache from snapshot storage.
 *
 * Exercises two distinct patterns:
 * 1. Direct scf_tag_read with literal PT_PRESSURE
 * 2. Delegation to dio_lookup, which uses a macro that injects context
 */
int dio_prime_cache(int fno)
{
    static TagCtx rc;
    char buf[32];

    /*
     * Direct call: ensures scf_tag_read is registered in the framework.
     * arg2 = PT_PRESSURE (literal constant)
     */
    (void)scf_tag_read(&rc, PT_PRESSURE, buf);

    /* Delegate to helper, which uses the TAG_SNAPSHOT macro */
    return dio_lookup(fno);
}

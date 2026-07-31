#include "app.h"
#include "mf_macros.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_const.h"

/* ============================================================
 * GROUND TRUTH
 *
 * path 1: main -> mf_apply_config -> mf_write_setpoint -> scf_tag_write (direct)
 *         type=WRITEF launch_via=FORK  arg2=pid=PT_SETPOINT=0x1007  arg3=42
 *
 * path 2: mf_write_setpoint -> MF_ZERO (macro expansion) -> scf_tag_write
 *         arg1=&g_mf_ctx (injected), arg2=pid=PT_SETPOINT=0x1007, arg3=0 (injected)
 *
 * path 3: mf_write_setpoint -> MF_SET (macro expansion) -> MF_SET2
 *         [STOPS — chained macro not followed to scf_tag_write] (known limitation)
 *
 * path 4: main -> mf_apply_config -> scf_tag_copy
 *         type=COPYF  arg1=PT_PUMP_SPEED=0x1001  arg2=PT_SETPOINT=0x1007
 *
 * path 5: main -> mf_apply_config -> scf_cmdq_load
 *         type=LOADQ  arg1=Q_CMD=12
 * ============================================================ */

/* Global context for macro-driven tag operations.
 * Declared extern in mf_macros.h, defined in framework. */
extern TagCtx g_mf_ctx;

/* ============================================================
 * Helper: validate and apply control-loop parameter.
 * Exercises both direct scf_tag_write calls and macro-driven
 * expansions (single-level and chained).
 * ============================================================ */
int mf_write_setpoint(int pid)
{
    int result = 0;

    /* Direct scf_tag_write call: ensures the framework API
     * is detected by the tracer independent of macro usage.
     * Sets point to configured value 42. */
    scf_tag_write(&g_mf_ctx, pid, 0x2A);

    /* Single-level macro MF_ZERO: expands directly to
     * scf_tag_write(&g_mf_ctx, pid, 0).
     * Tracer FOLLOWS this expansion to the underlying API call. */
    MF_ZERO(pid);

    /* Chained macro MF_SET -> MF_SET2: tracer resolves only
     * the first hop (MF_SET -> MF_SET2) and stops.
     * Does NOT traverse the full chain to scf_tag_write.
     * This demonstrates the single-hop macro resolution limit. */
    MF_SET(PT_VALVE_POS, 250);

    return result;
}

/* ============================================================
 * Main configuration entry point: apply startup setpoints
 * and dispatch queued commands.
 *
 * Called from main() as a fork (launch_via=FORK).
 * Orchestrates point initialization, data propagation, and
 * command queue processing.
 * ============================================================ */
int mf_apply_config(void)
{
    int status = 0;

    /* Initialize primary process variable with configured setpoint.
     * Triggers mf_write_setpoint, which exercises both direct
     * framework calls and macro-driven tag writes. */
    mf_write_setpoint(PT_SETPOINT);

    /* Copy pump speed baseline to active setpoint for control loop
     * initialization. Direct COPYF call with two literal point IDs. */
    scf_tag_copy(PT_PUMP_SPEED, PT_SETPOINT);

    /* Load and dispatch buffered control commands.
     * Processes queued operator commands before entering main
     * scan cycle. Uses LOADQ to retrieve command queue. */
    scf_cmdq_load(Q_CMD);

    return status;
}

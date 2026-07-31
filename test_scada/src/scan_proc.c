/*
 * scan_proc.c — Periodic scan cycle handler for SCADA data acquisition.
 * Registers as EVT_SCAN_CYCLE event handler; reads all monitored points
 * and applies setpoint writes via the tag subsystem.
 */

#include "app.h"
#include "scf_tag.h"
#include "scf_event.h"
#include "scf_const.h"

/* ============================================================
 * GROUND TRUTH
 *
 * Path 1: main -> scf_evt_register(EVENT) -> on_scan_cycle ->
 *         read_all_points -> read_one_point -> scf_tag_read
 *   api       : scf_tag_read
 *   type      : READF
 *   launch_via: EVENT
 *   arg2      : PT_FLOW_RATE = 0x1004
 *   call_number: 3001 (EVT_SCAN_CYCLE)
 *
 * Path 2: main -> scf_evt_register(EVENT) -> on_scan_cycle ->
 *         read_all_points -> read_one_point -> scf_tag_write
 *   api       : scf_tag_write
 *   type      : WRITEF
 *   launch_via: EVENT
 *   arg2      : PT_SETPOINT = 0x1007
 *   arg3      : 100 (literal)
 *   call_number: 3001 (EVT_SCAN_CYCLE via scf_evt_post in on_scan_cycle)
 *
 * ============================================================ */

static int read_one_point(int pid);

/*
 * on_scan_cycle — Event handler for the periodic scan cycle.
 * Posts the scan cycle event and initiates point reads for flow-rate data.
 */
void on_scan_cycle(int evt, void *data)
{
    /* Notify downstream that scan cycle has begun.
     * This provides the call_number (EVT_SCAN_CYCLE = 3001) for paths
     * originating from this handler. */
    scf_evt_post(EVT_SCAN_CYCLE, data);

    /* Scan and acquire all flow-rate points through the read pipeline. */
    read_all_points(PT_FLOW_RATE);
}

/*
 * read_all_points — Scan multiple points from a base tag ID.
 * Iterates across a small set of related sensor points, accumulating
 * status from each read operation.
 *
 * Args:
 *   base_pid: The starting point ID (e.g., PT_FLOW_RATE = 0x1004).
 *
 * Returns:
 *   Accumulated status: 0 if all reads succeeded, non-zero on error.
 */
int read_all_points(int base_pid)
{
    int status = 0;
    int i;

    /* Scan up to 3 related sensor points in sequence. */
    for (i = 0; i < 3; i++) {
        int read_status = read_one_point(base_pid);
        if (read_status != 0) {
            status = read_status;
        }
    }

    return status;
}

/*
 * read_one_point — Read a single tag point and apply setpoint control.
 * Opens the tag context, reads the current value into a buffer, then
 * writes a control setpoint. This demonstrates a value (pid) flowing
 * down from above through the parameter into the scf_tag_read call.
 *
 * Args:
 *   pid: The point ID to read (receives base_pid = PT_FLOW_RATE from caller).
 *
 * Returns:
 *   0 on success, non-zero error code otherwise.
 */
static int read_one_point(int pid)
{
    static TagCtx ctx;
    char buf[16];
    int status;

    /* Read the current sensor value at point ID 'pid'.
     * This call is traced with arg2 = pid = PT_FLOW_RATE = 0x1004,
     * and the call_number originates from scf_evt_post(EVT_SCAN_CYCLE)
     * posted in on_scan_cycle. */
    status = scf_tag_read(&ctx, pid, buf);
    if (status != 0) {
        return status;
    }

    /* Apply setpoint control: write a nominal 100-unit setpoint.
     * This call is a WRITEF with literal arg3 = 100 and arg2 = PT_SETPOINT. */
    status = scf_tag_write(&ctx, PT_SETPOINT, 100);

    return status;
}

/* edge_cases.c - Synthetic test file for call-graph tracer edge cases */

#include "app.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"
#include "scf_const.h"

/* GROUND TRUTH - Expected analyzer outcomes for 9 edge-case patterns:
 *
 * PATTERN 1 (VALID direct edge):
 *   path: main -> ec_run -> scf_tag_close
 *   api: scf_tag_close   type=CLOSEF   launch_via=NONE
 *   result: EDGE CREATED
 *
 * PATTERN 2 (function-pointer call):
 *   form: int (*fp)(int,int) = scf_tag_copy; fp(...)
 *   result: indirect_call, NO EDGE (function pointer not followed)
 *
 * PATTERN 3 (struct-field call):
 *   form: ec_ops.writer(&g_ec_ctx, PT_MOTOR_TEMP, 7)
 *   result: indirect_call, NO EDGE (struct field dereference not followed)
 *
 * PATTERN 4 (ternary-selected callee):
 *   form: (1 ? scf_cmdq_save : scf_cmdq_load)(Q_CMD)
 *   result: indirect_call, NO EDGE (ternary operator not followed)
 *
 * PATTERN 5 (broken callback form &Handler):
 *   form: scf_evt_register(EVT_VALVE_CMD, &ec_valve_evt)
 *   result: NO EDGE (address-of parses as pointer_expression, not bare callback)
 *
 * PATTERN 6 (bare-identifier callback):
 *   form: scf_signal_hook(SIG_FAULT, ec_fault_sig)
 *   path: main -> ec_run -> scf_signal_hook(SIGNAL) -> ec_fault_sig -> scf_tag_close
 *   result: EDGE CREATED, BUT DUPLICATED (bare id appended twice in builder)
 *
 * PATTERN 7 (K&R function):
 *   form: ec_knr(PT_TANK_LEVEL)
 *   path: main -> ec_run -> ec_knr -> scf_tag_read
 *   api: scf_tag_read   arg2=PT_TANK_LEVEL=0x1003
 *   result: EDGE CREATED, arg2 resolvable
 *
 * PATTERN 8 (recursion):
 *   form: ec_recurse(3)
 *   path: main -> ec_run -> ec_recurse -> ... -> scf_tag_close
 *   result: EDGE CREATED (recursion/cycle handling tested)
 *
 * PATTERN 9 (unresolved external input):
 *   form: scf_alarmq_enq(Q_CMD, ec_external_input())
 *   api: scf_alarmq_enq   arg1=Q_CMD=12   arg2=UNRESOLVED (external, no definition)
 *   result: EDGE CREATED, arg1 resolvable, arg2 marked UNRESOLVED
 */

/* External input: declared but not defined (tests unresolved tracing) */
extern int ec_external_input(void);

/* File-local context and operations structure */
static TagCtx g_ec_ctx;

struct ec_ops_s {
    int (*writer)(TagCtx *, int, int);
};
static struct ec_ops_s ec_ops;

/* Forward declarations of static handlers */
static void ec_valve_evt(int evt, void *data);
static void ec_fault_sig(int sig_no);
static void ec_recurse(int n);

/* K&R style function: old C89 declaration form */
static int ec_knr(pid)
int pid;
{
    return scf_tag_read(&g_ec_ctx, pid, 0);
}

/* Event handler: would be called if callback registration were followed */
static void ec_valve_evt(int evt, void *data)
{
    (void)evt;
    (void)data;
    /* Pattern 5 never reaches here, but if it did, this would create an edge */
    scf_tag_write(&g_ec_ctx, PT_VALVE_POS, 1);
}

/* Signal handler: called via Pattern 6 (bare callback registration) */
static void ec_fault_sig(int sig_no)
{
    (void)sig_no;
    /* Pattern 6: This creates a duplicate edge to scf_tag_close */
    scf_tag_close(&g_ec_ctx);
}

/* Recursive function: tests cycle detection in the tracer */
static void ec_recurse(int n)
{
    if (n > 0) {
        ec_recurse(n - 1);
    }
    scf_tag_close(&g_ec_ctx);
}

/* Main entry point for edge-case testing */
void ec_run(void)
{
    /* PATTERN 1: Valid direct edge (CLOSEF) */
    scf_tag_close(&g_ec_ctx);

    /* PATTERN 2: Function pointer (indirect_call; NOT an edge) */
    int (*fp)(int, int) = scf_tag_copy;
    fp(PT_PUMP_SPEED, PT_VALVE_POS);

    /* PATTERN 3: Struct field dereference (indirect_call; NOT an edge) */
    ec_ops.writer(&g_ec_ctx, PT_MOTOR_TEMP, 7);

    /* PATTERN 4: Ternary operator selecting callee (indirect_call; NOT an edge) */
    (1 ? scf_cmdq_save : scf_cmdq_load)(Q_CMD);

    /* PATTERN 5: Address-of callback (address-of; NOT followed, no edge) */
    scf_evt_register(EVT_VALVE_CMD, &ec_valve_evt);

    /* PATTERN 6: Bare identifier callback (followed, but duplicated in path) */
    scf_signal_hook(SIG_FAULT, ec_fault_sig);

    /* PATTERN 7: K&R function call (edge created, arg2 resolvable) */
    ec_knr(PT_TANK_LEVEL);

    /* PATTERN 8: Recursive call (tests cycle detection) */
    ec_recurse(3);

    /* PATTERN 9: Call with unresolved argument (arg1 resolvable, arg2 unresolved) */
    scf_alarmq_enq(Q_CMD, ec_external_input());
}

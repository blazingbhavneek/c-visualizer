#include "app.h"
#include "scf_event.h"
#include "scf_tag.h"

/* GROUND TRUTH
 * value_flow_cases -> branch open(A or B) -> scf_file_read
 *   linked file: PT_TANK_LEVEL=0x1003 or PT_FLOW_RATE=0x1004 (both possible)
 *   link_method: VARTRACE
 *
 * value_flow_cases -> close -> reopen(PT_PRESSURE) -> scf_file_read
 *   linked file: PT_PRESSURE=0x1006 only (the closed binding does not reach)
 *   link_method: VARTRACE
 *
 * value_flow_cases -> open(PT_SETPOINT) -> read_bound_handle -> scf_file_read
 *   linked file: PT_SETPOINT=0x1007 (handle crosses a function parameter)
 *   link_method: VARTRACE
 *
 * value_flow_cases -> scf_file_access -> *record = 77
 *   type: WRITEF; linked file: PT_SETPOINT=0x1007
 *
 * main -> scf_evt_register -> value_flow_external_handler
 *   scf_file_open file number origin: EXTERNAL_ENTRY (event_no is framework input)
 *   scf_file_read inherits that same external source through its handle
 *
 * --- cases the AST deliberately cannot answer (these are the LLM's job) ---
 *
 * vf_pick_file() return feeds scf_file_open
 *   syntax stops at an opaque call result; the LLM should reach PT_VALVE_POS=0x1002
 *
 * bare scf_file_access(&opaque_ctx); with the result discarded
 *   syntax cannot classify a discarded return; the LLM decides READF vs WRITEF
 */

static void read_bound_handle(TagCtx *ctx)
{
    int record = 0;
    scf_file_read(ctx, &record);
}

/* Opaque to the AST: the resolver must ask the LLM, which can read this body. */
static int vf_pick_file(void)
{
    return PT_VALVE_POS;
}

static void vf_llm_required_cases(void)
{
    TagCtx opaque_ctx = {0};
    int chosen = vf_pick_file();

    scf_file_open(&opaque_ctx, chosen);
    scf_file_access(&opaque_ctx);
    scf_file_close(&opaque_ctx);
}

void value_flow_cases(int mode)
{
    TagCtx branch_ctx = {0};
    TagCtx reopen_ctx = {0};
    TagCtx passed_ctx = {0};
    int record = 0;
    int *writable;

    if (mode) {
        scf_file_open(&branch_ctx, PT_TANK_LEVEL);
    } else {
        scf_file_open(&branch_ctx, PT_FLOW_RATE);
    }
    scf_file_read(&branch_ctx, &record);

    scf_file_open(&reopen_ctx, PT_MOTOR_TEMP);
    scf_file_close(&reopen_ctx);
    scf_file_open(&reopen_ctx, PT_PRESSURE);
    scf_file_read(&reopen_ctx, &record);

    scf_file_open(&passed_ctx, PT_SETPOINT);
    read_bound_handle(&passed_ctx);
    scf_file_write(&passed_ctx, &record);
    writable = (int *)scf_file_access(&passed_ctx);
    *writable = 77;
    scf_file_close(&passed_ctx);

    vf_llm_required_cases();
}

void value_flow_external_handler(int event_no, void *data)
{
    TagCtx external_ctx = {0};
    int record = 0;

    (void)data;
    scf_file_open(&external_ctx, event_no);
    scf_file_read(&external_ctx, &record);
    scf_file_close(&external_ctx);
}

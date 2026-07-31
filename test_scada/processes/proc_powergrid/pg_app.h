#ifndef PG_APP_H
#define PG_APP_H

/* ============================================================
 * proc_powergrid — electrical substation SCADA / RTU poller.
 * Cross-module symbol contract. Globals unique within process;
 * module-internal helpers must be `static`.
 * Framework API: ../../headers/scf_*.h (bodies in ../../lib/scf_stubs.c).
 * ============================================================ */

#include "scf_types.h"
#include "scf_const.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"

/* ---- main.c ---------------------------------------------- */
void pg_init(void);
void pg_poll_timer(int timer_id);       /* TimerCb (TMR_SCAN) */

/* ---- pg_telemetry.c -------------------------------------- */
void pg_on_scan(int evt, void *data);   /* EvtHandler (EVT_SCAN_CYCLE) */
void pg_poll_task(int task_id);         /* TaskEntry  (TASK_HIST)      */
int  pg_scan_feeders(int base_pid);
int  pg_read_analog(int pid);
int  pg_read_status(int pid);
void *pg_rtu_getptr(int fno);           /* pointer-getter (call-site selection) */

/* ---- pg_dispatch.c --------------------------------------- */
void pg_on_dispatch(int evt, void *data); /* EvtHandler (EVT_ALARM_RAISED) */
int  pg_dispatch_load(int feeder);
int  pg_breaker_cmd(int feeder, int cmd);
int  pg_send_cmd(int queue_id, int code);

/* Deliberate UNRESOLVED source (declared, never defined). */
extern int pg_ext_comm_value(void);

/* ============================================================
 * TRACED CALLS / GROUND TRUTH:
 *
 * main.c (~300-450 lines):
 *   scf_evt_post(EVT_STARTUP,0) EVENT arg1=3000
 *   scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)pg_on_scan)      -> EVENT
 *   scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)pg_on_dispatch)-> EVENT
 *   scf_timer_start(TMR_SCAN,250,(TimerCb)pg_poll_timer)         -> TIMER
 *   scf_task_fork(TASK_HIST,(TaskEntry)pg_poll_task)             -> FORK
 *   pg_init(): scf_sem_wait(SEM_DBLOCK); scf_cfg_clear(CFG_SCAN);
 *              pg_rtu_getptr(PT_PRESSURE)
 *   pg_poll_timer(): scf_task_kill(TASK_ALARM) KILL launch=TIMER arg1=61
 *
 * pg_telemetry.c (~1600-2400 lines):
 *   pg_rtu_getptr(fno): 3+ scf_tag_open calls, intended one marked
 *       [CONSIDER THIS CALL]  OPENF arg2=fno (PT_PRESSURE=0x1006 from pg_init)
 *   pg_on_scan -> scf_evt_post(EVT_SCAN_CYCLE) [call_number=3001]
 *              -> pg_scan_feeders(PT_MOTOR_TEMP) -> pg_read_analog(pid)
 *                 -> scf_tag_read(&ctx,pid,buf) READF launch=EVENT arg2=PT_MOTOR_TEMP=0x1005 call_number=3001
 *              -> pg_read_status(PT_VALVE_POS) -> scf_tag_read arg2=0x1002
 *   EDGE CASES (must NOT create edges):
 *     - RTU driver dispatch table: drv->read(ctx,pid) via struct fn-ptr -> indirect_call
 *     - a local int (poll_fn)(int) = pg_read_analog; poll_fn(pid);  -> indirect_call
 *   UNRESOLVED: scf_tag_write(&ctx, PT_SETPOINT, pg_ext_comm_value())  arg3 UNRESOLVED, arg2=0x1007
 *   pg_poll_task -> scf_hist_save(ARC_TREND,&rec) SAVEF launch=FORK; scf_evt_post(EVT_HIST_FLUSH) call_number=3005
 *   Fill with: RTU frame parsing, scaling/engineering-unit conversion,
 *   deadband filtering, quality flags, poll scheduling tables - many statics.
 *
 * pg_dispatch.c (~1400-2000 lines):
 *   pg_on_dispatch -> scf_var_evt(EVT_ALARM_RAISED,1,data) [call_number=3002]
 *                  -> pg_dispatch_load(PT_FLOW_RATE)
 *   pg_breaker_cmd -> scf_evt_post(EVT_VALVE_CMD,0) EVENT arg1=EVT_VALVE_CMD=3003
 *                  -> pg_send_cmd(Q_CMD, code)
 *   pg_send_cmd -> scf_msgq_write(Q_MSG,msg) WRITEQ launch=MESSAGE arg1=13;
 *                  scf_cmdq_load(Q_CMD) LOADQ arg1=12; scf_alarmq_enq(Q_ALARM_HI,ALM_OVERPRESSURE) ENQ arg1=10 arg2=0x0903
 *   Fill with: load-flow heuristics, breaker state machine, tap-changer
 *   logic, priority dispatch tables - many statics.
 * ============================================================ */

#endif /* PG_APP_H */

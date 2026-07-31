#ifndef HV_APP_H
#define HV_APP_H

/* ============================================================
 * proc_hvac — building HVAC / BMS controller.
 * Cross-module symbol contract. Globals unique within process.
 * Heavy macro-flow process: uses hv_macros.h (HV_SET_TEMP, HV_ZERO,
 * HV_CLEAR, HV_READ) which expand to direct framework calls.
 * ============================================================ */

#include "scf_types.h"
#include "scf_const.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"
#include "hv_macros.h"

/* ---- main.c ---------------------------------------------- */
void hv_init(void);
void hv_tick(int timer_id);             /* TimerCb (TMR_SCAN) */

/* ---- hv_zones.c ------------------------------------------ */
void hv_on_scan(int evt, void *data);   /* EvtHandler (EVT_SCAN_CYCLE) */
void hv_zone_task(int task_id);         /* TaskEntry  (TASK_HIST)      */
int  hv_zone_update(int zone_pid);
int  hv_read_temp(int pid);
int  hv_write_damper(int pid, int pos);

/* ---- hv_sched.c ------------------------------------------ */
void hv_on_sched(int evt, void *data);  /* EvtHandler (EVT_ALARM_RAISED) */
int  hv_apply_schedule(int slot);
int  hv_load_config(int cfg_id);
int  hv_clear_config(int cfg_id);

/* ============================================================
 * TRACED CALLS / GROUND TRUTH:
 *
 * main.c (~300-450 lines):
 *   scf_evt_post(EVT_STARTUP,0) EVENT arg1=3000
 *   scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)hv_on_scan)   -> EVENT
 *   scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)hv_on_sched)-> EVENT
 *   scf_timer_start(TMR_SCAN,1000,(TimerCb)hv_tick)           -> TIMER
 *   scf_task_fork(TASK_HIST,(TaskEntry)hv_zone_task)          -> FORK
 *   hv_init(): scf_sem_wait(SEM_DBLOCK); hv_clear_config(CFG_ALARM)
 *
 * hv_zones.c (~1600-2400 lines) — defines `TagCtx hv_ctx;` (global for the macros):
 *   hv_on_scan -> scf_evt_post(EVT_SCAN_CYCLE) [call_number=3001]
 *             -> hv_zone_update(PT_MOTOR_TEMP) -> hv_read_temp(pid)
 *                -> HV_READ(pid,buf) macro -> scf_tag_read(&hv_ctx,pid,buf) READF launch=EVENT arg2=PT_MOTOR_TEMP=0x1005 call_number=3001
 *                -> HV_SET_TEMP(PT_SETPOINT,72) macro -> scf_tag_write(&hv_ctx,PT_SETPOINT,72) WRITEF arg2=0x1007 arg3=72
 *                -> HV_ZERO(PT_VALVE_POS) macro -> scf_tag_write(&hv_ctx,PT_VALVE_POS,0)
 *   hv_write_damper -> scf_tag_write(&hv_ctx,pid,pos) direct (ensures scf_tag_write detected)
 *   hv_zone_task -> scf_hist_save(ARC_TREND,&rec) SAVEF launch=FORK; scf_evt_post(EVT_HIST_FLUSH) call_number=3005
 *   Fill with: per-zone PID, occupancy schedules, economizer logic,
 *   psychrometrics, staging, comfort bands — many statics across many zones.
 *
 * hv_sched.c (~1300-1900 lines):
 *   hv_on_sched -> scf_var_evt(EVT_ALARM_RAISED,1,data) [call_number=3002]
 *              -> hv_apply_schedule(1)
 *   hv_load_config: scf_cmdq_load(Q_CMD) LOADQ arg1=12; HV_CLEAR(CFG_SCAN) macro -> scf_cfg_clear(CFG_SCAN=300)
 *   hv_clear_config: scf_cfg_clear(cfg_id) direct CLEARF (ensures detection); scf_cmdq_clear(Q_CMD) CLEARQ arg1=12
 *   Fill with: weekly/holiday schedule tables, setpoint reset logic,
 *   demand-response, night setback — many statics.
 * ============================================================ */

#endif /* HV_APP_H */

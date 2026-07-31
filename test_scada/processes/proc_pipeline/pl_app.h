#ifndef PL_APP_H
#define PL_APP_H

/* ============================================================
 * proc_pipeline — gas/oil pipeline flow + leak detection.
 * Cross-module symbol contract. Globals unique within process.
 * Framework API: ../../headers/scf_*.h. Chained-macro demo uses
 * mf_macros.h (MF_SET is only followed one hop).
 * ============================================================ */

#include "scf_types.h"
#include "scf_const.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"
#include "mf_macros.h"

/* ---- main.c ---------------------------------------------- */
void pl_init(void);
void pl_scan_timer(int timer_id);       /* TimerCb (TMR_SCAN) */

/* ---- pl_flow.c ------------------------------------------- */
void pl_on_scan(int evt, void *data);   /* EvtHandler (EVT_SCAN_CYCLE) */
void pl_flow_task(int task_id);         /* TaskEntry  (TASK_HIST)      */
int  pl_compute_flow(int base_pid);
int  pl_read_meter(int pid);
int  pl_archive(int archive_id);

/* ---- pl_leak.c ------------------------------------------- */
void pl_on_leak(int evt, void *data);   /* EvtHandler (EVT_ALARM_RAISED) */
int  pl_leak_scan(int pid);
int  pl_leak_eval(int pid, int value);
int  pl_notify(int alarm_code);

/* ============================================================
 * TRACED CALLS / GROUND TRUTH:
 *
 * main.c (~300-450 lines):
 *   scf_evt_post(EVT_STARTUP,0) EVENT arg1=3000
 *   scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)pl_on_scan)   -> EVENT
 *   scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)pl_on_leak) -> EVENT
 *   scf_timer_start(TMR_SCAN,200,(TimerCb)pl_scan_timer)      -> TIMER
 *   scf_task_fork(TASK_HIST,(TaskEntry)pl_flow_task)          -> FORK
 *   pl_init(): scf_sem_wait(SEM_DBLOCK); scf_cfg_clear(CFG_SCAN)
 *
 * pl_flow.c (~1600-2400 lines):
 *   pl_on_scan -> scf_evt_post(EVT_SCAN_CYCLE) [call_number=3001]
 *             -> pl_compute_flow(PT_FLOW_RATE) -> pl_read_meter(pid)
 *                -> scf_tag_read(&ctx,pid,buf) READF launch=EVENT arg2=PT_FLOW_RATE=0x1004 call_number=3001
 *                -> scf_tag_write(&ctx,PT_SETPOINT,50) WRITEF arg2=0x1007 arg3=50
 *   CHAINED-MACRO DEMO: MF_SET(PT_VALVE_POS,250) -> resolves MF_SET->MF_SET2 then STOPS (not to scf_tag_write)
 *   pl_flow_task -> scf_evt_post(EVT_HIST_FLUSH) [call_number=3005]
 *                -> pl_archive(ARC_TREND):
 *                     scf_hist_save(ARC_TREND,&rec) SAVEF launch=FORK arg1=200
 *                     RETURN-USE (get_upper=false): p = scf_hist_load(ARC_AUDIT,buf); *p = 0;  => WRITE, arg1=202
 *                     scf_cmdq_save(Q_CMD) SAVEQ arg1=12
 *   Fill with: AGA/orifice flow math, temperature/pressure compensation,
 *   totalizers, batching, moving windows — many statics.
 *
 * pl_leak.c (~1400-2000 lines):
 *   pl_on_leak -> scf_var_evt(EVT_ALARM_RAISED,1,data) [call_number=3002]
 *             -> pl_notify(ALM_OVERPRESSURE)
 *   pl_leak_eval(pid,value): mass-balance/RTTM state machine; on trip -> pl_notify
 *   pl_notify: scf_alarmq_enq(Q_ALARM_HI,alarm_code) ENQ arg1=10 arg2=ALM_OVERPRESSURE=0x0903 (via RAISE_ALARM macro is OK too);
 *              scf_msgq_write(Q_MSG,msg) WRITEQ launch=MESSAGE arg1=13; scf_msgq_read(Q_MSG,buf) READQ arg1=13
 *   pl_leak_scan(pid) -> scf_tag_read arg2 flows from caller
 *   Fill with: pressure-wave detection, correlation, segment tables,
 *   confidence scoring, debounce — many statics.
 * ============================================================ */

#endif /* PL_APP_H */

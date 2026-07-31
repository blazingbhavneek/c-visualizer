#ifndef BO_APP_H
#define BO_APP_H

/* ============================================================
 * proc_boiler — boiler / turbine combustion + safety process.
 * Cross-module symbol contract. Globals unique within process.
 * Emphasis: DEEP call chains (many hops to the API), call-site
 * selection, return-value classification, and a broken &Handler
 * callback edge case.
 * ============================================================ */

#include "scf_types.h"
#include "scf_const.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"

/* ---- main.c ---------------------------------------------- */
void bo_init(void);
void bo_wd(int timer_id);               /* TimerCb (TMR_WATCHDOG) */

/* ---- bo_combust.c ---------------------------------------- */
void bo_on_scan(int evt, void *data);   /* EvtHandler (EVT_SCAN_CYCLE) */
void bo_combust_task(int task_id);      /* TaskEntry  (TASK_HIST)      */
int  bo_stage1(int pid);                /* deep chain entry */
int  bo_stage2(int pid);
int  bo_stage3(int pid);
int  bo_stage4(int pid);
int  bo_stage5(int pid);
int  bo_stage6(int pid);                /* reaches the framework API */
void *bo_get_ctx(int fno);              /* pointer-getter (call-site selection) */

/* ---- bo_safety.c ----------------------------------------- */
void bo_on_trip(int evt, void *data);   /* EvtHandler (EVT_ALARM_RAISED) */
int  bo_trip_eval(int pid, int value);
int  bo_shed_load(int stage);
int  bo_hist_audit(int archive_id);

/* ============================================================
 * TRACED CALLS / GROUND TRUTH:
 *
 * main.c (~320-460 lines):
 *   scf_evt_post(EVT_STARTUP,0) EVENT arg1=3000
 *   scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)bo_on_scan)   -> EVENT
 *   scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)bo_on_trip) -> EVENT
 *   scf_timer_start(TMR_WATCHDOG,500,(TimerCb)bo_wd)          -> TIMER
 *   scf_task_fork(TASK_HIST,(TaskEntry)bo_combust_task)       -> FORK
 *   BROKEN CALLBACK EDGE CASE: scf_evt_register(EVT_VALVE_CMD, &bo_on_trip)
 *       -> &Handler parses as pointer_expression, NOT followed (no extra edge)
 *   bo_init(): scf_sem_wait(SEM_DBLOCK); scf_cfg_clear(CFG_SCAN); bo_get_ctx(PT_MOTOR_TEMP)
 *   bo_wd(): scf_task_kill(TASK_ALARM) KILL launch=TIMER arg1=61
 *
 * bo_combust.c (~1700-2600 lines):
 *   DEEP CHAIN: bo_on_scan -> scf_evt_post(EVT_SCAN_CYCLE) [call_number=3001]
 *               -> bo_stage1(PT_MOTOR_TEMP) -> bo_stage2 -> bo_stage3
 *               -> bo_stage4 -> bo_stage5 -> bo_stage6(pid)
 *                  -> scf_tag_write(&ctx,pid,val) WRITEF launch=EVENT arg2=PT_MOTOR_TEMP=0x1005 call_number=3001
 *       (pid flows through all 6 stage parameters unchanged -- long backward trace.)
 *   also bo_stage3 -> scf_tag_read(&ctx,PT_PRESSURE,buf) READF arg2=0x1006
 *   bo_get_ctx(fno): 3+ scf_tag_open, intended one marked [CONSIDER THIS CALL]
 *       OPENF arg2=fno (PT_MOTOR_TEMP=0x1005 from bo_init)
 *   bo_combust_task -> scf_hist_save(ARC_TREND,&rec) SAVEF launch=FORK; scf_evt_post(EVT_HIST_FLUSH) call_number=3005
 *   Fill with: air/fuel ratio trim, O2/CO trim, drum-level 3-element
 *   control, burner sequencing state machine, flame-scanner logic -- many statics.
 *
 * bo_safety.c (~1400-2100 lines):
 *   bo_on_trip -> scf_var_evt(EVT_ALARM_RAISED,1,data) [call_number=3002]
 *             -> bo_trip_eval(PT_PRESSURE, 9999)
 *   bo_trip_eval: on trip -> bo_shed_load(3); scf_alarmq_enq(Q_ALARM_HI,ALM_OVERPRESSURE) ENQ arg1=10 arg2=0x0903
 *   bo_shed_load: scf_task_kill(TASK_ALARM) KILL arg1=61; scf_task_fork(TASK_ALARM,(TaskEntry)bo_combust_task) FORK
 *   bo_hist_audit(ARC_AUDIT): RETURN-USE (get_upper=false): p=scf_hist_load(ARC_AUDIT,buf); x=*p; (READ) => classified READ, arg1=202
 *                             scf_cmdq_save(Q_CMD) SAVEQ arg1=12
 *   Fill with: trip matrix, first-out annunciation, MFT logic,
 *   permissives, purge sequencing -- many statics.
 * ============================================================ */

#endif /* BO_APP_H */

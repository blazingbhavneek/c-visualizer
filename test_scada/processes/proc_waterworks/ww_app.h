#ifndef WW_APP_H
#define WW_APP_H

/* ============================================================
 * proc_waterworks - water-treatment plant control process.
 *
 * Cross-module symbol contract. Every GLOBAL function is unique
 * within this process and is listed here with the file that
 * DEFINES it. Module-internal helpers must be `static` (not here).
 *
 * Shared framework API: ../../headers/scf_*.h (call those; the
 * bodies live in ../../lib/scf_stubs.c). Flowing macros available:
 * TAG_OPEN_RD, TAG_SNAPSHOT, HIST_TREND (scf_tag.h), RAISE_ALARM
 * (scf_queue.h).
 * ============================================================ */

#include "scf_types.h"
#include "scf_const.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"

/* ---- main.c ---------------------------------------------- */
void ww_init(void);                 /* fans out subsystem init */
void ww_watchdog(int timer_id);     /* TimerCb (TMR_WATCHDOG)  */

/* ---- ww_control.c ---------------------------------------- */
void ww_on_scan(int evt, void *data);   /* EvtHandler (EVT_SCAN_CYCLE) */
void ww_hist_task(int task_id);         /* TaskEntry  (TASK_HIST)      */
int  ww_scan_cycle(int base_pid);
int  ww_read_point(int pid);
void *ww_get_ctx(int fno);              /* pointer-getter (call-site selection) */
int  ww_flush_history(int archive_id);

/* ---- ww_alarm.c ------------------------------------------ */
void ww_on_alarm(int evt, void *data);  /* EvtHandler (EVT_ALARM_RAISED) */
int  ww_alarm_check(int pid, int value);
int  ww_alarm_dispatch(int alarm_code);

/* ============================================================
 * TRACED CALLS / GROUND TRUTH (what each file must contain and
 * the expected tracer result). Values are from scf_const.h.
 *
 * main.c (~300-450 lines):
 *   - scf_evt_post(EVT_STARTUP,0)                 EVENT   arg1=3000
 *   - scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)ww_on_scan)     -> EVENT link
 *   - scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)ww_on_alarm)  -> EVENT link
 *   - scf_timer_start(TMR_WATCHDOG,500,(TimerCb)ww_watchdog)      -> TIMER link
 *   - scf_task_fork(TASK_HIST,(TaskEntry)ww_hist_task)            -> FORK link
 *   - ww_init(): scf_sem_wait(SEM_DBLOCK) [SEMAPHORE arg1=80];
 *                ww_get_ctx(PT_TANK_LEVEL); scf_cfg_clear(CFG_SCAN) [CLEARF arg1=300]
 *   - ww_watchdog(): scf_task_kill(TASK_ALARM) [KILL launch=TIMER arg1=61]
 *
 * ww_control.c (~1500-2200 lines):
 *   - ww_get_ctx(fno): 3+ scf_tag_open calls, the intended one marked
 *       [CONSIDER THIS CALL]  -> OPENF, arg2=fno (param; PT_TANK_LEVEL=0x1003 from ww_init)
 *   - ww_on_scan -> scf_evt_post(EVT_SCAN_CYCLE,...) [call_number=3001]
 *                -> ww_scan_cycle(PT_FLOW_RATE) -> ww_read_point(pid)
 *                   -> scf_tag_read(&ctx,pid,buf)  READF launch=EVENT arg2=PT_FLOW_RATE=0x1004 call_number=3001
 *                   -> scf_tag_write(&ctx,PT_SETPOINT,100) WRITEF arg2=0x1007 arg3=100
 *                   -> TAG_SNAPSHOT(pid,buf) macro -> scf_tag_read (arg1 injected)
 *                   -> on breach, call ww_alarm_check(pid,value)  (cross-module -> ww_alarm.c)
 *   - ww_hist_task -> scf_evt_post(EVT_HIST_FLUSH,0) [call_number=3005]
 *                  -> ww_flush_history(ARC_TREND):
 *                        HIST_TREND(&rec) macro -> scf_hist_save(ARC_TREND=200 injected)  SAVEF launch=FORK
 *                        scf_hist_save(archive_id,&rec) [CONSIDER THIS CALL]
 *                        scf_cmdq_save(Q_CMD)  SAVEQ
 *   Fill the rest with realistic aux code: PID loops, setpoint ramping,
 *   sensor validation/clamping, unit conversion, ring buffers, moving
 *   averages, diagnostics tables - many distinct static functions.
 *
 * ww_alarm.c (~1200-1800 lines):
 *   - ww_on_alarm -> scf_var_evt(EVT_ALARM_RAISED,1,data) [call_number=3002]
 *                 -> ww_alarm_dispatch(ALM_OVERTEMP)
 *   - ww_alarm_dispatch:
 *        scf_alarmq_enq(Q_ALARM_LO,ALM_LOWLEVEL) direct  ENQ arg1=11 arg2=0x0902
 *        RAISE_ALARM(alarm_code) macro -> scf_alarmq_enq(Q_ALARM_HI injected, alarm_code)  arg1=10 arg2=ALM_OVERTEMP=0x0901
 *        scf_alarmq_deq(Q_ALARM_LO,out)  DEQ arg1=11
 *        scf_msgq_write(Q_MSG,msg)       WRITEQ launch=MESSAGE arg1=13
 *   - ww_alarm_check(pid,value): threshold logic; when tripped, enqueue via ww_alarm_dispatch.
 *   Fill with alarm priority tables, debounce/hysteresis, shelving,
 *   ack/reset state machines, formatting - many static functions.
 * ============================================================ */

#endif /* WW_APP_H */

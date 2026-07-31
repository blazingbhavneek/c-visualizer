#ifndef RY_APP_H
#define RY_APP_H

/* ============================================================
 * proc_railyard — rail yard signaling / interlocking process.
 * Cross-module symbol contract. Globals unique within process.
 * Emphasis: SEMAPHORE interlocks, SIGNAL-hook callback, full
 * command-queue lifecycle (ENQ/DEQ/SAVEQ/LOADQ/CLEARQ), KILL/FORK.
 * ============================================================ */

#include "scf_types.h"
#include "scf_const.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"

/* ---- main.c ---------------------------------------------- */
void ry_init(void);
void ry_fault_sig(int sig_no);          /* SignalCb (SIG_FAULT) */

/* ---- ry_interlock.c -------------------------------------- */
void ry_on_scan(int evt, void *data);   /* EvtHandler (EVT_SCAN_CYCLE) */
void ry_interlock_task(int task_id);    /* TaskEntry  (TASK_HIST)      */
int  ry_check_interlock(int section);
int  ry_lock_section(int section);
int  ry_read_signal(int pid);

/* ---- ry_route.c ------------------------------------------ */
void ry_on_route(int evt, void *data);  /* EvtHandler (EVT_ALARM_RAISED) */
int  ry_set_route(int route_id);
int  ry_cmd_enqueue(int code);
int  ry_cmd_process(void);

/* ============================================================
 * TRACED CALLS / GROUND TRUTH:
 *
 * main.c (~320-460 lines):
 *   scf_evt_post(EVT_STARTUP,0) EVENT arg1=3000
 *   scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)ry_on_scan)   -> EVENT
 *   scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)ry_on_route)-> EVENT
 *   scf_signal_hook(SIG_FAULT,(SignalCb)ry_fault_sig)         -> SIGNAL link
 *   scf_task_fork(TASK_HIST,(TaskEntry)ry_interlock_task)     -> FORK
 *   ry_init(): scf_sem_wait(SEM_DBLOCK) SEMAPHORE arg1=80; scf_cfg_clear(CFG_SCAN)
 *   ry_fault_sig(): scf_task_kill(TASK_ALARM) KILL launch=SIGNAL arg1=61
 *
 * ry_interlock.c (~1500-2200 lines):
 *   ry_on_scan -> scf_evt_post(EVT_SCAN_CYCLE) [call_number=3001]
 *             -> ry_check_interlock(1) -> ry_read_signal(PT_VALVE_POS)
 *                -> scf_tag_read(&ctx,pid,buf) READF launch=EVENT arg2=PT_VALVE_POS=0x1002 call_number=3001
 *   ry_lock_section: scf_sem_wait(SEM_DBLOCK) SEMAPHORE arg1=80; scf_sem_post(SEM_DBLOCK); scf_tag_write(&ctx,PT_SETPOINT,1) WRITEF
 *   ry_interlock_task -> scf_hist_save(ARC_EVENTLOG,&rec) SAVEF launch=FORK arg1=201; scf_evt_post(EVT_HIST_FLUSH) call_number=3005
 *   Fill with: route locking tables, flank/point protection, aspect
 *   sequencing, occupancy detection — many statics.
 *
 * ry_route.c (~1500-2100 lines):
 *   ry_on_route -> scf_var_evt(EVT_ALARM_RAISED,1,data) [call_number=3002]
 *             -> ry_set_route(5)
 *   ry_cmd_enqueue: scf_alarmq_enq(Q_CMD,code) ENQ arg1=12; scf_cmdq_save(Q_CMD) SAVEQ arg1=12
 *   ry_cmd_process: scf_cmdq_load(Q_CMD) LOADQ arg1=12; scf_alarmq_deq(Q_CMD,out) DEQ arg1=12;
 *                   scf_cmdq_clear(Q_CMD) CLEARQ arg1=12; scf_msgq_write(Q_MSG,msg) WRITEQ launch=MESSAGE arg1=13
 *   Fill with: route request queue, conflict resolution, dwell timers,
 *   sequencing state machine — many statics.
 * ============================================================ */

#endif /* RY_APP_H */

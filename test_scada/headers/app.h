#ifndef APP_H
#define APP_H

#include "scf_types.h"

/* ============================================================
 * Cross-module prototypes (the inter-file symbol contract).
 *
 * Every GLOBAL function name is unique across the whole project
 * (the call-graph indexes global functions by name only, so
 * duplicates would collide). `static` helpers live inside their
 * own .c file and are NOT declared here.
 *
 * Which file DEFINES each symbol is noted in [brackets].
 * ============================================================ */

/* ---- main.c --------------------------------------------- */
void init_subsystems(void);                 /* [main.c] */
void tick_watchdog(int timer_id);           /* [main.c]  TimerCb */

/* ---- dio_layer.c ---------------------------------------- */
void *DioGetPtr(int fno);                   /* [dio_layer.c] pointer-getter layer */
int   dio_prime_cache(int fno);             /* [dio_layer.c] */

/* ---- scan_proc.c ---------------------------------------- */
void on_scan_cycle(int evt, void *data);    /* [scan_proc.c] EvtHandler (EVT_SCAN_CYCLE) */
int  read_all_points(int base_pid);         /* [scan_proc.c] */

/* ---- alarm_proc.c --------------------------------------- */
void on_alarm(int evt, void *data);         /* [alarm_proc.c] EvtHandler (EVT_ALARM_RAISED) */
int  alarm_dispatch(int alarm_code);        /* [alarm_proc.c] */

/* ---- hist_proc.c ---------------------------------------- */
void hist_task_entry(int task_id);          /* [hist_proc.c] TaskEntry (TASK_HIST) */
int  flush_history(int archive_id);         /* [hist_proc.c] */

/* ---- macro_flow.c --------------------------------------- */
int  mf_write_setpoint(int pid);            /* [macro_flow.c] */
int  mf_apply_config(void);                 /* [macro_flow.c] */

/* ---- edge_cases.c --------------------------------------- */
void ec_run(void);                          /* [edge_cases.c] */

#endif /* APP_H */

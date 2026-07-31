#ifndef SCF_EVENT_H
#define SCF_EVENT_H

#include "scf_types.h"
#include "scf_const.h"

/* ============================================================
 * SCF Event / Process-control API.
 *
 * call_number sources (like pmf_addevent / pmd_addvarevt in the
 * real codebase): the tracer resolves the 1st argument of these
 * and reports it as call_number.
 * ============================================================ */
int scf_evt_post(int event_no, void *data);            /* EVENT   */
int scf_var_evt (int event_no, int argc, void *argv);  /* EVENT   */

/* ---- Callback REGISTRATION APIs (the ONLY supported indirect
 *      link). The handler passed here becomes an extra call-graph
 *      node; the path's launch_via is derived from the registrar.
 *      Argument positions holding the callback are declared in
 *      function_callback_info.json. ------------------------- */
int scf_evt_register(int event_no, EvtHandler handler);          /* launch EVENT  */
int scf_timer_start (int timer_id, int interval, TimerCb cb);    /* launch TIMER  */
int scf_task_fork   (int task_id, TaskEntry entry);              /* launch FORK   */
int scf_signal_hook (int sig_no, SignalCb cb);                   /* launch SIGNAL */
int scf_input_bind  (int chan, InputCb cb);                      /* launch INPUT  */

/* ---- Plain process-control (no callbacks) ---------------- */
int scf_sem_wait(int sem_id);                          /* SEMAPHORE */
int scf_sem_post(int sem_id);
int scf_task_kill(int task_id);                        /* KILL      */

#endif /* SCF_EVENT_H */

/* ============================================================
 * scf_stubs.c — trivial stub bodies for the SCF framework APIs.
 *
 * These exist so the framework symbols resolve. The tracer cares
 * about the CALL SITES in the process code (src/*.c), not about
 * what happens inside these stubs, so the bodies are intentionally
 * inert. Kept as GLOBAL (non-static) definitions.
 * ============================================================ */

#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"

TagCtx g_snap_ctx;
TagCtx g_mf_ctx;

/* ---- tag / historian ---- */
void *scf_tag_open (TagCtx *ctx, int point_id, int mode)  { (void)ctx; (void)point_id; (void)mode; return 0; }
int   scf_tag_read (TagCtx *ctx, int point_id, void *buf) { (void)ctx; (void)point_id; (void)buf; return 0; }
int   scf_tag_write(TagCtx *ctx, int point_id, int value) { (void)ctx; (void)point_id; (void)value; return 0; }
int   scf_tag_close(TagCtx *ctx)                          { (void)ctx; return 0; }
int   scf_tag_copy (int src_id, int dst_id)               { (void)src_id; (void)dst_id; return 0; }
int   scf_hist_save(int archive_id, void *rec)            { (void)archive_id; (void)rec; return 0; }
void *scf_hist_load(int archive_id, void *buf)            { (void)archive_id; (void)buf; return 0; }
int   scf_cfg_clear(int cfg_id)                           { (void)cfg_id; return 0; }
int   scf_file_open(TagCtx *ctx, int file_no)             { (void)ctx; (void)file_no; return 0; }
int   scf_file_read(TagCtx *ctx, void *buf)                { (void)ctx; (void)buf; return 0; }
int   scf_file_write(TagCtx *ctx, const void *buf)         { (void)ctx; (void)buf; return 0; }
int   scf_file_close(TagCtx *ctx)                          { (void)ctx; return 0; }
void *scf_file_access(TagCtx *ctx)                         { (void)ctx; return 0; }

/* ---- queue ---- */
int scf_alarmq_enq(int queue_id, int alarm_code) { (void)queue_id; (void)alarm_code; return 0; }
int scf_alarmq_deq(int queue_id, void *out)      { (void)queue_id; (void)out; return 0; }
int scf_msgq_write(int queue_id, void *msg)      { (void)queue_id; (void)msg; return 0; }
int scf_msgq_read (int queue_id, void *buf)      { (void)queue_id; (void)buf; return 0; }
int scf_cmdq_save (int queue_id)                 { (void)queue_id; return 0; }
int scf_cmdq_load (int queue_id)                 { (void)queue_id; return 0; }
int scf_cmdq_clear(int queue_id)                 { (void)queue_id; return 0; }

/* ---- event / process ---- */
int scf_evt_post(int event_no, void *data)                     { (void)event_no; (void)data; return 0; }
int scf_var_evt (int event_no, int argc, void *argv)           { (void)event_no; (void)argc; (void)argv; return 0; }
int scf_evt_register(int event_no, EvtHandler handler)         { (void)event_no; (void)handler; return 0; }
int scf_timer_start (int timer_id, int interval, TimerCb cb)   { (void)timer_id; (void)interval; (void)cb; return 0; }
int scf_task_fork   (int task_id, TaskEntry entry)             { (void)task_id; (void)entry; return 0; }
int scf_signal_hook (int sig_no, SignalCb cb)                  { (void)sig_no; (void)cb; return 0; }
int scf_input_bind  (int chan, InputCb cb)                     { (void)chan; (void)cb; return 0; }
int scf_sem_wait(int sem_id)                                   { (void)sem_id; return 0; }
int scf_sem_post(int sem_id)                                   { (void)sem_id; return 0; }
int scf_task_kill(int task_id)                                 { (void)task_id; return 0; }

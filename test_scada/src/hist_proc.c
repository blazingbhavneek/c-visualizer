/*
 * hist_proc.c - Historian task / archive flushing process.
 *
 * Handles periodic archival of trend data and audit records.
 * Runs in a dedicated task spawned via scf_task_fork(TASK_HIST, hist_task_entry).
 */

#include "app.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"
#include "scf_const.h"

/* ============================================================
 * GROUND TRUTH
 *
 * path 1: main -> scf_task_fork(FORK) -> hist_task_entry -> flush_history
 *         -> scf_hist_save (annotated CONSIDER-THIS-CALL)
 * api    : scf_hist_save   type=SAVEF   launch_via=FORK
 * arg1   : archive_id (parameter) = ARC_TREND = 200
 * call_num: EVT_HIST_FLUSH = 3005 (via scf_evt_post in hist_task_entry)
 *
 * path 2: main -> scf_task_fork(FORK) -> hist_task_entry -> flush_history
 *         -> HIST_TREND macro -> scf_hist_save
 * api    : scf_hist_save   type=SAVEF   launch_via=FORK
 * arg1   : ARC_TREND = 200 (macro-injected)
 * call_num: EVT_HIST_FLUSH = 3005 (via scf_evt_post in hist_task_entry)
 *
 * path 3: main -> scf_task_fork(FORK) -> hist_task_entry -> flush_history
 *         -> scf_hist_load
 * api    : scf_hist_load   type=WRITEF   launch_via=FORK   get_upper=false
 * arg1   : ARC_AUDIT = 202
 * return : pointer is dereferenced and written (*p = 0) => classified WRITE
 * call_num: EVT_HIST_FLUSH = 3005
 *
 * path 4: main -> scf_task_fork(FORK) -> hist_task_entry -> flush_history
 *         -> scf_cmdq_save
 * api    : scf_cmdq_save   type=SAVEQ   launch_via=FORK
 * arg1   : Q_CMD = 12
 * call_num: EVT_HIST_FLUSH = 3005
 *
 * ============================================================
 */

/* ============================================================
 * Static helper: perform a single historian archive operation.
 * ============================================================ */
static int archive_record(int archive_id, HistRec *rec)
{
    if (!rec) {
        return -1;
    }
    rec->archive_id = archive_id;
    return scf_hist_save(archive_id, rec);
}

/*
 * hist_task_entry - Main entry point for the historian background task.
 *
 * Called via scf_task_fork(TASK_HIST, hist_task_entry) from main.
 * Posts a flush event and invokes the history flusher.
 */
void hist_task_entry(int task_id)
{
    /* Signal that historian is performing a flush cycle. */
    scf_evt_post(EVT_HIST_FLUSH, 0);

    /* Flush trend data (ARC_TREND) and other archives. */
    flush_history(ARC_TREND);
}

/*
 * flush_history - Flush historian archives and save command queue.
 *
 * @archive_id: primary archive to flush (typically ARC_TREND).
 *
 * This function:
 *   1. Saves a trend record via HIST_TREND macro (injects ARC_TREND)
 *   2. Saves a trend record via direct call (uses passed archive_id param)
 *   3. Tests get_upper=false: load and write through a buffer pointer
 *   4. Persists the command queue
 *
 * Returns: status code (0 on success, -1 on error).
 */
int flush_history(int archive_id)
{
    static HistRec rec;
    char buf[64];
    char *p;
    int status;

    /* Initialize the record structure. */
    rec.stamp = 0;
    rec.value = 0;

    /*
     * Path 1: Use the HIST_TREND macro to save with injected archive ID.
     * This expands to: scf_hist_save(ARC_TREND, &rec)
     * The tracer follows the macro and detects arg1 = ARC_TREND = 200.
     */
    HIST_TREND(&rec);

    /*
     * Path 2: Direct call to scf_hist_save with archive_id parameter.
     * The tracer resolves archive_id as ARC_TREND (200) passed from caller.
     * The CONSIDER-THIS-CALL annotation selects this site (since we call
     * scf_hist_save twice in this function).
     */
    status = scf_hist_save(archive_id, &rec); /*CONSIDER THIS CALL*/
    if (status < 0) {
        return -1;
    }

    /*
     * Path 3: Test return-value classification (get_upper=false).
     * scf_hist_load returns a pointer; we dereference and write through it.
     * This usage pattern (write through return value) is classified as WRITE.
     */
    p = scf_hist_load(ARC_AUDIT, buf);
    if (p) {
        *p = 0;  /* Write through the returned pointer => WRITE classification */
    }

    /*
     * Path 4: Persist the command queue to stable storage.
     */
    scf_cmdq_save(Q_CMD);

    return 0;
}

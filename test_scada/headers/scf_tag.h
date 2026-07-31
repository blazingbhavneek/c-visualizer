#ifndef SCF_TAG_H
#define SCF_TAG_H

#include "scf_types.h"
#include "scf_const.h"

/* ============================================================
 * SCF Tag / Historian storage API (FILE-class operations).
 * These are the "framework file APIs" the tracer classifies as
 * OPENF / READF / WRITEF / CLOSEF / COPYF / SAVEF / LOADF / CLEARF.
 * ============================================================ */

void *scf_tag_open (TagCtx *ctx, int point_id, int mode);   /* OPENF  */
int   scf_tag_read (TagCtx *ctx, int point_id, void *buf);  /* READF  */
int   scf_tag_write(TagCtx *ctx, int point_id, int value);  /* WRITEF */
int   scf_tag_close(TagCtx *ctx);                           /* CLOSEF */
int   scf_tag_copy (int src_id, int dst_id);                /* COPYF  */

int   scf_hist_save(int archive_id, void *rec);             /* SAVEF  */
void *scf_hist_load(int archive_id, void *buf);             /* LOADF (returns loaded record ptr) */
int   scf_cfg_clear(int cfg_id);                            /* CLEARF */

/* Shared snapshot context used by the TAG_SNAPSHOT macro. */
extern TagCtx g_snap_ctx;

/* ---- Flowing / function-like macros ----------------------
 * Each forwards to exactly ONE direct named call so the
 * call-graph macro expander can follow it. Note the injected /
 * reordered arguments (documented for the arg-index mapping). */

/* injects mode=SCF_READ_LOCK */
#define TAG_OPEN_RD(ctx, pid)   scf_tag_open((ctx), (pid), SCF_READ_LOCK)

/* injects the shared g_snap_ctx as arg 1 */
#define TAG_SNAPSHOT(pid, buf)  scf_tag_read(&g_snap_ctx, (pid), (buf))

/* injects archive id ARC_TREND as arg 1 */
#define HIST_TREND(rec)         scf_hist_save(ARC_TREND, (rec))

#endif /* SCF_TAG_H */

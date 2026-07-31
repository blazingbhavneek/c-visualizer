#ifndef SCF_TYPES_H
#define SCF_TYPES_H

/* ============================================================
 * Shared SCF types. Kept deliberately small and C89-friendly.
 * ============================================================ */

typedef struct TagCtx {
    int   point_id;
    int   handle;
    int   mode;
    void *buf;
} TagCtx;

typedef struct QueueCtx {
    int queue_id;
    int depth;
} QueueCtx;

typedef struct ScanRec {
    int point_id;
    int value;
    int quality;
} ScanRec;

typedef struct HistRec {
    int archive_id;
    int stamp;
    int value;
} HistRec;

/* Callback function-pointer typedefs. These are ONLY followed by
 * the analyzer when passed to a registration API listed in
 * function_callback_info.json (see CONTRACT.md). */
typedef void (*EvtHandler)(int evt, void *data);
typedef void (*TimerCb)(int timer_id);
typedef void (*TaskEntry)(int task_id);
typedef void (*SignalCb)(int sig_no);
typedef void (*InputCb)(int chan, int value);

#endif /* SCF_TYPES_H */

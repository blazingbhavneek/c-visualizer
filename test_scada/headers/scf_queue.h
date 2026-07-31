#ifndef SCF_QUEUE_H
#define SCF_QUEUE_H

#include "scf_types.h"
#include "scf_const.h"

/* ============================================================
 * SCF Queue API (QUEUE-class operations).
 * Classified as ENQ / DEQ / READQ / WRITEQ / SAVEQ / LOADQ / CLEARQ.
 * ============================================================ */

int scf_alarmq_enq (int queue_id, int alarm_code);  /* ENQ    */
int scf_alarmq_deq (int queue_id, void *out);       /* DEQ    */
int scf_msgq_write (int queue_id, void *msg);       /* WRITEQ */
int scf_msgq_read  (int queue_id, void *buf);       /* READQ  */
int scf_cmdq_save  (int queue_id);                  /* SAVEQ  */
int scf_cmdq_load  (int queue_id);                  /* LOADQ  */
int scf_cmdq_clear (int queue_id);                  /* CLEARQ */

/* function-like macro forwarding to a direct enqueue call,
 * injecting the Q_ALARM_HI queue id as arg 1. */
#define RAISE_ALARM(code)   scf_alarmq_enq(Q_ALARM_HI, (code))

#endif /* SCF_QUEUE_H */

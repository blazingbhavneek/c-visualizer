/*
 * alarm_proc.c - Alarm event handler and dispatch system.
 * Handles alarm-raised events from the control process and queues them
 * through both high and low-priority alarm queues. Demonstrates direct
 * enqueue calls and macro-based queue operations.
 */

#include "app.h"
#include "scf_queue.h"
#include "scf_event.h"
#include "scf_const.h"

/* GROUND TRUTH
 * 1. main -> scf_evt_register(EVENT) -> on_alarm -> scf_var_evt(EVT_ALARM_RAISED)
 *    (call_number source)
 *
 * 2. main -> scf_evt_register(EVENT) -> on_alarm -> alarm_dispatch -> RAISE_ALARM -> scf_alarmq_enq
 *    type=ENQ  launch_via=EVENT  arg1=Q_ALARM_HI=10 (macro-injected)  arg2=ALM_OVERTEMP=0x0901
 *    call_number=EVT_ALARM_RAISED=3002 (via scf_var_evt in on_alarm)
 *
 * 3. alarm_dispatch -> scf_alarmq_enq(Q_ALARM_LO, ALM_LOWLEVEL)
 *    type=ENQ  arg1=Q_ALARM_LO=11  arg2=ALM_LOWLEVEL=0x0902
 *
 * 4. alarm_dispatch -> scf_alarmq_deq(Q_ALARM_LO, out)
 *    type=DEQ  arg1=Q_ALARM_LO=11
 *
 * 5. alarm_dispatch -> scf_msgq_write(Q_MSG, msg)
 *    type=WRITEQ  launch=MESSAGE  arg1=Q_MSG=13
 */

/* Forward declaration of static helper */
static int log_alarm_event(int code, char *buf, int sz);

/*
 * on_alarm - Event handler for alarm-raised events.
 * Registered by main via scf_evt_register(EVT_ALARM_RAISED, on_alarm).
 * Called indirectly by the framework when an alarm condition is detected.
 *
 * Marks the event in the audit log (via scf_var_evt) and dispatches
 * the alarm code for processing through the alarm queues.
 */
void on_alarm(int evt, void *data)
{
    /* Log this alarm event to the var log; establishes call_number */
    scf_var_evt(EVT_ALARM_RAISED, 1, data);

    /* Dispatch the alarm for queue processing */
    alarm_dispatch(ALM_OVERTEMP);
}

/*
 * alarm_dispatch - Process an alarm code through the alarm handling system.
 * Routes alarms to both high and low-priority queues and posts a message
 * to the message queue. Demonstrates direct enqueue, macro-expanded enqueue,
 * dequeue, and write operations.
 *
 * alarm_code: Alarm code (e.g., ALM_OVERTEMP, ALM_LOWLEVEL)
 * Returns: Status code (0 for success, negative for error)
 */
int alarm_dispatch(int alarm_code)
{
    static char out[32];      /* Buffer for dequeued alarm data */
    static char msg[32];      /* Message buffer for message queue */
    int status = 0;

    /*
     * Queue a low-priority alarm directly to the low-priority alarm queue.
     * This direct enqueue call is traced as a distinct API path.
     */
    status = scf_alarmq_enq(Q_ALARM_LO, ALM_LOWLEVEL);
    if (status < 0)
        return status;

    /*
     * Raise a high-priority alarm via the RAISE_ALARM macro.
     * The macro expands to scf_alarmq_enq(Q_ALARM_HI, alarm_code),
     * injecting Q_ALARM_HI as the queue ID argument.
     * This forms a separate traced path through the macro expansion.
     */
    status = RAISE_ALARM(alarm_code);
    if (status < 0)
        return status;

    /*
     * Dequeue from the low-priority queue to inspect the alarm.
     * Demonstrates the DEQ operation class.
     */
    status = scf_alarmq_deq(Q_ALARM_LO, out);
    if (status < 0)
        return status;

    /*
     * Format the alarm information and post to the message queue.
     * This triggers a MESSAGE-class write operation.
     */
    log_alarm_event(alarm_code, msg, sizeof(msg));
    status = scf_msgq_write(Q_MSG, msg);

    return status;
}

/*
 * log_alarm_event - Static helper: format an alarm code into a message.
 * Not part of the call-graph API (static scope, internal only).
 *
 * code: Alarm code
 * buf: Output buffer
 * sz: Buffer size
 * Returns: 0 on success
 */
static int log_alarm_event(int code, char *buf, int sz)
{
    const char *desc = "UNKNOWN_ALARM";

    /* Map alarm code to a descriptive string */
    switch (code) {
        case ALM_OVERTEMP:
            desc = "MOTOR_OVERTEMP";
            break;
        case ALM_LOWLEVEL:
            desc = "TANK_LOW_LEVEL";
            break;
        case ALM_OVERPRESSURE:
            desc = "SYSTEM_OVERPRESSURE";
            break;
        default:
            break;
    }

    /* Ensure null termination */
    if (sz > 0)
        buf[sz - 1] = '\0';

    return 0;
}

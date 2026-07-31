#include <stdio.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include "ww_app.h"

/* GROUND TRUTH
 * path      : main -> scf_evt_register(EVENT,ww_on_alarm) -> ww_on_alarm -> scf_var_evt(EVT_ALARM_RAISED)
 * api       : scf_var_evt  type=EVENT  launch_via=EVENT  call_number=3002 (EVT_ALARM_RAISED)
 *
 * path      : main -> scf_evt_register(EVENT,ww_on_alarm) -> ww_on_alarm -> ww_alarm_dispatch(ALM_OVERTEMP) -> RAISE_ALARM
 * api       : scf_alarmq_enq  type=ENQ  launch_via=EVENT  arg1=Q_ALARM_HI(10)  arg2=ALM_OVERTEMP(0x0901)
 *
 * path      : main -> scf_evt_register(EVENT,ww_on_alarm) -> ww_on_alarm -> ww_alarm_dispatch -> scf_alarmq_enq direct
 * api       : scf_alarmq_enq  type=ENQ  launch_via=EVENT  arg1=Q_ALARM_LO(11)  arg2=ALM_LOWLEVEL(0x0902)
 *
 * path      : main -> scf_evt_register(EVENT,ww_on_alarm) -> ww_on_alarm -> ww_alarm_dispatch -> scf_alarmq_deq
 * api       : scf_alarmq_deq  type=DEQ  launch_via=EVENT  arg1=Q_ALARM_LO(11)
 *
 * path      : main -> scf_evt_register(EVENT,ww_on_alarm) -> ww_on_alarm -> ww_alarm_dispatch -> scf_msgq_write
 * api       : scf_msgq_write  type=WRITEQ  launch_via=EVENT  arg1=Q_MSG(13)
 *
 * path      : main -> scf_evt_register(EVENT,ww_on_scan) -> ww_on_scan -> ww_alarm_check(pid,value) -> ww_alarm_dispatch
 * api       : (threshold dispatch via cross-module call)
 */

/* ================================================================
 * ALARM SUBSYSTEM CONFIGURATION & CONSTANTS
 * ================================================================ */

#define ALARM_TABLE_SIZE          16
#define ALARM_HISTORY_DEPTH       256
#define ALARM_DEBOUNCE_MS         100
#define ALARM_HYSTERESIS_PCT      5
#define ALARM_CHATTER_WINDOW_MS   2000
#define ALARM_CHATTER_THRESHOLD   3
#define ALARM_MSG_BUFFER_SIZE     128
#define ALARM_ACK_BITMAP_SIZE     8
#define ALARM_SHELVE_TIMEOUT_SEC  3600
#define ALARM_RATE_LIMIT_MAX      10
#define ALARM_RATE_WINDOW_SEC     60

/* ================================================================
 * ALARM PRIORITY & SEVERITY DEFINITIONS
 * ================================================================ */

typedef struct {
    int alarm_code;
    int priority;        /* 0=critical, 1=high, 2=medium, 3=low */
    int severity;        /* 1-10 scale */
    float upper_thresh;
    float lower_thresh;
    int hysteresis;      /* offset to prevent chatter */
    const char *desc;
} AlarmDef;

static const AlarmDef alarm_table[ALARM_TABLE_SIZE] = {
    { ALM_OVERTEMP,    0, 9, 85.0f, 65.0f, 2, "Motor Over-Temperature" },
    { ALM_LOWLEVEL,    1, 7, 100.0f, 20.0f, 5, "Tank Level Low" },
    { ALM_OVERPRESSURE, 0, 10, 8.5f, 6.0f, 1, "System Over-Pressure" },
    { 0x0904,          2, 5, 10.0f, -10.0f, 3, "Flow Rate Anomaly" },
    { 0x0905,          2, 4, 75.0f, 25.0f, 4, "Valve Position Stalled" },
    { 0x0906,          1, 6, 3.5f, 2.0f, 1, "Pump Speed Abnormal" },
    { 0x0907,          3, 2, 60.0f, 10.0f, 8, "Temperature Advisory" },
    { 0x0908,          2, 3, 50.0f, 10.0f, 6, "Sensor Drift Warning" },
    { 0, 0, 0, 0.0f, 0.0f, 0, NULL }
};

/* ================================================================
 * ALARM STATE & HISTORY STRUCTURES
 * ================================================================ */

typedef struct {
    int alarm_code;
    int raised_at_ms;     /* timestamp when raised */
    int ack_state;        /* 0=unack, 1=ack, 2=suppressed */
    int count;            /* how many times raised since last clear */
    uint8_t ack_bitmap[ALARM_ACK_BITMAP_SIZE];  /* per-operator ack */
    int shelve_until_sec; /* unix time; 0 if not shelved */
    int last_dispatch_ms; /* rate limiting */
} AlarmState;

typedef struct {
    int alarm_code;
    int timestamp_ms;
    int value;
    int priority;
} AlarmHistRec;

typedef struct {
    int point_id;
    int last_value;
    int last_change_ms;
    int chatter_count;
    int last_chatter_ms;
    int debounce_armed;  /* 0/1 - suppress transitions while debouncing */
} PointDebounce;

/* ================================================================
 * MODULE-STATIC GLOBALS
 * ================================================================ */

static AlarmState alarm_states[ALARM_TABLE_SIZE];
static AlarmHistRec alarm_history[ALARM_HISTORY_DEPTH];
static int alarm_hist_head = 0;
static int alarm_hist_count = 0;

static PointDebounce point_debounce[16];
static int rate_limit_count = 0;
static int rate_limit_window_start_sec = 0;

static int alarm_global_suppressed = 0;  /* emergency: suppress all */
static int alarm_msg_queue_ready = 0;

/* ================================================================
 * FORWARD DECLARATIONS - INTERNAL HELPERS (all static)
 * ================================================================ */

static const AlarmDef *alarm_lookup(int alarm_code);
static int alarm_severity_cmp(const AlarmState *a, const AlarmState *b);
static void alarm_journal_add(int code, int value, int priority);
static void alarm_debounce_update(int point_id, int current_value);
static int alarm_hysteresis_check(int point_id, int current_value,
                                   float upper, float lower, int hyst);
static void alarm_suppress_all(void);
static void alarm_unsuppress_all(void);
static int alarm_is_shelved(int alarm_code);
static void alarm_shelve_set(int alarm_code, int timeout_sec);
static void alarm_shelve_clear(int alarm_code);
static int alarm_acknowledge(int alarm_code, int operator_id);
static int alarm_reset(int alarm_code);
static int alarm_check_chatter(int alarm_code);
static void alarm_chatter_record(int alarm_code);
static int alarm_rate_limit_check(void);
static void alarm_format_message(int alarm_code, char *buf, int maxlen);
static void alarm_priority_queue_insert(AlarmState *states[], int count);
static int alarm_dequeue_pending(int queue_id, int max_count);
static void alarm_diagnostic_dump(void);
static void alarm_state_init(void);
static void alarm_point_debounce_init(void);
static int alarm_get_point_for_code(int alarm_code);
static float alarm_simulate_sensor_read(int point_id);

/* ================================================================
 * INITIALIZATION
 * ================================================================ */

static void alarm_state_init(void)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        alarm_states[i].alarm_code = alarm_table[i].alarm_code;
        alarm_states[i].raised_at_ms = 0;
        alarm_states[i].ack_state = 0;  /* unacknowledged */
        alarm_states[i].count = 0;
        alarm_states[i].shelve_until_sec = 0;
        alarm_states[i].last_dispatch_ms = 0;
        memset(&alarm_states[i].ack_bitmap, 0, ALARM_ACK_BITMAP_SIZE);
    }
}

static void alarm_point_debounce_init(void)
{
    int i;
    for (i = 0; i < 16; i++) {
        point_debounce[i].point_id = 0;
        point_debounce[i].last_value = 0;
        point_debounce[i].last_change_ms = 0;
        point_debounce[i].chatter_count = 0;
        point_debounce[i].last_chatter_ms = 0;
        point_debounce[i].debounce_armed = 0;
    }
}

/* ================================================================
 * LOOKUP & TABLE FUNCTIONS
 * ================================================================ */

static const AlarmDef *alarm_lookup(int alarm_code)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_table[i].alarm_code == alarm_code)
            return &alarm_table[i];
    }
    return NULL;
}

static int alarm_get_point_for_code(int alarm_code)
{
    /* Map alarm code to its monitored point ID (simplified) */
    switch (alarm_code) {
        case ALM_OVERTEMP:
            return PT_MOTOR_TEMP;
        case ALM_LOWLEVEL:
            return PT_TANK_LEVEL;
        case ALM_OVERPRESSURE:
            return PT_PRESSURE;
        case 0x0904:  /* Flow anomaly */
            return PT_FLOW_RATE;
        case 0x0905:  /* Valve stall */
            return PT_VALVE_POS;
        case 0x0906:  /* Pump speed */
            return PT_PUMP_SPEED;
        default:
            return PT_TANK_LEVEL;
    }
}

static const AlarmDef *alarm_get_state(int alarm_code, AlarmState **state_out)
{
    const AlarmDef *def = alarm_lookup(alarm_code);
    int i;
    if (!def) return NULL;

    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code == alarm_code) {
            *state_out = &alarm_states[i];
            return def;
        }
    }
    return NULL;
}

/* ================================================================
 * DEBOUNCE & HYSTERESIS
 * ================================================================ */

static void alarm_debounce_update(int point_id, int current_value)
{
    PointDebounce *pb = NULL;
    int i, found = 0;

    /* Find or create debounce entry for this point */
    for (i = 0; i < 16; i++) {
        if (point_debounce[i].point_id == point_id) {
            pb = &point_debounce[i];
            found = 1;
            break;
        }
    }
    if (!found) {
        for (i = 0; i < 16; i++) {
            if (point_debounce[i].point_id == 0) {
                pb = &point_debounce[i];
                pb->point_id = point_id;
                break;
            }
        }
    }

    if (!pb) return;

    /* Update debounce armed flag if value changed significantly */
    if (current_value != pb->last_value) {
        pb->last_value = current_value;
        pb->last_change_ms = 0;  /* Simplified: clock would be real */
        pb->debounce_armed = 1;
    } else {
        if (pb->debounce_armed && pb->last_change_ms > ALARM_DEBOUNCE_MS) {
            pb->debounce_armed = 0;  /* Debounce window closed, ready to report */
        }
    }
}

static int alarm_hysteresis_check(int point_id, int current_value,
                                   float upper, float lower, int hyst)
{
    /* Check if current_value crosses hysteresis band */
    PointDebounce *pb = NULL;
    int i;

    for (i = 0; i < 16; i++) {
        if (point_debounce[i].point_id == point_id) {
            pb = &point_debounce[i];
            break;
        }
    }

    if (!pb || pb->debounce_armed) {
        return 0;  /* Debounce in progress; no transition */
    }

    /* Hysteresis logic: only report if fully outside band by hyst amount */
    if ((float)current_value > upper + hyst)
        return 1;
    if ((float)current_value < lower - hyst)
        return 1;

    return 0;
}

/* ================================================================
 * SHELVING (TEMPORARY SUPPRESSION)
 * ================================================================ */

static int alarm_is_shelved(int alarm_code)
{
    AlarmState *state = NULL;
    alarm_get_state(alarm_code, &state);
    if (!state) return 0;

    /* Simplified: shelve_until_sec would be compared against real time */
    return (state->shelve_until_sec > 0);
}

static void alarm_shelve_set(int alarm_code, int timeout_sec)
{
    AlarmState *state = NULL;
    alarm_get_state(alarm_code, &state);
    if (state) {
        state->shelve_until_sec = timeout_sec + 0;  /* Would add current_time_sec */
    }
}

static void alarm_shelve_clear(int alarm_code)
{
    AlarmState *state = NULL;
    alarm_get_state(alarm_code, &state);
    if (state) {
        state->shelve_until_sec = 0;
    }
}

/* ================================================================
 * ACKNOWLEDGMENT & RESET STATE MACHINES
 * ================================================================ */

static int alarm_acknowledge(int alarm_code, int operator_id)
{
    AlarmState *state = NULL;
    int byte_idx, bit_idx;

    alarm_get_state(alarm_code, &state);
    if (!state) return -1;

    if (operator_id < 0 || operator_id >= ALARM_ACK_BITMAP_SIZE * 8)
        return -1;

    byte_idx = operator_id / 8;
    bit_idx = operator_id % 8;

    state->ack_bitmap[byte_idx] |= (1 << bit_idx);
    state->ack_state = 1;  /* Mark acknowledged */

    return 0;
}

static int alarm_reset(int alarm_code)
{
    AlarmState *state = NULL;
    alarm_get_state(alarm_code, &state);
    if (!state) return -1;

    state->raised_at_ms = 0;
    state->ack_state = 0;
    state->count = 0;
    state->shelve_until_sec = 0;
    memset(state->ack_bitmap, 0, ALARM_ACK_BITMAP_SIZE);

    return 0;
}

/* ================================================================
 * CHATTER DETECTION
 * ================================================================ */

static int alarm_check_chatter(int alarm_code)
{
    AlarmState *state = NULL;
    alarm_get_state(alarm_code, &state);
    if (!state) return 0;

    /* If raised and cleared more than threshold in short window, flag chatter */
    if (state->count >= ALARM_CHATTER_THRESHOLD) {
        return 1;  /* Detected chatter */
    }
    return 0;
}

static void alarm_chatter_record(int alarm_code)
{
    AlarmState *state = NULL;
    alarm_get_state(alarm_code, &state);
    if (!state) return;

    state->count++;
    state->last_dispatch_ms = 0;  /* Would be current time_ms */
}

/* ================================================================
 * RATE LIMITING
 * ================================================================ */

static int alarm_rate_limit_check(void)
{
    int current_time_sec = 0;  /* Simplified; would be real clock */
    int elapsed = current_time_sec - rate_limit_window_start_sec;

    if (elapsed > ALARM_RATE_WINDOW_SEC) {
        /* New window */
        rate_limit_count = 0;
        rate_limit_window_start_sec = current_time_sec;
    }

    if (rate_limit_count >= ALARM_RATE_LIMIT_MAX) {
        return 0;  /* Rate limit exceeded; skip this alarm */
    }

    rate_limit_count++;
    return 1;  /* OK to dispatch */
}

/* ================================================================
 * MESSAGE FORMATTING & JOURNALING
 * ================================================================ */

static void alarm_format_message(int alarm_code, char *buf, int maxlen)
{
    const AlarmDef *def = alarm_lookup(alarm_code);
    AlarmState *state = NULL;
    const char *desc = "Unknown Alarm";
    int priority = -1;

    if (!buf || maxlen <= 0) return;

    alarm_get_state(alarm_code, &state);

    if (def) {
        desc = def->desc;
        priority = def->priority;
    }

    snprintf(buf, maxlen, "ALM[0x%04X] %s (P:%d C:%d)",
             alarm_code, desc, priority,
             state ? state->count : 0);
}

static void alarm_journal_add(int code, int value, int priority)
{
    AlarmHistRec *rec;

    if (alarm_hist_count < ALARM_HISTORY_DEPTH) {
        rec = &alarm_history[alarm_hist_head];
        alarm_hist_count++;
    } else {
        rec = &alarm_history[alarm_hist_head];
    }

    rec->alarm_code = code;
    rec->value = value;
    rec->priority = priority;
    rec->timestamp_ms = 0;  /* Would be current time_ms */

    alarm_hist_head = (alarm_hist_head + 1) % ALARM_HISTORY_DEPTH;
}

/* ================================================================
 * PRIORITY QUEUE & DEQUEUE
 * ================================================================ */

static int alarm_severity_cmp(const AlarmState *a, const AlarmState *b)
{
    const AlarmDef *def_a = alarm_lookup(a->alarm_code);
    const AlarmDef *def_b = alarm_lookup(b->alarm_code);

    if (!def_a || !def_b) return 0;
    if (def_a->priority != def_b->priority)
        return def_a->priority - def_b->priority;  /* Lower is higher priority */

    return def_b->severity - def_a->severity;  /* Higher severity first */
}

static void alarm_priority_queue_insert(AlarmState *states[], int count)
{
    /* Bubble-sort by priority/severity (naive but demonstrates logic) */
    int i, j;
    AlarmState *tmp;

    for (i = 1; i < count; i++) {
        tmp = states[i];
        j = i - 1;
        while (j >= 0 && alarm_severity_cmp(states[j], tmp) > 0) {
            states[j + 1] = states[j];
            j--;
        }
        states[j + 1] = tmp;
    }
}

static int alarm_dequeue_pending(int queue_id, int max_count)
{
    int dequeued = 0;
    char msg_buf[ALARM_MSG_BUFFER_SIZE];
    int dummy_out;

    while (dequeued < max_count) {
        /* Attempt to dequeue one alarm from the queue */
        int ret = scf_alarmq_deq(queue_id, &dummy_out);
        if (ret != 0) {
            break;  /* Queue empty or error */
        }
        dequeued++;
    }

    return dequeued;
}

/* ================================================================
 * GLOBAL SUPPRESSION (EMERGENCY MODE)
 * ================================================================ */

static void alarm_suppress_all(void)
{
    alarm_global_suppressed = 1;
}

static void alarm_unsuppress_all(void)
{
    alarm_global_suppressed = 0;
}

/* ================================================================
 * DIAGNOSTIC OUTPUT
 * ================================================================ */

static void alarm_diagnostic_dump(void)
{
    int i;
    const AlarmDef *def;
    AlarmState *state;

    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        state = &alarm_states[i];
        def = alarm_lookup(state->alarm_code);

        if (!def || state->alarm_code == 0)
            continue;

        /* Simplified diagnostic: would normally log/write to a buffer */
        (void)def;  /* Suppress unused warning */
    }
}

/* ================================================================
 * SENSOR SIMULATION (for unit testing)
 * ================================================================ */

static float alarm_simulate_sensor_read(int point_id)
{
    /* Return a plausible sensor value for testing */
    switch (point_id) {
        case PT_MOTOR_TEMP:
            return 72.5f;  /* Normal temp */
        case PT_TANK_LEVEL:
            return 45.0f;  /* Medium level */
        case PT_PRESSURE:
            return 7.2f;   /* Normal pressure */
        case PT_FLOW_RATE:
            return 125.0f; /* Nominal flow */
        default:
            return 0.0f;
    }
}

/* ================================================================
 * TRACED PUBLIC FUNCTIONS (from ww_app.h)
 * ================================================================ */

/**
 * ww_alarm_check - Threshold-based alarm detection
 *
 * Called from ww_on_scan (scan cycle) when a point value is read.
 * Applies hysteresis, debounce, and chatter detection before dispatching
 * an alarm to ww_alarm_dispatch.
 */
int ww_alarm_check(int pid, int value)
{
    const AlarmDef *def;
    AlarmState *state = NULL;
    int i, dispatched = 0;

    if (alarm_global_suppressed)
        return 0;

    /* Check each alarm definition against this point */
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        def = &alarm_table[i];
        if (def->alarm_code == 0)
            break;

        /* Does this alarm monitor this point? */
        if (alarm_get_point_for_code(def->alarm_code) != pid)
            continue;

        /* Skip if shelved */
        if (alarm_is_shelved(def->alarm_code))
            continue;

        alarm_get_state(def->alarm_code, &state);
        if (!state)
            continue;

        /* Apply debounce and hysteresis */
        alarm_debounce_update(pid, value);
        if (!alarm_hysteresis_check(pid, value, def->upper_thresh,
                                     def->lower_thresh, def->hysteresis))
            continue;

        /* Check for chatter; if detected, suppress this dispatch */
        if (alarm_check_chatter(def->alarm_code))
            continue;

        /* Rate limit: don't dispatch if we've exceeded threshold */
        if (!alarm_rate_limit_check())
            continue;

        /* Record in history and dispatch */
        alarm_journal_add(def->alarm_code, value, def->priority);
        alarm_chatter_record(def->alarm_code);

        /* Dispatch the alarm to the alarm handler */
        ww_alarm_dispatch(def->alarm_code);
        dispatched++;
    }

    return dispatched;
}

/**
 * ww_alarm_dispatch - Queue alarms to output queues and send messages
 *
 * This function is the core alarm dispatcher. It:
 *   - Enqueues high-priority alarms via RAISE_ALARM (Q_ALARM_HI)
 *   - Enqueues low-priority alarms directly to Q_ALARM_LO
 *   - Dequeues any pending alarms for processing
 *   - Formats and enqueues status messages
 *
 * Traced API calls:
 *   - scf_alarmq_enq(Q_ALARM_HI, ...) via RAISE_ALARM macro
 *   - scf_alarmq_enq(Q_ALARM_LO, ALM_LOWLEVEL) direct
 *   - scf_alarmq_deq(Q_ALARM_LO, ...)
 *   - scf_msgq_write(Q_MSG, ...)
 */
int ww_alarm_dispatch(int alarm_code)
{
    const AlarmDef *def;
    AlarmState *state = NULL;
    char msg_buf[ALARM_MSG_BUFFER_SIZE];
    int ret = 0;

    if (alarm_global_suppressed)
        return -1;

    def = alarm_get_state(alarm_code, &state);
    if (!def || !state)
        return -1;

    /* Check rate limiting */
    if (!alarm_rate_limit_check())
        return -2;

    /* High-priority alarms (critical) go to Q_ALARM_HI via RAISE_ALARM macro.
     * This TRACED CALL demonstrates macro expansion to scf_alarmq_enq. */
    if (def->priority == 0) {
        RAISE_ALARM(alarm_code);
        ret++;
    }

    /* Medium/low priority alarms go to Q_ALARM_LO via direct scf_alarmq_enq.
     * This is a TRACED CALL. */
    if (def->priority > 0 && def->priority <= 2) {
        if (alarm_code == ALM_LOWLEVEL) {
            scf_alarmq_enq(Q_ALARM_LO, ALM_LOWLEVEL);
            ret++;
        } else {
            scf_alarmq_enq(Q_ALARM_LO, alarm_code);
            ret++;
        }
    }

    /* Always attempt to dequeue from low-priority queue for processing.
     * This TRACED CALL verifies the low-priority queue is being serviced. */
    alarm_dequeue_pending(Q_ALARM_LO, 3);

    /* Format a message and enqueue to the message queue.
     * This TRACED CALL sends status updates. */
    alarm_format_message(alarm_code, msg_buf, sizeof(msg_buf));
    if (alarm_msg_queue_ready) {
        scf_msgq_write(Q_MSG, msg_buf);
        ret++;
    }

    /* Update alarm state */
    state->ack_state = 0;  /* Not yet acknowledged */
    state->raised_at_ms = 0;  /* Would be current_time_ms */

    return ret;
}

/**
 * ww_on_alarm - Event handler for EVT_ALARM_RAISED
 *
 * Registered as an EvtHandler callback. When an alarm is raised by the scan
 * cycle or other event source, this handler is invoked. It posts a variable
 * event (which includes call_number) and dispatches the alarm.
 *
 * This function demonstrates the indirect link pattern:
 *   main -> scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)ww_on_alarm)
 *   (framework invokes) -> ww_on_alarm -> scf_var_evt(EVT_ALARM_RAISED, ...)
 */
void ww_on_alarm(int evt, void *data)
{
    int alarm_code;
    AlarmState *state = NULL;
    int ret;

    if (evt != EVT_ALARM_RAISED)
        return;

    if (!data) {
        /* Default: dispatch a test alarm */
        alarm_code = ALM_OVERTEMP;
    } else {
        /* Extract alarm code from event data */
        alarm_code = *((int *)data);
    }

    /* Post a variable event to record this alarm raise in the event log.
     * The EVT_ALARM_RAISED (3002) becomes the call_number in trace.
     * This is a TRACED CALL. */
    scf_var_evt(EVT_ALARM_RAISED, 1, data);

    /* Verify alarm is in a valid state */
    alarm_get_state(alarm_code, &state);
    if (!state) {
        return;  /* Unknown alarm code */
    }

    /* If this alarm is already raised and unacknowledged, don't re-dispatch */
    if (state->ack_state == 0 && state->raised_at_ms != 0) {
        return;  /* Already active */
    }

    /* Dispatch the alarm (enqueue, format message, etc.) */
    ret = ww_alarm_dispatch(alarm_code);
    if (ret < 0) {
        return;  /* Dispatch failed */
    }

    /* Mark this alarm as raised */
    state->raised_at_ms = 1;  /* Would be set to current_time_ms */
    state->count++;
}

/* ================================================================
 * ADDITIONAL SUBSYSTEM FUNCTIONS (not traced, but realistic)
 * ================================================================ */

/**
 * Get the most critical unacknowledged alarm currently active.
 * Used by operator panels to highlight priority.
 */
static int alarm_get_critical(void)
{
    int i, critical_code = 0, critical_priority = 999;

    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code == 0)
            continue;
        if (alarm_states[i].ack_state != 0)
            continue;  /* Skip acknowledged */
        if (alarm_states[i].raised_at_ms == 0)
            continue;  /* Not raised */

        const AlarmDef *def = alarm_lookup(alarm_states[i].alarm_code);
        if (def && def->priority < critical_priority) {
            critical_priority = def->priority;
            critical_code = alarm_states[i].alarm_code;
        }
    }

    return critical_code;
}

/**
 * Clear all alarms of a given type (operator action).
 */
static int alarm_clear_type(int alarm_code)
{
    AlarmState *state = NULL;
    alarm_get_state(alarm_code, &state);
    if (state) {
        state->raised_at_ms = 0;
        state->ack_state = 0;
        state->count = 0;
    }
    return 0;
}

/**
 * Return count of unacknowledged alarms.
 */
static int alarm_get_unack_count(void)
{
    int i, count = 0;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code == 0)
            continue;
        if (alarm_states[i].raised_at_ms > 0 && alarm_states[i].ack_state == 0) {
            count++;
        }
    }
    return count;
}

/**
 * Operator acknowledgment of an alarm.
 */
static int alarm_ack_by_operator(int alarm_code, int op_id)
{
    if (alarm_acknowledge(alarm_code, op_id) == 0) {
        return 0;
    }
    return -1;
}

/**
 * Return the alarm state object (read-only access for display).
 */
static const AlarmState *alarm_get_state_ro(int alarm_code)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code == alarm_code)
            return &alarm_states[i];
    }
    return NULL;
}

/**
 * Reset all alarms (system action, e.g., at startup or emergency reset).
 */
static void alarm_reset_all(void)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code != 0) {
            alarm_reset(alarm_states[i].alarm_code);
        }
    }
    alarm_hist_head = 0;
    alarm_hist_count = 0;
    rate_limit_count = 0;
}

/**
 * Compute alarm statistics for diagnostics.
 */
static void alarm_stat_summary(int *total_raised, int *total_unack,
                                int *total_suppressed)
{
    int i;
    *total_raised = 0;
    *total_unack = 0;
    *total_suppressed = 0;

    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code == 0)
            continue;

        if (alarm_states[i].raised_at_ms > 0) {
            (*total_raised)++;
        }
        if (alarm_states[i].ack_state == 0 && alarm_states[i].raised_at_ms > 0) {
            (*total_unack)++;
        }
        if (alarm_states[i].shelve_until_sec > 0) {
            (*total_suppressed)++;
        }
    }
}

/**
 * Check if any critical alarms (priority 0) are unacknowledged.
 */
static int alarm_has_critical(void)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        const AlarmDef *def = alarm_lookup(alarm_states[i].alarm_code);
        if (!def)
            continue;

        if (def->priority == 0 &&
            alarm_states[i].raised_at_ms > 0 &&
            alarm_states[i].ack_state == 0) {
            return 1;
        }
    }
    return 0;
}

/**
 * Log alarm state change (audit trail).
 */
static void alarm_audit_log(int alarm_code, const char *action)
{
    /* In a real system, this would write to an audit queue or file.
     * Here we just demonstrate the function exists. */
    (void)alarm_code;
    (void)action;
}

/**
 * Initialize the entire alarm subsystem (called from ww_init).
 */
static void alarm_system_init(void)
{
    alarm_state_init();
    alarm_point_debounce_init();
    alarm_reset_all();
    alarm_msg_queue_ready = 1;
}

/**
 * Validate alarm configuration (e.g., at startup).
 */
static int alarm_validate_config(void)
{
    int i, count = 0;

    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_table[i].alarm_code != 0) {
            if (alarm_table[i].upper_thresh <= alarm_table[i].lower_thresh) {
                return -1;  /* Invalid thresholds */
            }
            count++;
        }
    }

    return count;
}

/**
 * Dump alarm configuration for logging.
 */
static void alarm_config_dump(void)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        const AlarmDef *def = &alarm_table[i];
        if (def->alarm_code == 0)
            break;

        /* Simplified: would normally write to a log buffer */
        (void)def;
    }
}

/**
 * Process a shelve-clear request when timer expires.
 */
static void alarm_process_unshelve_events(void)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].shelve_until_sec > 0) {
            /* In a real implementation, compare against current time_sec */
            alarm_shelve_clear(alarm_states[i].alarm_code);
        }
    }
}

/**
 * Query pending alarms (alarm count in each queue).
 */
static int alarm_query_queue_depth(int queue_id)
{
    /* Simplified: return a plausible depth */
    if (queue_id == Q_ALARM_HI)
        return alarm_get_critical() != 0 ? 1 : 0;
    if (queue_id == Q_ALARM_LO)
        return alarm_get_unack_count();
    return 0;
}

/**
 * Format a detailed alarm report string for UI/export.
 */
static void alarm_format_report(char *buf, int maxlen)
{
    int total_raised, total_unack, total_suppressed;
    if (!buf || maxlen <= 0) return;

    alarm_stat_summary(&total_raised, &total_unack, &total_suppressed);
    snprintf(buf, maxlen, "Alarms: %d raised, %d unack, %d shelved",
             total_raised, total_unack, total_suppressed);
}

/**
 * Simulate hysteresis recovery (for testing).
 */
static int alarm_test_hysteresis_recovery(int alarm_code, int new_value)
{
    const AlarmDef *def = alarm_lookup(alarm_code);
    if (!def) return -1;

    return alarm_hysteresis_check(def->alarm_code, new_value,
                                   def->upper_thresh, def->lower_thresh,
                                   def->hysteresis);
}

/**
 * Map alarm severity to color/icon for UI display.
 */
static const char *alarm_severity_to_color(int severity)
{
    if (severity >= 8)
        return "RED";
    else if (severity >= 5)
        return "ORANGE";
    else if (severity >= 3)
        return "YELLOW";
    else
        return "GRAY";
}

/**
 * Generate a unique alarm ID (sequence number).
 */
static int alarm_generate_id(void)
{
    static int alarm_seq = 1000;
    return ++alarm_seq;
}

/**
 * Check if operator has permission to acknowledge specific alarm.
 */
static int alarm_operator_has_permission(int operator_id, int alarm_code)
{
    /* Simplified permission model: operator 0 can ack anything,
     * others require specific permission bits */
    if (operator_id == 0)
        return 1;

    const AlarmDef *def = alarm_lookup(alarm_code);
    if (!def) return 0;

    /* Critical alarms require supervisor (operator_id < 10) */
    if (def->priority == 0 && operator_id >= 10)
        return 0;

    return 1;
}

/**
 * Validate sensor reading against physical limits.
 */
static int alarm_validate_sensor_value(int point_id, float value)
{
    /* Check for physically impossible values */
    switch (point_id) {
        case PT_MOTOR_TEMP:
            if (value < -50.0f || value > 150.0f) return 0;  /* Invalid */
            break;
        case PT_TANK_LEVEL:
            if (value < 0.0f || value > 100.0f) return 0;
            break;
        case PT_PRESSURE:
            if (value < 0.0f || value > 15.0f) return 0;
            break;
        case PT_FLOW_RATE:
            if (value < 0.0f || value > 500.0f) return 0;
            break;
        default:
            break;
    }
    return 1;  /* Valid */
}

/**
 * Calculate time-weighted severity increase.
 * Alarms that persist longer should escalate.
 */
static int alarm_escalate_severity_by_age(int alarm_code, int age_ms)
{
    const AlarmDef *def = alarm_lookup(alarm_code);
    if (!def) return 0;

    int escalation = (age_ms / 60000);  /* +1 severity every minute */
    int new_severity = def->severity + escalation;
    if (new_severity > 10) new_severity = 10;

    return new_severity;
}

/**
 * Determine if an alarm is "flapping" (rapid state transitions).
 */
static int alarm_is_flapping(int alarm_code)
{
    AlarmState *state = NULL;
    alarm_get_state(alarm_code, &state);
    if (!state) return 0;

    /* Flapping = many state changes in short time window */
    return (state->count >= 5);  /* Simplified: >=5 raise/clear cycles */
}

/**
 * Format alarm for export to external systems (e.g., SNMP, syslog).
 */
static void alarm_export_format(int alarm_code, char *buf, int maxlen)
{
    const AlarmDef *def = alarm_lookup(alarm_code);
    AlarmState *state = NULL;
    const char *severity_str = "UNKNOWN";

    if (!buf || maxlen <= 0) return;

    alarm_get_state(alarm_code, &state);
    if (!state) return;

    if (def) {
        switch (def->severity) {
            case 9:
            case 10:
                severity_str = "CRITICAL";
                break;
            case 6:
            case 7:
            case 8:
                severity_str = "MAJOR";
                break;
            case 3:
            case 4:
            case 5:
                severity_str = "MINOR";
                break;
            default:
                severity_str = "INFO";
        }
    }

    snprintf(buf, maxlen, "ALM_ID=%04X|CODE=%04X|SEV=%s|ACK=%d|COUNT=%d",
             alarm_generate_id(), alarm_code, severity_str,
             state->ack_state, state->count);
}

/**
 * Batch acknowledge multiple alarms (operator dashboard action).
 */
static int alarm_batch_acknowledge(int *codes, int count, int operator_id)
{
    int i, acked = 0;

    for (i = 0; i < count; i++) {
        if (codes[i] == 0) break;
        if (alarm_operator_has_permission(operator_id, codes[i])) {
            if (alarm_acknowledge(codes[i], operator_id) == 0) {
                acked++;
            }
        }
    }

    return acked;
}

/**
 * Query alarm state for dashboard display.
 */
static void alarm_get_display_state(int alarm_code, int *severity,
                                     int *count, int *ack_state)
{
    const AlarmDef *def = alarm_lookup(alarm_code);
    AlarmState *state = NULL;

    *severity = 0;
    *count = 0;
    *ack_state = 0;

    alarm_get_state(alarm_code, &state);
    if (!state) return;

    if (def) *severity = def->severity;
    *count = state->count;
    *ack_state = state->ack_state;
}

/**
 * Compute overall system alarm state for LED/indicator.
 * Returns: 0=normal, 1=caution, 2=warning, 3=critical
 */
static int alarm_system_overall_state(void)
{
    int i, max_priority = 999;
    int has_critical = 0, has_major = 0, has_minor = 0;

    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code == 0) continue;
        if (alarm_states[i].raised_at_ms == 0) continue;  /* Not raised */

        const AlarmDef *def = alarm_lookup(alarm_states[i].alarm_code);
        if (!def) continue;

        if (def->priority == 0) has_critical = 1;
        if (def->priority == 1) has_major = 1;
        if (def->priority >= 2) has_minor = 1;
    }

    if (has_critical) return 3;
    if (has_major) return 2;
    if (has_minor) return 1;
    return 0;
}

/**
 * Simulate time passage for alarm state updates (used in testing).
 */
static void alarm_simulate_time_advance(int milliseconds)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code == 0) continue;
        if (alarm_states[i].raised_at_ms > 0) {
            alarm_states[i].raised_at_ms += milliseconds;
        }
        if (alarm_states[i].last_dispatch_ms > 0) {
            alarm_states[i].last_dispatch_ms += milliseconds;
        }
    }
}

/**
 * Export full alarm state as a structured record for historian.
 */
static void alarm_export_to_historian(int historian_archive_id)
{
    int i;
    char msg_buf[ALARM_MSG_BUFFER_SIZE];

    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code == 0) continue;
        if (alarm_states[i].raised_at_ms == 0) continue;

        alarm_format_message(alarm_states[i].alarm_code, msg_buf, sizeof(msg_buf));
        /* In real code: would call scf_hist_save(historian_archive_id, &rec) */
    }
}

/**
 * Dump complete alarm subsystem statistics.
 */
static void alarm_dump_statistics(void)
{
    int i, total_defs = 0, total_raised = 0;
    int total_unack = 0, total_ack = 0;
    int total_suppressed = 0, total_chatter = 0;

    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_table[i].alarm_code != 0)
            total_defs++;

        if (alarm_states[i].alarm_code == 0) continue;

        if (alarm_states[i].raised_at_ms > 0) {
            total_raised++;
            if (alarm_states[i].ack_state == 0)
                total_unack++;
            else
                total_ack++;
        }

        if (alarm_states[i].shelve_until_sec > 0)
            total_suppressed++;

        if (alarm_is_flapping(alarm_states[i].alarm_code))
            total_chatter++;
    }

    /* Simplified diagnostic output (in real system: log or write to buffer) */
    (void)total_defs;
    (void)total_raised;
    (void)total_unack;
    (void)total_ack;
    (void)total_suppressed;
    (void)total_chatter;
}

/**
 * Determine recommended maintenance action based on alarm pattern.
 */
static const char *alarm_suggest_maintenance(int alarm_code)
{
    AlarmState *state = NULL;
    const AlarmDef *def = alarm_lookup(alarm_code);

    alarm_get_state(alarm_code, &state);
    if (!state || !def) return "UNKNOWN";

    if (alarm_is_flapping(alarm_code))
        return "CHECK SENSOR CONNECTIONS";

    if (alarm_is_shelved(alarm_code))
        return "REVIEW SETPOINT CALIBRATION";

    if (state->count > 100)
        return "SCHEDULE PREVENTIVE MAINTENANCE";

    if (def->priority == 0)
        return "IMMEDIATE ATTENTION REQUIRED";

    return "MONITOR TREND";
}

/**
 * Reset statistics counters (system maintenance action).
 */
static void alarm_reset_statistics(void)
{
    int i;
    for (i = 0; i < ALARM_TABLE_SIZE; i++) {
        if (alarm_states[i].alarm_code != 0) {
            alarm_states[i].count = 0;
        }
    }
    rate_limit_count = 0;
    rate_limit_window_start_sec = 0;
}

/**
 * Emergency "all stop" action - suppress all alarms and log event.
 */
static void alarm_emergency_stop(void)
{
    alarm_suppress_all();
    alarm_audit_log(0xFFFF, "EMERGENCY_STOP");
}

/* ================================================================
 * GROUND TRUTH DOCUMENTATION
 * ================================================================
 *
 * TRACED CALLS IN THIS FILE:
 *
 * 1. scf_var_evt(EVT_ALARM_RAISED, 1, data)
 *    Location: ww_on_alarm() function
 *    Type: EVENT (call_number source)
 *    call_number: EVT_ALARM_RAISED = 3002
 *    Path: main -> scf_evt_register(EVENT,ww_on_alarm) -> ww_on_alarm -> scf_var_evt
 *    Description: Records each alarm raise event in the event log with call_number.
 *
 * 2. RAISE_ALARM(alarm_code) macro expansion -> scf_alarmq_enq(Q_ALARM_HI, alarm_code)
 *    Location: ww_alarm_dispatch() when def->priority == 0
 *    Type: ENQ
 *    arg1: Q_ALARM_HI = 10 (injected by macro)
 *    arg2: alarm_code (e.g., ALM_OVERTEMP = 0x0901)
 *    Path: ... -> ww_on_alarm -> ww_alarm_dispatch -> RAISE_ALARM -> scf_alarmq_enq
 *    Description: High-priority alarms enqueued to critical queue.
 *
 * 3. scf_alarmq_enq(Q_ALARM_LO, ALM_LOWLEVEL) - direct call
 *    Location: ww_alarm_dispatch() when alarm_code == ALM_LOWLEVEL
 *    Type: ENQ
 *    arg1: Q_ALARM_LO = 11
 *    arg2: ALM_LOWLEVEL = 0x0902
 *    Path: ... -> ww_on_alarm -> ww_alarm_dispatch -> scf_alarmq_enq (direct)
 *    Description: Low-priority alarms enqueued to background queue.
 *
 * 4. scf_alarmq_enq(Q_ALARM_LO, alarm_code) - direct call (alternative)
 *    Location: ww_alarm_dispatch() when priority > 0 and priority <= 2
 *    Type: ENQ
 *    arg1: Q_ALARM_LO = 11
 *    arg2: alarm_code (various medium-priority codes)
 *    Description: General medium/low priority alarm enqueue.
 *
 * 5. scf_alarmq_deq(Q_ALARM_LO, &dummy_out)
 *    Location: alarm_dequeue_pending() called from ww_alarm_dispatch()
 *    Type: DEQ
 *    arg1: Q_ALARM_LO = 11
 *    Description: Dequeue pending alarms from low-priority queue for processing.
 *
 * 6. scf_msgq_write(Q_MSG, msg_buf)
 *    Location: ww_alarm_dispatch() when alarm_msg_queue_ready == 1
 *    Type: WRITEQ
 *    arg1: Q_MSG = 13
 *    arg2: msg_buf (formatted alarm message)
 *    Description: Send formatted alarm message to message queue for UI/export.
 *
 * 7. ww_alarm_check(pid, value)
 *    Location: Called from ww_on_scan (ww_control.c) when scan cycle detects value change
 *    Returns: count of alarms dispatched
 *    Description: Applies threshold, debounce, hysteresis logic; dispatches alarms.
 *
 * ================================================================
 */

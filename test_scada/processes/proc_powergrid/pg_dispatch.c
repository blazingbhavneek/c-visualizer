/* pg_dispatch.c — Electrical dispatch engine for substation RTU
 * Implements breaker control, load-flow heuristics, tap-changer logic,
 * and command validation/confirmation handling.
 *
 * GROUND TRUTH:
 * pg_on_dispatch -> scf_var_evt(EVT_ALARM_RAISED,1,data) EVENT call_number=3002
 *               -> pg_dispatch_load(PT_FLOW_RATE)
 * pg_breaker_cmd -> scf_evt_post(EVT_VALVE_CMD,0) EVENT arg1=3003
 *               -> pg_send_cmd(Q_CMD, code)
 * pg_send_cmd -> scf_msgq_write(Q_MSG,msg) WRITEQ arg1=13
 *             -> scf_cmdq_load(Q_CMD) LOADQ arg1=12
 *             -> scf_alarmq_enq(Q_ALARM_HI,ALM_OVERPRESSURE) ENQ arg1=10 arg2=0x0903
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "pg_app.h"
#include "scf_types.h"
#include "scf_const.h"
#include "scf_queue.h"
#include "scf_event.h"

/* ===== STATIC CONSTANTS & CONFIGURATION ===== */

/* Feeder names and baseline parameters */
static const char *feeder_names[] = {
    "FEEDER_A_132kV",
    "FEEDER_B_69kV",
    "FEEDER_C_138kV",
    "FEEDER_D_13.8kV"
};

/* Load-flow priority tables (dispatch order) */
static int dispatch_priority_table[] = {
    0, 1, 2, 3, 0, 1  /* Round-robin with weight */
};

/* Breaker inter-lock matrix: [from][to] */
static int breaker_interlock[4][4] = {
    { 0, 1, 1, 0 },  /* Feeder A: cannot sync with B,C */
    { 1, 0, 1, 0 },
    { 1, 1, 0, 0 },
    { 0, 0, 0, 0 }
};

/* Tap-changer nominal and limit settings per feeder */
static struct TapSettings {
    int nominal;
    int min_tap;
    int max_tap;
    int deadband;
} tap_settings[] = {
    { 8, 0, 16, 1 },   /* Feeder A: 132kV autotransformer */
    { 8, 0, 32, 2 },
    { 6, 0, 16, 1 },
    { 4, 0, 8,  1 }
};

/* Economical dispatch cost coefficients ($/MWh) */
static float econ_costs[] = { 45.2f, 38.7f, 52.1f, 35.5f };

/* Voltage control set-points (pu) */
static float voltage_setpoints[] = { 1.05f, 1.02f, 1.03f, 0.98f };

/* Over-current relay trip thresholds (Amperes) */
static int overcurrent_limits[] = { 2500, 2000, 2200, 800 };

/* Reactive power dispatch limits (MVar) */
static int reactive_limits[] = { 150, 120, 140, 50 };

/* ===== DISPATCH STATE MACHINE ===== */

typedef struct {
    int feeder_id;
    int state;               /* 0=idle, 1=armed, 2=executing, 3=confirmed */
    unsigned int timestamp;
    int confirmation_pending;
    int retry_count;
    int last_error;
} DispatchState;

static DispatchState dispatch_state[4] = {
    { 0, 0, 0, 0, 0, 0 },
    { 1, 0, 0, 0, 0, 0 },
    { 2, 0, 0, 0, 0, 0 },
    { 3, 0, 0, 0, 0, 0 }
};

/* ===== LOAD FLOW CACHE ===== */

typedef struct {
    int feeder;
    float active_power;     /* MW */
    float reactive_power;   /* MVar */
    float voltage;          /* pu */
    float current;          /* A */
    int quality;
    unsigned int age_ms;
} LoadFlowSnapshot;

static LoadFlowSnapshot lf_cache[4] = {
    { 0, 0.0f, 0.0f, 1.05f, 0, 100, 0 },
    { 1, 0.0f, 0.0f, 1.02f, 0, 100, 0 },
    { 2, 0.0f, 0.0f, 1.03f, 0, 100, 0 },
    { 3, 0.0f, 0.0f, 0.98f, 0, 100, 0 }
};

/* ===== COMMAND QUEUE STRUCTURES ===== */

typedef struct {
    int cmd_type;           /* 1=breaker_trip, 2=breaker_close, 3=tap_change */
    int feeder_id;
    int value;              /* New tap position or breaker state */
    int priority;
    unsigned int issue_time;
    int sender_id;
} DispatchCmd;

static DispatchCmd pending_cmd = { 0, 0, 0, 0, 0, 0 };

/* ===== BREAKER STATE MACHINE ===== */

typedef struct {
    int feeder_id;
    int trip_coil_state;    /* 0=de-energized, 1=energized */
    int close_coil_state;
    int mechanism_pos;      /* 0=open, 1=closed, 2=intermediate */
    int auto_reclose_armed;
    unsigned int reclose_delay_ms;
    int overcurrent_detected;
} BreakerState;

static BreakerState breaker_state[4] = {
    { 0, 0, 0, 1, 0, 3000, 0 },
    { 1, 0, 0, 1, 0, 3000, 0 },
    { 2, 0, 0, 1, 0, 3000, 0 },
    { 3, 0, 0, 1, 0, 3000, 0 }
};

/* ===== TAP-CHANGER STATE MACHINE ===== */

typedef struct {
    int feeder_id;
    int current_tap;
    int target_tap;
    int motor_enabled;
    int step_in_progress;
    unsigned int step_start_time;
    unsigned int step_duration_ms;  /* ~1000ms per tap */
    int direction;                   /* -1=down, 0=idle, +1=up */
} TapChangerState;

static TapChangerState tap_state[4] = {
    { 0, 8, 8, 0, 0, 0, 1200, 0 },
    { 1, 8, 8, 0, 0, 0, 1200, 0 },
    { 2, 6, 6, 0, 0, 0, 1200, 0 },
    { 3, 4, 4, 0, 0, 0, 1200, 0 }
};

/* ===== COMMAND/EVENT MESSAGE FORMAT ===== */

typedef struct {
    int msg_type;           /* 0x1=cmd_execute, 0x2=cmd_cancel, 0x4=cmd_confirm */
    int feeder;
    int action;
    int parameter;
    unsigned int timestamp;
} CommandMsg;

/* ===== HELPER FUNCTION PROTOTYPES ===== */

/* Load flow computations */
static float compute_active_power(int feeder);
static float compute_reactive_power(int feeder);
static float compute_bus_voltage(int feeder);
static int validate_power_mismatch(int feeder);

/* Breaker control */
static int breaker_check_interlocks(int from_feeder, int to_feeder);
static int breaker_close_sequence(int feeder);
static int breaker_trip_sequence(int feeder);
static int breaker_verify_position(int feeder);

/* Tap-changer control */
static int tap_changer_direction(int feeder, float v_error);
static int tap_calculate_steps(int feeder, float target_voltage);
static int tap_motor_start(int feeder, int direction);
static int tap_motor_stop(int feeder);
static int tap_step_execute(int feeder);

/* Economic dispatch */
static int econ_dispatch_order(int *feeder_list, int count);
static float econ_calculate_cost(int feeder, float power_output);
static int econ_optimize_generation(void);

/* Command validation & confirmation */
static int validate_command(int feeder, int cmd_type, int value);
static int send_confirmation(int feeder, int status);
static int handle_command_timeout(int feeder);

/* Priority & state */
static int get_next_dispatch_feeder(void);
static int update_dispatch_state(int feeder, int new_state);

/* ===== LOAD FLOW COMPUTATION ENGINE ===== */

static float compute_active_power(int feeder)
{
    /* Stub load-flow: returns MW based on voltage and configured cost.
     * In production, this would solve AC or DC power flow. */
    float v = lf_cache[feeder].voltage;
    float p_base = 100.0f * v * v;  /* Simple quadratic model */
    float cost_factor = econ_costs[feeder] / 50.0f;
    return p_base * (1.0f - 0.05f * cost_factor);
}

static float compute_reactive_power(int feeder)
{
    float v = lf_cache[feeder].voltage;
    float v_error = v - voltage_setpoints[feeder];

    /* Q ~ voltage regulation error: +/- few MVar per 0.01pu */
    return v_error * 50.0f * 100.0f;  /* Roughly 500 MVar / 0.01pu */
}

static float compute_bus_voltage(int feeder)
{
    /* Iterative voltage calculation mock: depends on load and tap */
    float v_base = voltage_setpoints[feeder];
    int tap_delta = tap_state[feeder].current_tap - tap_settings[feeder].nominal;
    float tap_v_change = tap_delta * 0.00625f;  /* 0.625% per tap */

    float load_drop = 0.02f * (lf_cache[feeder].active_power / 100.0f);

    return v_base + tap_v_change - load_drop;
}

static int validate_power_mismatch(int feeder)
{
    /* Verify active/reactive power balance within limits */
    float p = lf_cache[feeder].active_power;
    float q = lf_cache[feeder].reactive_power;

    if (p > 250.0f || q > 200.0f) {
        return -1;  /* Limit violation */
    }
    return 0;
}

/* ===== BREAKER CONTROL LOGIC ===== */

static int breaker_check_interlocks(int from_feeder, int to_feeder)
{
    /* Matrix check: can 'from' connect to 'to'? */
    if (from_feeder < 0 || from_feeder >= 4 || to_feeder < 0 || to_feeder >= 4)
        return -1;

    if (breaker_interlock[from_feeder][to_feeder] == 0) {
        return 0;  /* Interlock allows */
    }
    return -1;  /* Interlock violation */
}

static int breaker_close_sequence(int feeder)
{
    BreakerState *b = &breaker_state[feeder];

    if (b->mechanism_pos == 1)
        return 0;  /* Already closed */

    if (b->overcurrent_detected)
        return -1;  /* Cannot close with overcurrent */

    /* Energize close coil, wait for mechanism */
    b->close_coil_state = 1;
    b->mechanism_pos = 1;
    b->close_coil_state = 0;  /* De-energize after close */

    return 0;
}

static int breaker_trip_sequence(int feeder)
{
    BreakerState *b = &breaker_state[feeder];

    if (b->mechanism_pos == 0)
        return 0;  /* Already open */

    b->trip_coil_state = 1;
    b->mechanism_pos = 0;
    b->trip_coil_state = 0;

    if (b->auto_reclose_armed) {
        /* Arm reclose after delay */
        b->overcurrent_detected = 0;
    }

    return 0;
}

static int breaker_verify_position(int feeder)
{
    BreakerState *b = &breaker_state[feeder];
    return b->mechanism_pos;
}

/* ===== TAP-CHANGER CONTROL LOGIC ===== */

static int tap_changer_direction(int feeder, float v_error)
{
    if (v_error > 0.01f)
        return -1;  /* Voltage too high: reduce tap (down) */
    if (v_error < -0.01f)
        return 1;   /* Voltage too low: raise tap (up) */
    return 0;       /* Within deadband */
}

static int tap_calculate_steps(int feeder, float target_voltage)
{
    float v_error = target_voltage - voltage_setpoints[feeder];
    float steps_needed = v_error / 0.00625f;  /* Per step */
    return (int)(steps_needed > 0 ? steps_needed + 0.5f : steps_needed - 0.5f);
}

static int tap_motor_start(int feeder, int direction)
{
    TapChangerState *t = &tap_state[feeder];

    if (t->step_in_progress)
        return -1;  /* Already stepping */

    t->motor_enabled = 1;
    t->direction = direction;
    t->step_in_progress = 1;
    t->step_start_time = (unsigned int)time(NULL);

    return 0;
}

static int tap_motor_stop(int feeder)
{
    TapChangerState *t = &tap_state[feeder];

    if (!t->motor_enabled)
        return 0;

    t->motor_enabled = 0;
    t->step_in_progress = 0;
    t->direction = 0;

    return 0;
}

static int tap_step_execute(int feeder)
{
    TapChangerState *t = &tap_state[feeder];
    struct TapSettings *s = &tap_settings[feeder];

    if (t->direction == 0)
        return 0;  /* No step in progress */

    if (t->direction == 1) {
        if (t->current_tap < s->max_tap)
            t->current_tap++;
    } else if (t->direction == -1) {
        if (t->current_tap > s->min_tap)
            t->current_tap--;
    }

    /* Update voltage cache */
    lf_cache[feeder].voltage = compute_bus_voltage(feeder);

    return 0;
}

/* ===== ECONOMIC DISPATCH OPTIMIZATION ===== */

static int econ_dispatch_order(int *feeder_list, int count)
{
    /* Sort feeders by economic cost (greedy merit-order dispatch) */
    int i, j, temp;

    for (i = 0; i < count - 1; i++) {
        for (j = i + 1; j < count; j++) {
            if (econ_costs[feeder_list[i]] > econ_costs[feeder_list[j]]) {
                temp = feeder_list[i];
                feeder_list[i] = feeder_list[j];
                feeder_list[j] = temp;
            }
        }
    }

    return 0;
}

static float econ_calculate_cost(int feeder, float power_output)
{
    /* Simple linear cost model: $/h = c * P_MW */
    return econ_costs[feeder] * power_output;
}

static int econ_optimize_generation(void)
{
    /* Determine optimal generation dispatch for 4 feeders.
     * Constrained by:
     * - Individual feeder limits (250MW, 200MW, etc.)
     * - Total demand = sum of generation
     * - Minimum generation per feeder
     */
    int feeder_list[] = { 0, 1, 2, 3 };
    float total_demand = 300.0f;  /* Fixed load (stub) */
    float allocated = 0.0f;
    int i;

    econ_dispatch_order(feeder_list, 4);

    for (i = 0; i < 4; i++) {
        int f = feeder_list[i];
        float capacity_remaining = 250.0f - allocated;  /* Simplified */
        float to_allocate = (total_demand - allocated) / (4 - i);  /* Even split stub */

        if (to_allocate > capacity_remaining)
            to_allocate = capacity_remaining;
        if (to_allocate < 0)
            to_allocate = 0;

        lf_cache[f].active_power = to_allocate;
        allocated += to_allocate;
    }

    return 0;
}

/* ===== COMMAND VALIDATION & CONFIRMATION ===== */

static int validate_command(int feeder, int cmd_type, int value)
{
    if (feeder < 0 || feeder >= 4)
        return -1;  /* Invalid feeder */

    switch (cmd_type) {
    case 1:  /* Breaker trip */
    case 2:  /* Breaker close */
        if (breaker_state[feeder].overcurrent_detected)
            return -2;  /* Cannot change breaker during fault */
        break;
    case 3:  /* Tap change */
        if (value < tap_settings[feeder].min_tap ||
            value > tap_settings[feeder].max_tap)
            return -3;  /* Tap out of range */
        break;
    default:
        return -4;
    }

    return 0;  /* Valid */
}

static int send_confirmation(int feeder, int status)
{
    CommandMsg msg;
    msg.msg_type = 0x4;  /* Confirmation */
    msg.feeder = feeder;
    msg.action = status;  /* 0=success, <0=error */
    msg.parameter = 0;
    msg.timestamp = (unsigned int)time(NULL);

    /* Write to message queue */
    scf_msgq_write(Q_MSG, &msg);

    return 0;
}

static int handle_command_timeout(int feeder)
{
    DispatchState *d = &dispatch_state[feeder];

    d->retry_count++;
    if (d->retry_count >= 3) {
        d->state = 0;  /* Reset */
        d->last_error = -5;  /* Timeout */
        return -1;
    }

    return 0;  /* Retry */
}

/* ===== DISPATCH STATE MANAGEMENT ===== */

static int get_next_dispatch_feeder(void)
{
    /* Round-robin from priority table */
    static int priority_index = 0;
    int feeder = dispatch_priority_table[priority_index];
    priority_index = (priority_index + 1) % 6;
    return feeder;
}

static int update_dispatch_state(int feeder, int new_state)
{
    if (feeder < 0 || feeder >= 4)
        return -1;

    dispatch_state[feeder].state = new_state;
    dispatch_state[feeder].timestamp = (unsigned int)time(NULL);

    return 0;
}

/* ===== PUBLIC API FUNCTIONS ===== */

void pg_on_dispatch(int evt, void *data)
{
    /* Event handler for EVT_ALARM_RAISED */
    int feeder;
    int alarm_code;

    if (data == NULL)
        return;

    alarm_code = *(int *)data;

    /* Post variable event to trace */
    scf_var_evt(EVT_ALARM_RAISED, 1, data);

    /* Decode alarm to feeder + determine response */
    switch (alarm_code) {
    case ALM_OVERTEMP:
        feeder = 1;  /* Motor thermal */
        break;
    case ALM_LOWLEVEL:
        feeder = 0;  /* Tank level */
        break;
    case ALM_OVERPRESSURE:
        feeder = 2;  /* System pressure */
        break;
    default:
        feeder = 0;
    }

    /* Load dispatch parameters for this feeder */
    pg_dispatch_load(PT_FLOW_RATE);
}

int pg_dispatch_load(int feeder)
{
    /* Load state snapshot for feeder into cache.
     * 'feeder' is a point ID interpreted as feeder selector.
     * In this stub, we'll use PT_FLOW_RATE (0x1004) as generic event trigger.
     */

    int f;

    if (feeder == PT_FLOW_RATE)
        f = 0;  /* Default feeder */
    else
        f = feeder % 4;

    /* Recompute load-flow for this feeder */
    lf_cache[f].active_power = compute_active_power(f);
    lf_cache[f].reactive_power = compute_reactive_power(f);
    lf_cache[f].voltage = compute_bus_voltage(f);
    lf_cache[f].current = lf_cache[f].active_power * 1000.0f / (1.732f * lf_cache[f].voltage * 10.0f);
    lf_cache[f].age_ms = 0;

    /* Validate power balance */
    if (validate_power_mismatch(f) != 0) {
        lf_cache[f].quality = 0;
    } else {
        lf_cache[f].quality = 100;
    }

    /* Check if tap-changer adjustment needed */
    float v_error = lf_cache[f].voltage - voltage_setpoints[f];
    int tap_dir = tap_changer_direction(f, v_error);

    if (tap_dir != 0 && !tap_state[f].step_in_progress) {
        int steps = tap_calculate_steps(f, voltage_setpoints[f]);
        if (steps != 0) {
            tap_motor_start(f, tap_dir);
        }
    }

    return 0;
}

int pg_breaker_cmd(int feeder, int cmd)
{
    /* Issue breaker control command (trip/close).
     * cmd: 0=trip, 1=close
     */

    int status;

    if (feeder < 0 || feeder >= 4)
        return -1;

    /* Validate command */
    status = validate_command(feeder, (cmd ? 2 : 1), 0);
    if (status != 0)
        return status;

    /* Post event for tracing */
    scf_evt_post(EVT_VALVE_CMD, 0);

    /* Execute breaker sequence */
    if (cmd == 0) {
        breaker_trip_sequence(feeder);
    } else {
        breaker_close_sequence(feeder);
    }

    /* Verify final position */
    status = breaker_verify_position(feeder);

    /* Send command to device via message queue */
    pg_send_cmd(Q_CMD, (cmd << 8) | feeder);

    /* Confirm to operator */
    send_confirmation(feeder, 0);

    return status;
}

int pg_send_cmd(int queue_id, int code)
{
    /* Send control command to RTU output queue.
     * Manages messaging, command persistence, and alarm logging.
     */

    CommandMsg msg;
    int feeder;
    int status;

    feeder = code & 0xFF;
    if (feeder >= 4)
        return -1;

    /* Format command message */
    msg.msg_type = 0x1;  /* Execute */
    msg.feeder = feeder;
    msg.action = (code >> 8) & 0xFF;
    msg.parameter = 0;
    msg.timestamp = (unsigned int)time(NULL);

    /* Write to message queue for RTU transmission */
    scf_msgq_write(Q_MSG, &msg);

    /* Persist command to disk */
    scf_cmdq_load(Q_CMD);

    /* Check for alarm conditions that require notification */
    if (lf_cache[feeder].reactive_power > reactive_limits[feeder]) {
        scf_alarmq_enq(Q_ALARM_HI, ALM_OVERPRESSURE);
    }

    /* Update dispatch state */
    update_dispatch_state(feeder, 2);  /* Executing */

    return 0;
}

/* ===== ADDITIONAL HELPER IMPLEMENTATIONS (for realistic bulk) ===== */

static int emergency_load_shed(void)
{
    /* Shed non-critical loads if system unstable */
    int i, shed_count = 0;

    for (i = 0; i < 4; i++) {
        if (lf_cache[i].active_power > 200.0f) {
            pg_breaker_cmd(i, 0);  /* Trip feeder */
            shed_count++;
        }
    }

    return shed_count;
}

static int rebalance_taps(void)
{
    /* Iteratively adjust tap-changers for voltage profile */
    int i, steps_taken = 0;

    for (i = 0; i < 4; i++) {
        if (tap_state[i].step_in_progress)
            continue;

        float v_err = lf_cache[i].voltage - voltage_setpoints[i];
        if (v_err > tap_settings[i].deadband * 0.005f) {
            tap_motor_start(i, -1);
            steps_taken++;
        } else if (v_err < -tap_settings[i].deadband * 0.005f) {
            tap_motor_start(i, 1);
            steps_taken++;
        }
    }

    return steps_taken;
}

static void log_dispatch_event(int feeder, int event_type, int value)
{
    /* Stub logging for dispatch actions */
    (void)feeder;
    (void)event_type;
    (void)value;
}

static int check_breaker_coordination(int feeder1, int feeder2)
{
    /* Verify protection coordination between two feeders */
    if (breaker_state[feeder1].mechanism_pos == breaker_state[feeder2].mechanism_pos) {
        return -1;  /* Both in same state — may violate N-1 security */
    }
    return 0;
}

static int predict_load_growth(int feeder, int horizon_minutes)
{
    /* Stub forecaster for 5-30 min lookahead */
    (void)horizon_minutes;
    return lf_cache[feeder].active_power > 180.0f ? -1 : 0;
}

static float compute_thermal_rating(int feeder, int tap_pos)
{
    /* Return MVA rating at given tap for thermal constraints */
    float base_rating = 250.0f;
    float tap_derating = 1.0f - 0.02f * (tap_pos - tap_settings[feeder].nominal);
    return base_rating * tap_derating;
}

static int sync_bus_check(int feeder1, int feeder2)
{
    /* Verify voltage/phase compatibility for bus paralleling */
    float v_diff = lf_cache[feeder1].voltage - lf_cache[feeder2].voltage;

    if (v_diff < -0.05f || v_diff > 0.05f)
        return -1;  /* Voltage mismatch too large */

    return 0;
}

static int handle_protection_trip(int feeder, int trip_type)
{
    /* Respond to protection relay signal: trip_type 1=OC, 2=EF, 3=REF */
    breaker_state[feeder].overcurrent_detected = 1;

    pg_breaker_cmd(feeder, 0);  /* Trip immediately */

    log_dispatch_event(feeder, trip_type, 0);

    return 0;
}

static int check_reactive_reserve(int feeder)
{
    /* Verify reactive power margin available */
    float q_available = reactive_limits[feeder] - lf_cache[feeder].reactive_power;

    return q_available > 20.0f ? 0 : -1;
}

static int automatic_voltage_control(void)
{
    /* Run AVR on all feeders for integrated voltage support */
    int i, actions = 0;

    for (i = 0; i < 4; i++) {
        float v_err = lf_cache[i].voltage - voltage_setpoints[i];

        if (v_err > 0.02f && check_reactive_reserve(i) == 0) {
            /* Voltage high & Q available: increase reactive */
            lf_cache[i].reactive_power += 10.0f;
            actions++;
        } else if (v_err < -0.02f) {
            /* Voltage low: decrease reactive */
            lf_cache[i].reactive_power -= 10.0f;
            if (lf_cache[i].reactive_power < -reactive_limits[i])
                lf_cache[i].reactive_power = -reactive_limits[i];
            actions++;
        }
    }

    return actions;
}

static int sequential_tap_control(int feeder, int direction, int steps)
{
    /* Execute multi-step tap sequence with inter-step delay */
    int i, status;

    for (i = 0; i < steps; i++) {
        status = tap_motor_start(feeder, direction);
        if (status != 0)
            return status;

        tap_step_execute(feeder);
        tap_motor_stop(feeder);

        /* In production: wait ~1 second per step */
    }

    return 0;
}

static void dump_dispatch_state(void)
{
    int i;
    for (i = 0; i < 4; i++) {
        log_dispatch_event(i, dispatch_state[i].state, 0);
    }
}

static int detect_islanding(int feeder1, int feeder2)
{
    /* Simple islanding detector: loss of sync indication */
    float f_diff = lf_cache[feeder1].current - lf_cache[feeder2].current;

    if (f_diff > 500.0f)  /* Large current imbalance */
        return -1;

    return 0;
}

static int execute_contingency_plan(int contingency_type)
{
    /* Stub contingency response: loss of genset, line fault, etc. */
    int response = -1;

    switch (contingency_type) {
    case 1:  /* Loss of largest genset */
        response = emergency_load_shed();
        break;
    case 2:  /* Line fault (trip both ends) */
        pg_breaker_cmd(0, 0);
        pg_breaker_cmd(1, 0);
        response = 0;
        break;
    case 3:  /* Voltage collapse */
        automatic_voltage_control();
        response = 0;
        break;
    }

    return response;
}

/* ===== EXTENDED LOAD-FLOW SOLVER ===== */

typedef struct {
    int iteration;
    float mismatch_p;
    float mismatch_q;
    float convergence_tolerance;
} LoadFlowIteration;

static LoadFlowIteration lf_iteration = { 0, 0.0f, 0.0f, 0.001f };

static int newton_raphson_iteration(void)
{
    /* Simplified Newton-Raphson power flow iteration.
     * Solves: P_injection = V_mag * sum(Y_ik * V_k * cos(theta_ik - theta_i - theta_k))
     * This is a stub that demonstrates realistic numerical method structure.
     */
    int i, iter_count = 0;
    float max_error = 1.0f;

    while (max_error > lf_iteration.convergence_tolerance && iter_count < 20) {
        max_error = 0.0f;

        for (i = 0; i < 4; i++) {
            /* Compute power residuals */
            float p_inj = compute_active_power(i);
            float q_inj = compute_reactive_power(i);

            float p_calc = p_inj;  /* Stub */
            float q_calc = q_inj;  /* Stub */

            lf_iteration.mismatch_p = p_calc - p_inj;
            lf_iteration.mismatch_q = q_calc - q_inj;

            float error = lf_iteration.mismatch_p * lf_iteration.mismatch_p +
                         lf_iteration.mismatch_q * lf_iteration.mismatch_q;

            if (error > max_error)
                max_error = error;

            /* Update tap changer if needed (voltage control loop) */
            if (lf_cache[i].voltage < voltage_setpoints[i] - 0.01f) {
                if (tap_state[i].current_tap < tap_settings[i].max_tap)
                    tap_state[i].current_tap++;
            }
        }

        iter_count++;
    }

    lf_iteration.iteration = iter_count;
    return (iter_count < 20) ? 0 : -1;
}

static int linearized_powerflow(void)
{
    /* DC power flow approximation for fast contingency screening */
    int i, j;
    float susceptance[4][4] = {
        { 10.0f, -5.0f,  0.0f, -2.0f },
        { -5.0f,  8.0f, -2.0f, -1.0f },
        {  0.0f, -2.0f,  7.0f, -3.0f },
        { -2.0f, -1.0f, -3.0f,  6.0f }
    };

    for (i = 0; i < 4; i++) {
        float p_flow = 0.0f;
        for (j = 0; j < 4; j++) {
            if (i != j) {
                /* Simplified angle assumption */
                float angle_diff = (i - j) * 0.05f;
                p_flow += susceptance[i][j] * angle_diff * 100.0f;
            }
        }
        lf_cache[i].active_power += p_flow;
    }

    return 0;
}

/* ===== ADVANCED PROTECTION COORDINATION ===== */

typedef struct {
    int relay_id;
    int device_type;         /* 1=OC, 2=EF, 3=REF, 4=UV, 5=OV */
    int primary_zone;
    int backup_zone;
    float pickup_threshold;
    float time_dial;
    int coordination_group;
} ProtectionRelay;

static ProtectionRelay relays[] = {
    { 1, 1, 0, 1, 2000.0f, 0.5f, 0 },  /* OC relay F1 primary zone */
    { 2, 1, 1, 2, 2000.0f, 0.6f, 0 },  /* OC relay F2 backup */
    { 3, 2, 0, 0, 200.0f,  1.0f, 1 },  /* EF relay */
    { 4, 5, 0, 0, 1.1f,    1.0f, 2 },  /* OV relay */
    { 5, 4, 0, 0, 0.9f,    1.0f, 3 }   /* UV relay */
};

static int verify_protection_coordination(int relay1_id, int relay2_id)
{
    /* Check that primary relay clears before backup (CT ratio accounted) */
    float time_primary = relays[relay1_id].time_dial * 0.1f;    /* ~0.05-0.1s */
    float time_backup = relays[relay2_id].time_dial * 0.15f;    /* ~0.1-0.2s margin */

    if (time_primary >= time_backup)
        return -1;  /* Coordination loss */

    return 0;
}

static int assess_fault_transient(int feeder, float fault_current)
{
    /* Evaluate breaker transient response to fault initiation */
    BreakerState *b = &breaker_state[feeder];

    if (fault_current > overcurrent_limits[feeder]) {
        b->overcurrent_detected = 1;
        return 1;  /* Trip required */
    }

    return 0;
}

static int coordinate_protection_group(int group_id)
{
    /* Verify all relays in a group have correct backup arrangement */
    int i, pass = 0;

    for (i = 0; i < 5; i++) {
        if (relays[i].coordination_group != group_id)
            continue;

        if (verify_protection_coordination(i, (i + 1) % 5) == 0)
            pass++;
    }

    return (pass > 0) ? 0 : -1;
}

/* ===== SYSTEM SECURITY & CONTINGENCY ANALYSIS ===== */

typedef struct {
    int contingency_id;
    int element_type;        /* 1=gen, 2=line, 3=transformer, 4=load */
    int element_id;
    int severity;            /* 0=minor, 1=moderate, 2=severe, 3=blackout */
    int is_credible;         /* N-1 criterion */
} Contingency;

static Contingency contingencies[] = {
    { 1, 1, 0, 1, 1 },       /* Loss of generator 0 */
    { 2, 2, 0, 1, 1 },       /* Loss of line 0-1 */
    { 3, 3, 0, 0, 1 },       /* Loss of transformer */
    { 4, 4, 0, 2, 1 },       /* Sudden load drop */
    { 5, 1, 1, 2, 0 }        /* Simultaneous gen loss (N-2) */
};

static int screen_contingencies(void)
{
    /* Identify credible contingencies (N-1) */
    int i, count = 0;

    for (i = 0; i < 5; i++) {
        if (contingencies[i].is_credible) {
            count++;
            if (contingencies[i].severity > 2) {
                return -1;  /* Severe condition found */
            }
        }
    }

    return count;
}

static int evaluate_contingency(int cont_id, int *feeder_impacts)
{
    /* Run power flow for contingency scenario */
    int i;

    for (i = 0; i < 4; i++)
        feeder_impacts[i] = 0;

    switch (contingencies[cont_id].element_type) {
    case 1:  /* Generator loss */
        if (contingencies[cont_id].element_id < 2)
            feeder_impacts[contingencies[cont_id].element_id] = -50;
        break;
    case 2:  /* Line loss */
        feeder_impacts[0]++;
        feeder_impacts[1]++;
        break;
    }

    return newton_raphson_iteration();
}

static int post_contingency_correction(int cont_id)
{
    /* Automatic corrective controls for contingency */
    int impacts[4] = { 0 };
    int i;

    evaluate_contingency(cont_id, impacts);

    for (i = 0; i < 4; i++) {
        if (impacts[i] < -40)
            pg_breaker_cmd(i, 1);  /* Reclose */
    }

    return 0;
}

/* ===== REAL-TIME MONITORING & ALARM HANDLING ===== */

typedef struct {
    int alarm_code;
    int feeder_id;
    unsigned int onset_time;
    int acknowledged;
    int auto_cleared;
} ActiveAlarm;

static ActiveAlarm alarm_stack[10];
static int alarm_count = 0;

static int log_alarm(int code, int feeder)
{
    if (alarm_count >= 10)
        return -1;  /* Stack full */

    alarm_stack[alarm_count].alarm_code = code;
    alarm_stack[alarm_count].feeder_id = feeder;
    alarm_stack[alarm_count].onset_time = (unsigned int)time(NULL);
    alarm_stack[alarm_count].acknowledged = 0;
    alarm_stack[alarm_count].auto_cleared = 0;

    alarm_count++;

    scf_alarmq_enq(Q_ALARM_HI, code);

    return 0;
}

static int acknowledge_alarm(int index)
{
    if (index < 0 || index >= alarm_count)
        return -1;

    alarm_stack[index].acknowledged = 1;
    return 0;
}

static int check_alarm_recovery(int feeder)
{
    /* Verify fault condition has cleared */
    if (lf_cache[feeder].quality < 50)
        return -1;  /* Still faulted */

    breaker_state[feeder].overcurrent_detected = 0;
    return 0;
}

static int clear_old_alarms(void)
{
    int i, cleared = 0;
    unsigned int now = (unsigned int)time(NULL);

    for (i = 0; i < alarm_count; i++) {
        if (alarm_stack[i].acknowledged &&
            (now - alarm_stack[i].onset_time) > 3600) {  /* >1 hour old */

            alarm_stack[i].auto_cleared = 1;
            cleared++;
        }
    }

    return cleared;
}

static int filter_alarm_chatter(int code, int feeder)
{
    /* Debounce repeated alarms on same element */
    static int last_alarm_code = 0;
    static int last_feeder = -1;
    static unsigned int last_time = 0;
    unsigned int now = (unsigned int)time(NULL);

    if (code == last_alarm_code && feeder == last_feeder) {
        if ((now - last_time) < 2)  /* Within 2 seconds */
            return -1;  /* Suppress duplicate */
    }

    last_alarm_code = code;
    last_feeder = feeder;
    last_time = now;

    return 0;
}

/* ===== ADVANCED DISPATCH SCHEDULING ===== */

typedef struct {
    int schedule_id;
    int feeder_id;
    int action;              /* 1=dispatch, 2=ramp, 3=reserve, 4=curtail */
    unsigned int start_time;
    unsigned int duration_sec;
    float target_mw;
} DispatchSchedule;

static DispatchSchedule schedules[8] = {
    { 1, 0, 1, 0, 600, 80.0f },   /* Dispatch 80MW at feeder 0 for 10min */
    { 2, 1, 3, 300, 900, 50.0f }, /* Curtail to 50MW after 5min */
    { 3, 2, 1, 600, 600, 120.0f },
    { 4, 3, 2, 900, 1800, 30.0f },
    { 5, 0, 3, 1200, 300, 40.0f },
    { 6, 1, 1, 1500, 600, 70.0f },
    { 7, 2, 2, 1800, 900, 100.0f },
    { 8, 3, 3, 2100, 600, 20.0f }
};

static int execute_schedule(int sched_id)
{
    DispatchSchedule *s = &schedules[sched_id];
    unsigned int now = (unsigned int)time(NULL);

    if (now < s->start_time || now > (s->start_time + s->duration_sec))
        return -1;  /* Outside window */

    switch (s->action) {
    case 1:  /* Dispatch */
        lf_cache[s->feeder_id].active_power = s->target_mw;
        break;
    case 2:  /* Ramp */
        lf_cache[s->feeder_id].active_power += (s->target_mw / s->duration_sec) * 10.0f;
        break;
    case 3:  /* Reserve */
        /* Hold capacity in reserve */
        break;
    case 4:  /* Curtail */
        lf_cache[s->feeder_id].active_power = s->target_mw;
        break;
    }

    return 0;
}

static int manage_all_schedules(void)
{
    int i, count = 0;

    for (i = 0; i < 8; i++) {
        if (execute_schedule(i) == 0)
            count++;
    }

    return count;
}

/* ===== DEMAND RESPONSE & LOAD CONTROL ===== */

typedef struct {
    int dr_program_id;
    int feeder_id;
    float curtailment_mw;
    int status;              /* 0=idle, 1=armed, 2=active */
    unsigned int activation_time;
} DRProgram;

static DRProgram dr_programs[4] = {
    { 1, 0, 25.0f, 0, 0 },
    { 2, 1, 15.0f, 0, 0 },
    { 3, 2, 30.0f, 0, 0 },
    { 4, 3, 10.0f, 0, 0 }
};

static int activate_dr_program(int prog_id)
{
    if (prog_id < 0 || prog_id >= 4)
        return -1;

    dr_programs[prog_id].status = 2;  /* Active */
    dr_programs[prog_id].activation_time = (unsigned int)time(NULL);

    log_alarm(ALM_LOWLEVEL + prog_id, prog_id);

    return 0;
}

static int deactivate_dr_program(int prog_id)
{
    if (prog_id < 0 || prog_id >= 4)
        return -1;

    dr_programs[prog_id].status = 0;  /* Idle */

    return 0;
}

static int apply_dr_curtailments(void)
{
    int i, total_curtailed = 0;

    for (i = 0; i < 4; i++) {
        if (dr_programs[i].status == 2) {
            lf_cache[i].active_power -= dr_programs[i].curtailment_mw;
            if (lf_cache[i].active_power < 0)
                lf_cache[i].active_power = 0;
            total_curtailed += (int)dr_programs[i].curtailment_mw;
        }
    }

    return total_curtailed;
}

/* ===== SYSTEM STABILITY & DAMPING ===== */

typedef struct {
    float frequency_deviation;     /* Hz deviation from 60Hz */
    float rate_of_change;          /* RoCoF: Hz/sec */
    int stability_margin;          /* 0=critical, 1=marginal, 2=stable */
} StabilityMetric;

static StabilityMetric stability = { 0.0f, 0.0f, 2 };

static int estimate_system_frequency(void)
{
    float total_gen = 0.0f;
    float total_load = 0.0f;
    int i;

    for (i = 0; i < 4; i++) {
        total_gen += lf_cache[i].active_power;
    }

    total_load = 300.0f;  /* Stub load */

    stability.frequency_deviation = (total_gen - total_load) * 0.1f;

    if (stability.frequency_deviation > 1.0f)
        stability.stability_margin = 0;  /* Critical */
    else if (stability.frequency_deviation > 0.3f)
        stability.stability_margin = 1;  /* Marginal */
    else
        stability.stability_margin = 2;  /* Stable */

    return (int)stability.frequency_deviation;
}

static int damping_control(void)
{
    int i, control_actions = 0;

    if (stability.stability_margin < 2) {
        for (i = 0; i < 4; i++) {
            if (lf_cache[i].active_power > 0) {
                pg_breaker_cmd(i, 0);  /* Trip to shed */
                control_actions++;
                if (stability.stability_margin > 0)
                    break;  /* One trip sufficient if marginal */
            }
        }
    }

    return control_actions;
}

/* ===== COMMAND QUEUING & SERIALIZATION ===== */

typedef struct {
    int queue_index;
    int total_in_queue;
    DispatchCmd commands[20];
} CommandQueue;

static CommandQueue cmd_queue = { 0, 0, {} };

static int enqueue_dispatch_cmd(DispatchCmd cmd)
{
    if (cmd_queue.total_in_queue >= 20)
        return -1;

    cmd_queue.commands[cmd_queue.total_in_queue++] = cmd;
    return cmd_queue.total_in_queue;
}

static int dequeue_dispatch_cmd(DispatchCmd *out)
{
    if (cmd_queue.total_in_queue == 0)
        return -1;

    *out = cmd_queue.commands[cmd_queue.queue_index];

    cmd_queue.queue_index++;
    if (cmd_queue.queue_index >= cmd_queue.total_in_queue) {
        cmd_queue.queue_index = 0;
        cmd_queue.total_in_queue = 0;
    }

    return 0;
}

static int process_pending_commands(void)
{
    DispatchCmd cmd;
    int count = 0;

    while (dequeue_dispatch_cmd(&cmd) == 0) {
        switch (cmd.cmd_type) {
        case 1:  /* Breaker trip */
            pg_breaker_cmd(cmd.feeder_id, 0);
            break;
        case 2:  /* Breaker close */
            pg_breaker_cmd(cmd.feeder_id, 1);
            break;
        case 3:  /* Tap change */
            sequential_tap_control(cmd.feeder_id, cmd.value > 0 ? 1 : -1, 1);
            break;
        }
        count++;
    }

    return count;
}

/* ===== MEASUREMENT & ESTIMATION ===== */

typedef struct {
    int measurement_id;
    int quality;             /* 0-100% */
    float value;
    unsigned int timestamp;
    int is_bad;
} Measurement;

static Measurement measurements[16];

static int update_measurement(int meas_id, float value, int quality)
{
    if (meas_id < 0 || meas_id >= 16)
        return -1;

    measurements[meas_id].measurement_id = meas_id;
    measurements[meas_id].value = value;
    measurements[meas_id].quality = quality;
    measurements[meas_id].timestamp = (unsigned int)time(NULL);
    measurements[meas_id].is_bad = (quality < 50) ? 1 : 0;

    return 0;
}

static int bad_data_detection(void)
{
    int i, bad_count = 0;

    for (i = 0; i < 16; i++) {
        if (measurements[i].is_bad)
            bad_count++;
    }

    return bad_count;
}

static int state_estimation(void)
{
    /* Filter bad measurements & interpolate state */
    int i, good_measures = 0;
    float sum = 0.0f;

    for (i = 0; i < 4; i++) {
        if (!measurements[i].is_bad) {
            sum += measurements[i].value;
            good_measures++;
        }
    }

    if (good_measures > 0)
        return (int)(sum / good_measures);

    return -1;
}

/* ===== END OF EXTENDED DISPATCH MODULE ===== */


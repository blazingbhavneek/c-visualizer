/*
 * ww_control.c - waterworks plant control engine.
 * Scan cycle, point reading, historian integration, and control algorithms.
 */

#include "ww_app.h"

/* ============================================================
 * GROUND TRUTH
 *
 * path      : main -> scf_evt_register(EVT_SCAN_CYCLE) -> ww_on_scan
 *             -> scf_evt_post(EVT_SCAN_CYCLE, ...) -> ww_scan_cycle(PT_FLOW_RATE)
 *             -> ww_read_point(PT_FLOW_RATE) -> scf_tag_read(&ctx, PT_FLOW_RATE, buf)
 * api       : scf_tag_read
 * type      : READF
 * launch_via: EVENT
 * arg2      : PT_FLOW_RATE = 0x1004
 * call_num  : 3001 (EVT_SCAN_CYCLE)
 *
 * path      : main -> scf_evt_register(EVT_SCAN_CYCLE) -> ww_on_scan
 *             -> ww_scan_cycle -> ww_read_point -> scf_tag_write(&ctx, PT_SETPOINT, 100)
 * api       : scf_tag_write
 * type      : WRITEF
 * launch_via: EVENT
 * arg2      : PT_SETPOINT = 0x1007
 * arg3      : 100
 * call_num  : 3001
 *
 * path      : main -> scf_evt_register(EVT_SCAN_CYCLE) -> ww_on_scan
 *             -> TAG_SNAPSHOT(pid, buf) [macro-expanded]
 *             -> scf_tag_read(&g_snap_ctx, pid, buf)
 * api       : scf_tag_read
 * type      : READF
 * launch_via: EVENT
 * call_num  : 3001
 *
 * path      : main -> scf_evt_register(EVT_SCAN_CYCLE) -> ww_on_scan
 *             -> scf_evt_post(EVT_SCAN_CYCLE, ...)
 * api       : scf_evt_post
 * type      : EVENT
 * launch_via: EVENT (recursive)
 * arg1      : EVT_SCAN_CYCLE = 3001
 * call_num  : 3001
 *
 * path      : main -> ww_init -> ww_get_ctx(PT_TANK_LEVEL)
 *             -> scf_tag_open(&ctx, PT_TANK_LEVEL, SCF_READ_LOCK) [marked [CONSIDER THIS CALL]]
 * api       : scf_tag_open
 * type      : OPENF
 * launch_via: MAIN (or startup)
 * arg2      : PT_TANK_LEVEL = 0x1003
 *
 * path      : main -> scf_task_fork(TASK_HIST) -> ww_hist_task
 *             -> scf_evt_post(EVT_HIST_FLUSH, 0)
 * api       : scf_evt_post
 * type      : EVENT
 * launch_via: FORK
 * arg1      : EVT_HIST_FLUSH = 3005
 * call_num  : 3005
 *
 * path      : main -> scf_task_fork(TASK_HIST) -> ww_hist_task
 *             -> ww_flush_history(ARC_TREND)
 *             -> HIST_TREND(&rec) [macro-expanded]
 *             -> scf_hist_save(ARC_TREND, &rec)
 * api       : scf_hist_save
 * type      : SAVEF
 * launch_via: FORK
 * arg1      : ARC_TREND = 200
 * call_num  : 3005
 *
 * path      : main -> scf_task_fork(TASK_HIST) -> ww_hist_task
 *             -> ww_flush_history(ARC_TREND)
 *             -> scf_hist_save(archive_id, &rec) [marked [CONSIDER THIS CALL]]
 * api       : scf_hist_save
 * type      : SAVEF
 * launch_via: FORK
 * call_num  : 3005
 *
 * path      : main -> scf_task_fork(TASK_HIST) -> ww_hist_task
 *             -> ww_flush_history -> scf_cmdq_save(Q_CMD)
 * api       : scf_cmdq_save
 * type      : SAVEQ
 * launch_via: FORK
 * arg1      : Q_CMD = 12
 * call_num  : 3005
 *
 * ============================================================ */

/* ============================================================
 * Ring buffer for moving average (temperature smoothing, etc.)
 * ============================================================ */
#define RINGBUF_SIZE  32

typedef struct {
    int samples[RINGBUF_SIZE];
    int head;
    int count;
} RingBuf;

/* ============================================================
 * PID controller state for pump/valve feedback loops
 * ============================================================ */
typedef struct {
    int setpoint;
    int last_error;
    int integral_sum;
    int proportional_gain;     /* K_p * 1000 */
    int integral_gain;         /* K_i * 1000 */
    int derivative_gain;       /* K_d * 1000 */
    int deadband;
    int output_limit_high;
    int output_limit_low;
} PIDCtrl;

/* ============================================================
 * Sensor validation state
 * ============================================================ */
typedef struct {
    int point_id;
    int last_valid;
    int fail_count;
    int fail_threshold;
    int min_range;
    int max_range;
} SensorState;

/* ============================================================
 * Pump sequencing state machine (for duty cycling)
 * ============================================================ */
typedef struct {
    int pump_id;
    int state;           /* 0=idle, 1=starting, 2=running, 3=stopping */
    int runtime_seconds;
    int idle_seconds;
    int cycle_count;
    int target_speed;
} PumpSeq;

/* ============================================================
 * Valve position ramping (smooth setpoint changes)
 * ============================================================ */
typedef struct {
    int current_pos;
    int target_pos;
    int ramp_rate;       /* units/sec */
    int last_update_ms;
} ValveRamp;

/* ============================================================
 * Static globals for control state
 * ============================================================ */

static PIDCtrl g_pump_pid = {
    .setpoint = 50,
    .proportional_gain = 250,
    .integral_gain = 50,
    .derivative_gain = 100,
    .deadband = 2,
    .output_limit_high = 100,
    .output_limit_low = 0
};

static PIDCtrl g_flow_pid = {
    .setpoint = 75,
    .proportional_gain = 180,
    .integral_gain = 40,
    .derivative_gain = 80,
    .deadband = 3,
    .output_limit_high = 95,
    .output_limit_low = 5
};

static RingBuf g_temp_history = {0};
static RingBuf g_pressure_history = {0};

static SensorState g_tank_sensor = {
    .point_id = PT_TANK_LEVEL,
    .fail_threshold = 5,
    .min_range = 0,
    .max_range = 100
};

static SensorState g_flow_sensor = {
    .point_id = PT_FLOW_RATE,
    .fail_threshold = 3,
    .min_range = 0,
    .max_range = 150
};

static PumpSeq g_pump_main = {
    .pump_id = 1,
    .target_speed = 75
};

static PumpSeq g_pump_standby = {
    .pump_id = 2,
    .target_speed = 0
};

static ValveRamp g_setpoint_ramp = {
    .current_pos = 50,
    .target_pos = 50,
    .ramp_rate = 5
};

static int g_scan_count = 0;
static int g_alarm_posted = 0;
static TagCtx g_global_ctx = {0};

/* ============================================================
 * Helper: Ring buffer add/average
 * ============================================================ */

static void ringbuf_push(RingBuf *rb, int sample) {
    rb->samples[rb->head] = sample;
    rb->head = (rb->head + 1) % RINGBUF_SIZE;
    if (rb->count < RINGBUF_SIZE) {
        rb->count++;
    }
}

static int ringbuf_average(RingBuf *rb) {
    int i, sum = 0;
    if (rb->count == 0) return 0;
    for (i = 0; i < rb->count; i++) {
        sum += rb->samples[i];
    }
    return sum / rb->count;
}

/* ============================================================
 * Helper: Clamp value to range
 * ============================================================ */

static int clamp_value(int val, int min_v, int max_v) {
    if (val < min_v) return min_v;
    if (val > max_v) return max_v;
    return val;
}

/* ============================================================
 * Helper: Engineering unit conversion (raw -> normalized)
 * ============================================================ */

static int raw_to_normalized(int raw_val, int raw_min, int raw_max) {
    int range = raw_max - raw_min;
    if (range == 0) return 0;
    int normalized = ((raw_val - raw_min) * 100) / range;
    return clamp_value(normalized, 0, 100);
}

static int normalized_to_raw(int norm_val, int raw_min, int raw_max) {
    int range = raw_max - raw_min;
    int raw = raw_min + (norm_val * range) / 100;
    return clamp_value(raw, raw_min, raw_max);
}

/* ============================================================
 * Helper: PID loop calculation
 * ============================================================ */

static int pid_update(PIDCtrl *pid, int measured_value, int dt_ms) {
    int error = pid->setpoint - measured_value;
    int proportional = (error * pid->proportional_gain) / 1000;

    pid->integral_sum += error * dt_ms;
    if (pid->integral_sum > 100000) pid->integral_sum = 100000;
    if (pid->integral_sum < -100000) pid->integral_sum = -100000;
    int integral = (pid->integral_sum * pid->integral_gain) / 1000;

    int derivative = ((error - pid->last_error) * pid->derivative_gain) / 1000;
    pid->last_error = error;

    int output = proportional + integral + derivative;

    if (output < -pid->deadband && output > -pid->deadband) {
        output = 0;
    }

    output = clamp_value(output, pid->output_limit_low, pid->output_limit_high);
    return output;
}

/* ============================================================
 * Helper: Sensor validation with hysteresis
 * ============================================================ */

static int validate_sensor(SensorState *sensor, int raw_value) {
    if (raw_value < sensor->min_range || raw_value > sensor->max_range) {
        sensor->fail_count++;
        if (sensor->fail_count >= sensor->fail_threshold) {
            return -1;  /* Invalid */
        }
        return sensor->last_valid;  /* Stale but acceptable */
    }

    sensor->fail_count = 0;
    sensor->last_valid = raw_value;
    return raw_value;
}

/* ============================================================
 * Helper: Deadband filter (suppress jitter)
 * ============================================================ */

static int deadband_filter(int current, int last, int threshold) {
    if (current > last + threshold || current < last - threshold) {
        return current;
    }
    return last;
}

/* ============================================================
 * Helper: Moving average with min/max tracking
 * ============================================================ */

typedef struct {
    int min_val;
    int max_val;
    int sum;
    int count;
} MinMaxTracker;

static void mmtrack_add(MinMaxTracker *mmt, int val) {
    if (mmt->count == 0) {
        mmt->min_val = val;
        mmt->max_val = val;
    } else {
        if (val < mmt->min_val) mmt->min_val = val;
        if (val > mmt->max_val) mmt->max_val = val;
    }
    mmt->sum += val;
    mmt->count++;
}

static int mmtrack_avg(MinMaxTracker *mmt) {
    if (mmt->count == 0) return 0;
    return mmt->sum / mmt->count;
}

/* ============================================================
 * Helper: Pump sequencing logic (duty cycling)
 * ============================================================ */

static void pump_update_state(PumpSeq *pump, int elapsed_ms) {
    if (pump->state == 2) {  /* running */
        pump->runtime_seconds += elapsed_ms / 1000;
        if (pump->runtime_seconds > 3600) {  /* 1-hour cutoff */
            pump->state = 3;  /* stopping */
        }
    } else if (pump->state == 3) {  /* stopping */
        pump->idle_seconds += elapsed_ms / 1000;
        if (pump->idle_seconds > 600) {  /* 10-minute rest */
            pump->idle_seconds = 0;
            pump->runtime_seconds = 0;
            pump->cycle_count++;
            pump->state = 1;  /* restart */
        }
    } else if (pump->state == 0 || pump->state == 1) {  /* idle or starting */
        if (pump->target_speed > 10) {
            pump->state = 1;  /* go to starting */
        }
    }
}

static int pump_get_speed(PumpSeq *pump) {
    if (pump->state == 2) return pump->target_speed;
    if (pump->state == 1) return (pump->target_speed * 20) / 100;  /* ramp-up */
    return 0;
}

/* ============================================================
 * Helper: Valve position ramping (smooth transitions)
 * ============================================================ */

static void valve_ramp_update(ValveRamp *vr, int elapsed_ms) {
    int delta = vr->target_pos - vr->current_pos;
    if (delta == 0) return;

    int ramp_amount = (vr->ramp_rate * elapsed_ms) / 1000;
    if (ramp_amount == 0 && delta != 0) ramp_amount = 1;

    if (delta > 0) {
        vr->current_pos += (ramp_amount < delta) ? ramp_amount : delta;
    } else {
        vr->current_pos -= (ramp_amount < -delta) ? ramp_amount : -delta;
    }
    vr->last_update_ms = elapsed_ms;
}

/* ============================================================
 * Helper: Setpoint calculation (cascade or override logic)
 * ============================================================ */

static int calculate_setpoint(int tank_level, int flow_demand) {
    int sp = 50;  /* base */

    /* Adjust based on tank level */
    if (tank_level < 30) {
        sp = 75;  /* fill faster */
    } else if (tank_level > 80) {
        sp = 25;  /* fill slower */
    }

    /* Adjust based on demand */
    if (flow_demand > 90) {
        sp = clamp_value(sp + 15, 0, 100);
    } else if (flow_demand < 20) {
        sp = clamp_value(sp - 10, 0, 100);
    }

    return sp;
}

/* ============================================================
 * Helper: Diagnostics table (runtime/fault tracking)
 * ============================================================ */

typedef struct {
    int total_cycles;
    int total_errors;
    int last_error_code;
    int last_error_time;
    int sensor_failures;
    int overtemp_count;
} DiagTable;

static DiagTable g_diag = {0};

static void diag_log_error(int error_code, int timestamp) {
    g_diag.total_errors++;
    g_diag.last_error_code = error_code;
    g_diag.last_error_time = timestamp;
}

/* ============================================================
 * Helper: Pressure/temperature threshold checking
 * ============================================================ */

static int check_overpressure(int pressure) {
    if (pressure > 95) return 1;
    return 0;
}

static int check_overtemp(int temperature) {
    if (temperature > 85) return 1;
    return 0;
}

/* ============================================================
 * ww_get_ctx: Open tag context (pointer-based selection)
 *
 * The tracer marks the intended scf_tag_open call with
 * [CONSIDER THIS CALL] and resolves arg2 (point_id).
 * ============================================================ */

void *ww_get_ctx(int fno) {
    static TagCtx ctx_tank;
    static TagCtx ctx_flow;
    static TagCtx ctx_temp;

    /* Try three different contexts */
    if (fno == PT_TANK_LEVEL) {
        scf_tag_open(&ctx_tank, PT_PUMP_SPEED, SCF_READ_LOCK);
        scf_tag_open(&ctx_flow, PT_MOTOR_TEMP, SCF_READ_LOCK);
        scf_tag_open(&ctx_tank, fno, SCF_READ_LOCK);  /*CONSIDER THIS CALL*/
        return &ctx_tank;
    } else if (fno == PT_FLOW_RATE) {
        scf_tag_open(&ctx_flow, fno, SCF_READ_LOCK);
        return &ctx_flow;
    } else {
        scf_tag_open(&ctx_temp, fno, SCF_READ_LOCK);
        return &ctx_temp;
    }
}

/* ============================================================
 * ww_read_point: Single point read with validation
 *
 * Called from ww_scan_cycle for each point of interest.
 * Performs validation, sensor error checking, and clamping.
 * ============================================================ */

int ww_read_point(int pid) {
    TagCtx local_ctx = {0};
    int raw_buf = 0;
    int validated = 0;

    /* Read from tag storage */
    scf_tag_read(&local_ctx, pid, &raw_buf);

    /* Validate based on point type */
    if (pid == PT_TANK_LEVEL) {
        validated = validate_sensor(&g_tank_sensor, raw_buf);
        if (validated < 0) {
            diag_log_error(0x0001, 0);
            return 50;  /* failsafe default */
        }
    } else if (pid == PT_FLOW_RATE) {
        validated = validate_sensor(&g_flow_sensor, raw_buf);
        if (validated < 0) {
            g_diag.sensor_failures++;
            return 0;
        }
    } else if (pid == PT_MOTOR_TEMP) {
        validated = clamp_value(raw_buf, 0, 120);
        ringbuf_push(&g_temp_history, validated);
    } else if (pid == PT_PRESSURE) {
        validated = clamp_value(raw_buf, 0, 120);
        ringbuf_push(&g_pressure_history, validated);
    } else {
        validated = raw_buf;
    }

    return validated;
}

/* ============================================================
 * ww_scan_cycle: Main scan loop for a base point ID
 *
 * Reads a cascade of related points, applies control logic,
 * posts alarms on breach, and updates setpoints.
 * ============================================================ */

int ww_scan_cycle(int base_pid) {
    int tank_level = 0;
    int flow_rate = 0;
    int motor_temp = 0;
    int pressure = 0;
    int new_setpoint = 0;
    TagCtx ctx = {0};
    int snapshot_buf = 0;

    /* Read the base point (e.g., PT_FLOW_RATE) */
    flow_rate = ww_read_point(base_pid);

    /* Read companion points */
    tank_level = ww_read_point(PT_TANK_LEVEL);
    motor_temp = ww_read_point(PT_MOTOR_TEMP);
    pressure = ww_read_point(PT_PRESSURE);

    /* Snapshot reading for archive */
    TAG_SNAPSHOT(base_pid, &snapshot_buf);

    /* Calculate new setpoint based on state */
    new_setpoint = calculate_setpoint(tank_level, flow_rate);
    g_setpoint_ramp.target_pos = new_setpoint;
    valve_ramp_update(&g_setpoint_ramp, 100);

    /* Write updated setpoint to storage */
    scf_tag_write(&ctx, PT_SETPOINT, g_setpoint_ramp.current_pos);

    /* PID updates for pump control */
    int pump_output = pid_update(&g_pump_pid, tank_level, 100);
    int flow_output = pid_update(&g_flow_pid, flow_rate, 100);

    /* Update pump sequencing */
    pump_update_state(&g_pump_main, 100);
    g_pump_main.target_speed = clamp_value(pump_output, 0, 100);

    /* Check alarm thresholds */
    if (check_overtemp(motor_temp)) {
        g_diag.overtemp_count++;
        if (g_alarm_posted == 0) {
            ww_alarm_check(PT_MOTOR_TEMP, motor_temp);
            g_alarm_posted = 1;
        }
    } else {
        g_alarm_posted = 0;
    }

    if (check_overpressure(pressure)) {
        ww_alarm_check(PT_PRESSURE, pressure);
    }

    /* Increment cycle counter */
    g_scan_count++;
    if (g_scan_count > 999999) g_scan_count = 0;

    return flow_rate;
}

/* ============================================================
 * ww_on_scan: Event handler for EVT_SCAN_CYCLE
 *
 * Registered callback invoked by framework.
 * Posts recursive scan events and dispatches control cycle.
 * ============================================================ */

void ww_on_scan(int evt, void *data) {
    int result = 0;

    /* Post the scan cycle event (call_number=3001) */
    scf_evt_post(EVT_SCAN_CYCLE, 0);

    /* Execute main control scan with base PID */
    result = ww_scan_cycle(PT_FLOW_RATE);

    /* Secondary scan for pump speed feedback */
    ww_scan_cycle(PT_PUMP_SPEED);

    /* Tertiary scan for valve position */
    ww_scan_cycle(PT_VALVE_POS);

    (void)result;  /* suppress unused */
    (void)evt;
    (void)data;
}

/* ============================================================
 * ww_flush_history: Archive accumulated historical records
 *
 * Pops records from snapshot buffer and saves to archive.
 * Uses both macro-expanded and direct scf_hist_save calls.
 * ============================================================ */

int ww_flush_history(int archive_id) {
    HistRec record = {0};
    int i = 0;
    int count = 0;
    int avg_temp = 0;
    int avg_pressure = 0;

    /* Prepare aggregated record */
    record.archive_id = archive_id;
    record.stamp = g_scan_count;
    record.value = ringbuf_average(&g_temp_history);

    /* Use HIST_TREND macro (injects ARC_TREND) */
    HIST_TREND(&record);

    /* Reset temp history after archiving */
    if (archive_id == ARC_TREND) {
        g_temp_history.count = 0;
        g_temp_history.head = 0;
    }

    /* Multiple saves to different archives */
    avg_temp = ringbuf_average(&g_temp_history);
    record.value = avg_temp;
    scf_hist_save(ARC_EVENTLOG, &record);  /* alternate archive */

    /* Direct save with CONSIDER marker */
    record.archive_id = archive_id;
    scf_hist_save(archive_id, &record);  /*CONSIDER THIS CALL*/
    count++;

    /* Pressure trend */
    avg_pressure = ringbuf_average(&g_pressure_history);
    record.value = avg_pressure;
    scf_hist_save(archive_id, &record);
    count++;

    /* Pump diagnostics */
    record.value = g_pump_main.cycle_count;
    scf_hist_save(ARC_AUDIT, &record);

    /* Save command queue state */
    scf_cmdq_save(Q_CMD);

    return count;
}

/* ============================================================
 * ww_hist_task: Background historian task (TaskEntry for TASK_HIST)
 *
 * Spawned via scf_task_fork in main.
 * Periodically flushes historical data and posts events.
 * ============================================================ */

void ww_hist_task(int task_id) {
    int iter = 0;
    int flush_interval = 100;  /* every N cycles */

    while (iter < 1000) {  /* bounded loop for testing */
        iter++;

        if ((iter % flush_interval) == 0) {
            /* Post historian flush event (call_number=3005) */
            scf_evt_post(EVT_HIST_FLUSH, 0);

            /* Flush accumulated trends to archive */
            ww_flush_history(ARC_TREND);

            /* Optionally flush audit trail */
            if ((iter % (flush_interval * 10)) == 0) {
                ww_flush_history(ARC_AUDIT);
            }
        }

        /* Simulate background work */
        int i;
        for (i = 0; i < 1000; i++) {
            /* spin: represents I/O wait or other blocking */
        }
    }

    (void)task_id;
}

/* ============================================================
 * Auxiliary: Setpoint ramping helper (smooth transitions)
 * ============================================================ */

static int ramp_setpoint(int current, int target, int rate) {
    if (current < target) {
        int delta = target - current;
        int step = (rate * 10) / 100;  /* rate is in units/sec */
        if (step == 0) step = 1;
        return current + ((step < delta) ? step : delta);
    } else if (current > target) {
        int delta = current - target;
        int step = (rate * 10) / 100;
        if (step == 0) step = 1;
        return current - ((step < delta) ? step : delta);
    }
    return current;
}

/* ============================================================
 * Auxiliary: Pressure compensation logic
 * ============================================================ */

static int pressure_compensate(int base_output, int measured_pressure) {
    int target_pressure = 50;
    int error = target_pressure - measured_pressure;
    int comp = (error * 10) / 100;  /* 0.1x gain */
    return clamp_value(base_output + comp, 0, 100);
}

/* ============================================================
 * Auxiliary: Temperature cutout (safety shutdown)
 * ============================================================ */

static int apply_thermal_shutdown(int output, int temperature) {
    if (temperature > 95) {
        return 0;  /* hard cutout */
    } else if (temperature > 85) {
        return (output * 70) / 100;  /* reduce to 70% */
    } else if (temperature > 75) {
        return (output * 85) / 100;  /* reduce to 85% */
    }
    return output;
}

/* ============================================================
 * Auxiliary: Flow rate deadband (suppress oscillation)
 * ============================================================ */

static int apply_flow_deadband(int measured, int last_measured) {
    static int flow_history = 0;
    int filtered = deadband_filter(measured, flow_history, 5);
    flow_history = filtered;
    return filtered;
}

/* ============================================================
 * Auxiliary: Valve position limiting (mechanical constraints)
 * ============================================================ */

static int apply_valve_limits(int cmd_pos) {
    /* Physical limits: 5% to 95% */
    if (cmd_pos < 5) return 5;
    if (cmd_pos > 95) return 95;
    return cmd_pos;
}

/* ============================================================
 * Auxiliary: Pressure cascade control
 * ============================================================ */

static int cascade_pressure_to_flow(int setpoint, int feedback_pressure) {
    int comp = (feedback_pressure - 50) / 10;  /* offset comp */
    int adjusted = setpoint - comp;
    return clamp_value(adjusted, 0, 100);
}

/* ============================================================
 * Auxiliary: Multi-loop coordination
 * ============================================================ */

static int coordinate_loops(int tank_setpoint, int flow_feedback,
                           int pressure_feedback, int temp_feedback) {
    int result = tank_setpoint;

    /* Don't push flow if pressure is high */
    if (pressure_feedback > 80) {
        result = (result * 80) / 100;
    }

    /* Boost flow if temp is low */
    if (temp_feedback < 40) {
        result = clamp_value(result + 10, 0, 100);
    }

    return result;
}

/* ============================================================
 * Auxiliary: Statistics accumulator for diagnostics
 * ============================================================ */

typedef struct {
    int scan_count;
    int error_count;
    int alarm_count;
    int flush_count;
} RunStats;

static RunStats g_run_stats = {0};

static void record_stat_scan(void) {
    g_run_stats.scan_count++;
}

static void record_stat_error(void) {
    g_run_stats.error_count++;
}

static void record_stat_alarm(void) {
    g_run_stats.alarm_count++;
}

static void record_stat_flush(void) {
    g_run_stats.flush_count++;
}

/* ============================================================
 * Auxiliary: Hysteresis filter for on/off controls
 * ============================================================ */

typedef struct {
    int state;
    int threshold_high;
    int threshold_low;
    int hysteresis;
} HysteresisFilter;

static void hyst_update(HysteresisFilter *hf, int input) {
    if (hf->state == 0 && input > hf->threshold_high) {
        hf->state = 1;
    } else if (hf->state == 1 && input < hf->threshold_low) {
        hf->state = 0;
    }
}

/* ============================================================
 * Auxiliary: Rate limiter (slew rate control)
 * ============================================================ */

static int rate_limit(int target, int current, int max_rate) {
    int delta = target - current;
    if (delta > max_rate) delta = max_rate;
    if (delta < -max_rate) delta = -max_rate;
    return current + delta;
}

/* ============================================================
 * Auxiliary: PI controller (simpler variant)
 * ============================================================ */

static int pi_update(int setpoint, int feedback, int kp, int ki) {
    static int integral = 0;
    int error = setpoint - feedback;
    int p = (error * kp) / 100;
    integral += error;
    if (integral > 10000) integral = 10000;
    if (integral < -10000) integral = -10000;
    int i = (integral * ki) / 100;
    return clamp_value(p + i, 0, 100);
}

/* ============================================================
 * Auxiliary: Lead-lag filter (frequency response shaping)
 * ============================================================ */

typedef struct {
    int x_prev;
    int y_prev;
    int alpha;  /* 0-100 */
} LeadLagFilter;

static int leadlag_filter(LeadLagFilter *llf, int input) {
    int output = ((input * llf->alpha) + (llf->y_prev * (100 - llf->alpha))) / 100;
    llf->x_prev = input;
    llf->y_prev = output;
    return output;
}

/* ============================================================
 * Auxiliary: State enumeration for complex machines
 * ============================================================ */

typedef enum {
    STATE_IDLE = 0,
    STATE_STARTUP = 1,
    STATE_NORMAL = 2,
    STATE_RAMP_DOWN = 3,
    STATE_FAULT = 4,
    STATE_MAINTENANCE = 5
} SystemState;

static SystemState g_system_state = STATE_IDLE;

static void update_system_state(int tank_level, int temp, int pressure) {
    switch (g_system_state) {
        case STATE_IDLE:
            if (tank_level < 40 && temp < 70 && pressure < 40) {
                g_system_state = STATE_STARTUP;
            }
            break;
        case STATE_STARTUP:
            if (tank_level > 50) {
                g_system_state = STATE_NORMAL;
            }
            break;
        case STATE_NORMAL:
            if (temp > 90 || pressure > 95) {
                g_system_state = STATE_RAMP_DOWN;
            }
            break;
        case STATE_RAMP_DOWN:
            if (temp < 75 && pressure < 70) {
                g_system_state = STATE_IDLE;
            }
            break;
        case STATE_FAULT:
            /* manual reset required */
            break;
        case STATE_MAINTENANCE:
            /* manual transition */
            break;
    }
}

/* ============================================================
 * Auxiliary: Adaptive gain scheduling
 * ============================================================ */

static void adapt_gains(PIDCtrl *pid, int operating_point) {
    /* Lower gains at low operating points for stability */
    if (operating_point < 30) {
        pid->proportional_gain = 150;
        pid->integral_gain = 30;
        pid->derivative_gain = 50;
    } else if (operating_point > 70) {
        pid->proportional_gain = 300;
        pid->integral_gain = 60;
        pid->derivative_gain = 120;
    } else {
        pid->proportional_gain = 250;
        pid->integral_gain = 50;
        pid->derivative_gain = 100;
    }
}

/* ============================================================
 * Auxiliary: Cross-coupled control (multivariable)
 * ============================================================ */

static int crosscoup_adjust(int primary_output,
                           int primary_feedback,
                           int coupling_feedback,
                           int coupling_gain) {
    int delta = coupling_feedback - 50;
    int coup_effect = (delta * coupling_gain) / 100;
    return clamp_value(primary_output + coup_effect, 0, 100);
}

/* ============================================================
 * Auxiliary: Anti-windup for integrator saturation
 * ============================================================ */

static void antiwindup_check(PIDCtrl *pid, int output) {
    if (output >= pid->output_limit_high) {
        if (pid->integral_sum > 0) {
            pid->integral_sum = (pid->integral_sum * 80) / 100;
        }
    } else if (output <= pid->output_limit_low) {
        if (pid->integral_sum < 0) {
            pid->integral_sum = (pid->integral_sum * 80) / 100;
        }
    }
}

/* ============================================================
 * Auxiliary: Output shaping (dither / resolution)
 * ============================================================ */

static int shape_output(int raw_output, int dither) {
    /* Quantize to discrete levels if needed */
    int quantized = (raw_output / dither) * dither;
    return quantized;
}

/* ============================================================
 * Auxiliary: Fault detection and recovery
 * ============================================================ */

static int detect_fault(int feedback, int last_feedback) {
    int delta = feedback - last_feedback;
    if (delta > 50 || delta < -50) {
        return 1;  /* sudden jump => sensor fault */
    }
    return 0;
}

static void recover_from_fault(void) {
    g_pump_main.state = 0;
    g_pump_standby.state = 0;
    g_setpoint_ramp.target_pos = 50;
    g_system_state = STATE_IDLE;
}

/* ============================================================
 * Auxiliary: Load profile estimation
 * ============================================================ */

static int estimate_load(int flow_rate, int pressure) {
    int load = (flow_rate * pressure) / 100;
    return clamp_value(load, 0, 100);
}

/* ============================================================
 * Auxiliary: Efficiency calculation
 * ============================================================ */

static int calc_efficiency(int motor_speed, int flow_rate) {
    if (motor_speed == 0) return 0;
    int eff = (flow_rate * 100) / motor_speed;
    return clamp_value(eff, 0, 100);
}

/* ============================================================
 * Auxiliary: Cascade loop for inter-stage pressure control
 * ============================================================ */

typedef struct {
    int primary_output;
    int secondary_feedback;
    int cascade_setpoint;
    int coupling_ratio;
} CascadeCtrl;

static int cascade_update(CascadeCtrl *casc, int primary_error) {
    int adjusted = (primary_error * casc->coupling_ratio) / 100;
    casc->cascade_setpoint += adjusted;
    if (casc->cascade_setpoint < 0) casc->cascade_setpoint = 0;
    if (casc->cascade_setpoint > 100) casc->cascade_setpoint = 100;
    return casc->cascade_setpoint;
}

/* ============================================================
 * Auxiliary: Flow compensation under pressure variation
 * ============================================================ */

static int compensate_flow_for_pressure(int base_flow, int current_pressure,
                                       int reference_pressure) {
    if (reference_pressure == 0) return base_flow;
    int ratio = (current_pressure * 100) / reference_pressure;
    if (ratio == 0) return base_flow;
    int compensated = (base_flow * reference_pressure) / (ratio + 1);
    return clamp_value(compensated, 0, 100);
}

/* ============================================================
 * Auxiliary: Soft-start ramp for pump motor (reduce inrush)
 * ============================================================ */

typedef struct {
    int target_speed;
    int current_speed;
    int ramp_step;
    int step_count;
    int step_max;
} SoftStart;

static void softstart_update(SoftStart *ss) {
    if (ss->current_speed < ss->target_speed) {
        if (ss->step_count < ss->step_max) {
            ss->step_count++;
        } else {
            ss->current_speed += ss->ramp_step;
            if (ss->current_speed > ss->target_speed) {
                ss->current_speed = ss->target_speed;
            }
            ss->step_count = 0;
        }
    } else if (ss->current_speed > ss->target_speed) {
        ss->current_speed -= ss->ramp_step;
        if (ss->current_speed < ss->target_speed) {
            ss->current_speed = ss->target_speed;
        }
    }
}

/* ============================================================
 * Auxiliary: Backpressure regulator logic (pilot control)
 * ============================================================ */

static int backpressure_regulator(int outlet_pressure, int pilot_feedback) {
    static int vent_pos = 50;
    int error = 60 - outlet_pressure;  /* target 60 psi */

    if (error > 5) {
        vent_pos = clamp_value(vent_pos + 2, 0, 100);
    } else if (error < -5) {
        vent_pos = clamp_value(vent_pos - 2, 0, 100);
    }

    return vent_pos;
}

/* ============================================================
 * Auxiliary: Dual-pump load sharing (redundancy logic)
 * ============================================================ */

typedef struct {
    int pump1_speed;
    int pump2_speed;
    int pump1_load;
    int pump2_load;
    int load_imbalance;
} DualPumpShare;

static void dual_pump_balance(DualPumpShare *dps) {
    dps->load_imbalance = dps->pump1_load - dps->pump2_load;

    if (dps->load_imbalance > 10) {
        dps->pump1_speed = clamp_value(dps->pump1_speed - 2, 0, 100);
        dps->pump2_speed = clamp_value(dps->pump2_speed + 2, 0, 100);
    } else if (dps->load_imbalance < -10) {
        dps->pump1_speed = clamp_value(dps->pump1_speed + 2, 0, 100);
        dps->pump2_speed = clamp_value(dps->pump2_speed - 2, 0, 100);
    }
}

/* ============================================================
 * Auxiliary: Surge tank level trim controller
 * ============================================================ */

static int surge_tank_trim(int tank_level, int flow_in, int flow_out) {
    static int trim_valve = 50;
    int delta = flow_in - flow_out;

    if (tank_level > 75 && delta > 0) {
        trim_valve = clamp_value(trim_valve + 3, 0, 100);
    } else if (tank_level < 30 && delta < 0) {
        trim_valve = clamp_value(trim_valve - 3, 0, 100);
    }

    return trim_valve;
}

/* ============================================================
 * Auxiliary: Fouling detection via pressure drop across filter
 * ============================================================ */

static int detect_filter_fouling(int inlet_pressure, int outlet_pressure,
                                 int last_differential) {
    int differential = inlet_pressure - outlet_pressure;
    int rate_of_change = differential - last_differential;

    if (differential > 70) {
        return 1;  /* fouling detected - high differential */
    } else if (rate_of_change > 20) {
        return 1;  /* rapid rise = fouling in progress */
    }
    return 0;
}

/* ============================================================
 * Auxiliary: Automatic backflush trigger (with time delay)
 * ============================================================ */

typedef struct {
    int backflush_enabled;
    int backflush_timer;
    int backflush_threshold_diff;
    int backflush_duration_sec;
} BackflushCtrl;

static void backflush_logic(BackflushCtrl *bfc, int current_diff) {
    if (current_diff > bfc->backflush_threshold_diff && !bfc->backflush_enabled) {
        bfc->backflush_enabled = 1;
        bfc->backflush_timer = bfc->backflush_duration_sec;
    }

    if (bfc->backflush_enabled) {
        bfc->backflush_timer--;
        if (bfc->backflush_timer <= 0) {
            bfc->backflush_enabled = 0;
        }
    }
}

/* ============================================================
 * Auxiliary: Inline static mixer velocity/shear control
 * ============================================================ */

static int mixer_velocity_control(int setpoint_concentration, int actual_conc,
                                  int base_flow) {
    int error = setpoint_concentration - actual_conc;
    int velocity_adj = (error * 15) / 100;
    int flow_adj = base_flow + velocity_adj;
    return clamp_value(flow_adj, 0, 100);
}

/* ============================================================
 * Auxiliary: Chemical injection pump modulation (metering)
 * ============================================================ */

typedef struct {
    int dose_setpoint;       /* ppm or mg/L */
    int flow_rate;
    int pump_speed;
    int proportionality_gain;
} ChemicalDose;

static int chemical_pump_speed(ChemicalDose *cd) {
    int flow_dependent = (cd->flow_rate * cd->pump_speed) / 100;
    int dose_adjustment = (cd->dose_setpoint * cd->proportionality_gain) / 100;
    int result = flow_dependent + dose_adjustment;
    return clamp_value(result, 0, 100);
}

/* ============================================================
 * Auxiliary: Residence time calculation (detention volume)
 * ============================================================ */

static int calculate_residence_time(int tank_volume_liters, int flow_rate_lpm) {
    if (flow_rate_lpm <= 0) return 0;
    int residence_min = (tank_volume_liters * 60) / flow_rate_lpm;
    return residence_min;
}

/* ============================================================
 * Auxiliary: Turbidity feedback with clarifier control
 * ============================================================ */

typedef struct {
    int turbidity_in;
    int turbidity_out;
    int sludge_blanket_height;
    int underflow_rate;
    int removal_efficiency;
} ClarifierCtrl;

static void clarifier_update(ClarifierCtrl *clr) {
    if (clr->turbidity_in > 0) {
        clr->removal_efficiency = ((clr->turbidity_in - clr->turbidity_out) * 100) /
                                  clr->turbidity_in;
    }

    /* Adjust underflow to maintain sludge level */
    if (clr->sludge_blanket_height > 3000) {
        clr->underflow_rate = clamp_value(clr->underflow_rate + 5, 0, 100);
    } else if (clr->sludge_blanket_height < 1000) {
        clr->underflow_rate = clamp_value(clr->underflow_rate - 5, 0, 100);
    }
}

/* ============================================================
 * Auxiliary: UV disinfection dose (UV intensity * residence time)
 * ============================================================ */

typedef struct {
    int uv_lamp_intensity;   /* % output */
    int water_flow_rate;
    int reactor_volume;
    int dose_mJ_cm2;
} UVDisinfection;

static int uv_dose_required(UVDisinfection *uv) {
    if (uv->reactor_volume == 0) return 0;
    int residence = (uv->reactor_volume * 100) / (uv->water_flow_rate + 1);
    int dose = (uv->uv_lamp_intensity * residence) / 100;
    return dose;
}

/* ============================================================
 * Auxiliary: Ozone generation (corona discharge) control
 * ============================================================ */

typedef struct {
    int ozone_demand_mg_min;
    int o2_feed_percent;
    int discharge_voltage;
    int current_output;
} OzoneGen;

static void ozone_generator_update(OzoneGen *oz) {
    if (oz->ozone_demand_mg_min > 50) {
        oz->discharge_voltage = clamp_value(oz->discharge_voltage + 50, 4000, 8000);
    } else if (oz->ozone_demand_mg_min < 20) {
        oz->discharge_voltage = clamp_value(oz->discharge_voltage - 50, 4000, 8000);
    }

    oz->current_output = (oz->discharge_voltage * oz->o2_feed_percent) / 1000;
}

/* ============================================================
 * Auxiliary: pH adjustment by acid/base addition (dual feed)
 * ============================================================ */

typedef struct {
    int target_ph;
    int measured_ph;
    int acid_pump_speed;
    int base_pump_speed;
    int ph_deadband;
} pHControl;

static void ph_adjustment(pHControl *ph) {
    int error = ph->target_ph - ph->measured_ph;

    if (error > ph->ph_deadband) {
        /* Need more base */
        ph->base_pump_speed = clamp_value(ph->base_pump_speed + 3, 0, 100);
        ph->acid_pump_speed = clamp_value(ph->acid_pump_speed - 1, 0, 100);
    } else if (error < -ph->ph_deadband) {
        /* Need more acid */
        ph->acid_pump_speed = clamp_value(ph->acid_pump_speed + 3, 0, 100);
        ph->base_pump_speed = clamp_value(ph->base_pump_speed - 1, 0, 100);
    }
}

/* ============================================================
 * Auxiliary: Dissolved oxygen control (aeration basin)
 * ============================================================ */

typedef struct {
    int do_setpoint;         /* mg/L */
    int do_measured;
    int blower_speed;
    int surface_aerator_speed;
    int do_sensor_lag;
} DissolvedOxygen;

static void do_control_update(DissolvedOxygen *dox) {
    int error = dox->do_setpoint - dox->do_measured;

    if (error > 2) {
        dox->blower_speed = clamp_value(dox->blower_speed + 5, 0, 100);
    } else if (error < -2) {
        dox->blower_speed = clamp_value(dox->blower_speed - 5, 0, 100);
    }

    if (dox->do_setpoint > 5) {
        dox->surface_aerator_speed = clamp_value(dox->surface_aerator_speed + 2, 0, 50);
    }
}

/* ============================================================
 * Auxiliary: Membrane filtration (MF/UF) pressure control
 * ============================================================ */

typedef struct {
    int transmembrane_pressure;
    int target_tmp;
    int permeate_flow;
    int backwash_timer;
    int backwash_interval_min;
} MembraneCtrl;

static void membrane_pressure_control(MembraneCtrl *mem) {
    if (mem->transmembrane_pressure > mem->target_tmp) {
        mem->permeate_flow = clamp_value(mem->permeate_flow - 3, 0, 100);
    } else if (mem->transmembrane_pressure < mem->target_tmp - 10) {
        mem->permeate_flow = clamp_value(mem->permeate_flow + 3, 0, 100);
    }

    mem->backwash_timer++;
    if (mem->backwash_timer > mem->backwash_interval_min * 60) {
        mem->backwash_timer = 0;
        /* Trigger backwash */
    }
}

/* ============================================================
 * Auxiliary: Reverse osmosis (RO) concentrate flow balancing
 * ============================================================ */

static int ro_concentrate_balance(int feed_pressure, int reject_pressure) {
    int differential = feed_pressure - reject_pressure;
    int concentrate_flow = (differential * 50) / 100;
    return clamp_value(concentrate_flow, 0, 100);
}

/* ============================================================
 * Auxiliary: Ion exchange resin regeneration cycle
 * ============================================================ */

typedef struct {
    int resin_capacity_remaining;
    int hardness_treated;
    int last_regen_hours_ago;
    int regen_interval_hours;
    int in_service;
} IonExchange;

static void ion_exchange_update(IonExchange *ix) {
    ix->resin_capacity_remaining -= (ix->hardness_treated / 10);
    ix->last_regen_hours_ago++;

    if (ix->resin_capacity_remaining < 10 || ix->last_regen_hours_ago > ix->regen_interval_hours) {
        ix->in_service = 0;
        /* Schedule regeneration */
    }
}

/* ============================================================
 * Auxiliary: GAC (Granular Activated Carbon) breakthrough detection
 * ============================================================ */

typedef struct {
    int influent_odor_units;
    int effluent_odor_units;
    int contact_hours;
    int saturation_percent;
} GACCtrl;

static int gac_breakthrough_risk(GACCtrl *gac) {
    if (gac->influent_odor_units == 0) return 0;

    int removal_percent = ((gac->influent_odor_units - gac->effluent_odor_units) * 100) /
                         gac->influent_odor_units;

    gac->saturation_percent = ((100 - removal_percent) * gac->contact_hours) / 1000;

    if (gac->saturation_percent > 80) {
        return 1;  /* high risk */
    }
    return 0;
}

/* ============================================================
 * Auxiliary: Combined chlorine residual (free vs combined)
 * ============================================================ */

typedef struct {
    int total_chlorine;
    int free_chlorine;
    int combined_chlorine;
    int chlorine_demand;
} ChlorineResidual;

static void chlorine_residual_calc(ChlorineResidual *cr) {
    cr->combined_chlorine = cr->total_chlorine - cr->free_chlorine;
    cr->chlorine_demand = cr->free_chlorine + (cr->combined_chlorine * 2);

    /* If demand is high, more chlorine needed */
    if (cr->chlorine_demand > 1) {
        /* Signal to increase chlorine feed */
    }
}

/* ============================================================
 * Auxiliary: Residual water age tracking (for booster stations)
 * ============================================================ */

typedef struct {
    int residence_in_tank_min;
    int temperature;
    int residual_decay_percent_per_hr;
    int residual_remaining;
} ResidualTracking;

static void residual_decay_calc(ResidualTracking *rt) {
    int decay_rate = (rt->residual_decay_percent_per_hr * rt->residence_in_tank_min) / 60;

    /* Temperature accelerates decay */
    if (rt->temperature > 20) {
        decay_rate = (decay_rate * (100 + (rt->temperature - 20) * 5)) / 100;
    }

    rt->residual_remaining = rt->residual_remaining - decay_rate;
    if (rt->residual_remaining < 0) rt->residual_remaining = 0;
}

/* ============================================================
 * Auxiliary: Sensor calibration drift detection
 * ============================================================ */

typedef struct {
    int last_calibration_days;
    int drift_rate_per_day;
    int calibration_interval_days;
    int current_reading_offset;
} SensorDrift;

static void sensor_drift_update(SensorDrift *sd) {
    sd->last_calibration_days++;
    sd->current_reading_offset = sd->drift_rate_per_day * sd->last_calibration_days;

    if (sd->last_calibration_days > sd->calibration_interval_days) {
        /* Calibration needed */
    }
}

/* ============================================================
 * Auxiliary: Power demand forecasting (peak shaving)
 * ============================================================ */

typedef struct {
    int current_power_kw;
    int peak_power_limit;
    int reserve_margin;
    int forecast_power_next_hour;
} PowerMgmt;

static int power_demand_control(PowerMgmt *pm) {
    int safe_limit = pm->peak_power_limit - pm->reserve_margin;

    if (pm->current_power_kw > safe_limit) {
        return -1;  /* Reduce load */
    } else if (pm->forecast_power_next_hour > safe_limit) {
        return 0;   /* Prepare to reduce */
    }
    return 1;       /* Normal operation */
}

/* ============================================================
 * Auxiliary: Inventory tracking (reagent levels)
 * ============================================================ */

typedef struct {
    int current_inventory;
    int daily_consumption;
    int reorder_point;
    int days_until_empty;
} InventoryMgmt;

static void inventory_update(InventoryMgmt *inv) {
    inv->current_inventory -= inv->daily_consumption;
    if (inv->daily_consumption > 0) {
        inv->days_until_empty = inv->current_inventory / inv->daily_consumption;
    }

    if (inv->current_inventory < inv->reorder_point) {
        /* Trigger reorder alert */
    }
}

/* ============================================================
 * Auxiliary: End of file marker
 * ============================================================ */

/* ============================================================
 * pl_leak.c — Pipeline leak detection and diagnostics.
 * Real-time transient model (RTTM), pressure-wave correlation,
 * segment inventory, confidence scoring, debounce, escalation.
 * ============================================================ */

#include "pl_app.h"

/* ============================================================
 * GROUND TRUTH
 *
 * pl_on_leak -> scf_var_evt(EVT_ALARM_RAISED,1,data) [call_number=3002]
 *            -> pl_notify(ALM_OVERPRESSURE)
 * pl_leak_eval(pid,value): mass-balance/RTTM state machine; on trip -> pl_notify
 * pl_notify: scf_alarmq_enq(Q_ALARM_HI,alarm_code) ENQ arg1=10 arg2=ALM_OVERPRESSURE=0x0903
 *            scf_msgq_write(Q_MSG,msg) WRITEQ arg1=13
 *            scf_msgq_read(Q_MSG,buf) READQ arg1=13
 * pl_leak_scan(pid) -> scf_tag_read arg2 flows from caller
 * ============================================================ */

/* --- Constant thresholds & parameters --- */
#define RTTM_WINDOW_SZ        16
#define RTTM_SAMPLE_INTERVAL  100
#define PRESS_WAVE_MIN_MAG    5
#define PRESS_WAVE_CORRELATION_THR 0.75
#define CONFIDENCE_INIT       0
#define CONFIDENCE_MAX        100
#define CONFIDENCE_TRIP_THR   85
#define SEGMENT_MAX_COUNT     32
#define DEBOUNCE_CYCLES       4
#define PERSISTENCE_CYCLES    2
#define ALARM_ESCALATION_STEP 3

/* --- State machine states --- */
#define STATE_NORMAL          0
#define STATE_TRANSIENT       1
#define STATE_ALARM_PENDING   2
#define STATE_ALARM_ACTIVE    3
#define STATE_RECOVERY        4

/* --- Pressure segment/event structure --- */
typedef struct {
    int timestamp;
    int pressure;
    int magnitude;
    int signature;
} PressureWave;

/* --- Leak evaluation state --- */
typedef struct {
    int state;
    int baseline_flow;
    int baseline_pressure;
    int mass_balance_integral;
    int mass_error_threshold;
    int rttm_samples[RTTM_WINDOW_SZ];
    int rttm_index;
    int pressure_history[RTTM_WINDOW_SZ];
    int debounce_counter;
    int persistence_counter;
    int alarm_level;
    int last_alarm_code;
} LeakState;

/* --- Segment inventory record --- */
typedef struct {
    int segment_id;
    int length;
    int diameter;
    int material;
    int installed_pressure;
    int current_integrity;
} PipelineSegment;

/* --- RTTM (Real-Time Transient Model) parameters --- */
typedef struct {
    int wave_speed;
    int damping_ratio;
    int frequency;
    int phase_lag;
} RTTMParams;

/* --- Global state (file-local) --- */
static LeakState g_leak_state = {
    .state = STATE_NORMAL,
    .baseline_flow = 0,
    .baseline_pressure = 0,
    .mass_balance_integral = 0,
    .mass_error_threshold = 50,
    .rttm_index = 0,
    .debounce_counter = 0,
    .persistence_counter = 0,
    .alarm_level = 0,
    .last_alarm_code = 0
};

static PipelineSegment g_segments[SEGMENT_MAX_COUNT];
static int g_segment_count = 0;

static PressureWave g_wave_cache[RTTM_WINDOW_SZ];
static int g_wave_cache_count = 0;

static RTTMParams g_rttm_params = {
    .wave_speed = 1200,
    .damping_ratio = 15,
    .frequency = 50,
    .phase_lag = 12
};

/* --- Alarm escalation table --- */
static int g_escalation_codes[] = {
    ALM_LOWLEVEL,
    ALM_OVERPRESSURE,
    ALM_OVERTEMP
};

static int g_escalation_count = 3;

/* --- Forward declarations --- */
static int rttm_evaluate_transient(int pressure_sample);
static int pressure_wave_detector(int current, int previous);
static int correlation_score(void);
static int confidence_accumulate(int score);
static void segment_inventory_init(void);
static int segment_integrity_check(int seg_id);
static int pressure_drop_model(int flow_rate, int segment_id);
static int debounce_filter(int raw_decision);
static int persistence_filter(int raw_decision);
static void alarm_escalate(int current_level, int *new_code);
static int mass_balance_check(int flow_in, int flow_out);
static void transient_buffer_push(int sample);
static int transient_buffer_mean(void);
static int transient_buffer_stdev(void);
static int wave_correlation_matrix(void);
static void pressure_history_record(int pressure);
static int negative_pressure_detect(void);
static int frequency_spectrum_analysis(void);
static void leak_localization(int *estimated_position);

/* ============================================================
 * Public API Functions
 * ============================================================ */

/* Handler for EVT_ALARM_RAISED events. */
void pl_on_leak(int evt, void *data)
{
    /* Post the event with call_number tracking. */
    scf_var_evt(EVT_ALARM_RAISED, 1, data);

    /* Escalate and notify. */
    pl_notify(ALM_OVERPRESSURE);
}

/* Scan and read a specific pressure/flow point. */
int pl_leak_scan(int pid)
{
    TagCtx ctx;
    int buffer;
    int result;

    /* Initialize context and read the tag. */
    ctx.point_id = pid;
    ctx.mode = SCF_READ_LOCK;

    result = scf_tag_read(&ctx, pid, &buffer);
    return result;
}

/* Leak evaluation state machine: mass-balance & RTTM decision logic. */
int pl_leak_eval(int pid, int value)
{
    int trip_decision = 0;
    int mass_error;
    int rttm_score;
    int conf_score;

    /* Record pressure sample. */
    pressure_history_record(value);
    transient_buffer_push(value);

    switch (g_leak_state.state) {

    case STATE_NORMAL:
        /* Check mass balance. */
        mass_error = mass_balance_check(value, g_leak_state.baseline_flow);
        if (mass_error > g_leak_state.mass_error_threshold) {
            g_leak_state.state = STATE_TRANSIENT;
        }
        break;

    case STATE_TRANSIENT:
        /* Evaluate RTTM score. */
        rttm_score = rttm_evaluate_transient(value);

        /* Check for pressure wave signature. */
        if (pressure_wave_detector(value, g_leak_state.pressure_history[0]) > 0) {
            /* Compute confidence through correlation. */
            conf_score = correlation_score();
            conf_score = confidence_accumulate(conf_score);

            if (conf_score > CONFIDENCE_TRIP_THR) {
                g_leak_state.state = STATE_ALARM_PENDING;
            }
        } else if (mass_error < (g_leak_state.mass_error_threshold / 2)) {
            /* False alarm recovery. */
            g_leak_state.state = STATE_RECOVERY;
        }
        break;

    case STATE_ALARM_PENDING:
        /* Debounce and persistence filters. */
        trip_decision = debounce_filter(1);
        trip_decision = persistence_filter(trip_decision);

        if (trip_decision) {
            g_leak_state.state = STATE_ALARM_ACTIVE;
            pl_notify(ALM_OVERPRESSURE);
        }
        break;

    case STATE_ALARM_ACTIVE:
        /* Check for sustained condition or escalation. */
        if (negative_pressure_detect()) {
            alarm_escalate(g_leak_state.alarm_level, &g_leak_state.last_alarm_code);
            pl_notify(g_leak_state.last_alarm_code);
        }
        break;

    case STATE_RECOVERY:
        /* Verify return to baseline. */
        if (mass_balance_check(value, g_leak_state.baseline_flow)
            < (g_leak_state.mass_error_threshold / 4)) {
            g_leak_state.state = STATE_NORMAL;
            g_leak_state.debounce_counter = 0;
            g_leak_state.persistence_counter = 0;
        }
        break;

    default:
        break;
    }

    return trip_decision;
}

/* Notify: enqueue alarm, write & read diagnostic message. */
int pl_notify(int alarm_code)
{
    char msg_buf[64];
    void *out_buf;

    /* Enqueue high-priority alarm. */
    RAISE_ALARM(alarm_code);

    /* Write diagnostic message to queue. */
    msg_buf[0] = (char)alarm_code;
    msg_buf[1] = (char)g_leak_state.alarm_level;
    scf_msgq_write(Q_MSG, (void *)msg_buf);

    /* Read acknowledgment/status. */
    scf_msgq_read(Q_MSG, &out_buf);

    /* Track last alarm code. */
    g_leak_state.last_alarm_code = alarm_code;

    return 0;
}

/* ============================================================
 * Real-Time Transient Model (RTTM) Functions
 * ============================================================ */

/* Evaluate transient behavior based on pressure sample. */
static int rttm_evaluate_transient(int pressure_sample)
{
    int mean_sample;
    int stdev_sample;
    int z_score;
    int score = 0;

    /* Compute mean and standard deviation. */
    mean_sample = transient_buffer_mean();
    stdev_sample = transient_buffer_stdev();

    /* Calculate z-score (distance from mean in units of stdev). */
    if (stdev_sample > 0) {
        z_score = (pressure_sample - mean_sample) * 100 / stdev_sample;

        /* Z-score > 2.5 indicates significant transient. */
        if (z_score > 250) {
            score = 80;
        } else if (z_score > 150) {
            score = 50;
        } else {
            score = 20;
        }
    }

    return score;
}

/* Detect pressure wave (magnitude and phase). */
static int pressure_wave_detector(int current, int previous)
{
    int magnitude;
    int delta;
    PressureWave wave;

    delta = current - previous;
    if (delta < 0) delta = -delta;

    /* Magnitude must exceed threshold. */
    if (delta < PRESS_WAVE_MIN_MAG) {
        return 0;
    }

    magnitude = delta;

    /* Record wave signature. */
    if (g_wave_cache_count < RTTM_WINDOW_SZ) {
        wave.timestamp = g_wave_cache_count;  /* pseudo-timestamp index */
        wave.pressure = current;
        wave.magnitude = magnitude;
        wave.signature = (magnitude * g_rttm_params.frequency) / 100;

        g_wave_cache[g_wave_cache_count] = wave;
        g_wave_cache_count++;
    }

    return magnitude;
}

/* Correlation score: how well do pressure waves correlate with model prediction? */
static int correlation_score(void)
{
    int score = 0;
    int i, j;
    int corr_sum = 0;

    /* Simple cross-correlation: compare each wave with baseline model. */
    for (i = 0; i < g_wave_cache_count; i++) {
        for (j = i + 1; j < g_wave_cache_count && j < i + 3; j++) {
            int delta_time = g_wave_cache[j].timestamp - g_wave_cache[i].timestamp;
            int expected_delay = (g_rttm_params.phase_lag * delta_time) / 100;

            if (expected_delay > 0 && expected_delay < 500) {
                corr_sum += 25;
            }
        }
    }

    /* Normalize. */
    if (g_wave_cache_count > 1) {
        score = (corr_sum / (g_wave_cache_count - 1));
        if (score > 100) score = 100;
    }

    return score;
}

/* Accumulate confidence score with hysteresis. */
static int confidence_accumulate(int score)
{
    int new_confidence;

    /* Weighted running average. */
    new_confidence = (g_leak_state.alarm_level * 70 + score * 30) / 100;

    /* Ensure bounds. */
    if (new_confidence < CONFIDENCE_INIT) new_confidence = CONFIDENCE_INIT;
    if (new_confidence > CONFIDENCE_MAX) new_confidence = CONFIDENCE_MAX;

    g_leak_state.alarm_level = new_confidence;

    return new_confidence;
}

/* ============================================================
 * Pressure Wave & Negative-Pressure Detection
 * ============================================================ */

/* Detect negative pressure (reverse flow signature). */
static int negative_pressure_detect(void)
{
    int i;
    int falling_edges = 0;
    int prev_val;

    if (g_wave_cache_count < 2) return 0;

    /* Count falling edges (sudden pressure drops). */
    for (i = 1; i < g_wave_cache_count; i++) {
        if (g_wave_cache[i].pressure < g_wave_cache[i - 1].pressure) {
            falling_edges++;
        }
    }

    /* More than 40% falling edges suggests negative pressure wave. */
    return (falling_edges * 100) / g_wave_cache_count > 40;
}

/* Frequency spectrum analysis: check for characteristic leak harmonics. */
static int frequency_spectrum_analysis(void)
{
    int spectrum[8] = {0};
    int i;
    int max_bin = 0;
    int max_power = 0;

    /* FFT approximation: bin pressure magnitudes. */
    for (i = 0; i < g_wave_cache_count && i < 8; i++) {
        spectrum[i] = g_wave_cache[i].magnitude * g_wave_cache[i].magnitude;
    }

    /* Find peak frequency bin. */
    for (i = 0; i < 8; i++) {
        if (spectrum[i] > max_power) {
            max_power = spectrum[i];
            max_bin = i;
        }
    }

    /* Leak typically manifests in bins 2-5 (acoustic signature). */
    return (max_bin >= 2 && max_bin <= 5) ? max_power : 0;
}

/* Wave correlation matrix: time-lagged cross-correlation. */
static int wave_correlation_matrix(void)
{
    int i, lag;
    int correlation = 0;
    int count = 0;

    /* Check time-lag correlations. */
    for (lag = 1; lag <= 3 && lag < g_wave_cache_count; lag++) {
        for (i = 0; i + lag < g_wave_cache_count; i++) {
            int delta = g_wave_cache[i].magnitude - g_wave_cache[i + lag].magnitude;
            if (delta < 0) delta = -delta;

            /* Lower delta = better correlation. */
            if (delta < 10) {
                correlation += 25;
                count++;
            }
        }
    }

    if (count > 0) {
        correlation = correlation / count;
    }

    return correlation;
}

/* ============================================================
 * Mass Balance & Pressure Drop Modeling
 * ============================================================ */

/* Mass balance: detect flow conservation violations. */
static int mass_balance_check(int flow_in, int flow_out)
{
    int error;
    int integral_delta;

    /* Compute instantaneous error. */
    error = flow_in - flow_out;
    if (error < 0) error = -error;

    /* Accumulate integral of error over time. */
    integral_delta = error / 10;  /* damping */
    g_leak_state.mass_balance_integral += integral_delta;

    /* Decay integral (recovery). */
    g_leak_state.mass_balance_integral = (g_leak_state.mass_balance_integral * 95) / 100;

    return g_leak_state.mass_balance_integral;
}

/* Model pressure drop across a pipe segment. */
static int pressure_drop_model(int flow_rate, int segment_id)
{
    int drop;
    int friction_factor = 25;
    int length, diameter;

    if (segment_id >= 0 && segment_id < g_segment_count) {
        length = g_segments[segment_id].length;
        diameter = g_segments[segment_id].diameter;

        /* Simplified Darcy-Weisbach. */
        if (diameter > 0) {
            drop = (friction_factor * length * flow_rate * flow_rate) /
                   (diameter * diameter * 1000);
        } else {
            drop = 0;
        }
    } else {
        drop = 0;
    }

    return drop;
}

/* ============================================================
 * Segment Inventory & Integrity Monitoring
 * ============================================================ */

/* Initialize pipeline segment table. */
static void segment_inventory_init(void)
{
    int i;

    g_segment_count = 4;

    for (i = 0; i < g_segment_count; i++) {
        g_segments[i].segment_id = i;
        g_segments[i].length = (i + 1) * 500;  /* meters */
        g_segments[i].diameter = 200 + i * 50;  /* mm */
        g_segments[i].material = 1;  /* steel */
        g_segments[i].installed_pressure = 80 + i * 5;  /* bar */
        g_segments[i].current_integrity = 100;  /* % */
    }
}

/* Check integrity score of a segment. */
static int segment_integrity_check(int seg_id)
{
    int integrity;
    int degradation;

    if (seg_id < 0 || seg_id >= g_segment_count) {
        return 100;
    }

    /* Simulate time-based degradation. */
    degradation = seg_id * 2;  /* each segment degrades slightly */
    integrity = g_segments[seg_id].current_integrity - degradation;

    if (integrity < 0) integrity = 0;
    if (integrity > 100) integrity = 100;

    g_segments[seg_id].current_integrity = integrity;

    return integrity;
}

/* Estimate leak position based on arrival times. */
static void leak_localization(int *estimated_position)
{
    int i, j;
    int arrival_time;
    int distance_sum = 0;
    int count = 0;

    /* Simple triangulation: use pressure wave arrival times at segments. */
    for (i = 0; i < g_segment_count && i < g_wave_cache_count; i++) {
        arrival_time = g_wave_cache[i].timestamp;

        /* Estimate distance based on wave propagation. */
        for (j = i + 1; j < g_segment_count && j < g_wave_cache_count; j++) {
            int delta_time = g_wave_cache[j].timestamp - arrival_time;
            int distance = (delta_time * g_rttm_params.wave_speed) / 1000;

            distance_sum += distance;
            count++;
        }
    }

    if (count > 0) {
        *estimated_position = distance_sum / count;
    } else {
        *estimated_position = 0;
    }
}

/* ============================================================
 * Debounce & Persistence Filtering
 * ============================================================ */

/* Debounce filter: suppress noise/transients via cycle counter. */
static int debounce_filter(int raw_decision)
{
    if (raw_decision) {
        g_leak_state.debounce_counter++;

        if (g_leak_state.debounce_counter >= DEBOUNCE_CYCLES) {
            return 1;
        }
    } else {
        g_leak_state.debounce_counter = 0;
    }

    return 0;
}

/* Persistence filter: verify sustained condition. */
static int persistence_filter(int raw_decision)
{
    if (raw_decision) {
        g_leak_state.persistence_counter++;

        if (g_leak_state.persistence_counter >= PERSISTENCE_CYCLES) {
            return 1;
        }
    } else {
        g_leak_state.persistence_counter = 0;
    }

    return 0;
}

/* ============================================================
 * Alarm Escalation
 * ============================================================ */

/* Escalate alarm level to next severity. */
static void alarm_escalate(int current_level, int *new_code)
{
    int escalation_index;

    escalation_index = (current_level / 33);  /* 0-100 -> 0-3 */

    if (escalation_index >= g_escalation_count) {
        escalation_index = g_escalation_count - 1;
    }

    *new_code = g_escalation_codes[escalation_index];

    /* Increase alarm level. */
    g_leak_state.alarm_level += ALARM_ESCALATION_STEP;
    if (g_leak_state.alarm_level > CONFIDENCE_MAX) {
        g_leak_state.alarm_level = CONFIDENCE_MAX;
    }
}

/* ============================================================
 * RTTM Buffer Management
 * ============================================================ */

/* Push sample into circular transient buffer. */
static void transient_buffer_push(int sample)
{
    g_leak_state.rttm_samples[g_leak_state.rttm_index] = sample;
    g_leak_state.rttm_index = (g_leak_state.rttm_index + 1) % RTTM_WINDOW_SZ;
}

/* Compute mean of buffer samples. */
static int transient_buffer_mean(void)
{
    int sum = 0;
    int i;

    for (i = 0; i < RTTM_WINDOW_SZ; i++) {
        sum += g_leak_state.rttm_samples[i];
    }

    return sum / RTTM_WINDOW_SZ;
}

/* Compute standard deviation of buffer samples. */
static int transient_buffer_stdev(void)
{
    int mean = transient_buffer_mean();
    int variance = 0;
    int i;
    int diff;

    for (i = 0; i < RTTM_WINDOW_SZ; i++) {
        diff = g_leak_state.rttm_samples[i] - mean;
        variance += (diff * diff);
    }

    variance = variance / RTTM_WINDOW_SZ;

    /* Integer square root approximation. */
    if (variance > 1000) return 32;
    if (variance > 500) return 22;
    if (variance > 100) return 10;
    return 5;
}

/* Record pressure into history buffer. */
static void pressure_history_record(int pressure)
{
    int i;

    /* Shift history down. */
    for (i = RTTM_WINDOW_SZ - 1; i > 0; i--) {
        g_leak_state.pressure_history[i] = g_leak_state.pressure_history[i - 1];
    }

    g_leak_state.pressure_history[0] = pressure;
}

/* ============================================================
 * Initialization & Diagnostics
 * ============================================================ */

/* Initialize leak detection subsystem (called at startup). */
void pl_leak_init(void)
{
    int i;

    /* Clear state. */
    g_leak_state.state = STATE_NORMAL;
    g_leak_state.baseline_flow = 500;  /* nominal flow */
    g_leak_state.baseline_pressure = 80;  /* bar */
    g_leak_state.mass_balance_integral = 0;
    g_leak_state.alarm_level = 0;

    /* Initialize buffers. */
    for (i = 0; i < RTTM_WINDOW_SZ; i++) {
        g_leak_state.rttm_samples[i] = 0;
        g_leak_state.pressure_history[i] = 0;
    }

    g_wave_cache_count = 0;

    /* Initialize segment inventory. */
    segment_inventory_init();
}

/* Diagnostic: return current state. */
int pl_leak_get_state(void)
{
    return g_leak_state.state;
}

/* Diagnostic: return current alarm level. */
int pl_leak_get_alarm_level(void)
{
    return g_leak_state.alarm_level;
}

/* Diagnostic: return current mass balance error. */
int pl_leak_get_mass_error(void)
{
    return g_leak_state.mass_balance_integral;
}

/* Diagnostic: check specific segment. */
int pl_leak_segment_status(int seg_id)
{
    return segment_integrity_check(seg_id);
}

/* Diagnostic: estimate leak position. */
int pl_leak_estimate_position(void)
{
    int position = 0;
    leak_localization(&position);
    return position;
}

/* Diagnostic: get frequency analysis. */
int pl_leak_frequency_power(void)
{
    return frequency_spectrum_analysis();
}

/* Diagnostic: get wave correlation score. */
int pl_leak_correlation(void)
{
    return wave_correlation_matrix();
}

/* ============================================================
 * Advanced Filtering & Signal Processing
 * ============================================================ */

/* Kalman-like adaptive filter state. */
typedef struct {
    int state_estimate;
    int covariance;
    int process_noise;
    int measurement_noise;
} AdaptiveFilter;

static AdaptiveFilter g_flow_filter = {
    .state_estimate = 500,
    .covariance = 100,
    .process_noise = 10,
    .measurement_noise = 50
};

/* Adaptive filter predict and update. */
static int adaptive_filter_step(AdaptiveFilter *filt, int measurement)
{
    int prediction;
    int innovation;
    int gain;

    /* Predict. */
    prediction = filt->state_estimate;
    filt->covariance += filt->process_noise;

    /* Update. */
    innovation = measurement - prediction;
    gain = (filt->covariance * 100) / (filt->covariance + filt->measurement_noise);
    filt->state_estimate = prediction + ((innovation * gain) / 100);
    filt->covariance = (100 - gain) * filt->covariance / 100;

    return filt->state_estimate;
}

/* Rate-of-change monitor: detect sudden flow changes. */
typedef struct {
    int prev_flow;
    int prev_timestamp;
    int max_delta_rate;
} RateMonitor;

static RateMonitor g_roc_monitor = {
    .prev_flow = 500,
    .prev_timestamp = 0,
    .max_delta_rate = 200  /* max 200 units/sec */
};

static int rate_of_change_check(int current_flow, int current_ts)
{
    int rate;
    int time_delta;
    int violation = 0;

    if (current_ts > g_roc_monitor.prev_timestamp) {
        time_delta = current_ts - g_roc_monitor.prev_timestamp;
        if (time_delta == 0) time_delta = 1;

        rate = ((current_flow - g_roc_monitor.prev_flow) * 1000) / time_delta;

        if (rate < 0) rate = -rate;

        if (rate > g_roc_monitor.max_delta_rate) {
            violation = 1;
        }
    }

    g_roc_monitor.prev_flow = current_flow;
    g_roc_monitor.prev_timestamp = current_ts;

    return violation;
}

/* Trend analyzer: detect long-term drift. */
typedef struct {
    int samples[32];
    int index;
    int min_val;
    int max_val;
    int drift_threshold;
} TrendAnalyzer;

static TrendAnalyzer g_trend = {
    .index = 0,
    .min_val = 0,
    .max_val = 1000,
    .drift_threshold = 150
};

static int trend_analyze(int sample)
{
    int i;
    int drift_detected = 0;

    g_trend.samples[g_trend.index] = sample;
    g_trend.index = (g_trend.index + 1) % 32;

    /* Compute min/max over window. */
    g_trend.min_val = 10000;
    g_trend.max_val = 0;

    for (i = 0; i < 32; i++) {
        if (g_trend.samples[i] < g_trend.min_val) {
            g_trend.min_val = g_trend.samples[i];
        }
        if (g_trend.samples[i] > g_trend.max_val) {
            g_trend.max_val = g_trend.samples[i];
        }
    }

    /* Drift is sustained deviation from baseline. */
    if ((g_trend.max_val - g_trend.min_val) > g_trend.drift_threshold) {
        drift_detected = 1;
    }

    return drift_detected;
}

/* ============================================================
 * Acoustic Signature Analysis
 * ============================================================ */

/* Acoustic event record. */
typedef struct {
    int frequency;
    int amplitude;
    int duration;
    int harmonic_content;
} AcousticEvent;

static AcousticEvent g_acoustic_events[16];
static int g_acoustic_event_count = 0;

/* Detect acoustic signature of leak (cavitation/turbulence). */
static int acoustic_signature_detect(void)
{
    int i;
    int cavity_score = 0;
    int turbulence_score = 0;

    /* Analyze recorded acoustic events. */
    for (i = 0; i < g_acoustic_event_count && i < 16; i++) {
        /* Cavitation: high frequency, short duration. */
        if (g_acoustic_events[i].frequency > 2000 &&
            g_acoustic_events[i].duration < 50) {
            cavity_score += g_acoustic_events[i].amplitude;
        }

        /* Turbulence: mid-range harmonics. */
        if (g_acoustic_events[i].harmonic_content > 0) {
            turbulence_score += g_acoustic_events[i].amplitude;
        }
    }

    return (cavity_score + turbulence_score) / 2;
}

/* Record an acoustic event. */
static void acoustic_event_record(int freq, int amp, int dur, int harm)
{
    if (g_acoustic_event_count < 16) {
        g_acoustic_events[g_acoustic_event_count].frequency = freq;
        g_acoustic_events[g_acoustic_event_count].amplitude = amp;
        g_acoustic_events[g_acoustic_event_count].duration = dur;
        g_acoustic_events[g_acoustic_event_count].harmonic_content = harm;
        g_acoustic_event_count++;
    }
}

/* ============================================================
 * Multi-Point Pressure Correlation
 * ============================================================ */

/* Pressure sensor array state. */
typedef struct {
    int point_id;
    int pressure;
    int timestamp;
} PressurePoint;

static PressurePoint g_pressure_points[8];
static int g_pressure_point_count = 0;

/* Register a pressure sensor. */
static void pressure_point_register(int point_id)
{
    if (g_pressure_point_count < 8) {
        g_pressure_points[g_pressure_point_count].point_id = point_id;
        g_pressure_points[g_pressure_point_count].pressure = 0;
        g_pressure_points[g_pressure_point_count].timestamp = 0;
        g_pressure_point_count++;
    }
}

/* Update pressure reading at a point. */
static void pressure_point_update(int point_id, int pressure, int timestamp)
{
    int i;

    for (i = 0; i < g_pressure_point_count; i++) {
        if (g_pressure_points[i].point_id == point_id) {
            g_pressure_points[i].pressure = pressure;
            g_pressure_points[i].timestamp = timestamp;
            break;
        }
    }
}

/* Compute arrival time gradient across sensor array. */
static int arrival_time_gradient(void)
{
    int i, j;
    int gradient_sum = 0;
    int pair_count = 0;

    for (i = 0; i < g_pressure_point_count; i++) {
        for (j = i + 1; j < g_pressure_point_count; j++) {
            int delta_p = g_pressure_points[j].pressure - g_pressure_points[i].pressure;
            int delta_t = g_pressure_points[j].timestamp - g_pressure_points[i].timestamp;

            if (delta_t != 0 && delta_p != 0) {
                gradient_sum += ((delta_p * 1000) / delta_t);
                pair_count++;
            }
        }
    }

    if (pair_count > 0) {
        return gradient_sum / pair_count;
    }

    return 0;
}

/* ============================================================
 * Fault/Anomaly Injection (Test Support)
 * ============================================================ */

/* Anomaly injection flags for testing. */
typedef struct {
    int inject_roc_violation;
    int inject_pressure_spike;
    int inject_flow_bias;
    int inject_sensor_fault;
} AnomalyInjector;

static AnomalyInjector g_anomalies = {0};

/* Enable anomaly injection. */
void pl_leak_inject_anomaly(int anomaly_type)
{
    switch (anomaly_type) {
    case 1:  /* ROC violation */
        g_anomalies.inject_roc_violation = 1;
        break;
    case 2:  /* Pressure spike */
        g_anomalies.inject_pressure_spike = 1;
        break;
    case 3:  /* Flow bias */
        g_anomalies.inject_flow_bias = 1;
        break;
    case 4:  /* Sensor fault */
        g_anomalies.inject_sensor_fault = 1;
        break;
    default:
        break;
    }
}

/* Clear all anomaly injections. */
void pl_leak_clear_anomalies(void)
{
    g_anomalies.inject_roc_violation = 0;
    g_anomalies.inject_pressure_spike = 0;
    g_anomalies.inject_flow_bias = 0;
    g_anomalies.inject_sensor_fault = 0;
}

/* Apply injected anomalies to flow measurement. */
static int apply_anomalies(int base_flow)
{
    int flow = base_flow;

    if (g_anomalies.inject_flow_bias) {
        flow += 50;  /* Persistent bias. */
    }

    if (g_anomalies.inject_sensor_fault) {
        flow = flow / 2;  /* Halve reading. */
    }

    return flow;
}

/* ============================================================
 * Multi-Method Leak Confirmation
 * ============================================================ */

/* Combine multiple detection methods into confidence score. */
static int multimethod_confidence(void)
{
    int conf = 0;
    int contributions = 0;

    /* Method 1: Pressure wave correlation. */
    if (g_wave_cache_count > 2) {
        conf += correlation_score();
        contributions++;
    }

    /* Method 2: Frequency analysis. */
    int freq_score = frequency_spectrum_analysis();
    if (freq_score > 0) {
        conf += (freq_score / 100);
        contributions++;
    }

    /* Method 3: Wave correlation matrix. */
    int corr = wave_correlation_matrix();
    if (corr > 0) {
        conf += (corr / 2);
        contributions++;
    }

    /* Method 4: Acoustic signature. */
    int acoustic = acoustic_signature_detect();
    if (acoustic > 20) {
        conf += 40;
        contributions++;
    }

    /* Method 5: Arrival time gradient (multi-point). */
    int gradient = arrival_time_gradient();
    if (gradient != 0) {
        conf += 25;
        contributions++;
    }

    if (contributions > 0) {
        conf = conf / contributions;
    }

    return conf;
}

/* ============================================================
 * Data Logging & Compression
 * ============================================================ */

/* Event log record. */
typedef struct {
    int event_type;
    int timestamp;
    int pressure;
    int flow;
    int alarm_code;
} EventLog;

#define LOG_MAX_SIZE 64
static EventLog g_event_log[LOG_MAX_SIZE];
static int g_log_head = 0;
static int g_log_count = 0;

/* Log an event. */
static void event_log_record(int evt_type, int ts, int press, int flow, int alarm)
{
    EventLog *slot;

    slot = &g_event_log[g_log_head];
    slot->event_type = evt_type;
    slot->timestamp = ts;
    slot->pressure = press;
    slot->flow = flow;
    slot->alarm_code = alarm;

    g_log_head = (g_log_head + 1) % LOG_MAX_SIZE;
    if (g_log_count < LOG_MAX_SIZE) {
        g_log_count++;
    }
}

/* Retrieve log entry. */
int pl_leak_log_entry(int index, int *evt_type, int *timestamp)
{
    int slot;

    if (index < 0 || index >= g_log_count) {
        return -1;
    }

    slot = (g_log_head - g_log_count + index + LOG_MAX_SIZE) % LOG_MAX_SIZE;
    *evt_type = g_event_log[slot].event_type;
    *timestamp = g_event_log[slot].timestamp;

    return 0;
}

/* Get log count. */
int pl_leak_log_count(void)
{
    return g_log_count;
}

/* Flush log (archival). */
int pl_leak_log_flush(void)
{
    g_log_head = 0;
    g_log_count = 0;
    return 0;
}

/* ============================================================
 * Safety Interlocks
 * ============================================================ */

/* Interlock state. */
typedef struct {
    int valve_block_enabled;
    int pump_shutdown_armed;
    int isolation_valves_state;
} SafetyInterlock;

static SafetyInterlock g_safety = {
    .valve_block_enabled = 0,
    .pump_shutdown_armed = 0,
    .isolation_valves_state = 0
};

/* Enable automatic valve isolation on high-severity alarm. */
static int safety_isolation_check(int alarm_code)
{
    if (alarm_code == ALM_OVERPRESSURE) {
        /* Trigger isolation protocol. */
        g_safety.valve_block_enabled = 1;
        g_safety.pump_shutdown_armed = 1;
        return 1;
    }

    return 0;
}

/* Reset safety interlocks. */
int pl_leak_safety_reset(void)
{
    g_safety.valve_block_enabled = 0;
    g_safety.pump_shutdown_armed = 0;
    g_safety.isolation_valves_state = 0;
    return 0;
}

/* Query interlock state. */
int pl_leak_safety_armed(void)
{
    return g_safety.pump_shutdown_armed;
}

/* ============================================================
 * Advanced Leak Volume Estimation
 * ============================================================ */

/* Estimate leak flow rate from pressure drop and orifice model. */
static int leak_flow_estimate(int pressure_drop)
{
    int leak_flow;

    /* Simplified orifice equation: Q = Cd * A * sqrt(2*g*dP). */
    /* Cd ~ 0.6, A ~ 1 mm^2 (small hole). */

    if (pressure_drop > 0) {
        leak_flow = (6 * (pressure_drop * 100)) / 1000;  /* Scaled integer math. */
    } else {
        leak_flow = 0;
    }

    return leak_flow;
}

/* Cumulative leak volume (integral over time). */
static int g_cumulative_leak_volume = 0;

/* Accumulate leak volume based on estimated leak rate. */
static void leak_volume_accumulate(int estimated_leak_rate, int time_interval)
{
    int volume_delta;

    if (estimated_leak_rate > 0 && time_interval > 0) {
        volume_delta = (estimated_leak_rate * time_interval) / 1000;
        g_cumulative_leak_volume += volume_delta;
    }
}

/* Get cumulative leak volume. */
int pl_leak_volume_total(void)
{
    return g_cumulative_leak_volume;
}

/* Reset cumulative volume. */
int pl_leak_volume_reset(void)
{
    g_cumulative_leak_volume = 0;
    return 0;
}

/* ============================================================
 * Extended Initialization & Diagnostics
 * ============================================================ */

/* Initialize pressure sensor array. */
void pl_leak_sensor_array_init(void)
{
    pressure_point_register(PT_PRESSURE);
    pressure_point_register(PT_PUMP_SPEED);
}

/* Inject synthetic acoustic event (for testing). */
void pl_leak_acoustic_inject(int freq, int amp)
{
    acoustic_event_record(freq, amp, 30, 5);
}

/* Get multimethod confidence. */
int pl_leak_multimethod_confidence(void)
{
    return multimethod_confidence();
}

/* Get rate-of-change monitor status. */
int pl_leak_roc_status(void)
{
    return g_roc_monitor.max_delta_rate;
}

/* Get trend analysis status. */
int pl_leak_trend_status(void)
{
    return (g_trend.max_val - g_trend.min_val);
}

/* Get acoustic signature score. */
int pl_leak_acoustic_score(void)
{
    return acoustic_signature_detect();
}

/* Get arrival time gradient. */
int pl_leak_arrival_gradient(void)
{
    return arrival_time_gradient();
}

/* Apply adaptive filter to raw measurement. */
int pl_leak_filter_flow(int raw_flow)
{
    return adaptive_filter_step(&g_flow_filter, raw_flow);
}

/* Perform a self-test diagnostic. */
int pl_leak_selftest(void)
{
    int i;
    int status = 0;

    /* Check segment integrity. */
    for (i = 0; i < g_segment_count; i++) {
        if (segment_integrity_check(i) < 80) {
            status = -1;  /* At least one segment degraded. */
            break;
        }
    }

    return status;
}

/* ============================================================
 * Comparative Pressure Analysis
 * ============================================================ */

/* Pressure baseline tracker for each segment. */
typedef struct {
    int segment_id;
    int baseline_pressure;
    int deviation_count;
    int max_deviation;
} PressureBaseline;

static PressureBaseline g_pressure_baselines[SEGMENT_MAX_COUNT];

/* Initialize pressure baselines. */
static void pressure_baselines_init(void)
{
    int i;

    for (i = 0; i < g_segment_count; i++) {
        g_pressure_baselines[i].segment_id = i;
        g_pressure_baselines[i].baseline_pressure = 80;
        g_pressure_baselines[i].deviation_count = 0;
        g_pressure_baselines[i].max_deviation = 0;
    }
}

/* Track pressure deviation from baseline. */
static int pressure_deviation_track(int segment_id, int current_pressure)
{
    int deviation;
    int threshold = 15;  /* 15 bar deviation threshold */

    if (segment_id < 0 || segment_id >= g_segment_count) {
        return 0;
    }

    deviation = current_pressure - g_pressure_baselines[segment_id].baseline_pressure;
    if (deviation < 0) deviation = -deviation;

    if (deviation > threshold) {
        g_pressure_baselines[segment_id].deviation_count++;
        if (deviation > g_pressure_baselines[segment_id].max_deviation) {
            g_pressure_baselines[segment_id].max_deviation = deviation;
        }
        return 1;  /* Deviation detected */
    }

    return 0;
}

/* Get pressure deviation for diagnostics. */
int pl_leak_pressure_deviation(int segment_id)
{
    if (segment_id >= 0 && segment_id < g_segment_count) {
        return g_pressure_baselines[segment_id].max_deviation;
    }
    return 0;
}

/* ============================================================
 * Dynamic Threshold Adaptation
 * ============================================================ */

/* Adaptive threshold manager. */
typedef struct {
    int base_threshold;
    int current_threshold;
    int adaptation_rate;
    int learning_samples;
    int learned_mean;
    int learned_variance;
} AdaptiveThreshold;

static AdaptiveThreshold g_adapt_threshold = {
    .base_threshold = 50,
    .current_threshold = 50,
    .adaptation_rate = 5,
    .learning_samples = 0,
    .learned_mean = 0,
    .learned_variance = 0
};

/* Learn from normal operating conditions. */
static void threshold_adapt_learn(int sample)
{
    int new_mean;
    int sample_delta;

    if (g_adapt_threshold.learning_samples < 100) {
        /* Accumulate statistics. */
        sample_delta = sample - g_adapt_threshold.learned_mean;

        new_mean = g_adapt_threshold.learned_mean +
                   (sample_delta / (g_adapt_threshold.learning_samples + 1));

        g_adapt_threshold.learned_mean = new_mean;
        g_adapt_threshold.learning_samples++;
    }
}

/* Adapt threshold based on learned distribution. */
static void threshold_adapt_update(void)
{
    int new_threshold;

    if (g_adapt_threshold.learning_samples > 50) {
        /* Set threshold to mean + 2 * learned std dev */
        new_threshold = g_adapt_threshold.learned_mean +
                       (g_adapt_threshold.learned_variance / 25);

        /* Smooth transition to new threshold */
        g_adapt_threshold.current_threshold =
            (g_adapt_threshold.current_threshold * 90 +
             new_threshold * 10) / 100;
    }
}

/* Get current adaptive threshold. */
int pl_leak_adaptive_threshold(void)
{
    return g_adapt_threshold.current_threshold;
}

/* ============================================================
 * Transient Classification
 * ============================================================ */

/* Transient event types. */
#define TRANSIENT_TYPE_NONE        0
#define TRANSIENT_TYPE_STEP        1
#define TRANSIENT_TYPE_RAMP        2
#define TRANSIENT_TYPE_OSCILLATION 3
#define TRANSIENT_TYPE_SPIKE       4

/* Classify current transient event. */
static int transient_classify(void)
{
    int i, j;
    int type = TRANSIENT_TYPE_NONE;
    int sample_count = 0;
    int monotonic_up = 0;
    int monotonic_down = 0;
    int oscillations = 0;
    int peaks = 0;

    if (g_leak_state.rttm_index < 4) {
        return TRANSIENT_TYPE_NONE;
    }

    /* Analyze pattern in recent samples. */
    sample_count = RTTM_WINDOW_SZ;

    for (i = 0; i < sample_count - 1; i++) {
        if (g_leak_state.rttm_samples[i + 1] > g_leak_state.rttm_samples[i]) {
            monotonic_up++;
        } else if (g_leak_state.rttm_samples[i + 1] < g_leak_state.rttm_samples[i]) {
            monotonic_down++;
        }
    }

    /* Check for oscillations (sign changes). */
    for (i = 1; i < sample_count - 1; i++) {
        int curr = g_leak_state.rttm_samples[i];
        int prev = g_leak_state.rttm_samples[i - 1];
        int next = g_leak_state.rttm_samples[i + 1];

        if ((curr > prev && curr > next) || (curr < prev && curr < next)) {
            peaks++;
        }
    }

    oscillations = peaks;

    /* Classify. */
    if (monotonic_up > sample_count - 3) {
        type = TRANSIENT_TYPE_RAMP;
    } else if (monotonic_down > sample_count - 3) {
        type = TRANSIENT_TYPE_RAMP;
    } else if (oscillations > sample_count / 3) {
        type = TRANSIENT_TYPE_OSCILLATION;
    } else if (transient_buffer_stdev() > 40) {
        type = TRANSIENT_TYPE_SPIKE;
    } else if (transient_buffer_stdev() > 10) {
        type = TRANSIENT_TYPE_STEP;
    }

    return type;
}

/* Get transient classification. */
int pl_leak_transient_type(void)
{
    return transient_classify();
}

/* ============================================================
 * Alarm History & Statistics
 * ============================================================ */

/* Alarm statistics. */
typedef struct {
    int total_alarms;
    int alarms_by_type[3];
    int last_alarm_time;
    int alarm_rate;  /* alarms per hour */
} AlarmStats;

static AlarmStats g_alarm_stats = {0};

/* Record alarm event. */
static void alarm_stats_record(int alarm_code)
{
    g_alarm_stats.total_alarms++;

    if (alarm_code == ALM_LOWLEVEL) {
        g_alarm_stats.alarms_by_type[0]++;
    } else if (alarm_code == ALM_OVERPRESSURE) {
        g_alarm_stats.alarms_by_type[1]++;
    } else if (alarm_code == ALM_OVERTEMP) {
        g_alarm_stats.alarms_by_type[2]++;
    }
}

/* Get alarm count. */
int pl_leak_alarm_count(void)
{
    return g_alarm_stats.total_alarms;
}

/* Get count for specific alarm type. */
int pl_leak_alarm_count_by_type(int alarm_code)
{
    if (alarm_code == ALM_LOWLEVEL) {
        return g_alarm_stats.alarms_by_type[0];
    } else if (alarm_code == ALM_OVERPRESSURE) {
        return g_alarm_stats.alarms_by_type[1];
    } else if (alarm_code == ALM_OVERTEMP) {
        return g_alarm_stats.alarms_by_type[2];
    }
    return 0;
}

/* Reset alarm statistics. */
int pl_leak_alarm_stats_reset(void)
{
    g_alarm_stats.total_alarms = 0;
    g_alarm_stats.alarms_by_type[0] = 0;
    g_alarm_stats.alarms_by_type[1] = 0;
    g_alarm_stats.alarms_by_type[2] = 0;
    return 0;
}

/* ============================================================
 * Comprehensive System State Export
 * ============================================================ */

/* Export complete system state for diagnostics. */
typedef struct {
    int current_state;
    int alarm_level;
    int mass_balance_error;
    int confidence_score;
    int transient_type;
    int multimethod_conf;
    int cumulative_volume;
    int safety_armed;
} SystemState;

void pl_leak_export_state(SystemState *out_state)
{
    if (out_state == 0) {
        return;
    }

    out_state->current_state = g_leak_state.state;
    out_state->alarm_level = g_leak_state.alarm_level;
    out_state->mass_balance_error = g_leak_state.mass_balance_integral;
    out_state->confidence_score = multimethod_confidence();
    out_state->transient_type = transient_classify();
    out_state->multimethod_conf = multimethod_confidence();
    out_state->cumulative_volume = g_cumulative_leak_volume;
    out_state->safety_armed = g_safety.pump_shutdown_armed;
}

/* ============================================================
 * GROUND TRUTH (Authorized Call Paths)
 *
 * pl_on_leak:
 *   scf_var_evt(EVT_ALARM_RAISED, 1, data)  [call_number=3002]
 *   -> pl_notify(ALM_OVERPRESSURE)
 *
 * pl_leak_eval:
 *   mass-balance state machine
 *   calls pl_notify on STATE_ALARM_ACTIVE transition
 *   accumulates confidence via correlation_score()
 *   records transient_buffer_push, pressure_history_record
 *
 * pl_notify:
 *   RAISE_ALARM(alarm_code) -> scf_alarmq_enq(Q_ALARM_HI, alarm_code)  [ENQ]
 *   scf_msgq_write(Q_MSG, msg)  [WRITEQ arg1=13]
 *   scf_msgq_read(Q_MSG, buf)   [READQ arg1=13]
 *
 * pl_leak_scan:
 *   scf_tag_read(&ctx, pid, &buffer)  [READF arg2=pid]
 * ============================================================ */

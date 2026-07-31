/*
 * pl_flow.c — Pipeline flow measurement, compensation, and historian.
 * Part of proc_pipeline; implements the synthetic SCADA flow tracer fixture.
 *
 * GROUND TRUTH (traced calls):
 *   pl_on_scan -> scf_evt_post(EVT_SCAN_CYCLE) [call_number=3001]
 *              -> pl_compute_flow(PT_FLOW_RATE) -> pl_read_meter(pid)
 *                 -> scf_tag_read(&ctx,pid,buf) READF launch=EVENT arg2=0x1004 call_number=3001
 *                 -> scf_tag_write(&ctx,PT_SETPOINT,50) WRITEF arg2=0x1007 arg3=50
 *   CHAINED-MACRO: MF_SET(PT_VALVE_POS,250) resolves MF_SET->MF_SET2, stops (not to scf_tag_write)
 *   pl_flow_task -> scf_evt_post(EVT_HIST_FLUSH) [call_number=3005]
 *               -> pl_archive(ARC_TREND):
 *                  scf_hist_save(ARC_TREND,&rec) SAVEF launch=FORK arg1=200
 *                  p = scf_hist_load(ARC_AUDIT,buf); *p=0; WRITE arg1=202 (get_upper=false RETURN-USE)
 *                  scf_cmdq_save(Q_CMD) SAVEQ arg1=12
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "pl_app.h"

/* ============================================================================
 * GLOBALS assigned by pl_app.h contract
 * ============================================================================ */

/* Scratch context for tag reads/writes in pl_read_meter and compensation */
TagCtx g_flow_ctx;
/* g_mf_ctx used by MF_* macros is declared extern in mf_macros.h and
 * defined in ../../lib/scf_stubs.c (shared) — do not redefine here. */

/* ============================================================================
 * STATIC GLOBALS — Measurement state and calibration data
 * ============================================================================ */

/* --- Raw measurement buffers and states --- */
static int s_orifice_dp_raw;          /* Orifice plate differential pressure, raw ADC */
static int s_orifice_dp_filtered;     /* After low-pass filter */
static int s_ultrasonic_dt;           /* Ultrasonic transit-time delta, nanosec */
static int s_turbine_frequency;       /* Turbine meter pulse frequency (Hz) */
static int s_turbine_pulse_count;     /* Accumulated pulse count in measurement interval */

static int s_line_temperature;        /* Flowing gas temperature, 0.01°C units */
static int s_line_pressure;           /* Flowing gas pressure, Pa (absolute) */
static int s_atm_pressure;            /* Atmospheric reference, Pa */

static int s_flow_rate_uncorrected;   /* Before AGA/compensation, cm³/s */
static int s_flow_rate_corrected;     /* After temperature/pressure compensation */
static int s_flow_rate_base_conditions; /* Normalized to standard conditions */

/* --- Totalizer and batching --- */
static long s_cumulative_volume;      /* Total volume measured, mL (double-width) */
static long s_batch_start_volume;     /* Volume at batch start marker */
static int s_batch_number;            /* Current batch/interface ID */
static int s_batch_active;            /* Flag: batch in progress */

/* --- Linepack calculations (gas compressibility state) --- */
static int s_linepack_volume;         /* Estimated gas in pipeline, cm³ */
static int s_linepack_change_rate;    /* Rate of change, cm³/s */

/* --- Meter proving and validation --- */
static int s_proving_run_count;       /* Count of complete proving runs */
static int s_proving_factor;          /* Calibration factor, ppm (parts per million) */
static int s_proving_error_limit;     /* Acceptance threshold, ppm */

/* --- Moving average windows for smoothing --- */
#define WINDOW_DEPTH 60                /* 60-second window at 1Hz scan */
static int s_flow_window[WINDOW_DEPTH];
static int s_window_idx;

/* --- AGA-3 and thermodynamic coefficients --- */
static int s_c_value;                 /* Orifice discharge coefficient, per 1e6 */
static int s_reynolds_number;         /* Flow Reynolds number estimate */
static int s_compressibility_factor;  /* Z (compressibility), normalized x 1e6 */

/* --- Density and viscosity (correlation tables live in statics) --- */
static int s_gas_density_std;         /* kg/m³ at base conditions (x100) */
static int s_gas_viscosity;           /* µPa·s dynamic viscosity (x100) */

/* --- Alarm/validation state --- */
static int s_measurement_quality;     /* 0=bad, 50=fair, 100=good */
static int s_outlier_count;           /* Consecutive outliers detected */
static int s_last_valid_flow;         /* Last measurement that passed QA */

/* --- Historian/archive ring buffer --- */
#define HIST_BUFFER_SIZE 256
static struct {
    int timestamp;
    int flow_rate;
    int temperature;
    int pressure;
    int cumulative_vol;
} s_hist_buffer[HIST_BUFFER_SIZE];
static int s_hist_write_idx;

/* --- Configuration snapshot --- */
static struct {
    int scan_interval_ms;
    int alarm_hi_flow;
    int alarm_lo_flow;
    int temperature_offset;
    int pressure_offset;
} s_config;

/* ============================================================================
 * UTILITY: Low-pass filter for noisy differential pressure
 * ============================================================================ */

static int filter_dp(int raw_dp, int alpha_num, int alpha_den) {
    /* First-order IIR: filtered = filtered + (raw - filtered) * alpha */
    int delta = raw_dp - s_orifice_dp_filtered;
    int adjustment = (delta * alpha_num) / alpha_den;
    s_orifice_dp_filtered += adjustment;
    return s_orifice_dp_filtered;
}

/* ============================================================================
 * AGA-3 ORIFICE FLOW CALCULATION
 *
 * Simplified implementation: Qb = C * Y * A * sqrt(2*g*rho*dP)
 * where: C = discharge coef, Y = expansion factor, A = orifice area,
 *        g = gravity, rho = density, dP = differential pressure
 *
 * This is a core SCADA flow calculation; real implementations include
 * Reynold-number dependent C, thermal mass corrections, etc.
 * ============================================================================ */

static int aga3_compute_discharge_coef(int d_pipe, int d_orifice) {
    /*
     * AGA-3 discharge coefficient depends on beta ratio (d_orifice/d_pipe)
     * and Reynolds number. Simplified lookup table for common ratios.
     */
    int beta = (d_orifice * 1000) / d_pipe;  /* beta x 1000 */
    int c_coef = 610000;                     /* nominal 0.61, x 1e6 */

    /* Adjust for high beta (tighter restriction → higher C) */
    if (beta > 700) {
        c_coef = 640000;  /* 0.64 */
    }
    if (beta > 750) {
        c_coef = 650000;  /* 0.65 */
    }

    /* Adjust for Reynolds effects (typically 1% variation) */
    if (s_reynolds_number < 500000) {
        c_coef = (c_coef * 99) / 100;  /* Slightly lower at low Re */
    }

    s_c_value = c_coef;
    return c_coef;
}

static int aga3_compute_expansion_factor(int pressure, int dp_percent) {
    /*
     * Y expansion factor corrects for gas compressibility change across plate.
     * Simplified: Y = 1 - (k-1)/(6*k) * (dP/P) for weak expansions
     * k ≈ 1.3 for natural gas, dP_percent = (dP/P)*100
     */
    int y_factor;

    if (dp_percent < 5) {
        y_factor = 996000;  /* ≈0.996, x 1e6 */
    } else if (dp_percent < 10) {
        y_factor = 992000;  /* ≈0.992 */
    } else if (dp_percent < 15) {
        y_factor = 987000;  /* ≈0.987 */
    } else {
        y_factor = 980000;  /* ≈0.98 for larger expansions */
    }

    return y_factor;
}

static int aga3_flow_compute(void) {
    /*
     * Main AGA-3 flow calculation. Combines pressure, temperature,
     * differential pressure into a volumetric flow rate (uncorrected).
     *
     * Qb = C * Y * A * sqrt(2*rho*g*dP)
     * In practical terms: flow is proportional to sqrt(dP), with
     * nonlinear density and pressure corrections.
     */
    int dp_filtered = s_orifice_dp_filtered;  /* Pa */
    int pressure_abs = s_line_pressure + s_atm_pressure;  /* Absolute, Pa */
    int temp_abs = 27315 + s_line_temperature / 100;      /* Kelvin x 100 */

    if (pressure_abs <= 0 || temp_abs <= 0 || dp_filtered < 0) {
        return -1;  /* Invalid input state */
    }

    /* Estimate density using ideal gas (rho = P / R*T), then AGA corrections */
    int density_num = 14400000LL * pressure_abs;  /* numerator for rho calc */
    int density = density_num / (461 * temp_abs);  /* gas constant 461 J/(kg·K) */

    /* Orifice area (fixed hardware), in cm² */
    int orifice_area = 125;  /* 5cm diameter orifice → ~19.6 cm², simplified to 125 */

    /* Compute C and Y factors */
    int c_factor = aga3_compute_discharge_coef(100, 70);  /* pipe 100mm, orifice 70mm */
    int dp_percent = (dp_filtered * 100) / pressure_abs;
    int y_factor = aga3_compute_expansion_factor(pressure_abs, dp_percent);

    /* Flow: Q = (C * Y * A / sqrt(rho)) * sqrt(2*g*dP) */
    /* Simplified: Q_raw ∝ sqrt(dP) with density and area corrections */
    int sqrt_dp = (int)sqrt(dp_filtered);  /* Approximate square root */
    int flow_uncorrected = (c_factor * y_factor * orifice_area * sqrt_dp) / 1000000000;

    s_flow_rate_uncorrected = flow_uncorrected;
    return flow_uncorrected;
}

/* ============================================================================
 * ULTRASONIC FLOW MEASUREMENT (cross-check)
 *
 * Measures gas velocity via transit time of ultrasonic pulses upstream
 * vs downstream. Velocity = (tube_length * c_sound) / (2 * dT_transit)
 * Then flow = velocity * cross_section.
 * ============================================================================ */

static int ultrasonic_sound_speed(int temperature, int pressure, int composition) {
    /*
     * Speed of sound in natural gas depends on temperature, pressure, and
     * gas mixture. Simplified correlation.
     * c ≈ sqrt(k*R*T) where k=Cp/Cv ≈ 1.3 for natural gas
     */
    int temp_kelvin = 27315 + temperature / 100;
    int c_approx = (int)sqrt(130000 * 461 * temp_kelvin / 10000);  /* m/s */
    return c_approx;
}

static int ultrasonic_flow_compute(void) {
    /*
     * Compute flow from ultrasonic transit-time measurement.
     * dT = s_ultrasonic_dt (nanoseconds)
     * Velocity ≈ L * c / dT; Flow = Velocity * A
     */
    int c_sound = ultrasonic_sound_speed(s_line_temperature, s_line_pressure, 0);
    int tube_length = 300;  /* mm of measurement path */

    if (s_ultrasonic_dt <= 0 || c_sound <= 0) {
        return -1;
    }

    int velocity = (tube_length * c_sound * 1000000) / s_ultrasonic_dt;  /* mm/s */
    int flow_area = 7850;  /* 100mm diameter tube ≈ 7850 mm² */
    int flow_rate = (velocity * flow_area) / 1000;  /* convert to cm³/s */

    return flow_rate;
}

/* ============================================================================
 * TURBINE METER PULSE COUNTING
 * ============================================================================ */

static int turbine_flow_compute(int pulse_count, int interval_ms) {
    /*
     * Turbine meter produces pulses proportional to volume.
     * K = pulses per volume unit (calibrated, e.g., 100 pulses/liter).
     * Flow = (pulses / K) / time_interval.
     */
    int k_factor = 1000;  /* 1000 pulses per liter */
    long volume_count = pulse_count * 1000 / k_factor;  /* Volume in mL */
    int flow_rate = (volume_count * 1000) / interval_ms;  /* mL/s -> cm³/s */
    return flow_rate;
}

/* ============================================================================
 * TEMPERATURE & PRESSURE COMPENSATION
 *
 * Convert measured flow to standard (base) conditions using gas laws.
 * Q_base = Q_measured * (P_base/P_line) * (T_line/T_base)
 * where T_base = 288.15K (15°C), P_base = 101325 Pa (1 atm standard)
 * ============================================================================ */

static int compute_z_factor(int pressure, int temperature) {
    /*
     * Compressibility factor Z = P*V / (n*R*T) (equation-of-state correction).
     * For natural gas at moderate pressure/temperature, simplified correlation:
     * Z ≈ 1 - (0.001 * P_bar / T_K) + higher order terms
     * Returned as integer x 1e6 (e.g., 998000 ≈ 0.998).
     */
    int pressure_bar = pressure / 100000;  /* Convert Pa to bar */
    int temp_kelvin = 27315 + temperature / 100;

    int z_factor = 1000000 - (pressure_bar * 1000 / (temp_kelvin / 10));  /* Simplified */
    if (z_factor < 500000) z_factor = 500000;  /* Sanity clamp */
    if (z_factor > 1050000) z_factor = 1050000;

    s_compressibility_factor = z_factor;
    return z_factor;
}

static int compensate_to_base_conditions(int flow_measured) {
    /*
     * Adjust flow from line conditions to base (standard reference) conditions.
     * Accounts for temperature and pressure variations.
     */
    int pressure_base = 101325;  /* Pa, standard atmosphere */
    int temp_base = 28815;       /* 15°C in 0.01K units = 288.15K */

    int pressure_line = s_line_pressure + s_atm_pressure;
    int temp_line = 27315 + s_line_temperature / 100;

    if (pressure_line <= 0 || temp_line <= 0) {
        return flow_measured;  /* Can't compensate with bad inputs */
    }

    /* Pressure ratio and temperature ratio */
    long flow_compensated = (long)flow_measured * pressure_line * temp_base;
    flow_compensated /= (pressure_base * temp_line);

    /* Z-factor correction */
    int z_line = compute_z_factor(pressure_line, s_line_temperature);
    int z_base = 1000000;  /* Z≈1 at standard conditions */
    flow_compensated = (flow_compensated * z_base) / z_line;

    return (int)flow_compensated;
}

/* ============================================================================
 * TOTALIZER AND VOLUME ACCUMULATION
 * ============================================================================ */

static void update_cumulative_volume(int flow_rate_cms, int interval_ms) {
    /*
     * Integrate flow over scan interval to accumulate total volume.
     * V = integral(Q dt) ≈ Q * dt (simple rectangular integration).
     */
    long delta_volume = (long)flow_rate_cms * interval_ms / 1000;  /* mL */
    s_cumulative_volume += delta_volume;
}

static int get_batch_volume(void) {
    /*
     * Return volume accumulated in current batch (since batch start marker).
     */
    return (int)(s_cumulative_volume - s_batch_start_volume);
}

static void batch_marker_insert(int batch_id) {
    /*
     * Mark the start of a new batch/interface (e.g., different grade of gas).
     * Historian will record this transition.
     */
    s_batch_start_volume = s_cumulative_volume;
    s_batch_number = batch_id;
    s_batch_active = 1;
}

/* ============================================================================
 * LINEPACK CALCULATION (gas compressibility storage)
 *
 * Linepack = integral of (Z*P*V_section) over pipeline length.
 * Used to detect leaks: sudden drops in linepack without corresponding
 * outlet flow changes suggest pipeline loss.
 * ============================================================================ */

static int linepack_mass_compute(void) {
    /*
     * Estimate "mass" of gas in pipeline at current conditions.
     * Linepack = sum over segments: (Z * P * V) / (R * T).
     * Simplified: assumes constant pressure/temp over ~500-meter pipeline.
     *
     * Returns linepack in kg x 100 (for fixed-point math).
     */
    int pressure = s_line_pressure + s_atm_pressure;
    int temp = 27315 + s_line_temperature / 100;
    int z_factor = s_compressibility_factor;

    /* Pipeline volume ~500m at 100mm diameter ≈ 3.93 m³ = 3.93e6 cm³ */
    long pipeline_volume = 3930000;

    /* Mass = (P * V) / (Z * R * T) in SI */
    long mass_si = (long)pressure * pipeline_volume / (461 * temp);
    mass_si = (mass_si * 1000000) / z_factor;  /* Correct by Z-factor */

    return (int)(mass_si / 10000);  /* Return in kg x 100 */
}

static void linepack_rate_estimate(int prev_linepack) {
    /*
     * Compute rate of change of linepack mass. Indicates pressure transients.
     */
    int curr_linepack = linepack_mass_compute();
    s_linepack_change_rate = curr_linepack - prev_linepack;
}

/* ============================================================================
 * METER PROVING AND CALIBRATION VERIFICATION
 *
 * Periodically verifies meter calibration against a known volume/weight
 * (prover tank or coriolis reference).
 * ============================================================================ */

static int meter_proving_cycle(int prover_volume, int meter_reading) {
    /*
     * Compare meter indication to actual delivered volume in prover.
     * Acceptance typically within ±0.2% (±2000 ppm).
     *
     * Returns proving factor in ppm (parts per million), 0 if failed acceptance.
     */
    if (meter_reading <= 0 || prover_volume <= 0) {
        return 0;
    }

    long error_ppm = ((long)(meter_reading - prover_volume) * 1000000) / prover_volume;
    if (error_ppm < 0) error_ppm = -error_ppm;

    s_proving_error_limit = 2000;  /* ±0.2% */

    if (error_ppm <= s_proving_error_limit) {
        s_proving_run_count++;
        s_proving_factor = (int)((1000000LL * prover_volume) / meter_reading);
        return (int)error_ppm;
    }

    return 0;  /* Failed, don't update factor */
}

/* ============================================================================
 * MOVING AVERAGE WINDOW FOR FLOW SMOOTHING
 *
 * Reduces noise in flow measurements by averaging over N samples.
 * Trades lag for stability.
 * ============================================================================ */

static void flow_window_push(int flow_sample) {
    /*
     * Add a new sample to the moving window and advance index.
     */
    s_flow_window[s_window_idx] = flow_sample;
    s_window_idx = (s_window_idx + 1) % WINDOW_DEPTH;
}

static int flow_window_average(void) {
    /*
     * Compute average of all values in the window.
     */
    long sum = 0;
    int i;
    for (i = 0; i < WINDOW_DEPTH; i++) {
        sum += s_flow_window[i];
    }
    return (int)(sum / WINDOW_DEPTH);
}

/* ============================================================================
 * MEASUREMENT QUALITY AND OUTLIER DETECTION
 * ============================================================================ */

static int validate_measurement(int flow_rate, int last_flow, int max_ramp_rate) {
    /*
     * Check if measurement passes basic sanity checks:
     *   - Not negative
     *   - Not a wild outlier relative to previous value
     *   - Pressure/temperature in plausible ranges
     */
    int quality = 100;  /* Start at good */

    if (flow_rate < 0) {
        return 0;  /* Reject negative flow */
    }

    /* Ramp-rate check: sudden large changes indicate noise/fault */
    int delta = flow_rate - last_flow;
    if (delta < 0) delta = -delta;
    if (delta > max_ramp_rate) {
        quality -= 40;
        s_outlier_count++;
    } else {
        s_outlier_count = 0;  /* Reset consecutive outlier counter */
    }

    /* Reject if too many consecutive outliers */
    if (s_outlier_count > 3) {
        return 0;
    }

    /* Check pressure/temperature are in operating range */
    if (s_line_pressure < 0 || s_line_pressure > 5000000 ||     /* 0-50 bar */
        s_line_temperature < -4000 || s_line_temperature > 12000) {  /* -40 to +120°C */
        quality -= 30;
    }

    s_measurement_quality = quality;
    return quality;
}

/* ============================================================================
 * INTERFACE/BATCH DETECTION
 *
 * Natural gas pipelines carry different grades/batches of gas that are
 * sequentially plugged into the pipeline (interface detection).
 * Detects compositional changes via property shifts.
 * ============================================================================ */

static int detect_interface(int pressure, int temperature, int density) {
    /*
     * Simple heuristic: if density changes significantly, likely an interface.
     * Returns batch_id if detected, -1 otherwise.
     *
     * In real systems, this uses spectroscopy, differential pressure,
     * or pilot-tube arrays.
     */
    int expected_density = (density * 100) / (pressure + s_atm_pressure);
    int density_error = (expected_density - s_gas_density_std) * 100;
    if (density_error < 0) density_error = -density_error;

    if (density_error > 10000) {  /* >10% density shift */
        return s_batch_number + 1;  /* New interface detected */
    }

    return -1;  /* No interface */
}

/* ============================================================================
 * PRESSURE-WAVE / TRANSIENT DETECTION (for leak detection prep)
 *
 * Pipeline disturbances propagate as pressure waves. Detection helps
 * correlate leak events. (Real leak detection is in pl_leak.c)
 * ============================================================================ */

static int pressure_wave_detected(int curr_pressure, int prev_pressure) {
    /*
     * Detect abnormal pressure transients.
     * Threshold: rate of change > 1000 Pa/s indicates fault/isolation event.
     */
    int dp_dt = (curr_pressure - prev_pressure);  /* One-sample rate */
    if (dp_dt < 0) dp_dt = -dp_dt;

    return (dp_dt > 1000) ? 1 : 0;
}

/* ============================================================================
 * TRACER FIXTURE FUNCTIONS — Framework API Integration Points
 * ============================================================================ */

/*
 * pl_read_meter: Read a physical measurement point (pressure transducer, etc.)
 * This is where the tracer sees scf_tag_read().
 *
 * The measurement is buffered; on subsequent calls to pl_compute_flow,
 * these values are available for compensation calculations.
 */
int pl_read_meter(int pid) {
    int buf;
    int status;

    /* Initialize context if needed */
    g_flow_ctx.point_id = pid;
    g_flow_ctx.mode = SCF_READ_LOCK;
    g_flow_ctx.buf = &buf;

    /* TRACED CALL: scf_tag_read is the READF interface */
    status = scf_tag_read(&g_flow_ctx, pid, &buf);

    if (status < 0) {
        return -1;  /* Read failed */
    }

    /* Decode and store the measurement */
    switch (pid) {
        case PT_PRESSURE:
            s_line_pressure = buf;
            return buf;
        case PT_MOTOR_TEMP:
            s_line_temperature = buf;
            return buf;
        case PT_FLOW_RATE:
            s_orifice_dp_raw = buf;  /* OrificeDP is the immediate raw input */
            return buf;
        default:
            return buf;
    }
}

/*
 * pl_compute_flow: Main flow calculation orchestrator.
 * Reads raw measurements, applies AGA-3 calculation, compensates,
 * updates totalizers, and validates output.
 */
int pl_compute_flow(int base_pid) {
    int flow_raw, flow_comp, flow_avg;
    int interval_ms = s_config.scan_interval_ms;

    /* Read primary measurement points */
    pl_read_meter(PT_FLOW_RATE);     /* Orifice DP */
    pl_read_meter(PT_PRESSURE);      /* Line pressure */
    pl_read_meter(PT_MOTOR_TEMP);    /* Line temperature */

    /* Smooth the raw differential pressure */
    filter_dp(s_orifice_dp_raw, 3, 10);  /* α=0.3, low-pass filter */

    /* Compute flow via AGA-3 orifice equation */
    flow_raw = aga3_flow_compute();

    /* Apply temperature/pressure compensation to reference conditions */
    flow_comp = compensate_to_base_conditions(flow_raw);

    /* Add to moving average window */
    flow_window_push(flow_comp);
    flow_avg = flow_window_average();

    /* Validate measurement quality */
    if (!validate_measurement(flow_avg, s_last_valid_flow, 5000)) {
        flow_avg = s_last_valid_flow;  /* Reject outlier, use last good value */
    } else {
        s_last_valid_flow = flow_avg;
    }

    s_flow_rate_corrected = flow_avg;

    /* Accumulate into totalizer */
    update_cumulative_volume(flow_avg, interval_ms);

    /* Check for interfaces */
    int new_batch = detect_interface(s_line_pressure, s_line_temperature,
                                     s_gas_density_std);
    if (new_batch >= 0) {
        batch_marker_insert(new_batch);
    }

    /* CHAINED-MACRO DEMONSTRATION (resolves one hop, documented):
     * MF_SET expands to MF_SET2 which expands to scf_tag_write,
     * but the tracer stops after one hop (known limitation).
     * This demonstrates the limitation in the traced flow.
     */
    MF_SET(PT_VALVE_POS, 250);

    /* Set a setpoint (direct API call) */
    g_flow_ctx.point_id = PT_SETPOINT;
    g_flow_ctx.mode = SCF_WRITE_LOCK;
    scf_tag_write(&g_flow_ctx, PT_SETPOINT, 50);  /* TRACED CALL: WRITEF */

    return flow_avg;
}

/*
 * pl_on_scan: EVENT handler invoked by the timer or scan cycle.
 * Orchestrates the measurement cycle and calls the framework event posting.
 * This is the entry point for the traced EVENT path.
 */
void pl_on_scan(int evt, void *data) {
    int flow_result;

    /* Post the scan-cycle event (call_number=3001 from EVT_SCAN_CYCLE) */
    scf_evt_post(EVT_SCAN_CYCLE, NULL);  /* TRACED CALL: call_number=3001 */

    /* Execute the main flow computation */
    flow_result = pl_compute_flow(PT_FLOW_RATE);

    /* Log measurement for diagnostics */
    (void)flow_result;
}

/* ============================================================================
 * HISTORIAN AND ARCHIVE MANAGEMENT
 * ============================================================================ */

/*
 * pl_archive: Saves flow measurements and metadata to persistent storage.
 * Called periodically by the historian task (pl_flow_task).
 *
 * This is where the tracer sees scf_hist_save and scf_hist_load
 * in a FORK context, plus the scf_cmdq_save call.
 */
int pl_archive(int archive_id) {
    HistRec rec;
    void *loaded_rec;
    unsigned char audit_buf[512];
    int result;

    /* Prepare history record */
    rec.archive_id = archive_id;
    rec.stamp = (int)(s_cumulative_volume & 0xFFFFFFFF);  /* Use volume as pseudo-timestamp */
    rec.value = s_flow_rate_corrected;

    /* TRACED CALL (FORK context): scf_hist_save is SAVEF, arg1=ARC_TREND=200 */
    result = scf_hist_save(ARC_TREND, &rec);

    if (result < 0) {
        return -1;  /* Archive write failed */
    }

    /* TRACED CALL (FORK, get_upper=false): RETURN-USE test shows WRITE semantics
     * p = scf_hist_load(ARC_AUDIT, buf); *p = 0;  => classified as WRITE, arg1=202
     * This demonstrates the tracer's return-value analysis.
     */
    loaded_rec = scf_hist_load(ARC_AUDIT, audit_buf);  /* LOADF */
    if (loaded_rec != NULL) {
        *(int *)loaded_rec = 0;  /* Write to loaded record => WRITE classification */
    }

    /* TRACED CALL: scf_cmdq_save is SAVEQ, arg1=Q_CMD=12 */
    scf_cmdq_save(Q_CMD);

    return result;
}

/*
 * pl_flow_task: Background task that manages historian flushing and
 * long-term flow data storage. Runs in FORK context.
 *
 * This is the entry point for the FORK-launched historian thread.
 */
void pl_flow_task(int task_id) {
    int archive_result;

    /* Signal that historian task is starting */
    scf_evt_post(EVT_HIST_FLUSH, NULL);  /* TRACED CALL: call_number=3005, FORK */

    /* Archive the current flow state to persistent storage */
    archive_result = pl_archive(ARC_TREND);

    if (archive_result < 0) {
        /* On archive failure, post alarm/recovery event if needed */
    }

    /* Historical data has been flushed; historian is up-to-date */
}

/* ============================================================================
 * INITIALIZATION AND STATE MANAGEMENT
 * ============================================================================ */

static void pl_flow_init_statics(void) {
    /*
     * Initialize all static state to safe defaults.
     * Called early in the SCADA startup sequence.
     */
    s_orifice_dp_filtered = 0;
    s_turbine_frequency = 0;
    s_turbine_pulse_count = 0;

    s_line_temperature = 2500;      /* 25°C */
    s_line_pressure = 200000;       /* 2 bar gauge */
    s_atm_pressure = 101325;        /* Atmospheric */

    s_flow_rate_uncorrected = 0;
    s_flow_rate_corrected = 0;
    s_flow_rate_base_conditions = 0;

    s_cumulative_volume = 0;
    s_batch_start_volume = 0;
    s_batch_number = 0;
    s_batch_active = 0;

    s_linepack_volume = 0;
    s_linepack_change_rate = 0;

    s_proving_run_count = 0;
    s_proving_factor = 1000000;
    s_proving_error_limit = 2000;

    s_window_idx = 0;
    memset(s_flow_window, 0, sizeof(s_flow_window));

    s_c_value = 610000;
    s_reynolds_number = 1000000;
    s_compressibility_factor = 1000000;

    s_gas_density_std = 72500;       /* kg/m³ x 100 at STP ≈ 0.725 kg/m³ */
    s_gas_viscosity = 1100;          /* µPa·s x 100 ≈ 11 µPa·s at 20°C */

    s_measurement_quality = 100;
    s_outlier_count = 0;
    s_last_valid_flow = 0;

    s_hist_write_idx = 0;
    memset(s_hist_buffer, 0, sizeof(s_hist_buffer));

    s_config.scan_interval_ms = 200;
    s_config.alarm_hi_flow = 100000;
    s_config.alarm_lo_flow = 100;
    s_config.temperature_offset = 0;
    s_config.pressure_offset = 0;
}

/* ============================================================================
 * ADDITIONAL FLOW MEASUREMENT CROSSCHECKS AND DIAGNOSTICS
 * ============================================================================ */

static int flow_consistency_check(void) {
    /*
     * Compare measurements from different meter types (orifice, ultrasonic, turbine)
     * to validate the primary orifice measurement.
     * Returns 1 if consistent, 0 if divergent.
     */
    int flow_aga = s_flow_rate_corrected;
    int flow_ultrasonic = ultrasonic_flow_compute();
    int flow_turbine = turbine_flow_compute(s_turbine_pulse_count,
                                            s_config.scan_interval_ms);

    /* All three meters should agree within ±5% */
    int error_margin = (flow_aga * 5) / 100;

    if (flow_ultrasonic > 0) {
        int delta = flow_aga - flow_ultrasonic;
        if (delta < 0) delta = -delta;
        if (delta > error_margin) {
            return 0;  /* Ultrasonic disagrees significantly */
        }
    }

    if (flow_turbine > 0) {
        int delta = flow_aga - flow_turbine;
        if (delta < 0) delta = -delta;
        if (delta > error_margin) {
            return 0;  /* Turbine disagrees significantly */
        }
    }

    return 1;  /* All consistent */
}

static int mass_balance_check(int inlet_flow, int outlet_flow) {
    /*
     * Simple mass-balance check: inlet ≈ outlet ± linepack change.
     * Detects gross leaks if inlet >> outlet over time.
     *
     * For diagnostics; the main leak detection logic is in pl_leak.c.
     */
    int linepack_before = linepack_mass_compute();
    /* ... time passes ... */
    int linepack_after = linepack_mass_compute();  /* Would be from different scan */

    int linepack_delta = linepack_after - linepack_before;
    int imbalance = inlet_flow - outlet_flow - linepack_delta;

    return imbalance;  /* Should be ~0 for healthy line */
}

static void flow_diagnostics_log(void) {
    /*
     * Compiles current state snapshot for logging/debugging.
     * (In a real system, this would write to a diagnostic buffer or SD card.)
     */
    int batch_vol = get_batch_volume();
    int consistency = flow_consistency_check();

    /* Pseudo-logging (real code would write to scf_msgq or file) */
    (void)batch_vol;
    (void)consistency;
}

/* ============================================================================
 * ADVANCED: Reynolds Number and Viscosity-Dependent Flows
 * ============================================================================ */

static void update_reynolds_number(void) {
    /*
     * Reynolds = (rho * v * D) / mu
     * where rho=density, v=velocity, D=pipe diameter, mu=viscosity.
     * Needed for accurate C-factor in orifice plate calculations.
     */
    int velocity = (s_flow_rate_corrected * 1000) / 7850;  /* cm³/s to mm/s, then scaled */
    int pipe_diameter = 100;  /* mm */

    if (s_gas_viscosity > 0) {
        long re_num = (long)s_gas_density_std * velocity * pipe_diameter;
        s_reynolds_number = (int)(re_num / (s_gas_viscosity * 100));
    }
}

static void gas_property_correlation_update(void) {
    /*
     * Update gas density and viscosity based on current P, T.
     * These affect flow calculations and meter factor aging.
     * Simplified correlation tables (real systems use detailed EOS).
     */
    int temp_c = s_line_temperature / 100;
    int pres_bar = (s_line_pressure + s_atm_pressure) / 100000;

    /* Density: rho = P/(R*T), with AGA-style adjustments */
    int rho_base = 72500;  /* kg/m³ x 100 at 15°C, 1 atm */
    int rho_adjusted = (rho_base * (pres_bar + 1)) / 11;  /* Very simplified */
    s_gas_density_std = rho_adjusted;

    /* Viscosity increases with temperature (Sutherland-like) */
    int mu_base = 1100;  /* µPa·s x 100 at 20°C */
    int mu_adjusted = mu_base + ((temp_c - 20) * 30);  /* ~0.3% per °C */
    if (mu_adjusted < 500) mu_adjusted = 500;
    if (mu_adjusted > 2000) mu_adjusted = 2000;
    s_gas_viscosity = mu_adjusted;
}

/* ============================================================================
 * EXTENDED DIAGNOSTICS: Meter Factor Drift Detection
 * ============================================================================ */

static int meter_factor_drift_analysis(void) {
    /*
     * Continuous verification that meter calibration factor remains stable.
     * Large drift may indicate swelling, corrosion, or upstream contamination.
     * Returns ppm change from baseline; 0 = stable.
     */
    int current_factor = s_proving_factor;
    int baseline_factor = 1000000;  /* Ideal unity factor */

    if (current_factor <= 0 || baseline_factor <= 0) {
        return 0;
    }

    int drift_ppm = ((current_factor - baseline_factor) * 1000000) / baseline_factor;
    return drift_ppm;
}

/* ============================================================================
 * ADVANCED PRESSURE TRANSDUCER LINEARIZATION
 *
 * Orifice differential pressure transducers have nonlinear output; this
 * section linearizes raw ADC readings via polynomial calibration curves.
 * ============================================================================ */

static int pressure_transducer_linearize(int raw_adc) {
    /*
     * Convert raw ADC count (12-bit, 0-4095) to pressure in Pa.
     * Transducer range: 0-5000 Pa (0-50 mbar), with 4-20mA output.
     * 4095 ADC ≈ 5000 Pa nominal.
     * Polynomial fit: P = a0 + a1*ADC + a2*ADC² + a3*ADC³
     * Coefficients from 3-point calibration (0, 2500, 5000 Pa reference).
     */
    long a0 = 100;         /* Offset (Pa) */
    long a1 = 1220;        /* Linear coefficient */
    long a2 = -5;          /* Quadratic (slight nonlinearity) */

    if (raw_adc < 0 || raw_adc > 4095) {
        return 0;  /* Out of range, return zero pressure */
    }

    long result = a0 + (a1 * raw_adc) + (a2 * raw_adc * raw_adc) / 10000;
    if (result < 0) result = 0;
    if (result > 5000) result = 5000;

    return (int)result;
}

static int temperature_sensor_cold_junction_comp(int thermocouple_mv, int cjc_temp) {
    /*
     * Thermocouple T/C measurements require cold-junction compensation.
     * cjc_temp = cold-junction temperature (internal reference).
     * Converts T/C millivolts back to actual temperature.
     * Type K thermocouple used in this application.
     * Simplified: assumes linear in the operating range (0-150°C).
     *
     * Real implementation uses lookup tables or Steinhart-Hart equations.
     */
    int cjc_mv = (cjc_temp * 41) / 1000;  /* ~41 µV/°C for type K at 25°C */
    int total_mv = thermocouple_mv + cjc_mv;  /* Cold-junction reference voltage */

    /* Convert total mV to temperature (simplified type K: ~41 µV/°C) */
    int temperature_c = (total_mv * 1000) / 41;
    int temperature_01c = temperature_c * 100;  /* Convert to 0.01°C units */

    return temperature_01c;
}

/* ============================================================================
 * SIGNAL CONDITIONING: Spike Detection and Replacement
 * ============================================================================ */

#define SPIKE_HISTORY 5
static int s_spike_history[SPIKE_HISTORY];
static int s_spike_idx;

static int detect_and_filter_spike(int current_sample) {
    /*
     * Detects impulse noise (single outlier spike) and replaces it
     * with interpolation from surrounding samples.
     * Uses simple median-of-neighbors logic.
     */
    int prev1 = s_spike_history[(s_spike_idx + SPIKE_HISTORY - 1) % SPIKE_HISTORY];
    int prev2 = s_spike_history[(s_spike_idx + SPIKE_HISTORY - 2) % SPIKE_HISTORY];
    int next_expected = (prev1 + prev2) / 2;

    int delta = current_sample - next_expected;
    if (delta < 0) delta = -delta;

    int threshold = (next_expected > 100) ? (next_expected / 10) : 50;

    s_spike_history[s_spike_idx] = current_sample;
    s_spike_idx = (s_spike_idx + 1) % SPIKE_HISTORY;

    if (delta > threshold * 3) {
        return next_expected;  /* Spike detected, return interpolated */
    }

    return current_sample;  /* No spike, return original */
}

/* ============================================================================
 * ADVANCED COMPRESSIBILITY CALCULATIONS (Z-factor correlations)
 *
 * The compressibility factor Z = P*V / (n*R*T) varies with gas composition,
 * pressure, and temperature. This section includes multiple correlation
 * methods for high accuracy in SCADA flow applications.
 * ============================================================================ */

static int z_factor_aga8_detailed(int pressure, int temperature, int co2_pct) {
    /*
     * AGA-8 method: uses detailed equation-of-state for higher accuracy.
     * Takes CO2 mole fraction as example impurity (natural gas can contain
     * CO2, N2, He, etc.). Adjusted Z-factor for different compositions.
     *
     * Simplified version; real AGA-8 is complex (iterative solver needed).
     * Returns Z factor x 1e6.
     */
    int z_pure = compute_z_factor(pressure, temperature);  /* Pure gas Z */

    /* CO2 increases compressibility (lowers Z) slightly */
    int co2_effect = (co2_pct * 50) / 100;  /* CO2 reduces Z by ~0.5% per % CO2 */
    z_pure -= co2_effect;

    return z_pure;
}

static int gas_density_aga3(int pressure, int temperature) {
    /*
     * Compute gas density using AGA-3 method (iterative ideal gas with Z-correction).
     * Returns density in kg/m³ x 100.
     */
    int pressure_pa = pressure;
    int temp_k = 27315 + temperature / 100;  /* Absolute temperature */
    int z_factor = compute_z_factor(pressure_pa, temperature);

    if (temp_k <= 0 || z_factor <= 0) {
        return 0;
    }

    /* rho = (P * M) / (Z * R * T)
     * For natural gas (M ≈ 18.5 kg/kmol, R = 8.314 J/(mol·K)):
     * rho = (P * 18.5) / (Z * 8.314 * T) in SI units
     * Simplified: rho ≈ (P * 0.637) / (Z * T) in Pa, result in kg/m³
     */
    long density_num = (long)pressure_pa * 637;
    long density = density_num / (z_factor / 1000 * temp_k);

    return (int)density;  /* x 100 */
}

/* ============================================================================
 * DETAILED ORIFICE PLATE FLOW CALCULATION
 *
 * Extends the basic AGA-3 calculation with:
 *  - Reynolds-dependent C factor
 *  - Pressure profile (compressibility) correction
 *  - Thermal expansion of orifice plate (small but real effect at high temp)
 * ============================================================================ */

static int orifice_plate_thermal_expansion(int temp_operating, int temp_calibration) {
    /*
     * Orifice diameter changes with temperature due to thermal expansion.
     * Brass or steel, linear expansion coefficient ~11-13 ppm/°C.
     * Effect on flow: A ∝ D² so ΔA/A = 2*α*ΔT
     */
    int delta_t = temp_operating - temp_calibration;
    int alpha = 12;  /* ppm/°C, typical for brass */
    int expansion_ppm = (2 * alpha * delta_t) / 100;  /* Delta-A / A in ppm */

    int expansion_factor = 1000000 + expansion_ppm;
    return expansion_factor;
}

static int aga3_compute_Reynolds_dependent_C(int d_pipe, int d_orifice, int flow_rate) {
    /*
     * Discharge coefficient varies with Reynolds number (Re).
     * C typically increases from ~0.61 at Re=10000 to ~0.62 at Re=1000000.
     * This is the dominant source of meter factor drift at low flows.
     */
    int velocity = (flow_rate * 1000) / 7850;  /* Approximate velocity, mm/s */
    int pipe_dia_mm = d_pipe;

    if (s_gas_viscosity <= 0) {
        return s_c_value;  /* Can't compute, use last known */
    }

    long reynolds = (long)s_gas_density_std * velocity * pipe_dia_mm;
    reynolds /= s_gas_viscosity;

    int c_base = 610000;  /* Base 0.61 */

    if (reynolds < 300000) {
        c_base = (c_base * 99) / 100;  /* Lower C at low Re */
    } else if (reynolds > 1000000) {
        c_base = (c_base * 101) / 100;  /* Higher C at high Re */
    }

    s_reynolds_number = (int)reynolds;
    return c_base;
}

static int aga3_flow_compute_detailed(void) {
    /*
     * Extended AGA-3 flow calculation with detailed coefficient corrections.
     * Called in place of the simple aga3_flow_compute for high-accuracy work.
     */
    int dp_filtered = s_orifice_dp_filtered;
    int pressure_abs = s_line_pressure + s_atm_pressure;
    int temp_abs = 27315 + s_line_temperature / 100;

    if (pressure_abs <= 0 || temp_abs <= 0 || dp_filtered < 0) {
        return -1;
    }

    /* Compute gas properties */
    int density = gas_density_aga3(pressure_abs, s_line_temperature);
    int z_factor = compute_z_factor(pressure_abs, s_line_temperature);

    /* Discharge coefficient with Reynolds correction */
    int c_factor = aga3_compute_Reynolds_dependent_C(100, 70, s_flow_rate_uncorrected);

    /* Expansion factor */
    int dp_percent = (dp_filtered * 100) / pressure_abs;
    int y_factor = aga3_compute_expansion_factor(pressure_abs, dp_percent);

    /* Thermal expansion correction for orifice plate */
    int thermal_factor = orifice_plate_thermal_expansion(s_line_temperature / 100, 20);

    /* Square root of differential pressure (approximation) */
    int sqrt_dp = (int)sqrt((double)dp_filtered);

    /* Combine all factors */
    long flow_raw = (long)c_factor * y_factor * thermal_factor * sqrt_dp;
    flow_raw /= 1000000000;  /* Scale factor normalization */

    s_flow_rate_uncorrected = (int)flow_raw;
    return (int)flow_raw;
}

/* ============================================================================
 * CUSTODY TRANSFER ACCURACY: Meter Calibration Tracking
 *
 * In custody-transfer applications, meter accuracy is critical.
 * This section tracks calibration stability and aging.
 * ============================================================================ */

#define CALIBRATION_HISTORY 10
static struct {
    int timestamp;
    int proving_factor;
    int error_ppm;
} s_calibration_log[CALIBRATION_HISTORY];
static int s_calib_log_idx;

static void log_proving_result(int factor, int error) {
    /*
     * Record each meter proving cycle for trend analysis.
     * Helps detect meter aging or fouling.
     */
    s_calibration_log[s_calib_log_idx].proving_factor = factor;
    s_calibration_log[s_calib_log_idx].error_ppm = error;
    s_calib_log_idx = (s_calib_log_idx + 1) % CALIBRATION_HISTORY;
}

static int meter_factor_trend(void) {
    /*
     * Compute slope of meter factor over recent calibration runs.
     * Positive slope = meter losing sensitivity (possibly fouled).
     * Negative slope = meter becoming more sensitive (rare, possible electronics drift).
     */
    if (s_calib_log_idx < 2) {
        return 0;  /* Not enough history yet */
    }

    int oldest_idx = (s_calib_log_idx + 1) % CALIBRATION_HISTORY;
    int newest_idx = (s_calib_log_idx + CALIBRATION_HISTORY - 1) % CALIBRATION_HISTORY;

    int factor_change = s_calibration_log[newest_idx].proving_factor -
                        s_calibration_log[oldest_idx].proving_factor;

    return factor_change;  /* Positive = declining sensitivity */
}

static int meter_uncertainty_estimate(void) {
    /*
     * Estimate total measurement uncertainty (combined from all sources).
     * Includes: transducer accuracy, electronics noise, compensation error, etc.
     * Returns uncertainty as percentage x 1000 (e.g., 2500 = ±0.25%).
     *
     * Simplified: base ±0.2% + aging + temperature drift, etc.
     */
    int base_uncertainty = 2000;  /* ±0.2% from meter certification */

    /* Add uncertainty from recent temperature variation */
    static int s_last_temp;
    int temp_delta = (s_line_temperature - s_last_temp) / 100;
    if (temp_delta < 0) temp_delta = -temp_delta;
    base_uncertainty += (temp_delta * 10);  /* ±0.01% per °C */

    /* Add uncertainty from pressure variation (compressibility uncertainty) */
    int pressure_delta = (s_line_pressure - 200000) / 100000;  /* Deviation from nominal 2 bar */
    if (pressure_delta < 0) pressure_delta = -pressure_delta;
    base_uncertainty += (pressure_delta * 50);

    /* Add uncertainty from meter age / proving history drift */
    int factor_drift = meter_factor_trend();
    if (factor_drift < 0) factor_drift = -factor_drift;
    base_uncertainty += (factor_drift / 100000);  /* Convert ppm to % uncertainty */

    s_last_temp = s_line_temperature;

    return base_uncertainty;
}

/* ============================================================================
 * FLOW BATCHING AND INTERFACE DETECTION (Extended)
 *
 * Pipeline transportation often involves sequential batches of different
 * gas grades, crude oil grades, or refined products. This section extends
 * the basic interface detection with multi-parameter correlation.
 * ============================================================================ */

static struct {
    int density_kg_m3;
    int viscosity_upas;
    int heat_capacity_kj_kg_k;  /* Heat capacity at constant pressure */
    int sound_speed_m_s;
} s_batch_properties;

static int detect_interface_advanced(void) {
    /*
     * Multi-parameter interface detection: compares current properties
     * to expected range for current batch. Triggers on multiple parameters.
     */
    int detections = 0;

    /* Density check */
    int expected_density = s_gas_density_std;
    int density_error = expected_density - (s_gas_density_std * 100) / (s_line_pressure + 1);
    if (density_error < 0) density_error = -density_error;
    if (density_error > expected_density / 10) {
        detections++;
    }

    /* Viscosity check (changes with gas composition) */
    if (s_gas_viscosity > s_batch_properties.viscosity_upas * 120 / 100 ||
        s_gas_viscosity < s_batch_properties.viscosity_upas * 80 / 100) {
        detections++;
    }

    /* Sound speed check (very sensitive to composition, especially CO2, N2) */
    int current_sound_speed = ultrasonic_sound_speed(s_line_temperature, s_line_pressure, 0);
    if (current_sound_speed > 0) {
        int speed_error = current_sound_speed - s_batch_properties.sound_speed_m_s;
        if (speed_error < 0) speed_error = -speed_error;
        if (speed_error > 20) {  /* >20 m/s indicates different composition */
            detections++;
        }
    }

    return detections >= 2 ? 1 : 0;  /* Interface = 2+ parameters agree */
}

/* ============================================================================
 * EXTENDED HISTORIAN MANAGEMENT: Multi-Archive Support
 * ============================================================================ */

static struct {
    int archive_id;
    int record_count;
    int last_write_time;
    int status;  /* 0=idle, 1=writing, -1=error */
} s_archive_status[3];  /* Supports multiple archive types */

static int historian_write_multi_archive(void) {
    /*
     * Write flow snapshot to multiple archive types simultaneously.
     * TREND (200): every scan for trending
     * EVENTLOG (201): only on alarms or significant changes
     * AUDIT (202): every 100 scans for audit trail
     */
    HistRec rec;
    int result = 0;

    rec.archive_id = ARC_TREND;
    rec.stamp = s_hist_write_idx++;
    rec.value = s_flow_rate_corrected;

    /* Write to TREND archive every cycle */
    if (scf_hist_save(ARC_TREND, &rec) < 0) {
        result = -1;
    }

    /* Write to EVENTLOG if flow changed significantly */
    if ((s_last_valid_flow - s_flow_rate_corrected > 1000) ||
        (s_flow_rate_corrected - s_last_valid_flow > 1000)) {
        rec.archive_id = ARC_EVENTLOG;
        if (scf_hist_save(ARC_EVENTLOG, &rec) < 0) {
            result = -1;
        }
    }

    /* Write to AUDIT trail periodically */
    if ((s_hist_write_idx % 100) == 0) {
        rec.archive_id = ARC_AUDIT;
        if (scf_hist_save(ARC_AUDIT, &rec) < 0) {
            result = -1;
        }
    }

    return result;
}

/* ============================================================================
 * COMMAND QUEUE INTEGRATION: Remote Commands for Flow Control
 *
 * Historian task also processes any pending remote commands
 * (calibration updates, valve adjustments, etc.) from the command queue.
 * ============================================================================ */

static int process_remote_command(void) {
    /*
     * Dequeue and execute any pending flow-control commands.
     * Examples: calibration factor update, meter type selection, etc.
     */
    int cmd_id = scf_cmdq_load(Q_CMD);
    if (cmd_id <= 0) {
        return 0;  /* No command pending */
    }

    switch (cmd_id) {
        case 1001:
            /* Recalibrate meter factor */
            s_proving_factor = 1000100;  /* Example: 1.001x correction */
            break;
        case 1002:
            /* Switch to secondary meter (ultrasonic) */
            /* Flow calculation would use ultrasonic_flow_compute() instead */
            break;
        case 1003:
            /* Reset totalizer */
            s_cumulative_volume = 0;
            break;
        default:
            break;
    }

    return cmd_id;
}

/* ============================================================================
 * GAS COMPOSITION ESTIMATION
 *
 * Identifies gas mixture composition from P/T/ρ measurements and
 * adjusts thermodynamic properties accordingly.
 * ============================================================================ */

static struct {
    int ch4_percent;   /* Methane percentage x 100 */
    int c2h6_percent;  /* Ethane */
    int c3h8_percent;  /* Propane */
    int n2_percent;    /* Nitrogen */
    int co2_percent;   /* Carbon dioxide */
    int he_percent;    /* Helium (trace) */
} s_gas_composition;

static void gas_composition_estimate(void) {
    /*
     * Estimate composition by comparing measured sonic velocity and density
     * to reference curves for different gas blends. Simplified heuristic.
     */
    int sound_speed = ultrasonic_sound_speed(s_line_temperature, s_line_pressure, 0);
    int density = gas_density_aga3(s_line_pressure + s_atm_pressure, s_line_temperature);

    /* Speed of sound varies strongly with composition:
     * Hydrocarbon-rich: lower speed (~380 m/s)
     * Air/N2-rich: higher speed (~350 m/s at low P)
     * Pure methane: ~430 m/s at 15°C, 1 atm
     */

    if (sound_speed < 350) {
        /* Heavier hydrocarbons detected (ethane, propane, butane) */
        s_gas_composition.c2h6_percent = 500;  /* ~5% */
        s_gas_composition.c3h8_percent = 200;  /* ~2% */
        s_gas_composition.ch4_percent = 9300;  /* ~93% */
    } else if (sound_speed > 420) {
        /* Lighter gas (more nitrogen or CO2 stripped) */
        s_gas_composition.n2_percent = 1000;  /* ~10% */
        s_gas_composition.ch4_percent = 9000;  /* ~90% */
    } else {
        /* Typical transmission-line natural gas */
        s_gas_composition.ch4_percent = 9500;  /* ~95% */
        s_gas_composition.c2h6_percent = 300;  /* ~3% */
        s_gas_composition.n2_percent = 150;    /* ~1.5% */
        s_gas_composition.co2_percent = 50;    /* ~0.5% */
    }
}

static int molecular_weight_composition(void) {
    /*
     * Calculate average molecular weight of gas mixture.
     * Used in pressure/density calculations.
     * M = sum(x_i * M_i) for component i
     *
     * Molecular weights: CH4=16, C2H6=30, C3H8=44, N2=28, CO2=44, He=4 kg/kmol
     */
    long mw_sum = 0;
    int total_pct = 0;

    mw_sum += (long)s_gas_composition.ch4_percent * 16;
    mw_sum += (long)s_gas_composition.c2h6_percent * 30;
    mw_sum += (long)s_gas_composition.c3h8_percent * 44;
    mw_sum += (long)s_gas_composition.n2_percent * 28;
    mw_sum += (long)s_gas_composition.co2_percent * 44;
    mw_sum += (long)s_gas_composition.he_percent * 4;

    total_pct = s_gas_composition.ch4_percent + s_gas_composition.c2h6_percent +
                s_gas_composition.c3h8_percent + s_gas_composition.n2_percent +
                s_gas_composition.co2_percent + s_gas_composition.he_percent;

    if (total_pct <= 0) {
        return 18500;  /* Default ~18.5 kg/kmol for typical natural gas */
    }

    return (int)(mw_sum / (total_pct / 100));
}

/* ============================================================================
 * KALMAN FILTER FOR FLOW MEASUREMENT (1D simplified)
 *
 * Reduces noise and provides optimal state estimate combining measurement
 * with process model. Essential for noisy transducers.
 * ============================================================================ */

static struct {
    int x_est;           /* Estimated state (flow) */
    int p_est;           /* Estimated error covariance */
    int q_process;       /* Process noise variance */
    int r_measurement;   /* Measurement noise variance */
} s_kalman;

static void kalman_filter_init(void) {
    /*
     * Initialize Kalman filter state.
     * q_process = how much we expect the true flow to change per scan
     * r_measurement = measurement noise variance from transducer specs
     */
    s_kalman.x_est = 0;
    s_kalman.p_est = 100000;  /* High initial uncertainty */
    s_kalman.q_process = 1000;   /* Process model allows ~1000 cm³/s change */
    s_kalman.r_measurement = 5000;  /* Transducer noise ~5% of max value */
}

static int kalman_update(int measurement) {
    /*
     * Execute one Kalman filter cycle.
     * Predict: x_pred = x_est, p_pred = p_est + q
     * Update: K = p_pred / (p_pred + r)
     *         x_est = x_pred + K * (z - x_pred)
     *         p_est = (1 - K) * p_pred
     *
     * Simplified integer arithmetic (fixed-point).
     */
    /* Predict step */
    int p_pred = s_kalman.p_est + s_kalman.q_process;

    /* Kalman gain (fixed-point divide) */
    int k_gain = (p_pred * 1000) / (p_pred + s_kalman.r_measurement);

    /* Update step */
    int innovation = measurement - s_kalman.x_est;
    s_kalman.x_est += (innovation * k_gain) / 1000;

    /* Update error covariance */
    s_kalman.p_est = ((1000 - k_gain) * p_pred) / 1000;

    return s_kalman.x_est;
}

/* ============================================================================
 * EXTENDED DIAGNOSTICS: Signal Health Monitoring
 * ============================================================================ */

static struct {
    int signal_count;
    int error_count;
    int last_error_code;
} s_signal_health[4];  /* Tracks health of 4 input signals: DP, P, T, F */

static void signal_health_update(int signal_id, int is_error) {
    /*
     * Track reliability of each sensor signal.
     * Error rate helps identify failing transducers early.
     */
    if (signal_id >= 0 && signal_id < 4) {
        s_signal_health[signal_id].signal_count++;
        if (is_error) {
            s_signal_health[signal_id].error_count++;
            s_signal_health[signal_id].last_error_code = is_error;
        }
    }
}

static int signal_health_check(int signal_id) {
    /*
     * Returns error rate (ppm) for a given signal.
     * >10000 ppm (>1%) error rate indicates potential failure.
     */
    if (signal_id < 0 || signal_id >= 4 || s_signal_health[signal_id].signal_count == 0) {
        return 0;
    }

    long error_rate = (long)s_signal_health[signal_id].error_count * 1000000;
    error_rate /= s_signal_health[signal_id].signal_count;

    return (int)error_rate;
}

/* ============================================================================
 * EXTENDED FLOW MEASUREMENT: Support for Multiple Meter Types
 *
 * Real pipelines often use multiple independent measurement methods
 * (orifice, turbine, Coriolis, ultrasonic) for cross-check and redundancy.
 * ============================================================================ */

static struct {
    int orifice_flow;
    int turbine_flow;
    int ultrasonic_flow;
    int coriolis_flow;
    int consensus_flow;
} s_multimethod_flow;

static int consensus_flow_compute(void) {
    /*
     * Combine multiple meter readings into a weighted consensus.
     * Weights are based on measurement confidence and meter health.
     * Example: orifice 70%, turbine 20%, ultrasonic 10% (if healthy).
     */
    int weight_sum = 0;
    long flow_weighted_sum = 0;

    /* Orifice (primary, highest weight if healthy) */
    if (s_measurement_quality >= 80) {
        flow_weighted_sum += (long)s_orifice_dp_filtered * 70;
        weight_sum += 70;
    }

    /* Turbine (secondary) */
    if (s_turbine_frequency > 0) {
        int turbine_flow = turbine_flow_compute(s_turbine_pulse_count, 200);
        flow_weighted_sum += (long)turbine_flow * 20;
        weight_sum += 20;
    }

    /* Ultrasonic (backup) */
    int ultrasonic_flow = ultrasonic_flow_compute();
    if (ultrasonic_flow > 0) {
        flow_weighted_sum += (long)ultrasonic_flow * 10;
        weight_sum += 10;
    }

    if (weight_sum > 0) {
        s_multimethod_flow.consensus_flow = (int)(flow_weighted_sum / weight_sum);
        return s_multimethod_flow.consensus_flow;
    }

    return 0;
}

/* ============================================================================
 * PRESSURE-DEPENDENT VOLUME CORRECTION (Advanced Linepack)
 *
 * In compressible flow, the volume at different pressure states differs
 * significantly. This section computes actual vs. standard volumes.
 * ============================================================================ */

static int volume_correction_factor_pv_t(void) {
    /*
     * Returns volume correction factor for converting measured volume
     * to reference conditions: V_ref = V_meas * (P_meas/P_ref) * (T_ref/T_meas) / Z
     * Returned as factor x 1e6.
     */
    int pressure_ref = 101325;     /* Pa, standard */
    int pressure_meas = s_line_pressure + s_atm_pressure;
    int temp_ref = 28815;          /* 15°C in 0.01K units */
    int temp_meas = 27315 + s_line_temperature / 100;

    int z_ref = 1000000;
    int z_meas = s_compressibility_factor;

    if (pressure_meas <= 0 || temp_meas <= 0 || z_meas <= 0) {
        return 1000000;  /* No correction */
    }

    long factor = ((long)pressure_meas * 1000000 * temp_ref * z_ref) /
                  (pressure_ref * temp_meas * z_meas);

    return (int)factor;
}

static long volume_corrected_to_base(long volume_measured) {
    /*
     * Convert measured volume to base (standard reference) conditions.
     * Used for custody transfer billing.
     */
    int factor = volume_correction_factor_pv_t();
    long result = (volume_measured * factor) / 1000000;
    return result;
}

/* ============================================================================
 * EXTENDED TOTALIZER WITH SAFETY LIMITS
 *
 * Totalizer accumulation with guards against:
 *  - Rollover protection (when approaching 32-bit int limit)
 *  - Backwards-motion detection (negative flow at outlet, system reverse)
 *  - Maximum reasonable flow rate sanity checks
 * ============================================================================ */

#define TOTALIZER_ROLLOVER_THRESHOLD 2000000000LL  /* Near 2^31 */

static int totalizer_safe_accumulate(int flow_rate_cms, int interval_ms) {
    /*
     * Safely accumulate flow into long-word totalizer.
     * Returns error code: 0=ok, -1=rollover imminent, -2=negative flow, -3=unreasonable
     */
    if (flow_rate_cms < 0) {
        /* Negative flow: system reverse, counterflow, or sensor fault */
        return -2;
    }

    if (flow_rate_cms > 1000000) {
        /* Unreasonable: >1 million cm³/s at this pipeline (~1000 m³/h) */
        return -3;
    }

    long delta = (long)flow_rate_cms * interval_ms / 1000;
    if (s_cumulative_volume + delta >= TOTALIZER_ROLLOVER_THRESHOLD) {
        /* Approaching limit; would need to switch to extended storage */
        return -1;
    }

    s_cumulative_volume += delta;
    return 0;
}

static long get_totalizer_with_extended_digits(void) {
    /*
     * Return totalizer value. In real systems with rollover,
     * this would combine multiple stored words.
     */
    return s_cumulative_volume;
}

/* ============================================================================
 * FLOW PROFILE AND SWIRL DETECTION
 *
 * Asymmetric velocity profiles (swirl, cavitation) distort orifice meter
 * readings. This section detects evidence of profile distortion.
 * ============================================================================ */

#define VELOCITY_SENSOR_COUNT 4  /* Number of points across diameter */
static int s_velocity_profile[VELOCITY_SENSOR_COUNT];  /* Simplified radial profile */

static int detect_swirl_or_profile_distortion(void) {
    /*
     * Checks if velocity profile is symmetric.
     * Large asymmetry suggests swirl, cavitation, or two-phase flow.
     * Returns asymmetry factor 0-1000 (0=symmetric, 1000=highly asymmetric).
     */
    int center = (s_velocity_profile[1] + s_velocity_profile[2]) / 2;
    int edge = (s_velocity_profile[0] + s_velocity_profile[3]) / 2;

    int asymmetry = center - edge;
    if (asymmetry < 0) asymmetry = -asymmetry;

    int factor = (center > 0) ? (asymmetry * 1000) / center : 0;
    if (factor > 1000) factor = 1000;

    return factor;
}

static int apply_swirl_correction(int flow_measured) {
    /*
     * If swirl detected, apply empirical correction to orifice discharge coef.
     * Simplified: swirl typically lowers effective C by 1-2%.
     */
    int swirl = detect_swirl_or_profile_distortion();
    int correction_factor = 1000 - (swirl / 2);  /* Reduce by up to 0.5% */

    long corrected = ((long)flow_measured * correction_factor) / 1000;
    return (int)corrected;
}

/* ============================================================================
 * CAVITATION AND TWO-PHASE FLOW DETECTION
 *
 * If downstream pressure drops below vapor pressure, cavitation occurs,
 * invalidating the orifice flow equation. This section detects it.
 * ============================================================================ */

static int water_vapor_pressure_at_temp(int temp_c) {
    /*
     * Approximate saturation vapor pressure of water as function of temperature.
     * Returns pressure in Pa. Simplified using Antoine equation.
     * Only relevant if pipeline carries humid gas.
     */
    if (temp_c < 0) temp_c = 0;
    if (temp_c > 100) temp_c = 100;

    /* Simplified: P_vap ≈ 611 Pa * exp(17.27 * T / (T + 237.7)) at 0-100°C */
    /* Very rough linear approximation for simplicity */
    int p_vap = 611 + (temp_c * 100);  /* ~611 Pa at 0°C, ~10000 Pa at 100°C */

    return p_vap;
}

static int detect_cavitation(int pressure_downstream) {
    /*
     * Cavitation occurs if P_downstream < P_vapor.
     * More generally, cavitation happens when backpressure is insufficient
     * for stable orifice operation.
     * Returns 1 if cavitation likely, 0 otherwise.
     */
    int p_vap = water_vapor_pressure_at_temp(s_line_temperature / 100);

    if (pressure_downstream < p_vap) {
        return 1;  /* Cavitation risk */
    }

    if (pressure_downstream < (s_line_pressure / 4)) {
        /* Expansion ratio >4:1 is risky for orifice meters */
        return 1;
    }

    return 0;
}

/* ============================================================================
 * COMPRESSOR STATION SIMULATION: Discharge Measurement
 *
 * If this measurement point is at a compressor discharge, additional
 * considerations apply: vibration, pulsation, multiphase discharge.
 * ============================================================================ */

static int s_compressor_discharge_factor;  /* Flow correction for pulsating discharge */

static void compressor_pulsation_correction(int comp_stroke_rate) {
    /*
     * Compressor discharge is pulsating, not steady. Orifice meters
     * may over/underestimate pulsating flow by 1-3%.
     * Correction depends on stroke rate and orifice bore ratio.
     */
    int bore_ratio = 70;  /* D_orifice / D_pipe = 70/100 */
    int correction_ppm = (comp_stroke_rate * 100 * bore_ratio) / 1000;  /* Simplified */

    s_compressor_discharge_factor = 1000000 - (correction_ppm / 2);  /* Conservative -0.05% */
}

/* ============================================================================
 * CONFIGURATION PERSISTENCE: Save/Restore Calibration State
 * ============================================================================ */

static int save_calibration_state(void) {
    /*
     * Prepare meter calibration state for archival:
     * proving factor, recent drift, configuration snapshots.
     * Returns status: 0=ok, <0=error.
     */
    HistRec calib_rec;
    calib_rec.archive_id = ARC_TREND;
    calib_rec.stamp = (int)(s_proving_run_count & 0xFFFFFFFF);
    calib_rec.value = s_proving_factor;

    /* Save via historian */
    if (scf_hist_save(ARC_TREND, &calib_rec) < 0) {
        return -1;
    }

    return 0;
}

static int restore_calibration_state(void) {
    /*
     * Restore previously saved calibration factor on startup.
     * Allows soft-recovery without full re-proving.
     */
    unsigned char buf[512];
    void *loaded = scf_hist_load(ARC_TREND, buf);

    if (loaded == NULL) {
        return -1;  /* No saved state */
    }

    HistRec *rec = (HistRec *)loaded;
    s_proving_factor = rec->value;

    return 0;
}

/* ============================================================================
 * FLOW RATE LIMITS AND ALARMS (set in configuration)
 * ============================================================================ */

static int check_flow_alarms(int flow_rate) {
    /*
     * Monitor flow against configured limits.
     * Posts alarms if exceeded.
     */
    if (flow_rate > s_config.alarm_hi_flow) {
        RAISE_ALARM(ALM_OVERPRESSURE);  /* Use pressure alarm as proxy (traced) */
        return 1;
    }

    if (flow_rate < s_config.alarm_lo_flow && s_batch_active) {
        RAISE_ALARM(ALM_LOWLEVEL);  /* Low flow alarm */
        return -1;
    }

    return 0;
}

/* ============================================================================
 * HISTORIAN BUFFER WRAPAROUND AND RECOVERY
 * ============================================================================ */

static int historian_next_record_index(void) {
    /*
     * Advance histogram write pointer with wraparound.
     * In real systems, would check for overwrite of unread data.
     */
    int next = (s_hist_write_idx + 1) % HIST_BUFFER_SIZE;
    return next;
}

static void historian_commit_batch(void) {
    /*
     * Batch-write accumulated samples to persistent storage.
     * Called periodically (every 100 scans) to flush buffer.
     */
    int count = 0;
    int idx;

    for (idx = 0; idx < HIST_BUFFER_SIZE && count < 10; idx++) {
        HistRec rec;
        rec.archive_id = ARC_TREND;
        rec.stamp = s_hist_buffer[idx].timestamp;
        rec.value = s_hist_buffer[idx].flow_rate;

        if (scf_hist_save(ARC_TREND, &rec) >= 0) {
            count++;
        }
    }
}

/* ============================================================================
 * STATISTICAL FLOW SUMMARY FOR DAILY/MONTHLY REPORTS
 * ============================================================================ */

static struct {
    int flow_min;
    int flow_max;
    long flow_sum;      /* For computing average */
    int sample_count;
} s_flow_stats;

static void accumulate_flow_statistics(int flow_rate) {
    /*
     * Track min, max, sum for eventual averaging.
     */
    if (s_flow_stats.sample_count == 0) {
        s_flow_stats.flow_min = flow_rate;
        s_flow_stats.flow_max = flow_rate;
    } else {
        if (flow_rate < s_flow_stats.flow_min) {
            s_flow_stats.flow_min = flow_rate;
        }
        if (flow_rate > s_flow_stats.flow_max) {
            s_flow_stats.flow_max = flow_rate;
        }
    }

    s_flow_stats.flow_sum += flow_rate;
    s_flow_stats.sample_count++;
}

static int get_flow_average(void) {
    /*
     * Compute average from accumulated statistics.
     */
    if (s_flow_stats.sample_count == 0) {
        return 0;
    }

    return (int)(s_flow_stats.flow_sum / s_flow_stats.sample_count);
}

/* ============================================================================
 * ADVANCED: Maintenance and Health Diagnostics
 *
 * Predictive maintenance: tracks trends that indicate upcoming maintenance.
 * ============================================================================ */

static struct {
    int meter_factor_drift_ppm;     /* Cumulative drift from baseline */
    int transducer_noise_level;     /* RMS noise in raw signal */
    int filter_coefficient_age;     /* Estimated age of filter calibration */
    int last_maintenance_timestamp; /* When last serviced */
} s_maintenance_state;

static int estimate_transducer_noise(void) {
    /*
     * Compute RMS noise in differential pressure signal.
     * High noise suggests failing transducer or contamination.
     * Returns noise level x 100 in Pa.
     */
    long sum_sq = 0;
    int i;

    for (i = 0; i < WINDOW_DEPTH; i++) {
        int sample = s_flow_window[i];
        int avg = flow_window_average();
        int deviation = sample - avg;
        sum_sq += (long)deviation * deviation;
    }

    int rms = (int)sqrt((double)sum_sq / WINDOW_DEPTH);
    s_maintenance_state.transducer_noise_level = rms;

    return rms;
}

static int predict_maintenance_interval(void) {
    /*
     * Estimate when meter should be serviced based on drift and noise trends.
     * Returns days until recommended maintenance (0 = immediate, -1 = unknown).
     *
     * Heuristic: if noise increasing or factor drifting, shorten interval.
     */
    int noise_level = estimate_transducer_noise();
    int drift = meter_factor_drift_analysis();

    int days_remaining = 365;  /* Default annual maintenance */

    if (noise_level > 1000) {  /* High noise */
        days_remaining = 30;
    } else if (drift > 5000 || drift < -5000) {  /* >0.5% drift */
        days_remaining = 90;
    } else if (s_outlier_count > 5) {  /* Too many outliers */
        days_remaining = 60;
    }

    return days_remaining;
}

static int run_self_test_sequence(void) {
    /*
     * Execute meter self-test: validates sensor ranges, filter response, etc.
     * Returns test result: 0=pass, 1=warning, -1=fail.
     */
    int result = 0;

    /* Test 1: Pressure transducer in range */
    if (s_line_pressure < 0 || s_line_pressure > 5000000) {
        result = -1;
    }

    /* Test 2: Temperature transducer in range */
    if (s_line_temperature < -4000 || s_line_temperature > 12000) {
        result = -1;
    }

    /* Test 3: Filter convergence (should have decayed old spikes by now) */
    int oldest_sample = s_flow_window[s_window_idx];
    int newest_sample = s_flow_window[(s_window_idx + WINDOW_DEPTH - 1) % WINDOW_DEPTH];
    if ((oldest_sample - newest_sample > 5000) ||
        (newest_sample - oldest_sample > 5000)) {
        result = 1;  /* Warning: filter slow to converge */
    }

    /* Test 4: Meter proving factor reasonable (within ±2% of unity) */
    if (s_proving_factor < 980000 || s_proving_factor > 1020000) {
        result = 1;  /* Warning: meter may be drifted */
    }

    return result;
}

/* ============================================================================
 * FLOW RATE TRENDING AND FORECASTING
 *
 * Simple time-series analysis for flow trending and anomaly detection.
 * ============================================================================ */

#define TREND_HISTORY 288  /* 24-hour history at 5-minute intervals */
static struct {
    int timestamp;
    int flow_rate;
    int temperature;
    int pressure;
} s_trend_history[TREND_HISTORY];
static int s_trend_idx;

static void log_trend_point(int flow, int temp, int press) {
    /*
     * Record current measurement for trend analysis.
     */
    s_trend_history[s_trend_idx].timestamp = (int)(s_cumulative_volume & 0xFFFFFFFF);
    s_trend_history[s_trend_idx].flow_rate = flow;
    s_trend_history[s_trend_idx].temperature = temp;
    s_trend_history[s_trend_idx].pressure = press;
    s_trend_idx = (s_trend_idx + 1) % TREND_HISTORY;
}

static int compute_flow_trend_slope(void) {
    /*
     * Compute slope of flow vs. time over recent history.
     * Positive slope = flow increasing over time
     * Negative slope = flow decreasing (possible leak)
     * Returns slope in (cm³/s) / hour.
     */
    if (s_trend_idx < 2) {
        return 0;  /* Not enough history */
    }

    int oldest_idx = (s_trend_idx + 1) % TREND_HISTORY;
    int newest_idx = (s_trend_idx + TREND_HISTORY - 1) % TREND_HISTORY;

    int flow_delta = s_trend_history[newest_idx].flow_rate -
                     s_trend_history[oldest_idx].flow_rate;

    /* Assuming 288 samples over 24 hours, ~5-min intervals */
    long slope = (long)flow_delta * 12;  /* Per hour */

    return (int)slope;
}

static int detect_flow_anomaly(void) {
    /*
     * Detects sudden, unexplained changes in flow.
     * Returns severity: 0=normal, 1=minor, 2=major anomaly.
     */
    int slope = compute_flow_trend_slope();

    if (slope > 20000 || slope < -20000) {
        return 2;  /* Major trend change (±20000 cm³/s per hour) */
    }

    if (slope > 5000 || slope < -5000) {
        return 1;  /* Minor trend change */
    }

    return 0;  /* Normal */
}

/* ============================================================================
 * ENERGY/POWER FLOW (Secondary calculation)
 *
 * In gas-fired systems, volumetric flow must be converted to energy flow.
 * Calorific value varies with composition and state.
 * ============================================================================ */

static int gross_calorific_value_gas(void) {
    /*
     * Compute gross calorific value (heat of combustion) of gas.
     * MJ/m³ at standard conditions.
     *
     * Depends on composition: methane ~37.5 MJ/m³, ethane ~63, etc.
     * Returns GCV x 100 in MJ/m³ units.
     */
    int gcv = 3750;  /* ~37.5 MJ/m³ for typical 95% methane gas */

    /* Adjust based on estimated composition */
    if (s_gas_composition.c2h6_percent > 500) {
        gcv += (s_gas_composition.c2h6_percent - 500) / 5;  /* Higher for ethane content */
    }

    if (s_gas_composition.n2_percent > 200) {
        gcv -= (s_gas_composition.n2_percent - 200) / 10;  /* Lower for nitrogen */
    }

    return gcv;
}

static long compute_energy_flow(void) {
    /*
     * Convert volumetric flow to energy (power) in MJ/s = MW.
     * Energy_flow = volume_flow * density * gcv / 1e6
     * Returns power in kW x 100.
     */
    int volume_flow = s_flow_rate_corrected;  /* cm³/s */
    int gcv = gross_calorific_value_gas();    /* MJ/m³ x 100 */

    if (volume_flow <= 0) {
        return 0;
    }

    /* volume_flow cm³/s = volume_flow/1e6 m³/s
     * energy = (volume/1e6) * gcv/100 MJ/s = power in MW
     * in units of kW x 100: power = volume_flow * gcv / 10000
     */
    long energy = ((long)volume_flow * gcv) / 10000;

    return energy;  /* kW x 100 */
}

/* ============================================================================
 * ADVANCED: Flow Rate Hysteresis Detection
 *
 * Some flowmeters exhibit hysteresis (different reading depending on
 * direction of flow change). This section detects and compensates.
 * ============================================================================ */

static struct {
    int rising_threshold;   /* Flow reading when going up-to-down */
    int falling_threshold;  /* Flow reading when going down-to-up */
    int last_direction;     /* 1=rising, 0=falling */
} s_hysteresis_state;

static int apply_hysteresis_compensation(int flow_raw, int last_flow) {
    /*
     * Detect hysteresis and apply correction.
     * If flow increasing, apply +offset; if decreasing, apply -offset.
     */
    int delta = flow_raw - last_flow;
    int hysteresis_offset = 50;  /* Small correction */

    if (delta > 0) {
        s_hysteresis_state.last_direction = 1;
        return flow_raw + hysteresis_offset;
    } else if (delta < 0) {
        s_hysteresis_state.last_direction = 0;
        return flow_raw - hysteresis_offset;
    }

    return flow_raw;  /* No change, use as-is */
}

/* ============================================================================
 * CONFIGURATION RELOAD AND PERSISTENCE INTERFACE
 * ============================================================================ */

static int load_config_from_archive(void) {
    /*
     * Restore meter configuration from persistent storage.
     * Includes calibration factors, alarm limits, filter coefficients.
     */
    unsigned char config_buf[256];
    void *loaded = scf_hist_load(ARC_AUDIT, config_buf);

    if (loaded == NULL) {
        return -1;  /* No saved config */
    }

    /* In real code, would deserialize config struct from loaded buffer */
    s_config.scan_interval_ms = 200;
    s_config.alarm_hi_flow = 100000;
    s_config.alarm_lo_flow = 100;

    return 0;
}

static int save_config_to_archive(void) {
    /*
     * Persist current configuration to stable storage.
     */
    HistRec config_rec;
    config_rec.archive_id = ARC_AUDIT;
    config_rec.stamp = s_config.scan_interval_ms;
    config_rec.value = s_config.alarm_hi_flow;

    if (scf_hist_save(ARC_AUDIT, &config_rec) < 0) {
        return -1;
    }

    return 0;
}

/* ============================================================================
 * EXTENDED INITIALIZATION: State Machine for Cold Start
 * ============================================================================ */

static int s_init_phase;  /* 0=stalled, 1=warmup, 2=stabilizing, 3=ready */

static int cold_start_state_machine(void) {
    /*
     * After power-up, meter goes through startup phases:
     * 1. Warmup: transducers and electronics stabilize (10-30 sec)
     * 2. Stabilizing: filters converge, first measurements taken (1-5 min)
     * 3. Ready: meter ready for accurate measurement
     */
    static int startup_counter;

    if (s_init_phase == 0) {
        /* Stalled: initialize all subsystems */
        pl_flow_init_statics();
        kalman_filter_init();
        startup_counter = 0;
        s_init_phase = 1;
        return -1;  /* Not ready */
    }

    if (s_init_phase == 1) {
        /* Warmup phase */
        startup_counter++;
        if (startup_counter < 30) {  /* 30 scans ~ 6 sec at 5Hz */
            return -1;  /* Still warming up */
        }
        s_init_phase = 2;
        startup_counter = 0;
    }

    if (s_init_phase == 2) {
        /* Stabilizing phase */
        startup_counter++;
        if (startup_counter < 300) {  /* 300 scans ~ 60 sec */
            return -1;  /* Still stabilizing */
        }
        s_init_phase = 3;
    }

    return (s_init_phase == 3) ? 0 : -1;  /* 0 = ready, -1 = not ready */
}

/* ============================================================================
 * FINAL DIAGNOSTIC SUMMARY AND STATUS REPORTING
 * ============================================================================ */

static struct {
    int total_scans;
    int valid_measurements;
    int failed_measurements;
    int alarms_posted;
    int maintenance_flags;
} s_lifetime_stats;

static void update_lifetime_statistics(int is_valid) {
    /*
     * Track meter operation over its lifetime for reporting.
     */
    s_lifetime_stats.total_scans++;

    if (is_valid) {
        s_lifetime_stats.valid_measurements++;
    } else {
        s_lifetime_stats.failed_measurements++;
    }
}

static int get_meter_uptime_availability(void) {
    /*
     * Returns percentage uptime: 100 * valid / total (x 100 for precision).
     */
    if (s_lifetime_stats.total_scans == 0) {
        return 0;
    }

    long availability = (long)s_lifetime_stats.valid_measurements * 10000 /
                        s_lifetime_stats.total_scans;

    return (int)availability;  /* e.g., 9999 = 99.99% */
}

static void meter_diagnostic_snapshot(void) {
    /*
     * Compile comprehensive diagnostic snapshot for logging/debug output.
     * In real code, would be written to a diagnostic message or log file.
     */
    int quality = s_measurement_quality;
    int noise = estimate_transducer_noise();
    int trend = compute_flow_trend_slope();
    int anomaly = detect_flow_anomaly();
    int maintenance_days = predict_maintenance_interval();

    (void)quality;  /* Use to suppress compiler warnings */
    (void)noise;
    (void)trend;
    (void)anomaly;
    (void)maintenance_days;

    /* Real code would format these into a report buffer */
}

/* ============================================================================
 * GROUND TRUTH SUMMARY
 *
 * TRACED API CALLS IN THIS FILE:
 *
 * 1. pl_on_scan (EvtHandler, launched by EVENT registration):
 *    -> scf_evt_post(EVT_SCAN_CYCLE, NULL)  [call_number=3001]
 *    -> pl_compute_flow(PT_FLOW_RATE)
 *       -> pl_read_meter(PT_FLOW_RATE, ...)
 *          -> scf_tag_read(&g_flow_ctx, PT_FLOW_RATE=0x1004, buf)  [READF, arg2=0x1004, launch=EVENT]
 *       -> scf_tag_write(&g_flow_ctx, PT_SETPOINT=0x1007, 50)  [WRITEF, arg2=0x1007, arg3=50]
 *       -> MF_SET(PT_VALVE_POS=0x1002, 250)  [CHAINED MACRO: resolves MF_SET->MF_SET2, stops]
 *
 * 2. pl_flow_task (TaskEntry, launched by FORK registration):
 *    -> scf_evt_post(EVT_HIST_FLUSH, NULL)  [call_number=3005, launch=FORK]
 *    -> pl_archive(ARC_TREND=200)
 *       -> scf_hist_save(ARC_TREND=200, &rec)  [SAVEF, arg1=200, launch=FORK]
 *       -> scf_hist_load(ARC_AUDIT=202, audit_buf)  [LOADF, arg1=202, RETURN-USE=>WRITE]
 *          *(int *)loaded_rec = 0;  [write to returned pointer => WRITE classification]
 *       -> scf_cmdq_save(Q_CMD=12)  [SAVEQ, arg1=12]
 *
 * ============================================================================ */

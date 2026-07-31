/*
 * proc_boiler/bo_combust.c — Combustion control and feedwater regulation.
 * Synthetic SCADA test process for deep call chains and call-site selection.
 *
 * GROUND TRUTH:
 * path      : main -> scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)bo_on_scan) -> bo_on_scan -> scf_evt_post(EVT_SCAN_CYCLE) -> bo_stage1(PT_MOTOR_TEMP) -> bo_stage2 -> bo_stage3 -> bo_stage4 -> bo_stage5 -> bo_stage6 -> scf_tag_write
 * api       : scf_tag_write  type=WRITEF  launch_via=EVENT
 * arg 2     : PT_MOTOR_TEMP = 0x1005
 * call_num  : 3001 (EVT_SCAN_CYCLE via scf_evt_post in bo_on_scan)
 *
 * path      : main -> scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)bo_on_scan) -> bo_on_scan -> bo_stage1 -> bo_stage2 -> bo_stage3 -> scf_tag_read
 * api       : scf_tag_read   type=READF   launch_via=EVENT
 * arg 2     : PT_PRESSURE = 0x1006
 *
 * path      : main -> bo_init -> bo_get_ctx(PT_MOTOR_TEMP) -> scf_tag_open [CONSIDER THIS CALL variant]
 * api       : scf_tag_open   type=OPENF   launch_via=MAIN
 * arg 2     : PT_MOTOR_TEMP = 0x1005
 *
 * path      : main -> scf_task_fork(TASK_HIST,(TaskEntry)bo_combust_task) -> bo_combust_task -> scf_hist_save
 * api       : scf_hist_save  type=SAVEF   launch_via=FORK
 * arg 1     : ARC_TREND = 200
 *
 * path      : main -> scf_task_fork(TASK_HIST,(TaskEntry)bo_combust_task) -> bo_combust_task -> scf_evt_post(EVT_HIST_FLUSH)
 * api       : scf_evt_post   type=EVENT   launch_via=FORK
 * call_num  : 3005 (EVT_HIST_FLUSH)
 */

#include <string.h>
#include <math.h>
#include "bo_app.h"

/* ============================================================
 * Globals written/managed by bo_combust.c
 * ============================================================ */
TagCtx bo_ctx_motor;
TagCtx bo_ctx_pressure;
TagCtx bo_ctx_feedwater;

/* ============================================================
 * Static process state machines and accumulators
 * ============================================================ */

/* Burner sequencing state machine */
static int burner_stage = 0;
static int ignition_countdown = 0;
static int flame_detect_samples = 0;

/* Air/fuel ratio trim loop */
static double af_error_integral = 0.0;
static double af_error_last = 0.0;
static int af_trim_counts = 0;

/* O2/CO feedback compensation */
static double o2_setpoint = 3.5;      /* % O2 target */
static double o2_measured = 3.2;
static double co_measured = 0.0;      /* ppm */
static int o2_trim_step = 0;

/* Drum-level 3-element control */
static double drum_level = 50.0;      /* % */
static double drum_level_sp = 50.0;   /* setpoint */
static double steam_demand = 0.0;     /* inferred from pressure derivative */
static double feedwater_valve_pos = 30;
static int fw_control_mode = 0;       /* 0=wide range, 1=narrow, 2=proportional */

/* Flame scanner and burner supervision */
static int flame_present = 0;
static int flame_supervision_fault = 0;
static int furnace_purge_count = 0;
static int mft_timer = 0;             /* minimum fan time in seconds */

/* State for temperature and pressure tracking */
static int last_motor_temp = 0;
static int last_pressure = 0;
static int scan_count = 0;

/* Historian buffering */
#define HIST_BUFFER_SIZE 16
static struct {
    int point_id;
    int value;
    int timestamp;
} hist_buffer[HIST_BUFFER_SIZE];
static int hist_write_idx = 0;

/* ============================================================
 * Static Helper Functions
 * ============================================================ */

/* Compute air/fuel trim correction based on O2 feedback */
static int trim_air_fuel_ratio(double o2_error, int sample_count) {
    const double kp = 0.15;
    const double ki = 0.02;
    const double kd = 0.08;

    af_error_integral += o2_error;
    if (af_error_integral > 2.0) af_error_integral = 2.0;
    if (af_error_integral < -2.0) af_error_integral = -2.0;

    double derivative = (o2_error - af_error_last) / (sample_count > 0 ? sample_count : 1);
    af_error_last = o2_error;

    double correction = kp * o2_error + ki * af_error_integral + kd * derivative;
    return (int)(correction * 100);
}

/* Evaluate CO formation and stoichiometry */
static int evaluate_co_formation(double o2_pct, double co_ppm) {
    if (co_ppm > 100.0 && o2_pct < 2.0) {
        return 1;  /* Combustion efficiency warning */
    }
    if (co_ppm > 200.0) {
        return 2;  /* Critical incomplete combustion */
    }
    return 0;
}

/* 3-element drum-level control: combines level, steam demand, feedwater */
static double compute_3element_fw_demand(double level, double level_sp,
                                         double steam_flow, double fw_flow_actual) {
    const double gain_level = 0.5;
    const double gain_steam = 1.2;
    const double gain_offset = 5.0;

    double level_error = level_sp - level;
    double steam_imbalance = steam_flow - fw_flow_actual;

    double demanded = gain_level * level_error
                    + gain_steam * steam_imbalance
                    + gain_offset;

    if (demanded > 100.0) demanded = 100.0;
    if (demanded < 0.0) demanded = 0.0;

    return demanded;
}

/* Burner sequencing logic (warm-up, ramp, stabilize) */
static int step_burner_sequence(int flame_detected, int air_pressure_ok) {
    switch (burner_stage) {
        case 0:  /* Idle */
            if (air_pressure_ok) {
                burner_stage = 1;
                furnace_purge_count = 10;
            }
            break;
        case 1:  /* Purge sequence (10 cycles) */
            furnace_purge_count--;
            if (furnace_purge_count <= 0) {
                burner_stage = 2;
                ignition_countdown = 3;  /* 3-cycle ignition attempt */
            }
            break;
        case 2:  /* Ignition attempt */
            ignition_countdown--;
            if (flame_detected) {
                burner_stage = 3;
                flame_detect_samples = 0;
            } else if (ignition_countdown <= 0) {
                burner_stage = 0;  /* Retry from purge */
            }
            break;
        case 3:  /* Flame established, stabilizing */
            flame_detect_samples++;
            if (flame_detect_samples > 20) {
                burner_stage = 4;
            }
            break;
        case 4:  /* Normal operation */
            if (!flame_detected) {
                burner_stage = 0;  /* Loss of flame → shutdown sequence */
            }
            break;
    }
    return burner_stage;
}

/* Flame-scanner UV/IR validation with hysteresis */
static int detect_flame(int uv_signal, int ir_signal, int pressure) {
    const int uv_threshold = 100;
    const int ir_threshold = 50;
    const int min_pressure = 20;

    if (pressure < min_pressure) {
        return 0;  /* No fuel pressure → no flame */
    }

    if (uv_signal > uv_threshold || ir_signal > ir_threshold) {
        flame_detect_samples++;
        if (flame_detect_samples > 3) {
            return 1;
        }
    } else {
        flame_detect_samples = 0;
    }

    return 0;
}

/* Minimum fan time (MFT) logic before fuel ramp */
static void enforce_mft(int mft_setpoint_sec, int enable) {
    if (enable && mft_timer < mft_setpoint_sec) {
        mft_timer++;
    }
    if (!enable) {
        mft_timer = 0;
    }
}

/* Furnace temperature trend with ramp rate limiting */
static int limit_furnace_temp_ramp(int target_temp, int current_temp, int max_ramp_per_scan) {
    int delta = target_temp - current_temp;
    if (delta > max_ramp_per_scan) {
        return current_temp + max_ramp_per_scan;
    }
    if (delta < -max_ramp_per_scan) {
        return current_temp - max_ramp_per_scan;
    }
    return target_temp;
}

/* Proportional-integral steam temperature control */
static int control_steam_temperature(int steam_temp, int steam_temp_sp,
                                     int spray_valve_pos) {
    const int max_delta = 50;
    int error = steam_temp_sp - steam_temp;

    int new_spray_pos = spray_valve_pos + (error / 10);
    if (new_spray_pos > 100) new_spray_pos = 100;
    if (new_spray_pos < 0) new_spray_pos = 0;

    return new_spray_pos;
}

/* Check permissives before allowing fuel ramp */
static int check_fuel_permissives(int air_ok, int water_ok, int fuel_pressure_ok) {
    return (air_ok && water_ok && fuel_pressure_ok) ? 1 : 0;
}

/* Adaptive setpoint tracking for load changes */
static double track_load_setpoint(double measured_level, double current_sp,
                                  double load_rate) {
    const double max_sp_ramp = 2.0;
    double demand_sp = measured_level + load_rate;

    double delta = demand_sp - current_sp;
    if (delta > max_sp_ramp) {
        return current_sp + max_sp_ramp;
    }
    if (delta < -max_sp_ramp) {
        return current_sp - max_sp_ramp;
    }
    return demand_sp;
}

/* ============================================================
 * bo_get_ctx — Tag context getter with call-site selection.
 * Multiple scf_tag_open calls; the real one marked CONSIDER THIS CALL.
 * ============================================================ */
void *bo_get_ctx(int fno) {
    TagCtx *selected_ctx = &bo_ctx_motor;

    /* Exploratory open (not used) */
    scf_tag_open(&bo_ctx_feedwater, PT_PUMP_SPEED, SCF_READ_LOCK);

    /* Real open for the requested point ID — MARKED */
    /*CONSIDER THIS CALL*/
    scf_tag_open(selected_ctx, fno, SCF_READ_LOCK);

    /* Fallback open (also not used) */
    scf_tag_open(&bo_ctx_pressure, PT_TANK_LEVEL, SCF_NO_LOCK);

    return (void *)selected_ctx;
}

/* ============================================================
 * Deep call chain: stage1 through stage6
 * The pid parameter flows unchanged through all 6 functions
 * so backward tracing resolves arg2=PT_MOTOR_TEMP across the chain.
 * ============================================================ */

int bo_stage2(int pid);

int bo_stage1(int pid) {
    /* Validate input stage, prepare for next */
    if (pid < 0 || pid > 0x10000) {
        return -1;
    }
    return bo_stage2(pid);
}

int bo_stage2(int pid) {
    /* Pre-filter stage: pass the point id through UNCHANGED so the
     * backward trace stays clean across the entire 6-stage chain. */
    return bo_stage3(pid);
}

int bo_stage3(int pid) {
    /* Read pressure feedback for cross-check */
    int buf[4] = {0};
    scf_tag_read(&bo_ctx_pressure, PT_PRESSURE, buf);

    int pressure_value = buf[0];
    if (pressure_value > 500) {
        /* High pressure trim needed */
    }

    return bo_stage4(pid);
}

int bo_stage4(int pid) {
    /* Validation stage: ensure PID is still valid */
    if (pid != PT_MOTOR_TEMP) {
        /* Mismatch check */
        return -2;
    }
    return bo_stage5(pid);
}

int bo_stage5(int pid) {
    /* Pre-compute compensation */
    int compensation = af_trim_counts;
    return bo_stage6(pid);
}

int bo_stage6(int pid) {
    /* Final stage: write the computed value */
    int motor_temp_setpoint = 450 + (af_trim_counts / 10);
    scf_tag_write(&bo_ctx_motor, pid, motor_temp_setpoint);

    return motor_temp_setpoint;
}

/* ============================================================
 * Main scan event handler
 * ============================================================ */
void bo_on_scan(int evt, void *data) {
    int alarm_code = 0;
    int uv_signal = 150;    /* simulated UV scanner reading */
    int ir_signal = 80;     /* simulated IR scanner reading */
    int air_pressure = 45;  /* psi */
    int fuel_pressure = 35; /* psi */
    int water_level = 52;   /* % of drum */
    int steam_flow = 450;   /* klbs/hr */
    int fw_flow = 442;      /* klbs/hr */
    int steam_temp = 725;   /* degF */
    int steam_temp_sp = 730;
    int spray_pos = 15;

    /* Post the event to establish call_number in tracer */
    scf_evt_post(EVT_SCAN_CYCLE, data);

    scan_count++;

    /* ---- Flame detection and burner sequencing ---- */
    flame_present = detect_flame(uv_signal, ir_signal, fuel_pressure);

    int fuel_permissive = check_fuel_permissives(
        (air_pressure > 30 ? 1 : 0),
        (water_level > 30 ? 1 : 0),
        (fuel_pressure > 20 ? 1 : 0)
    );

    step_burner_sequence(flame_present, fuel_permissive);

    if (flame_present == 0 && burner_stage >= 3) {
        /* Loss of flame during normal operation */
        alarm_code = ALM_OVERTEMP;
    }

    /* ---- MFT (minimum fan time) enforcement ---- */
    enforce_mft(5, (air_pressure > 40 ? 1 : 0));

    /* ---- Air/fuel trim loop ---- */
    double o2_error = o2_setpoint - o2_measured;
    int trim_correction = trim_air_fuel_ratio(o2_error, scan_count);
    af_trim_counts += trim_correction;

    if (af_trim_counts > 500) af_trim_counts = 500;
    if (af_trim_counts < -500) af_trim_counts = -500;

    /* ---- CO formation check ---- */
    int co_status = evaluate_co_formation(o2_measured, co_measured);
    if (co_status == 2) {
        alarm_code = ALM_OVERTEMP;  /* Severe combustion problem */
    }

    /* ---- Drum-level 3-element control ---- */
    steam_demand = steam_flow;
    double fw_demand = compute_3element_fw_demand(water_level, drum_level_sp,
                                                  steam_demand, fw_flow);
    feedwater_valve_pos = fw_demand;

    /* Adjust drum level setpoint based on load trend */
    drum_level_sp = track_load_setpoint(water_level, drum_level_sp, 2.0);

    /* ---- Steam temperature control (spray valve) ---- */
    spray_pos = control_steam_temperature(steam_temp, steam_temp_sp, spray_pos);

    /* ---- Deep call chain for motor temperature feedback ---- */
    bo_stage1(PT_MOTOR_TEMP);

    /* ---- Update historian buffer ---- */
    if (hist_write_idx < HIST_BUFFER_SIZE) {
        hist_buffer[hist_write_idx].point_id = PT_MOTOR_TEMP;
        hist_buffer[hist_write_idx].value = last_motor_temp;
        hist_buffer[hist_write_idx].timestamp = scan_count;
        hist_write_idx++;
    }

    /* ---- Raise alarm if needed ---- */
    if (alarm_code != 0) {
        RAISE_ALARM(alarm_code);
    }
}

/* ============================================================
 * Historian and background task
 * ============================================================ */
void bo_combust_task(int task_id) {
    int i;

    /* Flush accumulated historian records */
    for (i = 0; i < hist_write_idx && i < HIST_BUFFER_SIZE; i++) {
        HistRec rec;
        rec.archive_id = ARC_TREND;
        rec.stamp = hist_buffer[i].timestamp;
        rec.value = hist_buffer[i].value;

        scf_hist_save(ARC_TREND, &rec);
    }

    /* Reset buffer for next cycle */
    hist_write_idx = 0;

    /* Post flush completion event */
    scf_evt_post(EVT_HIST_FLUSH, NULL);
}

/* ============================================================
 * Additional Support Functions (realistic domain logic)
 * ============================================================ */

/* Update O2 and CO measurements from gas analysis */
static void update_emissions_analysis(void) {
    /* Simulated analyzer readings, subject to lag */
    static int analyzer_delay = 0;
    analyzer_delay++;

    if (analyzer_delay > 5) {
        o2_measured = 3.2 + (af_trim_counts / 500.0);
        co_measured = 50.0 - (o2_measured * 15.0);
        if (co_measured < 0.0) co_measured = 0.0;
        analyzer_delay = 0;
    }
}

/* Secondary air damper position control */
static int control_secondary_air(int primary_air_pos, int load_percent) {
    int secondary_pos = 20 + (load_percent / 2);
    if (secondary_pos > 80) secondary_pos = 80;
    return secondary_pos;
}

/* Gas and fuel oil switchover logic */
static int select_fuel_source(int gas_pressure, int oil_temp, int oil_viscosity) {
    if (gas_pressure > 50 && oil_temp < 140) {
        return 1;  /* Prefer gas */
    }
    if (oil_temp > 180 && oil_viscosity < 30) {
        return 2;  /* Switch to oil */
    }
    return 0;  /* Standby */
}

/* Atomizing steam pressure control for oil burners */
static int adjust_atomizing_steam(int oil_flow_setpoint, int steam_pressure) {
    const int min_atom_steam = 60;  /* psi minimum */
    int required_steam = min_atom_steam + (oil_flow_setpoint / 5);

    if (required_steam > 200) required_steam = 200;
    return required_steam;
}

/* Fuel control valve ramp rate limiter */
static int fuel_valve_ramp(int target_pos, int current_pos, int scan_interval_ms) {
    int max_rate = 2;  /* % per scan at 500ms */
    int delta = target_pos - current_pos;

    if (delta > max_rate) return current_pos + max_rate;
    if (delta < -max_rate) return current_pos - max_rate;
    return target_pos;
}

/* Furnace pressure control (balancing forced draft and induced draft) */
static int balance_furnace_draft(int fd_fan_speed, int id_fan_speed,
                                 int target_furnace_press) {
    int delta = target_furnace_press - (fd_fan_speed - id_fan_speed);
    int fd_adjustment = delta / 2;
    return fd_fan_speed + fd_adjustment;
}

/* Oxygen trim feedback filter with exponential smoothing */
static int smooth_o2_feedback(int raw_o2_signal, int smoothing_factor) {
    static int filtered_o2 = 0;
    if (filtered_o2 == 0) filtered_o2 = raw_o2_signal;

    filtered_o2 = (filtered_o2 * (100 - smoothing_factor) + raw_o2_signal * smoothing_factor) / 100;
    return filtered_o2;
}

/* Cross-limit check: ensure steam pressure doesn't exceed fuel rate */
static int apply_cross_limit(int fuel_rate, int steam_pressure) {
    int fuel_limit = (steam_pressure / 10) + 20;
    if (fuel_rate > fuel_limit) {
        return fuel_limit;
    }
    return fuel_rate;
}

/* Combustion instability detection (flame flutter, oscillation) */
static int detect_combustion_instability(int flame_signal_current,
                                         int flame_signal_history) {
    int delta = flame_signal_current - flame_signal_history;
    if (delta > 40 || delta < -40) {
        return 1;  /* Oscillation detected */
    }
    return 0;
}

/* Acid dew point protection: maintain exhaust temp above saturation */
static int monitor_acid_dew_point(int exhaust_temp, int sulfur_ppm) {
    /* Simplified: ADP ~250-300°F with high sulfur */
    int adp_setpoint = 300 + (sulfur_ppm / 100);

    if (exhaust_temp < adp_setpoint) {
        return 1;  /* Heat recovery bypass needed */
    }
    return 0;
}

/* NOx trim: secondary air staging or selective catalytic reduction */
static int nox_trim_control(int nox_measured, int nox_setpoint, int sa_damper_pos) {
    int error = nox_setpoint - nox_measured;
    int new_damper = sa_damper_pos - (error / 20);

    if (new_damper > 90) new_damper = 90;
    if (new_damper < 10) new_damper = 10;
    return new_damper;
}

/* Turndown ratio enforcement: prevent stable operation below minimum load */
static int enforce_turndown_limit(int load_percent, int minimum_turndown) {
    if (load_percent < minimum_turndown && load_percent > 0) {
        return minimum_turndown;  /* Snap to minimum stable load */
    }
    return load_percent;
}

/* Boiler response model: predict required changes for anticipated load */
static int anticipatory_fuel_ramp(int load_rate, int current_fuel, int inertia) {
    int predicted_demand = current_fuel + (load_rate * inertia / 10);
    return predicted_demand;
}

/* Soot blowing sequence trigger (time-based or opacity-based) */
static int schedule_soot_blow(int elapsed_hours, int last_blow_hours, int blow_interval) {
    if ((elapsed_hours - last_blow_hours) >= blow_interval) {
        return 1;  /* Initiate soot blowing */
    }
    return 0;
}

/* Air heater bypass control for cold startup */
static int control_air_heater_bypass(int ambient_temp, int air_heater_inlet) {
    if (ambient_temp < 30 && air_heater_inlet < 150) {
        return 80;  /* Bypass 80% until warm */
    }
    if (air_heater_inlet > 200) {
        return 10;  /* Minimal bypass, use heater */
    }
    return 50;  /* Balanced operation */
}

/* Flue gas recirculation (FGR) damper for NOx reduction */
static int modulate_fgr_damper(int nox_level, int co_level, int furnace_temp) {
    int fgr_pos = 0;

    if (nox_level > 80 && furnace_temp > 2400) {
        fgr_pos = 40;  /* Increase FGR to cool and reduce NOx */
    }

    if (co_level > 100) {
        fgr_pos = 10;  /* Reduce FGR to improve combustion */
    }

    return fgr_pos;
}

/* Load profile smooth-out: prevent abrupt setpoint changes */
static int smooth_load_profile(int setpoint, int previous_sp, int smoothing) {
    int delta = setpoint - previous_sp;
    int max_change = smoothing / 10;

    if (delta > max_change) return previous_sp + max_change;
    if (delta < -max_change) return previous_sp - max_change;
    return setpoint;
}

/* Superheater temperature limit: protect against overtemp */
static int clamp_superheater_temp(int measured_temp, int max_temp) {
    if (measured_temp > max_temp) {
        return max_temp;  /* Trigger desuperheater spray */
    }
    return measured_temp;
}

/* Reheater outlet temp control: balance main steam with reheater steam */
static int control_reheater_outlet(int main_steam_temp, int reheat_inlet_temp,
                                   int spray_pos) {
    int temp_error = (main_steam_temp - 50) - reheat_inlet_temp;
    int new_spray = spray_pos + (temp_error / 15);

    if (new_spray > 100) new_spray = 100;
    if (new_spray < 0) new_spray = 0;
    return new_spray;
}

/* Boiler load demand inference from steam pressure derivative */
static int infer_steam_demand(int current_press, int previous_press, int trend) {
    int press_delta = current_press - previous_press;
    if (press_delta > 10) return 80;      /* Rising pressure → more steam demand */
    if (press_delta < -10) return 40;     /* Falling pressure → less demand */
    return trend;                         /* Stable, maintain current trend */
}

/* Fuel flow measurement with fault detection */
static int validate_fuel_flow(int measured_flow, int demanded_flow) {
    int deviation = measured_flow - demanded_flow;

    if (deviation > 50 || deviation < -50) {
        return -1;  /* Fault: flow controller not responding */
    }
    return measured_flow;
}

/* Overfire air damper for emission control */
static int position_overfire_air(int burner_load, int nox_trim) {
    int ofa_pos = (burner_load / 3) + nox_trim;
    if (ofa_pos > 100) ofa_pos = 100;
    if (ofa_pos < 0) ofa_pos = 0;
    return ofa_pos;
}

/* Monitoring routine for bearing temperatures (motor, fan, pump) */
static int monitor_bearing_temperatures(int motor_brg_temp, int fan_brg_temp,
                                        int pump_brg_temp) {
    const int brg_alarm_threshold = 180;  /* degF */

    if (motor_brg_temp > brg_alarm_threshold) {
        return ALM_OVERTEMP;
    }
    if (fan_brg_temp > brg_alarm_threshold) {
        return ALM_OVERTEMP;
    }
    if (pump_brg_temp > brg_alarm_threshold) {
        return ALM_OVERTEMP;
    }
    return 0;
}

/* ============================================================
 * Expanded domain-specific functions for realistic control logic
 * ============================================================ */

/* Load demand estimator based on steam pressure and temperature trends */
static int estimate_boiler_load_demand(int steam_pressure, int previous_pressure,
                                       int steam_temp, int previous_temp,
                                       int drum_level, int previous_level) {
    int load = 50;  /* Start at 50% base load */

    /* Pressure-based load estimation */
    if (steam_pressure > previous_pressure + 20) {
        load += (steam_pressure - previous_pressure) / 2;  /* Rising pressure suggests higher demand */
    }

    /* Temperature trend adjustment */
    if (steam_temp > previous_temp + 5) {
        load += 5;  /* Rising temperature could indicate increased burn rate */
    }

    /* Drum level influence */
    if (drum_level < previous_level - 2) {
        load += 10;  /* Falling level could indicate steam demand exceeding feedwater */
    }

    if (load > 100) load = 100;
    if (load < 20) load = 20;

    return load;
}

/* Proportional-derivative furnace temperature controller */
static int furnace_temp_control(int measured_temp, int setpoint,
                                int last_measured_temp, int scan_interval) {
    const double kp = 2.0;
    const double kd = 1.5;

    int error = setpoint - measured_temp;
    int derivative = (measured_temp - last_measured_temp) / scan_interval;

    int correction = (int)(kp * error + kd * derivative);

    return correction;
}

/* Integrated flue gas analysis (O2, CO, NOx, SO2 cross-correlation) */
static void analyze_flue_gas_composition(double o2_pct, double co_ppm,
                                         double nox_ppm, double so2_ppm,
                                         int *combustion_quality, int *emission_risk) {
    *combustion_quality = 100;  /* Default good */
    *emission_risk = 0;

    /* O2 too high = excess air, efficiency loss */
    if (o2_pct > 4.5) {
        *combustion_quality -= (int)((o2_pct - 4.0) * 5);
    }

    /* O2 too low = incomplete combustion */
    if (o2_pct < 2.5) {
        *combustion_quality -= 20;
        if (co_ppm > 100) *emission_risk = 1;
    }

    /* High CO + low O2 = serious incomplete combustion */
    if (co_ppm > 150 && o2_pct < 3.0) {
        *combustion_quality -= 40;
        *emission_risk = 2;
    }

    /* NOx formation risk (increases with high temp and O2) */
    if (nox_ppm > 150 && o2_pct > 3.5) {
        *emission_risk = 1;
    }

    if (*combustion_quality < 0) *combustion_quality = 0;
}

/* Coordinated control of inlet guide vanes for fan speed modulation */
static int modulate_fan_igv(int fan_speed_demand, int furnace_pressure,
                            int air_flow_required) {
    int igv_pos = 30;  /* Base position */

    if (fan_speed_demand > 70 && furnace_pressure < -50) {
        igv_pos = 90;  /* Open IGV for high volume */
    } else if (fan_speed_demand < 40 && furnace_pressure > -20) {
        igv_pos = 10;  /* Close IGV for low volume */
    } else {
        igv_pos = 40 + (fan_speed_demand / 2);
    }

    return igv_pos;
}

/* Thermal efficiency calculator (using classic boiler efficiency formula) */
static double calculate_boiler_efficiency(double steam_enthalpy_out,
                                          double feedwater_enthalpy_in,
                                          double fuel_heat_input_btu_hr,
                                          double steam_flow_lb_hr) {
    double useful_heat = steam_flow_lb_hr * (steam_enthalpy_out - feedwater_enthalpy_in);

    if (fuel_heat_input_btu_hr <= 0) return 0.0;

    double efficiency = (useful_heat / fuel_heat_input_btu_hr) * 100.0;

    if (efficiency > 100.0) efficiency = 100.0;
    if (efficiency < 50.0) efficiency = 50.0;

    return efficiency;
}

/* Fan power demand estimation (cube law relationship) */
static double estimate_fan_power(int fan_speed_rpm, double airflow_percent) {
    const double base_power = 500.0;  /* kW at base speed */
    const double base_speed = 1800.0; /* RPM reference */

    double speed_ratio = fan_speed_rpm / base_speed;
    double power_demand = base_power * airflow_percent * speed_ratio * speed_ratio * speed_ratio;

    return power_demand;
}

/* Soot accumulation model for optimal soot blowing timing */
static int calculate_soot_blow_timing(int hours_since_last_blow,
                                      int boiler_load_percent,
                                      int flue_gas_temp) {
    int blow_interval_base = 24;  /* Hours */

    /* Higher load = faster soot accumulation */
    if (boiler_load_percent > 80) {
        blow_interval_base = 16;
    } else if (boiler_load_percent < 50) {
        blow_interval_base = 36;
    }

    /* Higher exhaust temp = better soot burnoff, less frequent blowing needed */
    if (flue_gas_temp > 350) {
        blow_interval_base = (blow_interval_base * 120) / 100;
    } else if (flue_gas_temp < 300) {
        blow_interval_base = (blow_interval_base * 80) / 100;
    }

    if (hours_since_last_blow >= blow_interval_base) {
        return 1;  /* Time to blow soot */
    }
    return 0;
}

/* Tube bank differential pressure monitoring (fouling detection) */
static int monitor_tube_bank_fouling(int bank_dp_current, int bank_dp_baseline) {
    int dp_increase = bank_dp_current - bank_dp_baseline;

    if (dp_increase > 5) {
        return 1;  /* Minor fouling detected */
    }
    if (dp_increase > 12) {
        return 2;  /* Significant fouling, schedule blowing */
    }
    if (dp_increase > 20) {
        return 3;  /* Severe fouling, consider emergency action */
    }
    return 0;
}

/* Cascade master-slave coordination for pressure control */
static int cascade_pressure_master_logic(int header_pressure, int header_sp,
                                         int valve_position, int fuel_flow) {
    int error = header_sp - header_pressure;

    int fuel_demand = fuel_flow + (error / 10);

    if (fuel_demand > 100) fuel_demand = 100;
    if (fuel_demand < 10) fuel_demand = 10;

    return fuel_demand;
}

/* Compute oxygen trim bias curve for load linearization */
static double oxygen_trim_bias_curve(int load_percent) {
    double bias = 0.0;

    /* Empirical curve to match stoichiometric excess air across load range */
    if (load_percent < 20) {
        bias = 0.8;
    } else if (load_percent < 40) {
        bias = 0.6 + (load_percent - 20) * 0.01;
    } else if (load_percent < 70) {
        bias = 0.4 + (load_percent - 40) * 0.005;
    } else {
        bias = 0.3;
    }

    return bias;
}

/* Air register sequencing for optimal mixing throughout load range */
static void sequence_air_registers(int total_air_percent, int *primary_pos,
                                   int *secondary_pos, int *tertiary_pos) {
    *primary_pos = 20 + (total_air_percent / 3);
    *secondary_pos = 25 + (total_air_percent / 4);
    *tertiary_pos = 15 + (total_air_percent / 5);

    if (*primary_pos > 90) *primary_pos = 90;
    if (*secondary_pos > 85) *secondary_pos = 85;
    if (*tertiary_pos > 75) *tertiary_pos = 75;
}

/* Reheater outlet temperature control with spray valve feedback */
static int reheat_outlet_control(int reheat_outlet_temp, int reheat_outlet_sp,
                                 int spray_position, int main_steam_temp) {
    int temp_error = reheat_outlet_sp - reheat_outlet_temp;

    /* Proportional + derivative action */
    int new_spray = spray_position + (temp_error / 12);

    /* Cross-limit with main steam temperature for protection */
    if (main_steam_temp > 750) {
        new_spray -= 10;  /* Reduce spray somewhat to protect superheater */
    }

    if (new_spray > 100) new_spray = 100;
    if (new_spray < 0) new_spray = 0;

    return new_spray;
}

/* Air heater exit temperature control and bypass damper modulation */
static int control_air_heater_temperature(int ah_outlet_temp, int ah_outlet_sp,
                                          int ah_bypass_damper_pos) {
    int temp_error = ah_outlet_sp - ah_outlet_temp;

    int new_bypass = ah_bypass_damper_pos - (temp_error / 20);

    /* Safety limit: don't freeze acid dew point protection */
    if (ah_outlet_temp < 250) {
        new_bypass = 100;  /* Full bypass */
    }

    if (new_bypass > 100) new_bypass = 100;
    if (new_bypass < 0) new_bypass = 0;

    return new_bypass;
}

/* Throttle pressure governor coordination */
static int coordinate_throttle_pressure_with_load(int load_demand, int header_pressure,
                                                   int header_sp, int current_throttle_pos) {
    int pressure_correction = (header_sp - header_pressure) / 5;

    int load_bias = (load_demand - 50) / 4;

    int new_throttle = current_throttle_pos + pressure_correction + load_bias;

    if (new_throttle > 100) new_throttle = 100;
    if (new_throttle < 5) new_throttle = 5;

    return new_throttle;
}

/* Blowdown valve cycling for continuous sludge removal */
static int manage_continuous_blowdown(int drum_level, int drum_level_sp,
                                      int dissolved_solids_ppm, int max_solids_ppm) {
    int blow_percent = 0;

    if (dissolved_solids_ppm > (max_solids_ppm * 80 / 100)) {
        blow_percent = 10;  /* Increase blowdown */
    }

    if (dissolved_solids_ppm > max_solids_ppm) {
        blow_percent = 25;  /* More aggressive blowdown */
    }

    /* Adjust for level control interaction */
    if (drum_level > (drum_level_sp + 3)) {
        blow_percent += 5;
    }

    if (blow_percent > 50) blow_percent = 50;

    return blow_percent;
}

/* Emergency tramp iron detection from magnetic flux variation */
static int detect_tramp_iron_in_fuel(int fuel_flow_signal_stability,
                                     int magnetic_sensor_output) {
    if (magnetic_sensor_output > 200) {
        return 1;  /* Ferrous material detected in fuel */
    }
    if (fuel_flow_signal_stability < 30) {
        return 2;  /* Fuel flow instability suggesting blockage */
    }
    return 0;
}

/* Predictive maintenance: bearing wear monitoring via vibration */
static int assess_bearing_wear_status(int vibration_frequency_hz,
                                      int vibration_amplitude_mm) {
    if (vibration_frequency_hz > 10000 && vibration_amplitude_mm > 1.2) {
        return 2;  /* High-frequency, high-amplitude: bearing wear */
    }
    if (vibration_amplitude_mm > 0.8) {
        return 1;  /* Elevated vibration: monitor closely */
    }
    return 0;  /* Normal */
}

/* Compute and validate flame scanner UV/IR signal ratio */
static int validate_flame_scanner_signal(int uv_raw, int ir_raw,
                                         int *signal_quality) {
    *signal_quality = 100;

    if (uv_raw < 50 && ir_raw < 30) {
        *signal_quality = 10;
        return 0;  /* Insufficient signal */
    }

    /* Sanity check ratio to avoid false positives from stray light */
    if (uv_raw > 0) {
        int ratio = (ir_raw * 100) / uv_raw;
        if (ratio > 150 || ratio < 20) {
            *signal_quality = 40;  /* Signal ratio out of normal range */
        }
    }

    return (uv_raw > 100 || ir_raw > 60) ? 1 : 0;
}

/* Steam/water cycle heat balance check */
static double verify_energy_balance(double fuel_input_mmbtu_hr,
                                    double steam_output_mmbtu_hr,
                                    double losses_estimated_percent) {
    double acceptable_balance = fuel_input_mmbtu_hr * (1.0 - losses_estimated_percent / 100.0);

    /* Return margin to efficiency envelope */
    if (fuel_input_mmbtu_hr <= 0) return 0.0;

    double balance_margin = (acceptable_balance - steam_output_mmbtu_hr) / fuel_input_mmbtu_hr * 100.0;
    return balance_margin;
}

/* Compute integrated performance metric for operator feedback */
static int compute_boiler_performance_index(double thermal_efficiency,
                                            int combustion_quality, int emission_risk) {
    int efficiency_score = (int)(thermal_efficiency / 0.88 * 30);  /* Normalize to 30 pts */
    int combustion_score = (combustion_quality / 100) * 40;
    int emission_score = (3 - emission_risk) * 30;  /* 0-risk=30, 2-risk=30, high-risk=lower */

    if (efficiency_score > 30) efficiency_score = 30;
    if (combustion_score > 40) combustion_score = 40;
    if (emission_score > 30) emission_score = 30;

    return efficiency_score + combustion_score + emission_score;
}

/* Load profile smoothing with inertia model of boiler thermal mass */
static int smooth_load_demand_with_inertia(int instantaneous_demand,
                                           int last_demand, int thermal_inertia_time_s) {
    int tau = thermal_inertia_time_s / 5;  /* Convert to scan intervals */
    if (tau < 1) tau = 1;

    int new_demand = (instantaneous_demand + (last_demand * (tau - 1))) / tau;
    return new_demand;
}

/* Compute optimal fuel/steam ratio for maximum efficiency */
static double compute_optimal_fuel_steam_ratio(int boiler_type_flag,
                                               int load_percent) {
    double ratio = 1.0;

    if (boiler_type_flag == 1) {
        /* Water-tube: ~1.14-1.17 lb fuel / lb steam */
        ratio = 1.15 + (load_percent < 50 ? 0.02 : -0.01);
    } else {
        /* Fire-tube: ~1.18-1.22 */
        ratio = 1.20 + (load_percent < 50 ? 0.02 : 0.0);
    }

    return ratio;
}

/* Additional support functions for realistic diagnostics and tuning */

static void validate_sensor_health(int pt_value, int sensorid) {
    /* Cross-check sensor readings for plausibility */
    if (pt_value < -1000 || pt_value > 100000) {
        /* Out of range → sensor fault */
    }
}

static int apply_hysteresis_to_setpoint(int current_sp, int new_sp, int hysteresis) {
    /* Prevent oscillation around setpoint boundary */
    if ((new_sp - current_sp) > hysteresis) return new_sp;
    if ((current_sp - new_sp) > hysteresis) return new_sp;
    return current_sp;
}

static int compute_cascade_master_output(int primary_error, int secondary_feedback) {
    /* For cascaded control (e.g., steam pressure as master of fuel valve) */
    return 50 + (primary_error / 2) + (secondary_feedback / 10);
}

static void log_event_to_audit_trail(int event_type, int point_id, int value) {
    /* Record significant changes for compliance and diagnostics */
}

static int calculate_safe_operating_envelope(int steam_pressure, int steam_temp,
                                             int drum_level) {
    /* Verify operation within design limits */
    if (steam_pressure > 1650) return 0;  /* Over-pressure */
    if (steam_temp > 1050) return 0;      /* Over-temperature */
    if (drum_level > 80) return 0;        /* Over-level */
    if (drum_level < 20) return 0;        /* Low-level */
    return 1;                             /* Safe */
}

/* ============================================================
 * Extended PID controller implementations
 * ============================================================ */

/* Generic PID loop for adaptive tuning (feed-forward optional) */
typedef struct {
    double kp;
    double ki;
    double kd;
    double integral;
    double derivative;
    double last_error;
    int output_min;
    int output_max;
} PID_Controller;

static int execute_pid_loop(PID_Controller *pid, int setpoint, int measured_value) {
    int error = setpoint - measured_value;

    /* Proportional term */
    double p_term = pid->kp * error;

    /* Integral term with anti-windup */
    pid->integral += error;
    if (pid->integral > 100) pid->integral = 100;
    if (pid->integral < -100) pid->integral = -100;
    double i_term = pid->ki * pid->integral;

    /* Derivative term */
    pid->derivative = error - pid->last_error;
    double d_term = pid->kd * pid->derivative;
    pid->last_error = error;

    int output = (int)(p_term + i_term + d_term);

    if (output > pid->output_max) output = pid->output_max;
    if (output < pid->output_min) output = pid->output_min;

    return output;
}

/* ============================================================
 * Rate-of-change monitoring for safety
 * ============================================================ */

static int monitor_pressure_ramp_rate(int current_pressure, int previous_pressure,
                                      int max_rate_psi_per_minute) {
    /* Monitor for runaway pressure rise (blocked vent, valve malfunction) */
    int delta = current_pressure - previous_pressure;

    if (delta * 12 > max_rate_psi_per_minute) {  /* *12 = 5-sec scan to min conversion */
        return 1;  /* Over-rate detected */
    }

    return 0;
}

static int monitor_level_ramp_rate(int current_level, int previous_level,
                                   int max_rate_pct_per_minute) {
    int delta_pct = current_level - previous_level;

    if (delta_pct * 12 > max_rate_pct_per_minute) {
        return 1;  /* Level change too fast */
    }

    return 0;
}

/* ============================================================
 * State machine support for multi-step procedures
 * ============================================================ */

static int startup_sequence_state_machine(int current_state, int air_pressure,
                                          int fuel_pressure, int ignition_ok) {
    switch (current_state) {
        case 0:  /* Idle */
            if (air_pressure > 35) {
                return 1;  /* Advance to purge */
            }
            break;

        case 1:  /* Furnace purge (ensure no fuel vapor) */
            return 2;  /* After 5-10 scans */

        case 2:  /* Pre-ignition air flow */
            if (fuel_pressure > 25 && ignition_ok) {
                return 3;
            }
            break;

        case 3:  /* Ignition enable */
            return 4;  /* After ignition spark for 3 sec */

        case 4:  /* Pilot light verification */
            return 5;  /* If flame proven */

        case 5:  /* Main fuel ramp (slow increase) */
            return 6;  /* If stable over 30 sec */

        case 6:  /* Normal operation at setpoint */
            if (air_pressure < 30 || fuel_pressure < 20) {
                return 0;  /* Back to idle on fault */
            }
            break;

        default:
            return 0;
    }

    return current_state;
}

static int shutdown_sequence_state_machine(int current_state, int current_fuel_pos) {
    switch (current_state) {
        case 0:  /* Operating */
            if (current_fuel_pos > 5) {
                return 1;  /* Start fuel ramp down */
            }
            break;

        case 1:  /* Fuel ramp down (from current to 0) */
            if (current_fuel_pos <= 5) {
                return 2;  /* Proceed to purge after fuel off */
            }
            break;

        case 2:  /* Post-flame air purge (remove any fuel vapor) */
            return 3;  /* After 20-30 scans */

        case 3:  /* All dampers closed, fans off */
            return 4;  /* Safe to stop */

        case 4:  /* Idle state */
            break;

        default:
            return 0;
    }

    return current_state;
}

/* ============================================================
 * Coordination of interlock logic
 * ============================================================ */

static int evaluate_fuel_ramp_interlocks(int air_pressure_ok, int water_ok,
                                         int fuel_pressure_ok, int furnace_purged,
                                         int flame_proven) {
    /* All must be true to allow fuel increase */
    if (!air_pressure_ok) return 0;
    if (!water_ok) return 0;
    if (!fuel_pressure_ok) return 0;
    if (!furnace_purged && flame_proven == 0) return 0;  /* Purge on cold start */
    return 1;  /* All interlocks satisfied */
}

static int evaluate_high_load_permissives(int boiler_design_pressure,
                                          int current_pressure,
                                          int boiler_design_temp,
                                          int current_steam_temp) {
    /* High load only permissible if headroom exists */
    if (current_pressure > boiler_design_pressure * 0.95) {
        return 0;  /* Pressure too close to limit */
    }

    if (current_steam_temp > boiler_design_temp * 0.98) {
        return 0;  /* Temperature too close to limit */
    }

    return 1;  /* Safe to load up */
}

/* ============================================================
 * Diagnostic functions for troubleshooting
 * ============================================================ */

static int diagnose_fuel_control_valve(int valve_command, int valve_feedback,
                                       int expected_flow, int actual_flow) {
    int valve_error = valve_feedback - valve_command;

    if (valve_error > 15) {
        return 1;  /* Valve opening slower than commanded (sticking) */
    }

    if (valve_error < -15) {
        return 2;  /* Valve over-opening (hunting) */
    }

    int flow_error = actual_flow - expected_flow;
    if (flow_error < -20) {
        return 3;  /* Low flow despite good valve position (blockage?) */
    }

    return 0;  /* Valve responds normally */
}

static int diagnose_feedwater_control_valve(int fw_valve_pos, int fw_flow,
                                            int drum_level, int drum_level_sp) {
    int level_error = drum_level_sp - drum_level;

    /* Valve position should move opposite to level error */
    if (level_error > 3 && fw_valve_pos < 20) {
        return 1;  /* Valve stuck low or slow response */
    }

    if (level_error < -3 && fw_valve_pos > 80) {
        return 2;  /* Valve stuck high */
    }

    return 0;
}

static int diagnose_combustion_control(double o2_current, double o2_target,
                                       int trim_output) {
    double o2_error = o2_target - o2_current;

    if (o2_error > 0.5 && trim_output > 50) {
        return 1;  /* Oxygen setter unable to reduce excess air */
    }

    if (o2_error < -0.5 && trim_output < 50) {
        return 2;  /* Oxygen setter unable to increase air */
    }

    return 0;
}

/* ============================================================
 * Data logging and historian support functions
 * ============================================================ */

static void record_snapshot_to_historian(int snapshot_id, int *point_ids, int *values,
                                         int num_points) {
    /* Archive a multi-point snapshot at an instant in time */
    int i;
    for (i = 0; i < num_points && i < HIST_BUFFER_SIZE; i++) {
        hist_buffer[i].point_id = point_ids[i];
        hist_buffer[i].value = values[i];
    }
}

static void compute_boiler_statistics(int *samples, int sample_count,
                                      int *avg, int *min, int *max) {
    int i;
    int sum = 0;

    *min = 99999;
    *max = -99999;

    for (i = 0; i < sample_count; i++) {
        sum += samples[i];
        if (samples[i] < *min) *min = samples[i];
        if (samples[i] > *max) *max = samples[i];
    }

    *avg = (sample_count > 0) ? (sum / sample_count) : 0;
}

/* ============================================================
 * Load following and setpoint ramping
 * ============================================================ */

static int ramp_pressure_setpoint(int current_sp, int target_sp, int ramp_rate_per_scan) {
    int delta = target_sp - current_sp;

    if (delta > ramp_rate_per_scan) {
        return current_sp + ramp_rate_per_scan;
    }
    if (delta < -ramp_rate_per_scan) {
        return current_sp - ramp_rate_per_scan;
    }

    return target_sp;
}

static int ramp_load_gradually(int current_load, int target_load, int ramp_rate) {
    int delta = target_load - current_load;

    if (delta > ramp_rate) {
        return current_load + ramp_rate;
    }
    if (delta < -ramp_rate) {
        return current_load - ramp_rate;
    }

    return target_load;
}

/* ============================================================
 * Multi-burner coordination (if applicable)
 * ============================================================ */

static int sequence_burner_staging(int load_percent, int num_burners,
                                   int *burner_on_mask) {
    /* Sequence burners on/off based on load for even wear */
    int burners_required = (load_percent * num_burners) / 100;

    if (burners_required < 1) burners_required = 1;
    if (burners_required > num_burners) burners_required = num_burners;

    /* Simple rotation: turn on first N burners */
    int i;
    for (i = 0; i < num_burners; i++) {
        burner_on_mask[i] = (i < burners_required) ? 1 : 0;
    }

    return burners_required;
}

/* ============================================================
 * Advanced algorithm support
 * ============================================================ */

static double exponential_smoothing_filter(double new_value, double previous_smoothed,
                                          double alpha) {
    /* 0 < alpha < 1: smaller alpha = more smoothing */
    return alpha * new_value + (1.0 - alpha) * previous_smoothed;
}

static double low_pass_filter(double new_sample, double filtered_prev,
                             double cutoff_hz, double sample_rate_hz) {
    double tau = 1.0 / (2.0 * 3.14159 * cutoff_hz);
    double dt = 1.0 / sample_rate_hz;
    double alpha = dt / (tau + dt);

    return alpha * new_sample + (1.0 - alpha) * filtered_prev;
}

static int moving_average_filter(int *samples, int sample_count, int window_size) {
    int sum = 0;
    int i;
    int count = (sample_count < window_size) ? sample_count : window_size;

    for (i = 0; i < count; i++) {
        sum += samples[sample_count - 1 - i];
    }

    return (count > 0) ? (sum / count) : 0;
}

/* ============================================================
 * Alarm generation and escalation
 * ============================================================ */

static int generate_pressure_alarm(int current_pressure, int alarm_hi_limit,
                                   int alarm_hi_hi_limit, int *alarm_status) {
    if (current_pressure > alarm_hi_hi_limit) {
        *alarm_status = 2;  /* Critical */
        return ALM_OVERPRESSURE;
    }

    if (current_pressure > alarm_hi_limit) {
        *alarm_status = 1;  /* Warning */
        return ALM_OVERPRESSURE;
    }

    *alarm_status = 0;
    return 0;
}

static int generate_level_alarm(int current_level, int alarm_low_limit,
                                int alarm_low_low_limit, int *alarm_status) {
    if (current_level < alarm_low_low_limit) {
        *alarm_status = 2;  /* Critical low level */
        return ALM_LOWLEVEL;
    }

    if (current_level < alarm_low_limit) {
        *alarm_status = 1;  /* Warning */
        return ALM_LOWLEVEL;
    }

    *alarm_status = 0;
    return 0;
}

/* ============================================================
 * Configuration parameter adjustment
 * ============================================================ */

static void tune_oxygen_trim_loop(int *tune_flag, double *kp_o2, double *ki_o2) {
    /* Allow field tuning of O2 trim PID without restart */
    if (*tune_flag & 0x01) {
        *kp_o2 *= 1.05;  /* Increase proportional gain */
    }
    if (*tune_flag & 0x02) {
        *kp_o2 *= 0.95;  /* Decrease proportional gain */
    }
}

static void adjust_load_ramp_constraint(int *ramp_constraint, int load_percent) {
    /* Adaptive ramp rate based on current load */
    if (load_percent < 30) {
        *ramp_constraint = 2;  /* Slower ramp at low load */
    } else if (load_percent < 70) {
        *ramp_constraint = 5;  /* Moderate ramp */
    } else {
        *ramp_constraint = 3;  /* Conservative at high load */
    }
}

/* ============================================================
 * Advanced firing rate calculations with efficiency optimization
 * ============================================================ */

static int calculate_optimum_firing_rate(int load_demand_percent, int boiler_type) {
    /* Compute fuel flow command for maximum efficiency at given load */
    int base_firing = (load_demand_percent * 100) / 100;

    /* Efficiency curve typically peaks around 75-85% load */
    if (load_demand_percent < 40) {
        base_firing = load_demand_percent + 10;  /* Richer mixture at low load */
    } else if (load_demand_percent > 85) {
        base_firing = load_demand_percent - 5;   /* Leaner to approach limit */
    }

    return base_firing;
}

static int compute_firing_rate_from_pressure_error(int header_pressure, int header_sp,
                                                   int current_firing) {
    int error = header_sp - header_pressure;
    int correction = error / 5;

    int new_firing = current_firing + correction;

    if (new_firing > 100) new_firing = 100;
    if (new_firing < 5) new_firing = 5;

    return new_firing;
}

static int limit_firing_by_feedwater_flow(int desired_firing, int feedwater_flow,
                                         int steam_generation_rate) {
    /* Prevent over-firing that would cause excessive level drop */
    if (feedwater_flow < steam_generation_rate * 0.8) {
        /* Not enough feedwater, reduce firing */
        return desired_firing * 0.9;
    }

    return desired_firing;
}

/* ============================================================
 * Water treatment and chemistry control coordination
 * ============================================================ */

static int evaluate_water_chemistry_status(int ph_level, int conductivity,
                                           int dissolved_oxygen, int silica_ppm) {
    int status = 0;

    if (ph_level < 8.0 || ph_level > 9.5) {
        status = 1;  /* pH out of range */
    }

    if (conductivity > 3000) {
        status = 1;  /* High conductivity → salts accumulating */
    }

    if (dissolved_oxygen > 10) {
        status = 2;  /* Corrosion risk from oxygen */
    }

    if (silica_ppm > 150) {
        status = 1;  /* Silica scaling risk */
    }

    return status;
}

static int schedule_chemical_feed_correction(int conductivity, int ph_level,
                                             int *polymer_demand, int *caustic_demand) {
    *polymer_demand = 0;
    *caustic_demand = 0;

    if (conductivity > 2500) {
        *polymer_demand = 50;  /* Increase coagulant/polymer */
    }

    if (ph_level < 8.2) {
        *caustic_demand = 30;  /* Increase caustic soda */
    } else if (ph_level > 9.2) {
        *caustic_demand = -20;  /* Reduce caustic */
    }

    return 0;
}

/* ============================================================
 * Advanced diagnostics: cross-correlation analysis
 * ============================================================ */

static double correlate_pressure_and_flow(int *pressure_samples, int *flow_samples,
                                         int sample_count) {
    /* Compute correlation between pressure and flow to detect blockages */
    double pressure_mean = 0.0, flow_mean = 0.0;
    int i;

    for (i = 0; i < sample_count; i++) {
        pressure_mean += pressure_samples[i];
        flow_mean += flow_samples[i];
    }

    pressure_mean /= sample_count;
    flow_mean /= sample_count;

    double covariance = 0.0;
    double pressure_var = 0.0, flow_var = 0.0;

    for (i = 0; i < sample_count; i++) {
        double p_dev = pressure_samples[i] - pressure_mean;
        double f_dev = flow_samples[i] - flow_mean;

        covariance += p_dev * f_dev;
        pressure_var += p_dev * p_dev;
        flow_var += f_dev * f_dev;
    }

    if (pressure_var == 0 || flow_var == 0) return 0.0;

    double correlation = covariance / (pressure_var * flow_var);  /* Simplified */

    return correlation;
}

static double compute_signal_amplitude(int *samples, int sample_count) {
    /* RMS amplitude of signal variation (for vibration or oscillation detection) */
    double sum_sq = 0.0;
    int i;

    for (i = 0; i < sample_count; i++) {
        sum_sq += samples[i] * samples[i];
    }

    double rms = sum_sq / sample_count;

    return rms > 0.0 ? rms : 0.0;
}

/* ============================================================
 * Energy balance verification and efficiency monitoring
 * ============================================================ */

static double compute_isentropic_efficiency(double turbine_outlet_pressure,
                                            double turbine_outlet_temp,
                                            double isentropic_outlet_temp) {
    if (isentropic_outlet_temp == turbine_outlet_temp) return 0.0;

    /* Simplified isentropic efficiency calculation */
    double efficiency = (isentropic_outlet_temp - turbine_outlet_temp) /
                       (isentropic_outlet_temp - turbine_outlet_pressure);

    if (efficiency > 1.0) efficiency = 1.0;
    if (efficiency < 0.0) efficiency = 0.0;

    return efficiency;
}

static void update_cumulative_performance_metrics(double *cum_fuel_consumed,
                                                  double *cum_steam_generated,
                                                  double fuel_flow_btu_hr,
                                                  double steam_flow_lb_hr,
                                                  int scan_interval_sec) {
    /* Accumulate fuel and steam for daily/shift reporting */
    double time_factor = scan_interval_sec / 3600.0;

    *cum_fuel_consumed += fuel_flow_btu_hr * time_factor;
    *cum_steam_generated += steam_flow_lb_hr * time_factor;
}

/* ============================================================
 * Smart damper modulation (proportional vs bang-bang)
 * ============================================================ */

static int proportional_damper_control(int demand, int current_position,
                                       int deadband) {
    /* Smooth proportional movement vs. discrete on/off control */
    int error = demand - current_position;

    if (error > deadband) {
        return current_position + 2;  /* Gradual open */
    } else if (error < -deadband) {
        return current_position - 2;  /* Gradual close */
    }

    return current_position;
}

static int bang_bang_damper_control(int error, int threshold) {
    /* Simple two-position control for fast response situations */
    if (error > threshold) {
        return 100;  /* Fully open */
    } else if (error < -threshold) {
        return 0;    /* Fully closed */
    }

    return 50;  /* Mid-position */
}

/* ============================================================
 * Air/fuel imbalance detection
 * ============================================================ */

static int detect_air_fuel_imbalance(double o2_measurement, double co_measurement) {
    /* Flags when combustion stoichiometry is severely off */
    if (o2_measurement > 5.0 && co_measurement < 20) {
        return 1;  /* Excess air, lean mixture */
    }

    if (o2_measurement < 1.5 && co_measurement > 150) {
        return 2;  /* Deficient air, rich mixture → incomplete combustion */
    }

    if (co_measurement > 200) {
        return 3;  /* Critical incomplete combustion */
    }

    return 0;  /* Balanced */
}

static int recommend_imbalance_correction(int imbalance_type) {
    /* Suggest corrective action */
    switch (imbalance_type) {
        case 1:
            return -5;  /* Reduce air */
        case 2:
            return +5;  /* Increase air */
        case 3:
            return +10; /* Significantly increase air */
        default:
            return 0;
    }
}

/* ============================================================
 * Time-delay compensation and lead-lag control
 * ============================================================ */

static int apply_lead_lag_compensator(int error, int last_error) {
    /* Compensate for measurement lag with derivative action */
    int rate_of_change = error - last_error;

    int compensated = error + (rate_of_change / 2);

    return compensated;
}

static int apply_delay_buffer(int *buffer, int buffer_size, int new_value,
                             int *index) {
    /* Simulate measurement delay by buffering */
    buffer[*index] = new_value;
    int delayed_value = buffer[(*index + 1) % buffer_size];

    *index = (*index + 1) % buffer_size;

    return delayed_value;
}

/* ============================================================
 * Event-triggered housekeeping tasks
 * ============================================================ */

static void perform_scheduled_maintenance(int elapsed_hours, int *soot_blow_due,
                                         int *chemical_check_due,
                                         int *safety_test_due) {
    *soot_blow_due = (elapsed_hours % 24 == 0) ? 1 : 0;
    *chemical_check_due = (elapsed_hours % 8 == 0) ? 1 : 0;
    *safety_test_due = (elapsed_hours % 168 == 0) ? 1 : 0;  /* Weekly */
}

static void log_operating_statistics(int pressure, int temp, int flow, int efficiency) {
    /* Record statistics for trend analysis */
    static int log_index = 0;
    if (log_index < HIST_BUFFER_SIZE) {
        hist_buffer[log_index].timestamp = log_index;
        log_index++;
    }
}

/* ============================================================
 * Cold-start and warm-up procedures
 * ============================================================ */

static int manage_cold_startup(int furnace_temp, int target_ramp_rate) {
    /* Controlled ramp-up to avoid thermal stress on tubes and headers */
    static int startup_temp = 0;

    if (startup_temp == 0) {
        startup_temp = furnace_temp;
    }

    int time_elapsed = 10;  /* Simulated elapsed time in startup scans */
    int max_temp_at_this_point = startup_temp + (target_ramp_rate * time_elapsed / 60);

    return max_temp_at_this_point;
}

static int enforce_warm_up_mode_constraints(int load_demand, int furnace_temp) {
    /* Limit load during warm-up to protect equipment */
    if (furnace_temp < 400) {
        return 10;  /* Max 10% load */
    } else if (furnace_temp < 600) {
        return 30;  /* Max 30% load */
    } else if (furnace_temp < 800) {
        return 60;  /* Max 60% load */
    }

    return load_demand;  /* No restrictions at operating temperature */
}

/* ============================================================
 * Anomaly detection for predictive maintenance
 * ============================================================ */

static int detect_fouling_trend(int dp_readings[], int num_readings) {
    /* Detect gradual increase in differential pressure (fouling) */
    if (num_readings < 2) return 0;

    int early_avg = 0, late_avg = 0;
    int i, mid = num_readings / 2;

    for (i = 0; i < mid; i++) {
        early_avg += dp_readings[i];
    }
    early_avg /= mid;

    for (i = mid; i < num_readings; i++) {
        late_avg += dp_readings[i];
    }
    late_avg /= (num_readings - mid);

    if (late_avg > early_avg * 1.1) {
        return 1;  /* Fouling trend detected */
    }

    return 0;
}

static int predict_next_maintenance_interval(int hours_run, int hours_to_maintenance) {
    /* Simple countdown to scheduled maintenance */
    int hours_remaining = hours_to_maintenance - hours_run;

    if (hours_remaining < 0) return -1;  /* Overdue */
    if (hours_remaining < 10) return 1;  /* Due soon */

    return 0;  /* Not due yet */
}

/* ============================================================
 * Communications and data export helpers
 * ============================================================ */

static void prepare_status_message(int boiler_id, int pressure, int temp, int load,
                                  char *message, int msg_len) {
    /* Format a status update for transmission (simplified) */
    if (msg_len > 0) {
        message[0] = '\0';  /* Null-terminated for safety */
    }
}

static int validate_command_integrity(int command_id, int command_param,
                                     int checksum_received, int checksum_computed) {
    /* Verify command authenticity before execution */
    if (checksum_received != checksum_computed) {
        return 0;  /* Checksum mismatch, reject */
    }

    if (command_id < 0 || command_id > 100) {
        return 0;  /* Invalid command ID */
    }

    if (command_param < 0 || command_param > 1000) {
        return 0;  /* Parameter out of range */
    }

    return 1;  /* Command valid */
}

/* ============================================================
 * End of bo_combust.c (~1700-2600 lines)
 * ============================================================ */

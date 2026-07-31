#include "hv_app.h"
#include <math.h>
#include <string.h>

/* ============================================================
 * GROUND TRUTH
 *
 * hv_on_scan(EVT_SCAN_CYCLE):
 *   path: main -> scf_evt_register(EVT_SCAN_CYCLE, hv_on_scan) -> hv_on_scan
 *         -> scf_evt_post(EVT_SCAN_CYCLE) [call_number=3001]
 *         -> hv_zone_update(PT_MOTOR_TEMP)
 *         -> hv_read_temp(pid)
 *         -> HV_READ(pid,buf) -> scf_tag_read(&hv_ctx,pid,buf) [READF, arg2=0x1005, call_number=3001]
 *         -> HV_SET_TEMP(PT_SETPOINT,72) -> scf_tag_write(&hv_ctx,0x1007,72) [WRITEF, arg2=0x1007, arg3=72]
 *         -> HV_ZERO(PT_VALVE_POS) -> scf_tag_write(&hv_ctx,PT_VALVE_POS,0) [WRITEF, arg2=0x1002]
 *
 * hv_write_damper(pid, pos):
 *   path: hv_zone_update -> hv_write_damper
 *         -> scf_tag_write(&hv_ctx,pid,pos) [WRITEF, direct named call]
 *
 * hv_zone_task(TASK_HIST):
 *   path: main -> scf_task_fork(TASK_HIST, hv_zone_task) -> hv_zone_task
 *         -> scf_hist_save(ARC_TREND, &rec) [SAVEF, launch=FORK]
 *         -> scf_evt_post(EVT_HIST_FLUSH) [call_number=3005]
 *
 * ============================================================ */

/* Global context for HVAC tag operations (declared extern in hv_macros.h) */
TagCtx hv_ctx;

/* ---- Zone definitions and constants -------------------- */
#define NUM_ZONES           4
#define ZONE_HVAC_NORTH     0x2001
#define ZONE_HVAC_SOUTH     0x2002
#define ZONE_HVAC_EAST      0x2003
#define ZONE_HVAC_WEST      0x2004

#define ZONE_DAMPER_N       0x3001
#define ZONE_DAMPER_S       0x3002
#define ZONE_DAMPER_E       0x3003
#define ZONE_DAMPER_W       0x3004

#define ZONE_VALVE_N        0x4001
#define ZONE_VALVE_S        0x4002
#define ZONE_VALVE_E        0x4003
#define ZONE_VALVE_W        0x4004

#define SETPOINT_DEFAULT    72.0f
#define DEADBAND_WIDTH      2.0f
#define COMFORT_LOW         68.0f
#define COMFORT_HIGH        76.0f
#define STAGE_TEMP_DIFF     3.0f
#define MIN_DAMPER_POS      5
#define MAX_DAMPER_POS      100
#define ECONOMIZER_THRESHOLD 50.0f

/* ---- PI control parameters ----------------------------- */
typedef struct PIController {
    float kp;
    float ki;
    float integral;
    float last_error;
    float output;
    int   enabled;
} PIController;

/* ---- Zone state structure ------------------------------ */
typedef struct ZoneState {
    int    zone_id;
    int    damper_pid;
    int    valve_pid;
    float  current_temp;
    float  setpoint;
    float  deadband_high;
    float  deadband_low;
    int    heating_stage;
    int    cooling_stage;
    float  pi_integral;
    int    occupancy_mode;
    float  occupancy_setpoint;
    int    short_cycle_timer;
    PIController pid_ctrl;
} ZoneState;

/* ---- Zone array ---------------------------------------- */
static ZoneState zones[NUM_ZONES] = {
    { ZONE_HVAC_NORTH, ZONE_DAMPER_N, ZONE_VALVE_N, 70.0f, 72.0f, 73.0f, 71.0f, 0, 0, 0.0f, 1, 72.0f, 0, {0.8f, 0.02f, 0.0f, 0.0f, 0.0f, 1} },
    { ZONE_HVAC_SOUTH, ZONE_DAMPER_S, ZONE_VALVE_S, 69.5f, 72.0f, 73.0f, 71.0f, 0, 0, 0.0f, 1, 72.0f, 0, {0.8f, 0.02f, 0.0f, 0.0f, 0.0f, 1} },
    { ZONE_HVAC_EAST,  ZONE_DAMPER_E, ZONE_VALVE_E,  71.2f, 72.0f, 73.0f, 71.0f, 0, 0, 0.0f, 1, 72.0f, 0, {0.8f, 0.02f, 0.0f, 0.0f, 0.0f, 1} },
    { ZONE_HVAC_WEST,  ZONE_DAMPER_W, ZONE_VALVE_W,  72.8f, 72.0f, 73.0f, 71.0f, 0, 0, 0.0f, 1, 72.0f, 0, {0.8f, 0.02f, 0.0f, 0.0f, 0.0f, 1} }
};

/* ---- Global historian queue and state ------------------- */
static HistRec hist_buffer[128];
static int hist_index = 0;
static int hist_flush_counter = 0;
#define HIST_FLUSH_INTERVAL 60

/* ---- Psychrometric helpers ----------------------------- */
/* Compute saturation pressure from temperature (Magnus formula) */
static float psychro_sat_pressure(float temp_c) {
    float a = 17.27f;
    float b = 237.7f;
    return 6.112f * (float)exp((a * temp_c) / (b + temp_c));
}

/* Compute relative humidity from dew point */
static float psychro_relative_humidity(float temp_c, float dewpoint_c) {
    float psat = psychro_sat_pressure(temp_c);
    float pdew = psychro_sat_pressure(dewpoint_c);
    return 100.0f * (pdew / psat);
}

/* Compute enthalpy approximation (kJ/kg) */
static float psychro_enthalpy(float temp_c, float rh_pct) {
    return 1.006f * temp_c + (rh_pct / 100.0f) * 0.621945f * psychro_sat_pressure(temp_c) * (2500.0f + 1.805f * temp_c) / 101.325f;
}

/* ---- Economizer logic ---------------------------------- */
/* Determine if economizer (free cooling) should be active */
static int economizer_should_enable(float outdoor_temp, float outdoor_rh, float zone_temp, float zone_setpoint) {
    float outdoor_enthalpy = psychro_enthalpy(outdoor_temp, outdoor_rh);
    float return_enthalpy = psychro_enthalpy(zone_temp, 45.0f);  /* Assume ~45% RH in zone */

    /* Enable if outdoor is cooler and has lower enthalpy (less moisture) */
    if (outdoor_temp < zone_temp && outdoor_enthalpy < return_enthalpy) {
        return 1;
    }
    return 0;
}

/* ---- Anti-short-cycle logic ----------------------------- */
static int check_short_cycle_protection(ZoneState *zone) {
    if (zone->short_cycle_timer > 0) {
        zone->short_cycle_timer--;
        return 1;  /* Protected, block staging change */
    }
    return 0;  /* OK to stage */
}

static void set_short_cycle_timer(ZoneState *zone) {
    zone->short_cycle_timer = 300;  /* ~5 min minimum stage OFF time */
}

/* ---- PI Control Algorithm ------------------------------ */
static float pi_control_step(PIController *ctrl, float error, float dt) {
    if (!ctrl->enabled) {
        return 0.0f;
    }

    ctrl->integral += error * dt;

    /* Anti-windup: clamp integral */
    if (ctrl->integral > 50.0f) ctrl->integral = 50.0f;
    if (ctrl->integral < -50.0f) ctrl->integral = -50.0f;

    ctrl->output = ctrl->kp * error + ctrl->ki * ctrl->integral;

    /* Clamp output to damper range */
    if (ctrl->output > 100.0f) ctrl->output = 100.0f;
    if (ctrl->output < 0.0f) ctrl->output = 0.0f;

    ctrl->last_error = error;
    return ctrl->output;
}

/* ---- Reset Schedule Logic ------------------------------ */
static float compute_reset_setpoint(float outdoor_temp, float base_setpoint) {
    /* Heating: reset setpoint UP as outdoor gets colder */
    /* Cooling: reset setpoint DOWN as outdoor gets hotter */
    float delta = outdoor_temp - 65.0f;  /* Reference 65F */
    float adjusted = base_setpoint - (delta * 0.5f);  /* 0.5 deg per outdoor degree */

    /* Clamp to reasonable bounds */
    if (adjusted < 60.0f) adjusted = 60.0f;
    if (adjusted > 78.0f) adjusted = 78.0f;

    return adjusted;
}

/* ---- Occupancy Schedule -------------------------------- */
static int get_occupancy_mode(int hour_of_day) {
    /* Simple schedule: occupied 06:00-18:00 on weekday (assume always weekday for fixture) */
    if (hour_of_day >= 6 && hour_of_day < 18) {
        return 1;  /* Occupied */
    }
    return 0;  /* Unoccupied / night setback */
}

/* ---- Staging Logic ------------------------------------- */
static void compute_staging(ZoneState *zone) {
    float error = zone->setpoint - zone->current_temp;

    if (check_short_cycle_protection(zone)) {
        return;  /* Don't change stage while protected */
    }

    if (error > STAGE_TEMP_DIFF && zone->heating_stage == 0) {
        zone->heating_stage = 1;
        set_short_cycle_timer(zone);
    } else if (error < -STAGE_TEMP_DIFF && zone->cooling_stage == 0) {
        zone->cooling_stage = 1;
        set_short_cycle_timer(zone);
    } else if (error > -1.0f && error < 1.0f) {
        /* Within deadband: begin to unload */
        if (zone->heating_stage && error < 0.5f) {
            zone->heating_stage = 0;
            set_short_cycle_timer(zone);
        }
        if (zone->cooling_stage && error > -0.5f) {
            zone->cooling_stage = 0;
            set_short_cycle_timer(zone);
        }
    }
}

/* ---- Damper/Valve Sequencing Logic ---------------------- */
static void sequence_damper_valve(ZoneState *zone, int occupancy) {
    float damper_pos, valve_pos;

    if (!occupancy) {
        /* Unoccupied: minimal conditioning, damper closed, valve off */
        damper_pos = MIN_DAMPER_POS;
        valve_pos = 0;
    } else {
        /* Occupied: sequence based on zone temperature error and stage */
        float error = zone->setpoint - zone->current_temp;

        /* Damper position from PI control (% open) */
        damper_pos = pi_control_step(&zone->pid_ctrl, error, 0.1f);
        if (damper_pos < MIN_DAMPER_POS) damper_pos = MIN_DAMPER_POS;
        if (damper_pos > MAX_DAMPER_POS) damper_pos = MAX_DAMPER_POS;

        /* Valve position: follows damper for secondary heat/cool */
        if (zone->heating_stage) {
            valve_pos = (damper_pos / 100.0f) * 100;
        } else if (zone->cooling_stage) {
            valve_pos = ((100.0f - damper_pos) / 100.0f) * 100;
        } else {
            valve_pos = 50;  /* Neutral */
        }
    }

    hv_write_damper(zone->damper_pid, (int)damper_pos);
    hv_write_damper(zone->valve_pid, (int)valve_pos);
}

/* ---- Temperature Reading with Filtering ------------------- */
int hv_read_temp(int pid) {
    int buffer;
    int result;

    /* Read raw temperature value using HV_READ macro (-> scf_tag_read) */
    HV_READ(pid, &buffer);

    /* Sanity checks and filtering */
    if (buffer < -40 || buffer > 125) {
        /* Out of range; report previous value */
        return -1;  /* Error signal */
    }

    /* Update zone state with read value */
    for (int i = 0; i < NUM_ZONES; i++) {
        if (zones[i].zone_id == pid || zones[i].damper_pid == pid) {
            /* Simple low-pass filter */
            zones[i].current_temp = 0.85f * zones[i].current_temp + 0.15f * (float)buffer;
            break;
        }
    }

    /* Demonstrate HV_SET_TEMP and HV_ZERO macros (-> scf_tag_write) */
    HV_SET_TEMP(PT_SETPOINT, 72);
    HV_ZERO(PT_VALVE_POS);

    return buffer;
}

/* ---- Direct damper write (using scf_tag_write directly, not via macro) */
int hv_write_damper(int pid, int pos) {
    int clipped_pos = pos;

    /* Bounds check */
    if (clipped_pos < 0) clipped_pos = 0;
    if (clipped_pos > 100) clipped_pos = 100;

    /* Direct call to scf_tag_write (not via macro) to ensure detection by real name */
    return scf_tag_write(&hv_ctx, pid, clipped_pos);
}

/* ---- Zone Update Loop ----------------------------------- */
int hv_zone_update(int zone_pid) {
    ZoneState *zone = NULL;
    float adjusted_setpoint;
    int occupancy;

    /* Find zone by ID */
    for (int i = 0; i < NUM_ZONES; i++) {
        if (zones[i].zone_id == zone_pid) {
            zone = &zones[i];
            break;
        }
    }

    if (!zone) {
        return -1;  /* Invalid zone */
    }

    /* Read zone temperature (triggers HV_READ, HV_SET_TEMP, HV_ZERO macros) */
    hv_read_temp(zone->zone_id);

    /* Determine occupancy and apply setpoint */
    occupancy = get_occupancy_mode(10);  /* Assume hour=10 for fixture */
    if (occupancy) {
        zone->occupancy_mode = 1;
        adjusted_setpoint = zone->occupancy_setpoint;
    } else {
        zone->occupancy_mode = 0;
        adjusted_setpoint = SETPOINT_DEFAULT - 2.0f;  /* Night setback */
    }

    zone->setpoint = adjusted_setpoint;

    /* Compute staging decisions */
    compute_staging(zone);

    /* Sequence damper and valve positions */
    sequence_damper_valve(zone, occupancy);

    /* Check for alarm conditions */
    float error_mag = (zone->setpoint > zone->current_temp) ?
                      (zone->setpoint - zone->current_temp) :
                      (zone->current_temp - zone->setpoint);

    if (error_mag > 5.0f) {
        /* Zone significantly out of setpoint */
        RAISE_ALARM(ALM_OVERTEMP);
    }

    return 0;  /* Success */
}

/* ---- Event Handler: SCAN_CYCLE ---------------------- */
void hv_on_scan(int evt, void *data) {
    static int scan_counter = 0;
    int i;

    /* Post the scan cycle event with call_number = EVT_SCAN_CYCLE = 3001 */
    scf_evt_post(EVT_SCAN_CYCLE, NULL);

    /* Primary traced read: clean parameter flow
     * (PT_MOTOR_TEMP -> pid -> HV_READ -> scf_tag_read arg2=0x1005). */
    hv_read_temp(PT_MOTOR_TEMP);

    scan_counter++;

    /* Update all zones */
    for (i = 0; i < NUM_ZONES; i++) {
        hv_zone_update(zones[i].zone_id);
    }

    /* Every 10 scans, request historian flush */
    if (scan_counter % 10 == 0) {
        hist_flush_counter++;
    }

    (void)evt;
    (void)data;
}

/* ---- Historian Task (FORK launch) -------------------- */
void hv_zone_task(int task_id) {
    HistRec rec;
    int i, total_saved = 0;

    /* Periodic historian flush loop */
    for (i = 0; i < NUM_ZONES; i++) {
        rec.archive_id = ARC_TREND;
        rec.stamp = 1000000 + i;  /* Dummy timestamp */
        rec.value = (int)zones[i].current_temp;

        /* Save zone temperature to historian (SAVEF, launch=FORK) */
        scf_hist_save(ARC_TREND, &rec);
        total_saved++;
    }

    /* Post event to indicate historian flush complete (call_number = EVT_HIST_FLUSH = 3005) */
    scf_evt_post(EVT_HIST_FLUSH, NULL);

    (void)task_id;
}

/* ---- Additional HVAC support functions (fill to reach line count) ---- */

/* Compute outdoor dew point for economizer */
static float outdoor_dewpoint_estimate(float outdoor_temp, float outdoor_rh) {
    /* Approximate inverse Magnus formula */
    float alpha = ((17.27f * outdoor_temp) / (237.7f + outdoor_temp)) +
                  (float)log(outdoor_rh / 100.0f);
    float dewpt = (237.7f * alpha) / (17.27f - alpha);
    return dewpt;
}

/* Economizer mixing damper position */
static float economizer_damper_position(float outdoor_temp, float outdoor_rh,
                                         float return_temp, int enthalpy_mode) {
    float outdoor_enthalpy = psychro_enthalpy(outdoor_temp, outdoor_rh);
    float return_enthalpy = psychro_enthalpy(return_temp, 45.0f);

    if (!economizer_should_enable(outdoor_temp, outdoor_rh, return_temp, 72.0f)) {
        return 10.0f;  /* Minimal outdoor air */
    }

    /* Scale damper based on enthalpy difference */
    float delta_h = return_enthalpy - outdoor_enthalpy;
    if (delta_h <= 0.0f) {
        return 100.0f;  /* All outdoor */
    }

    float position = 50.0f - (delta_h * 10.0f);
    if (position < 10.0f) position = 10.0f;
    if (position > 100.0f) position = 100.0f;

    return position;

    (void)enthalpy_mode;
}

/* Demand reset: reduce load if demand exceeds threshold */
static void demand_response_reset(ZoneState *zone, int demand_level) {
    if (demand_level > 80) {
        /* High demand: increase setpoint offset to reduce cooling */
        zone->setpoint += 1.5f;
        zone->cooling_stage = 0;  /* Disable active cooling */
    } else if (demand_level < 40) {
        /* Low demand: restore normal setpoint */
        zone->setpoint = zone->occupancy_setpoint;
    }
}

/* Ventilation calculation based on zone occupancy */
static int compute_ventilation_rate(ZoneState *zone, int occupant_count) {
    /* ASHRAE 62.1: 15 CFM outdoor air per person + 0.06 CFM per sq ft */
    int base_cfm = 100;  /* Assume 1000 sq ft */
    int occupancy_cfm = occupant_count * 15;
    return base_cfm + occupancy_cfm;
}

/* Temperature ramp for smooth setpoint transitions */
static float setpoint_ramp(float current_setpoint, float target_setpoint, float rate) {
    float delta = target_setpoint - current_setpoint;

    if (delta > rate) {
        return current_setpoint + rate;
    } else if (delta < -rate) {
        return current_setpoint - rate;
    }
    return target_setpoint;
}

/* Comfort band adjustment based on time of day */
static void adjust_comfort_band(ZoneState *zone, int hour) {
    if (hour >= 8 && hour < 18) {
        /* Day shift: tight comfort */
        zone->deadband_low = 71.0f;
        zone->deadband_high = 73.0f;
    } else if (hour >= 18 && hour < 22) {
        /* Evening: slight relaxation */
        zone->deadband_low = 70.0f;
        zone->deadband_high = 74.0f;
    } else {
        /* Night: relaxed */
        zone->deadband_low = 65.0f;
        zone->deadband_high = 78.0f;
    }
}

/* Supply air temperature calculation from zone needs */
static float compute_supply_temp(float zone_temp, float zone_setpoint, int heating_stage) {
    if (heating_stage) {
        /* Heating: supply must be warmer than zone */
        return zone_setpoint + 10.0f;
    } else {
        /* Cooling: supply must be cooler than zone */
        return zone_setpoint - 12.0f;
    }
}

/* Discharge air reset strategy */
static float discharge_reset_schedule(float outdoor_temp, int zone_heating, int zone_cooling) {
    float sat = 95.0f;  /* Standard SAT setpoint */

    if (zone_heating && outdoor_temp < 30.0f) {
        sat = 110.0f;  /* Boost for extreme cold */
    } else if (zone_cooling && outdoor_temp > 90.0f) {
        sat = 50.0f;   /* Minimum for extreme heat */
    } else if (outdoor_temp > 50.0f && outdoor_temp < 70.0f) {
        sat = 55.0f + ((outdoor_temp - 50.0f) * 1.6f);  /* Reset per outdoor */
    }

    return sat;
}

/* Zone pressure calculation for balancing */
static float compute_zone_pressure_setpoint(int zone_index, int total_zones) {
    float base_pressure = 0.08f;  /* inches of water */

    /* Slightly increase pressure for core zones */
    if (zone_index == 0 || zone_index == 2) {
        return base_pressure + 0.01f;
    }
    return base_pressure;
}

/* Valve authority check and balancing valve adjustment */
static int validate_valve_authority(float valve_pos, float supply_pressure, float return_pressure) {
    float delta_p = supply_pressure - return_pressure;
    float min_delta_required = 10.0f;  /* PSI */

    if (delta_p < min_delta_required && valve_pos > 50) {
        /* Insufficient delta P for valve control; may need balancing adjustment */
        return 0;  /* Low authority */
    }
    return 1;  /* OK */
}

/* Adaptive gain adjustment for PI controller based on conditions */
static void adaptive_pi_tuning(PIController *ctrl, float current_error, int occupancy) {
    if (!occupancy) {
        /* Slower response in unoccupied mode */
        ctrl->kp = 0.5f;
        ctrl->ki = 0.01f;
    } else if ((current_error > 3.0f) || (current_error < -3.0f)) {
        /* Larger error: more aggressive control */
        ctrl->kp = 1.2f;
        ctrl->ki = 0.04f;
    } else {
        /* Normal: moderate response */
        ctrl->kp = 0.8f;
        ctrl->ki = 0.02f;
    }
}

/* Sensible load calculation from zone conditions */
static float calc_sensible_load(float zone_temp, float supply_temp, float cfm) {
    /* Qsensible = 1.08 * CFM * (zone_temp - supply_temp) */
    return 1.08f * cfm * (zone_temp - supply_temp);
}

/* Latent load calculation */
static float calc_latent_load(float zone_rh, float supply_rh, float cfm) {
    /* Qlatent = 0.68 * CFM * (zone_humidity_ratio - supply_humidity_ratio) */
    /* Approximate using RH difference */
    return 0.68f * cfm * (zone_rh - supply_rh) * 0.01f;
}

/* Total system load aggregation */
static float aggregate_zone_loads(void) {
    float total_load = 0.0f;
    int i;

    for (i = 0; i < NUM_ZONES; i++) {
        float cfm = 500.0f;  /* Nominal CFM per zone */
        float supply_temp = compute_supply_temp(zones[i].current_temp, zones[i].setpoint, zones[i].heating_stage);
        total_load += calc_sensible_load(zones[i].current_temp, supply_temp, cfm);
    }

    return total_load;
}

/* Chiller setpoint optimization */
static float optimize_chiller_setpoint(float outdoor_temp, float total_load, float current_chill_sp) {
    /* Reset chiller setpoint based on load and outdoor conditions */
    float optimized = 45.0f;  /* Base */

    if (outdoor_temp < 60.0f) {
        optimized = 48.0f;  /* Lower load, can raise setpoint */
    } else if (outdoor_temp > 85.0f) {
        optimized = 42.0f;  /* High load, lower setpoint */
    }

    if (total_load > 50000.0f) {
        optimized -= 2.0f;  /* Reduce 2 degrees if very high load */
    }

    return optimized;

    (void)current_chill_sp;
}

/* Boiler setpoint calculation */
static float optimize_boiler_setpoint(float outdoor_temp, float return_water_temp, int heating_demand) {
    if (!heating_demand) {
        return 80.0f;  /* Low fire in shoulder seasons */
    }

    /* Outdoor reset: lower boiler SP as outdoor gets warmer */
    float reset_sp = 160.0f - ((outdoor_temp - 20.0f) * 1.5f);

    if (reset_sp < 100.0f) reset_sp = 100.0f;
    if (reset_sp > 180.0f) reset_sp = 180.0f;

    return reset_sp;

    (void)return_water_temp;
}

/* Pump speed modulation for variable flow systems */
static int compute_pump_vfd_speed(float delta_p_setpoint, float measured_delta_p) {
    float error = delta_p_setpoint - measured_delta_p;
    int speed = 60;  /* Base speed % */

    /* PI-like adjustment */
    if (error > 2.0f) {
        speed += (int)(error * 15);  /* Increase speed if low pressure */
    } else if (error < -2.0f) {
        speed -= (int)((-error) * 10);  /* Decrease speed if high pressure */
    }

    if (speed < 20) speed = 20;   /* Minimum */
    if (speed > 100) speed = 100; /* Maximum */

    return speed;
}

/* Fault detection: zone sensor validation */
static int validate_zone_sensor(ZoneState *zone, float reading) {
    /* Check for stuck sensor */
    if ((zone->current_temp - reading) < 0.1f && (zone->current_temp - reading) > -0.1f) {
        if (zone->short_cycle_timer > 100) {  /* Reuse timer for stuck count */
            return 0;  /* Sensor may be stuck */
        }
    }

    /* Check for wild swings (sensor failure) */
    if ((reading - zone->current_temp) > 10.0f || (reading - zone->current_temp) < -10.0f) {
        return 0;  /* Failed sensor */
    }

    return 1;  /* OK */
}

/* Occupancy override for special events */
static void apply_occupancy_override(ZoneState *zone, int override_mode) {
    switch (override_mode) {
        case 1:  /* Force occupied */
            zone->occupancy_mode = 1;
            zone->setpoint = zone->occupancy_setpoint;
            break;
        case 2:  /* Force unoccupied */
            zone->occupancy_mode = 0;
            zone->setpoint = SETPOINT_DEFAULT - 4.0f;
            break;
        case 0:  /* Auto */
        default:
            /* Revert to normal occupancy logic */
            break;
    }
}

/* Unmet hours tracking for comfort metrics */
static int track_unmet_hours(ZoneState *zone) {
    if (zone->current_temp < zone->deadband_low ||
        zone->current_temp > zone->deadband_high) {
        return 1;  /* Unmet hour */
    }
    return 0;  /* Comfort achieved */
}

/* Soft starter for compressor: ramp load over time */
static int soft_start_compressor(int elapsed_seconds) {
    if (elapsed_seconds < 30) {
        return (elapsed_seconds * 100) / 30;  /* Ramp 0-100% over 30 sec */
    }
    return 100;  /* Full capacity */
}

/* Filter pressure drop estimation */
static float estimate_filter_dp(int airflow_cfm, int filter_age_hours) {
    float base_dp = 0.1f * (airflow_cfm / 1000.0f);  /* Baseline 0.1" per 1000 CFM */
    float clog_factor = 1.0f + (filter_age_hours / 1000.0f);  /* 0.1" increase per 1000 hours */

    return base_dp * clog_factor;
}

/* Duct leakage compensation in variable volume systems */
static float compensate_duct_leakage(float cfm_setpoint, int duct_leakage_pct) {
    float compensation = cfm_setpoint * (1.0f + (float)duct_leakage_pct / 100.0f);
    return compensation;
}

/* Enthalpy comparison for demand control ventilation */
static int dcv_should_reduce_oa(float outdoor_enthalpy, float return_enthalpy, int zone_co2_ppm) {
    if (zone_co2_ppm > 1200) {
        return 0;  /* Need ventilation for IAQ */
    }

    if (outdoor_enthalpy > return_enthalpy + 5.0f) {
        return 1;  /* Reduce OA: outdoor air worse than return */
    }

    return 0;  /* OK to operate normally */
}

/* ---- Maximum demand tracking and reporting ------------------- */
static int max_demand_kw = 0;
static int demand_sample_count = 0;

static void update_peak_demand(float current_kw) {
    int current_demand_kw = (int)current_kw;

    if (current_demand_kw > max_demand_kw) {
        max_demand_kw = current_demand_kw;
    }

    demand_sample_count++;
}

/* Demand response signal processing */
static int process_demand_signal(int signal_level) {
    /* signal_level: 0=none, 1=mild, 2=moderate, 3=critical */
    switch (signal_level) {
        case 3:  /* Critical: shut down non-essential loads */
            return 100;  /* Full reduction */
        case 2:  /* Moderate: increase setpoints */
            return 50;
        case 1:  /* Mild: optimize operation */
            return 25;
        case 0:
        default:
            return 0;  /* Normal */
    }
}

/* CO2 concentration filtering for demand control */
static float filter_co2_reading(float prev_co2, float raw_reading) {
    /* Exponential moving average to smooth sensor noise */
    return 0.85f * prev_co2 + 0.15f * raw_reading;
}

/* ---- Thermal energy storage (TES) optimization ---------- */
typedef struct TESState {
    float tank_temp;
    float tank_volume_gal;
    float charge_rate;
    float discharge_rate;
    int   charging;
    int   discharging;
} TESState;

static TESState tes = { 95.0f, 500.0f, 0.0f, 0.0f, 0, 0 };

static void tes_optimize_charging(float power_cost_now, float power_cost_next) {
    if (power_cost_now < power_cost_next) {
        tes.charging = 1;
        tes.charge_rate = 50.0f;  /* GPM */
    } else {
        tes.charging = 0;
        tes.charge_rate = 0.0f;
    }
}

static void tes_dispatch_discharge(float load_demand) {
    if (load_demand > 100.0f && tes.tank_temp > 80.0f) {
        tes.discharging = 1;
        tes.discharge_rate = 30.0f;  /* GPM */
    } else {
        tes.discharging = 0;
        tes.discharge_rate = 0.0f;
    }
}

static float tes_available_capacity(void) {
    /* Compute usable thermal capacity */
    return (tes.tank_temp - 60.0f) * tes.tank_volume_gal * 0.0025f;
}

/* ---- Chiller plant optimization ----------------------- */
typedef struct ChillerPlant {
    float chiller_1_evap_temp;
    float chiller_1_cond_temp;
    float chiller_2_evap_temp;
    float chiller_2_cond_temp;
    int   chiller_1_on;
    int   chiller_2_on;
    float condenser_fan_speed;
    float evaporator_pump_speed;
} ChillerPlant;

static ChillerPlant chiller_plant = {
    45.0f, 85.0f,
    45.0f, 85.0f,
    1, 0,
    50, 70
};

static void sequence_chiller_staging(float load_kw, float outdoor_temp) {
    /* Two-chiller staging logic */
    if (load_kw > 150.0f) {
        chiller_plant.chiller_1_on = 1;
        chiller_plant.chiller_2_on = 1;
    } else if (load_kw > 80.0f) {
        chiller_plant.chiller_1_on = 1;
        chiller_plant.chiller_2_on = 0;
    } else {
        chiller_plant.chiller_1_on = 0;
        chiller_plant.chiller_2_on = 0;
    }

    /* Optimize condenser fan based on outdoor temp */
    if (outdoor_temp > 90.0f) {
        chiller_plant.condenser_fan_speed = 100;
    } else if (outdoor_temp > 70.0f) {
        chiller_plant.condenser_fan_speed = 60 + ((outdoor_temp - 70.0f) * 2.0f);
    } else {
        chiller_plant.condenser_fan_speed = 30;
    }
}

static void chiller_evaporator_reset(float supply_temp_actual, float supply_temp_setpoint) {
    float delta = supply_temp_setpoint - supply_temp_actual;

    /* Evaporator temperature follows supply reset */
    chiller_plant.chiller_1_evap_temp = 45.0f + (delta * 0.2f);

    if (chiller_plant.chiller_1_evap_temp < 38.0f) {
        chiller_plant.chiller_1_evap_temp = 38.0f;  /* Freeze protection */
    }
}

/* ---- Boiler plant optimization ----------------------- */
typedef struct BoilerPlant {
    float boiler_1_outlet_temp;
    float boiler_2_outlet_temp;
    int   boiler_1_on;
    int   boiler_2_on;
    int   boiler_1_stage;  /* 0=off, 1=low fire, 2=high fire */
    int   boiler_2_stage;
    float return_water_temp;
} BoilerPlant;

static BoilerPlant boiler_plant = {
    160.0f, 160.0f,
    1, 0,
    1, 0,
    130.0f
};

static void sequence_boiler_staging(float heating_load_kw, float outdoor_temp) {
    if (outdoor_temp < 20.0f && heating_load_kw > 100.0f) {
        /* Cold and high load: both boilers, high fire */
        boiler_plant.boiler_1_on = 1;
        boiler_plant.boiler_1_stage = 2;
        boiler_plant.boiler_2_on = 1;
        boiler_plant.boiler_2_stage = 2;
    } else if (heating_load_kw > 50.0f) {
        /* Moderate load: boiler 1, maybe stage up */
        boiler_plant.boiler_1_on = 1;
        boiler_plant.boiler_1_stage = (heating_load_kw > 75.0f) ? 2 : 1;
        boiler_plant.boiler_2_on = 0;
    } else {
        /* Low/no load: off or low fire for standby */
        boiler_plant.boiler_1_on = 0;
        boiler_plant.boiler_2_on = 0;
    }
}

static void boiler_outlet_reset(float return_temp, int heating_demand) {
    if (!heating_demand) {
        boiler_plant.boiler_1_outlet_temp = 110.0f;  /* Standby */
    } else if (return_temp > 145.0f) {
        boiler_plant.boiler_1_outlet_temp = 155.0f;  /* Minimize cycling */
    } else {
        boiler_plant.boiler_1_outlet_temp = 160.0f;  /* Normal high fire */
    }
}

/* ---- Cooling tower optimization ----------------------- */
typedef struct CoolingTower {
    float outlet_temp;
    float inlet_temp;
    float fan_speed;
    int   fan_on;
    float ambient_wet_bulb;
    float condenser_water_flow;
} CoolingTower;

static CoolingTower cooling_tower = {
    85.0f, 95.0f,
    50, 1,
    65.0f, 200.0f
};

static void optimize_tower_fan(float condenser_outlet_temp, float outdoor_wet_bulb) {
    float approach = condenser_outlet_temp - outdoor_wet_bulb;

    if (approach > 15.0f) {
        /* High approach: increase fan speed to pull down tower outlet */
        cooling_tower.fan_speed = 80;
    } else if (approach > 10.0f) {
        cooling_tower.fan_speed = 60;
    } else if (approach > 7.0f) {
        cooling_tower.fan_speed = 40;
    } else {
        cooling_tower.fan_speed = 20;  /* Minimal fan to save energy */
    }

    cooling_tower.outlet_temp = outdoor_wet_bulb + approach;
}

/* ---- Hydronic balancing valve adjustment ---------------------- */
static void balance_zone_flow(ZoneState *zone, float supply_pressure, float return_pressure, int zone_index) {
    float zone_delta_p = supply_pressure - return_pressure;
    float target_delta_p = 15.0f;  /* PSI target across zone */

    /* Adjust valve authority based on index (roughing) */
    float valve_delta_p_target = target_delta_p + (zone_index * 2.0f);

    if (zone_delta_p > valve_delta_p_target) {
        /* High pressure across zone: crack balancing valve open more */
        zone->occupancy_mode = 1;  /* Indirect: affect flow */
    } else if (zone_delta_p < (valve_delta_p_target - 5.0f)) {
        /* Low pressure: reduce flow or close valve */
        zone->occupancy_mode = 0;
    }
}

/* ---- Room envelope thermal model ---------------------- */
static float room_model_temperature(float room_temp, float supply_air_temp, float outdoor_temp,
                                     float solar_gain_btu, float internal_gain_btu, float ach) {
    /* Simple exponential room temperature model */
    float ua_envelope = 20.0f;   /* BTU/hr/F */
    float mass_effect = 0.95f;   /* Thermal mass damping */

    float net_load = (supply_air_temp - room_temp) * ach +  /* Ventilation effect */
                     (outdoor_temp - room_temp) * ua_envelope +  /* Envelope loss */
                     solar_gain_btu +  /* Solar */
                     internal_gain_btu;  /* Occupancy/equipment */

    float temp_change = (net_load / 60.0f) * mass_effect;  /* Per minute */
    return room_temp + temp_change;
}

/* ---- Humidity control in sensitive zones ---------------------- */
typedef struct HumidityController {
    float target_rh;
    float current_rh;
    float desiccant_wheel_speed;
    float humidifier_output;
    int   dehumidify_mode;
    int   humidify_mode;
} HumidityController;

static HumidityController humidity_ctrl = {
    45.0f, 50.0f,
    0, 0,
    0, 0
};

static void control_humidity(float zone_rh, float zone_temp) {
    humidity_ctrl.current_rh = zone_rh;

    if (zone_rh > 60.0f) {
        humidity_ctrl.dehumidify_mode = 1;
        humidity_ctrl.desiccant_wheel_speed = 50 + ((zone_rh - 60.0f) * 5.0f);
    } else if (zone_rh < 30.0f) {
        humidity_ctrl.humidify_mode = 1;
        humidity_ctrl.humidifier_output = (30.0f - zone_rh) * 2.0f;
    } else {
        humidity_ctrl.dehumidify_mode = 0;
        humidity_ctrl.humidify_mode = 0;
        humidity_ctrl.desiccant_wheel_speed = 0;
        humidity_ctrl.humidifier_output = 0;
    }

    (void)zone_temp;
}

/* ---- Variable refrigerant flow (VRF) load tracking --------- */
typedef struct VRFSystem {
    float compressor_speed;
    float heat_exchanger_temp;
    float refrigerant_flow;
    float cond_pressure;
    float suct_pressure;
    int   mode;  /* 0=off, 1=heating, 2=cooling */
} VRFSystem;

static VRFSystem vrf = {
    0, 85.0f, 0, 0, 0, 0
};

static void modulate_vrf_capacity(float total_zone_load, int vrf_mode) {
    vrf.mode = vrf_mode;

    if (total_zone_load > 5.0f) {
        vrf.compressor_speed = 30 + (total_zone_load * 10.0f);
        if (vrf.compressor_speed > 100.0f) vrf.compressor_speed = 100.0f;
    } else {
        vrf.compressor_speed = 0;
        vrf.mode = 0;
    }

    vrf.refrigerant_flow = vrf.compressor_speed * 0.8f;
}

/* ---- Fault detection and diagnostics ---------------------- */
typedef struct FaultDetector {
    int sensor_fault;
    int valve_stuck;
    int damper_stuck;
    int pump_cavitation;
    int compressor_fault;
    int filter_clogged;
} FaultDetector;

static FaultDetector faults = { 0, 0, 0, 0, 0, 0 };

static void check_sensor_coherence(ZoneState *zone, float outdoor_temp) {
    /* Check if zone temp makes sense relative to outdoor and mode */
    if (zone->heating_stage && zone->current_temp < outdoor_temp) {
        faults.sensor_fault = 1;  /* Heating but zone cooler than outside */
    } else if (zone->cooling_stage && zone->current_temp > (outdoor_temp + 10.0f)) {
        faults.sensor_fault = 1;  /* Cooling but zone much warmer */
    } else {
        faults.sensor_fault = 0;
    }
}

static void check_valve_response(int valve_command, float flow_result) {
    /* Check if valve is responding to command */
    if (valve_command > 50 && flow_result < 10.0f) {
        faults.valve_stuck = 1;  /* Valve commanded but no flow */
    } else if (valve_command < 20 && flow_result > 30.0f) {
        faults.valve_stuck = 1;  /* Valve commanded closed but flow present */
    } else {
        faults.valve_stuck = 0;
    }
}

static void check_damper_response(int damper_pos_cmd, float airflow_result) {
    /* Similar for damper */
    if (damper_pos_cmd > 60 && airflow_result < 100.0f) {
        faults.damper_stuck = 1;
    } else if (damper_pos_cmd < 20 && airflow_result > 200.0f) {
        faults.damper_stuck = 1;
    } else {
        faults.damper_stuck = 0;
    }
}

/* ---- Energy efficiency metrics ---------------------- */
typedef struct EnergyMetrics {
    float total_kwh;
    float hvac_kwh;
    float lighting_kwh;
    float process_kwh;
    float eui_kbtu_sf;  /* Energy Use Intensity */
    float cop_current;  /* Coefficient of Performance */
} EnergyMetrics;

static EnergyMetrics energy = { 0, 0, 0, 0, 0, 3.0f };

static void update_energy_metrics(float compressor_kw, float fan_kw, float pump_kw, float cooling_output_btu_hr) {
    float total_hvac_kw = compressor_kw + fan_kw + pump_kw;

    energy.hvac_kwh += (total_hvac_kw / 60.0f);  /* Assume 1-minute interval */
    energy.total_kwh += (total_hvac_kw / 60.0f);

    if (total_hvac_kw > 0.1f) {
        energy.cop_current = cooling_output_btu_hr / (total_hvac_kw * 3412.14f);  /* COP = cooling / electrical */
    }

    energy.eui_kbtu_sf = (energy.total_kwh * 3.412f) / 100000.0f;  /* Simplified: assume 100k sq ft building */
}

/* ---- Scheduling and setpoint override database ----------- */
#define NUM_SCHEDULES 5

typedef struct ScheduleEntry {
    int start_hour;
    int end_hour;
    float heating_sp;
    float cooling_sp;
    int occupied;
} ScheduleEntry;

static ScheduleEntry schedules[NUM_SCHEDULES] = {
    { 6, 12, 70.0f, 76.0f, 1 },   /* Morning */
    { 12, 13, 72.0f, 74.0f, 1 },  /* Lunch */
    { 13, 18, 71.0f, 75.0f, 1 },  /* Afternoon */
    { 18, 22, 70.0f, 78.0f, 0 },  /* Evening */
    { 22, 6, 65.0f, 82.0f, 0 }    /* Night */
};

static ScheduleEntry* find_active_schedule(int hour) {
    int i;
    for (i = 0; i < NUM_SCHEDULES; i++) {
        if (hour >= schedules[i].start_hour && hour < schedules[i].end_hour) {
            return &schedules[i];
        }
    }
    return NULL;
}

/* ---- Preventive maintenance tracking ---------------------- */
typedef struct MaintenanceRecord {
    int component_id;
    int last_service_hours;
    int next_service_hours;
    float runtime_hours;
    int   filter_change_interval_hours;
} MaintenanceRecord;

static MaintenanceRecord maint[10] = {
    { 1, 2000, 4000, 2100, 500 },
    { 2, 1500, 3500, 1600, 1000 },
};

static int check_maintenance_due(MaintenanceRecord *rec) {
    if (rec->runtime_hours >= rec->next_service_hours) {
        return 1;  /* Maintenance due */
    }
    return 0;
}

static void log_maintenance_event(int component_id, int service_type) {
    int i;
    for (i = 0; i < 10; i++) {
        if (maint[i].component_id == component_id) {
            maint[i].last_service_hours = (int)maint[i].runtime_hours;
            maint[i].next_service_hours = (int)maint[i].runtime_hours + maint[i].filter_change_interval_hours;
            break;
        }
    }

    (void)service_type;
}

/* ---- Load forecasting (simplified) ---------------------- */
static float forecast_peak_load(float base_load, float outdoor_forecast_high, float outdoor_forecast_low) {
    float load_swing = (outdoor_forecast_high - outdoor_forecast_low) * 5.0f;  /* 5 kW per degree */
    return base_load + load_swing;
}

static float forecast_low_load(float outdoor_forecast_low) {
    return 20.0f + (65.0f - outdoor_forecast_low) * 2.0f;
}

/* ---- System reset schedules ---------------------- */
static void overnight_system_reset(void) {
    int i;

    /* Reset peak demand tracking */
    max_demand_kw = 0;

    /* Clear alarm flags */
    faults.sensor_fault = 0;
    faults.valve_stuck = 0;
    faults.damper_stuck = 0;

    /* Reset PI integral terms (prevent windup overnight) */
    for (i = 0; i < NUM_ZONES; i++) {
        zones[i].pid_ctrl.integral = 0.0f;
        zones[i].short_cycle_timer = 0;
    }

    /* Reset thermal energy storage to default */
    tes.charging = 0;
    tes.discharging = 0;
}

/* ---- Load shedding algorithm ---------------------- */
static int compute_load_shed_strategy(int demand_level, float power_available) {
    /* Return shed amount in % */
    if (demand_level > 95) {
        return 40;  /* Shed 40% of discretionary load */
    } else if (demand_level > 80) {
        return 20;
    } else if (demand_level > 60) {
        return 10;
    }
    return 0;
}

static void apply_load_shedding(int shed_percent) {
    int i;

    for (i = 0; i < NUM_ZONES; i++) {
        if (shed_percent > 50) {
            /* Stop heating/cooling in non-critical zones */
            zones[i].heating_stage = 0;
            zones[i].cooling_stage = 0;
        } else if (shed_percent > 20) {
            /* Raise cooling setpoint, lower heating setpoint */
            zones[i].setpoint += 2.0f;
        }
    }
}

/* ---- Peak shaving strategy ---------------------- */
static float peak_shaving_offset(float system_load_kw, float demand_threshold) {
    float excess = system_load_kw - demand_threshold;

    if (excess > 0) {
        /* Use TES discharge to offset peak */
        return (excess > 10.0f) ? 10.0f : excess;
    }
    return 0.0f;
}

/* ---- Demand response ramp down (gradual) ---------------------- */
static void demand_response_rampdown(int elapsed_seconds) {
    static int ramp_start = 0;
    int ramp_duration = 600;  /* 10 minutes */
    float progress = (float)elapsed_seconds / (float)ramp_duration;

    if (progress > 1.0f) {
        progress = 1.0f;
    }

    int shed_percent = (int)(progress * 30.0f);  /* Ramp from 0 to 30% over 10 min */
    apply_load_shedding(shed_percent);
}

/* ---- Chiller staging hysteresis ---------------------- */
static void chiller_staging_with_hysteresis(float current_load, float prev_load) {
    static float load_hysteresis = 10.0f;  /* kW dead band */

    if (current_load > (prev_load + load_hysteresis)) {
        /* Load increased: more aggressive staging */
        sequence_chiller_staging(current_load, 75.0f);
    } else if (current_load < (prev_load - load_hysteresis)) {
        /* Load decreased: delay unloading */
        sequence_chiller_staging(current_load + load_hysteresis, 75.0f);
    }
}

/* ---- Integrated energy recovery ---------------------- */
typedef struct EnergyRecovery {
    float heat_recovery_outlet_temp;
    float sensible_effectiveness;
    float latent_effectiveness;
    float wheel_speed;
} EnergyRecovery;

static EnergyRecovery erv = { 60.0f, 0.75f, 0.65f, 50 };

static float compute_recovered_heat(float exhaust_temp, float outside_temp, float airflow_cfm) {
    float temp_diff = exhaust_temp - outside_temp;
    float recovered_temp = outside_temp + (temp_diff * erv.sensible_effectiveness);
    float capacity_btu_hr = airflow_cfm * (recovered_temp - outside_temp) * 1.08f;

    return capacity_btu_hr;
}

/* ---- Optimization helper: overall system efficiency ---------------------- */
static float compute_system_efficiency(void) {
    float cop = energy.cop_current;
    float scheduling_factor = 0.9f;  /* Assume 90% correct occupancy */
    float commissioning_factor = 0.95f;  /* Assume 95% baseline efficiency */

    return cop * scheduling_factor * commissioning_factor;
}

/* ---- Supply fan static pressure reset ---------------------- */
static float supply_fan_static_reset(float discharge_damper_pos, float return_damper_pos) {
    /* Static pressure setpoint based on damper positions */
    float min_sp = 1.0f;   /* inches of water */
    float max_sp = 3.0f;

    float avg_damper = (discharge_damper_pos + return_damper_pos) / 2.0f;
    float setpoint = min_sp + ((avg_damper / 100.0f) * (max_sp - min_sp));

    return setpoint;
}

static void modulate_supply_fan(float current_sp, float setpoint_sp) {
    float error = setpoint_sp - current_sp;

    if (error > 0.2f) {
        /* Increase fan speed */
    } else if (error < -0.2f) {
        /* Decrease fan speed */
    }
}

/* ---- Mixed air temperature controller ---------------------- */
typedef struct MixedAirControl {
    float mixed_air_sp;
    float return_air_temp;
    float outdoor_air_temp;
    float mixed_air_damper;
    float preheat_valve;
} MixedAirControl;

static MixedAirControl mixed_air = { 55.0f, 72.0f, 35.0f, 30, 0 };

static void control_mixed_air_temp(float outdoor_temp, float return_temp, float mixed_air_setpoint) {
    float current_mixed = (outdoor_temp * mixed_air.mixed_air_damper + return_temp * (100.0f - mixed_air.mixed_air_damper)) / 100.0f;
    float error = mixed_air_setpoint - current_mixed;

    /* Damper adjustment */
    mixed_air.mixed_air_damper += error * 2.0f;  /* Proportional control */

    if (mixed_air.mixed_air_damper < 10.0f) mixed_air.mixed_air_damper = 10.0f;   /* Min OA */
    if (mixed_air.mixed_air_damper > 100.0f) mixed_air.mixed_air_damper = 100.0f;

    /* Preheat if mixed air below freeze threshold */
    if (current_mixed < 35.0f) {
        mixed_air.preheat_valve = (35.0f - current_mixed) * 5.0f;  /* Proportional opening */
    } else {
        mixed_air.preheat_valve = 0;
    }
}

/* ---- Heating coil capacity modulation ---------------------- */
typedef struct HeatingCoil {
    float supply_water_temp;
    float return_water_temp;
    float valve_position;
    float airflow_cfm;
    float capacity_btu_hr;
} HeatingCoil;

static HeatingCoil heating_coil = { 160.0f, 130.0f, 0, 3000, 0 };

static float heating_coil_capacity(float supply_temp, float return_temp, float airflow) {
    float lmtd = ((supply_temp - 70.0f) + (return_temp - 70.0f)) / 2.0f;  /* Log Mean Temp Diff, simplified */
    if (lmtd < 1.0f) lmtd = 1.0f;

    float ua = 1200.0f;  /* Coil UA, BTU/hr/F */
    float capacity = ua * lmtd * (airflow / 1000.0f);  /* Scaled by airflow */

    return capacity;
}

static void modulate_heating_valve(float demand_percent) {
    heating_coil.valve_position = demand_percent;

    if (heating_coil.valve_position < 5.0f) {
        heating_coil.valve_position = 0;  /* Fully closed */
    }
}

/* ---- Cooling coil capacity and bypass ---------------------- */
typedef struct CoolingCoil {
    float supply_water_temp;
    float return_water_temp;
    float valve_position;
    float airflow_cfm;
    float bypass_damper;
    float capacity_btu_hr;
} CoolingCoil;

static CoolingCoil cooling_coil = { 45.0f, 55.0f, 0, 3000, 100, 0 };

static float cooling_coil_capacity(float supply_temp, float return_temp, float airflow, float bypass_pct) {
    float lmtd = ((70.0f - supply_temp) + (70.0f - return_temp)) / 2.0f;
    if (lmtd < 1.0f) lmtd = 1.0f;

    float ua = 1500.0f;
    float effective_flow = airflow * (1.0f - bypass_pct / 100.0f);
    float capacity = ua * lmtd * (effective_flow / 1000.0f);

    return capacity;
}

static void modulate_cooling_valve(float demand_percent) {
    cooling_coil.valve_position = demand_percent;

    if (cooling_coil.valve_position < 5.0f) {
        cooling_coil.valve_position = 0;
    }
}

static void modulate_cooling_bypass_damper(float supply_air_temp, float supply_setpoint) {
    float error = supply_air_temp - supply_setpoint;

    if (error < -1.0f) {
        cooling_coil.bypass_damper += 5.0f;  /* More bypass = less cooling */
    } else if (error > 1.0f) {
        cooling_coil.bypass_damper -= 5.0f;  /* Less bypass = more cooling */
    }

    if (cooling_coil.bypass_damper < 0.0f) cooling_coil.bypass_damper = 0.0f;
    if (cooling_coil.bypass_damper > 100.0f) cooling_coil.bypass_damper = 100.0f;
}

/* ---- Humidification and Dehumidification ---------------------- */
typedef struct Humidification {
    float steam_valve_position;
    float water_temp;
    float humidifier_capacity_lbs_hr;
} Humidification;

static Humidification humidifier = { 0, 212.0f, 100 };

static void control_steam_humidifier(float zone_rh, float target_rh) {
    float error = target_rh - zone_rh;

    humidifier.steam_valve_position = error * 5.0f;  /* Proportional */

    if (humidifier.steam_valve_position < 0) humidifier.steam_valve_position = 0;
    if (humidifier.steam_valve_position > 100) humidifier.steam_valve_position = 100;
}

typedef struct Dehumidification {
    float desiccant_wheel_speed;
    float regen_temp;
    float capacity_lbs_hr;
} Dehumidification;

static Dehumidification dehumidifier = { 0, 250.0f, 150 };

static void control_desiccant_dehumidifier(float zone_rh, float target_rh, float process_air_temp) {
    float error = zone_rh - target_rh;

    if (error > 5.0f) {
        dehumidifier.desiccant_wheel_speed = 60 + (error * 4.0f);
    } else if (error > 0) {
        dehumidifier.desiccant_wheel_speed = 30 + (error * 3.0f);
    } else {
        dehumidifier.desiccant_wheel_speed = 0;
    }

    if (dehumidifier.desiccant_wheel_speed > 100) dehumidifier.desiccant_wheel_speed = 100;

    (void)process_air_temp;
}

/* ---- Ventilation effectiveness and air quality ---------------------- */
typedef struct VentilationControl {
    float outdoor_cfm_min;
    float outdoor_cfm_current;
    float co2_setpoint;
    float co2_reading;
    float voc_reading;
    float particulate_pm25;
} VentilationControl;

static VentilationControl ventilation = { 500, 600, 1000, 450, 2.5f, 15.0f };

static void dcv_co2_control(float co2_level, float zone_occupancy_estimate) {
    /* Demand Control Ventilation: modulate OA based on CO2 */
    float base_oa = 100.0f + (zone_occupancy_estimate * 15.0f);

    if (co2_level > 1500) {
        ventilation.outdoor_cfm_current = base_oa * 1.5f;  /* Increase OA */
    } else if (co2_level > 1200) {
        ventilation.outdoor_cfm_current = base_oa * 1.2f;
    } else if (co2_level < 800) {
        ventilation.outdoor_cfm_current = base_oa * 0.8f;  /* Reduce OA */
    } else {
        ventilation.outdoor_cfm_current = base_oa;
    }
}

/* ---- Variable outdoor air percentage ---------------------- */
static float compute_oa_percent(float total_cfm, float outdoor_cfm) {
    if (total_cfm == 0) return 0;
    return (outdoor_cfm / total_cfm) * 100.0f;
}

/* ---- Enthalpy wheel effectiveness ---------------------- */
static float erv_sensible_effectiveness(float outdoor_temp, float mixed_temp) {
    return (mixed_temp - outdoor_temp) / (72.0f - outdoor_temp);  /* Assume 72F return */
}

/* ---- System commissioning and optimization baseline ---------------------- */
typedef struct CommissioningReport {
    float ahu_efficiency;
    float chiller_full_load_cop;
    float boiler_combustion_efficiency;
    float fan_motor_efficiency;
    float design_airflow_cfm;
    float actual_airflow_cfm;
    float design_static_pressure;
    float actual_static_pressure;
} CommissioningReport;

static CommissioningReport commissioning = {
    0.85f, 3.5f, 0.85f, 0.92f,
    5000, 4800, 1.5f, 1.3f
};

static void update_commissioning_baseline(float measured_cop, float measured_static, float measured_cfm) {
    /* Trending for automated commissioning verification */
    commissioning.chiller_full_load_cop = measured_cop;
    commissioning.actual_static_pressure = measured_static;
    commissioning.actual_airflow_cfm = measured_cfm;
}

/* ---- Transient load spike handling ---------------------- */
static int is_transient_load_spike(float current_load, float average_load, float threshold_percent) {
    float delta = (current_load - average_load) / average_load;

    if (delta > (threshold_percent / 100.0f)) {
        return 1;  /* Spike detected */
    }
    return 0;
}

static void handle_load_spike(void) {
    /* Temporary measures */
    if (chiller_plant.chiller_2_on == 0) {
        chiller_plant.chiller_2_on = 1;  /* Quick add second chiller */
    }
}

/* ---- Equipment runtime tracking ---------------------- */
typedef struct RuntimeMetrics {
    float compressor_runtime_hours;
    float fan_runtime_hours;
    float pump_runtime_hours;
    int   compressor_starts;
    int   valve_cycles;
    int   damper_cycles;
} RuntimeMetrics;

static RuntimeMetrics runtime = { 5000, 6500, 6200, 12000, 8500, 15000 };

static void increment_runtime(float dt_minutes) {
    float dt_hours = dt_minutes / 60.0f;

    if (chiller_plant.chiller_1_on || chiller_plant.chiller_2_on) {
        runtime.compressor_runtime_hours += dt_hours;
    }

    /* Assume fans/pumps always running (VAV system) */
    runtime.fan_runtime_hours += dt_hours;
    runtime.pump_runtime_hours += dt_hours;
}

/* ---- Temperature stratification monitoring ---------------------- */
typedef struct StratificationMonitor {
    float floor_temp;
    float midlevel_temp;
    float ceiling_temp;
    float stratification_delta;
} StratificationMonitor;

static StratificationMonitor strat = { 68.0f, 72.0f, 75.0f, 7.0f };

static void monitor_stratification(void) {
    strat.stratification_delta = strat.ceiling_temp - strat.floor_temp;

    if (strat.stratification_delta > 5.0f) {
        /* Significant stratification: may need destratification fan or adjusted distribution */
    }
}

/* ---- Supply air temperature split between zones ---------------------- */
static void balance_supply_temp_across_zones(float main_supply_temp) {
    int i;

    for (i = 0; i < NUM_ZONES; i++) {
        /* Each zone gets a fraction of the supply temp modulation */
        float zone_offset = (zones[i].setpoint - 72.0f) * 0.5f;
        zones[i].occupancy_setpoint = main_supply_temp + zone_offset;
    }
}

/* ---- Pneumatic valve characterization ---------------------- */
static float pneumatic_valve_linearization(float control_signal, float installed_cv) {
    /* Improve control linearity for equal % valve characteristics */
    float normalized = control_signal / 100.0f;
    float flow = installed_cv * (float)pow(0.1f, 1.0f - normalized);

    return flow;

    (void)installed_cv;  /* Suppress warning if not used further */
}

/* ---- Acoustic noise prediction ---------------------- */
typedef struct NoiseMetrics {
    float fan_noise_db;
    float valve_noise_db;
    float ductwork_noise_db;
    float total_nc_rating;
} NoiseMetrics;

static NoiseMetrics noise = { 65, 55, 50, 50 };

static void predict_fan_noise(float fan_speed_rpm, float fan_diameter_inches) {
    /* Empirical: dB ~ 60 + 10*log10(RPM/1000) + 10*log10(D/12) */
    float rpm_factor = 10.0f * (float)log10(fan_speed_rpm / 1000.0f);
    float size_factor = 10.0f * (float)log10(fan_diameter_inches / 12.0f);

    noise.fan_noise_db = 60.0f + rpm_factor + size_factor;
}

/* ---- Integrated demand side management (DSM) program ---------------------- */
typedef struct DSMProgram {
    int peak_time_rebate;
    int time_of_use_rate;
    int interruptible_load;
    int critical_peak_pricing;
    float financial_benefit_annual;
} DSMProgram;

static DSMProgram dsm = { 1, 1, 0, 1, 5000.0f };

static void evaluate_dsm_participation(float annual_savings, float incentive_available) {
    if (annual_savings > incentive_available) {
        dsm.peak_time_rebate = 1;
        dsm.financial_benefit_annual += annual_savings;
    }
}

/* ---- Zone reset schedules (setpoint scheduling) ---------------------- */
static void apply_zone_reset_schedule(int hour_of_day, int day_of_week) {
    static float base_heating_sp = 68.0f;
    static float base_cooling_sp = 76.0f;
    int i;

    if (day_of_week >= 5) {  /* Weekend */
        base_heating_sp = 62.0f;
        base_cooling_sp = 82.0f;
    } else if (hour_of_day >= 6 && hour_of_day < 22) {  /* Occupied */
        base_heating_sp = 70.0f;
        base_cooling_sp = 74.0f;
    } else {  /* Night setback */
        base_heating_sp = 62.0f;
        base_cooling_sp = 85.0f;
    }

    /* Apply to all zones */
    for (i = 0; i < NUM_ZONES; i++) {
        zones[i].occupancy_setpoint = (base_heating_sp + base_cooling_sp) / 2.0f;
    }
}

/* ---- Building automation system health monitoring ---------------------- */
typedef struct BASHealth {
    int heartbeat_count;
    int communication_errors;
    int database_errors;
    float system_uptime_pct;
} BASHealth;

static BASHealth bas_health = { 0, 0, 0, 99.95f };

static void check_bas_communication(void) {
    /* Simulate communication health */
    bas_health.heartbeat_count++;

    if (bas_health.heartbeat_count > 1000000) {
        bas_health.heartbeat_count = 0;  /* Reset counter */
    }
}

/* ---- Multi-zone coordination (cross-zone balancing) ---------------------- */
static void coordinate_zones_load_balancing(void) {
    float total_load = 0;
    float max_zone_load = 0;
    int i, max_zone = 0;

    /* Calculate zone loads */
    for (i = 0; i < NUM_ZONES; i++) {
        float zone_load = (zones[i].setpoint - zones[i].current_temp) * 100.0f;
        total_load += zone_load;

        if (zone_load > max_zone_load) {
            max_zone_load = zone_load;
            max_zone = i;
        }
    }

    /* Priority adjustment: focus on maximum load zone */
    if (max_zone_load > 10.0f) {
        zones[max_zone].pid_ctrl.kp = 1.2f;  /* Increase gain for fastest response */
    }
}

/* ---- Building electricity consumption prediction ---------------------- */
static float predict_daily_energy(float average_hourly_kwh) {
    return average_hourly_kwh * 24.0f;
}

static float predict_monthly_energy(float average_daily_kwh, int days_in_month) {
    return average_daily_kwh * days_in_month;
}

/* ---- Setpoint optimization for multi-objective control ---------------------- */
static float optimize_setpoint_comfort_vs_energy(float comfort_demand, float energy_price_multiplier) {
    float base_sp = 72.0f;
    float comfort_priority = 0.6f;  /* 60% comfort, 40% energy */

    float optimized = base_sp + (comfort_demand * comfort_priority) - (energy_price_multiplier * 1.0f);

    return optimized;
}

/* ============================================================ */



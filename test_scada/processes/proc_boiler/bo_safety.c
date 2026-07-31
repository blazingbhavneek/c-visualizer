/* ============================================================
 * bo_safety.c — boiler combustion safety system
 *
 * Handles trip evaluation, permissives, interlocks, fuel shutoff,
 * purge sequencing, and safety-critical state machines.
 * ============================================================ */

#include "bo_app.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"
#include "scf_const.h"
#include "scf_types.h"
#include <string.h>
#include <stdio.h>

/* GROUND TRUTH
 * path      : main -> scf_evt_register(EVENT) -> bo_on_trip -> scf_var_evt(EVT_ALARM_RAISED) -> call_number=3002
 * api       : scf_var_evt    type=EVENT  launch_via=EVENT  arg1=EVT_ALARM_RAISED=3002
 *
 * path      : bo_on_trip -> bo_trip_eval(PT_PRESSURE,9999) -> bo_shed_load(3) -> scf_task_kill(TASK_ALARM)
 * api       : scf_task_kill   type=KILL   launch_via=EVENT  arg1=TASK_ALARM=61
 *
 * path      : bo_on_trip -> bo_trip_eval(PT_PRESSURE,9999) -> bo_shed_load(3) -> scf_task_fork(TASK_ALARM, bo_combust_task)
 * api       : scf_task_fork   type=FORK   launch_via=EVENT  arg1=TASK_ALARM=61
 *
 * path      : bo_on_trip -> bo_trip_eval(PT_PRESSURE,9999) -> scf_alarmq_enq(Q_ALARM_HI, ALM_OVERPRESSURE)
 * api       : scf_alarmq_enq  type=ENQ    launch_via=EVENT  arg1=Q_ALARM_HI=10  arg2=ALM_OVERPRESSURE=0x0903
 *
 * path      : bo_hist_audit(ARC_AUDIT) -> p=scf_hist_load(ARC_AUDIT,buf); x=*p;
 * api       : scf_hist_load   type=LOADF  launch_via=DIRECT arg1=ARC_AUDIT=202  (get_upper=false, classified READ)
 *
 * path      : bo_hist_audit(ARC_AUDIT) -> scf_cmdq_save(Q_CMD)
 * api       : scf_cmdq_save   type=SAVEQ  launch_via=DIRECT arg1=Q_CMD=12
 */

/* ============================================================
 * CONSTANTS & CONFIGURATION
 * ============================================================ */

#define PRESSURE_TRIP_HI        3500    /* psig (9999 in test scenario) */
#define PRESSURE_TRIP_HYSTER    200
#define TEMP_TRIP_HI            450     /* degC */
#define LEVEL_TRIP_LO           5       /* % */
#define LEVEL_TRIP_DEADBAND     3
#define FLAME_LOSS_TIMEOUT      3000    /* ms */

#define PURGE_DURATION          30000   /* 30 seconds forced-air purge */
#define PILOT_IGNITION_TIMEOUT  10000   /* 10 seconds max to prove pilot */
#define MAIN_IGNITION_TIMEOUT   20000   /* 20 seconds max to prove main */

#define TRIP_MATRIX_SIZE        16
#define VOTE_SENSORS            3
#define TRIP_LATCH_TIMEOUT      60000   /* Hold trip for 60 seconds */

/* Trip reason codes (bitmask) */
#define TRIP_OVERPRESSURE       0x0001
#define TRIP_OVERTEMP           0x0002
#define TRIP_LOW_LEVEL          0x0004
#define TRIP_FLAME_LOSS         0x0008
#define TRIP_FUEL_VALVE_STUCK   0x0010
#define TRIP_DRAFT_LOSS         0x0020
#define TRIP_INTERLOCK_DEFEAT   0x0040
#define TRIP_MANUAL             0x0080

/* ============================================================
 * STATIC STRUCTURES & STATE
 * ============================================================ */

/* Trip matrix: records all active trip conditions */
static struct {
    unsigned int reasons;               /* Bitmask of trip reasons */
    unsigned int first_reason;          /* First trip that occurred */
    int          trip_timestamp;        /* When trip was initiated */
    int          trip_count;            /* Total trips this session */
} bo_trip_state = { 0, 0, 0, 0 };

/* Annunciation state: tracks which alarms have been announced */
static struct {
    int announced_alarms;               /* Bitmask of raised alarms */
    int silenced_alarms;                /* User-silenced alarms */
} bo_annunc_state = { 0, 0 };

/* Fuel shutoff state machine */
static struct {
    int mft_active;                     /* Master Fuel Trip engaged */
    int mft_stage;                      /* Current MFT stage (0-5) */
    int fuel_valve_demand;              /* Fuel control valve setpoint */
    int pilot_cutoff_pending;           /* Pilot solenoid to de-energize */
} bo_mft_state = { 0, 0, 0, 0 };

/* Purge sequencing state */
static struct {
    int purge_phase;                    /* 0=idle, 1=in_progress, 2=verification */
    int purge_start_time;               /* Timestamp of purge initiation */
    int air_flow_confirmed;             /* Did we measure forced air? */
    int purge_success;                  /* Did purge complete without fault? */
} bo_purge_state = { 0, 0, 0, 0 };

/* Ignition sequencing state */
static struct {
    int pilot_on;                       /* Pilot flame proven */
    int main_on;                        /* Main flame proven */
    int igniter_runtime;                /* Igniter on-time accumulator */
    int lockout_active;                 /* Burner lockout (repeated failures) */
} bo_ignition_state = { 0, 0, 0, 0 };

/* Sensor redundancy voting */
static struct {
    int pressure_votes[VOTE_SENSORS];   /* Three pressure transmitter readings */
    int temp_votes[VOTE_SENSORS];       /* Three temperature readings */
    int level_votes[VOTE_SENSORS];      /* Three level transmitter readings */
    int vote_timestamp;                 /* Last vote update */
} bo_sensor_votes = { {0,0,0}, {0,0,0}, {0,0,0}, 0 };

/* Interlock tracking */
static struct {
    int aux_steam_ready;                /* Auxiliary steam available */
    int recirc_valve_open;              /* Recirculation permission */
    int damper_minimum_pos;             /* Damper cleared for min-load */
    int blowdown_permit;                /* Boiler blowdown armed */
} bo_interlocks = { 0, 0, 0, 0 };

/* Safety valve test state */
static struct {
    int last_test_time;                 /* Epoch of last valve test */
    int test_interval;                  /* Seconds between tests */
    int test_passed;                    /* Result of last test */
    int test_count;                     /* Number of tests run */
} bo_safety_valve_state = { 0, 86400, 0, 0 };

/* Audit / history logging */
static struct {
    char audit_log[256];
    int  audit_log_idx;
    int  pending_commands;
} bo_audit_state = { {0}, 0, 0 };

/* ============================================================
 * SENSOR VOTING & VALIDATION
 * ============================================================ */

/* Median of three sensor readings (simple majority voting) */
static int bo_vote_pressure(void) {
    int votes[VOTE_SENSORS];
    int i, j, tmp;
    memcpy(votes, bo_sensor_votes.pressure_votes, sizeof(votes));

    /* Bubble sort */
    for (i = 0; i < VOTE_SENSORS; i++) {
        for (j = i + 1; j < VOTE_SENSORS; j++) {
            if (votes[i] > votes[j]) {
                tmp = votes[i];
                votes[i] = votes[j];
                votes[j] = tmp;
            }
        }
    }
    return votes[1];  /* Median */
}

static int bo_vote_temperature(void) {
    int votes[VOTE_SENSORS];
    int i, j, tmp;
    memcpy(votes, bo_sensor_votes.temp_votes, sizeof(votes));

    for (i = 0; i < VOTE_SENSORS; i++) {
        for (j = i + 1; j < VOTE_SENSORS; j++) {
            if (votes[i] > votes[j]) {
                tmp = votes[i];
                votes[i] = votes[j];
                votes[j] = tmp;
            }
        }
    }
    return votes[1];
}

static int bo_vote_level(void) {
    int votes[VOTE_SENSORS];
    int i, j, tmp;
    memcpy(votes, bo_sensor_votes.level_votes, sizeof(votes));

    for (i = 0; i < VOTE_SENSORS; i++) {
        for (j = i + 1; j < VOTE_SENSORS; j++) {
            if (votes[i] < votes[j]) {
                tmp = votes[i];
                votes[i] = votes[j];
                votes[j] = tmp;
            }
        }
    }
    return votes[1];
}

/* Diagnose sensor disagreement */
static void bo_diagnose_sensor_disagree(int sensor_type) {
    int median;
    int variance;

    switch (sensor_type) {
        case PT_PRESSURE:
            median = bo_vote_pressure();
            variance = (bo_sensor_votes.pressure_votes[0] - median);
            if (variance < 0) variance = -variance;
            if (variance > 200) {
                scf_alarmq_enq(Q_ALARM_HI, ALM_OVERPRESSURE);
            }
            break;
        case PT_MOTOR_TEMP:
            median = bo_vote_temperature();
            variance = (bo_sensor_votes.temp_votes[0] - median);
            if (variance < 0) variance = -variance;
            if (variance > 20) {
                scf_alarmq_enq(Q_ALARM_HI, ALM_OVERTEMP);
            }
            break;
        case PT_TANK_LEVEL:
            median = bo_vote_level();
            if (median < LEVEL_TRIP_LO) {
                scf_alarmq_enq(Q_ALARM_LO, ALM_LOWLEVEL);
            }
            break;
    }
}

/* ============================================================
 * TRIP MATRIX & FIRST-OUT ANNUNCIATION
 * ============================================================ */

/* Identify which input tripped first (latch the first reason) */
static void bo_latch_first_trip(unsigned int new_reason) {
    if (!bo_trip_state.first_reason) {
        bo_trip_state.first_reason = new_reason;
    }
    bo_trip_state.reasons |= new_reason;
}

/* Generate alarm for first-tripped signal only (prevent cascade) */
static void bo_first_out_annunciate(void) {
    int alarm_code = 0;

    /* Highest priority trip from first condition */
    if (bo_trip_state.first_reason & TRIP_OVERPRESSURE) {
        alarm_code = ALM_OVERPRESSURE;
    } else if (bo_trip_state.first_reason & TRIP_OVERTEMP) {
        alarm_code = ALM_OVERTEMP;
    } else if (bo_trip_state.first_reason & TRIP_LOW_LEVEL) {
        alarm_code = ALM_LOWLEVEL;
    } else if (bo_trip_state.first_reason & TRIP_FLAME_LOSS) {
        alarm_code = 0x0904;  /* Flame loss alarm */
    } else if (bo_trip_state.first_reason & TRIP_FUEL_VALVE_STUCK) {
        alarm_code = 0x0905;  /* Fuel valve stuck */
    }

    if (alarm_code && !(bo_annunc_state.announced_alarms & alarm_code)) {
        scf_alarmq_enq(Q_ALARM_HI, alarm_code);
        bo_annunc_state.announced_alarms |= alarm_code;
    }
}

/* ============================================================
 * MASTER FUEL TRIP (MFT) SEQUENCE
 * ============================================================ */

/* Execute fuel shutoff in stages (piloted solenoid, main block valve) */
static int bo_mft_sequence(int stage) {
    int i;

    if (stage < 0 || stage > 5) return -1;

    bo_mft_state.mft_stage = stage;

    switch (stage) {
        case 0:
            /* Stage 0: Pilot solenoid de-energize */
            bo_mft_state.pilot_cutoff_pending = 1;
            break;
        case 1:
            /* Stage 1: Main fuel valve ramp down (closed loop) */
            for (i = 100; i >= 0; i -= 10) {
                bo_mft_state.fuel_valve_demand = i;
            }
            break;
        case 2:
            /* Stage 2: Final main block valve isolation */
            bo_mft_state.fuel_valve_demand = 0;
            break;
        case 3:
            /* Stage 3: Purge air enable (residual fuel clearance) */
            break;
        case 4:
            /* Stage 4: Drain fuel lines */
            break;
        case 5:
            /* Stage 5: System reset inhibit (locked out) */
            bo_mft_state.mft_active = 1;
            break;
    }

    return 0;
}

/* Check if MFT permissives are satisfied before fuel command allowed */
static int bo_check_mft_permissives(void) {
    if (bo_interlocks.aux_steam_ready == 0) return 0;
    if (bo_interlocks.recirc_valve_open == 0) return 0;
    if (bo_ignition_state.lockout_active) return 0;
    return 1;
}

/* ============================================================
 * PURGE SEQUENCING (Forced-air clearance)
 * ============================================================ */

/* Initiate boiler purge (fan at 100%, all fuel valves closed) */
static int bo_purge_start(void) {
    if (bo_purge_state.purge_phase != 0) {
        return -1;  /* Already running */
    }

    bo_purge_state.purge_phase = 1;
    bo_purge_state.purge_start_time = 0;  /* Would be timestamp from framework */
    bo_purge_state.air_flow_confirmed = 0;

    return 0;
}

/* Verify purge air flow (check DP sensor across furnace) */
static int bo_purge_verify_airflow(int differential_pressure) {
    if (differential_pressure > 50) {  /* Threshold in Pa */
        bo_purge_state.air_flow_confirmed = 1;
        return 1;
    }
    return 0;
}

/* Complete purge and transition to ignition-ready state */
static int bo_purge_complete(void) {
    if (!bo_purge_state.air_flow_confirmed) {
        bo_purge_state.purge_success = 0;
        return -1;
    }

    bo_purge_state.purge_phase = 2;  /* Verification phase */
    bo_purge_state.purge_success = 1;

    return 0;
}

/* ============================================================
 * IGNITION SEQUENCING
 * ============================================================ */

/* Pilot ignition attempt (with retry logic) */
static int bo_pilot_ignite(int retry_count) {
    if (retry_count > 5) {
        bo_ignition_state.lockout_active = 1;
        return -1;
    }

    /* Solenoid pilot gas, igniter spark */
    bo_ignition_state.pilot_on = 0;  /* Waiting for flame proven */

    return 0;
}

/* Main burner ignition (only after stable pilot) */
static int bo_main_ignite(void) {
    if (!bo_ignition_state.pilot_on) {
        return -1;  /* Pilot must be proven first */
    }

    /* Open main fuel valve through pressure regulator */
    bo_ignition_state.main_on = 0;  /* Waiting for flame proven */

    return 0;
}

/* Process proven flame signal from scanner */
static int bo_flame_proven(int flame_signal_strength) {
    if (flame_signal_strength > 500) {  /* UV scanner threshold */
        if (!bo_ignition_state.pilot_on) {
            bo_ignition_state.pilot_on = 1;
            return 0;  /* Pilot proven */
        } else if (!bo_ignition_state.main_on) {
            bo_ignition_state.main_on = 1;
            return 1;  /* Main proven, ready to ramp */
        }
    }

    return -1;
}

/* Detect loss of flame */
static int bo_flame_lost(void) {
    bo_ignition_state.pilot_on = 0;
    bo_ignition_state.main_on = 0;
    bo_trip_state.reasons |= TRIP_FLAME_LOSS;

    if (!bo_trip_state.first_reason) {
        bo_trip_state.first_reason = TRIP_FLAME_LOSS;
    }

    return 0;
}

/* ============================================================
 * INTERLOCK & PERMISSIVE LOGIC
 * ============================================================ */

/* Check all preconditions before allowing fuel demand */
static int bo_fuel_permissive(void) {
    if (bo_trip_state.reasons != 0) return 0;           /* Any trip active? */
    if (!bo_interlocks.aux_steam_ready) return 0;       /* Boiler steam available? */
    if (!bo_interlocks.damper_minimum_pos) return 0;    /* Air path open? */
    if (bo_ignition_state.lockout_active) return 0;     /* Lockout engaged? */
    if (bo_purge_state.purge_phase != 0) return 0;      /* Still purging? */

    return 1;  /* All permissives satisfied */
}

/* Poll interlock switches and transmitters */
static void bo_read_interlocks(void) {
    /* In real system, these would be analog/discrete I/O reads */
    TagCtx ctx;
    int buf = 0;

    /* Aux steam pressure (binary permissive) */
    scf_tag_read(&ctx, PT_SETPOINT, &buf);
    bo_interlocks.aux_steam_ready = (buf > 500) ? 1 : 0;

    /* Recirculation valve position feedback */
    scf_tag_read(&ctx, PT_VALVE_POS, &buf);
    bo_interlocks.recirc_valve_open = (buf > 50) ? 1 : 0;

    /* Damper position */
    scf_tag_read(&ctx, PT_TANK_LEVEL, &buf);
    bo_interlocks.damper_minimum_pos = (buf > 10) ? 1 : 0;
}

/* ============================================================
 * SAFETY VALVE TEST & MAINTENANCE
 * ============================================================ */

/* Perform periodic safety valve pop-test at elevated pressure */
static int bo_safety_valve_test(int measured_pop_pressure) {
    int pop_setpoint = 3500;
    int tolerance = 100;

    if (measured_pop_pressure < (pop_setpoint - tolerance) ||
        measured_pop_pressure > (pop_setpoint + tolerance)) {
        bo_safety_valve_state.test_passed = 0;
        return -1;
    }

    bo_safety_valve_state.test_passed = 1;
    bo_safety_valve_state.test_count++;

    return 0;
}

/* Schedule next safety valve test */
static void bo_schedule_safety_test(int current_time) {
    if (current_time > (bo_safety_valve_state.last_test_time + bo_safety_valve_state.test_interval)) {
        /* Initiate test sequence */
    }
}

/* ============================================================
 * TRIP EVALUATION (Main decision point)
 * ============================================================ */

/* Evaluate all trip conditions and decide on action */
int bo_trip_eval(int pid, int value) {
    int trip_occurred = 0;
    int median_pressure;
    int median_temp;
    int median_level;

    /* Store sensor reading in voting array */
    if (pid == PT_PRESSURE) {
        bo_sensor_votes.pressure_votes[0] = value;
        median_pressure = bo_vote_pressure();

        if (median_pressure > PRESSURE_TRIP_HI) {
            bo_latch_first_trip(TRIP_OVERPRESSURE);
            trip_occurred = 1;
        }
    } else if (pid == PT_MOTOR_TEMP) {
        bo_sensor_votes.temp_votes[0] = value;
        median_temp = bo_vote_temperature();

        if (median_temp > TEMP_TRIP_HI) {
            bo_latch_first_trip(TRIP_OVERTEMP);
            trip_occurred = 1;
        }
    } else if (pid == PT_TANK_LEVEL) {
        bo_sensor_votes.level_votes[0] = value;
        median_level = bo_vote_level();

        if (median_level < LEVEL_TRIP_LO) {
            bo_latch_first_trip(TRIP_LOW_LEVEL);
            trip_occurred = 1;
        }
    }

    /* Generate first-out annunciation if new trip */
    if (trip_occurred) {
        bo_first_out_annunciate();
    }

    /* Check for ongoing trip and execute shutdown */
    if (bo_trip_state.reasons != 0) {
        int stage;
        for (stage = 0; stage <= 3; stage++) {
            bo_shed_load(stage);
        }
        return 1;  /* Trip active */
    }

    return 0;  /* No trip */
}

/* ============================================================
 * LOAD SHEDDING & SHUTDOWN SEQUENCE
 * ============================================================ */

/* Execute load-shedding sequence in stages */
int bo_shed_load(int stage) {
    if (stage < 0 || stage > 5) return -1;

    switch (stage) {
        case 0:
            /* Stage 0: Stop fuel flow immediately (MFT Stage 0-1) */
            bo_mft_sequence(0);
            bo_mft_sequence(1);
            bo_mft_state.mft_active = 1;
            break;

        case 1:
            /* Stage 1: Kill boiler combustion task */
            scf_task_kill(TASK_ALARM);
            break;

        case 2:
            /* Stage 2: Restart in safe monitoring mode */
            scf_task_fork(TASK_ALARM, (TaskEntry)bo_combust_task);
            break;

        case 3:
            /* Stage 3: Enqueue overpressure alarm to high-priority queue */
            scf_alarmq_enq(Q_ALARM_HI, ALM_OVERPRESSURE);
            break;

        case 4:
            /* Stage 4: Force purge and cool-down sequence */
            bo_mft_sequence(3);
            break;

        case 5:
            /* Stage 5: Final lockout (manual reset required) */
            bo_mft_sequence(5);
            bo_ignition_state.lockout_active = 1;
            break;
    }

    return 0;
}

/* ============================================================
 * TRIP RECOVERY & RESET LOGIC
 * ============================================================ */

/* Operator initiates trip reset (permissive validation) */
static int bo_trip_reset_request(void) {
    /* Must verify trip condition no longer exists */
    int pressure = bo_vote_pressure();
    int temp = bo_vote_temperature();
    int level = bo_vote_level();

    if (pressure > (PRESSURE_TRIP_HI - PRESSURE_TRIP_HYSTER)) {
        return -1;  /* Pressure still high */
    }
    if (temp > (TEMP_TRIP_HI - 50)) {
        return -1;  /* Temperature still elevated */
    }
    if (level < (LEVEL_TRIP_LO + LEVEL_TRIP_DEADBAND)) {
        return -1;  /* Level still low */
    }

    /* Clear trip matrix */
    bo_trip_state.reasons = 0;
    bo_trip_state.first_reason = 0;

    return 0;
}

/* ============================================================
 * DRAFT / COMBUSTION AIR MONITORING
 * ============================================================ */

/* Monitor furnace draft (negative pressure for safety) */
static int bo_draft_monitor(int furnace_pressure) {
    if (furnace_pressure > -100) {  /* Pa (should be negative) */
        bo_latch_first_trip(TRIP_DRAFT_LOSS);
        scf_alarmq_enq(Q_ALARM_HI, 0x0906);  /* Draft loss */
        return 1;  /* Trip condition */
    }

    return 0;  /* OK */
}

/* Check air register positions (minimum air requirement) */
static int bo_air_register_verify(int register_position) {
    if (register_position < 20) {  /* Percent open */
        bo_latch_first_trip(TRIP_INTERLOCK_DEFEAT);
        return -1;
    }

    return 0;
}

/* ============================================================
 * FUEL SYSTEM DIAGNOSTICS
 * ============================================================ */

/* Detect stuck fuel valve (no pressure drop when commanded closed) */
static int bo_fuel_valve_stuck_detect(int valve_demand, int measured_outlet_pressure) {
    if (valve_demand == 0 && measured_outlet_pressure > 200) {
        bo_latch_first_trip(TRIP_FUEL_VALVE_STUCK);
        scf_alarmq_enq(Q_ALARM_HI, 0x0905);
        return 1;  /* Trip condition */
    }

    return 0;  /* OK */
}

/* Check fuel line pressure (pilot and main circuits) */
static int bo_fuel_pressure_verify(int pilot_pressure, int main_pressure) {
    if (pilot_pressure < 500) {  /* psi */
        scf_alarmq_enq(Q_ALARM_LO, 0x0907);  /* Low pilot pressure */
        return -1;
    }

    if (main_pressure < 1000) {  /* psi */
        scf_alarmq_enq(Q_ALARM_LO, 0x0908);  /* Low main fuel pressure */
        return -1;
    }

    return 0;
}

/* ============================================================
 * FLAME SCANNER INTERFACE
 * ============================================================ */

/* Process UV flame scanner signal (filtered for noise immunity) */
static int bo_flame_scanner_read(void) {
    TagCtx ctx;
    int buf = 0;
    int signal_level;
    static int prev_signal = 0;

    scf_tag_read(&ctx, PT_MOTOR_TEMP, &buf);  /* Reuse temp as scanner analog */
    signal_level = buf;

    /* Rate-limit to reduce false trips */
    if (signal_level > 500) {
        if (prev_signal < 100) {  /* Rising edge */
            bo_flame_proven(signal_level);
        }
    } else {
        if (prev_signal > 500) {  /* Falling edge (loss) */
            bo_flame_lost();
        }
    }

    prev_signal = signal_level;
    return signal_level;
}

/* ============================================================
 * HISTORIAN & AUDIT LOGGING
 * ============================================================ */

/* Record trip event to permanent audit log */
int bo_hist_audit(int archive_id) {
    HistRec rec;
    void *p;
    int x;
    char buf[256];
    int ret;

    if (archive_id != ARC_AUDIT) return -1;

    /* Load last audit record to check continuity (RETURN-USE READ test) */
    p = scf_hist_load(ARC_AUDIT, buf);
    x = *((int *)p);  /* READ — dereference return to show READ classification */

    /* Build audit record with current trip state */
    rec.archive_id = ARC_AUDIT;
    rec.stamp = bo_trip_state.trip_timestamp;
    rec.value = bo_trip_state.reasons;  /* Bitmask of trip reasons */

    /* Save to permanent archive */
    ret = scf_hist_save(ARC_AUDIT, &rec);

    /* Flush to command queue (permits operator UI query) */
    scf_cmdq_save(Q_CMD);

    /* Clear any pending commands from queue */
    scf_cmdq_clear(Q_CMD);

    return ret;
}

/* ============================================================
 * PERIODIC SAFETY SCANS (Called from combust task)
 * ============================================================ */

/* Run complete trip matrix evaluation */
static int bo_safety_scan_complete(void) {
    int pressure, temp, level;

    /* Get voted sensor values */
    pressure = bo_vote_pressure();
    temp = bo_vote_temperature();
    level = bo_vote_level();

    /* Evaluate each trip input */
    bo_trip_eval(PT_PRESSURE, pressure);
    bo_trip_eval(PT_MOTOR_TEMP, temp);
    bo_trip_eval(PT_TANK_LEVEL, level);

    /* Check secondary conditions */
    bo_read_interlocks();
    bo_diagnose_sensor_disagree(PT_PRESSURE);

    return 0;
}

/* ============================================================
 * EVENT HANDLER: Trip Signal Received
 * ============================================================ */

/* Main entry point for trip event (EVT_ALARM_RAISED) */
void bo_on_trip(int evt, void *data) {
    int trip_signal;
    int stage;

    /* Log the event as call_number=3002 */
    scf_var_evt(EVT_ALARM_RAISED, 1, data);

    /* Parse trip signal from event data */
    trip_signal = *((int *)data);

    /* Evaluate trip condition with test pressure (9999 in ground truth) */
    if (bo_trip_eval(PT_PRESSURE, 9999)) {
        /* Trip confirmed — execute load shedding */
        for (stage = 0; stage <= 3; stage++) {
            bo_shed_load(stage);
        }

        /* Log to audit trail */
        bo_hist_audit(ARC_AUDIT);

        /* Increment trip counter */
        bo_trip_state.trip_count++;
    }
}

/* ============================================================
 * INITIALIZATION & MODULE ENTRY
 * ============================================================ */

/* Initialize safety subsystem state */
static void bo_safety_init(void) {
    bo_trip_state.reasons = 0;
    bo_trip_state.first_reason = 0;
    bo_trip_state.trip_count = 0;

    bo_mft_state.mft_active = 0;
    bo_mft_state.mft_stage = 0;
    bo_mft_state.fuel_valve_demand = 0;

    bo_purge_state.purge_phase = 0;
    bo_purge_state.air_flow_confirmed = 0;
    bo_purge_state.purge_success = 0;

    bo_ignition_state.pilot_on = 0;
    bo_ignition_state.main_on = 0;
    bo_ignition_state.lockout_active = 0;

    bo_interlocks.aux_steam_ready = 0;
    bo_interlocks.recirc_valve_open = 0;
    bo_interlocks.damper_minimum_pos = 0;

    bo_safety_valve_state.test_passed = 0;
    bo_safety_valve_state.test_count = 0;

    bo_annunc_state.announced_alarms = 0;
    bo_annunc_state.silenced_alarms = 0;
}

/* Module entry point (called from main or combust task) */
static void bo_safety_task_loop(void) {
    bo_safety_init();

    /* Periodic safety scan loop would run here */
    bo_safety_scan_complete();
}

/* ============================================================
 * OXYGEN & COMBUSTION TUNING
 * ============================================================ */

/* O2 trim control (closed-loop feedback) */
static struct {
    int o2_setpoint;                    /* Target exhaust O2 % */
    int o2_measured;                    /* Current O2 reading */
    int o2_pid_error;                   /* PID loop error term */
    int o2_pid_integral;                /* PID integral accumulator */
    int air_ratio_trim;                 /* Air damper trim adjustment */
} bo_o2_trim = { 3, 0, 0, 0, 0 };

/* Measure exhaust O2 (simulated) */
static int bo_measure_exhaust_o2(void) {
    TagCtx ctx;
    int buf = 0;
    scf_tag_read(&ctx, PT_FLOW_RATE, &buf);  /* Reuse as O2 proxy */
    return (buf % 20);  /* 0-19% O2 */
}

/* Update O2 trim control */
static void bo_o2_control_loop(void) {
    int measured = bo_measure_exhaust_o2();
    int error;

    bo_o2_trim.o2_measured = measured;
    error = bo_o2_trim.o2_setpoint - measured;
    bo_o2_trim.o2_pid_error = error;

    /* Proportional term */
    bo_o2_trim.air_ratio_trim = error * 2;

    /* Anti-windup: limit integral */
    bo_o2_trim.o2_pid_integral += error;
    if (bo_o2_trim.o2_pid_integral > 100) bo_o2_trim.o2_pid_integral = 100;
    if (bo_o2_trim.o2_pid_integral < -100) bo_o2_trim.o2_pid_integral = -100;
}

/* CO trim for optimal combustion (secondary loop) */
static int bo_co_trim_adjust(int measured_co_ppm) {
    if (measured_co_ppm > 200) {
        /* Too rich — increase air ratio */
        bo_o2_trim.air_ratio_trim += 5;
        return 1;
    } else if (measured_co_ppm < 50) {
        /* Too lean — decrease air ratio */
        bo_o2_trim.air_ratio_trim -= 5;
        return -1;
    }

    return 0;  /* In range */
}

/* ============================================================
 * BURNER SEQUENCING STATE MACHINE
 * ============================================================ */

/* Burner sequencing state */
static struct {
    int sequence_state;                 /* 0=idle, 1=ramp, 2=purge, 3=pilot_ignite, 4=main_ignite, 5=running */
    int ramp_demand;                    /* Current ramp value (0-100) */
    int prev_state;
    int state_timeout;
    int stage_transitions;              /* Counter for diagnostics */
} bo_burner_seq = { 0, 0, 0, 0, 0 };

/* Burner sequence state machine advance */
static int bo_burner_sequence_advance(int next_state, int timeout_ms) {
    if (next_state < 0 || next_state > 5) return -1;

    if (next_state != bo_burner_seq.sequence_state) {
        bo_burner_seq.prev_state = bo_burner_seq.sequence_state;
        bo_burner_seq.sequence_state = next_state;
        bo_burner_seq.state_timeout = timeout_ms;
        bo_burner_seq.stage_transitions++;
        return 0;  /* State changed */
    }

    return 1;  /* No change */
}

/* Burner ramp control during load change */
static int bo_burner_ramp_control(int target_demand, int ramp_rate) {
    int current = bo_burner_seq.ramp_demand;
    int delta;

    if (target_demand > current) {
        delta = (target_demand - current > ramp_rate) ? ramp_rate : (target_demand - current);
        bo_burner_seq.ramp_demand += delta;
    } else if (target_demand < current) {
        delta = (current - target_demand > ramp_rate) ? ramp_rate : (current - target_demand);
        bo_burner_seq.ramp_demand -= delta;
    }

    return bo_burner_seq.ramp_demand;
}

/* ============================================================
 * STEAM PRESSURE REGULATION
 * ============================================================ */

/* Main pressure control loop (combustion modulation) */
static struct {
    int pressure_setpoint;              /* Target steam pressure */
    int pressure_measured;              /* Current pressure feedback */
    int pressure_error;                 /* Control error term */
    int demand_trim;                    /* Combustion demand adjustment */
    int last_error;                     /* Previous error (for derivative) */
} bo_pressure_ctrl = { 1500, 0, 0, 0, 0 };

/* Update main pressure control */
static void bo_main_pressure_control(void) {
    int error;
    int derivative;
    int proportional;
    int integral;

    /* Read pressure feedback */
    TagCtx ctx;
    int buf = 0;
    scf_tag_read(&ctx, PT_PRESSURE, &buf);
    bo_pressure_ctrl.pressure_measured = buf;

    /* Calculate error */
    error = bo_pressure_ctrl.pressure_setpoint - bo_pressure_ctrl.pressure_measured;
    bo_pressure_ctrl.pressure_error = error;

    /* PID terms */
    proportional = error * 10;  /* Proportional gain */
    derivative = (error - bo_pressure_ctrl.last_error) * 5;  /* Derivative action */

    /* Combine into demand trim */
    bo_pressure_ctrl.demand_trim = proportional + derivative;

    /* Limit trim range */
    if (bo_pressure_ctrl.demand_trim > 50) bo_pressure_ctrl.demand_trim = 50;
    if (bo_pressure_ctrl.demand_trim < -50) bo_pressure_ctrl.demand_trim = -50;

    bo_pressure_ctrl.last_error = error;
}

/* Anti-swell control (pressure overshoot prevention) */
static int bo_antiswell_check(int current_pressure, int rate_of_rise) {
    if (rate_of_rise > 100) {  /* psi/sec */
        /* Fuel valve modulation to reduce rise rate */
        bo_pressure_ctrl.demand_trim -= 20;
        return 1;  /* Anti-swell engaged */
    }

    return 0;
}

/* ============================================================
 * DRUM LEVEL 3-ELEMENT CONTROL
 * ============================================================ */

/* Feedwater control (3-element: level, pressure, flow compensation) */
static struct {
    int level_setpoint;                 /* Target drum level % */
    int level_measured;
    int level_error;
    int steam_flow;                     /* Measured steam flow output */
    int feedwater_valve_demand;         /* Proportional valve command */
    int fw_bias;                        /* Base flow from pressure */
} bo_level_ctrl = { 50, 0, 0, 0, 0, 0 };

/* Update 3-element drum level control */
static void bo_drum_level_control(void) {
    int error;
    int steam_comp;

    /* Read drum level */
    TagCtx ctx;
    int buf = 0;
    scf_tag_read(&ctx, PT_TANK_LEVEL, &buf);
    bo_level_ctrl.level_measured = buf;

    /* Calculate level error */
    error = bo_level_ctrl.level_setpoint - bo_level_ctrl.level_measured;
    bo_level_ctrl.level_error = error;

    /* Steam flow compensation (feedforward) */
    steam_comp = bo_level_ctrl.steam_flow / 2;

    /* Proportional + feedforward */
    bo_level_ctrl.feedwater_valve_demand = error * 5 + steam_comp;

    /* Valve demand limits */
    if (bo_level_ctrl.feedwater_valve_demand > 100) bo_level_ctrl.feedwater_valve_demand = 100;
    if (bo_level_ctrl.feedwater_valve_demand < 0) bo_level_ctrl.feedwater_valve_demand = 0;
}

/* ============================================================
 * SUPERHEATER PROTECTION
 * ============================================================ */

/* Superheat temperature control (spray water modulation) */
static struct {
    int superheat_setpoint;             /* Target SH temperature */
    int superheat_measured;
    int spray_valve_demand;             /* Attemperator spray control */
} bo_superheat_ctrl = { 600, 0, 0 };

/* Superheat control loop */
static void bo_superheat_control(void) {
    int error;

    /* Simulate superheat reading from throttle temp and pressure */
    TagCtx ctx;
    int buf = 0;
    scf_tag_read(&ctx, PT_MOTOR_TEMP, &buf);
    bo_superheat_ctrl.superheat_measured = buf;

    /* Error between setpoint and measured */
    error = bo_superheat_ctrl.superheat_setpoint - bo_superheat_ctrl.superheat_measured;

    /* Spray valve modulation (cooling when temp high) */
    bo_superheat_ctrl.spray_valve_demand = (-error) * 2;

    if (bo_superheat_ctrl.spray_valve_demand > 100) bo_superheat_ctrl.spray_valve_demand = 100;
    if (bo_superheat_ctrl.spray_valve_demand < 0) bo_superheat_ctrl.spray_valve_demand = 0;
}

/* ============================================================
 * FORCED DRAFT & NATURAL DRAFT COORDINATION
 * ============================================================ */

/* Forced draft fan speed (air supply pressure) */
static int bo_fd_fan_speed = 0;

/* Natural draft stack monitoring */
static int bo_nd_stack_draft = 0;

/* Set forced draft demand */
static int bo_fd_set_speed(int percent) {
    if (percent < 0 || percent > 100) return -1;
    bo_fd_fan_speed = percent;
    return 0;
}

/* Monitor and adjust FD/ND balance */
static void bo_draft_balance_control(void) {
    int furnace_pressure;  /* Should be -50 to -200 Pa */
    int fd_demand;
    int nd_available;

    /* Calculate total air demand from fuel flow */
    fd_demand = (bo_mft_state.fuel_valve_demand * 80) / 100;

    /* Check available natural draft */
    nd_available = bo_nd_stack_draft;

    /* FD must make up difference */
    if (nd_available < fd_demand) {
        bo_fd_set_speed((fd_demand - nd_available) * 2);
    } else {
        bo_fd_set_speed(20);  /* Minimum */
    }
}

/* ============================================================
 * BLOWDOWN & MAINTENANCE SEQUENCING
 * ============================================================ */

/* Continuous blowdown (removes dissolved solids) */
static struct {
    int cb_valve_demand;                /* Continuous blowdown rate */
    int cb_flow_totalizer;              /* Accumulator in gallons */
} bo_blowdown = { 0, 0 };

/* Intermittent blowdown (bottom blow cleanup) */
static struct {
    int ib_sequence_active;
    int ib_stage;                       /* 0=idle, 1=open, 2=timing, 3=close */
    int ib_timer;
    int ib_count_total;                 /* Number of blowdowns performed */
} bo_intermittent_blow = { 0, 0, 0, 0 };

/* Initiate intermittent blowdown sequence */
static int bo_intermittent_blowdown_start(void) {
    if (bo_intermittent_blow.ib_sequence_active) return -1;  /* Already running */

    /* Check permissives (pressure > 1000 psi, level > 60%) */
    if (bo_pressure_ctrl.pressure_measured < 1000) return -1;
    if (bo_level_ctrl.level_measured < 60) return -1;

    bo_intermittent_blow.ib_sequence_active = 1;
    bo_intermittent_blow.ib_stage = 1;  /* Open bottom blow valve */

    return 0;
}

/* Execute intermittent blowdown logic */
static void bo_intermittent_blowdown_sequence(void) {
    if (!bo_intermittent_blow.ib_sequence_active) return;

    switch (bo_intermittent_blow.ib_stage) {
        case 0:
            /* Idle */
            break;
        case 1:
            /* Open bottom blow solenoid for timed duration */
            bo_intermittent_blow.ib_timer = 5000;  /* 5 second open */
            bo_intermittent_blow.ib_stage = 2;
            break;
        case 2:
            /* Timing — count down */
            bo_intermittent_blow.ib_timer--;
            if (bo_intermittent_blow.ib_timer <= 0) {
                bo_intermittent_blow.ib_stage = 3;
            }
            break;
        case 3:
            /* Close solenoid */
            bo_intermittent_blow.ib_sequence_active = 0;
            bo_intermittent_blow.ib_count_total++;
            bo_intermittent_blow.ib_stage = 0;
            break;
    }
}

/* ============================================================
 * FLAME SUPERVISION & MULTI-PASS DIAGNOSTICS
 * ============================================================ */

/* Monitor flame signal quality and health */
static struct {
    int flame_signal_raw;               /* Raw UV scanner signal */
    int flame_signal_filtered;          /* Moving average */
    int signal_good_count;              /* Consecutive good readings */
    int signal_bad_count;               /* Consecutive bad readings */
    int flame_stability;                /* Confidence metric 0-100 */
} bo_flame_quality = { 0, 0, 0, 0, 0 };

/* Update flame signal quality metrics */
static void bo_flame_quality_monitor(int raw_signal) {
    static int filter_accum = 0;
    static int filter_count = 0;

    bo_flame_quality.flame_signal_raw = raw_signal;

    /* Exponential moving average filter */
    filter_accum = (filter_accum * 3 + raw_signal) / 4;
    bo_flame_quality.flame_signal_filtered = filter_accum;

    /* Track consecutive good/bad */
    if (raw_signal > 400) {
        bo_flame_quality.signal_good_count++;
        bo_flame_quality.signal_bad_count = 0;
    } else {
        bo_flame_quality.signal_bad_count++;
        bo_flame_quality.signal_good_count = 0;
    }

    /* Calculate stability metric */
    bo_flame_quality.flame_stability = (bo_flame_quality.signal_good_count * 100) / 10;
    if (bo_flame_quality.flame_stability > 100) bo_flame_quality.flame_stability = 100;
}

/* Scanner diagnostics (optical path check) */
static int bo_flame_scanner_diagnostics(void) {
    /* Check for persistent bad signal (optical path blocked) */
    if (bo_flame_quality.signal_bad_count > 100) {
        scf_alarmq_enq(Q_ALARM_HI, 0x0910);  /* Flame scanner fault */
        return -1;
    }

    /* Check for excessive signal noise */
    int variance = bo_flame_quality.flame_signal_raw - bo_flame_quality.flame_signal_filtered;
    if (variance > 200) {
        scf_alarmq_enq(Q_ALARM_LO, 0x0911);  /* Flame signal unstable */
        return 1;  /* Warning only */
    }

    return 0;  /* OK */
}

/* ============================================================
 * MULTIPLE-MODULE INTERLOCK SEQUENCING
 * ============================================================ */

/* Feed pump discharge check valve verification */
static int bo_fp_check_valve_test(void) {
    /* Pressurize and hold, verify no backflow */
    int hold_time = 5000;  /* ms */
    int pressure_drop_allowed = 50;  /* psi */

    /* Check for leakage past valve */
    int measured_drop = 30;  /* Simulated */
    if (measured_drop > pressure_drop_allowed) {
        scf_alarmq_enq(Q_ALARM_LO, 0x0912);  /* Feed pump check valve leak */
        return -1;
    }

    return 0;
}

/* Fuel valve solenoid continuity & coil resistance test */
static int bo_fuel_solenoid_diagnostics(void) {
    int pilot_coil_ohms = 15;    /* Target 10-20 ohms */
    int main_coil_ohms = 18;
    int acceptable = 25;

    if (pilot_coil_ohms > acceptable) {
        scf_alarmq_enq(Q_ALARM_HI, 0x0913);  /* Pilot solenoid fault */
        return -1;
    }

    if (main_coil_ohms > acceptable) {
        scf_alarmq_enq(Q_ALARM_HI, 0x0914);  /* Main solenoid fault */
        return -1;
    }

    return 0;
}

/* Igniter electrode gap & insulation check */
static int bo_igniter_diagnostics(void) {
    int electrode_gap = 3;  /* mm (target 2-4) */
    int insulation_megohms = 500;

    if (electrode_gap < 2 || electrode_gap > 4) {
        scf_alarmq_enq(Q_ALARM_LO, 0x0915);  /* Igniter gap out of spec */
        return 1;
    }

    if (insulation_megohms < 100) {
        scf_alarmq_enq(Q_ALARM_HI, 0x0916);  /* Igniter insulation fault */
        return -1;
    }

    return 0;
}

/* ============================================================
 * OPERATOR INTERFACE & COMMAND PROCESSING
 * ============================================================ */

/* Process operator commands from queue */
static int bo_process_operator_command(int cmd_code, int param) {
    switch (cmd_code) {
        case 0x01:  /* Start boiler */
            bo_burner_sequence_advance(1, 5000);  /* Ramp state */
            return 0;

        case 0x02:  /* Stop boiler (normal shutdown) */
            bo_burner_sequence_advance(0, 10000);  /* Back to idle */
            return 0;

        case 0x03:  /* Reset trip */
            return bo_trip_reset_request();

        case 0x04:  /* Set pressure setpoint */
            bo_pressure_ctrl.pressure_setpoint = param;
            return 0;

        case 0x05:  /* Set level setpoint */
            bo_level_ctrl.level_setpoint = param;
            return 0;

        case 0x06:  /* Initiate intermittent blowdown */
            return bo_intermittent_blowdown_start();

        case 0x07:  /* Request diagnostics */
            bo_fuel_solenoid_diagnostics();
            bo_igniter_diagnostics();
            bo_fp_check_valve_test();
            return 0;

        default:
            return -1;  /* Unknown command */
    }
}

/* ============================================================
 * SHUTDOWN & SAFE OPERATING STATE
 * ============================================================ */

/* Execute controlled shutdown sequence */
static int bo_shutdown_sequence(int mode) {
    /* mode: 0=normal, 1=emergency, 2=maintenance */

    if (mode == 1) {
        /* Emergency stop — immediate fuel shutoff */
        bo_mft_sequence(0);
        bo_mft_sequence(1);
        bo_mft_state.mft_active = 1;
        bo_ignition_state.lockout_active = 1;
        return 0;
    }

    if (mode == 0) {
        /* Normal shutdown — ramp down gradually */
        bo_burner_sequence_advance(0, 30000);  /* Ramp down over 30 sec */
        return 0;
    }

    if (mode == 2) {
        /* Maintenance shutdown — purge and cool */
        bo_mft_sequence(3);  /* Purge */
        bo_mft_sequence(4);  /* Drain */
        return 0;
    }

    return -1;
}

/* ============================================================
 * EFFICIENCY & HEAT RECOVERY OPTIMIZATION
 * ============================================================ */

/* Stack gas temperature monitoring (efficiency indicator) */
static struct {
    int stack_temp_measured;            /* Flue gas temperature */
    int stack_temp_setpoint;            /* Desired target */
    int heat_recovery_active;           /* Economizer demand */
    int economizer_water_flow;
    int efficiency_percent;
} bo_efficiency = { 0, 400, 0, 0, 0 };

/* Calculate and optimize thermal efficiency */
static void bo_efficiency_monitor(void) {
    int fuel_heat_input;                /* BTU/hr equivalent */
    int steam_heat_output;              /* BTU/hr out */

    /* Estimate from pressure and flow */
    fuel_heat_input = (bo_mft_state.fuel_valve_demand * 500000) / 100;
    steam_heat_output = (bo_level_ctrl.steam_flow * 1200);

    if (fuel_heat_input > 0) {
        bo_efficiency.efficiency_percent = (steam_heat_output * 100) / fuel_heat_input;
    }

    /* Optimize economizer for stack gas recovery */
    if (bo_efficiency.stack_temp_measured > 500) {
        /* Too hot — more heat recovery */
        bo_efficiency.heat_recovery_active = 1;
        bo_efficiency.economizer_water_flow = 80;
    } else if (bo_efficiency.stack_temp_measured < 300) {
        /* Too cool — less recovery (risk condensation) */
        bo_efficiency.heat_recovery_active = 0;
        bo_efficiency.economizer_water_flow = 20;
    }
}

/* ============================================================
 * ENVIRONMENTAL & EMISSIONS MONITORING
 * ============================================================ */

/* Continuous emission monitoring system (CEMS) data */
static struct {
    int nox_ppm;                        /* NOx (nitrogen oxides) */
    int nox_limit;                      /* Regulatory limit */
    int sox_ppm;                        /* SOx (sulfur oxides) */
    int particulate_mg_m3;              /* Particulate matter */
    int co2_percent;                    /* Carbon dioxide in exhaust */
    int opacity_percent;                /* Stack opacity */
} bo_emissions = { 0, 200, 0, 0, 0, 0 };

/* NOx reduction via flue gas recirculation (FGR) */
static struct {
    int fgr_valve_position;             /* 0-100% open */
    int fgr_damper_demand;
    int fgr_active;
} bo_fgr_system = { 0, 0, 0 };

/* Adjust FGR for NOx control */
static void bo_nox_control_adjustment(void) {
    if (bo_emissions.nox_ppm > bo_emissions.nox_limit) {
        /* Increase FGR recirculation to dilute oxygen */
        bo_fgr_system.fgr_valve_position += 5;
        bo_fgr_system.fgr_active = 1;
    } else if (bo_emissions.nox_ppm < (bo_emissions.nox_limit - 50)) {
        /* Can reduce FGR */
        bo_fgr_system.fgr_valve_position -= 3;
    }

    if (bo_fgr_system.fgr_valve_position > 100) bo_fgr_system.fgr_valve_position = 100;
    if (bo_fgr_system.fgr_valve_position < 0) bo_fgr_system.fgr_valve_position = 0;
}

/* Monitor stack opacity (visible emissions) */
static void bo_opacity_monitor(void) {
    /* Opacity limit typically 20% */
    if (bo_emissions.opacity_percent > 20) {
        scf_alarmq_enq(Q_ALARM_HI, 0x0920);  /* High opacity alarm */
    }
}

/* ============================================================
 * ADVANCED BURNER CONTROL (Air/Fuel Coordination)
 * ============================================================ */

/* Combustion air pressure drop across registers */
static struct {
    int air_register_dp;                /* Differential pressure */
    int air_register_position;          /* Mechanical position % */
    int air_register_demand;            /* Control demand */
} bo_air_registers = { 0, 0, 0 };

/* Burner front-end air flow measurement (pitot/dp based) */
static int bo_measure_burner_air_flow(void) {
    /* Calculate from air register DP and position */
    int dp = bo_air_registers.air_register_dp;
    int pos = bo_air_registers.air_register_position;

    if (pos == 0) return 0;  /* Closed */

    /* Flow ~ sqrt(DP) * position */
    int flow = (pos * 80) / 100;  /* Simplified calculation */

    return flow;
}

/* Fuel/air ratio verification (stoichiometric check) */
static int bo_fuel_air_ratio_verify(int fuel_percent, int air_percent) {
    int ratio;
    int tolerance = 10;

    if (fuel_percent == 0) return 0;  /* Shutdown OK */

    ratio = (air_percent * 100) / fuel_percent;

    /* Stoichiometric ratio nominally 15:1 */
    if (ratio < (1500 - tolerance) || ratio > (1500 + tolerance)) {
        scf_alarmq_enq(Q_ALARM_LO, 0x0921);  /* F/A ratio out of range */
        return -1;
    }

    return 0;  /* OK */
}

/* ============================================================
 * LOAD FOLLOWING & DEMAND RESPONSE
 * ============================================================ */

/* Steam demand from turbine / process */
static struct {
    int steam_demand_current;           /* Current load % */
    int steam_demand_setpoint;          /* Operator set point */
    int load_ramp_rate;                 /* Max change per second (%) */
    int turndown_ratio;                 /* Minimum stable load % */
} bo_demand = { 0, 50, 5, 25 };

/* Process steam demand change request */
static int bo_set_steam_demand(int percent) {
    if (percent < bo_demand.turndown_ratio) {
        return -1;  /* Below minimum turndown */
    }

    if (percent > 100) {
        return -1;  /* Over 100% */
    }

    bo_demand.steam_demand_setpoint = percent;
    return 0;
}

/* Ramp actual load toward demand with rate limiting */
static void bo_load_following_control(void) {
    int target = bo_demand.steam_demand_setpoint;
    int current = bo_demand.steam_demand_current;
    int max_delta = bo_demand.load_ramp_rate;
    int delta;

    if (target > current) {
        delta = (target - current > max_delta) ? max_delta : (target - current);
        bo_demand.steam_demand_current += delta;
    } else if (target < current) {
        delta = (current - target > max_delta) ? max_delta : (current - target);
        bo_demand.steam_demand_current -= delta;
    }
}

/* ============================================================
 * SYSTEM DIAGNOSTICS & TRACE LOGGING
 * ============================================================ */

/* Trace buffer for debugging (circular log) */
static struct {
    int trace_idx;
    int trace_events[128];
    int trace_values[128];
    int trace_timestamps[128];
} bo_trace = { 0, {0}, {0}, {0} };

/* Log a trace event for later analysis */
static void bo_trace_event(int event_code, int value) {
    int idx = bo_trace.trace_idx % 128;

    bo_trace.trace_events[idx] = event_code;
    bo_trace.trace_values[idx] = value;
    bo_trace.trace_timestamps[idx] = 0;  /* Would be real timestamp */

    bo_trace.trace_idx++;
}

/* Diagnostic readout of all critical parameters */
static void bo_diagnostics_readout(void) {
    bo_trace_event(0x01, bo_pressure_ctrl.pressure_measured);
    bo_trace_event(0x02, bo_level_ctrl.level_measured);
    bo_trace_event(0x03, bo_mft_state.mft_active);
    bo_trace_event(0x04, bo_ignition_state.lockout_active);
    bo_trace_event(0x05, bo_burner_seq.sequence_state);
    bo_trace_event(0x06, bo_flame_quality.flame_stability);
    bo_trace_event(0x07, bo_efficiency.efficiency_percent);
    bo_trace_event(0x08, bo_emissions.nox_ppm);
}

/* ============================================================
 * ANOMALY DETECTION & PREDICTIVE MAINTENANCE
 * ============================================================ */

/* Performance trending (detect degradation) */
static struct {
    int efficiency_trend_days[30];      /* Daily efficiency average */
    int trend_day_idx;
    int efficiency_degradation_pct;     /* % loss from best */
} bo_trends = { {0}, 0, 0 };

/* Detect efficiency loss over time */
static void bo_efficiency_trend_check(void) {
    int best_efficiency = 90;  /* Baseline */
    int current = bo_efficiency.efficiency_percent;

    bo_trends.efficiency_trend_days[bo_trends.trend_day_idx % 30] = current;

    if (current < best_efficiency) {
        bo_trends.efficiency_degradation_pct = ((best_efficiency - current) * 100) / best_efficiency;
    }

    /* Alert if degradation > 5% */
    if (bo_trends.efficiency_degradation_pct > 5) {
        scf_alarmq_enq(Q_ALARM_LO, 0x0930);  /* Efficiency degradation */
    }
}

/* Fouling detection (rising stack temperature with constant load) */
static int bo_fouling_detect(int current_stack_temp, int load) {
    static int last_stack_temp = 0;

    if (load > 50 && current_stack_temp > (last_stack_temp + 30)) {
        /* Stack temp rising without load increase = fouling */
        scf_alarmq_enq(Q_ALARM_LO, 0x0931);  /* Surface fouling detected */
        last_stack_temp = current_stack_temp;
        return 1;
    }

    last_stack_temp = current_stack_temp;
    return 0;
}

/* ============================================================
 * WATCHDOG & HEALTH MONITORING
 * ============================================================ */

/* System health counters */
static struct {
    int loop_iterations;                /* Control loop count */
    int scan_faults;                    /* Failed sensor reads */
    int trip_events;
    int alarms_total;
    int commands_processed;
    int uptime_seconds;
} bo_health = { 0, 0, 0, 0, 0, 0 };

/* Periodic health check */
static void bo_health_check(void) {
    bo_health.loop_iterations++;
    bo_health.uptime_seconds++;

    /* Detect runaway conditions */
    if (bo_health.loop_iterations > 1000000) {
        bo_health.loop_iterations = 0;  /* Wrap around */
    }

    /* Check for stuck values (no change in measurables) */
    if (bo_pressure_ctrl.pressure_measured == 0) {
        bo_health.scan_faults++;
    }

    if (bo_health.scan_faults > 10) {
        scf_alarmq_enq(Q_ALARM_HI, 0x0940);  /* System sensor fault */
    }
}

/* Final comprehensive loop execution */
static void bo_safety_comprehensive_cycle(void) {
    /* Run all major control loops in sequence */

    bo_main_pressure_control();
    bo_drum_level_control();
    bo_superheat_control();
    bo_o2_control_loop();
    bo_draft_balance_control();

    bo_safety_scan_complete();
    bo_load_following_control();
    bo_intermittent_blowdown_sequence();

    bo_efficiency_monitor();
    bo_nox_control_adjustment();
    bo_opacity_monitor();

    bo_fuel_air_ratio_verify(bo_mft_state.fuel_valve_demand, 80);
    bo_efficiency_trend_check();
    bo_fouling_detect(bo_efficiency.stack_temp_measured, bo_demand.steam_demand_current);

    bo_diagnostics_readout();
    bo_health_check();
}

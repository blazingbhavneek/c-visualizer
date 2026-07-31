/*
 * proc_boiler/main.c — SCADA boiler process initialization.
 * Stateful startup sequence: permissive checks, burner staging,
 * trip-matrix initialization, watchdog, event handlers.
 *
 * Emphasis: deep call chains through bo_combust and bo_safety;
 * broken &Handler callback edge case (EVT_VALVE_CMD); timer +
 * fork; call-site selection via bo_get_ctx(PT_MOTOR_TEMP).
 */

#include <stdio.h>
#include <string.h>

#include "bo_app.h"
#include "scf_event.h"
#include "scf_tag.h"
#include "scf_queue.h"

/* ============================================================
 * GROUND TRUTH
 *
 * main.c:
 *   scf_evt_post(EVT_STARTUP, NULL)
 *       EVENT arg1=3000
 *   scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)bo_on_scan)
 *       EVENT launch_via=EVENT
 *   scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)bo_on_trip)
 *       EVENT launch_via=EVENT
 *   scf_timer_start(TMR_WATCHDOG, 500, (TimerCb)bo_wd)
 *       TIMER launch_via=TIMER
 *   scf_task_fork(TASK_HIST, (TaskEntry)bo_combust_task)
 *       FORK launch_via=FORK
 *   BROKEN: scf_evt_register(EVT_VALVE_CMD, &bo_on_trip)
 *       NOT followed (pointer_expression) — no extra edge
 *   bo_init():
 *       scf_sem_wait(SEM_DBLOCK)
 *       scf_cfg_clear(CFG_SCAN)
 *       bo_get_ctx(PT_MOTOR_TEMP)
 *   bo_wd():
 *       scf_task_kill(TASK_ALARM) KILL launch=TIMER arg1=61
 * ============================================================ */

/* ---- State flags and counters ----------------------------- */
static int bo_enabled         = 0;
static int bo_fuel_ready      = 0;
static int bo_air_ready       = 0;
static int bo_ignition_tried  = 0;
static int bo_flame_detected  = 0;
static int bo_drum_primed     = 0;
static int bo_purge_complete  = 0;
static int bo_startup_stage   = 0;

/* ---- Permissive matrix (hardcoded defaults for this fixture) */
static int bo_low_fuel_level  = 0;  /* alarm if 1 */
static int bo_high_temp_limit = 850;
static int bo_drum_min_level  = 15;
static int bo_steam_pressure_max = 950;

/* ---- Permissive check subroutines (static helpers) -------- */

static int check_fuel_supply(void)
{
	/* In real code: read PT_TANK_LEVEL; here, static check. */
	bo_fuel_ready = 1;
	return bo_fuel_ready;
}

static int check_air_supply(void)
{
	/* In real code: verify forced-draft fan speed, damper. */
	bo_air_ready = 1;
	return bo_air_ready;
}

static int check_drum_level(void)
{
	/* In real code: read PT_TANK_LEVEL tag, compare to min. */
	bo_drum_primed = (bo_drum_min_level > 0) ? 1 : 0;
	return bo_drum_primed;
}

static int purge_combustion_chamber(void)
{
	/* Pre-ignition purge: run FD fan + open damper, clear mixture.
	 * Typically 30-120 seconds in real systems.
	 */
	int purge_time = 5;  /* fixture: short purge */
	bo_purge_complete = (purge_time > 0) ? 1 : 0;
	return bo_purge_complete;
}

static int initiate_ignition(void)
{
	/* Spark ignition attempt: energize igniter, monitor for flame. */
	bo_ignition_tried = 1;
	bo_flame_detected = 1;  /* fixture: always succeeds */
	return bo_flame_detected;
}

static void setup_burner_sequencing(void)
{
	/* Initialize the multi-stage burner management state machine.
	 * Stages: 0=idle, 1=low-fire, 2=mid-fire, 3=high-fire, 4=turndown.
	 * Real system tracks fuel valve modulation, air damper trim,
	 * and fuel/air ratio control.
	 */
	bo_startup_stage = 1;  /* enter low-fire */
}

static void setup_trip_matrix(void)
{
	/* Load or verify interlock trip conditions:
	 *   - High temperature => ALM_OVERTEMP
	 *   - Low drum level => ALM_LOWLEVEL
	 *   - Overpressure => ALM_OVERPRESSURE
	 * Real system would initialize lookup tables, event masks, etc.
	 */
	/* Matrix presets are statically embedded. */
}

static void initialize_control_loop(void)
{
	/* PID loop parameters for drum level (3-element), steam pressure,
	 * fuel/air ratio trim. Typically read from non-volatile config.
	 */
	/* Fixture: defaults already set above. */
}

/* ---- Fuel/air ratio trim (O2 and CO feedback) --------------- */
static int  trim_o2_setpoint = 3;       /* target O2 % in flue gas */
static int  trim_co_setpoint = 50;      /* target CO ppm (low) */
static int  fuel_valve_position = 0;    /* 0..100% */
static int  air_damper_position = 0;

static void trim_fuel_air_ratio(void)
{
	/* Dynamic fuel/air ratio control based on O2 and CO measurements.
	 * Typical logic: if O2 high, reduce air; if CO high, reduce fuel.
	 * This is called from scan cycle for continuous optimization.
	 */
	if (bo_startup_stage < 2) {
		return;  /* only trim during ramp-up */
	}
	/* In real code: read O2/CO sensors, adjust valve/damper positions */
	fuel_valve_position += 2;
	if (fuel_valve_position > 100) fuel_valve_position = 100;
}

/* ---- Drum level 3-element control -------------------------- */
static int  drum_level_sp = 50;         /* setpoint: 50% */
static int  drum_level_pv = 48;         /* current level */
static int  feedwater_valve_pos = 30;   /* valve opening % */

static void control_drum_level_3elem(void)
{
	/* Classic 3-element drum level control:
	 * - Primary: actual drum level
	 * - Secondary: steam flow feedforward
	 * - Tertiary: feedwater flow feedback
	 * Ensures stable drum level under load changes.
	 */
	int error = drum_level_sp - drum_level_pv;
	if (error > 5) {
		feedwater_valve_pos += 3;
	} else if (error < -5) {
		feedwater_valve_pos -= 3;
	}
	if (feedwater_valve_pos < 5) feedwater_valve_pos = 5;
	if (feedwater_valve_pos > 95) feedwater_valve_pos = 95;
}

/* ---- Flame scanner and combustion monitoring --------------- */
static int  flame_scanner_signal = 0;
static int  flame_scanner_threshold = 100;
static int  mft_active = 0;  /* Minimum Fuel Trim */

static int verify_flame_signal(void)
{
	/* Monitor UV/IR flame scanner for stable ignition.
	 * Returns 1 if flame detected, 0 if lost.
	 */
	return (flame_scanner_signal > flame_scanner_threshold) ? 1 : 0;
}

static void check_and_enforce_mft(void)
{
	/* Minimum Fuel Trim: safety interlock to prevent unburned fuel
	 * accumulation. If flame is lost, trip to minimal fuel flow.
	 */
	if (!verify_flame_signal()) {
		mft_active = 1;
		fuel_valve_position = 5;  /* minimal fuel flow */
	} else {
		mft_active = 0;
	}
}

/* ---- Burner sequencing and ramp-up state machine ----------- */
static int  ramp_rate = 2;              /* % change per scan cycle */
static int  target_load = 50;           /* target steam load % */
static int  current_load = 0;

static void execute_burner_ramp(void)
{
	/* Multi-stage burner ramp sequence: low-fire, mid-fire, high-fire.
	 * Ramps up fuel and air proportionally to avoid air/fuel mismatch.
	 */
	if (bo_startup_stage < 3 && current_load < target_load) {
		current_load += ramp_rate;
		fuel_valve_position = current_load;
		air_damper_position = current_load + 10;  /* lead air slightly */
		if (current_load >= 25) {
			bo_startup_stage = 2;
		}
		if (current_load >= 75) {
			bo_startup_stage = 3;
		}
	}
}

/* ---- First-out annunciation and trip recording ------------- */
static int  first_trip_code = 0;
static int  trip_timestamp = 0;

static void record_first_trip(int trip_code)
{
	/* Record the FIRST alarm that caused a trip (First Out logic).
	 * Suppresses subsequent redundant alarms for easier diagnostics.
	 */
	if (first_trip_code == 0) {
		first_trip_code = trip_code;
		trip_timestamp = 0;  /* would be real timestamp in production */
	}
}

/* ============================================================
 * bo_init() — Boiler initialization (called by main).
 * ============================================================ */
void bo_init(void)
{
	/* Acquire the data-block lock (prevent concurrent scan/alarm). */
	scf_sem_wait(SEM_DBLOCK);

	/* Clear the scan configuration and reload defaults. */
	scf_cfg_clear(CFG_SCAN);

	/* Open motor temperature context for later writes (deep call chain). */
	bo_get_ctx(PT_MOTOR_TEMP);

	/* Initialize trip matrix and control constants. */
	setup_trip_matrix();
	initialize_control_loop();

	/* Initialize fuel/air trim setpoints. */
	trim_o2_setpoint = 3;
	trim_co_setpoint = 50;

	/* Set initial drum level target. */
	drum_level_sp = 50;

	/* Configure flame safety thresholds. */
	flame_scanner_threshold = 100;

	/* Pre-load burner sequence state. */
	setup_burner_sequencing();
}

/* ---- Watchdog heartbeat and task health monitoring -------- */
static int  alarm_task_heartbeat = 0;
static int  scan_task_heartbeat = 0;

/* ============================================================
 * bo_wd() — Watchdog timer callback (invoked by framework).
 * Ensures alarm task doesn't stall; force-kill if needed.
 * ============================================================ */
void bo_wd(int timer_id)
{
	static int  wd_counter = 0;
	static int  alarm_last_beat = 0;

	/* Sanity check: ensure the alarm task (TASK_ALARM) is responsive.
	 * If watchdog fires and task is hung, kill and restart it.
	 * This demonstrates scf_task_kill() with a hard timeout.
	 */
	if (timer_id == TMR_WATCHDOG) {
		wd_counter++;

		/* Heartbeat timeout: if alarm_task_heartbeat hasn't advanced
		 * in 10 watchdog cycles (5 seconds @ 500ms), force-kill.
		 */
		if (alarm_task_heartbeat == alarm_last_beat) {
			if (wd_counter > 10) {
				/* Task hung; force restart by killing it.
				 * The framework will eventually restart it.
				 */
				scf_task_kill(TASK_ALARM);
				wd_counter = 0;
			}
		} else {
			/* Task is responsive; reset counter. */
			wd_counter = 0;
			alarm_last_beat = alarm_task_heartbeat;
		}
	}
}

/* ============================================================
 * main() — Process entry point.
 * Single entry; sets up event handlers, timers, tasks, then
 * posts EVT_STARTUP to trigger the boiler sequence.
 * ============================================================ */
int main(void)
{
	int rc = 0;

	/* Step 1: Initialize global state and data-block. */
	bo_init();

	/* Step 2: Register the main scan-cycle event handler.
	 * Framework invokes bo_on_scan when EVT_SCAN_CYCLE is posted.
	 * This is where combustion control logic executes periodically.
	 */
	rc = scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)bo_on_scan);
	if (rc < 0) {
		return -1;
	}

	/* Step 3: Register the alarm/trip handler.
	 * Triggers on EVT_ALARM_RAISED; bo_on_trip performs load-shedding,
	 * annunciation, and MFT (Forced Minimum Fuel) logic.
	 */
	rc = scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)bo_on_trip);
	if (rc < 0) {
		return -1;
	}

	/* Step 4: EDGE CASE — broken callback registration.
	 * Using &bo_on_trip (address-of form) instead of cast form.
	 * Parses as pointer_expression => NOT followed by analyzer.
	 * Registers correctly at runtime but creates NO traced edge.
	 */
	(void)scf_evt_register(EVT_VALVE_CMD, &bo_on_trip);

	/* Step 5: Start the watchdog timer.
	 * Fires every 500 ms; invokes bo_wd() to ensure alarm task
	 * health and force-kill if hung.
	 */
	rc = scf_timer_start(TMR_WATCHDOG, 500, (TimerCb)bo_wd);
	if (rc < 0) {
		return -1;
	}

	/* Step 6: Fork the historian task.
	 * Runs independently; buffers scan data and flushes to archive
	 * on EVT_HIST_FLUSH. Participates in deep call chain to
	 * scf_hist_save().
	 */
	rc = scf_task_fork(TASK_HIST, (TaskEntry)bo_combust_task);
	if (rc < 0) {
		return -1;
	}

	/* Step 7: Start the main boiler sequence.
	 * Posts EVT_STARTUP, which wakes the control logic to begin
	 * permissive checks, purge, ignition, and burner ramp-up.
	 */
	rc = scf_evt_post(EVT_STARTUP, NULL);
	if (rc < 0) {
		return -1;
	}

	return 0;
}

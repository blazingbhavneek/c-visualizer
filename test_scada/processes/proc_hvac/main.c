/* ============================================================
 * proc_hvac/main.c — HVAC Building Management System Process
 * Synthetic SCADA test process (static-tracer fixture).
 * Implements BMS startup: zones, AHU inventory, sensor bus,
 * schedules, occupancy, and watchdog timer.
 * ============================================================ */

#include "hv_app.h"
#include <string.h>

/* GROUND TRUTH
 * path: main -> scf_evt_post(EVT_STARTUP) -> (no further calls in path)
 *   api: scf_evt_post  type=EVENT  launch_via=none  arg1=EVT_STARTUP=3000
 *
 * path: main -> scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)hv_on_scan)
 *   api: scf_evt_register  type=EVENT  launch_via=none (registrar)
 *   launch_via from this registrar: EVENT (handler invoked on scan)
 *   handler: hv_on_scan may call scf_evt_post(EVT_SCAN_CYCLE, ...) with call_number=3001
 *
 * path: main -> scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)hv_on_sched)
 *   api: scf_evt_register  type=EVENT  launch_via=none (registrar)
 *   launch_via from this registrar: EVENT
 *   handler: hv_on_sched may call scf_var_evt(EVT_ALARM_RAISED, ...) with call_number=3002
 *
 * path: main -> scf_timer_start(TMR_SCAN, 1000, (TimerCb)hv_tick)
 *   api: scf_timer_start  type=TIMER  launch_via=none (registrar)
 *   launch_via from this registrar: TIMER
 *   handler: hv_tick (TimerCb) invoked periodically
 *
 * path: main -> scf_task_fork(TASK_HIST, (TaskEntry)hv_zone_task)
 *   api: scf_task_fork  type=FORK  launch_via=none (registrar)
 *   launch_via from this registrar: FORK
 *   handler: hv_zone_task (TaskEntry) spawned as background task
 *
 * path: main -> hv_init -> scf_sem_wait(SEM_DBLOCK)
 *   api: scf_sem_wait  type=SEMAPHORE  arg1=SEM_DBLOCK=80
 *
 * path: main -> hv_init -> hv_clear_config(CFG_ALARM)
 *   function call chain (not direct API, but required by spec)
 */

/* ============================================================
 * Zone / AHU configuration (realistic BMS inventory)
 * ============================================================ */

#define MAX_ZONES           8
#define MAX_AHUS            3
#define MAX_SETPOINTS       16

/* Zone descriptor: tracks occupancy, mode, setpoints */
struct Zone {
    int   zone_id;
    int   temp_sensor_pid;      /* PT_MOTOR_TEMP or similar */
    int   damper_pid;           /* PT_VALVE_POS for zone damper */
    int   occupied;             /* 1 = occupied schedule slot */
    int   desired_temp;         /* occupied setpoint (°F * 10) */
    int   unoccupied_temp;      /* night setback (°F * 10) */
    int   current_temp;         /* last-read value */
    int   damper_position;      /* 0-100% */
};

/* Air Handling Unit: central supply/return fan control */
struct AHU {
    int   ahu_id;
    int   supply_flow_pid;      /* PT_FLOW_RATE */
    int   return_damper_pid;    /* PT_VALVE_POS (exhaust damper) */
    int   mode;                 /* 0=off, 1=heating, 2=cooling, 3=auto */
    int   target_cfm;           /* supply air volume */
    int   economizer_active;    /* 1 = free cooling enabled */
};

/* Weekly occupancy schedule (per-hour slot) */
struct Schedule {
    int   slot_id;
    int   day_of_week;          /* 0=Sun, 6=Sat */
    int   hour;                 /* 0-23 */
    int   occupied;             /* 1 = building occupied */
};

/* Global zone and AHU arrays */
static struct Zone g_zones[MAX_ZONES];
static struct AHU  g_ahus[MAX_AHUS];
static struct Schedule g_schedule[MAX_SETPOINTS];

/* Scan cycle state */
static int g_scan_count = 0;
static int g_startup_phase = 0;
static int g_watchdog_kicks = 0;

/* Occupancy and mode globals */
static int g_occupancy_override = 0;
static int g_global_mode = 1;               /* 1 = auto */
static int g_night_setback_enabled = 1;
static int g_emergency_stop = 0;

/* ============================================================
 * Static helper functions (internal to main.c)
 * ============================================================ */

/* Initialize zone inventory with realistic defaults */
static void init_zones(void)
{
    int i;

    for (i = 0; i < MAX_ZONES; i++) {
        g_zones[i].zone_id = 100 + i;
        g_zones[i].temp_sensor_pid = PT_MOTOR_TEMP;  /* shared sensor type */
        g_zones[i].damper_pid = PT_VALVE_POS;
        g_zones[i].occupied = 0;
        g_zones[i].desired_temp = 720;              /* 72.0°F */
        g_zones[i].unoccupied_temp = 620;           /* 62.0°F night setback */
        g_zones[i].current_temp = 700;
        g_zones[i].damper_position = 0;
    }
}

/* Initialize AHU (air handling unit) inventory */
static void init_ahus(void)
{
    int i;

    for (i = 0; i < MAX_AHUS; i++) {
        g_ahus[i].ahu_id = 200 + i;
        g_ahus[i].supply_flow_pid = PT_FLOW_RATE;
        g_ahus[i].return_damper_pid = PT_VALVE_POS;
        g_ahus[i].mode = 1;                     /* default: heating */
        g_ahus[i].target_cfm = 5000 + (i * 1000);
        g_ahus[i].economizer_active = 0;
    }
}

/* Initialize weekly occupancy schedule (realistic work hours + weekend) */
static void init_schedule(void)
{
    int i = 0;

    /* Weekday (Mon-Fri): 6am-6pm occupied, else unoccupied */
    int dow, hour;

    for (dow = 1; dow <= 5; dow++) {     /* Monday through Friday */
        for (hour = 0; hour < 24; hour++) {
            if (hour >= 6 && hour < 18) {
                g_schedule[i].occupied = 1;
            } else {
                g_schedule[i].occupied = 0;
            }
            g_schedule[i].slot_id = i;
            g_schedule[i].day_of_week = dow;
            g_schedule[i].hour = hour;
            i++;
            if (i >= MAX_SETPOINTS) break;
        }
    }

    /* Weekend: unoccupied (simplified) */
    for (dow = 0; dow <= 0; dow++) {     /* Sunday */
        for (hour = 0; hour < 24; hour++) {
            g_schedule[i].occupied = 0;
            g_schedule[i].slot_id = i;
            g_schedule[i].day_of_week = dow;
            g_schedule[i].hour = hour;
            i++;
            if (i >= MAX_SETPOINTS) break;
        }
    }
}

/* Initialize sensor bus and point registration (synthetic) */
static void init_sensor_bus(void)
{
    /* In a real system, this would enumerate I/O modules, configure
     * modbus/BACnet addresses, and set up scan groups. Here we just
     * mark that the sensor network is ready. */
    int i;

    for (i = 0; i < MAX_ZONES; i++) {
        /* Pre-register each zone's sensor point as readable */
        TagCtx ctx;
        ctx.point_id = g_zones[i].temp_sensor_pid;
        ctx.mode = SCF_READ_LOCK;
        ctx.handle = 100 + i;
    }
}

/* Occupancy defaults: read from schedule (or override) */
static void init_occupancy(void)
{
    int i;

    for (i = 0; i < MAX_ZONES; i++) {
        /* Occupancy inherited from global schedule; can be overridden */
        g_zones[i].occupied = (g_occupancy_override ? 1 : 0);
    }
}

/* Watchdog supervisor check: ensure critical tasks are responsive */
static void watchdog_check(void)
{
    g_watchdog_kicks++;

    if (g_watchdog_kicks > 100) {
        /* Watchdog timeout: could trigger failsafe or alert */
        g_emergency_stop = 1;
    }
}

/* Alarm queue flush: drain high-priority alarms if any */
static void flush_alarm_queue(void)
{
    int alarm_code;
    int status;

    /* Attempt to dequeue alarms and log them (simplified) */
    status = scf_alarmq_deq(Q_ALARM_HI, &alarm_code);
    if (status == 0) {
        /* Process alarm_code, e.g., ALM_OVERTEMP, ALM_LOWLEVEL */
        switch (alarm_code) {
        case ALM_OVERTEMP:
            /* Log high-temperature alarm */
            break;
        case ALM_LOWLEVEL:
            /* Log low-level alarm */
            break;
        case ALM_OVERPRESSURE:
            /* Log overpressure alarm */
            break;
        }
    }
}

/* Load initial command queue (e.g., from persistent storage or network) */
static void load_command_queue(void)
{
    int status;

    status = scf_cmdq_load(Q_CMD);
    if (status == 0) {
        /* Commands loaded; will be processed in scan loop */
    }
}

/* Initialize real-time historian flush mechanism */
static void init_historian(void)
{
    /* Historian task (hv_zone_task) will be spawned separately via
     * scf_task_fork. This just sets up any initial state or buffers. */
}

/* ============================================================
 * Main entry point
 * ============================================================ */

int main(void)
{
    /* Initialization order: critical first, then registration */

    /* 1. Initialize hardware/configuration structures */
    init_zones();
    init_ahus();
    init_schedule();
    init_sensor_bus();
    init_occupancy();
    load_command_queue();
    init_historian();

    /* 2. Initialize app-level state (semaphore, config clear) */
    hv_init();

    /* 3. Post startup event (notifies other tasks system is running) */
    scf_evt_post(EVT_STARTUP, 0);

    /* 4. Register scan-cycle handler (fires on TMR_SCAN interval) */
    scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)hv_on_scan);

    /* 5. Register alarm/schedule handler (fires on alarms) */
    scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)hv_on_sched);

    /* 6. Start main scan timer (1000 ms = 1 second cycle) */
    scf_timer_start(TMR_SCAN, 1000, (TimerCb)hv_tick);

    /* 7. Fork background historian task (persists trends to ARC_TREND) */
    scf_task_fork(TASK_HIST, (TaskEntry)hv_zone_task);

    /* 8. Prime watchdog and clear any residual alarms */
    watchdog_check();
    flush_alarm_queue();

    g_startup_phase = 1;

    return 0;
}

/* ============================================================
 * hv_init - Application initialization
 * Called from main() after hardware setup, before event registration.
 * Handles synchronization and config reset.
 * ============================================================ */

void hv_init(void)
{
    /* Wait on data-block lock (ensures no concurrent access to
     * shared structures during startup) */
    scf_sem_wait(SEM_DBLOCK);

    /* Clear alarm configuration to reset any lingering state */
    hv_clear_config(CFG_ALARM);

    /* Additional init hooks could go here (thermostats, schedules, etc.) */
}

/* ============================================================
 * hv_tick - Periodic scan-cycle callback
 * Registered as TimerCb for TMR_SCAN (1000 ms interval).
 * Keeps watchdog alive and triggers periodic housekeeping.
 * ============================================================ */

void hv_tick(int timer_id)
{
    (void)timer_id;  /* unused in this fixture */

    g_scan_count++;
    g_watchdog_kicks = 0;  /* Reset watchdog on successful tick */

    /* Periodic tasks (run every N ticks if needed) */
    if (g_scan_count % 10 == 0) {
        /* Every 10 seconds: flush any queued commands */
        scf_cmdq_load(Q_CMD);
    }

    if (g_scan_count % 60 == 0) {
        /* Every 60 seconds: check occupancy schedule */
        if (!g_occupancy_override) {
            /* Apply schedule-based occupancy to zones */
        }
    }

    if (g_scan_count % 300 == 0) {
        /* Every 5 minutes: housekeeping (clear stale history, log stats) */
    }
}

/* ============================================================
 * Ground-truth verification block (for tracer validation).
 *
 * Expected tracer output for main.c:
 *
 * 1. scf_evt_post(EVT_STARTUP, 0)
 *    - type: EVENT
 *    - arg1: EVT_STARTUP (3000)
 *    - launch_via: none (direct call from main)
 *
 * 2. scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)hv_on_scan)
 *    - type: EVENT (registration)
 *    - handler: hv_on_scan
 *    - launch_via: EVENT (handler fired on scan cycle)
 *
 * 3. scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)hv_on_sched)
 *    - type: EVENT (registration)
 *    - handler: hv_on_sched
 *    - launch_via: EVENT
 *
 * 4. scf_timer_start(TMR_SCAN, 1000, (TimerCb)hv_tick)
 *    - type: TIMER (registration)
 *    - interval: 1000 ms
 *    - handler: hv_tick
 *    - launch_via: TIMER (periodic callback)
 *
 * 5. scf_task_fork(TASK_HIST, (TaskEntry)hv_zone_task)
 *    - type: FORK (registration)
 *    - handler: hv_zone_task
 *    - launch_via: FORK (background task)
 *
 * 6. In hv_init():
 *    - scf_sem_wait(SEM_DBLOCK) [arg1 = 80]
 *    - hv_clear_config(CFG_ALARM) [arg1 = 301]
 *
 * ============================================================ */

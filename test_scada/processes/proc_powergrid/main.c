/*
 * proc_powergrid / main.c -- electrical substation SCADA initialization.
 * RTU discovery, comm-port setup, watchdog init, configuration sequencing.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>

#include "scf_types.h"
#include "scf_const.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"

/* ============================================================
 * GROUND TRUTH
 *
 * main() -> scf_evt_post(EVT_STARTUP,0)
 *   api: scf_evt_post  type=EVENT  call_number=3000
 *
 * main() -> scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)pg_on_scan)
 *   api: scf_evt_register  launch_via=EVENT  arg1=3001
 *
 * main() -> scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)pg_on_dispatch)
 *   api: scf_evt_register  launch_via=EVENT  arg1=3002
 *
 * main() -> scf_timer_start(TMR_SCAN,250,(TimerCb)pg_poll_timer)
 *   api: scf_timer_start  launch_via=TIMER  arg1=50  arg2=250
 *
 * main() -> scf_task_fork(TASK_HIST,(TaskEntry)pg_poll_task)
 *   api: scf_task_fork  launch_via=FORK  arg1=60
 *
 * pg_init() -> scf_sem_wait(SEM_DBLOCK)
 *   api: scf_sem_wait  type=SEMAPHORE  arg1=80
 *
 * pg_init() -> scf_cfg_clear(CFG_SCAN)
 *   api: scf_cfg_clear  type=CLEARF  arg1=300
 *
 * pg_init() -> pg_rtu_getptr(PT_PRESSURE)
 *   api: pg_rtu_getptr indirect call  arg1=0x1006
 *
 * pg_poll_timer(int timer_id) -> scf_task_kill(TASK_ALARM)
 *   api: scf_task_kill  type=KILL  launch_via=TIMER  arg1=61
 * ============================================================ */

/* Forward declarations of process-module functions */
void pg_on_scan(int evt, void *data);
void pg_on_dispatch(int evt, void *data);
void pg_poll_task(int task_id);
void *pg_rtu_getptr(int fno);

/* --- Static configuration and state ---------------------- */

/* RTU inventory: static module descriptors for 3 feeders + tap changer */
static struct {
    int       fno;             /* feeder number PT_PRESSURE, etc */
    const char *label;         /* symbolic name */
    int       present;         /* 1 if on-line */
    int       retry_count;
} g_rtu_roster[] = {
    { PT_PRESSURE,   "Transformer-Primary", 0, 0 },
    { PT_MOTOR_TEMP, "Distribution-Feeder-1", 0, 0 },
    { PT_VALVE_POS,  "Distribution-Feeder-2", 0, 0 },
};
#define NUM_RTUS (sizeof(g_rtu_roster) / sizeof(g_rtu_roster[0]))

/* Comm-port state tracking */
static struct {
    int port_fd;               /* file descriptor (-1 if not open) */
    int baudrate;
    int parity;                /* 0=none, 1=odd, 2=even */
} g_comm_ports[2] = {
    { -1, 9600, 0 },
    { -1, 19200, 2 },
};

/* Watchdog / health counters */
static struct {
    int poll_count;
    int alarm_count;
    int last_heartbeat;        /* epoch timestamp */
    int watchdog_trips;
} g_health = { 0, 0, 0, 0 };

/* Config cache: scan interval, alarm thresholds */
static struct {
    int scan_interval_ms;
    int alarm_high_threshold;
    int alarm_low_threshold;
} g_config = { 0, 0, 0 };

/* Startup sequence tracker */
static int g_startup_phase = 0;
#define STARTUP_DISCOVER_RTUS  1
#define STARTUP_INIT_COMMS     2
#define STARTUP_LOAD_CONFIG    3
#define STARTUP_ARM_TIMERS     4
#define STARTUP_READY          5

/* ---- Static helpers ----- */

/* Discover RTUs by attempting to open each RTU's tag */
static void discover_rtu_inventory(void)
{
    size_t i;

    for (i = 0; i < NUM_RTUS; i++) {
        /* Attempt I/O to confirm presence */
        if (pg_rtu_getptr(g_rtu_roster[i].fno) != NULL) {
            g_rtu_roster[i].present = 1;
        } else {
            g_rtu_roster[i].present = 0;
            g_rtu_roster[i].retry_count = 0;
        }
    }
}

/* Initialize communication ports (stub: represents real serial/CAN init) */
static int init_comm_ports(void)
{
    int i;

    for (i = 0; i < 2; i++) {
        /* In a real system, open_serial_port(baudrate, parity, ...) */
        g_comm_ports[i].port_fd = i + 100;  /* placeholder fd */
        if (g_comm_ports[i].port_fd < 0) {
            return -1;
        }
    }
    return 0;
}

/* Load configuration from tag storage */
static int load_configuration(void)
{
    /* Poll tag storage for scan interval and alarm thresholds */
    TagCtx ctx = { 0, -1, SCF_READ_LOCK, NULL };
    int value = 0;

    /* Read scan interval (implicit from config tag) */
    if (scf_tag_read(&ctx, CFG_SCAN, &value) == 0) {
        g_config.scan_interval_ms = 250;  /* default 250ms */
    }

    /* Read alarm thresholds */
    if (scf_tag_read(&ctx, CFG_ALARM, &value) == 0) {
        g_config.alarm_high_threshold = 85;
        g_config.alarm_low_threshold = 10;
    }

    return 0;
}

/* Initialize watchdog and health monitoring */
static void init_watchdog(void)
{
    g_health.poll_count = 0;
    g_health.alarm_count = 0;
    g_health.last_heartbeat = (int)time(NULL);
    g_health.watchdog_trips = 0;
}

/* Report initialization status to log/console */
static void report_init_status(int phase)
{
    static const char *phase_names[] = {
        "UNKNOWN",
        "Discover-RTUs",
        "Init-Comms",
        "Load-Config",
        "Arm-Timers",
        "Ready",
    };

    if (phase >= 0 && phase < 6) {
        fprintf(stderr, "[INIT] Phase %d: %s\n", phase, phase_names[phase]);
    }
}

/* ============================================================
 * PUBLIC API: pg_init
 * ============================================================
 *
 * Initialize substation RTU inventory, comm ports, configuration,
 * and watchdog. Called from main() before event registration.
 */
void pg_init(void)
{
    /* Phase 1: Synchronize with data-block access */
    scf_sem_wait(SEM_DBLOCK);
    g_startup_phase = STARTUP_DISCOVER_RTUS;
    report_init_status(g_startup_phase);

    /* Phase 2: Clear scan configuration to known state */
    scf_cfg_clear(CFG_SCAN);
    g_startup_phase = STARTUP_INIT_COMMS;
    report_init_status(g_startup_phase);

    /* Phase 3: Discover available RTUs (will call pg_rtu_getptr) */
    discover_rtu_inventory();

    /* Phase 4: Verify reference RTU (pressure transducer at transformer primary) */
    if (pg_rtu_getptr(PT_PRESSURE) == NULL) {
        fprintf(stderr, "[WARN] Primary RTU (pressure) not responding\n");
    }

    /* Phase 5: Initialize communication ports */
    if (init_comm_ports() < 0) {
        fprintf(stderr, "[ERROR] Failed to initialize comm ports\n");
        return;
    }
    g_startup_phase = STARTUP_LOAD_CONFIG;
    report_init_status(g_startup_phase);

    /* Phase 6: Load configuration (scan interval, alarm setpoints, etc.) */
    if (load_configuration() < 0) {
        fprintf(stderr, "[ERROR] Failed to load configuration\n");
        return;
    }

    /* Phase 7: Initialize health/watchdog counters */
    init_watchdog();
    g_startup_phase = STARTUP_ARM_TIMERS;
    report_init_status(g_startup_phase);
}

/* ============================================================
 * PUBLIC API: pg_poll_timer
 * ============================================================
 *
 * Timer callback (TMR_SCAN @ 250ms). Polls RTUs, manages retry logic,
 * executes watchdog shutdown if needed. Called from framework timer ISR.
 */
void pg_poll_timer(int timer_id)
{
    /* Increment poll counter */
    g_health.poll_count++;

    /* Watchdog: if no RTU activity for N cycles, force alarm task kill */
    if (g_health.poll_count % 40 == 0) {  /* ~10 seconds at 250ms */
        if (g_health.poll_count > g_health.last_heartbeat + 10000) {
            g_health.watchdog_trips++;

            /* Shutdown alarm-dispatch task to prevent cascade */
            scf_task_kill(TASK_ALARM);
            fprintf(stderr, "[ALERT] Watchdog: killed TASK_ALARM (trip #%d)\n",
                    g_health.watchdog_trips);
        }
    }
}

/* ============================================================
 * main — entry point
 * ============================================================
 *
 * Orchestrate startup sequence:
 *  1. Initialize RTU subsystem (pg_init)
 *  2. Post startup event
 *  3. Register event handlers (scan, alarm dispatch)
 *  4. Start scan timer (250ms period)
 *  5. Fork historian background task
 *  6. Enter framework dispatch loop
 */
int main(int argc, char *argv[])
{
    int ret = 0;

    /* Suppress unused-argument warnings */
    (void)argc;
    (void)argv;

    fprintf(stderr, "[STARTUP] Powergrid SCADA process initializing...\n");

    /* Step 1: Initialize RTU subsystem */
    pg_init();
    if (g_startup_phase != STARTUP_ARM_TIMERS) {
        fprintf(stderr, "[ERROR] Initialization failed at phase %d\n", g_startup_phase);
        return 1;
    }

    /* Step 2: Signal framework that startup is in progress */
    scf_evt_post(EVT_STARTUP, 0);

    /* Step 3a: Register scan-cycle event handler (indirect via cast) */
    scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)pg_on_scan);

    /* Step 3b: Register alarm-dispatch event handler (indirect via cast) */
    scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)pg_on_dispatch);

    /* Step 4: Start periodic scan timer (250ms interval) */
    scf_timer_start(TMR_SCAN, 250, (TimerCb)pg_poll_timer);
    fprintf(stderr, "[STARTUP] Scan timer armed (250ms)\n");

    /* Step 5: Spawn historian background task */
    scf_task_fork(TASK_HIST, (TaskEntry)pg_poll_task);
    fprintf(stderr, "[STARTUP] Historian task forked\n");

    /* Update startup phase */
    g_startup_phase = STARTUP_READY;
    report_init_status(g_startup_phase);

    fprintf(stderr, "[STARTUP] Powergrid SCADA ready. RTUs online: %zu\n",
            NUM_RTUS);

    /* Step 6: Enter framework event loop (blocks until shutdown) */
    /* In real system: while(1) { framework dispatch event; } */
    /* For now, return success — framework runs in separate thread/process */

    return ret;
}

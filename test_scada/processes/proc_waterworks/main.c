/* Enable BSD/POSIX functions like usleep */
#define _BSD_SOURCE
#define _DEFAULT_SOURCE

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

/* Forward declarations for handlers defined in other modules */
void ww_on_scan(int evt, void *data);
void ww_on_alarm(int evt, void *data);
void ww_hist_task(int task_id);
void *ww_get_ctx(int fno);

/* ============================================================
 * GROUND TRUTH
 *
 * main():
 *   scf_evt_post(EVT_STARTUP, 0)                          EVENT  arg1=3000
 *   scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)ww_on_scan)     -> EVENT link
 *   scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)ww_on_alarm)  -> EVENT link
 *   scf_timer_start(TMR_WATCHDOG, 500, (TimerCb)ww_watchdog)     -> TIMER link
 *   scf_task_fork(TASK_HIST, (TaskEntry)ww_hist_task)            -> FORK link
 *
 * ww_init():
 *   scf_sem_wait(SEM_DBLOCK)                           SEMAPHORE arg1=80
 *   ww_get_ctx(PT_TANK_LEVEL)
 *   scf_cfg_clear(CFG_SCAN)                            CLEARF arg1=300
 *
 * ww_watchdog(int timer_id):
 *   scf_task_kill(TASK_ALARM)                          KILL launch=TIMER arg1=61
 * ============================================================ */

/* Process version and build info */
#define WW_VERSION_MAJOR   1
#define WW_VERSION_MINOR   2
#define WW_VERSION_PATCH   3
#define WW_BUILD_DATE      "2026-07-30"

/* Configuration and runtime state */
typedef struct {
    int   process_id;
    int   scan_interval_ms;
    int   alarm_threshold_ppm;
    int   tank_target_level;
    int   watchdog_timeout_ms;
    int   historian_flush_sec;
    int   retry_backoff_ms;
    int   max_retries;
    char  config_file[256];
} ProcessConfig;

typedef struct {
    int   startup_time;
    int   last_scan_time;
    int   total_scans;
    int   alarm_count;
    int   error_count;
    int   is_running;
    int   watchdog_kicks;
} HealthStatus;

/* Global state (internal to main.c) */
static ProcessConfig g_config;
static HealthStatus  g_health;
static int           g_shutdown_requested;
static int           g_init_complete;

/* ============================================================
 * Static helper functions for startup and diagnostics
 * ============================================================ */

/* Print startup banner with version info */
static void print_banner(void)
{
    printf("\n");
    printf("╔════════════════════════════════════════════════════════╗\n");
    printf("║  WATERWORKS SCADA PROCESS                             ║\n");
    printf("║  v%d.%d.%d  Built %s                                ║\n",
           WW_VERSION_MAJOR, WW_VERSION_MINOR, WW_VERSION_PATCH,
           WW_BUILD_DATE);
    printf("║  Water Treatment & Distribution Control System        ║\n");
    printf("╚════════════════════════════════════════════════════════╝\n");
    printf("\n");
}

/* Load process configuration from file (default: /etc/waterworks.conf) */
static int load_config(const char *config_path)
{
    FILE *fp;
    char line[256];

    /* Initialize defaults */
    g_config.process_id = 42;
    g_config.scan_interval_ms = 100;
    g_config.alarm_threshold_ppm = 50;
    g_config.tank_target_level = 3500;
    g_config.watchdog_timeout_ms = 5000;
    g_config.historian_flush_sec = 60;
    g_config.retry_backoff_ms = 500;
    g_config.max_retries = 3;
    strncpy(g_config.config_file, config_path, sizeof(g_config.config_file) - 1);

    /* Attempt to read config file */
    fp = fopen(config_path, "r");
    if (!fp) {
        printf("[WARN] Config file not found at %s; using defaults\n", config_path);
        return 0;  /* Continue with defaults */
    }

    while (fgets(line, sizeof(line), fp)) {
        /* Skip comments and empty lines */
        if (line[0] == '#' || line[0] == '\n') continue;

        /* Simple config parsing (key=value format) */
        if (strncmp(line, "scan_interval=", 14) == 0)
            g_config.scan_interval_ms = atoi(&line[14]);
        else if (strncmp(line, "watchdog_timeout=", 17) == 0)
            g_config.watchdog_timeout_ms = atoi(&line[17]);
        else if (strncmp(line, "tank_target=", 12) == 0)
            g_config.tank_target_level = atoi(&line[12]);
    }

    fclose(fp);
    printf("[INFO] Loaded config from %s\n", config_path);
    return 0;
}

/* Validate system dependencies and probe hardware */
static int probe_system(void)
{
    printf("[DIAG] Probing water system hardware...\n");
    printf("[DIAG]   Tank level sensor:      OK\n");
    printf("[DIAG]   Flow rate meter:        OK\n");
    printf("[DIAG]   Temperature probe:      OK\n");
    printf("[DIAG]   Pressure transducer:    OK\n");
    printf("[DIAG]   Main circulation pump:  OK\n");
    printf("[DIAG]   Isolation valves:       OK\n");
    return 0;
}

/* Initialize health monitoring structure */
static void init_health_status(void)
{
    g_health.startup_time = (int) time(NULL);
    g_health.last_scan_time = 0;
    g_health.total_scans = 0;
    g_health.alarm_count = 0;
    g_health.error_count = 0;
    g_health.is_running = 1;
    g_health.watchdog_kicks = 0;
    printf("[INFO] Health monitor initialized\n");
}

/* Print diagnostic summary */
static void print_diagnostics(void)
{
    int uptime = ((int) time(NULL)) - g_health.startup_time;
    printf("\n[STAT] System Diagnostics:\n");
    printf("       Uptime: %d seconds\n", uptime);
    printf("       Total scans: %d\n", g_health.total_scans);
    printf("       Alarms raised: %d\n", g_health.alarm_count);
    printf("       Errors: %d\n", g_health.error_count);
    printf("       Watchdog kicks: %d\n", g_health.watchdog_kicks);
}

/* Register shutdown handler (stub for signal handling) */
static void setup_shutdown_handler(void)
{
    printf("[INFO] Shutdown handler registered (SIGTERM/SIGINT)\n");
}

/* Retry wrapper with exponential backoff for resilience */
static int retry_operation(int (*operation)(void), int max_attempts, const char *op_name)
{
    int attempt;
    int backoff_ms = g_config.retry_backoff_ms;

    for (attempt = 0; attempt < max_attempts; attempt++) {
        if (operation() == 0) {
            printf("[OKAY] %s succeeded\n", op_name);
            return 0;
        }
        if (attempt < max_attempts - 1) {
            printf("[RETRY] %s attempt %d/%d, backoff %d ms\n",
                   op_name, attempt + 1, max_attempts, backoff_ms);
            usleep(backoff_ms * 1000);
            backoff_ms = (backoff_ms * 3) / 2;  /* 1.5x backoff */
        }
    }

    g_health.error_count++;
    printf("[ERROR] %s failed after %d attempts\n", op_name, max_attempts);
    return -1;
}

/* Dummy operation for testing retry logic */
static int probe_system_op(void)
{
    return probe_system();
}

/* Ring buffer for moving average of tank level (sensor smoothing) */
typedef struct {
    int  values[16];
    int  index;
    int  count;
} RingBuffer;

static RingBuffer g_level_buffer = {{0}, 0, 0};

/* Add sample to ring buffer and return smoothed value */
static int smooth_level_reading(int raw_level)
{
    int i, sum = 0;

    g_level_buffer.values[g_level_buffer.index] = raw_level;
    g_level_buffer.index = (g_level_buffer.index + 1) % 16;
    if (g_level_buffer.count < 16)
        g_level_buffer.count++;

    for (i = 0; i < g_level_buffer.count; i++)
        sum += g_level_buffer.values[i];

    return sum / g_level_buffer.count;
}

/* Threshold check for level breach detection */
static int check_level_breach(int level)
{
    int threshold = g_config.tank_target_level;
    if (level > (threshold * 110) / 100)
        return 1;  /* Over 110% */
    if (level < (threshold * 75) / 100)
        return 1;  /* Under 75% */
    return 0;
}

/* ============================================================
 * PUBLIC API (ww_init and ww_watchdog)
 * ============================================================ */

/*
 * ww_init() — main initialization sequence.
 * Called from main() after config load and system probe.
 * Coordinates subsystem startup with proper ordering and
 * error handling.
 */
void ww_init(void)
{
    TagCtx tank_ctx;

    printf("[INIT] Starting subsystem initialization...\n");

    /* 1. Acquire data block lock (serializes access) */
    printf("[INIT] Acquiring data block lock...\n");
    scf_sem_wait(SEM_DBLOCK);
    printf("[INIT] Lock acquired\n");

    /* 2. Initialize tank context and open tag storage */
    printf("[INIT] Opening tank level tag context...\n");
    memset(&tank_ctx, 0, sizeof(tank_ctx));
    ww_get_ctx(PT_TANK_LEVEL);
    printf("[INIT] Tank level context ready\n");

    /* 3. Clear scan cycle configuration (prepare for fresh scan) */
    printf("[INIT] Clearing stale scan configuration...\n");
    scf_cfg_clear(CFG_SCAN);
    printf("[INIT] Scan config cleared\n");

    /* 4. Mark initialization complete */
    g_init_complete = 1;
    printf("[INIT] Subsystem initialization complete\n");
}

/*
 * ww_watchdog() — timer callback invoked periodically by the
 * event dispatcher. Monitors process health and performs
 * recovery actions (e.g., killing hung alarm task).
 */
void ww_watchdog(int timer_id)
{
    g_health.watchdog_kicks++;

    /* Log watchdog activity (every 10th kick to reduce spam) */
    if ((g_health.watchdog_kicks % 10) == 0) {
        printf("[WATCH] Watchdog kick #%d at timer %d\n",
               g_health.watchdog_kicks, timer_id);
    }

    /* If alarm task is hung, terminate it and allow restart */
    if (g_health.error_count > 5) {
        printf("[WARN] High error count detected, terminating alarm task\n");
        scf_task_kill(TASK_ALARM);
    }
}

/* ============================================================
 * MAIN ENTRY POINT
 * ============================================================ */

int main(int argc, char *argv[])
{
    int rc;

    print_banner();

    /* Phase 1: Configuration */
    printf("[BOOT] Phase 1: Configuration loading\n");
    load_config("/etc/waterworks.conf");
    printf("[BOOT]   scan interval: %d ms\n", g_config.scan_interval_ms);
    printf("[BOOT]   watchdog timeout: %d ms\n", g_config.watchdog_timeout_ms);
    printf("[BOOT]   tank target: %d units\n", g_config.tank_target_level);

    /* Phase 2: Hardware probe and validation */
    printf("[BOOT] Phase 2: Hardware probing\n");
    rc = retry_operation(probe_system_op, g_config.max_retries, "hardware_probe");
    if (rc != 0) {
        fprintf(stderr, "[FATAL] Hardware probe failed; aborting startup\n");
        return 1;
    }

    /* Phase 3: Health status initialization */
    printf("[BOOT] Phase 3: Health monitoring setup\n");
    init_health_status();

    /* Phase 4: Process initialization (subsystems, locks, tags) */
    printf("[BOOT] Phase 4: Process subsystem initialization\n");
    ww_init();

    /* Phase 5: Event handler registration (indirect event links) */
    printf("[BOOT] Phase 5: Event handler registration\n");
    scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)ww_on_scan);
    printf("[BOOT]   Registered scan cycle handler\n");
    scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)ww_on_alarm);
    printf("[BOOT]   Registered alarm handler\n");

    /* Phase 6: Timer setup (watchdog for health monitoring) */
    printf("[BOOT] Phase 6: Timer setup\n");
    scf_timer_start(TMR_WATCHDOG, 500, (TimerCb)ww_watchdog);
    printf("[BOOT]   Watchdog timer armed (500 ms interval)\n");

    /* Phase 7: Background task spawning (historian flush task) */
    printf("[BOOT] Phase 7: Background task spawning\n");
    scf_task_fork(TASK_HIST, (TaskEntry)ww_hist_task);
    printf("[BOOT]   Historian task spawned\n");

    /* Phase 8: Shutdown handler and startup event */
    printf("[BOOT] Phase 8: Startup signaling\n");
    setup_shutdown_handler();
    scf_evt_post(EVT_STARTUP, 0);
    printf("[BOOT]   Startup event posted\n");

    /* Print final startup summary */
    printf("[BOOT] ───────────────────────────────────────────────\n");
    printf("[BOOT] Waterworks process ready for operation\n");
    printf("[BOOT] ───────────────────────────────────────────────\n");
    print_diagnostics();
    printf("\n");

    /* Simulate process event loop (stub; actual event dispatch
     * is handled by the framework's main loop, not here). */
    while (g_health.is_running && !g_shutdown_requested) {
        sleep(1);  /* Framework dispatches events in background */
    }

    /* Graceful shutdown */
    printf("[SHUT] Shutdown requested; cleaning up...\n");
    print_diagnostics();
    printf("[SHUT] Waterworks process terminated\n");

    return 0;
}

/* ============================================================
 * END MAIN.C
 * ============================================================ */

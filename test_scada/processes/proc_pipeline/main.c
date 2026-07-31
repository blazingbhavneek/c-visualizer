#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pl_app.h"

/* ============================================================
 * GROUND TRUTH
 *
 * main (entry):
 *   scf_evt_post(EVT_STARTUP, 0)                               EVENT arg1=3000
 *   scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)pl_on_scan)  EVENT
 *   scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)pl_on_leak) EVENT
 *   scf_timer_start(TMR_SCAN, 200, (TimerCb)pl_scan_timer)     TIMER
 *   scf_task_fork(TASK_HIST, (TaskEntry)pl_flow_task)          FORK
 *
 * pl_init (initialization phase):
 *   scf_sem_wait(SEM_DBLOCK)                                   SEMAPHORE
 *   scf_cfg_clear(CFG_SCAN)                                    CLEARF
 * ============================================================ */

/* --- Static configuration / station inventory -------------- */

typedef struct {
    int   segment_id;
    int   station_count;
    char  name[64];
} PipelineSegment;

typedef struct {
    int   station_id;
    int   meter_pid;
    int   pressure_pid;
    int   temp_pid;
    float base_flow;
} StationMeter;

typedef struct {
    int   detector_id;
    int   segment_id;
    float threshold;
    int   armed;
} LeakDetector;

/* --- Module-level singletons ------------------------------ */

static PipelineSegment g_segments[4];
static int             g_segment_count = 0;

static StationMeter    g_meters[8];
static int             g_meter_count = 0;

static LeakDetector    g_detectors[4];
static int             g_detector_count = 0;

static struct {
    int   initialized;
    int   comms_up;
    int   watchdog_armed;
    int   scan_enabled;
} g_app_state = {0, 0, 0, 0};

/* --- Static helper: segment registration ------------------- */
static void register_segment(int seg_id, int station_count, const char *name)
{
    if (g_segment_count >= 4) {
        fprintf(stderr, "ERROR: segment table full\n");
        return;
    }
    g_segments[g_segment_count].segment_id = seg_id;
    g_segments[g_segment_count].station_count = station_count;
    strncpy(g_segments[g_segment_count].name, name, 63);
    g_segments[g_segment_count].name[63] = '\0';
    g_segment_count++;
    printf("[INIT] Registered segment %d: '%s' (%d stations)\n",
           seg_id, name, station_count);
}

/* --- Static helper: meter/station configuration ------------ */
static void configure_meter(int station_id, int meter_pid,
                            int pressure_pid, int temp_pid, float base_flow)
{
    if (g_meter_count >= 8) {
        fprintf(stderr, "ERROR: meter table full\n");
        return;
    }
    g_meters[g_meter_count].station_id = station_id;
    g_meters[g_meter_count].meter_pid = meter_pid;
    g_meters[g_meter_count].pressure_pid = pressure_pid;
    g_meters[g_meter_count].temp_pid = temp_pid;
    g_meters[g_meter_count].base_flow = base_flow;
    g_meter_count++;
    printf("[INIT] Configured meter at station %d (flow@0x%04x, P@0x%04x, T@0x%04x)\n",
           station_id, meter_pid, pressure_pid, temp_pid);
}

/* --- Static helper: leak detector arming ------------------- */
static void arm_leak_detector(int detector_id, int segment_id, float threshold)
{
    if (g_detector_count >= 4) {
        fprintf(stderr, "ERROR: detector table full\n");
        return;
    }
    g_detectors[g_detector_count].detector_id = detector_id;
    g_detectors[g_detector_count].segment_id = segment_id;
    g_detectors[g_detector_count].threshold = threshold;
    g_detectors[g_detector_count].armed = 1;
    g_detector_count++;
    printf("[INIT] Armed leak detector %d on segment %d (threshold=%.2f%%)\n",
           detector_id, segment_id, threshold);
}

/* --- Static helper: comms stack init ----------------------- */
static int init_comms(void)
{
    printf("[INIT] Initializing RTU comms stack\n");
    /* Mock Modbus/DNP3 setup */
    printf("[INIT]   -> MTU size: 256 bytes\n");
    printf("[INIT]   -> Baud: 9600 (serial) / TCP 502 (IEC60870)\n");
    printf("[INIT]   -> Timeout: 5000 ms\n");
    g_app_state.comms_up = 1;
    return 0;
}

/* --- Static helper: tag/point database init ------------- */
static int init_tag_database(void)
{
    printf("[INIT] Initializing tag database\n");
    printf("[INIT]   -> Allocating %d points\n", 16);
    printf("[INIT]   -> Loading calibration from EEPROM\n");
    return 0;
}

/* --- Static helper: watchdog init ------------------------- */
static void init_watchdog(void)
{
    printf("[INIT] Configuring hardware watchdog (30s timeout)\n");
    g_app_state.watchdog_armed = 1;
}

/* --- Static helper: queue/message init -------------------- */
static int init_queues(void)
{
    printf("[INIT] Initializing message queues\n");
    printf("[INIT]   -> Alarm queue (HI): max 32\n");
    printf("[INIT]   -> Alarm queue (LO): max 32\n");
    printf("[INIT]   -> Command queue: max 16\n");
    printf("[INIT]   -> Message queue: max 64\n");
    return 0;
}

/* --- Static helper: total inventory setup ------------------- */
static void setup_pipeline_inventory(void)
{
    printf("[INIT] Setting up pipeline segments and stations\n\n");

    /* Segment 1: North Station */
    register_segment(0x0001, 2, "North Station");
    configure_meter(0x0101, PT_FLOW_RATE,    PT_PRESSURE, PT_MOTOR_TEMP, 150.0);
    configure_meter(0x0102, PT_PUMP_SPEED,   PT_PRESSURE, PT_MOTOR_TEMP, 125.0);

    /* Segment 2: Central Hub */
    register_segment(0x0002, 3, "Central Hub");
    configure_meter(0x0201, PT_FLOW_RATE,    PT_PRESSURE, PT_MOTOR_TEMP, 175.0);
    configure_meter(0x0202, PT_VALVE_POS,    PT_TANK_LEVEL, PT_SETPOINT, 100.0);

    /* Segment 3: South Export */
    register_segment(0x0003, 2, "South Export");
    configure_meter(0x0301, PT_FLOW_RATE,    PT_PRESSURE, PT_MOTOR_TEMP, 160.0);

    printf("\n[INIT] Total: %d segments, %d meters configured\n\n",
           g_segment_count, g_meter_count);
}

/* --- Static helper: leak detector network setup ------------- */
static void setup_leak_detection(void)
{
    printf("[INIT] Setting up leak detection network\n\n");

    /* Mass-balance detectors per segment */
    arm_leak_detector(0x0A01, 0x0001, 2.5);   /* North: 2.5% imbalance threshold */
    arm_leak_detector(0x0A02, 0x0002, 1.8);   /* Central: stricter 1.8% */
    arm_leak_detector(0x0A03, 0x0003, 2.0);   /* South: 2.0% */

    printf("[INIT] %d leak detectors armed\n\n", g_detector_count);
}

/* --- Static helper: event listener registration -------------- */
static int register_event_handlers(void)
{
    int rc;

    printf("[INIT] Registering event handlers\n");

    /* Register scan-cycle event handler */
    rc = scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)pl_on_scan);
    if (rc != 0) {
        fprintf(stderr, "ERROR: failed to register EVT_SCAN_CYCLE handler\n");
        return -1;
    }
    printf("[INIT]   -> EVT_SCAN_CYCLE -> pl_on_scan\n");

    /* Register alarm event handler */
    rc = scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)pl_on_leak);
    if (rc != 0) {
        fprintf(stderr, "ERROR: failed to register EVT_ALARM_RAISED handler\n");
        return -1;
    }
    printf("[INIT]   -> EVT_ALARM_RAISED -> pl_on_leak\n");

    return 0;
}

/* --- Static helper: timer/background task launch ------------ */
static int launch_tasks(void)
{
    int rc;

    printf("[INIT] Launching background tasks and timers\n");

    /* Start scan cycle timer (every 200 ms) */
    rc = scf_timer_start(TMR_SCAN, 200, (TimerCb)pl_scan_timer);
    if (rc != 0) {
        fprintf(stderr, "ERROR: failed to start TMR_SCAN\n");
        return -1;
    }
    printf("[INIT]   -> TMR_SCAN: 200 ms interval\n");

    /* Fork historian task */
    rc = scf_task_fork(TASK_HIST, (TaskEntry)pl_flow_task);
    if (rc != 0) {
        fprintf(stderr, "ERROR: failed to fork TASK_HIST\n");
        return -1;
    }
    printf("[INIT]   -> TASK_HIST: forked\n");

    return 0;
}

/* --- Static helper: final readiness check ------------------- */
static int final_readiness_check(void)
{
    printf("[INIT] Performing final system readiness checks\n");
    printf("[INIT]   -> Comms stack: %s\n",
           g_app_state.comms_up ? "OK" : "FAIL");
    printf("[INIT]   -> Tag database: OK\n");
    printf("[INIT]   -> Inventory: %d segments, %d meters, %d detectors\n",
           g_segment_count, g_meter_count, g_detector_count);
    printf("[INIT]   -> Watchdog: %s\n",
           g_app_state.watchdog_armed ? "ARMED" : "DISABLED");

    if (!g_app_state.comms_up) {
        fprintf(stderr, "ERROR: comms stack failed\n");
        return -1;
    }
    return 0;
}

/* ============================================================
 * pl_init — Initialization phase: system state setup, database
 * lock acquisition, configuration clear.
 * ============================================================ */
void pl_init(void)
{
    int rc;

    printf("\n===== PIPELINE SCADA INITIALIZATION =====\n\n");

    /* Acquire data block semaphore before modifying state */
    printf("[INIT] Acquiring semaphore SEM_DBLOCK...\n");
    rc = scf_sem_wait(SEM_DBLOCK);
    if (rc != 0) {
        fprintf(stderr, "ERROR: SEM_DBLOCK acquisition failed\n");
        return;
    }
    printf("[INIT] Semaphore acquired\n\n");

    /* Clear scan configuration from any prior run */
    printf("[INIT] Clearing prior scan configuration (CFG_SCAN)\n");
    rc = scf_cfg_clear(CFG_SCAN);
    if (rc != 0) {
        fprintf(stderr, "WARNING: CFG_SCAN clear returned %d\n", rc);
    }
    printf("[INIT] Configuration cleared\n\n");

    /* Initialize core systems */
    if (init_tag_database() != 0) {
        fprintf(stderr, "FATAL: tag database init failed\n");
        return;
    }

    if (init_comms() != 0) {
        fprintf(stderr, "FATAL: comms init failed\n");
        return;
    }

    if (init_queues() != 0) {
        fprintf(stderr, "FATAL: queue init failed\n");
        return;
    }

    /* Build system configuration */
    setup_pipeline_inventory();
    setup_leak_detection();

    /* Configure peripherals */
    init_watchdog();

    /* Register handlers and launch background tasks */
    if (register_event_handlers() != 0) {
        fprintf(stderr, "FATAL: event handler registration failed\n");
        return;
    }

    if (launch_tasks() != 0) {
        fprintf(stderr, "FATAL: task launch failed\n");
        return;
    }

    /* Final checks */
    if (final_readiness_check() != 0) {
        fprintf(stderr, "FATAL: readiness check failed\n");
        return;
    }

    g_app_state.initialized = 1;
    g_app_state.scan_enabled = 1;
    printf("\n[INIT] Initialization complete — system READY\n\n");
}

/* ============================================================
 * pl_scan_timer — Periodic timer callback for scan cycle
 * Triggered at 200 ms interval by the framework.
 * ============================================================ */
void pl_scan_timer(int timer_id)
{
    /* Trigger the scan cycle event if enabled */
    if (g_app_state.scan_enabled && g_app_state.initialized) {
        scf_evt_post(EVT_SCAN_CYCLE, NULL);
    }
}

/* ============================================================
 * main — Entry point
 *
 * Minimal startup: call pl_init, then enter event loop or
 * yield to framework. In a real RTU this would also handle
 * watchdog petting, signal handlers, and graceful shutdown.
 * ============================================================ */
int main(int argc, char *argv[])
{
    (void)argc;
    (void)argv;

    printf("\n╔════════════════════════════════════════════════════════════╗\n");
    printf("║     SCADA Pipeline Process — Synthetic Test Fixture       ║\n");
    printf("║          (Static Tracer Demonstration)                    ║\n");
    printf("╚════════════════════════════════════════════════════════════╝\n\n");

    /* Initialize the application */
    pl_init();

    /* Post startup event to trigger initial diagnostics */
    printf("[MAIN] Posting EVT_STARTUP event\n");
    scf_evt_post(EVT_STARTUP, 0);

    printf("[MAIN] System running. Framework owns event loop.\n\n");

    /* In a real system, this would return 0 only after clean shutdown.
     * For testing, we return immediately. */
    return 0;
}

/* ============================================================
 * GROUND TRUTH (Final Verification)
 *
 * Paths and API signatures as verified by static tracer:
 *
 * 1. main -> scf_evt_post(EVT_STARTUP, 0)
 *    type: EVENT, call_number: 3000
 *
 * 2. main -> scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)pl_on_scan)
 *    type: EVENT, launch_via: EVENT
 *
 * 3. main -> scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)pl_on_leak)
 *    type: EVENT, launch_via: EVENT
 *
 * 4. main -> scf_timer_start(TMR_SCAN, 200, (TimerCb)pl_scan_timer)
 *    type: TIMER, launch_via: TIMER, arg1=50, arg2=200
 *
 * 5. main -> scf_task_fork(TASK_HIST, (TaskEntry)pl_flow_task)
 *    type: FORK, launch_via: FORK, arg1=60
 *
 * 6. pl_init -> scf_sem_wait(SEM_DBLOCK)
 *    type: SEMAPHORE, arg1=80
 *
 * 7. pl_init -> scf_cfg_clear(CFG_SCAN)
 *    type: CLEARF, arg1=300
 * ============================================================ */

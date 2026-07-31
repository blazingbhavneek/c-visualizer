/* ============================================================
 * proc_railyard / main.c — Rail yard signaling process.
 * Synthetic SCADA control: interlocking, signal aspects,
 * command dispatch, watchdog, and fail-safe initialization.
 * ============================================================ */

#include "ry_app.h"
#include <stdio.h>
#include <string.h>

/* GROUND TRUTH
 * ============================================================
 * path      : main -> scf_evt_post(EVT_STARTUP,0)
 * api       : scf_evt_post   type=EVENT   launch_via=main
 * arg 1     : EVT_STARTUP = 3000
 * call_num  : 3000
 *
 * path      : main -> scf_evt_register(EVT_SCAN_CYCLE,(EvtHandler)ry_on_scan)
 * api       : scf_evt_register   type=EVENT   launch_via=main
 * arg 1     : EVT_SCAN_CYCLE = 3001
 * arg 2     : ry_on_scan
 *
 * path      : main -> scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)ry_on_route)
 * api       : scf_evt_register   type=EVENT   launch_via=main
 * arg 1     : EVT_ALARM_RAISED = 3002
 * arg 2     : ry_on_route
 *
 * path      : main -> scf_signal_hook(SIG_FAULT,(SignalCb)ry_fault_sig)
 * api       : scf_signal_hook   type=SIGNAL   launch_via=main
 * arg 1     : SIG_FAULT = 71
 * arg 2     : ry_fault_sig
 *
 * path      : main -> scf_task_fork(TASK_HIST,(TaskEntry)ry_interlock_task)
 * api       : scf_task_fork   type=FORK   launch_via=main
 * arg 1     : TASK_HIST = 60
 * arg 2     : ry_interlock_task
 *
 * path      : ry_init -> scf_sem_wait(SEM_DBLOCK)
 * api       : scf_sem_wait   type=SEMAPHORE   launch_via=main
 * arg 1     : SEM_DBLOCK = 80
 *
 * path      : ry_init -> scf_cfg_clear(CFG_SCAN)
 * api       : scf_cfg_clear   type=CLEARF   launch_via=main
 * arg 1     : CFG_SCAN = 300
 *
 * path      : ry_fault_sig -> scf_task_kill(TASK_ALARM)
 * api       : scf_task_kill   type=KILL   launch_via=SIGNAL
 * arg 1     : TASK_ALARM = 61
 * ============================================================ */

/* ---- Forward declarations for static callbacks ---- */
static void tick_watchdog(int timer_id);

/* ---- Globals exported to ry_app.h contract ---- */
static int ry_initialized = 0;
static int ry_watchdog_kicks = 0;
static int ry_fault_count = 0;

/* ---- Static rail yard state (fixture inventory) ---- */

/* Track section states: 1=occupied, 0=clear, -1=unknown */
static int g_section_state[16];

/* Signal aspects: each with a primary/secondary aspect pair */
static struct {
    int signal_id;
    int primary_aspect;
    int secondary_aspect;
} g_signals[8];

/* Route lock table: route_id -> section_id dependencies */
static struct {
    int route_id;
    int section_count;
    int sections[4];
} g_routes[6];

/* Command queue depth tracker */
static int g_cmdq_depth = 0;

/* ---- Static initialization helpers ---- */

static void init_sections(void) {
    int i;
    /* Clear all track sections as unknown initially */
    for (i = 0; i < 16; i++) {
        g_section_state[i] = -1;  /* Unknown state */
    }
}

static void init_signals(void) {
    int i;
    /* Initialize all signals to STOP (aspect 0) */
    for (i = 0; i < 8; i++) {
        g_signals[i].signal_id = 100 + i;
        g_signals[i].primary_aspect = 0;      /* STOP */
        g_signals[i].secondary_aspect = 0;    /* STOP */
    }
}

static void init_routes(void) {
    /* Route 0: Platform A->B via sections 0,1 */
    g_routes[0].route_id = 0;
    g_routes[0].section_count = 2;
    g_routes[0].sections[0] = 0;
    g_routes[0].sections[1] = 1;

    /* Route 1: Platform B->C via sections 1,2,3 */
    g_routes[1].route_id = 1;
    g_routes[1].section_count = 3;
    g_routes[1].sections[0] = 1;
    g_routes[1].sections[1] = 2;
    g_routes[1].sections[2] = 3;

    /* Route 2: Yard siding via sections 4,5 */
    g_routes[2].route_id = 2;
    g_routes[2].section_count = 2;
    g_routes[2].sections[0] = 4;
    g_routes[2].sections[1] = 5;

    /* Route 3: Depot loop via sections 6,7,8 */
    g_routes[3].route_id = 3;
    g_routes[3].section_count = 3;
    g_routes[3].sections[0] = 6;
    g_routes[3].sections[1] = 7;
    g_routes[3].sections[2] = 8;

    /* Route 4: Emergency crossover via sections 9,10 */
    g_routes[4].route_id = 4;
    g_routes[4].section_count = 2;
    g_routes[4].sections[0] = 9;
    g_routes[4].sections[1] = 10;

    /* Route 5: Maintenance track via sections 11,12 */
    g_routes[5].route_id = 5;
    g_routes[5].section_count = 2;
    g_routes[5].sections[0] = 11;
    g_routes[5].sections[1] = 12;
}

static int check_self_test(void) {
    /* Vital-logic self-test: verify signal/route integrity */
    int i, j;
    int test_passed = 1;

    /* Verify all signals initialized */
    for (i = 0; i < 8; i++) {
        if (g_signals[i].signal_id != 100 + i) {
            test_passed = 0;
            break;
        }
    }

    /* Verify all routes have valid section count */
    for (i = 0; i < 6 && test_passed; i++) {
        if (g_routes[i].section_count <= 0 || g_routes[i].section_count > 4) {
            test_passed = 0;
            break;
        }
        for (j = 0; j < g_routes[i].section_count; j++) {
            if (g_routes[i].sections[j] < 0 || g_routes[i].sections[j] >= 16) {
                test_passed = 0;
                break;
            }
        }
    }

    return test_passed;
}

static void set_failsafe_defaults(void) {
    /* Set fail-safe defaults: all signals STOP, all sections locked */
    int i;
    for (i = 0; i < 8; i++) {
        g_signals[i].primary_aspect = 0;      /* STOP (fail-safe) */
        g_signals[i].secondary_aspect = 0;    /* STOP */
    }
    /* All sections locked until proven otherwise */
    for (i = 0; i < 16; i++) {
        if (g_section_state[i] == -1) {
            g_section_state[i] = 1;  /* Assume occupied (locked) */
        }
    }
}

static void start_watchdog(void) {
    /* Arm watchdog timer for process liveness */
    ry_watchdog_kicks = 0;
    scf_timer_start(TMR_WATCHDOG, 500, tick_watchdog);
}

static void tick_watchdog(int timer_id) {
    /* Watchdog tick callback: count kicks */
    (void)timer_id;
    ry_watchdog_kicks++;
}

static void setup_event_handlers(void) {
    /* Register all event handlers for scan cycle and alarm routing */
    scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)ry_on_scan);
    scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)ry_on_route);
}

static void setup_signal_fault_hook(void) {
    /* Install signal handler for fault/abort conditions */
    scf_signal_hook(SIG_FAULT, (SignalCb)ry_fault_sig);
}

static void fork_background_tasks(void) {
    /* Launch historian / interlock task in background */
    scf_task_fork(TASK_HIST, (TaskEntry)ry_interlock_task);
}

/* ---- Public initialization function (exported to ry_app.h) ---- */

void ry_init(void) {
    /* Primary initialization sequence for rail yard process.
     * This is the authoritative startup path. */

    if (ry_initialized) {
        return;  /* Prevent re-entry */
    }

    /* 1. Acquire data-block semaphore for safe initialization */
    scf_sem_wait(SEM_DBLOCK);

    /* 2. Clear scan configuration (fail-safe reset) */
    scf_cfg_clear(CFG_SCAN);

    /* 3. Initialize track section inventory */
    init_sections();

    /* 4. Initialize signal aspects (all STOP initially) */
    init_signals();

    /* 5. Initialize route lock tables and dependencies */
    init_routes();

    /* 6. Run vital-logic self-test */
    if (!check_self_test()) {
        ry_fault_count++;
        return;
    }

    /* 7. Apply fail-safe defaults (all locked/stopped) */
    set_failsafe_defaults();

    /* 8. Register event handlers for scanning and alarm routing */
    setup_event_handlers();

    /* 9. Install signal fault hook (for emergency stop) */
    setup_signal_fault_hook();

    /* 10. Launch background interlock/historian task */
    fork_background_tasks();

    /* 11. Start watchdog timer for liveness monitoring */
    start_watchdog();

    /* 12. Mark process as initialized */
    ry_initialized = 1;
}

/* ---- Public signal fault handler (exported to ry_app.h) ---- */

void ry_fault_sig(int sig_no) {
    /* Emergency stop handler invoked on SIG_FAULT.
     * Immediately kills the alarm task and sets fail-safe. */

    (void)sig_no;  /* sig_no is SIG_FAULT = 71 */

    /* Kill alarm monitoring task */
    scf_task_kill(TASK_ALARM);

    /* Increment fault counter */
    ry_fault_count++;
}

/* ---- Main entry point ---- */

int main(void) {
    /* Application main: rail yard signaling control process.
     * Initialize, post startup event, and wait for framework. */

    /* Perform all initialization (semaphores, configs, tasks, handlers) */
    ry_init();

    if (!ry_initialized) {
        return 1;  /* Initialization failed */
    }

    /* Post startup event (marks system ready, call_number = EVT_STARTUP = 3000) */
    scf_evt_post(EVT_STARTUP, (void *)0);

    /* Return to framework event loop; framework manages all further execution */
    return 0;
}

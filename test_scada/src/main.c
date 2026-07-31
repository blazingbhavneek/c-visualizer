#include "app.h"
#include "scf_event.h"
#include "scf_tag.h"
#include "scf_const.h"

/* GROUND TRUTH
 *
 * main -> scf_evt_post
 *   api: scf_evt_post  type=EVENT  launch=EVENT
 *   arg1: EVT_STARTUP = 3000
 *
 * main -> init_subsystems -> DioGetPtr -> scf_tag_open
 *   api: scf_tag_open  type=OPENF  launch=FORK
 *   arg2: PT_TANK_LEVEL = 0x1003
 *
 * main -> init_subsystems -> scf_cfg_clear
 *   api: scf_cfg_clear  type=CLEARF  launch=FORK
 *   arg1: CFG_SCAN = 300
 *
 * main -> init_subsystems -> scf_sem_wait
 *   api: scf_sem_wait  type=SEMAPHORE  launch=SEMAPHORE
 *   arg1: SEM_DBLOCK = 80
 *
 * main -> scf_evt_register(EVT_SCAN_CYCLE) -> on_scan_cycle
 *   launch_via: EVENT (path continues in scan_proc.c)
 *
 * main -> scf_evt_register(EVT_ALARM_RAISED) -> on_alarm
 *   launch_via: EVENT (path continues in alarm_proc.c)
 *
 * main -> scf_timer_start(TMR_WATCHDOG) -> tick_watchdog -> scf_task_kill
 *   api: scf_task_kill  type=KILL  launch=TIMER
 *   arg1: TASK_ALARM = 61
 *
 * main -> scf_task_fork(TASK_HIST) -> hist_task_entry
 *   launch_via: FORK (path continues in hist_proc.c)
 *
 * main -> scf_input_bind(CHAN_KEYPAD) -> keypad_cb -> scf_tag_write
 *   api: scf_tag_write  type=WRITEF  launch=INPUT
 *   arg2: PT_SETPOINT = 0x1007
 *   arg3: value (UNRESOLVED, comes from framework)
 */

/* ========================================================================
 * Static keypad input handler
 * ======================================================================== */
static void keypad_cb(int chan, int value)
{
    /* Operator input: write setpoint via shared snapshot context. */
    scf_tag_write(&g_snap_ctx, PT_SETPOINT, value);
}

/* ========================================================================
 * Initialize subsystems: acquire locks, prime DI/O cache, clear config
 * ======================================================================== */
void init_subsystems(void)
{
    /* Acquire database lock before any tag operations. */
    scf_sem_wait(SEM_DBLOCK);

    /* Prime the DI/O layer for tank level (triggers tag_open in dio_layer). */
    (void)DioGetPtr(PT_TANK_LEVEL);

    /* Clear scan configuration to factory defaults. */
    scf_cfg_clear(CFG_SCAN);

    /* Pre-populate pressure sensor cache. */
    (void)dio_prime_cache(PT_PRESSURE);
}

/* ========================================================================
 * Watchdog timer handler: periodic health check and alarm task management
 * ======================================================================== */
void tick_watchdog(int timer_id)
{
    /* Release database lock for other tasks. */
    scf_sem_post(SEM_DBLOCK);

    /* Terminate stuck alarm processor. */
    scf_task_kill(TASK_ALARM);
}

/* ========================================================================
 * Main entry point: SCADA process startup and event loop wiring
 * ======================================================================== */
int main(void)
{
    /* Signal process startup to framework and audit log. */
    scf_evt_post(EVT_STARTUP, 0);

    /* Register scan cycle handler (triggered by framework EVT_SCAN_CYCLE). */
    scf_evt_register(EVT_SCAN_CYCLE, (EvtHandler)on_scan_cycle);

    /* Register alarm handler (triggered by framework EVT_ALARM_RAISED). */
    scf_evt_register(EVT_ALARM_RAISED, (EvtHandler)on_alarm);

    /* Start periodic watchdog timer (500 ms, triggers tick_watchdog). */
    scf_timer_start(TMR_WATCHDOG, 500, (TimerCb)tick_watchdog);

    /* Fork background historian task (runs hist_task_entry). */
    scf_task_fork(TASK_HIST, (TaskEntry)hist_task_entry);

    /* Bind keypad input channel to local operator handler. */
    scf_input_bind(CHAN_KEYPAD, (InputCb)keypad_cb);

    /* Initialize subsystems: locks, DI/O, config. */
    init_subsystems();

    /* Load application configuration (tag defaults, alarm thresholds). */
    mf_apply_config();

    /* Run edge-case simulator and other extended test flows. */
    ec_run();

    return 0;
}

/* ============================================================
 * proc_railyard / ry_route.c — Rail yard routing and command
 * sequencing. Handles route requests, conflict resolution,
 * dwell/headway timers, command enqueue/process lifecycle.
 * ============================================================ */

#include "ry_app.h"
#include "scf_const.h"
#include "scf_types.h"
#include "scf_queue.h"
#include "scf_event.h"

/* ============================================================
 * CONSTANTS
 * ============================================================ */

#define MAX_ROUTES           16
#define MAX_SECTIONS         32
#define MAX_ROUTE_REQS       64
#define MAX_ASPECTS_PER_ROUTE 5
#define MAX_DWELL_TIMERS     8
#define DWELL_TIMEOUT_MS     3000
#define HEADWAY_MIN_MS       2500
#define ROUTE_CONFLICT_THRESHOLD 50  /* Arbitrary occupancy metric */

/* Aspect codes (signal states) */
#define ASPECT_STOP          0x10
#define ASPECT_APPROACH      0x20
#define ASPECT_PROCEED       0x30
#define ASPECT_CLEAR         0x40

/* Command codes (route/signal operations) */
#define CMD_SET_SIGNAL       0x0001
#define CMD_SET_SWITCH       0x0002
#define CMD_LOCK_SECTION     0x0004
#define CMD_RESERVE_PATH     0x0008
#define CMD_CLEAR_PATH       0x0010
#define CMD_CHECK_OCCUPANCY  0x0020

/* Priority levels */
#define PRIORITY_LOW         1
#define PRIORITY_NORMAL      2
#define PRIORITY_HIGH        3
#define PRIORITY_URGENT      4

/* ============================================================
 * STATIC DATA STRUCTURES
 * ============================================================ */

/* Route definition: which sections, entry/exit signals, aspects sequence */
typedef struct {
    int route_id;
    int entry_signal;
    int exit_signal;
    int section_list[8];          /* Section IDs this route uses */
    int section_count;
    int aspect_sequence[MAX_ASPECTS_PER_ROUTE];  /* Sequence of aspect codes */
    int aspect_count;
    int priority;                  /* Route priority level */
    int headway_ms;               /* Min time between trains */
    int dwell_ms;                 /* Train dwell duration */
} RouteConfig;

/* Route reservation (current lock state) */
typedef struct {
    int route_id;
    int reserved_by;              /* Which train/job reserved this route */
    int section_lock[MAX_SECTIONS]; /* Per-section ownership (train_id or 0) */
    int timestamp;                /* When locked */
    int expires_at;               /* Lock expiry for deadlock prevention */
} RouteReservation;

/* Route request in queue */
typedef struct {
    int req_id;
    int route_id;
    int train_id;
    int priority;
    int timestamp;
    int retry_count;
} RouteRequest;

/* Dwell timer for headway tracking */
typedef struct {
    int route_id;
    int start_time;
    int end_time;
    int last_train_id;
} DwellTimer;

/* Command in process */
typedef struct {
    int cmd_id;
    int cmd_code;
    int param1;
    int param2;
    int status;                   /* Pending, active, complete */
} CommandRecord;

/* ============================================================
 * STATIC MODULE STATE
 * ============================================================ */

/* Route configuration table (static; pre-populated) */
static RouteConfig route_table[MAX_ROUTES] = {
    {1, PT_PUMP_SPEED, PT_VALVE_POS, {1, 2, 3}, 3, {ASPECT_STOP, ASPECT_APPROACH, ASPECT_PROCEED}, 3, PRIORITY_NORMAL, 2500, 1500},
    {2, PT_VALVE_POS, PT_TANK_LEVEL, {2, 4}, 2, {ASPECT_STOP, ASPECT_PROCEED}, 2, PRIORITY_NORMAL, 2600, 1600},
    {3, PT_TANK_LEVEL, PT_FLOW_RATE, {1, 5}, 2, {ASPECT_STOP, ASPECT_APPROACH, ASPECT_PROCEED}, 3, PRIORITY_HIGH, 2400, 1400},
    {4, PT_FLOW_RATE, PT_MOTOR_TEMP, {3, 6}, 2, {ASPECT_APPROACH, ASPECT_PROCEED}, 2, PRIORITY_LOW, 2800, 1800},
    {5, PT_MOTOR_TEMP, PT_PRESSURE, {4, 5, 7}, 3, {ASPECT_STOP, ASPECT_APPROACH, ASPECT_PROCEED}, 3, PRIORITY_NORMAL, 2500, 1500},
};
static int route_table_count = 5;

/* Path reservation state (which routes/trains own which sections) */
static RouteReservation reservations[MAX_ROUTES];

/* Route request queue (ring buffer) */
static RouteRequest req_queue[MAX_ROUTE_REQS];
static int req_head = 0;
static int req_tail = 0;
static int req_count = 0;

/* Dwell/headway timers */
static DwellTimer dwell_timers[MAX_DWELL_TIMERS];
static int dwell_timer_count = 0;

/* Sequencing state machine (per route) */
static int route_aspect_state[MAX_ROUTES];       /* Current aspect for each route */
static int route_sequence_idx[MAX_ROUTES];       /* Index in aspect sequence */

/* Command being processed */
static CommandRecord current_command;
static int command_seq_counter = 0;

/* Priority preemption queue (for high-priority routing) */
static int preemption_queue[MAX_ROUTES];
static int preemption_count = 0;

/* Conflict matrix: routes_conflict[i][j] = 1 if route i conflicts with route j */
static int routes_conflict[MAX_ROUTES][MAX_ROUTES];

/* Occupancy/status tracking (simulated sensor readings) */
static int section_occupancy[MAX_SECTIONS];
static int route_status[MAX_ROUTES];             /* 0=idle, 1=active, 2=reserved */

/* ============================================================
 * STATIC HELPER FUNCTIONS
 * ============================================================ */

/* Retrieve route configuration by ID */
static RouteConfig *load_route_table(int route_id) {
    int i;
    for (i = 0; i < route_table_count; i++) {
        if (route_table[i].route_id == route_id) {
            return &route_table[i];
        }
    }
    return 0;  /* Not found */
}

/* Build conflict matrix (static analysis of which routes interfere) */
static void build_conflict_matrix(void) {
    int i, j, k, l, conflict;
    RouteConfig *cfg_i, *cfg_j;

    for (i = 0; i < MAX_ROUTES; i++) {
        for (j = 0; j < MAX_ROUTES; j++) {
            routes_conflict[i][j] = 0;
        }
    }

    /* Two routes conflict if they share a section */
    for (i = 0; i < route_table_count; i++) {
        cfg_i = &route_table[i];
        for (j = i + 1; j < route_table_count; j++) {
            cfg_j = &route_table[j];
            conflict = 0;

            for (k = 0; k < cfg_i->section_count; k++) {
                for (l = 0; l < cfg_j->section_count; l++) {
                    if (cfg_i->section_list[k] == cfg_j->section_list[l]) {
                        conflict = 1;
                        break;
                    }
                }
                if (conflict) break;
            }

            if (conflict) {
                routes_conflict[i][j] = 1;
                routes_conflict[j][i] = 1;
            }
        }
    }
}

/* Check if a route can be reserved (no conflicts, no occupancy) */
static int is_route_available(int route_id) {
    int i, section_id, conflict_score;
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return 0;

    /* Check each section for occupancy */
    conflict_score = 0;
    for (i = 0; i < cfg->section_count; i++) {
        section_id = cfg->section_list[i];
        if (section_occupancy[section_id] > ROUTE_CONFLICT_THRESHOLD) {
            conflict_score += section_occupancy[section_id];
        }
    }

    /* If occupancy too high, route unavailable */
    if (conflict_score > (cfg->section_count * ROUTE_CONFLICT_THRESHOLD)) {
        return 0;
    }

    /* Check if any section already reserved by another train */
    for (i = 0; i < cfg->section_count; i++) {
        section_id = cfg->section_list[i];
        if (reservations[route_id].section_lock[section_id] != 0 &&
            reservations[route_id].section_lock[section_id] != route_id) {
            return 0;
        }
    }

    return 1;  /* Route available */
}

/* Reserve a path: lock down all sections for a route */
static int reserve_path(int route_id, int train_id) {
    int i, section_id;
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return -1;

    for (i = 0; i < cfg->section_count; i++) {
        section_id = cfg->section_list[i];
        reservations[route_id].section_lock[section_id] = train_id;
    }

    reservations[route_id].route_id = route_id;
    reservations[route_id].reserved_by = train_id;
    reservations[route_id].timestamp = 100;  /* Simulated */
    reservations[route_id].expires_at = 100 + cfg->dwell_ms;

    route_status[route_id] = 2;  /* Mark as reserved */

    return 0;
}

/* Release path locks for a route */
static int clear_reservations(int route_id, int train_id) {
    int i, section_id;
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return -1;

    /* Only release if this train holds the lock */
    if (reservations[route_id].reserved_by != train_id) {
        return -1;
    }

    for (i = 0; i < cfg->section_count; i++) {
        section_id = cfg->section_list[i];
        if (reservations[route_id].section_lock[section_id] == train_id) {
            reservations[route_id].section_lock[section_id] = 0;
        }
    }

    reservations[route_id].reserved_by = 0;
    route_status[route_id] = 0;  /* Mark as idle */

    return 0;
}

/* Check conflict between two routes */
static int check_conflicts(int route_id1, int route_id2) {
    if (route_id1 < 0 || route_id1 >= MAX_ROUTES) return 0;
    if (route_id2 < 0 || route_id2 >= MAX_ROUTES) return 0;

    return routes_conflict[route_id1][route_id2];
}

/* Calculate minimum dwell time (headway) for a route */
static int calc_dwell_time(int route_id) {
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return DWELL_TIMEOUT_MS;

    /* Higher priority routes get shorter dwell */
    if (cfg->priority == PRIORITY_URGENT) {
        return HEADWAY_MIN_MS - 500;
    }
    if (cfg->priority == PRIORITY_HIGH) {
        return HEADWAY_MIN_MS;
    }

    return cfg->dwell_ms;
}

/* State machine: advance aspect sequence for a route */
static int sequencer_next_aspect(int route_id) {
    RouteConfig *cfg = load_route_table(route_id);
    int next_idx;

    if (!cfg) return ASPECT_STOP;

    next_idx = route_sequence_idx[route_id] + 1;
    if (next_idx >= cfg->aspect_count) {
        next_idx = 0;  /* Wrap around to start */
    }

    route_sequence_idx[route_id] = next_idx;
    route_aspect_state[route_id] = cfg->aspect_sequence[next_idx];

    return cfg->aspect_sequence[next_idx];
}

/* Validate a command code */
static int validate_command(int cmd_code) {
    switch (cmd_code) {
        case CMD_SET_SIGNAL:
        case CMD_SET_SWITCH:
        case CMD_LOCK_SECTION:
        case CMD_RESERVE_PATH:
        case CMD_CLEAR_PATH:
        case CMD_CHECK_OCCUPANCY:
            return 1;
        default:
            return 0;
    }
}

/* Execute an aspect setting (apply signal command) */
static int execute_aspect_set(int route_id, int aspect) {
    int signal_point;
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return -1;

    signal_point = cfg->entry_signal;

    /* In real code, would scf_tag_write() to the signal hardware.
     * For trace testing, we just track state. */
    route_aspect_state[route_id] = aspect;

    return 0;
}

/* Handle priority preemption (high-priority route overrides low) */
static int handle_priority_preemption(int new_route_id) {
    int i, victim_route, victim_priority;
    RouteConfig *new_cfg = load_route_table(new_route_id);
    RouteConfig *victim_cfg;

    if (!new_cfg) return 0;

    /* Find lowest-priority active route that conflicts with new one */
    victim_priority = 999;
    victim_route = -1;

    for (i = 0; i < route_table_count; i++) {
        if (route_status[i] == 1) {  /* Active */
            if (check_conflicts(new_route_id, route_table[i].route_id)) {
                if (route_table[i].priority < victim_priority) {
                    victim_priority = route_table[i].priority;
                    victim_route = i;
                }
            }
        }
    }

    /* If victim found and new route has higher priority, preempt */
    if (victim_route >= 0 && new_cfg->priority > victim_priority) {
        clear_reservations(victim_route, 1);  /* Dummy train_id=1 */
        return 1;  /* Preemption occurred */
    }

    return 0;  /* No preemption */
}

/* Enqueue a route request */
static int route_request_enqueue(int route_id, int train_id, int priority) {
    if (req_count >= MAX_ROUTE_REQS) {
        return -1;  /* Queue full */
    }

    req_queue[req_tail].req_id = req_count;
    req_queue[req_tail].route_id = route_id;
    req_queue[req_tail].train_id = train_id;
    req_queue[req_tail].priority = priority;
    req_queue[req_tail].timestamp = 100;  /* Simulated */
    req_queue[req_tail].retry_count = 0;

    req_tail = (req_tail + 1) % MAX_ROUTE_REQS;
    req_count++;

    return req_queue[req_tail].req_id;
}

/* Dequeue a route request */
static RouteRequest *route_request_dequeue(void) {
    RouteRequest *req;

    if (req_count == 0) {
        return 0;  /* Queue empty */
    }

    req = &req_queue[req_head];
    req_head = (req_head + 1) % MAX_ROUTE_REQS;
    req_count--;

    return req;
}

/* Start a dwell timer for headway tracking */
static int start_dwell_timer(int route_id, int train_id) {
    if (dwell_timer_count >= MAX_DWELL_TIMERS) {
        return -1;  /* No free timers */
    }

    dwell_timers[dwell_timer_count].route_id = route_id;
    dwell_timers[dwell_timer_count].start_time = 100;  /* Simulated */
    dwell_timers[dwell_timer_count].end_time = 100 + calc_dwell_time(route_id);
    dwell_timers[dwell_timer_count].last_train_id = train_id;

    dwell_timer_count++;
    return 0;
}

/* Check if headway minimum is satisfied for a route */
static int check_headway(int route_id) {
    int i, elapsed;

    for (i = 0; i < dwell_timer_count; i++) {
        if (dwell_timers[i].route_id == route_id) {
            elapsed = 101 - dwell_timers[i].start_time;  /* Simulated time */
            if (elapsed < dwell_timers[i].end_time - dwell_timers[i].start_time) {
                return 0;  /* Still in dwell period */
            }
        }
    }

    return 1;  /* Headway satisfied or no prior dwell */
}

/* Post a routing status message to message queue */
static int post_routing_status(int route_id, int status_code) {
    char msg_buf[64];
    int ret;

    /* Format: "RY_ROUTE_STATUS: route=X status=Y" */
    msg_buf[0] = (char)route_id;
    msg_buf[1] = (char)status_code;

    ret = scf_msgq_write(Q_MSG, msg_buf);
    return ret;
}

/* Check occupancy sensors for a route's sections */
static int update_occupancy(int route_id) {
    RouteConfig *cfg = load_route_table(route_id);
    int i, section_id, total = 0;

    if (!cfg) return 0;

    for (i = 0; i < cfg->section_count; i++) {
        section_id = cfg->section_list[i];
        /* In real code, would read actual sensors.
         * Here we simulate a baseline with some variance. */
        section_occupancy[section_id] = (route_id * 3 + i) % 100;
        total += section_occupancy[section_id];
    }

    return total / cfg->section_count;  /* Average occupancy */
}

/* Validate route can be set (permissions, interlocks, etc.) */
static int validate_route(int route_id) {
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return 0;

    /* Check that entry/exit signals are not already reserved */
    if (reservations[route_id].reserved_by != 0) {
        return 0;  /* Already reserved */
    }

    return 1;  /* Valid */
}

/* Mark command as active in processing queue */
static int mark_command_active(int cmd_id) {
    current_command.cmd_id = cmd_id;
    current_command.status = 1;  /* Active */
    return 0;
}

/* Mark command as complete */
static int mark_command_complete(int cmd_id) {
    current_command.status = 2;  /* Complete */
    return 0;
}

/* ============================================================
 * EXPORTED FUNCTIONS (from ry_app.h)
 * ============================================================ */

/* Event handler for EVT_ALARM_RAISED: route selection triggered by alarm */
void ry_on_route(int evt, void *data) {
    int route_id = 5;  /* Hardcoded for trace: must be 5 */

    /* Call scf_var_evt to establish call_number=3002 for trace */
    scf_var_evt(EVT_ALARM_RAISED, 1, data);

    /* Process route setting */
    ry_set_route(route_id);
}

/* Set up a route: reserve path, sequence aspects, enqueue commands */
int ry_set_route(int route_id) {
    RouteConfig *cfg;
    int i, aspect, cmd_code;

    /* Validate route exists */
    cfg = load_route_table(route_id);
    if (!cfg) {
        return -1;
    }

    /* Check route availability and headway */
    if (!is_route_available(route_id)) {
        return -1;
    }
    if (!check_headway(route_id)) {
        return -1;
    }

    /* Handle preemption if needed */
    handle_priority_preemption(route_id);

    /* Update occupancy for decision-making */
    update_occupancy(route_id);

    /* Reserve the path */
    if (reserve_path(route_id, 1) < 0) {  /* Dummy train_id=1 */
        return -1;
    }

    /* Sequence through aspects (signal progression) */
    for (i = 0; i < cfg->aspect_count; i++) {
        aspect = sequencer_next_aspect(route_id);
        execute_aspect_set(route_id, aspect);

        /* Enqueue command for each aspect transition */
        cmd_code = CMD_SET_SIGNAL;
        if (ry_cmd_enqueue(cmd_code) < 0) {
            clear_reservations(route_id, 1);
            return -1;
        }
    }

    /* Mark route as active */
    route_status[route_id] = 1;

    /* Start dwell timer for next request's headway */
    start_dwell_timer(route_id, 1);

    /* Post status message */
    post_routing_status(route_id, 1);

    return 0;
}

/* Enqueue a command to the command queue (part of full lifecycle) */
int ry_cmd_enqueue(int cmd_code) {
    int ret;

    /* Validate command */
    if (!validate_command(cmd_code)) {
        return -1;
    }

    /* Allocate command ID */
    command_seq_counter++;
    current_command.cmd_id = command_seq_counter;
    current_command.cmd_code = cmd_code;
    current_command.status = 0;  /* Pending */

    /* Enqueue to alarm queue with command code as alarm ID */
    /* GROUND TRUTH: scf_alarmq_enq(Q_CMD,code) ENQ arg1=12 */
    ret = scf_alarmq_enq(Q_CMD, cmd_code);
    if (ret < 0) {
        return -1;
    }

    /* Save command to persistent queue */
    /* GROUND TRUTH: scf_cmdq_save(Q_CMD) SAVEQ arg1=12 */
    ret = scf_cmdq_save(Q_CMD);
    if (ret < 0) {
        return -1;
    }

    return current_command.cmd_id;
}

/* Process a command from the command queue (full lifecycle) */
int ry_cmd_process(void) {
    int ret, cmd_code, out_code;
    char msg_buf[32];
    void *out = &out_code;

    /* Load command from persistent queue */
    /* GROUND TRUTH: scf_cmdq_load(Q_CMD) LOADQ arg1=12 */
    ret = scf_cmdq_load(Q_CMD);
    if (ret < 0) {
        return -1;  /* No command available */
    }

    /* Dequeue from alarm queue */
    /* GROUND TRUTH: scf_alarmq_deq(Q_CMD,out) DEQ arg1=12 */
    ret = scf_alarmq_deq(Q_CMD, out);
    if (ret < 0) {
        return -1;
    }

    /* Mark command as active (in-flight) */
    mark_command_active(current_command.cmd_id);

    /* Execute command based on code */
    switch (out_code) {
        case CMD_SET_SIGNAL:
            /* Would execute signal aspect setting */
            break;
        case CMD_SET_SWITCH:
            /* Would execute switch point machine */
            break;
        case CMD_LOCK_SECTION:
            /* Would assert section lock */
            break;
        case CMD_RESERVE_PATH:
            /* Would commit path reservation */
            break;
        case CMD_CLEAR_PATH:
            /* Would release path */
            break;
        case CMD_CHECK_OCCUPANCY:
            /* Would read occupancy sensor */
            break;
    }

    /* Clear queue entry (mark as processed) */
    /* GROUND TRUTH: scf_cmdq_clear(Q_CMD) CLEARQ arg1=12 */
    ret = scf_cmdq_clear(Q_CMD);
    if (ret < 0) {
        return -1;
    }

    /* Write result to message queue */
    /* GROUND TRUTH: scf_msgq_write(Q_MSG,msg) WRITEQ launch=MESSAGE arg1=13 */
    msg_buf[0] = (char)(current_command.cmd_id >> 8);
    msg_buf[1] = (char)(current_command.cmd_id & 0xFF);
    msg_buf[2] = (char)(out_code);
    ret = scf_msgq_write(Q_MSG, msg_buf);
    if (ret < 0) {
        return -1;
    }

    /* Mark command complete */
    mark_command_complete(current_command.cmd_id);

    return current_command.cmd_id;
}

/* ============================================================
 * EXTENDED FUNCTIONS (plausible routing logic)
 * ============================================================ */

/* Process a route request from the queue (drain requests) */
static int process_route_request(void) {
    RouteRequest *req = route_request_dequeue();

    if (!req) {
        return 0;  /* No request available */
    }

    /* Try to satisfy request */
    if (ry_set_route(req->route_id) >= 0) {
        return 1;  /* Successfully set route */
    }

    /* Route unavailable; requeue if retries remain */
    if (req->retry_count < 3) {
        req->retry_count++;
        route_request_enqueue(req->route_id, req->train_id, req->priority);
        return 0;  /* Retry scheduled */
    }

    return -1;  /* Failed after retries */
}

/* Scan route queue and process pending requests */
static int scan_route_queue(void) {
    int processed = 0, result;

    while (req_count > 0) {
        result = process_route_request();
        if (result >= 0) {
            processed++;
        }
    }

    return processed;
}

/* Clear all reservations for maintenance (e.g., during alarm) */
static int clear_all_reservations(void) {
    int i, j;

    for (i = 0; i < MAX_ROUTES; i++) {
        for (j = 0; j < MAX_SECTIONS; j++) {
            reservations[i].section_lock[j] = 0;
        }
        reservations[i].reserved_by = 0;
        route_status[i] = 0;
    }

    return 0;
}

/* Query current state of a route */
static int query_route_state(int route_id) {
    if (route_id < 0 || route_id >= MAX_ROUTES) {
        return -1;
    }
    return route_status[route_id];
}

/* Get current aspect of a route */
static int get_route_aspect(int route_id) {
    if (route_id < 0 || route_id >= MAX_ROUTES) {
        return -1;
    }
    return route_aspect_state[route_id];
}

/* Initialize route subsystem (called at startup) */
static void route_subsystem_init(void) {
    int i, j;

    /* Zero out state */
    for (i = 0; i < MAX_ROUTES; i++) {
        route_aspect_state[i] = ASPECT_STOP;
        route_sequence_idx[i] = 0;
        route_status[i] = 0;

        for (j = 0; j < MAX_SECTIONS; j++) {
            section_occupancy[j] = 0;
            reservations[i].section_lock[j] = 0;
        }
    }

    /* Build conflict matrix */
    build_conflict_matrix();

    /* Initialize command tracking */
    command_seq_counter = 0;
    current_command.status = 0;

    /* Initialize queues */
    req_head = 0;
    req_tail = 0;
    req_count = 0;
    dwell_timer_count = 0;
    preemption_count = 0;
}

/* Periodic maintenance (clean up expired locks, timers) */
static int route_maintenance(void) {
    int i, current_time = 101;  /* Simulated current time */

    /* Check for expired locks */
    for (i = 0; i < MAX_ROUTES; i++) {
        if (reservations[i].reserved_by != 0 &&
            reservations[i].expires_at < current_time) {
            /* Lock expired; release it */
            clear_reservations(i, reservations[i].reserved_by);
        }
    }

    /* Cleanup expired timers */
    for (i = 0; i < dwell_timer_count; i++) {
        if (dwell_timers[i].end_time < current_time) {
            /* Shift remaining timers */
            if (i < dwell_timer_count - 1) {
                dwell_timers[i] = dwell_timers[dwell_timer_count - 1];
            }
            dwell_timer_count--;
        }
    }

    return 0;
}

/* ============================================================
 * EXTENDED ROUTING ANALYSIS & DIAGNOSTICS
 * ============================================================ */

/* Detailed conflict matrix inspection (for debugging route interference) */
static void dump_conflict_matrix(void) {
    int i, j;
    /* Log route conflict relationships for analysis */
    for (i = 0; i < route_table_count; i++) {
        for (j = i + 1; j < route_table_count; j++) {
            if (routes_conflict[i][j]) {
                /* Routes i and j conflict: they share sections */
            }
        }
    }
}

/* Trace route availability and identify blocking route */
static int diagnose_route_unavailable(int route_id) {
    int i, j, section_id;
    RouteConfig *cfg = load_route_table(route_id);
    int blocking_route = -1;

    if (!cfg) return -1;

    for (i = 0; i < cfg->section_count; i++) {
        section_id = cfg->section_list[i];
        if (reservations[route_id].section_lock[section_id] != 0) {
            /* This section is locked by another reservation */
            for (j = 0; j < route_table_count; j++) {
                if (reservations[j].route_id == route_id &&
                    j != route_id) {
                    blocking_route = j;
                    break;
                }
            }
        }
    }

    return blocking_route;
}

/* Compute route priority relative to current active routes */
static int compute_route_priority_rank(int route_id) {
    int rank = 0;
    int i, cfg_priority;
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return -1;

    for (i = 0; i < route_table_count; i++) {
        if (route_status[i] == 1) {  /* Route is active */
            if (route_table[i].priority > cfg->priority) {
                rank++;  /* Count higher-priority routes */
            }
        }
    }

    return rank;
}

/* Analyze headway constraint violations */
static int check_headway_violation(int route_id) {
    int i, min_headway, elapsed;

    for (i = 0; i < dwell_timer_count; i++) {
        if (dwell_timers[i].route_id == route_id) {
            min_headway = dwell_timers[i].end_time - dwell_timers[i].start_time;
            elapsed = 101 - dwell_timers[i].start_time;

            if (elapsed < min_headway) {
                return min_headway - elapsed;  /* Remaining wait time */
            }
        }
    }

    return 0;  /* No violation */
}

/* Compute cumulative reservation age (for preemption decisions) */
static int get_reservation_age(int route_id) {
    int current_time = 101;  /* Simulated */
    if (reservations[route_id].timestamp <= 0) {
        return 0;
    }
    return current_time - reservations[route_id].timestamp;
}

/* ============================================================
 * ADVANCED COMMAND EXECUTION & VALIDATION
 * ============================================================ */

/* Detailed validation of a command before execution */
static int deep_validate_command(int cmd_code, int route_id, int param1) {
    int ret = 0;

    switch (cmd_code) {
        case CMD_SET_SIGNAL:
            /* Verify signal point is valid and not already in target state */
            if (route_id >= 0 && route_id < MAX_ROUTES) {
                ret = 1;
            }
            break;

        case CMD_SET_SWITCH:
            /* Check that switch machine is not in motion */
            if (param1 >= 0 && param1 < MAX_SECTIONS) {
                ret = 1;
            }
            break;

        case CMD_LOCK_SECTION:
            /* Ensure section not already held by conflicting route */
            if (param1 >= 0 && param1 < MAX_SECTIONS &&
                section_occupancy[param1] < ROUTE_CONFLICT_THRESHOLD) {
                ret = 1;
            }
            break;

        case CMD_RESERVE_PATH:
            /* Full path availability check */
            if (is_route_available(route_id) && check_headway(route_id)) {
                ret = 1;
            }
            break;

        case CMD_CLEAR_PATH:
            /* Verify route is currently reserved */
            if (reservations[route_id].reserved_by != 0) {
                ret = 1;
            }
            break;

        case CMD_CHECK_OCCUPANCY:
            /* Occupancy query always valid */
            ret = 1;
            break;
    }

    return ret;
}

/* Execute a command with full error handling */
static int execute_command_safe(int cmd_code, int route_id, int param1, int param2) {
    int ret = -1;

    /* Deep validation first */
    if (!deep_validate_command(cmd_code, route_id, param1)) {
        return -2;  /* Validation failed */
    }

    /* Execute based on command type */
    switch (cmd_code) {
        case CMD_SET_SIGNAL:
            ret = execute_aspect_set(route_id, param1);
            break;

        case CMD_SET_SWITCH:
            /* Simulate switch machine movement */
            ret = 0;
            break;

        case CMD_LOCK_SECTION:
            /* Assert section lock for route */
            ret = 0;
            break;

        case CMD_RESERVE_PATH:
            ret = reserve_path(route_id, param1);
            break;

        case CMD_CLEAR_PATH:
            ret = clear_reservations(route_id, param1);
            break;

        case CMD_CHECK_OCCUPANCY:
            ret = update_occupancy(route_id);
            break;
    }

    return ret;
}

/* ============================================================
 * ADVANCED QUEUE MANAGEMENT & BATCHING
 * ============================================================ */

/* Batch-process multiple commands from queue (if available) */
static int batch_process_commands(int max_batch_size) {
    int i, processed = 0;

    for (i = 0; i < max_batch_size; i++) {
        if (ry_cmd_process() >= 0) {
            processed++;
        } else {
            break;  /* No more commands */
        }
    }

    return processed;
}

/* Peek at next command in queue without dequeuing */
static int peek_next_command(void) {
    /* In real implementation, would inspect queue state */
    return current_command.cmd_code;
}

/* Flush all pending commands (emergency / shutdown mode) */
static int flush_command_queue(void) {
    int flushed = 0;

    while (ry_cmd_process() >= 0) {
        flushed++;
    }

    return flushed;
}

/* ============================================================
 * STATE MACHINE & ASPECT SEQUENCING ANALYSIS
 * ============================================================ */

/* Get the full aspect sequence for a route */
static int get_aspect_sequence(int route_id, int *sequence_out, int max_len) {
    RouteConfig *cfg = load_route_table(route_id);
    int i;

    if (!cfg || max_len < cfg->aspect_count) {
        return -1;
    }

    for (i = 0; i < cfg->aspect_count; i++) {
        sequence_out[i] = cfg->aspect_sequence[i];
    }

    return cfg->aspect_count;
}

/* Predict next aspect in sequence without advancing state */
static int peek_next_aspect(int route_id) {
    RouteConfig *cfg = load_route_table(route_id);
    int next_idx;

    if (!cfg) return -1;

    next_idx = (route_sequence_idx[route_id] + 1) % cfg->aspect_count;
    return cfg->aspect_sequence[next_idx];
}

/* Reset aspect sequence to initial state */
static int reset_aspect_sequence(int route_id) {
    route_sequence_idx[route_id] = 0;
    route_aspect_state[route_id] = ASPECT_STOP;
    return 0;
}

/* ============================================================
 * COMPREHENSIVE STATUS & REPORTING
 * ============================================================ */

/* Get detailed status of a single route */
static int get_route_detail(int route_id) {
    int status = 0;

    if (route_id < 0 || route_id >= MAX_ROUTES) {
        return -1;
    }

    /* Encode: [state_bits|priority_bits|aspect_bits] */
    status = (route_status[route_id] << 20);
    status |= (route_table[route_id].priority << 16);
    status |= (route_aspect_state[route_id] & 0xFFFF);

    return status;
}

/* Report occupancy statistics across all sections */
static int get_occupancy_stats(void) {
    int i, total = 0, max_occupancy = 0;

    for (i = 0; i < MAX_SECTIONS; i++) {
        total += section_occupancy[i];
        if (section_occupancy[i] > max_occupancy) {
            max_occupancy = section_occupancy[i];
        }
    }

    return (max_occupancy << 16) | (total & 0xFFFF);  /* Max and avg */
}

/* Count active routes */
static int count_active_routes(void) {
    int i, count = 0;

    for (i = 0; i < MAX_ROUTES; i++) {
        if (route_status[i] == 1) {
            count++;
        }
    }

    return count;
}

/* Count reserved (but not yet active) routes */
static int count_reserved_routes(void) {
    int i, count = 0;

    for (i = 0; i < MAX_ROUTES; i++) {
        if (route_status[i] == 2) {
            count++;
        }
    }

    return count;
}

/* ============================================================
 * ADVANCED TIMER & OCCUPANCY MANAGEMENT
 * ============================================================ */

/* Extend dwell timer (e.g., if train hasn't vacated yet) */
static int extend_dwell_timer(int route_id, int additional_ms) {
    int i;

    for (i = 0; i < dwell_timer_count; i++) {
        if (dwell_timers[i].route_id == route_id) {
            dwell_timers[i].end_time += additional_ms;
            return 0;
        }
    }

    return -1;  /* Timer not found */
}

/* Cancel a dwell timer (e.g., manual override) */
static int cancel_dwell_timer(int route_id) {
    int i;

    for (i = 0; i < dwell_timer_count; i++) {
        if (dwell_timers[i].route_id == route_id) {
            if (i < dwell_timer_count - 1) {
                dwell_timers[i] = dwell_timers[dwell_timer_count - 1];
            }
            dwell_timer_count--;
            return 0;
        }
    }

    return -1;  /* Timer not found */
}

/* Simulate sensor reading for a section */
static int read_section_sensor(int section_id) {
    if (section_id < 0 || section_id >= MAX_SECTIONS) {
        return -1;
    }

    /* In real code, would read from hardware; here we use simulated state */
    return section_occupancy[section_id];
}

/* Update section occupancy (e.g., from external sensor event) */
static int update_section_occupancy(int section_id, int occupancy_value) {
    if (section_id < 0 || section_id >= MAX_SECTIONS) {
        return -1;
    }

    section_occupancy[section_id] = occupancy_value;
    return 0;
}

/* ============================================================
 * PRIORITY & PREEMPTION MANAGEMENT
 * ============================================================ */

/* Add route to preemption queue */
static int add_preemption_candidate(int route_id) {
    if (preemption_count >= MAX_ROUTES) {
        return -1;  /* Queue full */
    }

    preemption_queue[preemption_count] = route_id;
    preemption_count++;

    return 0;
}

/* Process preemption queue (highest priority first) */
static int process_preemption_queue(void) {
    int i, processed = 0;
    int max_priority_idx = -1, max_priority = 0;

    while (preemption_count > 0) {
        /* Find highest-priority route in queue */
        for (i = 0; i < preemption_count; i++) {
            if (route_table[preemption_queue[i]].priority > max_priority) {
                max_priority = route_table[preemption_queue[i]].priority;
                max_priority_idx = i;
            }
        }

        if (max_priority_idx >= 0) {
            /* Try to set that route */
            if (ry_set_route(preemption_queue[max_priority_idx]) >= 0) {
                processed++;
            }

            /* Remove from preemption queue */
            preemption_queue[max_priority_idx] = preemption_queue[preemption_count - 1];
            preemption_count--;
            max_priority = 0;
            max_priority_idx = -1;
        }
    }

    return processed;
}

/* ============================================================
 * ROUTE CONFIGURATION & METADATA
 * ============================================================ */

/* Get entry signal point ID for a route */
static int get_route_entry_signal(int route_id) {
    RouteConfig *cfg = load_route_table(route_id);
    if (!cfg) return -1;
    return cfg->entry_signal;
}

/* Get exit signal point ID for a route */
static int get_route_exit_signal(int route_id) {
    RouteConfig *cfg = load_route_table(route_id);
    if (!cfg) return -1;
    return cfg->exit_signal;
}

/* Get sections used by a route */
static int get_route_sections(int route_id, int *sections_out, int max_len) {
    RouteConfig *cfg = load_route_table(route_id);
    int i;

    if (!cfg || max_len < cfg->section_count) {
        return -1;
    }

    for (i = 0; i < cfg->section_count; i++) {
        sections_out[i] = cfg->section_list[i];
    }

    return cfg->section_count;
}

/* Get route priority level */
static int get_route_priority(int route_id) {
    RouteConfig *cfg = load_route_table(route_id);
    if (!cfg) return -1;
    return cfg->priority;
}

/* ============================================================
 * COMPREHENSIVE SYSTEM RESET & RECOVERY
 * ============================================================ */

/* Full system reset (emergency / restart) */
static int route_system_reset(void) {
    clear_all_reservations();
    route_subsystem_init();
    return 0;
}

/* Recover from deadlock (clear oldest locks) */
static int recover_from_deadlock(void) {
    int i, oldest_idx = -1;
    int oldest_time = 999999;

    for (i = 0; i < MAX_ROUTES; i++) {
        if (reservations[i].reserved_by != 0) {
            if (get_reservation_age(i) > oldest_time) {
                oldest_time = get_reservation_age(i);
                oldest_idx = i;
            }
        }
    }

    if (oldest_idx >= 0) {
        clear_reservations(oldest_idx, reservations[oldest_idx].reserved_by);
        return 0;
    }

    return -1;
}

/* ============================================================
 * LOGGING & DIAGNOSTIC TRACE FUNCTIONS
 * ============================================================ */

/* Log route request (for audit trail) */
static int log_route_request(int route_id, int train_id, int priority, int status) {
    /* In real implementation, would write to historian.
     * For trace testing, we just record in internal buffer. */
    char audit_buf[32];
    audit_buf[0] = (char)route_id;
    audit_buf[1] = (char)train_id;
    audit_buf[2] = (char)priority;
    audit_buf[3] = (char)status;

    /* Would call scf_hist_save or similar in real code */
    return 0;
}

/* Log command execution with full context */
static int log_command_execution(int cmd_id, int cmd_code, int route_id, int status) {
    /* Comprehensive audit logging */
    char log_entry[48];
    log_entry[0] = (char)(cmd_id >> 8);
    log_entry[1] = (char)(cmd_id & 0xFF);
    log_entry[2] = (char)cmd_code;
    log_entry[3] = (char)route_id;
    log_entry[4] = (char)status;

    return 0;
}

/* Emit diagnostic alert for route conflict */
static int emit_conflict_alert(int route_a, int route_b) {
    char alert_buf[16];
    alert_buf[0] = (char)route_a;
    alert_buf[1] = (char)route_b;

    /* Would use RAISE_ALARM or post to alarmq in real code */
    return 0;
}

/* Emit diagnostic alert for headway violation */
static int emit_headway_alert(int route_id, int remaining_wait) {
    char alert_buf[8];
    alert_buf[0] = (char)route_id;
    alert_buf[1] = (char)(remaining_wait & 0xFF);

    return 0;
}

/* Emit diagnostic alert for deadlock detection */
static int emit_deadlock_alert(void) {
    return 0;
}

/* ============================================================
 * DETAILED CONFLICT RESOLUTION STRATEGIES
 * ============================================================ */

/* Compute minimum wait time before route can proceed */
static int get_minimum_wait_time(int route_id) {
    int i, max_wait = 0, wait_time;

    /* Check headway constraints */
    wait_time = check_headway_violation(route_id);
    if (wait_time > max_wait) max_wait = wait_time;

    /* Check reservation blockers */
    for (i = 0; i < MAX_ROUTES; i++) {
        if (reservations[i].reserved_by != 0 && check_conflicts(route_id, i)) {
            wait_time = reservations[i].expires_at - 101;  /* Time until lock expires */
            if (wait_time > 0 && wait_time > max_wait) {
                max_wait = wait_time;
            }
        }
    }

    return max_wait;
}

/* Identify all blocking routes for a given route */
static int get_blocking_routes(int route_id, int *blockers_out, int max_len) {
    int count = 0, i;

    for (i = 0; i < route_table_count && count < max_len; i++) {
        if (route_status[i] != 0 && check_conflicts(route_id, i)) {
            blockers_out[count++] = i;
        }
    }

    return count;
}

/* Compute compatibility score between two routes (0 = fully incompatible, 10 = fully compatible) */
static int route_compatibility_score(int route_a, int route_b) {
    int conflict_level;

    if (route_a == route_b) return 10;

    /* Higher score if no conflict */
    if (!check_conflicts(route_a, route_b)) {
        return 10;
    }

    /* Compute partial conflict score based on section overlap */
    RouteConfig *cfg_a = load_route_table(route_a);
    RouteConfig *cfg_b = load_route_table(route_b);

    if (!cfg_a || !cfg_b) return 0;

    int shared_sections = 0, i, j;
    for (i = 0; i < cfg_a->section_count; i++) {
        for (j = 0; j < cfg_b->section_count; j++) {
            if (cfg_a->section_list[i] == cfg_b->section_list[j]) {
                shared_sections++;
            }
        }
    }

    /* Score inversely proportional to shared sections */
    return (10 * (cfg_a->section_count + cfg_b->section_count - shared_sections)) /
           (cfg_a->section_count + cfg_b->section_count);
}

/* ============================================================
 * BATCH OPERATIONS & COMPOUND TRANSACTIONS
 * ============================================================ */

/* Atomically reserve multiple routes (compound transaction) */
static int batch_reserve_routes(int *route_ids, int count, int train_id) {
    int i, ret;

    /* Validate all routes first */
    for (i = 0; i < count; i++) {
        if (!is_route_available(route_ids[i])) {
            return -1;  /* Batch failed: not all routes available */
        }
    }

    /* Reserve all routes */
    for (i = 0; i < count; i++) {
        ret = reserve_path(route_ids[i], train_id);
        if (ret < 0) {
            /* Rollback: clear all previously reserved routes */
            int j;
            for (j = 0; j < i; j++) {
                clear_reservations(route_ids[j], train_id);
            }
            return -1;
        }
    }

    return 0;
}

/* Release multiple routes simultaneously */
static int batch_clear_routes(int *route_ids, int count, int train_id) {
    int i, total_cleared = 0;

    for (i = 0; i < count; i++) {
        if (clear_reservations(route_ids[i], train_id) >= 0) {
            total_cleared++;
        }
    }

    return total_cleared;
}

/* Enqueue multiple commands as atomic batch */
static int batch_enqueue_commands(int *cmd_codes, int count) {
    int i, total_enqueued = 0;

    for (i = 0; i < count; i++) {
        if (ry_cmd_enqueue(cmd_codes[i]) >= 0) {
            total_enqueued++;
        } else {
            /* Partial failure: continue for remaining commands */
        }
    }

    return total_enqueued;
}

/* ============================================================
 * TRAFFIC ANALYSIS & SIMULATION
 * ============================================================ */

/* Simulate train occupancy progression through a route */
static int simulate_train_movement(int route_id, int train_id) {
    int i, section_id;
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return -1;

    /* Incrementally increase occupancy through sections */
    for (i = 0; i < cfg->section_count; i++) {
        section_id = cfg->section_list[i];
        if (section_occupancy[section_id] < 50) {
            section_occupancy[section_id] += 20;
        }
    }

    return 0;
}

/* Simulate train departure (clear occupancy) */
static int simulate_train_departure(int route_id) {
    int i, section_id;
    RouteConfig *cfg = load_route_table(route_id);

    if (!cfg) return -1;

    for (i = 0; i < cfg->section_count; i++) {
        section_id = cfg->section_list[i];
        section_occupancy[section_id] = 0;
    }

    return 0;
}

/* ============================================================
 * PERFORMANCE METRICS & ANALYTICS
 * ============================================================ */

/* Count pending route requests in queue */
static int get_pending_request_count(void) {
    return req_count;
}

/* Count active timers */
static int get_active_timer_count(void) {
    return dwell_timer_count;
}

/* Compute average route dwell time across system */
static int get_average_dwell_time(void) {
    int i, total = 0;

    for (i = 0; i < route_table_count; i++) {
        total += route_table[i].dwell_ms;
    }

    return total / route_table_count;
}

/* Get the maximum priority currently active */
static int get_max_active_priority(void) {
    int i, max_priority = 0;

    for (i = 0; i < MAX_ROUTES; i++) {
        if (route_status[i] != 0) {
            if (route_table[i].priority > max_priority) {
                max_priority = route_table[i].priority;
            }
        }
    }

    return max_priority;
}

/* Compute system congestion level (0-100) */
static int get_system_congestion(void) {
    int total_occupancy = 0, i;

    for (i = 0; i < MAX_SECTIONS; i++) {
        total_occupancy += section_occupancy[i];
    }

    return (total_occupancy * 100) / (MAX_SECTIONS * 100);  /* Normalized */
}

/* ============================================================
 * COMMAND QUEUE ANALYSIS & MANAGEMENT
 * ============================================================ */

/* Get current command queue depth */
static int get_command_queue_depth(void) {
    /* In real implementation, would query actual queue state.
     * For now, return symbolic value. */
    return current_command.status == 0 ? 1 : 0;  /* 1 if pending, 0 if processed */
}

/* Retry logic: requeue failed commands */
static int retry_failed_command(int cmd_id, int retry_delay_ms) {
    /* For the given command, schedule retry */
    if (current_command.cmd_id == cmd_id) {
        /* Delay and re-enqueue */
        return ry_cmd_enqueue(current_command.cmd_code);
    }

    return -1;
}

/* Purge commands of a specific type from queue */
static int purge_commands_by_type(int cmd_code) {
    /* In real implementation, would selectively dequeue.
     * Here, we just count potential purge. */
    int purged = 0;

    if (current_command.cmd_code == cmd_code) {
        purged = 1;
        current_command.status = 2;  /* Mark complete without execution */
    }

    return purged;
}

/* ============================================================
 * INTERNAL STATE INSPECTION (debug/testing)
 * ============================================================ */

/* Dump all route reservations for debugging */
static int dump_all_reservations(void) {
    int i, j;

    for (i = 0; i < MAX_ROUTES; i++) {
        if (reservations[i].reserved_by != 0) {
            /* Route i is reserved by train reservations[i].reserved_by */
            for (j = 0; j < MAX_SECTIONS; j++) {
                if (reservations[i].section_lock[j] != 0) {
                    /* Section j is locked by train reservations[i].section_lock[j] */
                }
            }
        }
    }

    return 0;
}

/* Dump all request queue entries */
static int dump_request_queue(void) {
    int i, idx = req_head;

    for (i = 0; i < req_count; i++) {
        /* Enqueued request: route=req_queue[idx].route_id, train=req_queue[idx].train_id */
        idx = (idx + 1) % MAX_ROUTE_REQS;
    }

    return req_count;
}

/* Validate consistency of global state */
static int validate_state_consistency(void) {
    int i, j, lock_count;

    /* Check that each section is locked by at most one route */
    for (j = 0; j < MAX_SECTIONS; j++) {
        lock_count = 0;
        for (i = 0; i < MAX_ROUTES; i++) {
            if (reservations[i].section_lock[j] != 0) {
                lock_count++;
            }
        }
        if (lock_count > 1) {
            return 0;  /* Inconsistent: multiple routes hold same section */
        }
    }

    return 1;  /* Consistent */
}

/* ============================================================
 * GROUND TRUTH
 * ============================================================
 *
 * ry_route.c exercises the full command-queue lifecycle:
 *
 * ry_on_route(int evt, void *data) [EvtHandler for EVT_ALARM_RAISED]:
 *   path:   main -> scf_evt_register(EVT_ALARM_RAISED,(EvtHandler)ry_on_route)
 *           -> (EVENT) -> ry_on_route
 *           -> scf_var_evt(EVT_ALARM_RAISED, 1, data) [call_number=3002]
 *           -> ry_set_route(5)
 *
 * ry_cmd_enqueue(int cmd_code):
 *   path:   ry_set_route -> ry_cmd_enqueue
 *           -> scf_alarmq_enq(Q_CMD, cmd_code)  [ENQ, arg1=12]
 *           -> scf_cmdq_save(Q_CMD)             [SAVEQ, arg1=12]
 *   api:    scf_alarmq_enq  type=ENQ    launch_via=INTERNAL   arg1=Q_CMD=12
 *   api:    scf_cmdq_save   type=SAVEQ  launch_via=INTERNAL   arg1=Q_CMD=12
 *
 * ry_cmd_process(void):
 *   path:   [async / queue processor] -> ry_cmd_process
 *           -> scf_cmdq_load(Q_CMD)       [LOADQ, arg1=12]
 *           -> scf_alarmq_deq(Q_CMD, out) [DEQ, arg1=12]
 *           -> scf_cmdq_clear(Q_CMD)      [CLEARQ, arg1=12]
 *           -> scf_msgq_write(Q_MSG, msg) [WRITEQ, arg1=13]
 *   api:    scf_cmdq_load   type=LOADQ  launch_via=INTERNAL   arg1=Q_CMD=12
 *   api:    scf_alarmq_deq  type=DEQ    launch_via=INTERNAL   arg1=Q_CMD=12
 *   api:    scf_cmdq_clear  type=CLEARQ launch_via=INTERNAL   arg1=Q_CMD=12
 *   api:    scf_msgq_write  type=WRITEQ launch_via=INTERNAL   arg1=Q_MSG=13
 *
 * ============================================================ */

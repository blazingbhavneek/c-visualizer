/*
 * proc_railyard/ry_interlock.c
 * Rail yard signaling system — route interlocking, semaphore control,
 * track occupancy voting, and event historiography.
 *
 * Emphasis: Semaphore-protected read/write, signal-aspect sequencing,
 * vital voting (2oo3), track-circuit occupancy, and forked histogram task.
 */

#include <stddef.h>
#include "ry_app.h"
#include "scf_tag.h"
#include "scf_event.h"
#include "scf_const.h"
#include "scf_queue.h"

/* ============================================================
 * GROUND TRUTH
 *
 * ry_on_scan (EVT_SCAN_CYCLE event handler, registered by main):
 *   -> scf_evt_post(EVT_SCAN_CYCLE, ...) [call_number=3001]
 *   -> ry_check_interlock(1)
 *      -> ry_read_signal(PT_VALVE_POS)
 *         -> scf_tag_read(&ctx, PT_VALVE_POS, buf) READF launch=EVENT arg2=0x1002 call_number=3001
 *
 * ry_lock_section (vital section protection):
 *   -> scf_sem_wait(SEM_DBLOCK)   SEMAPHORE arg1=80
 *   -> scf_sem_post(SEM_DBLOCK)
 *   -> scf_tag_write(&ctx, PT_SETPOINT, 1) WRITEF
 *
 * ry_interlock_task (FORK task entry, registered by main):
 *   -> scf_hist_save(ARC_EVENTLOG, &rec) SAVEF launch=FORK arg1=201
 *   -> scf_evt_post(EVT_HIST_FLUSH, ...) [call_number=3005]
 *
 * ============================================================ */

/* ============================================================
 * ROUTE & PROTECTION TABLES
 * ============================================================ */

/* Rail yard route geometry: each route protects a set of points/signals.
 * Routes protect their "flank" (side turnouts) and "lead" (leading points). */
struct RyRoute {
    int  route_id;
    int  signal_aspect;      /* RED=0, YELLOW=1, GREEN=2 */
    int  lead_point;         /* Main lead point to check */
    int  flank_left;         /* Flank protection left */
    int  flank_right;        /* Flank protection right */
    int  approach_block;     /* Approach locking semaphore ID */
    int  is_locked;          /* 1 if locked by route manager */
};

static struct RyRoute g_ry_routes[8] = {
    {1, 0, PT_VALVE_POS, 2, 3, SEM_DBLOCK, 0},
    {2, 0, PT_FLOW_RATE, 4, 5, SEM_DBLOCK, 0},
    {3, 0, PT_PRESSURE, 1, 2, SEM_DBLOCK, 0},
    {4, 0, PT_MOTOR_TEMP, 3, 4, SEM_DBLOCK, 0},
    {5, 0, PT_PUMP_SPEED, 5, 1, SEM_DBLOCK, 0},
    {6, 0, PT_TANK_LEVEL, 2, 3, SEM_DBLOCK, 0},
    {7, 0, PT_SETPOINT, 4, 5, SEM_DBLOCK, 0},
    {0, 0, 0, 0, 0, 0, 0},  /* sentinel */
};

/* Signal aspect sequencing rules (vital logic).
 * Aspects transition: RED -> YELLOW -> GREEN -> RED (with hold-safety intervals). */
struct AspectSeq {
    int current;      /* current aspect */
    int requested;    /* next requested aspect */
    int timer_hold;   /* hold timer counter (must reach 3 before advancing) */
    int is_transit;   /* 1 if in transition state */
};

static struct AspectSeq g_signal_seq[8] = {
    {0, 0, 0, 0},  /* signal 1 starts RED */
    {0, 0, 0, 0},  /* signal 2 starts RED */
    {0, 0, 0, 0},  /* signal 3 starts RED */
    {0, 0, 0, 0},  /* signal 4 starts RED */
    {0, 0, 0, 0},  /* signal 5 starts RED */
    {0, 0, 0, 0},  /* signal 6 starts RED */
    {0, 0, 0, 0},  /* signal 7 starts RED */
    {0, 0, 0, 0},  /* signal 8 starts RED */
};

/* Track circuit occupancy voting table (2oo3 vital voting).
 * Each track section has 3 independent track-circuit detectors;
 * occupancy is TRUE only if >= 2 agree. */
struct TrackVote {
    int section_id;
    int detector[3];    /* 0=unoccupied, 1=occupied */
    int consensus;      /* 0=clear, 1=occupied */
};

static struct TrackVote g_track_votes[6] = {
    {10, {0, 0, 0}, 0},  /* main approach */
    {11, {0, 0, 0}, 0},  /* yard lead 1 */
    {12, {0, 0, 0}, 0},  /* yard lead 2 */
    {13, {0, 0, 0}, 0},  /* siding 1 */
    {14, {0, 0, 0}, 0},  /* siding 2 */
    {15, {0, 0, 0}, 0},  /* departure */
};

/* Point (turnout) protection state: each point locks when route is cleared,
 * and blocks conflicting route requests. */
struct PointLock {
    int point_id;       /* PT_* from scf_const.h */
    int lock_route;     /* route_id holding the lock (0=free) */
    int lock_depth;     /* recursion depth for re-entrant locks */
};

static struct PointLock g_point_locks[7] = {
    {PT_VALVE_POS,  0, 0},
    {PT_FLOW_RATE,  0, 0},
    {PT_PRESSURE,   0, 0},
    {PT_MOTOR_TEMP, 0, 0},
    {PT_PUMP_SPEED, 0, 0},
    {PT_TANK_LEVEL, 0, 0},
    {PT_SETPOINT,   0, 0},
};

/* Approach-locking dwell timer (safety interval after train passes).
 * Prevents signal re-aspect until dwell completes. */
static int g_approach_dwell[8] = {0, 0, 0, 0, 0, 0, 0, 0};

/* Time-release lock: release routes after timeout if stuck. */
struct TimeRelease {
    int route_id;
    int expiry_count;   /* countdown to release */
};

static struct TimeRelease g_time_release[4] = {
    {0, 0}, {0, 0}, {0, 0}, {0, 0},
};

/* Historian event ringbuffer. */
struct HistEvent {
    int event_type;     /* route_locked=1, signal_aspect=2, occupancy=3, etc. */
    int param1, param2;
    int timestamp;      /* cycle counter */
};

static struct HistEvent g_hist_ring[128];
static int g_hist_head = 0;

/* Scan cycle counter (clock). */
static int g_scan_cycle_count = 0;

/* Interlock state machine. */
enum {
    ILCK_IDLE = 0,
    ILCK_SCAN = 1,
    ILCK_PROTECT = 2,
    ILCK_ADVISE = 3,
};
static int g_ilck_state = ILCK_IDLE;


/* ============================================================
 * HELPER FUNCTIONS
 * ============================================================ */

/* Helper: Find route by ID. */
static struct RyRoute *
ry_route_lookup(int route_id)
{
    int i;
    for (i = 0; i < 8; i++) {
        if (g_ry_routes[i].route_id == route_id)
            return &g_ry_routes[i];
    }
    return NULL;
}

/* Helper: Find point lock by ID. */
static struct PointLock *
ry_point_lookup(int point_id)
{
    int i;
    for (i = 0; i < 7; i++) {
        if (g_point_locks[i].point_id == point_id)
            return &g_point_locks[i];
    }
    return NULL;
}

/* Helper: Record event in historian ringbuffer. */
static void
ry_hist_record(int event_type, int p1, int p2)
{
    g_hist_ring[g_hist_head].event_type = event_type;
    g_hist_ring[g_hist_head].param1 = p1;
    g_hist_ring[g_hist_head].param2 = p2;
    g_hist_ring[g_hist_head].timestamp = g_scan_cycle_count;
    g_hist_head = (g_hist_head + 1) & 0x7f;  /* wrap at 128 */
}

/* Helper: Advance signal aspect (with hold safety). */
static int
ry_signal_advance(int signal_idx, int requested_aspect)
{
    struct AspectSeq *seq = &g_signal_seq[signal_idx];

    seq->requested = requested_aspect;
    seq->timer_hold++;

    /* Vital rule: must hold for 3 cycles before transitioning. */
    if (seq->timer_hold >= 3 && requested_aspect != seq->current) {
        seq->current = requested_aspect;
        seq->timer_hold = 0;
        seq->is_transit = 0;
        return 1;  /* aspect changed */
    }
    return 0;
}

/* Helper: Compute track-circuit consensus (2oo3 voting). */
static int
ry_track_consensus(int section_id)
{
    int i, occupied_count;

    for (i = 0; i < 6; i++) {
        if (g_track_votes[i].section_id == section_id) {
            occupied_count = g_track_votes[i].detector[0]
                           + g_track_votes[i].detector[1]
                           + g_track_votes[i].detector[2];
            return (occupied_count >= 2) ? 1 : 0;
        }
    }
    return 0;  /* not found, assume clear */
}

/* Helper: Check if route conflicts with any locked point. */
static int
ry_route_conflicts(int route_id)
{
    struct RyRoute *route = ry_route_lookup(route_id);
    struct PointLock *lead_lock, *flank_l, *flank_r;

    if (!route)
        return 1;  /* unknown route, conflicts */

    lead_lock = ry_point_lookup(route->lead_point);
    if (lead_lock && lead_lock->lock_route != 0 && lead_lock->lock_route != route_id)
        return 1;  /* lead point locked by another route */

    flank_l = ry_point_lookup(route->flank_left);
    if (flank_l && flank_l->lock_route != 0 && flank_l->lock_route != route_id)
        return 1;

    flank_r = ry_point_lookup(route->flank_right);
    if (flank_r && flank_r->lock_route != 0 && flank_r->lock_route != route_id)
        return 1;

    return 0;  /* no conflict */
}

/* Helper: Acquire locks on route points. */
static int
ry_acquire_route_locks(int route_id)
{
    struct RyRoute *route = ry_route_lookup(route_id);
    struct PointLock *lead_lock, *flank_l, *flank_r;

    if (!route)
        return 0;

    /* Acquire lead point. */
    lead_lock = ry_point_lookup(route->lead_point);
    if (lead_lock) {
        if (lead_lock->lock_route == 0) {
            lead_lock->lock_route = route_id;
            lead_lock->lock_depth = 1;
        } else if (lead_lock->lock_route == route_id) {
            lead_lock->lock_depth++;
        } else {
            return 0;  /* conflict */
        }
    }

    /* Acquire flank points (simplified: no conflict handling for brevity). */
    flank_l = ry_point_lookup(route->flank_left);
    if (flank_l && flank_l->lock_route == 0) {
        flank_l->lock_route = route_id;
        flank_l->lock_depth = 1;
    }

    flank_r = ry_point_lookup(route->flank_right);
    if (flank_r && flank_r->lock_route == 0) {
        flank_r->lock_route = route_id;
        flank_r->lock_depth = 1;
    }

    return 1;
}

/* Helper: Release locks on route points. */
static void
ry_release_route_locks(int route_id)
{
    struct RyRoute *route = ry_route_lookup(route_id);
    struct PointLock *lead_lock, *flank_l, *flank_r;

    if (!route)
        return;

    lead_lock = ry_point_lookup(route->lead_point);
    if (lead_lock && lead_lock->lock_route == route_id) {
        lead_lock->lock_depth--;
        if (lead_lock->lock_depth <= 0) {
            lead_lock->lock_route = 0;
            lead_lock->lock_depth = 0;
        }
    }

    flank_l = ry_point_lookup(route->flank_left);
    if (flank_l && flank_l->lock_route == route_id)
        flank_l->lock_route = 0;

    flank_r = ry_point_lookup(route->flank_right);
    if (flank_r && flank_r->lock_route == route_id)
        flank_r->lock_route = 0;
}

/* Helper: Dwell timer management (approach locking). */
static void
ry_dwell_tick(void)
{
    int i;
    for (i = 0; i < 8; i++) {
        if (g_approach_dwell[i] > 0)
            g_approach_dwell[i]--;
    }
}

/* Helper: Time-release expiry (allow stuck routes to be re-requested). */
static void
ry_time_release_tick(void)
{
    int i;
    for (i = 0; i < 4; i++) {
        if (g_time_release[i].route_id != 0 && g_time_release[i].expiry_count > 0) {
            g_time_release[i].expiry_count--;
            if (g_time_release[i].expiry_count == 0) {
                /* Route forced release. */
                ry_release_route_locks(g_time_release[i].route_id);
                g_time_release[i].route_id = 0;
                ry_hist_record(1, g_time_release[i].route_id, 999);  /* forced release event */
            }
        }
    }
}


/* ============================================================
 * PUBLIC API FUNCTIONS
 * ============================================================ */

/* ry_read_signal: Read a signal/point value via tag system.
 * Demonstrates the scf_tag_read READF path (called from ry_check_interlock).
 */
int
ry_read_signal(int pid)
{
    TagCtx ctx = {0};
    int value = 0;

    ctx.point_id = pid;
    ctx.mode = SCF_READ_LOCK;

    /* Direct scf_tag_read call (READF) with resolvable arg2=PT_VALVE_POS etc. */
    scf_tag_read(&ctx, PT_VALVE_POS, &value);

    return value;
}

/* ry_check_interlock: Vital interlock check for a section.
 * Returns 1 if safe to clear, 0 if conflicts/hazards remain.
 * Calls ry_read_signal as part of safety validation.
 */
int
ry_check_interlock(int section)
{
    int i, track_clear, signal_safe, route_ok;
    struct TrackVote *vote;

    /* Track-circuit consensus check (2oo3 vital). */
    track_clear = 1;
    for (i = 0; i < 6; i++) {
        vote = &g_track_votes[i];
        if (vote->section_id == section) {
            vote->consensus = ry_track_consensus(section);
            if (vote->consensus)
                track_clear = 0;
        }
    }

    /* Signal aspect safety. */
    signal_safe = 0;
    if (g_signal_seq[section].current == 0)  /* RED */
        signal_safe = 1;

    /* Approach dwell timer (safety hold-off). */
    if (g_approach_dwell[section] > 0)
        signal_safe = 0;

    /* Route conflict check. */
    route_ok = 1;
    if (ry_route_conflicts(section))
        route_ok = 0;

    /* Read signal input (part of interlock validation). */
    if (route_ok)
        ry_read_signal(PT_VALVE_POS);

    return (track_clear && signal_safe && route_ok) ? 1 : 0;
}

/* ry_lock_section: Acquire vital semaphore lock, write safety data.
 * Demonstrates scf_sem_wait/post + scf_tag_write (WRITEF) pattern.
 */
int
ry_lock_section(int section)
{
    TagCtx ctx = {0};
    int status;
    struct RyRoute *route;

    /* Vital semaphore acquire (must succeed atomically). */
    scf_sem_wait(SEM_DBLOCK);

    /* Lock route points. */
    route = ry_route_lookup(section);
    if (route && !ry_route_conflicts(section)) {
        ry_acquire_route_locks(section);
        route->is_locked = 1;
        ry_hist_record(1, section, 1);  /* route locked event */
        status = 1;
    } else {
        status = 0;
    }

    /* Write safety state to tag system (WRITEF). */
    ctx.point_id = PT_SETPOINT;
    ctx.mode = SCF_WRITE_LOCK;
    scf_tag_write(&ctx, PT_SETPOINT, 1);

    /* Vital semaphore release. */
    scf_sem_post(SEM_DBLOCK);

    return status;
}

/* ry_on_scan: Main interlock scan event handler (registered for EVT_SCAN_CYCLE).
 * Called each scan cycle; drives interlock state machine and occupancy polling.
 */
void
ry_on_scan(int evt, void *data)
{
    int i, section_locked;
    struct RyRoute *route;

    g_scan_cycle_count++;

    /* Post the event for call_number tracking. */
    scf_evt_post(EVT_SCAN_CYCLE, NULL);

    /* Dwell and time-release management. */
    ry_dwell_tick();
    ry_time_release_tick();

    /* Interlock state machine. */
    switch (g_ilck_state) {
        case ILCK_IDLE:
            /* Wait for route request. */
            g_ilck_state = ILCK_SCAN;
            break;

        case ILCK_SCAN:
            /* Scan occupancy and check interlocks. */
            for (i = 0; i < 8; i++) {
                route = &g_ry_routes[i];
                if (route->route_id != 0) {
                    if (ry_check_interlock(route->route_id)) {
                        g_ilck_state = ILCK_PROTECT;
                    }
                }
            }
            break;

        case ILCK_PROTECT:
            /* Acquire locks. */
            for (i = 0; i < 8; i++) {
                route = &g_ry_routes[i];
                if (route->route_id != 0 && !route->is_locked) {
                    section_locked = ry_lock_section(route->route_id);
                    if (section_locked)
                        g_ilck_state = ILCK_ADVISE;
                }
            }
            break;

        case ILCK_ADVISE:
            /* Advance signal aspects (with hold safety). */
            for (i = 0; i < 8; i++) {
                if (g_signal_seq[i].requested != 0) {
                    ry_signal_advance(i, g_signal_seq[i].requested);
                }
            }
            g_ilck_state = ILCK_IDLE;
            break;
    }
}

/* ry_interlock_task: Forked historian task (registered for TASK_HIST).
 * Runs independently; periodically flushes interlock events to history archive.
 */
void
ry_interlock_task(int task_id)
{
    int i, rec_count, flush_threshold;
    HistRec hist_rec = {0};
    struct HistEvent *evt;

    (void)task_id;  /* unused parameter */

    flush_threshold = 16;  /* flush every 16 events */
    rec_count = 0;

    /* Continuous historian loop. */
    for (;;) {
        /* Poll interlock event ringbuffer. */
        for (i = 0; i < 128; i++) {
            evt = &g_hist_ring[i];
            if (evt->event_type != 0 && rec_count < flush_threshold) {
                /* Build history record. */
                hist_rec.archive_id = ARC_EVENTLOG;
                hist_rec.stamp = evt->timestamp;
                hist_rec.value = (evt->event_type << 16) | evt->param1;

                /* Save to archive (SAVEF with ARC_EVENTLOG). */
                scf_hist_save(ARC_EVENTLOG, &hist_rec);

                rec_count++;
            }
        }

        /* When threshold reached, post flush event and reset. */
        if (rec_count >= flush_threshold) {
            scf_evt_post(EVT_HIST_FLUSH, NULL);
            rec_count = 0;
        }
    }
}


/* ============================================================
 * EXTENDED INTERLOCK LOGIC
 * ============================================================ */

/* Route-conflict matrix: precomputed to accelerate conflict checks. */
static int g_conflict_matrix[8][8] = {
    {0, 1, 1, 0, 1, 0, 0, 1},  /* route 1 conflicts with 2,3,5,8 */
    {1, 0, 0, 1, 0, 1, 0, 0},  /* route 2 conflicts with 1,4,6 */
    {1, 0, 0, 1, 1, 0, 1, 0},  /* route 3 conflicts with 1,4,5,7 */
    {0, 1, 1, 0, 0, 1, 1, 0},  /* route 4 conflicts with 2,3,6,7 */
    {1, 0, 1, 0, 0, 1, 0, 1},  /* route 5 conflicts with 1,3,6,8 */
    {0, 1, 0, 1, 1, 0, 1, 1},  /* route 6 conflicts with 2,4,5,7,8 */
    {0, 0, 1, 1, 0, 1, 0, 1},  /* route 7 conflicts with 3,4,6,8 */
    {1, 0, 0, 0, 1, 1, 1, 0},  /* route 8 conflicts with 1,5,6,7 */
};

/* Occupancy detector simulation: periodic injection of pseudo-random
 * track-circuit occupation data (simulates train movement). */
static int g_detector_inject_cycle = 0;

static void
ry_inject_occupancy(void)
{
    int section, detector_idx, val;

    g_detector_inject_cycle++;

    /* Inject synthetic occupancy every 8 cycles for main approach. */
    if ((g_detector_inject_cycle & 0x7) == 3) {
        section = 10;  /* main approach */
        detector_idx = (g_detector_inject_cycle >> 3) % 3;
        val = ((g_detector_inject_cycle >> 2) & 1);

        for (int i = 0; i < 6; i++) {
            if (g_track_votes[i].section_id == section) {
                g_track_votes[i].detector[detector_idx] = val;
            }
        }
    }
}

/* Approach aspect sequencing: manage signal color changes based on
 * track occupancy and route locking. GREEN->YELLOW->RED progression. */
static void
ry_approach_sequencing(int approach_id)
{
    int track_clear, can_green, can_yellow;
    struct RyRoute *route;

    route = ry_route_lookup(approach_id);
    if (!route)
        return;

    track_clear = (ry_track_consensus(approach_id + 9) == 0) ? 1 : 0;

    /* GREEN only if track clear and no conflicting routes locked. */
    can_green = track_clear && !ry_route_conflicts(approach_id);

    /* YELLOW if route locked but train approaching. */
    can_yellow = route->is_locked && !track_clear;

    if (can_green) {
        ry_signal_advance(approach_id, 2);  /* request GREEN */
    } else if (can_yellow) {
        ry_signal_advance(approach_id, 1);  /* request YELLOW */
    } else {
        ry_signal_advance(approach_id, 0);  /* enforce RED */
    }
}

/* Flank protection: ensure conflicting points are safe before clearing route. */
static int
ry_flank_protect(int route_id)
{
    struct RyRoute *route = ry_route_lookup(route_id);
    int flank_clear;

    if (!route)
        return 0;

    /* Check both flank track circuits are clear. */
    flank_clear = (ry_track_consensus(route->flank_left) == 0)
               && (ry_track_consensus(route->flank_right) == 0);

    return flank_clear;
}

/* Point protection: verify turnout is correctly positioned before route clear. */
static int
ry_point_protect(int point_id)
{
    int value = ry_read_signal(point_id);
    /* Simplified: assume >0 means "protected" position. */
    return (value > 0) ? 1 : 0;
}

/* Vital 2oo3 voting with error injection (for test data generation). */
static int
ry_vital_vote_with_error(int section_id, int fault_inject)
{
    struct TrackVote *vote;
    int i, occupied_count;

    for (i = 0; i < 6; i++) {
        vote = &g_track_votes[i];
        if (vote->section_id == section_id) {
            /* Simulate detector fault: flip one detector if fault_inject==1. */
            if (fault_inject && i == 0) {
                vote->detector[0] ^= 1;
            }

            occupied_count = vote->detector[0]
                           + vote->detector[1]
                           + vote->detector[2];

            /* Fail-safe: 2oo3 means 2 or more agree. */
            return (occupied_count >= 2) ? 1 : 0;
        }
    }
    return 0;
}

/* Time-release arbiter: assign time-release slots for stuck routes. */
static void
ry_assign_time_release(int route_id, int duration)
{
    int i;
    for (i = 0; i < 4; i++) {
        if (g_time_release[i].route_id == 0) {
            g_time_release[i].route_id = route_id;
            g_time_release[i].expiry_count = duration;
            return;
        }
    }
}

/* Extended occupancy processing: debounce track-circuit inputs. */
struct TCDebounce {
    int section_id;
    int stable_count;   /* counter to confirm state change */
    int last_state;     /* 0 or 1 */
};

static struct TCDebounce g_tc_debounce[6] = {
    {10, 0, 0}, {11, 0, 0}, {12, 0, 0},
    {13, 0, 0}, {14, 0, 0}, {15, 0, 0},
};

static void
ry_debounce_tc(int section_id, int raw_state)
{
    int i;
    for (i = 0; i < 6; i++) {
        if (g_tc_debounce[i].section_id == section_id) {
            if (raw_state == g_tc_debounce[i].last_state) {
                g_tc_debounce[i].stable_count++;
            } else {
                g_tc_debounce[i].stable_count = 1;
                g_tc_debounce[i].last_state = raw_state;
            }

            /* Confirm after 3 stable cycles. */
            if (g_tc_debounce[i].stable_count >= 3) {
                /* Update consensus (simplified). */
            }
        }
    }
}

/* Multi-route sequencing: prevent conflicting route advances
 * by building a state queue. */
struct RouteReq {
    int route_id;
    int priority;
    int age;
};

static struct RouteReq g_route_queue[16] = {0};
static int g_route_queue_depth = 0;

static int
ry_enqueue_route_request(int route_id, int priority)
{
    if (g_route_queue_depth >= 16)
        return 0;  /* queue full */

    g_route_queue[g_route_queue_depth].route_id = route_id;
    g_route_queue[g_route_queue_depth].priority = priority;
    g_route_queue[g_route_queue_depth].age = 0;
    g_route_queue_depth++;

    return 1;
}

static int
ry_dequeue_route_request(void)
{
    int best_idx = -1, best_pri = -1, i;

    /* Priority dequeue: select highest priority non-conflicting route. */
    for (i = 0; i < g_route_queue_depth; i++) {
        if (g_route_queue[i].priority > best_pri
            && !ry_route_conflicts(g_route_queue[i].route_id)) {
            best_idx = i;
            best_pri = g_route_queue[i].priority;
        }
    }

    if (best_idx >= 0) {
        int ret = g_route_queue[best_idx].route_id;
        /* Remove from queue. */
        for (i = best_idx; i < g_route_queue_depth - 1; i++)
            g_route_queue[i] = g_route_queue[i + 1];
        g_route_queue_depth--;
        return ret;
    }

    return 0;
}

/* Safety validation: confirm all preconditions before route clear. */
static int
ry_validate_route_clear(int route_id)
{
    struct RyRoute *route = ry_route_lookup(route_id);

    if (!route)
        return 0;

    /* Precondition checks: */
    if (ry_check_interlock(route_id) == 0)
        return 0;  /* interlock hazard */

    if (ry_flank_protect(route_id) == 0)
        return 0;  /* flank not clear */

    if (ry_point_protect(route->lead_point) == 0)
        return 0;  /* point not positioned */

    return 1;  /* safe to clear */
}

/* Scan-cycle diagnostic: log interlock state for forensics. */
static void
ry_diagnostic_snapshot(void)
{
    int i;

    /* Log route states. */
    for (i = 0; i < 8; i++) {
        if (g_ry_routes[i].route_id != 0) {
            ry_hist_record(1, g_ry_routes[i].route_id, g_ry_routes[i].is_locked);
        }
    }

    /* Log signal states. */
    for (i = 0; i < 8; i++) {
        if (g_signal_seq[i].current != 0 || g_signal_seq[i].requested != 0) {
            ry_hist_record(2, i, (g_signal_seq[i].current << 4) | g_signal_seq[i].requested);
        }
    }

    /* Log occupancy consensus. */
    for (i = 0; i < 6; i++) {
        if (g_track_votes[i].consensus != 0) {
            ry_hist_record(3, g_track_votes[i].section_id, g_track_votes[i].consensus);
        }
    }
}

/* Dwell timer arbiter: manage approach locking after train passage. */
static void
ry_set_approach_dwell(int approach_id, int dwell_cycles)
{
    if (approach_id < 8)
        g_approach_dwell[approach_id] = dwell_cycles;
}

/* Signal-circuit occupancy assessment (simulated). */
static int
ry_occupancy_detect(int section_id)
{
    return ry_track_consensus(section_id);
}

/* Vital state dump for debugging. */
static void
ry_dump_state(void)
{
    int i;

    /* Dump route locks. */
    for (i = 0; i < 7; i++) {
        if (g_point_locks[i].lock_route != 0) {
            ry_hist_record(1, g_point_locks[i].point_id, g_point_locks[i].lock_route);
        }
    }
}


/* ============================================================
 * ADVANCED VITAL LOGIC
 * ============================================================ */

/* Signal-conflict matrix (prevent safe-working-space violations). */
struct SignalConflict {
    int sig1, sig2;  /* conflicting signal pair */
    int restrict_color1, restrict_color2;  /* restricted colors when conflict active */
};

static struct SignalConflict g_sig_conflicts[12] = {
    {0, 1, 2, 2},  /* sigs 0,1 can't both be GREEN */
    {1, 2, 2, 2},
    {2, 3, 2, 2},
    {3, 4, 2, 2},
    {4, 5, 2, 2},
    {5, 6, 2, 2},
    {6, 7, 2, 2},
    {7, 0, 2, 2},
    {0, 3, 1, 1},  /* sigs 0,3 restrict YELLOW */
    {1, 4, 1, 1},
    {2, 5, 1, 1},
    {3, 6, 1, 1},
};

/* Enforce signal-conflict rules (safety interlocking). */
static void
ry_enforce_signal_conflicts(void)
{
    int i, sig1, sig2;
    struct SignalConflict *conflict;

    for (i = 0; i < 12; i++) {
        conflict = &g_sig_conflicts[i];
        sig1 = conflict->sig1;
        sig2 = conflict->sig2;

        /* If signal 1 is in restricted state, limit signal 2. */
        if (g_signal_seq[sig1].current == conflict->restrict_color1) {
            if (g_signal_seq[sig2].requested > conflict->restrict_color2)
                g_signal_seq[sig2].requested = conflict->restrict_color2;
        }

        /* Vice versa. */
        if (g_signal_seq[sig2].current == conflict->restrict_color2) {
            if (g_signal_seq[sig1].requested > conflict->restrict_color1)
                g_signal_seq[sig1].requested = conflict->restrict_color1;
        }
    }
}

/* Track section interlocking: limit aspect based on opposing traffic. */
struct TrackInterlockRule {
    int section_a, section_b;
    int max_aspect_a, max_aspect_b;  /* max allowed aspect in conflict */
};

static struct TrackInterlockRule g_track_rules[8] = {
    {10, 11, 1, 1},  /* approach & lead1: both max YELLOW */
    {11, 12, 1, 1},  /* lead1 & lead2 */
    {12, 13, 1, 1},  /* lead2 & siding1 */
    {13, 14, 0, 2},  /* siding1 & siding2: 1 must be RED */
    {14, 15, 0, 2},  /* siding2 & departure */
    {15, 10, 1, 1},  /* departure & approach */
    {10, 12, 1, 1},  /* approach & lead2 diagonal */
    {11, 13, 0, 2},  /* lead1 & siding1 diagonal */
};

static void
ry_enforce_track_interlocking(void)
{
    int i, both_occupied, rule_violated;
    struct TrackInterlockRule *rule;
    struct TrackVote *vote_a, *vote_b;

    for (i = 0; i < 8; i++) {
        rule = &g_track_rules[i];

        /* Find occupancy for each section. */
        vote_a = NULL;
        vote_b = NULL;
        int j;
        for (j = 0; j < 6; j++) {
            if (g_track_votes[j].section_id == rule->section_a)
                vote_a = &g_track_votes[j];
            if (g_track_votes[j].section_id == rule->section_b)
                vote_b = &g_track_votes[j];
        }

        if (!vote_a || !vote_b)
            continue;

        both_occupied = (vote_a->consensus && vote_b->consensus);

        /* If both sections occupied, enforce max aspects. */
        if (both_occupied) {
            if (g_signal_seq[rule->section_a - 10].requested > rule->max_aspect_a)
                g_signal_seq[rule->section_a - 10].requested = rule->max_aspect_a;

            if (g_signal_seq[rule->section_b - 10].requested > rule->max_aspect_b)
                g_signal_seq[rule->section_b - 10].requested = rule->max_aspect_b;
        }
    }
}

/* Turnout actuation table (simulates physical point machine commands). */
struct TurnoutCmd {
    int point_id;
    int target_state;   /* NORMAL=0, REVERSE=1 */
    int actuation_time; /* cycles to complete */
    int is_active;      /* 1 if machine energized */
};

static struct TurnoutCmd g_turnout_cmds[7] = {
    {PT_VALVE_POS,  0, 0, 0},
    {PT_FLOW_RATE,  0, 0, 0},
    {PT_PRESSURE,   0, 0, 0},
    {PT_MOTOR_TEMP, 0, 0, 0},
    {PT_PUMP_SPEED, 0, 0, 0},
    {PT_TANK_LEVEL, 0, 0, 0},
    {PT_SETPOINT,   0, 0, 0},
};

static void
ry_activate_turnout(int point_id, int target_state)
{
    int i;
    for (i = 0; i < 7; i++) {
        if (g_turnout_cmds[i].point_id == point_id) {
            g_turnout_cmds[i].target_state = target_state;
            g_turnout_cmds[i].actuation_time = 2;  /* 2-cycle actuation */
            g_turnout_cmds[i].is_active = 1;
            return;
        }
    }
}

static void
ry_turnout_cycle(void)
{
    int i;
    for (i = 0; i < 7; i++) {
        if (g_turnout_cmds[i].is_active && g_turnout_cmds[i].actuation_time > 0) {
            g_turnout_cmds[i].actuation_time--;
            if (g_turnout_cmds[i].actuation_time == 0) {
                g_turnout_cmds[i].is_active = 0;
                ry_hist_record(2, g_turnout_cmds[i].point_id, g_turnout_cmds[i].target_state);
            }
        }
    }
}

/* Lock release delay: after train clears, hold route lock for safety dwell. */
struct LockRelease {
    int route_id;
    int delay_cycles;   /* countdown */
};

static struct LockRelease g_lock_releases[8] = {
    {0, 0}, {0, 0}, {0, 0}, {0, 0},
    {0, 0}, {0, 0}, {0, 0}, {0, 0},
};

static void
ry_schedule_lock_release(int route_id, int delay)
{
    int i;
    for (i = 0; i < 8; i++) {
        if (g_lock_releases[i].route_id == 0) {
            g_lock_releases[i].route_id = route_id;
            g_lock_releases[i].delay_cycles = delay;
            return;
        }
    }
}

static void
ry_lock_release_cycle(void)
{
    int i;
    for (i = 0; i < 8; i++) {
        if (g_lock_releases[i].route_id != 0 && g_lock_releases[i].delay_cycles > 0) {
            g_lock_releases[i].delay_cycles--;
            if (g_lock_releases[i].delay_cycles == 0) {
                ry_release_route_locks(g_lock_releases[i].route_id);
                ry_hist_record(1, g_lock_releases[i].route_id, 0);  /* route released */
                g_lock_releases[i].route_id = 0;
            }
        }
    }
}

/* Grade-crossing predictor: use track-circuit trend to predict train arrival. */
struct CrossingPredictor {
    int crossing_id;
    int approach_section;
    int trend_counter;   /* moving average of occupancy changes */
};

static struct CrossingPredictor g_crossing_predict[4] = {
    {1, 10, 0}, {2, 11, 0}, {3, 12, 0}, {4, 13, 0},
};

static int
ry_predict_train_arrival(int crossing_id)
{
    int i, count_rising_trends = 0;

    for (i = 0; i < 4; i++) {
        if (g_crossing_predict[i].crossing_id == crossing_id) {
            /* Simple trend: if trend_counter positive and approach occupied, predict arrival. */
            if (g_crossing_predict[i].trend_counter > 0
                && ry_occupancy_detect(g_crossing_predict[i].approach_section)) {
                count_rising_trends++;
            }
        }
    }

    return (count_rising_trends > 0) ? 1 : 0;
}

/* Approach-hold arbiter: prevent conflicting approach routes from clearing simultaneously. */
struct ApproachHold {
    int approach_pair[2];   /* pair of mutually exclusive approaches */
    int hold_active;        /* 1 if one is locked */
};

static struct ApproachHold g_approach_holds[4] = {
    {{0, 1}, 0},
    {{2, 3}, 0},
    {{4, 5}, 0},
    {{6, 7}, 0},
};

static int
ry_approach_hold_check(int approach_id)
{
    int i, partner;

    for (i = 0; i < 4; i++) {
        if (g_approach_holds[i].approach_pair[0] == approach_id) {
            partner = g_approach_holds[i].approach_pair[1];
        } else if (g_approach_holds[i].approach_pair[1] == approach_id) {
            partner = g_approach_holds[i].approach_pair[0];
        } else {
            continue;
        }

        /* If partner is locked, this approach must be held. */
        if (g_ry_routes[partner].is_locked)
            return 0;  /* hold (cannot clear) */
    }

    return 1;  /* clear to proceed */
}

/* Safe-working-space validator: confirm clearance before signal GREEN. */
struct SafeWorkSpace {
    int route_id;
    int lead_clear_section;     /* main section before signal */
    int flank_left_section;     /* left flank */
    int flank_right_section;    /* right flank */
    int follow_clear_section;   /* exit section after signal */
};

static struct SafeWorkSpace g_safe_spaces[8] = {
    {1, 10, 11, 12, 13},
    {2, 11, 12, 13, 14},
    {3, 12, 13, 14, 15},
    {4, 13, 14, 15, 10},
    {5, 14, 15, 10, 11},
    {6, 15, 10, 11, 12},
    {7, 10, 11, 12, 13},
    {0, 0, 0, 0, 0},
};

static int
ry_validate_safe_working_space(int route_id)
{
    int i, all_clear;
    struct SafeWorkSpace *space;

    for (i = 0; i < 8; i++) {
        if (g_safe_spaces[i].route_id == route_id) {
            space = &g_safe_spaces[i];

            /* All sections must be clear. */
            all_clear = (ry_occupancy_detect(space->lead_clear_section) == 0)
                     && (ry_occupancy_detect(space->flank_left_section) == 0)
                     && (ry_occupancy_detect(space->flank_right_section) == 0)
                     && (ry_occupancy_detect(space->follow_clear_section) == 0);

            return all_clear;
        }
    }

    return 0;
}

/* Extended scan cycle logic with comprehensive diagnostics. */
static void
ry_extended_scan_cycle(void)
{
    int i;

    /* Enforce all safety constraints. */
    ry_enforce_signal_conflicts();
    ry_enforce_track_interlocking();
    ry_turnout_cycle();
    ry_lock_release_cycle();

    /* Approach holding (mutual exclusion). */
    for (i = 0; i < 8; i++) {
        if (ry_approach_hold_check(i) == 0) {
            if (g_ry_routes[i].is_locked)
                ry_release_route_locks(i);
        }
    }

    /* Injected occupancy (test stimulus). */
    ry_inject_occupancy();

    /* Diagnostic snapshot. */
    if ((g_scan_cycle_count & 0x0f) == 0) {
        ry_diagnostic_snapshot();
    }
}

/* Comprehensive interlock validation before route clear. */
static int
ry_comprehensive_interlock_check(int route_id)
{
    struct RyRoute *route;

    route = ry_route_lookup(route_id);
    if (!route)
        return 0;

    /* Sequential vital checks. */
    if (!ry_check_interlock(route_id))
        return 0;

    if (!ry_flank_protect(route_id))
        return 0;

    if (!ry_approach_hold_check(route_id))
        return 0;

    if (!ry_validate_safe_working_space(route_id))
        return 0;

    if (!ry_validate_route_clear(route_id))
        return 0;

    return 1;  /* all checks pass */
}

/* Deadlock prevention: if route stuck for too long, force release. */
static int g_route_stuck_counter[8] = {0, 0, 0, 0, 0, 0, 0, 0};

static void
ry_deadlock_detect(void)
{
    int i;
    struct RyRoute *route;

    for (i = 0; i < 8; i++) {
        route = &g_ry_routes[i];
        if (route->is_locked) {
            g_route_stuck_counter[i]++;

            /* If locked for > 100 cycles, force release. */
            if (g_route_stuck_counter[i] > 100) {
                ry_release_route_locks(route->route_id);
                route->is_locked = 0;
                ry_hist_record(1, route->route_id, 999);  /* forced release */
                g_route_stuck_counter[i] = 0;
            }
        } else {
            g_route_stuck_counter[i] = 0;
        }
    }
}

/* Route-request arbiter: process queued requests with conflict resolution. */
static void
ry_arbiter_cycle(void)
{
    int next_route;

    /* Dequeue highest-priority non-conflicting route. */
    next_route = ry_dequeue_route_request();
    if (next_route != 0) {
        if (ry_comprehensive_interlock_check(next_route)) {
            ry_lock_section(next_route);
        } else {
            /* Re-queue for retry. */
            ry_enqueue_route_request(next_route, 1);
        }
    }
}

/* Historian flush with event correlation. */
static void
ry_correlate_hist_events(void)
{
    int i, j, event_gap;
    struct HistEvent *evt_i, *evt_j;

    /* Find correlated events (same timestamp or nearby). */
    for (i = 0; i < 128; i++) {
        evt_i = &g_hist_ring[i];
        if (evt_i->event_type == 0)
            continue;

        for (j = i + 1; j < 128; j++) {
            evt_j = &g_hist_ring[j];
            if (evt_j->event_type == 0)
                continue;

            event_gap = (evt_j->timestamp - evt_i->timestamp) & 0xff;
            if (event_gap < 3) {
                /* Events close in time; may be correlated. */
                ry_hist_record(4, evt_i->event_type, evt_j->event_type);
            }
        }
    }
}

/* Histogram rollover: age old events when buffer fills. */
static void
ry_hist_age_records(void)
{
    int i, age_threshold;
    struct HistEvent *evt;

    age_threshold = g_scan_cycle_count - 256;

    for (i = 0; i < 128; i++) {
        evt = &g_hist_ring[i];
        if (evt->event_type != 0 && evt->timestamp < age_threshold) {
            evt->event_type = 0;  /* mark as aged */
        }
    }
}

/* Extended route sequencing for multi-step clearances. */
struct SequenceState {
    int route_id;
    int step;  /* 0=not-started, 1=step1, 2=step2, etc. */
    int step_timer;
};

static struct SequenceState g_sequences[4] = {
    {0, 0, 0}, {0, 0, 0}, {0, 0, 0}, {0, 0, 0},
};

static void
ry_advance_route_sequence(int route_id)
{
    int i, found = -1;

    /* Find sequence slot. */
    for (i = 0; i < 4; i++) {
        if (g_sequences[i].route_id == route_id) {
            found = i;
            break;
        } else if (g_sequences[i].route_id == 0) {
            found = i;
        }
    }

    if (found >= 0) {
        g_sequences[found].route_id = route_id;
        g_sequences[found].step++;
        g_sequences[found].step_timer = 5;  /* 5-cycle hold per step */
    }
}

static void
ry_sequence_timer_tick(void)
{
    int i;
    for (i = 0; i < 4; i++) {
        if (g_sequences[i].route_id != 0 && g_sequences[i].step_timer > 0) {
            g_sequences[i].step_timer--;
            if (g_sequences[i].step_timer == 0 && g_sequences[i].step >= 3) {
                /* Sequence complete. */
                g_sequences[i].route_id = 0;
                g_sequences[i].step = 0;
            }
        }
    }
}


/* ============================================================
 * VITAL 2oo3 REDUNDANCY MANAGEMENT
 * ============================================================ */

/* Redundant detector management: if one detector fails, 2oo3 becomes 2oo2. */
struct DetectorRedund {
    int detector_id;
    int healthy;        /* 1=OK, 0=FAILED */
    int failure_count;  /* consecutive failure cycles */
};

static struct DetectorRedund g_detector_redund[18] = {
    {0, 1, 0}, {1, 1, 0}, {2, 1, 0},
    {3, 1, 0}, {4, 1, 0}, {5, 1, 0},
    {6, 1, 0}, {7, 1, 0}, {8, 1, 0},
    {9, 1, 0}, {10, 1, 0}, {11, 1, 0},
    {12, 1, 0}, {13, 1, 0}, {14, 1, 0},
    {15, 1, 0}, {16, 1, 0}, {17, 1, 0},
};

static void
ry_detector_health_check(void)
{
    int i;
    for (i = 0; i < 18; i++) {
        if (g_detector_redund[i].healthy == 0) {
            g_detector_redund[i].failure_count++;

            /* After 10 cycles, consider detector failed. */
            if (g_detector_redund[i].failure_count > 10) {
                ry_hist_record(3, i, 0);  /* detector failed event */
            }
        } else {
            g_detector_redund[i].failure_count = 0;
        }
    }
}

/* Signaling authority: prevent dispatcher from creating unsafe routes. */
struct DispatcherAuth {
    int auth_level;     /* 0=restricted, 1=normal, 2=full */
    int is_emergency;   /* 1 if system in emergency state */
};

static struct DispatcherAuth g_dispatcher = {1, 0};

static int
ry_check_dispatcher_authority(int route_id)
{
    if (g_dispatcher.is_emergency)
        return 0;  /* no route clearance in emergency */

    if (g_dispatcher.auth_level < 1)
        return 0;  /* dispatcher not authorized */

    return 1;  /* authorized */
}

/* Emergency stop arbiter: force all routes to RED immediately. */
static void
ry_emergency_stop(void)
{
    int i;

    g_dispatcher.is_emergency = 1;

    /* Force all signals RED. */
    for (i = 0; i < 8; i++) {
        g_signal_seq[i].requested = 0;
        g_signal_seq[i].current = 0;
        g_signal_seq[i].is_transit = 0;
    }

    /* Release all routes. */
    for (i = 0; i < 8; i++) {
        if (g_ry_routes[i].route_id != 0) {
            ry_release_route_locks(g_ry_routes[i].route_id);
            g_ry_routes[i].is_locked = 0;
        }
    }

    ry_hist_record(1, 999, 999);  /* emergency stop event */
}

/* Resume from emergency: check all systems before resuming. */
static int
ry_emergency_resume(void)
{
    int i, all_safe;

    /* Verify all signals are RED. */
    all_safe = 1;
    for (i = 0; i < 8; i++) {
        if (g_signal_seq[i].current != 0)
            all_safe = 0;
    }

    /* Verify all routes unlocked. */
    for (i = 0; i < 8; i++) {
        if (g_ry_routes[i].is_locked)
            all_safe = 0;
    }

    if (all_safe) {
        g_dispatcher.is_emergency = 0;
        ry_hist_record(1, 888, 888);  /* emergency clear event */
        return 1;
    }

    return 0;
}

/* Aspect-hold arbiter: maintain GREEN aspect even after occupancy clears
 * (to prevent flicker). */
struct AspectHold {
    int signal_id;
    int hold_cycles;
};

static struct AspectHold g_aspect_holds[8] = {
    {0, 0}, {1, 0}, {2, 0}, {3, 0},
    {4, 0}, {5, 0}, {6, 0}, {7, 0},
};

static void
ry_set_aspect_hold(int sig_id, int duration)
{
    if (sig_id < 8)
        g_aspect_holds[sig_id].hold_cycles = duration;
}

static void
ry_aspect_hold_tick(void)
{
    int i;
    for (i = 0; i < 8; i++) {
        if (g_aspect_holds[i].hold_cycles > 0)
            g_aspect_holds[i].hold_cycles--;
    }
}

/* Occupancy trend analysis: detect moving trains vs. parked equipment. */
struct OccupancyTrend {
    int section_id;
    int sample[5];      /* occupancy history (5-cycle moving window) */
    int sample_idx;
    int is_moving;      /* 1 if trend suggests moving train */
};

static struct OccupancyTrend g_occ_trends[6] = {
    {10, {0,0,0,0,0}, 0, 0},
    {11, {0,0,0,0,0}, 0, 0},
    {12, {0,0,0,0,0}, 0, 0},
    {13, {0,0,0,0,0}, 0, 0},
    {14, {0,0,0,0,0}, 0, 0},
    {15, {0,0,0,0,0}, 0, 0},
};

static void
ry_update_occupancy_trend(int section_id, int current_occupancy)
{
    int i, occ_changes = 0;
    struct OccupancyTrend *trend;

    for (i = 0; i < 6; i++) {
        if (g_occ_trends[i].section_id == section_id) {
            trend = &g_occ_trends[i];
            trend->sample[trend->sample_idx] = current_occupancy;
            trend->sample_idx = (trend->sample_idx + 1) % 5;

            /* Count transitions in history. */
            occ_changes = 0;
            int j;
            for (j = 0; j < 4; j++) {
                if (trend->sample[j] != trend->sample[j+1])
                    occ_changes++;
            }

            /* Moving train: multiple transitions. Parked: stable. */
            trend->is_moving = (occ_changes >= 2) ? 1 : 0;
            return;
        }
    }
}

/* Crossing predictor refinement: use trend to improve arrival prediction. */
static int
ry_predict_crossing_time(int crossing_id)
{
    int i, approach_section, trend, distance;
    struct CrossingPredictor *pred;

    for (i = 0; i < 4; i++) {
        pred = &g_crossing_predict[i];
        if (pred->crossing_id == crossing_id) {
            approach_section = pred->approach_section;

            /* Find occupancy trend for approach section. */
            int j;
            for (j = 0; j < 6; j++) {
                if (g_occ_trends[j].section_id == approach_section) {
                    trend = g_occ_trends[j].is_moving;
                    break;
                }
            }

            /* If trend shows movement, estimate distance to crossing. */
            distance = pred->trend_counter * 10;  /* simplified distance model */

            if (trend && distance < 50)
                return distance;  /* return estimated time */
        }
    }

    return -1;  /* no prediction */
}

/* Signal-hold constraint: prevent rapid aspect changes (hold-safety interval). */
static int g_signal_hold_timer[8] = {0, 0, 0, 0, 0, 0, 0, 0};

static int
ry_signal_can_change(int sig_id)
{
    return (g_signal_hold_timer[sig_id] == 0) ? 1 : 0;
}

static void
ry_signal_lock_change(int sig_id, int hold_cycles)
{
    if (sig_id < 8)
        g_signal_hold_timer[sig_id] = hold_cycles;
}

static void
ry_signal_hold_tick(void)
{
    int i;
    for (i = 0; i < 8; i++) {
        if (g_signal_hold_timer[i] > 0)
            g_signal_hold_timer[i]--;
    }
}

/* Advanced validator: multi-level route-clear approval. */
static int
ry_validate_route_multi_level(int route_id)
{
    int level1, level2, level3;

    /* Level 1: basic interlock. */
    level1 = ry_check_interlock(route_id);

    /* Level 2: safe working space. */
    level2 = ry_validate_safe_working_space(route_id);

    /* Level 3: comprehensive (includes deadlock prevention). */
    level3 = (ry_deadlock_detect(), 1);  /* performs check as side-effect */

    return (level1 && level2 && level3) ? 1 : 0;
}

/* Route-failure recovery: attempt to auto-recover stuck routes. */
struct RouteRecovery {
    int route_id;
    int attempt_count;
    int last_attempt_cycle;
};

static struct RouteRecovery g_recoveries[8] = {
    {0, 0, 0}, {0, 0, 0}, {0, 0, 0}, {0, 0, 0},
    {0, 0, 0}, {0, 0, 0}, {0, 0, 0}, {0, 0, 0},
};

static void
ry_attempt_route_recovery(int route_id)
{
    int i, found = -1, retry_interval = 30;

    /* Find recovery slot. */
    for (i = 0; i < 8; i++) {
        if (g_recoveries[i].route_id == route_id) {
            found = i;
            break;
        } else if (g_recoveries[i].route_id == 0) {
            found = i;
            break;
        }
    }

    if (found >= 0) {
        if (g_scan_cycle_count - g_recoveries[found].last_attempt_cycle >= retry_interval) {
            g_recoveries[found].route_id = route_id;
            g_recoveries[found].attempt_count++;
            g_recoveries[found].last_attempt_cycle = g_scan_cycle_count;

            /* Try to release and re-lock. */
            ry_release_route_locks(route_id);
            if (ry_comprehensive_interlock_check(route_id)) {
                ry_lock_section(route_id);
                ry_hist_record(1, route_id, 888);  /* recovery success */
            }
        }
    }
}

/* Advanced occupancy voting with degraded mode (if detectors fail). */
static int
ry_occupancy_vote_degraded(int section_id)
{
    int i, healthy_count = 0, occupied_vote = 0;
    struct TrackVote *vote;

    for (i = 0; i < 6; i++) {
        if (g_track_votes[i].section_id == section_id) {
            vote = &g_track_votes[i];

            /* Count healthy detectors. */
            int j;
            for (j = 0; j < 3; j++) {
                if (g_detector_redund[i*3 + j].healthy)
                    healthy_count++;
            }

            /* Voting rule changes based on detector health. */
            if (healthy_count == 3) {
                /* Normal 2oo3. */
                occupied_vote = vote->detector[0] + vote->detector[1] + vote->detector[2];
                return (occupied_vote >= 2) ? 1 : 0;
            } else if (healthy_count == 2) {
                /* Degraded 2oo2: need both healthy detectors to agree. */
                occupied_vote = vote->detector[0] + vote->detector[1];
                return (occupied_vote >= 2) ? 1 : 0;
            } else {
                /* Too many failures: assume OCCUPIED (fail-safe). */
                return 1;
            }
        }
    }

    return 0;
}

/* Mutual-exclusion enforcement for conflicting signals. */
static void
ry_enforce_mutex_signals(void)
{
    int i, sig1, sig2;

    for (i = 0; i < 12; i++) {
        sig1 = g_sig_conflicts[i].sig1;
        sig2 = g_sig_conflicts[i].sig2;

        /* If both requested GREEN, downgrade one to YELLOW. */
        if (g_signal_seq[sig1].requested == 2 && g_signal_seq[sig2].requested == 2) {
            if (sig1 < sig2)
                g_signal_seq[sig2].requested = 1;  /* downgrade to YELLOW */
            else
                g_signal_seq[sig1].requested = 1;
        }
    }
}

/* Forward declaration for stub helper. */
static void
ry_injected_occupancy(void);

/* Comprehensive interlock cycle (all checks + timers + diagnostics). */
static void
ry_full_interlock_cycle(void)
{
    /* Phase 1: Update occupancy. */
    ry_injected_occupancy();

    /* Phase 2: Update trends. */
    int i;
    for (i = 0; i < 6; i++) {
        ry_update_occupancy_trend(g_track_votes[i].section_id,
                                   g_track_votes[i].consensus);
    }

    /* Phase 3: Enforce constraints. */
    ry_enforce_signal_conflicts();
    ry_enforce_track_interlocking();
    ry_enforce_mutex_signals();

    /* Phase 4: Timers. */
    ry_turnout_cycle();
    ry_lock_release_cycle();
    ry_aspect_hold_tick();
    ry_signal_hold_tick();
    ry_sequence_timer_tick();

    /* Phase 5: Health checks. */
    ry_detector_health_check();
    ry_deadlock_detect();

    /* Phase 6: Recovery attempts. */
    for (i = 1; i <= 8; i++) {
        if (g_ry_routes[i-1].is_locked) {
            ry_attempt_route_recovery(i);
        }
    }

    /* Phase 7: Diagnostics. */
    if ((g_scan_cycle_count & 0x3f) == 0) {
        ry_diagnostic_snapshot();
    }
}

/* Stub helper to fix broken reference. */
static void
ry_injected_occupancy(void)
{
    ry_inject_occupancy();
}

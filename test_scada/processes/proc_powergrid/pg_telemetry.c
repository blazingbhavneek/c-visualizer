/*
 * proc_powergrid/pg_telemetry.c
 * Electrical substation RTU poller and telemetry acquisition.
 * Implements event-driven scan cycles, historian archival, and distributed
 * remote-terminal-unit (RTU) communication with deadband filtering and
 * engineering-unit transformation.
 */

#include <stddef.h>
#include "pg_app.h"
#include "scf_tag.h"
#include "scf_queue.h"
#include "scf_event.h"
#include "scf_const.h"

/* ============================================================
 * GROUND TRUTH
 *
 * path 1: main -> (FORK) -> pg_poll_task
 *         -> scf_hist_save(ARC_TREND, &rec)
 *    api: scf_hist_save  type=SAVEF  launch_via=FORK  arg1=200
 *
 * path 2: main -> (FORK) -> pg_poll_task
 *         -> scf_evt_post(EVT_HIST_FLUSH, NULL)
 *    api: scf_evt_post  type=EVENT  launch_via=FORK  arg1=3005
 *
 * path 3: main -> (EVENT via scf_evt_register) -> pg_on_scan
 *         -> scf_evt_post(EVT_SCAN_CYCLE, data)
 *    api: scf_evt_post  type=EVENT  launch_via=EVENT  arg1=3001
 *
 * path 4: main -> (EVENT) -> pg_on_scan
 *         -> pg_scan_feeders(PT_MOTOR_TEMP)
 *         -> pg_read_analog(PT_MOTOR_TEMP)
 *         -> scf_tag_read(&ctx, PT_MOTOR_TEMP, buf)
 *    api: scf_tag_read  type=READF  launch_via=EVENT  arg2=0x1005  call_number=3001
 *
 * path 5: main -> (EVENT) -> pg_on_scan
 *         -> pg_read_status(PT_VALVE_POS)
 *         -> scf_tag_read(&ctx, PT_VALVE_POS, buf)
 *    api: scf_tag_read  type=READF  launch_via=EVENT  arg2=0x1002  call_number=3001
 *
 * path 6: main via pg_init -> pg_rtu_getptr(PT_PRESSURE)
 *         -> scf_tag_open(&ctx, PT_PRESSURE, SCF_READ_LOCK)  [CONSIDER THIS CALL]
 *    api: scf_tag_open  type=OPENF  arg2=0x1006
 *
 * path 7: main -> (EVENT) -> pg_on_scan
 *         -> scf_tag_write(&ctx, PT_SETPOINT, pg_ext_comm_value())
 *    api: scf_tag_write  type=WRITEF  launch_via=EVENT  arg2=0x1007  arg3=UNRESOLVED
 *
 * path 8: (edge case, NOT followed) RTU driver dispatch via struct fn-ptr
 *         drv->read(ctx, pid) -> indirect_call
 *
 * path 9: (edge case, NOT followed) local function pointer
 *         int (*poll_fn)(int) = pg_read_analog; poll_fn(pid) -> indirect_call
 *
 * ============================================================ */

/* ============================================================
 * Modbus RTU Register Mapping & Analog I/O Configuration
 * ============================================================ */

/* DNP3-compatible register offsets for remote RTU polling. */
#define MODBUS_PUMP_SPEED_REG      0x1001
#define MODBUS_VALVE_POS_REG       0x1002
#define MODBUS_TANK_LEVEL_REG      0x1003
#define MODBUS_FLOW_RATE_REG       0x1004
#define MODBUS_MOTOR_TEMP_REG      0x1005
#define MODBUS_PRESSURE_REG        0x1006
#define MODBUS_SETPOINT_REG        0x1007

/* Scaling factors: fixed-point 16.16 multipliers for engineering units. */
#define SCALE_PUMP_SPEED           655360  /* 10 rpm/count */
#define SCALE_VALVE_POS            32768   /* 0.5 %/count */
#define SCALE_TANK_LEVEL           327680  /* 5 m/count */
#define SCALE_FLOW_RATE            131072  /* 2 L/s per count */
#define SCALE_MOTOR_TEMP           16384   /* 0.25 C/count */
#define SCALE_PRESSURE             204800  /* 3.125 kPa/count */

/* Deadband thresholds (hysteresis) to suppress chattering reports. */
#define DEADBAND_PUMP_SPEED        50
#define DEADBAND_VALVE_POS         2
#define DEADBAND_TANK_LEVEL        100
#define DEADBAND_FLOW_RATE         25
#define DEADBAND_MOTOR_TEMP        5
#define DEADBAND_PRESSURE          10

/* Quality flags per SCADA convention (bit-encoded). */
#define QUALITY_GOOD               0x00
#define QUALITY_BAD_INPUT          0x01
#define QUALITY_DEVICE_FAIL        0x02
#define QUALITY_SENSOR_FAULT       0x04
#define QUALITY_COMM_TIMEOUT       0x08
#define QUALITY_OVERFLOW           0x10
#define QUALITY_OUT_OF_RANGE       0x20

/* Poll scheduling: intervals (msec) per point. */
#define POLL_INTERVAL_CRITICAL     250
#define POLL_INTERVAL_NORMAL       1000
#define POLL_INTERVAL_SLOW         5000

/* RTU Comms retry policy. */
#define MAX_RTU_RETRIES            3
#define RTU_TIMEOUT_MS             500
#define RTU_BACKOFF_MS             100

/* ============================================================
 * RTU Driver Structure and Frame Definitions
 * ============================================================ */

typedef struct {
    int   unit_id;
    int   state;
    int   crc_errors;
    int   timeout_count;
} RtuDevice;

typedef struct {
    int (*read)(int pid);   /* Function pointer for EDGE CASE. */
    int (*write)(int pid);
} RtuDriver;

/* RTU frame format (Modbus-like). */
typedef struct {
    unsigned char addr;
    unsigned char func;
    unsigned short reg;
    unsigned short count;
    unsigned short crc;
} ModbusFrame;

/* Frame buffer for RTU communication. */
static struct {
    unsigned char tx_buf[256];
    unsigned char rx_buf[256];
    int           tx_len;
    int           rx_len;
} rtu_frame = { {0}, {0}, 0, 0 };

/* ============================================================
 * Static State: Analog Point Cache, Deadband History, Poll Counters
 * ============================================================ */

/* Last-reported values for deadband filtering (one per analog point). */
static struct {
    int pump_speed_last;
    int valve_pos_last;
    int tank_level_last;
    int flow_rate_last;
    int motor_temp_last;
    int pressure_last;
    int setpoint_last;
} point_history = {
    0, 0, 0, 0, 0, 0, 0
};

/* Poll counters for scheduling (milliseconds elapsed). */
static struct {
    int pump_speed_counter;
    int valve_pos_counter;
    int tank_level_counter;
    int flow_rate_counter;
    int motor_temp_counter;
    int pressure_counter;
    int setpoint_counter;
} poll_timers = {
    0, 0, 0, 0, 0, 0, 0
};

/* Quality flags (tracked per point for historian). */
static struct {
    unsigned char pump_speed;
    unsigned char valve_pos;
    unsigned char tank_level;
    unsigned char flow_rate;
    unsigned char motor_temp;
    unsigned char pressure;
    unsigned char setpoint;
} point_quality = {
    QUALITY_GOOD, QUALITY_GOOD, QUALITY_GOOD, QUALITY_GOOD,
    QUALITY_GOOD, QUALITY_GOOD, QUALITY_GOOD
};

/* RTU connectivity state. */
static struct {
    int link_ok;
    int slave_id;
    int last_error;
    int retry_count;
    int state;
    int crc_errors;
} rtu_status = { 1, 1, 0, 0, 0, 0 };

/* Historian buffer (ring). */
static struct {
    HistRec records[128];
    int     write_ptr;
    int     count;
} hist_ring = { {0}, 0, 0 };

/* ============================================================
 * Helper: CRC-16 Modbus Checksum (for frame validation)
 * ============================================================ */

static unsigned short pg_crc16_modbus(unsigned char *buf, int len)
{
    unsigned short crc = 0xFFFF;
    int i, j;

    for (i = 0; i < len; i++) {
        crc ^= buf[i];
        for (j = 0; j < 8; j++) {
            if (crc & 1) {
                crc = (crc >> 1) ^ 0xA001;
            } else {
                crc = crc >> 1;
            }
        }
    }
    return crc;
}

/* ============================================================
 * Helper: RTU Frame Construction (Modbus Read Coil)
 * ============================================================ */

static int pg_frame_build_read_coil(int slave_id, int start_reg, int count)
{
    ModbusFrame *frm = (ModbusFrame *)rtu_frame.tx_buf;

    frm->addr  = slave_id;
    frm->func  = 0x01;  /* Read Coils */
    frm->reg   = (unsigned short)start_reg;
    frm->count = (unsigned short)count;
    frm->crc   = pg_crc16_modbus(rtu_frame.tx_buf, 6);

    rtu_frame.tx_len = 8;
    return 0;
}

/* ============================================================
 * Helper: RTU Frame Parsing (response extraction)
 * ============================================================ */

static int pg_frame_parse_response(unsigned char *data, int *out_val)
{
    unsigned short crc_rx, crc_calc;
    int len = rtu_frame.rx_len;

    if (len < 5) return -1;

    /* Verify CRC. */
    crc_rx = (rtu_frame.rx_buf[len - 1] << 8) | rtu_frame.rx_buf[len - 2];
    crc_calc = pg_crc16_modbus(rtu_frame.rx_buf, len - 2);

    if (crc_rx != crc_calc) {
        rtu_status.last_error = 1;
        return -2;
    }

    /* Extract value (coil state or register value). */
    if (rtu_frame.rx_buf[1] == 0x01 || rtu_frame.rx_buf[1] == 0x03) {
        *out_val = (int)(rtu_frame.rx_buf[3] | (rtu_frame.rx_buf[4] << 8));
        return 0;
    }

    return -3;
}

/* ============================================================
 * Helper: Apply Engineering-Unit Scaling
 * ============================================================ */

static int pg_apply_scale(int raw_value, int scale_factor)
{
    return (raw_value * scale_factor) >> 16;
}

/* ============================================================
 * Helper: Deadband Check (compare with history, update if changed)
 * ============================================================ */

static int pg_deadband_check(int current, int last, int threshold)
{
    int delta = current - last;
    if (delta < 0) delta = -delta;
    return (delta >= threshold) ? 1 : 0;
}

/* ============================================================
 * Helper: Write Point to Quality Cache
 * ============================================================ */

static void pg_set_quality(int point_id, unsigned char quality)
{
    switch (point_id) {
    case PT_PUMP_SPEED:   point_quality.pump_speed = quality; break;
    case PT_VALVE_POS:    point_quality.valve_pos = quality; break;
    case PT_TANK_LEVEL:   point_quality.tank_level = quality; break;
    case PT_FLOW_RATE:    point_quality.flow_rate = quality; break;
    case PT_MOTOR_TEMP:   point_quality.motor_temp = quality; break;
    case PT_PRESSURE:     point_quality.pressure = quality; break;
    case PT_SETPOINT:     point_quality.setpoint = quality; break;
    }
}

/* ============================================================
 * Helper: Get Quality Cache
 * ============================================================ */

static unsigned char pg_get_quality(int point_id)
{
    switch (point_id) {
    case PT_PUMP_SPEED:   return point_quality.pump_speed;
    case PT_VALVE_POS:    return point_quality.valve_pos;
    case PT_TANK_LEVEL:   return point_quality.tank_level;
    case PT_FLOW_RATE:    return point_quality.flow_rate;
    case PT_MOTOR_TEMP:   return point_quality.motor_temp;
    case PT_PRESSURE:     return point_quality.pressure;
    case PT_SETPOINT:     return point_quality.setpoint;
    }
    return QUALITY_GOOD;
}

/* ============================================================
 * Helper: Poll Timer Increment (call each scan cycle)
 * ============================================================ */

static void pg_poll_timers_tick(int interval_ms)
{
    poll_timers.pump_speed_counter += interval_ms;
    poll_timers.valve_pos_counter += interval_ms;
    poll_timers.tank_level_counter += interval_ms;
    poll_timers.flow_rate_counter += interval_ms;
    poll_timers.motor_temp_counter += interval_ms;
    poll_timers.pressure_counter += interval_ms;
    poll_timers.setpoint_counter += interval_ms;
}

/* ============================================================
 * Helper: Check if Point is Due for Poll
 * ============================================================ */

static int pg_poll_due(int point_id, int interval)
{
    int *counter = NULL;

    switch (point_id) {
    case PT_PUMP_SPEED:   counter = &poll_timers.pump_speed_counter; break;
    case PT_VALVE_POS:    counter = &poll_timers.valve_pos_counter; break;
    case PT_TANK_LEVEL:   counter = &poll_timers.tank_level_counter; break;
    case PT_FLOW_RATE:    counter = &poll_timers.flow_rate_counter; break;
    case PT_MOTOR_TEMP:   counter = &poll_timers.motor_temp_counter; break;
    case PT_PRESSURE:     counter = &poll_timers.pressure_counter; break;
    case PT_SETPOINT:     counter = &poll_timers.setpoint_counter; break;
    }

    if (counter && *counter >= interval) {
        *counter = 0;
        return 1;
    }
    return 0;
}

/* ============================================================
 * Helper: Historian Ring Buffer Append
 * ============================================================ */

static void pg_hist_append(int archive_id, int stamp, int value)
{
    int idx = hist_ring.write_ptr;

    hist_ring.records[idx].archive_id = archive_id;
    hist_ring.records[idx].stamp = stamp;
    hist_ring.records[idx].value = value;

    hist_ring.write_ptr = (hist_ring.write_ptr + 1) % 128;
    if (hist_ring.count < 128) {
        hist_ring.count++;
    }
}

/* ============================================================
 * Helper: Validate Remote Terminal Unit (link status)
 * ============================================================ */

static int pg_rtu_validate_link(void)
{
    /* Simulated link check: return status. */
    if (rtu_status.retry_count > MAX_RTU_RETRIES) {
        rtu_status.link_ok = 0;
        return -1;
    }
    rtu_status.link_ok = 1;
    return 0;
}

/* ============================================================
 * Helper: RTU Retry Logic with Exponential Backoff
 * ============================================================ */

static int pg_rtu_retry(int attempt)
{
    int backoff_ms = RTU_BACKOFF_MS * (1 << attempt);
    if (attempt >= MAX_RTU_RETRIES) {
        return -1;
    }
    rtu_status.retry_count = attempt + 1;
    return backoff_ms;
}

/* ============================================================
 * Helper: Simulate RTU Register Read (with timeout/CRC)
 * ============================================================ */

static int pg_rtu_raw_read(int slave_id, int register_addr, int *raw_val)
{
    int result;

    if (pg_rtu_validate_link() < 0) {
        pg_set_quality(register_addr, QUALITY_COMM_TIMEOUT);
        return -1;
    }

    pg_frame_build_read_coil(slave_id, register_addr, 1);
    rtu_frame.rx_len = 7;  /* Simulated response: 7 bytes. */
    rtu_frame.rx_buf[0] = slave_id;
    rtu_frame.rx_buf[1] = 0x03;
    rtu_frame.rx_buf[2] = 2;
    rtu_frame.rx_buf[3] = (register_addr >> 8) & 0xFF;
    rtu_frame.rx_buf[4] = (register_addr) & 0xFF;
    rtu_frame.rx_buf[5] = 0x00;
    rtu_frame.rx_buf[6] = 0x00;

    result = pg_frame_parse_response(NULL, raw_val);
    if (result < 0) {
        pg_rtu_retry(rtu_status.retry_count);
        return result;
    }

    rtu_status.retry_count = 0;
    pg_set_quality(register_addr, QUALITY_GOOD);
    return 0;
}

/* ============================================================
 * PUBLIC: pg_rtu_getptr — RTU Driver Getter (selection demo)
 *
 * Demonstrates multiple scf_tag_open calls with marked CONSIDER
 * for the intended call. Also demonstrates struct function-pointer
 * EDGE CASE (indirect_call, NOT followed by tracer).
 * ============================================================ */

void *pg_rtu_getptr(int fno)
{
    static TagCtx ctx_pump, ctx_motor, ctx_pressure;
    TagCtx *selected_ctx = NULL;
    static RtuDriver drv = { NULL, NULL };

    /* Initialize the driver with function pointers (EDGE CASE). */
    drv.read = pg_read_analog;
    drv.write = pg_read_status;

    /*
     * EDGE CASE 1: Struct function-pointer dispatch.
     * drv->read(...) becomes indirect_call (NOT followed).
     */
    if (fno == PT_PUMP_SPEED) {
        /* Unused call for comparison. */
        scf_tag_open(&ctx_pump, PT_PUMP_SPEED, SCF_READ_LOCK);
        selected_ctx = &ctx_pump;
    } else if (fno == PT_MOTOR_TEMP) {
        /* Unused call for comparison. */
        scf_tag_open(&ctx_motor, PT_MOTOR_TEMP, SCF_READ_LOCK);
        selected_ctx = &ctx_motor;
    } else if (fno == PT_PRESSURE) {
        /* INTENDED CALL — marked for tracer selection. arg2 is the fno
         * parameter (resolves to PT_PRESSURE via backward parameter flow). */
        scf_tag_open(&ctx_pressure, fno, SCF_READ_LOCK);  /*CONSIDER THIS CALL*/
        selected_ctx = &ctx_pressure;
    }

    return (void *)selected_ctx;
}

/* ============================================================
 * PUBLIC: pg_read_analog — Analog Value Acquisition
 *
 * Reads a raw register via RTU, applies engineering-unit scaling,
 * performs deadband filtering, and returns the transformed value.
 * Called from the EVENT-driven pg_scan_feeders path.
 * ============================================================ */

int pg_read_analog(int pid)
{
    TagCtx ctx;
    int raw_val = 0;
    int scaled_val = 0;
    int scale_factor = 0;
    int deadband_threshold = 0;
    int should_report = 0;
    int *last_value_ptr = NULL;
    void *buf = NULL;

    /* Determine scaling and deadband based on point type. */
    switch (pid) {
    case PT_PUMP_SPEED:
        scale_factor = SCALE_PUMP_SPEED;
        deadband_threshold = DEADBAND_PUMP_SPEED;
        last_value_ptr = &point_history.pump_speed_last;
        break;
    case PT_VALVE_POS:
        scale_factor = SCALE_VALVE_POS;
        deadband_threshold = DEADBAND_VALVE_POS;
        last_value_ptr = &point_history.valve_pos_last;
        break;
    case PT_TANK_LEVEL:
        scale_factor = SCALE_TANK_LEVEL;
        deadband_threshold = DEADBAND_TANK_LEVEL;
        last_value_ptr = &point_history.tank_level_last;
        break;
    case PT_FLOW_RATE:
        scale_factor = SCALE_FLOW_RATE;
        deadband_threshold = DEADBAND_FLOW_RATE;
        last_value_ptr = &point_history.flow_rate_last;
        break;
    case PT_MOTOR_TEMP:
        scale_factor = SCALE_MOTOR_TEMP;
        deadband_threshold = DEADBAND_MOTOR_TEMP;
        last_value_ptr = &point_history.motor_temp_last;
        break;
    case PT_PRESSURE:
        scale_factor = SCALE_PRESSURE;
        deadband_threshold = DEADBAND_PRESSURE;
        last_value_ptr = &point_history.pressure_last;
        break;
    default:
        return -1;
    }

    /* Fetch raw value from RTU. */
    if (pg_rtu_raw_read(rtu_status.slave_id, pid, &raw_val) < 0) {
        pg_set_quality(pid, QUALITY_COMM_TIMEOUT);
        return -1;
    }

    /* Apply engineering-unit scaling. */
    scaled_val = pg_apply_scale(raw_val, scale_factor);

    /* Deadband filtering: only report if change exceeds threshold. */
    should_report = pg_deadband_check(scaled_val, *last_value_ptr, deadband_threshold);
    if (should_report) {
        *last_value_ptr = scaled_val;
    }

    /* Read the point via framework API (traced). */
    scf_tag_read(&ctx, pid, buf);

    return scaled_val;
}

/* ============================================================
 * PUBLIC: pg_read_status — Status/Boolean Point Acquisition
 *
 * Reads a digital status point (e.g., valve position discrete).
 * Simpler path than analog: no scaling, only quality check.
 * ============================================================ */

int pg_read_status(int pid)
{
    TagCtx ctx;
    int raw_val = 0;
    void *buf = NULL;

    /* Fetch raw value from RTU. */
    if (pg_rtu_raw_read(rtu_status.slave_id, pid, &raw_val) < 0) {
        pg_set_quality(pid, QUALITY_COMM_TIMEOUT);
        return -1;
    }

    /* Validate range. */
    if (raw_val < 0 || raw_val > 100) {
        pg_set_quality(pid, QUALITY_OUT_OF_RANGE);
        return -1;
    }

    pg_set_quality(pid, QUALITY_GOOD);

    /* Read via framework API (traced). */
    scf_tag_read(&ctx, pid, buf);

    return raw_val;
}

/* ============================================================
 * PUBLIC: pg_scan_feeders — Feeder-Group Scan Loop
 *
 * Iterates over a set of analog points associated with a base
 * point ID. Calls pg_read_analog for each point in sequence.
 * Part of the EVENT-launched scan path (traced).
 * ============================================================ */

int pg_scan_feeders(int base_pid)
{
    int feeder_count = 0;
    int point_list[8];
    int i = 0;

    /*
     * Build dynamic feeder point list based on base_pid.
     * In a real system, this might enumerate a substation configuration.
     */
    if (base_pid == PT_MOTOR_TEMP) {
        point_list[0] = PT_MOTOR_TEMP;
        point_list[1] = PT_PUMP_SPEED;
        point_list[2] = PT_TANK_LEVEL;
        feeder_count = 3;
    } else if (base_pid == PT_PRESSURE) {
        point_list[0] = PT_PRESSURE;
        point_list[1] = PT_FLOW_RATE;
        feeder_count = 2;
    } else {
        feeder_count = 1;
        point_list[0] = base_pid;
    }

    /* Primary traced read: the base point resolves cleanly via parameter
     * flow (pg_on_scan passes PT_MOTOR_TEMP -> base_pid -> pid -> scf_tag_read). */
    pg_read_analog(base_pid);

    /* Poll the remaining feeder points (array-indexed; realistic scan). */
    for (i = 0; i < feeder_count; i++) {
        pg_read_analog(point_list[i]);
    }

    return feeder_count;
}

/* ============================================================
 * PUBLIC: pg_on_scan — EVENT-Driven Scan Cycle Handler
 *
 * Registered as the callback for EVT_SCAN_CYCLE events.
 * Initiates telemetry acquisition: scans feeders, reads status,
 * posts call_number event, and handles setpoint writes.
 * This is the entry point for EVENT-launched paths (traced).
 * ============================================================ */

void pg_on_scan(int evt, void *data)
{
    TagCtx ctx;
    int setpoint_cmd = 0;
    int poll_interval = POLL_INTERVAL_CRITICAL;

    /* Post event marker with call_number (EVT_SCAN_CYCLE = 3001). */
    scf_evt_post(EVT_SCAN_CYCLE, data);

    /* Tick poll timers. */
    pg_poll_timers_tick(poll_interval);

    /* Scan motor feeder group (includes PT_MOTOR_TEMP). */
    pg_scan_feeders(PT_MOTOR_TEMP);

    /* Read valve position status. */
    pg_read_status(PT_VALVE_POS);

    /* ====== UNRESOLVED CASE ====== */
    /* Setpoint write with unresolved external function. */
    setpoint_cmd = pg_ext_comm_value();
    scf_tag_write(&ctx, PT_SETPOINT, setpoint_cmd);

    /* ====== EDGE CASE 2 (NOT followed) ====== */
    /* Local function-pointer call: becomes indirect_call. */
    {
        int (*poll_fn)(int) = pg_read_analog;
        poll_fn(PT_FLOW_RATE);
    }
}

/* ============================================================
 * PUBLIC: pg_poll_task — Historian Archival and Flush (FORK)
 *
 * Runs as a separate task (via scf_task_fork).
 * Periodically saves historian records and flushes to archive.
 * Demonstrates FORK-launched path with scf_hist_save and scf_evt_post.
 * ============================================================ */

void pg_poll_task(int task_id)
{
    HistRec rec;
    int i = 0;
    int tick_count = 0;

    /* Infinite task loop (simplified for test). */
    for (tick_count = 0; tick_count < 10; tick_count++) {

        /* Wait for scan cycle to complete (semaphore). */
        scf_sem_wait(SEM_DBLOCK);

        /* Collect analog points into historian record. */
        rec.archive_id = ARC_TREND;
        rec.stamp = tick_count;
        rec.value = point_history.motor_temp_last;

        /* Save to historian ring buffer. */
        pg_hist_append(ARC_TREND, tick_count, point_history.motor_temp_last);

        /* Framework historian save (traced). */
        scf_hist_save(ARC_TREND, &rec);

        /* Every N cycles, post flush event. */
        if ((tick_count % 4) == 0) {
            /* Post with call_number (EVT_HIST_FLUSH = 3005). */
            scf_evt_post(EVT_HIST_FLUSH, NULL);
        }

        /* Signal next scan cycle. */
        scf_sem_post(SEM_DBLOCK);
    }

    /* Task exit (simulated). */
    scf_task_kill(TASK_HIST);
}

/* ============================================================
 * Static Helper: Historian Buffer Flush
 * ============================================================ */

static int pg_hist_flush_buffer(void)
{
    HistRec *rec_ptr = NULL;
    int i = 0;

    for (i = 0; i < hist_ring.count; i++) {
        rec_ptr = &hist_ring.records[i];
        scf_hist_save(ARC_TREND, rec_ptr);
    }

    hist_ring.write_ptr = 0;
    hist_ring.count = 0;
    return 0;
}

/* ============================================================
 * Static Helper: Point Quality Report (alarm conditions)
 * ============================================================ */

static void pg_check_point_quality(int point_id)
{
    unsigned char quality = pg_get_quality(point_id);

    if (quality & QUALITY_DEVICE_FAIL) {
        RAISE_ALARM(ALM_OVERTEMP);
    } else if (quality & QUALITY_COMM_TIMEOUT) {
        RAISE_ALARM(ALM_OVERPRESSURE);
    }
}

/* ============================================================
 * Static Helper: Register Map Lookup (Modbus address → point ID)
 * ============================================================ */

static int pg_register_to_point_id(unsigned short reg)
{
    switch (reg) {
    case MODBUS_PUMP_SPEED_REG:  return PT_PUMP_SPEED;
    case MODBUS_VALVE_POS_REG:   return PT_VALVE_POS;
    case MODBUS_TANK_LEVEL_REG:  return PT_TANK_LEVEL;
    case MODBUS_FLOW_RATE_REG:   return PT_FLOW_RATE;
    case MODBUS_MOTOR_TEMP_REG:  return PT_MOTOR_TEMP;
    case MODBUS_PRESSURE_REG:    return PT_PRESSURE;
    case MODBUS_SETPOINT_REG:    return PT_SETPOINT;
    default:                     return -1;
    }
}

/* ============================================================
 * Static Helper: Engineering Unit Conversion (scaled → physical)
 * ============================================================ */

static int pg_eng_unit_pump_speed(int scaled)
{
    return (scaled * 10) / 655360;
}

static int pg_eng_unit_motor_temp(int scaled)
{
    return (scaled * 100) / 16384;
}

static int pg_eng_unit_pressure(int scaled)
{
    return (scaled * 3125) / 204800;
}

/* ============================================================
 * Static Helper: Poll Scheduling Decision Logic
 * ============================================================ */

static int pg_decide_poll_priority(int point_id)
{
    /* Return poll interval (msec) based on point criticality. */
    switch (point_id) {
    case PT_PRESSURE:
    case PT_MOTOR_TEMP:
    case PT_FLOW_RATE:
        return POLL_INTERVAL_CRITICAL;
    case PT_PUMP_SPEED:
    case PT_VALVE_POS:
        return POLL_INTERVAL_NORMAL;
    case PT_TANK_LEVEL:
        return POLL_INTERVAL_SLOW;
    default:
        return POLL_INTERVAL_NORMAL;
    }
}

/* ============================================================
 * Static Helper: Alarm Threshold Check (min/max limits)
 * ============================================================ */

static int pg_check_alarm_thresholds(int point_id, int value)
{
    /* Simplified threshold logic. */
    if (point_id == PT_MOTOR_TEMP && value > 120) {
        RAISE_ALARM(ALM_OVERTEMP);
        return 1;
    }
    if (point_id == PT_TANK_LEVEL && value < 10) {
        RAISE_ALARM(ALM_LOWLEVEL);
        return 1;
    }
    if (point_id == PT_PRESSURE && value > 500) {
        RAISE_ALARM(ALM_OVERPRESSURE);
        return 1;
    }
    return 0;
}

/* ============================================================
 * Static Helper: RTU State Machine Advance
 * ============================================================ */

static int pg_rtu_state_tick(void)
{
    switch (rtu_status.state) {
    case 0:
        /* IDLE: wait for poll. */
        break;
    case 1:
        /* SENDING: transmit frame. */
        rtu_status.state = 2;
        break;
    case 2:
        /* WAITING: await response. */
        if (rtu_frame.rx_len > 0) {
            rtu_status.state = 3;
        }
        break;
    case 3:
        /* PROCESSING: parse and validate. */
        rtu_status.state = 0;
        break;
    }
    return rtu_status.state;
}

/* ============================================================
 * Static Helper: Trace Log (for diagnostic output)
 * ============================================================ */

static void pg_trace_scan_event(int event_code, int point_id, int value)
{
    /* In a real system, this would write to a trace buffer or syslog. */
    (void)event_code;
    (void)point_id;
    (void)value;
}

/* ============================================================
 * Static Helper: Configuration Load (scan intervals, limits)
 * ============================================================ */

static int pg_load_scan_config(void)
{
    /* Load configuration parameters from scf_cfg. */
    scf_cfg_clear(CFG_SCAN);
    return 0;
}

/* ============================================================
 * Static Helper: Validate Point Value Range
 * ============================================================ */

static int pg_validate_range(int point_id, int value)
{
    switch (point_id) {
    case PT_PUMP_SPEED:
        return (value >= 0 && value <= 4000) ? 1 : 0;
    case PT_VALVE_POS:
        return (value >= 0 && value <= 100) ? 1 : 0;
    case PT_TANK_LEVEL:
        return (value >= 0 && value <= 500) ? 1 : 0;
    case PT_FLOW_RATE:
        return (value >= 0 && value <= 300) ? 1 : 0;
    case PT_MOTOR_TEMP:
        return (value >= -50 && value <= 150) ? 1 : 0;
    case PT_PRESSURE:
        return (value >= 0 && value <= 800) ? 1 : 0;
    case PT_SETPOINT:
        return (value >= 0 && value <= 500) ? 1 : 0;
    }
    return 0;
}

/* ============================================================
 * Static Helper: Clear All Quality Flags
 * ============================================================ */

static void pg_clear_quality_flags(void)
{
    point_quality.pump_speed = QUALITY_GOOD;
    point_quality.valve_pos = QUALITY_GOOD;
    point_quality.tank_level = QUALITY_GOOD;
    point_quality.flow_rate = QUALITY_GOOD;
    point_quality.motor_temp = QUALITY_GOOD;
    point_quality.pressure = QUALITY_GOOD;
    point_quality.setpoint = QUALITY_GOOD;
}

/* ============================================================
 * Static Helper: Restart RTU Connection
 * ============================================================ */

static int pg_rtu_restart(void)
{
    rtu_status.link_ok = 0;
    rtu_status.retry_count = 0;
    rtu_status.last_error = 0;
    pg_clear_quality_flags();
    return 0;
}

/* ============================================================
 * Static Helper: Copy Tag Value (framework macro wrapper)
 * ============================================================ */

static int pg_tag_copy_helper(int src_id, int dst_id)
{
    return scf_tag_copy(src_id, dst_id);
}

/* ============================================================
 * Static Helper: Close Tag Context
 * ============================================================ */

static int pg_tag_close_helper(TagCtx *ctx)
{
    return scf_tag_close(ctx);
}

/* ============================================================
 * Static Helper: Point Lookup by Register Address
 * ============================================================ */

static int pg_lookup_point_from_address(int slave_id, unsigned short addr)
{
    int mapped_id = pg_register_to_point_id(addr);
    if (mapped_id >= 0) {
        return mapped_id;
    }
    return -1;
}

/* ============================================================
 * Static Helper: Feeder Load Profile Computation
 * ============================================================ */

static int pg_compute_load_profile(int feeder_id, int flow, int pressure)
{
    /* Simplified load profile: P = Q * H / efficiency
       where Q is flow rate, H is pressure head. */
    int load_kw = (flow * pressure) / 100;
    return (load_kw > 0) ? load_kw : 0;
}

/* ============================================================
 * Static Helper: Demand (kW) Accumulator for Historian
 * ============================================================ */

static struct {
    int demand_sum;
    int sample_count;
    int interval_ms;
} demand_accum = { 0, 0, 1000 };

static int pg_demand_add_sample(int kw)
{
    demand_accum.demand_sum += kw;
    demand_accum.sample_count++;
    if (demand_accum.sample_count >= 60) {
        int avg_demand = demand_accum.demand_sum / demand_accum.sample_count;
        demand_accum.demand_sum = 0;
        demand_accum.sample_count = 0;
        return avg_demand;
    }
    return -1;  /* Not yet ready */
}

/* ============================================================
 * Static Helper: Exponential Smoothing Filter
 * ============================================================ */

static int pg_ema_update(int *ema_state, int new_sample, int alpha_percent)
{
    int alpha = alpha_percent;  /* e.g., 30 for 30% = 0.3 */
    int new_ema;

    if (*ema_state == 0) {
        *ema_state = new_sample;
        return new_sample;
    }

    new_ema = ((*ema_state * (100 - alpha)) + (new_sample * alpha)) / 100;
    *ema_state = new_ema;
    return new_ema;
}

/* ============================================================
 * Static Helper: Analog Output (DAC) Update
 * ============================================================ */

static int pg_dac_update(int pid, int value)
{
    /* Simulate DAC write for setpoint control (e.g., pump speed ref). */
    if (pid == PT_SETPOINT) {
        if (pg_validate_range(pid, value)) {
            point_history.setpoint_last = value;
            return 0;
        }
    }
    return -1;
}

/* ============================================================
 * Static Helper: Coil/Discrete Output Control
 * ============================================================ */

static int pg_discrete_write(int discrete_id, int state)
{
    /* Write discrete output (e.g., breaker open/close). */
    switch (discrete_id) {
    case 0x2001:  /* Feeder 1 Breaker */
    case 0x2002:  /* Feeder 2 Breaker */
        return (state) ? 1 : 0;
    default:
        return -1;
    }
}

/* ============================================================
 * Static Helper: Event Priority and Dispatcher
 * ============================================================ */

static int pg_event_priority(int alarm_code)
{
    /* Return alarm priority (0=low, 2=high). */
    switch (alarm_code) {
    case ALM_OVERTEMP:       return 2;  /* Critical */
    case ALM_OVERPRESSURE:   return 2;  /* Critical */
    case ALM_LOWLEVEL:       return 1;  /* Normal */
    default:                 return 0;
    }
}

/* ============================================================
 * Static Helper: Modbus/DNP3 Compatibility Wrapper
 * ============================================================ */

static int pg_modbus_read_registers(int slave_id, unsigned short start,
                                     unsigned short count, unsigned short *buf)
{
    int i;
    int raw_val = 0;

    for (i = 0; i < (int)count; i++) {
        if (pg_rtu_raw_read(slave_id, start + i, &raw_val) < 0) {
            return -1;
        }
        buf[i] = (unsigned short)raw_val;
    }
    return (int)count;
}

/* ============================================================
 * Static Helper: Historian Record Formatting
 * ============================================================ */

static HistRec pg_format_hist_record(int point_id, int timestamp, int value)
{
    HistRec rec;
    rec.archive_id = ARC_TREND;
    rec.stamp = timestamp;
    rec.value = value;
    return rec;
}

/* ============================================================
 * Static Helper: Trend Data Window (sliding buffer)
 * ============================================================ */

static struct {
    int values[32];
    int timestamps[32];
    int head;
    int count;
} trend_window = { {0}, {0}, 0, 0 };

static void pg_trend_add(int timestamp, int value)
{
    trend_window.timestamps[trend_window.head] = timestamp;
    trend_window.values[trend_window.head] = value;
    trend_window.head = (trend_window.head + 1) % 32;
    if (trend_window.count < 32) {
        trend_window.count++;
    }
}

static int pg_trend_slope(void)
{
    /* Simple slope calculation: (y1 - y0) / (t1 - t0). */
    if (trend_window.count < 2) return 0;

    int y0 = trend_window.values[0];
    int y1 = trend_window.values[trend_window.count - 1];
    int t0 = trend_window.timestamps[0];
    int t1 = trend_window.timestamps[trend_window.count - 1];
    int dt = t1 - t0;

    if (dt == 0) return 0;
    return (y1 - y0) / dt;
}

/* ============================================================
 * Static Helper: Rate-of-Change Detector
 * ============================================================ */

static int pg_detect_ramp_rate(int point_id, int current_value,
                                 int *last_value, int *last_time,
                                 int current_time, int threshold_per_sec)
{
    int time_delta = current_time - *last_time;
    int value_delta = current_value - *last_value;
    int rate;

    if (time_delta <= 0) return 0;

    rate = (value_delta * 1000) / time_delta;  /* per second */

    *last_value = current_value;
    *last_time = current_time;

    return (rate > threshold_per_sec) ? 1 : 0;
}

/* ============================================================
 * Static Helper: RTU CRC Error Recovery
 * ============================================================ */

static int pg_rtu_crc_error_count = 0;

static int pg_rtu_handle_crc_error(void)
{
    pg_rtu_crc_error_count++;
    rtu_status.crc_errors++;
    if (pg_rtu_crc_error_count >= 5) {
        rtu_status.link_ok = 0;
        pg_rtu_crc_error_count = 0;
        return -1;  /* Link down */
    }
    return 0;
}

static void pg_rtu_crc_reset(void)
{
    pg_rtu_crc_error_count = 0;
    rtu_status.link_ok = 1;
}

/* ============================================================
 * Static Helper: Modbus RTU Frame Timeout Handler
 * ============================================================ */

static struct {
    int tx_time;
    int timeout_threshold;
} rtu_timeout = { 0, RTU_TIMEOUT_MS };

static int pg_rtu_check_timeout(int current_time)
{
    if (current_time - rtu_timeout.tx_time > rtu_timeout.timeout_threshold) {
        return 1;  /* Timeout */
    }
    return 0;
}

/* ============================================================
 * Static Helper: Protocol Exception Handler
 * ============================================================ */

static int pg_frame_exception_code = 0;

static int pg_handle_exception(unsigned char exception_code)
{
    pg_frame_exception_code = exception_code;
    switch (exception_code) {
    case 0x01:  /* ILLEGAL FUNCTION */
    case 0x02:  /* ILLEGAL DATA ADDRESS */
    case 0x03:  /* ILLEGAL DATA VALUE */
    case 0x04:  /* DEVICE FAILURE */
        return -1;
    default:
        return 0;
    }
}

/* ============================================================
 * Static Helper: Scaling Lookup Table
 * ============================================================ */

typedef struct {
    int point_id;
    int scale_factor;
    int offset;
} ScaleLut;

static const ScaleLut scale_table[] = {
    { PT_PUMP_SPEED,   SCALE_PUMP_SPEED,   0 },
    { PT_VALVE_POS,    SCALE_VALVE_POS,    0 },
    { PT_TANK_LEVEL,   SCALE_TANK_LEVEL,   0 },
    { PT_FLOW_RATE,    SCALE_FLOW_RATE,    0 },
    { PT_MOTOR_TEMP,   SCALE_MOTOR_TEMP,   -400 },  /* Offset for Celsius */
    { PT_PRESSURE,     SCALE_PRESSURE,     0 },
};

static int pg_lookup_scale_factor(int point_id)
{
    int i;
    for (i = 0; i < 6; i++) {
        if (scale_table[i].point_id == point_id) {
            return scale_table[i].scale_factor;
        }
    }
    return SCALE_PUMP_SPEED;  /* Default */
}

/* ============================================================
 * Static Helper: Alarm Hysteresis State Machine
 * ============================================================ */

typedef struct {
    int alarm_id;
    int state;  /* 0=normal, 1=alarm_pending, 2=alarm_active */
    int setpoint_hi;
    int setpoint_lo;
    int hysteresis;
} AlarmHyst;

static AlarmHyst alarm_hysteresis[] = {
    { ALM_OVERTEMP,     0, 120, 110, 5 },
    { ALM_LOWLEVEL,     0, 20,  30,  2 },
    { ALM_OVERPRESSURE, 0, 500, 480, 10 },
};

static int pg_check_hysteresis(AlarmHyst *hyst, int current_value)
{
    switch (hyst->state) {
    case 0:  /* Normal */
        if (current_value > hyst->setpoint_hi) {
            hyst->state = 1;
            return 1;  /* Alarm */
        }
        break;
    case 1:  /* Pending */
    case 2:  /* Active */
        if (current_value < hyst->setpoint_lo) {
            hyst->state = 0;
            return 0;  /* Clear alarm */
        }
        hyst->state = 2;
        break;
    }
    return hyst->state;
}

/* ============================================================
 * Static Helper: Message Queue Wrapper
 * ============================================================ */

static int pg_msgq_enqueue(int queue_id, int msg_type, int msg_value)
{
    /* Prepare message struct and enqueue to framework. */
    struct {
        int type;
        int value;
    } msg = { msg_type, msg_value };

    return scf_msgq_write(queue_id, &msg);
}

/* ============================================================
 * Static Helper: Alarm Queue Management
 * ============================================================ */

static int pg_alarm_queue_depth(int queue_id)
{
    /* Simulate queue depth query. */
    if (queue_id == Q_ALARM_HI) {
        return 5;  /* Simulated depth */
    }
    return 0;
}

/* ============================================================
 * Static Helper: Scan Cycle Statistics
 * ============================================================ */

static struct {
    int total_scans;
    int errors;
    int skips;
    int last_scan_ms;
} scan_stats = { 0, 0, 0, 0 };

static void pg_stat_scan_complete(int duration_ms)
{
    scan_stats.total_scans++;
    scan_stats.last_scan_ms = duration_ms;
}

static void pg_stat_scan_error(void)
{
    scan_stats.errors++;
}

/* ============================================================
 * Static Helper: Parity/Checksum for ASCII Modbus
 * ============================================================ */

static unsigned char pg_lrc_checksum(unsigned char *buf, int len)
{
    unsigned char lrc = 0;
    int i;
    for (i = 0; i < len; i++) {
        lrc += buf[i];
    }
    return (256 - lrc) & 0xFF;
}

/* ============================================================
 * Static Helper: DNP3 Analog Input Mapping
 * ============================================================ */

static int pg_dnp3_g32_read(int group, int index, int *value)
{
    /* DNP3 Group 32 (32-bit analog input). */
    if (group == 32 && index >= 0 && index < 8) {
        *value = point_history.motor_temp_last + (index * 10);
        return 0;
    }
    return -1;
}

/* ============================================================
 * Static Helper: Coil Bit Packing/Unpacking
 * ============================================================ */

static int pg_pack_coils(unsigned char *buf, int count, int *coil_values)
{
    int i, byte_idx = 0, bit_idx = 0;

    for (i = 0; i < count; i++) {
        if (coil_values[i]) {
            buf[byte_idx] |= (1 << bit_idx);
        }
        bit_idx++;
        if (bit_idx == 8) {
            byte_idx++;
            bit_idx = 0;
        }
    }
    return byte_idx + ((bit_idx > 0) ? 1 : 0);
}

/* ============================================================
 * Static Helper: Point Snapshot (all analog at single instant)
 * ============================================================ */

static struct {
    int pump_speed;
    int valve_pos;
    int tank_level;
    int flow_rate;
    int motor_temp;
    int pressure;
    int setpoint;
    int snapshot_time;
} point_snapshot = {0, 0, 0, 0, 0, 0, 0, 0};

static void pg_snapshot_all_points(int timestamp)
{
    point_snapshot.pump_speed   = point_history.pump_speed_last;
    point_snapshot.valve_pos    = point_history.valve_pos_last;
    point_snapshot.tank_level   = point_history.tank_level_last;
    point_snapshot.flow_rate    = point_history.flow_rate_last;
    point_snapshot.motor_temp   = point_history.motor_temp_last;
    point_snapshot.pressure     = point_history.pressure_last;
    point_snapshot.setpoint     = point_history.setpoint_last;
    point_snapshot.snapshot_time = timestamp;
}

/* ============================================================
 * Static Helper: Rolling 24-hour Archive
 * ============================================================ */

static struct {
    int hourly_max[24];
    int hourly_min[24];
    int hourly_avg[24];
    int current_hour;
    int current_sum;
    int current_count;
} daily_archive = { {0}, {0}, {0}, 0, 0, 0 };

static void pg_daily_archive_update(int point_value)
{
    daily_archive.current_sum += point_value;
    daily_archive.current_count++;

    if (point_value > daily_archive.hourly_max[daily_archive.current_hour]) {
        daily_archive.hourly_max[daily_archive.current_hour] = point_value;
    }
    if (point_value < daily_archive.hourly_min[daily_archive.current_hour]) {
        daily_archive.hourly_min[daily_archive.current_hour] = point_value;
    }
}

static void pg_daily_archive_hourly_rollover(void)
{
    if (daily_archive.current_count > 0) {
        daily_archive.hourly_avg[daily_archive.current_hour] =
            daily_archive.current_sum / daily_archive.current_count;
    }
    daily_archive.current_hour = (daily_archive.current_hour + 1) % 24;
    daily_archive.current_sum = 0;
    daily_archive.current_count = 0;
    daily_archive.hourly_max[daily_archive.current_hour] = -999999;
    daily_archive.hourly_min[daily_archive.current_hour] = 999999;
}

/* ============================================================
 * Static Helper: Maintenance Flag Tracking
 * ============================================================ */

static struct {
    int calibration_due;
    int battery_low;
    int memory_low;
    int last_maintenance;
} maint_flags = { 0, 0, 0, 0 };

static void pg_check_maintenance(void)
{
    if (rtu_status.crc_errors > 100) {
        maint_flags.calibration_due = 1;
    }
}

/* ============================================================
 * Static Helper: Version and Serial Number
 * ============================================================ */

static const char pg_firmware_version[] = "v2.1.4";
static const char pg_device_serial[] = "SN-RTU-00421";
static const int pg_protocol_version = 65;  /* 6.5 */

/* ============================================================
 * Static Helper: Advanced Load Sharing Logic (isochronous)
 * ============================================================ */

typedef struct {
    int feeder_id;
    int assigned_kw;
    int actual_kw;
    int droop_percent;
} LoadShareUnit;

static LoadShareUnit load_share_table[4] = {
    { 1, 100, 95, 5 },
    { 2, 100, 105, 5 },
    { 3, 150, 148, 4 },
    { 4, 150, 152, 4 },
};

static int pg_compute_load_sharing(void)
{
    /* Simulated droop generator load sharing. */
    int total_load = 0;
    int i, delta;
    for (i = 0; i < 4; i++) {
        total_load += load_share_table[i].actual_kw;
    }

    for (i = 0; i < 4; i++) {
        delta = load_share_table[i].actual_kw - load_share_table[i].assigned_kw;
        if (delta > 10) {
            load_share_table[i].assigned_kw += 5;
        } else if (delta < -10) {
            load_share_table[i].assigned_kw -= 5;
        }
    }

    return total_load;
}

/* ============================================================
 * Static Helper: Automatic Voltage Regulation (AVR)
 * ============================================================ */

static struct {
    int setpoint_volts;
    int measured_volts;
    int tap_position;
    int tap_delay_ms;
} avr_control = { 115, 114, 5, 0 };

static int pg_avr_compute_tap_change(void)
{
    int voltage_error = avr_control.setpoint_volts - avr_control.measured_volts;
    int new_tap = avr_control.tap_position;

    if (voltage_error > 2) {
        new_tap = (new_tap < 15) ? new_tap + 1 : 15;
    } else if (voltage_error < -2) {
        new_tap = (new_tap > 0) ? new_tap - 1 : 0;
    }

    if (new_tap != avr_control.tap_position) {
        avr_control.tap_delay_ms = 100;  /* Delay before next change */
        return new_tap;
    }
    return -1;  /* No change needed */
}

/* ============================================================
 * Static Helper: Breaker Coordination (fuse blowing precedence)
 * ============================================================ */

typedef struct {
    int breaker_id;
    int pickup_amps;
    int time_delay_ms;
    int trip_flag;
} BreakerChar;

static BreakerChar breaker_curves[] = {
    { 1, 1000, 100, 0 },
    { 2, 800,  150, 0 },
    { 3, 600,  200, 0 },
};

static int pg_breaker_coordination_check(int current_amps)
{
    int i;
    for (i = 0; i < 3; i++) {
        if (current_amps > breaker_curves[i].pickup_amps) {
            breaker_curves[i].time_delay_ms -= 10;
            if (breaker_curves[i].time_delay_ms <= 0) {
                breaker_curves[i].trip_flag = 1;
                return breaker_curves[i].breaker_id;
            }
        }
    }
    return 0;  /* No trip */
}

/* ============================================================
 * Static Helper: Reactive Power / Power Factor Monitoring
 * ============================================================ */

static struct {
    int real_power_kw;
    int reactive_power_kvar;
    int power_factor_x1000;
    int leading_flag;
} power_calc = { 0, 0, 1000, 0 };

static void pg_calculate_power_factor(int kw, int kvar)
{
    int apparent_power;
    power_calc.real_power_kw = kw;
    power_calc.reactive_power_kvar = kvar;

    if (kw == 0) {
        power_calc.power_factor_x1000 = 0;
        return;
    }

    apparent_power = (kw * kw + kvar * kvar) / kw;  /* Simplified */
    if (apparent_power > 0) {
        power_calc.power_factor_x1000 = (kw * 1000) / apparent_power;
    }
    power_calc.leading_flag = (kvar < 0) ? 1 : 0;
}

/* ============================================================
 * Static Helper: Demand Response Shed Logic
 * ============================================================ */

typedef struct {
    int load_id;
    int priority;
    int state;  /* 0=online, 1=shed */
    int max_duration_sec;
} ControllableLoad;

static ControllableLoad shed_table[6] = {
    { 1, 3, 0, 300 },  /* Low priority, 5 min max */
    { 2, 2, 0, 600 },  /* Medium priority */
    { 3, 1, 0, 900 },  /* High priority */
    { 4, 3, 0, 300 },
    { 5, 2, 0, 600 },
    { 6, 1, 0, 900 },
};

static int pg_demand_response_shed(int total_kw, int target_kw)
{
    int deficit_kw = total_kw - target_kw;
    int shed_count = 0;
    int i;

    if (deficit_kw <= 0) return 0;

    /* Shed loads in priority order (lowest priority first). */
    for (i = 0; i < 6; i++) {
        if (shed_table[i].priority == 3 && shed_table[i].state == 0) {
            shed_table[i].state = 1;
            shed_count++;
            deficit_kw -= 50;  /* Assume 50 kW per load */
            if (deficit_kw <= 0) break;
        }
    }

    return shed_count;
}

/* ============================================================
 * Static Helper: Event Audit Trail
 * ============================================================ */

typedef struct {
    int timestamp;
    int event_type;
    int user_id;
    int point_id;
    int old_value;
    int new_value;
} AuditRecord;

static struct {
    AuditRecord records[64];
    int write_ptr;
    int count;
} audit_log = { {0}, 0, 0 };

static void pg_audit_log_event(int timestamp, int evt_type, int user_id,
                                int pt_id, int old_val, int new_val)
{
    int idx = audit_log.write_ptr;
    audit_log.records[idx].timestamp = timestamp;
    audit_log.records[idx].event_type = evt_type;
    audit_log.records[idx].user_id = user_id;
    audit_log.records[idx].point_id = pt_id;
    audit_log.records[idx].old_value = old_val;
    audit_log.records[idx].new_value = new_val;

    audit_log.write_ptr = (audit_log.write_ptr + 1) % 64;
    if (audit_log.count < 64) {
        audit_log.count++;
    }
}

/* ============================================================
 * Static Helper: Historian Compression (delta-of-deltas)
 * ============================================================ */

static struct {
    int last_value;
    int last_delta;
} compression_state = { 0, 0 };

static int pg_compress_value(int raw_value)
{
    int delta = raw_value - compression_state.last_value;
    int delta_delta = delta - compression_state.last_delta;

    compression_state.last_value = raw_value;
    compression_state.last_delta = delta;

    return delta_delta;  /* Compressed representation */
}

/* ============================================================
 * Static Helper: Sequence of Events (SOE) Timestamp Buffering
 * ============================================================ */

typedef struct {
    unsigned int timestamp;
    int point_id;
    int state_change;  /* 0->1 or 1->0 */
} SoeRecord;

static struct {
    SoeRecord records[256];
    int write_ptr;
    int count;
} soe_buffer = { {0}, 0, 0 };

static void pg_soe_record_event(unsigned int timestamp, int pt_id, int state)
{
    int idx = soe_buffer.write_ptr;
    soe_buffer.records[idx].timestamp = timestamp;
    soe_buffer.records[idx].point_id = pt_id;
    soe_buffer.records[idx].state_change = state;

    soe_buffer.write_ptr = (soe_buffer.write_ptr + 1) % 256;
    if (soe_buffer.count < 256) {
        soe_buffer.count++;
    }
}

/* ============================================================
 * Static Helper: Configuration Validation
 * ============================================================ */

static int pg_validate_config_crc(void)
{
    /* Simulate configuration integrity check. */
    return 0;  /* CRC OK */
}

static int pg_validate_config_limits(void)
{
    /* Check alarm setpoints are in valid ranges. */
    if (alarm_hysteresis[0].setpoint_hi > 150) return -1;
    if (alarm_hysteresis[1].setpoint_lo < 5) return -1;
    return 0;
}

/* ============================================================
 * Static Helper: Historical Trending Analysis
 * ============================================================ */

static int pg_analyze_trend_spike(int *trend_values, int count)
{
    int i, mean = 0, variance = 0;
    int threshold;

    if (count < 3) return -1;

    for (i = 0; i < count; i++) {
        mean += trend_values[i];
    }
    mean /= count;

    for (i = 0; i < count; i++) {
        int dev = trend_values[i] - mean;
        variance += (dev * dev);
    }
    variance /= count;

    /* Spike if last value deviates > 2 sigma. */
    threshold = (2 * variance) / 10;  /* Simplified sqrt */
    if ((trend_values[count - 1] - mean) > threshold) {
        return 1;  /* Spike detected */
    }

    return 0;
}

/* ============================================================
 * Static Helper: Operator Command Validation
 * ============================================================ */

static int pg_validate_operator_cmd(int cmd_code, int user_privilege)
{
    /* Check if user has privilege for this command. */
    switch (cmd_code) {
    case 0x0001:  /* Breaker trip */
    case 0x0002:  /* Breaker close */
    case 0x0003:  /* Setpoint adjust */
        if (user_privilege >= 2) return 1;
        break;
    case 0x0100:  /* Read only */
        if (user_privilege >= 1) return 1;
        break;
    }
    return 0;
}

/* ============================================================
 * Static Helper: Phase Loss Detection (3-phase systems)
 * ============================================================ */

static struct {
    int phase_a_volts;
    int phase_b_volts;
    int phase_c_volts;
    int phase_loss_flag;
} phase_volts = { 120, 120, 120, 0 };

static int pg_detect_phase_loss(void)
{
    int min_volt = phase_volts.phase_a_volts;
    int max_volt = phase_volts.phase_a_volts;

    if (phase_volts.phase_b_volts < min_volt) min_volt = phase_volts.phase_b_volts;
    if (phase_volts.phase_c_volts < min_volt) min_volt = phase_volts.phase_c_volts;
    if (phase_volts.phase_b_volts > max_volt) max_volt = phase_volts.phase_b_volts;
    if (phase_volts.phase_c_volts > max_volt) max_volt = phase_volts.phase_c_volts;

    if (max_volt - min_volt > 30) {  /* >30V imbalance */
        phase_volts.phase_loss_flag = 1;
        return -1;
    } else {
        phase_volts.phase_loss_flag = 0;
    }
    return 0;
}

/* ============================================================
 * Static Helper: Frequency Deviation Monitoring (50/60 Hz)
 * ============================================================ */

static struct {
    int frequency_hz_x100;  /* e.g., 6000 = 60.00 Hz */
    int roc_hz_per_sec_x100;
} freq_monitor = { 6000, 0 };

static int pg_check_frequency_deviation(void)
{
    if (freq_monitor.frequency_hz_x100 < 5900 ||
        freq_monitor.frequency_hz_x100 > 6100) {
        return -1;  /* Outside 59.0-61.0 Hz */
    }
    if (freq_monitor.roc_hz_per_sec_x100 > 500) {
        return -2;  /* Rate of change > 5 Hz/sec */
    }
    return 0;
}

/* ============================================================
 * Static Helper: Configuration Persistence
 * ============================================================ */

static int pg_load_config_from_nvram(int config_id)
{
    scf_cfg_clear(config_id);
    return 0;
}

static int pg_save_config_to_nvram(int config_id, void *cfg_data)
{
    (void)config_id;
    (void)cfg_data;
    return 0;  /* Simulated save */
}

/* ============================================================
 * Static Helper: Tag Copy with Type Verification
 * ============================================================ */

static int pg_tag_copy_verified(int src_id, int dst_id)
{
    if (pg_validate_range(src_id, 0) && pg_validate_range(dst_id, 0)) {
        return scf_tag_copy(src_id, dst_id);
    }
    return -1;
}

/* ============================================================
 * Static Helper: SCADA Protocol Diagnostics
 * ============================================================ */

static struct {
    int frames_sent;
    int frames_received;
    int frames_rejected;
    int bytes_transmitted;
    int bytes_received;
    int last_transaction_time;
} link_stats = { 0, 0, 0, 0, 0, 0 };

static void pg_record_frame_stats(int tx_len, int rx_len, int success)
{
    link_stats.frames_sent++;
    link_stats.bytes_transmitted += tx_len;

    if (success) {
        link_stats.frames_received++;
        link_stats.bytes_received += rx_len;
    } else {
        link_stats.frames_rejected++;
    }
}

/* ============================================================
 * Static Helper: Network Time Synchronization (SNTP-like)
 * ============================================================ */

static struct {
    unsigned int system_time_sec;
    unsigned int ntp_offset_sec;
    unsigned int last_sync_sec;
    int sync_valid;
} time_sync = { 0, 0, 0, 0 };

static int pg_sync_time_with_master(unsigned int master_time)
{
    unsigned int drift = (master_time > time_sync.system_time_sec) ?
                         (master_time - time_sync.system_time_sec) :
                         (time_sync.system_time_sec - master_time);

    if (drift > 5) {  /* > 5 sec drift */
        time_sync.ntp_offset_sec = master_time - time_sync.system_time_sec;
        time_sync.last_sync_sec = master_time;
        return 1;  /* Sync applied */
    }
    return 0;  /* In sync */
}

/* ============================================================
 * Static Helper: Remote Terminal Unit (RTU) Initialization
 * ============================================================ */

static int pg_rtu_init_sequence(int slave_id)
{
    /* Modeled after IEC 60870-5-104 startup sequence. */
    int result = 0;

    rtu_status.slave_id = slave_id;
    rtu_status.link_ok = 0;

    /* Send STARTDT ACT (start data transmission activate). */
    result = pg_frame_build_read_coil(slave_id, 0x0000, 1);
    if (result < 0) return -1;

    /* Poll for response (STARTDT CON). */
    rtu_frame.rx_len = 6;
    result = pg_frame_parse_response(NULL, &result);
    if (result < 0) return -2;

    rtu_status.link_ok = 1;
    return 0;
}

/* ============================================================
 * Static Helper: Database Archive Rotation
 * ============================================================ */

static struct {
    int current_file_id;
    int records_written;
    int max_records_per_file;
    unsigned int file_open_time;
} archive_mgmt = { 1, 0, 10000, 0 };

static int pg_archive_file_rollover(void)
{
    if (archive_mgmt.records_written >= archive_mgmt.max_records_per_file) {
        archive_mgmt.current_file_id++;
        archive_mgmt.records_written = 0;
        archive_mgmt.file_open_time = 0;
        return archive_mgmt.current_file_id;
    }
    return archive_mgmt.current_file_id;
}

static void pg_archive_record_written(void)
{
    archive_mgmt.records_written++;
}

/* ============================================================
 * Static Helper: User Authentication / Authorization
 * ============================================================ */

typedef struct {
    int user_id;
    int privilege_level;  /* 0=view, 1=control, 2=admin */
    int session_active;
    unsigned int login_time;
} UserSession;

static UserSession active_sessions[8] = { {0} };

static int pg_user_login(int user_id, int privilege)
{
    int i;
    for (i = 0; i < 8; i++) {
        if (!active_sessions[i].session_active) {
            active_sessions[i].user_id = user_id;
            active_sessions[i].privilege_level = privilege;
            active_sessions[i].session_active = 1;
            return i;
        }
    }
    return -1;  /* No free session slots */
}

static int pg_user_logout(int session_id)
{
    if (session_id >= 0 && session_id < 8) {
        active_sessions[session_id].session_active = 0;
        return 0;
    }
    return -1;
}

/* ============================================================
 * Static Helper: Cyclic Redundancy Check Variants
 * ============================================================ */

static unsigned int pg_crc32_ethernet(unsigned char *data, int len)
{
    unsigned int crc = 0xFFFFFFFF;
    int i, j;

    for (i = 0; i < len; i++) {
        crc ^= data[i];
        for (j = 0; j < 8; j++) {
            crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320 : 0);
        }
    }

    return crc ^ 0xFFFFFFFF;
}

/* ============================================================
 * Static Helper: Protocol State Machine (Mealy)
 * ============================================================ */

typedef enum {
    STATE_IDLE,
    STATE_CONNECTING,
    STATE_CONNECTED,
    STATE_REQUESTING,
    STATE_RECEIVING,
    STATE_PROCESSING,
    STATE_ERROR,
    STATE_OFFLINE,
} ProtocolState;

static struct {
    ProtocolState current_state;
    ProtocolState next_state;
    int state_enter_count;
    int state_timeout_ms;
} protocol_fsm = {
    STATE_IDLE, STATE_IDLE, 0, 5000
};

static void pg_protocol_state_transition(ProtocolState new_state)
{
    if (new_state != protocol_fsm.current_state) {
        protocol_fsm.current_state = new_state;
        protocol_fsm.state_enter_count = 0;
        protocol_fsm.state_timeout_ms = 5000;
    }
    protocol_fsm.state_enter_count++;
}

/* ============================================================
 * Static Helper: Analog Ramp Generator (for setpoint profiles)
 * ============================================================ */

static struct {
    int start_value;
    int end_value;
    int current_value;
    int ramp_rate;  /* units per sec */
    int active;
} ramp_generator = { 0, 0, 0, 10, 0 };

static int pg_ramp_generator_tick(int delta_ms)
{
    int step;

    if (!ramp_generator.active) return ramp_generator.current_value;

    step = (ramp_generator.ramp_rate * delta_ms) / 1000;

    if (ramp_generator.current_value < ramp_generator.end_value) {
        ramp_generator.current_value += step;
        if (ramp_generator.current_value >= ramp_generator.end_value) {
            ramp_generator.current_value = ramp_generator.end_value;
            ramp_generator.active = 0;
        }
    } else if (ramp_generator.current_value > ramp_generator.end_value) {
        ramp_generator.current_value -= step;
        if (ramp_generator.current_value <= ramp_generator.end_value) {
            ramp_generator.current_value = ramp_generator.end_value;
            ramp_generator.active = 0;
        }
    }

    return ramp_generator.current_value;
}

/* ============================================================
 * Static Helper: Pulse Counter / Event Counter
 * ============================================================ */

static struct {
    unsigned int pulse_count;
    unsigned int event_count;
    unsigned int last_pulse_time;
    unsigned int pulse_frequency;
} counter_data = { 0, 0, 0, 0 };

static void pg_record_pulse(unsigned int timestamp)
{
    unsigned int time_delta = timestamp - counter_data.last_pulse_time;
    counter_data.pulse_count++;

    if (time_delta > 0) {
        counter_data.pulse_frequency = 1000 / time_delta;  /* Hz */
    }
    counter_data.last_pulse_time = timestamp;
}

/* ============================================================
 * Static Helper: Min/Max/Mean Trending
 * ============================================================ */

static struct {
    int min_value;
    int max_value;
    int sum_values;
    int count_samples;
    int mean_value;
} mmm_stats = { 999999, -999999, 0, 0, 0 };

static void pg_mmm_update(int value)
{
    if (value < mmm_stats.min_value) {
        mmm_stats.min_value = value;
    }
    if (value > mmm_stats.max_value) {
        mmm_stats.max_value = value;
    }
    mmm_stats.sum_values += value;
    mmm_stats.count_samples++;

    if (mmm_stats.count_samples > 0) {
        mmm_stats.mean_value = mmm_stats.sum_values / mmm_stats.count_samples;
    }
}

static void pg_mmm_reset(void)
{
    mmm_stats.min_value = 999999;
    mmm_stats.max_value = -999999;
    mmm_stats.sum_values = 0;
    mmm_stats.count_samples = 0;
    mmm_stats.mean_value = 0;
}

/* ============================================================
 * Static Helper: Boolean Pulse Output (relay simulation)
 * ============================================================ */

typedef struct {
    int output_id;
    int state;
    int pulse_width_ms;
    int pulse_remaining_ms;
} PulseOutput;

static PulseOutput pulse_outputs[4] = { {0} };

static int pg_pulse_output_set(int output_id, int pulse_ms)
{
    if (output_id >= 0 && output_id < 4) {
        pulse_outputs[output_id].output_id = output_id;
        pulse_outputs[output_id].state = 1;
        pulse_outputs[output_id].pulse_width_ms = pulse_ms;
        pulse_outputs[output_id].pulse_remaining_ms = pulse_ms;
        return 0;
    }
    return -1;
}

/* ============================================================
 * Static Helper: Hardware Watchdog Kick
 * ============================================================ */

static struct {
    unsigned int last_kick_time;
    unsigned int watchdog_timeout_ms;
    int triggered;
} watchdog_hw = { 0, 10000, 0 };

static int pg_watchdog_kick(unsigned int current_time)
{
    watchdog_hw.last_kick_time = current_time;
    watchdog_hw.triggered = 0;
    return 0;
}

static int pg_watchdog_check(unsigned int current_time)
{
    if ((current_time - watchdog_hw.last_kick_time) > watchdog_hw.watchdog_timeout_ms) {
        watchdog_hw.triggered = 1;
        return -1;  /* Watchdog timeout */
    }
    return 0;
}

/* ============================================================
 * Static Helper: LED Indicator State Machine
 * ============================================================ */

static struct {
    int status_led_state;  /* 0=off, 1=on, 2=blink */
    int alarm_led_state;
    int blink_counter;
} led_indicators = { 0, 0, 0 };

static void pg_update_leds(void)
{
    if (rtu_status.link_ok) {
        led_indicators.status_led_state = 1;
    } else {
        led_indicators.status_led_state = 2;  /* Blinking */
    }

    if (pg_alarm_queue_depth(Q_ALARM_HI) > 0) {
        led_indicators.alarm_led_state = 2;  /* Blinking alarm */
    } else {
        led_indicators.alarm_led_state = 0;
    }

    led_indicators.blink_counter = (led_indicators.blink_counter + 1) % 100;
}

/* ============================================================
 * Static Helper: Test/Calibration Mode
 * ============================================================ */

static struct {
    int test_mode_active;
    int cal_inject_value;
    int cal_point_id;
} test_cal_mode = { 0, 0, 0 };

static int pg_enable_test_mode(void)
{
    test_cal_mode.test_mode_active = 1;
    return 0;
}

static int pg_disable_test_mode(void)
{
    test_cal_mode.test_mode_active = 0;
    test_cal_mode.cal_point_id = 0;
    test_cal_mode.cal_inject_value = 0;
    return 0;
}

/* ============================================================
 * END OF FILE
 * ============================================================ */

#ifndef SCF_CONST_H
#define SCF_CONST_H

/* ============================================================
 * SCF constant macros (object-like, numeric => resolvable by
 * the backward tracer). Defined in a header so the call-graph
 * macro collector (which only reads .h files) can see them.
 * ============================================================ */

/* --- Tag / point IDs -------------------------------------- */
#define PT_PUMP_SPEED     0x1001
#define PT_VALVE_POS      0x1002
#define PT_TANK_LEVEL     0x1003
#define PT_FLOW_RATE      0x1004
#define PT_MOTOR_TEMP     0x1005
#define PT_PRESSURE       0x1006
#define PT_SETPOINT       0x1007

/* --- History / archive IDs -------------------------------- */
#define ARC_TREND         200
#define ARC_EVENTLOG      201
#define ARC_AUDIT         202

/* --- Config IDs ------------------------------------------- */
#define CFG_SCAN          300
#define CFG_ALARM         301

/* --- Queue IDs -------------------------------------------- */
#define Q_ALARM_HI        10
#define Q_ALARM_LO        11
#define Q_CMD             12
#define Q_MSG             13

/* --- Event numbers (become call_number via scf_evt_post /
 *     scf_var_evt 1st argument) --------------------------- */
#define EVT_STARTUP       3000
#define EVT_SCAN_CYCLE    3001
#define EVT_ALARM_RAISED  3002
#define EVT_VALVE_CMD     3003
#define EVT_SHUTDOWN      3004
#define EVT_HIST_FLUSH    3005

/* --- Timer / task / channel IDs --------------------------- */
#define TMR_SCAN          50
#define TMR_WATCHDOG      51
#define TASK_HIST         60
#define TASK_ALARM        61
#define CHAN_KEYPAD       70
#define SIG_FAULT         71
#define SEM_DBLOCK        80

/* --- Alarm codes ------------------------------------------ */
#define ALM_OVERTEMP      0x0901
#define ALM_LOWLEVEL      0x0902
#define ALM_OVERPRESSURE  0x0903

/* --- Lock / open modes ------------------------------------ */
#define SCF_NO_LOCK       0
#define SCF_READ_LOCK     1
#define SCF_WRITE_LOCK    2

#endif /* SCF_CONST_H */

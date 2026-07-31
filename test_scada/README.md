# `test_scada` — synthetic SCADA test project for the static tracer

A hand-built, multi-file C process that exercises the tracer end to end
(`makefile_resolver → extract_includes → Preprocess → call_graph →
parser_files → project_aware`). Every traced call has a documented, verifiable
ground truth so the tracer's output can be checked.

All C compiles clean under `gcc -std=c99 -fsyntax-only -Iheaders`. All JSON is
valid. Every global function is defined exactly once; every traced API has at
least one direct call-site.

## The invented API (SCF — "SCADA Control Framework")

Prototypes in `headers/`, inert stub bodies in `lib/scf_stubs.c`.

- **Tag/file class** (`scf_tag.h`): `scf_tag_open` (OPENF), `scf_tag_read`
  (READF), `scf_tag_write` (WRITEF), `scf_tag_close` (CLOSEF), `scf_tag_copy`
  (COPYF), `scf_hist_save` (SAVEF), `scf_hist_load` (LOADF, returns a pointer →
  used for the return-value READ/WRITE test), `scf_cfg_clear` (CLEARF).
- **Queue class** (`scf_queue.h`): `scf_alarmq_enq` (ENQ), `scf_alarmq_deq`
  (DEQ), `scf_msgq_write` (WRITEQ), `scf_msgq_read` (READQ), `scf_cmdq_save`
  (SAVEQ), `scf_cmdq_load` (LOADQ), `scf_cmdq_clear` (CLEARQ).
- **Event/process class** (`scf_event.h`): `scf_evt_post`, `scf_var_evt`
  (call_number sources), `scf_evt_register` (EVENT), `scf_timer_start` (TIMER),
  `scf_task_fork` (FORK), `scf_signal_hook` (SIGNAL), `scf_input_bind` (INPUT)
  as callback registrars, plus `scf_sem_wait` (SEMAPHORE), `scf_task_kill`
  (KILL).
- **Flowing macros** (headers): `TAG_OPEN_RD`, `TAG_SNAPSHOT`, `HIST_TREND`,
  `RAISE_ALARM` (single-level, followed) and `MF_ZERO`, `MF_SET2` (followed) /
  `MF_SET` (chained, deliberately only followed one hop).

The three config files under `json_data/` (`mpf_data.json`,
`function_callback_info.json`, `combined_data.json`) map to the pipeline's
`FUNCTION_TYPES`, `FUNCTION_POINTER_ARGS`, and `FUNCTION_MAP`. Point the loader
at this folder (or copy them into the repo's `json_data/`) and run
`project_aware.py` against this project's `Makefile`.

## Files and what each one tests

| File | Patterns exercised |
| --- | --- |
| `src/main.c` | entry point; **indirect event-listener wiring** — registers handlers via `scf_evt_register`/`scf_timer_start`/`scf_task_fork`/`scf_input_bind` (EVENT/TIMER/FORK/INPUT launches); direct `scf_evt_post` (call_number 3000); `scf_sem_wait`; cross-file value flow into `DioGetPtr`. |
| `src/dio_layer.c` | pointer-getter layer; **`/*CONSIDER THIS CALL*/` call-site selection** among 3 `scf_tag_open` calls; parameter flow `fno → arg2`; macro-expanded siblings (`TAG_OPEN_RD`, `TAG_SNAPSHOT` with leading-arg injection). |
| `src/scan_proc.c` | reached via EVENT listener; value flow through parameters into `scf_tag_read`; `call_number` (3001) from an in-handler `scf_evt_post`; literal-arg `scf_tag_write`. |
| `src/alarm_proc.c` | reached via EVENT listener; queue ops; **`RAISE_ALARM` macro injecting the queue id**; `call_number` (3002) from `scf_var_evt`; `WRITEQ`/`MESSAGE` launch. |
| `src/hist_proc.c` | reached via **FORK** (`scf_task_fork`); `HIST_TREND` macro injection; annotated direct `scf_hist_save`; **return-value classification** (`get_upper=false`) — `scf_hist_load`'s pointer is written through ⇒ WRITE; `call_number` 3005. |
| `src/macro_flow.c` | **macro flow across the project**: single-level macro followed to `scf_tag_write`; **chained macro `MF_SET→MF_SET2` stops after one hop** (limitation demo); literal `COPYF`; `LOADQ`. |
| `src/edge_cases.c` | 9 edge cases: valid direct edge, function-pointer call, struct-field call, ternary-selected callee (all `indirect_call`), `&Handler` callback (**not followed**), bare-id callback (**followed but duplicated**), **K&R old-style def**, recursion, and an **UNRESOLVED** argument from an undefined external. |

## Consolidated expected results (ground truth)

Each source file also carries its own `GROUND TRUTH` comment block. Highlights:

| Target call | Path (abbrev.) | type | launch_via | resolved args | call_number |
| --- | --- | --- | --- | --- | --- |
| `scf_tag_open` | main→init_subsystems→DioGetPtr | OPENF | FORK | arg2 = PT_TANK_LEVEL (0x1003) | — |
| `scf_cfg_clear` | main→init_subsystems | CLEARF | FORK | arg1 = CFG_SCAN (300) | — |
| `scf_sem_wait` | main→init_subsystems | SEMAPHORE | SEMAPHORE | arg1 = SEM_DBLOCK (80) | — |
| `scf_task_kill` | main→(TIMER)tick_watchdog | KILL | TIMER | arg1 = TASK_ALARM (61) | — |
| `scf_tag_read` | main→(EVENT)on_scan_cycle→read_all_points→read_one_point | READF | EVENT | arg2 = PT_FLOW_RATE (0x1004) | 3001 |
| `scf_tag_write` | …read_one_point | WRITEF | EVENT | arg2 = PT_SETPOINT (0x1007), arg3 = 100 | 3001 |
| `scf_alarmq_enq` | main→(EVENT)on_alarm→alarm_dispatch→RAISE_ALARM | ENQ | EVENT | arg1 = Q_ALARM_HI (10, injected), arg2 = ALM_OVERTEMP (0x0901) | 3002 |
| `scf_msgq_write` | …alarm_dispatch | WRITEQ | MESSAGE | arg1 = Q_MSG (13) | 3002 |
| `scf_hist_save` | main→(FORK)hist_task_entry→flush_history | SAVEF | FORK | arg1 = ARC_TREND (200) | 3005 |
| `scf_hist_load` | …flush_history | WRITE (return-use) | FORK | arg1 = ARC_AUDIT (202) | 3005 |
| `scf_cmdq_save` | …flush_history | SAVEQ | FORK | arg1 = Q_CMD (12) | 3005 |
| `scf_tag_write` | main→mf_apply_config→mf_write_setpoint | WRITEF | FORK | arg2 = PT_SETPOINT (0x1007), arg3 = 42 | — |
| `scf_tag_copy` | main→mf_apply_config | COPYF | FORK | arg1 = PT_PUMP_SPEED (0x1001), arg2 = PT_SETPOINT (0x1007) | — |
| `scf_tag_close` | main→ec_run (and via SIGNAL→ec_fault_sig, **duplicated**) | CLOSEF | FORK / SIGNAL | — | — |
| `scf_tag_read` | main→ec_run→ec_knr (K&R) | READF | FORK | arg2 = PT_TANK_LEVEL (0x1003) | — |
| `scf_alarmq_enq` | main→ec_run | ENQ | FORK | arg1 = Q_CMD (12), **arg2 = UNRESOLVED** | — |

Known-limitation demos (should NOT produce resolved edges): `edge_cases.c`
patterns 2–5 (function pointer / struct field / ternary / `&Handler`) and
`macro_flow.c`'s chained `MF_SET`.

---

# Full multi-process suite — `processes/`

`src/` above is a **compact pattern-reference process**. `processes/` holds
**6 independent, full-size SCADA processes**, each its own program: a `Makefile`,
a `main.c`, and 2 large control modules (1000–2600 lines each). They all reuse
the shared SCF API (`headers/`, `lib/scf_stubs.c`, `json_data/`) — the realistic
"one framework, many processes" model. Total ~23,000 lines of C.

All 18 module files compile clean under `gcc -std=c99 -fsyntax-only -I. -I../../headers`,
and every process links (exactly one `main`, no duplicate globals). Each file
carries its own `GROUND TRUTH` block; the per-process contract header
(`<prefix>_app.h`) is the authoritative symbol table + traced-call spec.

| Process | Files (lines) | Emphasis / tracer patterns |
| --- | --- | --- |
| `proc_waterworks` (ww_) | main 385, ww_control 1546, ww_alarm 1398 | event-listener wiring; `/*CONSIDER THIS CALL*/` selection; TAG_SNAPSHOT/HIST_TREND/RAISE_ALARM macro flow; FORK historian; cross-module control→alarm |
| `proc_powergrid` (pg_) | main 313, pg_telemetry 2276, pg_dispatch 1438 | RTU pointer-getter call-site selection; **indirect_call edge cases** (struct fn-ptr driver table + local fn-ptr); **UNRESOLVED** arg via `pg_ext_comm_value()`; TIMER poll; EVENT dispatch |
| `proc_pipeline` (pl_) | main 398, pl_flow 2296, pl_leak 1650 | **chained-macro limitation** (`MF_SET`); **return-value classification** (`scf_hist_load` → WRITE, get_upper=false); MESSAGE queue; leak state machine |
| `proc_hvac` (hv_) | main 377, hv_zones 1692, hv_sched 1646 | **heavy macro flow** via process-local `hv_macros.h` (HV_READ/HV_SET_TEMP/HV_ZERO/HV_CLEAR); config load/clear; TIMER schedules |
| `proc_railyard` (ry_) | main 297, ry_interlock 1766, ry_route 1690 | SEMAPHORE interlocks; **SIGNAL-hook callback**; full command-queue lifecycle (ENQ/DEQ/SAVEQ/LOADQ/CLEARQ); KILL/FORK |
| `proc_boiler` (bo_) | main 373, bo_combust 1867, bo_safety 1625 | **deep 6-hop call chain** (bo_stage1→…→bo_stage6, pid flows unchanged); call-site selection; return-value READ classification; **broken `&Handler` callback** edge case |

## Running the tracer against a process

1. Point the config loader at `test_scada/json_data/` (or copy those three JSON
   files into the repo's `json_data/`) — they define the SCF API detection.
2. Run `project_aware.py` against a process's `Makefile`, e.g.
   `processes/proc_boiler/Makefile`. The resolver picks up `SRCS` (main + 2
   modules), `INCLUDE` (`-I. -I../../headers`), and `LIBS`
   (`../../lib/scf_stubs.c`).
3. Compare the tracer's per-path output against that process's `GROUND TRUTH`
   comment blocks and its `<prefix>_app.h` spec.

Each process is analyzed independently, so global function names only need to be
unique within a process (they are).

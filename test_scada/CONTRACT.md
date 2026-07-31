# SCADA test-process authoring contract

You are writing ONE C file for a synthetic SCADA (Supervisory Control And Data
Acquisition) control process. Many files are written in parallel by different
authors; this contract is what keeps them consistent and analyzable by the
static tracer in this repository. Follow it exactly.

Read these headers before writing (they ARE the API — do not invent new API
functions): `headers/scf_const.h`, `headers/scf_types.h`, `headers/scf_tag.h`,
`headers/scf_queue.h`, `headers/scf_event.h`, `headers/app.h`.

## The framework API (call these; never redefine them)

- **Tag/file ops** (`scf_tag.h`): `scf_tag_open, scf_tag_read, scf_tag_write,
  scf_tag_close, scf_tag_copy, scf_hist_save, scf_hist_load, scf_cfg_clear`.
- **Queue ops** (`scf_queue.h`): `scf_alarmq_enq, scf_alarmq_deq, scf_msgq_write,
  scf_msgq_read, scf_cmdq_save, scf_cmdq_load, scf_cmdq_clear`.
- **Event/process** (`scf_event.h`): `scf_evt_post, scf_var_evt` (call_number
  sources), `scf_evt_register, scf_timer_start, scf_task_fork, scf_signal_hook,
  scf_input_bind` (callback registrars), `scf_sem_wait, scf_sem_post,
  scf_task_kill`.
- **Flowing macros** (in the headers): `TAG_OPEN_RD`, `TAG_SNAPSHOT`,
  `HIST_TREND`, `RAISE_ALARM`.
- **Constants**: use the `PT_*`, `ARC_*`, `CFG_*`, `Q_*`, `EVT_*`, `TMR_*`,
  `TASK_*`, `ALM_*`, `SCF_*_LOCK` macros from `scf_const.h`. Never hardcode the
  raw number when a macro exists.

## How the tracer reads your code (rules you MUST obey)

1. **C only.** Procedural C89/C99. No C++.
2. **Direct named calls only** for anything you want on the call graph:
   `foo(a, b)`. Calls through function pointers / struct fields / expressions
   become `indirect_call` and are NOT followed — use those ONLY where a task
   explicitly asks for an edge-case.
3. **Global function names are unique project-wide.** Only define the global
   names assigned to YOUR file (below). You MAY add extra `static` helpers with
   any name (static names are file-local). Prefer `static` for internal helpers.
4. Reference other modules' functions only through `headers/app.h` prototypes.
5. Include what you use: always `#include "app.h"` plus whichever `scf_*.h`
   headers your calls need.
6. Every framework API you want *detected* must appear as a **direct call by its
   real name somewhere in the project** (macros alone don't register it). The
   files are divided so this is covered; just call what your task lists.
7. **call_number**: if you place a `scf_evt_post(EVT_xxx, ...)` or
   `scf_var_evt(EVT_xxx, ...)` on a path, its 1st argument (an `EVT_*` macro)
   is reported as the path's call_number. Only add it when your ground truth
   says so.

## The indirect event-listener pattern (important)

`main` does NOT call the handler functions directly. Instead it *registers*
them, and the framework later invokes them. The tracer models this link ONLY
through the registration call:

```c
scf_evt_register(EVT_SCAN_CYCLE, on_scan_cycle);   /* main -> (EVENT) -> on_scan_cycle */
scf_timer_start (TMR_WATCHDOG, 500, tick_watchdog);/* main -> (TIMER) -> tick_watchdog */
scf_task_fork   (TASK_HIST, hist_task_entry);      /* main -> (FORK)  -> hist_task_entry */
```

Callback argument forms and how the analyzer treats each (verified against the
call-graph code):

- `(EvtHandler)Handler` (cast) — **followed cleanly**. PREFER THIS.
- `(Handler)` (parenthesized) — **followed cleanly**. Also fine.
- `Handler` (bare identifier) — followed, but the current code appends it twice,
  producing a DUPLICATE path. Use it in at most one place, on purpose.
- `&Handler` (address-of) — **NOT followed** (parses as `pointer_expression`,
  which the extractor ignores). This is a known limitation; only use it in the
  edge-case file to demonstrate the missed link.

The registered function then reaches a framework API through ordinary direct
calls, forming the traced path. `launch_via` for that path is the registrar's
launch type (EVENT/TIMER/FORK/SIGNAL/INPUT).

## get_upper (trace direction)

- Most APIs are `get_upper: true` — the tracer resolves the **argument values**
  passed *into* the call (values flow from above/callers). Make those arguments
  reach a concrete literal or numeric `*_*` macro through parameters/assignments.
- `scf_hist_load` is `get_upper: false` — the tracer instead classifies how the
  **return value is used below** the call (READ vs WRITE). If your task uses
  `scf_hist_load`, arrange its return so the intended READ/WRITE is obvious
  (`p = scf_hist_load(...); *p = v;` => WRITE; `x = scf_hist_load(...); use(x);`
  => READ).

## Selecting a call site when a callee repeats

If one function calls the same API more than once, annotate the intended one
with `/*CONSIDER THIS CALL*/` on the same line; the tracer picks that one (else
it uses the last occurrence).

## Ground-truth block (REQUIRED in every file)

At the top of your file, after the includes, add a comment block listing, for
each traced API call your file participates in, the expected tracer result:

```c
/* GROUND TRUTH
 * path      : main -> scf_evt_register(EVENT) -> on_scan_cycle -> read_all_points -> scf_tag_read
 * api       : scf_tag_read   type=READF   launch_via=EVENT
 * arg 2     : PT_FLOW_RATE = 0x1004
 * call_num  : 3001 (EVT_SCAN_CYCLE via scf_evt_post in on_scan_cycle)  |  or None
 */
```

Be precise: only claim a value is resolvable if a literal/`*_*` macro genuinely
reaches it along the path.

## Quality bar

Files must look like real, plausible SCADA process code (meaningful names,
comments, realistic control flow: scan loops, alarm handling, historian
flushing, command dispatch), NOT toy stubs. Aim for 90–160 lines. Include the
specific patterns your task assigns. Do not add a `main()` unless your file is
`main.c`.

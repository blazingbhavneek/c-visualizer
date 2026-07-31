# Requirements for C test code

This document specifies the kind of C source the tracer in this repository is
built to consume. Use it as the authoring contract when writing **synthetic
test projects** that exercise the pipeline end‑to‑end (`makefile_resolver` →
`extract_includes` → `Preprocess` → `call_graph` → `parser_files` →
`project_aware` LLM trace).

The goal of a test project is not to be a realistic application. It is to
produce a deterministic, hand‑verifiable answer for each traced API call so the
tracer's output (path, launch mechanism, operation type, resolved argument
values, `call_number`) can be checked against a known ground truth.

The pipeline accepts a very wide C *syntax* (see `report.md`), but the
*analysis* only understands a narrow subset. Test code must stay inside that
subset, or it must deliberately step outside it to test a documented
limitation. Both are useful; label which one each test file is.

---

## 1. Build & project layout

The project is discovered through a Makefile, not by scanning a folder.

- **Makefile is mandatory.** Each test project is a directory containing a
  `Makefile`. `makefile_resolver` reads a small variable model:
  - `SRCS` — the `.c` files. Each token must resolve to a `.c` file (a token
    without a `.c` suffix is rewritten to `<stem>.c`). One of these files must
    define `main`.
  - `INCLUDE` — include directories, `-I`‑prefixed tokens are accepted
    (`-I../headers`). These become the search path for headers.
  - `LIBS` — library tokens; each resolves to the *directory* containing the
    library, which is then swept for `.c`/`.h`. Use this to pull in framework
    stub sources/headers.
  - `include <path>` directives are followed recursively.
  - Variables are `$(VAR)` / `${VAR}` and expand from earlier assignments or the
    environment. Keep them simple: no `$(wildcard …)`, no pattern rules, no
    shell functions, no generated sources — the resolver does not model them.
- **Only `.c` and `.h` files participate.** No `.cpp`, `.cc`, `.inc`, or
  assembly. Files not reachable from `SRCS`/`INCLUDE`/`LIBS` and the include
  graph are invisible to the tracer.
- **Headers are reached by `#include`.** `#include "x.h"` and `#include <x.h>`
  are both followed transitively. A header that is never included by any
  reachable file will not be parsed, so its macros/definitions won't be seen.
- **Basenames should be unique across the whole project.** The mapping is keyed
  by filename in several places (`project_structure`, `file_functions`,
  `TREES`). Two different `util.h` (or two `main.c`) in different directories
  can be confused. Give every file a distinct basename unless you are
  specifically testing the duplicate‑basename limitation.
- **Encoding.** Sources are decoded as Latin‑1. Plain ASCII is safest; if you
  test non‑ASCII, use Latin‑1‑encodable bytes only.
- **Preprocessing is partial.** Comments are stripped and `unifdef` runs over
  `.c` files, but the real compiler command line is **not** reproduced. Do not
  rely on `-D` flags, build configs, or conditional compilation resolving the
  way a real build would. If a `#if` must select a branch, make it decidable
  from in‑file `#define`s.

Minimal Makefile shape:

```make
SRCS    = main.c dio.c
INCLUDE = -I. -Iheaders
LIBS    =
```

---

## 2. Language & entry point

- **C only, procedural, C89/C99 style.** No C++ (no classes, templates,
  references, overloading, namespaces). The grammar can parse many GNU/MSVC/
  modern‑C extensions, but the analysis gains nothing from them — keep test code
  plain unless a test targets a specific syntactic edge case.
- **A single conventional `main()` is the root.** The call tree is rooted at the
  function literally named `main`. Everything you want traced must be reachable
  from `main` through the call patterns in §3.
- **`static` vs global functions matter.**
  - Global (non‑`static`) functions are indexed by **name only**, project‑wide.
    Do not define two global functions with the same name in different files —
    the second silently overwrites the first.
  - `static` functions are file‑local and indexed per file. Two files may each
    have a `static helper()` without colliding. Use `static` to test
    file‑local resolution.

---

## 3. Call‑graph‑friendly control flow (the core constraint)

The call‑graph builder only creates an edge for a `call_expression` whose callee
is a **plain identifier** — `foo(...)`. This is the single most important rule.

**MUST use (resolvable, produce real edges):**

- Direct named calls: `foo(a, b);`, `ret = foo(a, b);`.
- Calls nested in expressions/conditions: `if (foo(x)) …`, `g(foo(x))`.
- Calls to `static` and global functions defined anywhere in the reachable set.

**MUST AVOID (unless testing the limitation — these become `indirect_call` or
are dropped):**

- Calls through function pointers: `fp(a, b);`, `table[i](a);`.
- Calls through struct/union fields: `obj->fn(a);`, `ops.write(a);`.
- Calls through arbitrary expressions: `(cond ? f : g)(x);`.
- Any vtable‑like or dynamic dispatch pattern.

The **only** sanctioned way a function pointer enters the call graph is through a
registered callback (see §5). Anything else is intentionally incomplete.

For each function you expect on a path, make sure its **definition** is in a
reachable `.c` file. Header‑only prototypes are treated as external and will not
be entered.

### Selecting a specific call site
When a caller `Fi` calls the same callee `Fi+1` more than once, the tracer picks
the call site marked `/*CONSIDER THIS CALL*/`, or the **last** occurrence if
none is marked. When a test needs a specific call site traced, annotate it:

```c
ptr = DioGetPtr(SDB_FILENO_DBKNR, 0);
ptr = DioGetPtr(FNO_HEALTH,       0); /*CONSIDER THIS CALL*/
```

---

## 4. Framework APIs to invoke (what the tracer looks for)

The tracer only reports on API names it has been configured to detect (see §7).
Test code should call functions from this family so there is something to
classify. Names should match the configured set; the built‑in vocabulary is:

- **File operations** → classified as one of
  `OPENF, READF, WRITEF, COPYF, SAVEF, LOADF, CLEARF, CLOSEF` — e.g.
  `mpf_mfs_open`, `mpf_mfs_getrec`, `mpf_mfs_close`.
- **Queue operations** → `ENQ, DEQ, READQ, WRITEQ, USEQ, SAVEQ, LOADQ, CLEARQ`,
  plus `ENQFORK, ENQSEM`.
- **Event / process control** → `EVENT, MESSAGE, FORK, FORKP, SEMAPHORE, TIMER,
  KILL, SIGNAL, INPUT` — e.g. `pmf_addevent`, `pmd_addvarevt`.
- Fallbacks the model may emit: `NOT_FILE_OR_QUEUE_OP`, `NO DATA`,
  `UNRESOLVED`.

**Launch mechanism** (`launch_via`) is one of `EVENT, FORK, SEMAPHORE, MESSAGE,
TIMER, FORKP, INPUT, SIGNAL, NO DATA`. A path that reaches the target through a
registered callback is reported as its callback‑registrar's launch type (often
`EVENT`); a path reached by plain direct calls defaults to `FORK`.

**`call_number`:** if `pmf_addevent(...)` or `pmd_addvarevt(...)` appears
anywhere in a traced path's context, the tracer resolves that call's **1st
argument** and reports it as `call_number`. To test this, place such a call on
the path and give its first argument a resolvable constant. Otherwise
`call_number` is `None`.

You do not need real implementations of these APIs. Header prototypes plus
trivial stub bodies (in a `LIBS`‑reachable `.c`) are enough — the values you
care about are at the **call sites in your own code**, not inside the API.

---

## 5. Callbacks (the only supported indirect flow)

A callback is only followed when it is passed to a **registration function**
that has been declared in `json_data/function_callback_info.json` as:

```json
{ "RegisterFn": { "func_argument": [2] } }
```

`func_argument` lists the **1‑based argument positions** that hold callback
function references. Requirements for test code:

- Call the registration function directly by name: `RegisterFn(id, MyHandler);`.
- Pass the callback at exactly the configured position, as one of:
  - a bare identifier — `MyHandler`
  - address‑of — `&MyHandler`
  - a parenthesized identifier — `(MyHandler)`
  - a cast identifier — `(void *)MyHandler` / `(CbType)MyHandler`
- The referenced handler must be a real function **defined** in the reachable
  set, so the graph can descend into it. The handler then becomes an extra path
  node, and the path's `launch_via`/`call_function` are derived from the
  registrar and the handler.

Do **not** expect a callback stored into a variable/struct first and registered
later to be tracked — only the direct argument form is analysed.

---

## 6. Macros

Macros are collected **only from `.h` files** (`#define`), object‑like and
function‑like:

- **Function‑like macro that forwards to a direct call** is expanded into an
  extra path node and followed:
  ```c
  /* in a .h */
  #define DioRead(f, n)  mpf_mfs_getrec((f), (n), 0)
  ```
  The builder follows `DioRead → mpf_mfs_getrec` and records the argument
  injection/reordering. Use this to test macro‑expanded call chains.
- **Object‑like constant macros** are surfaced to the tracer as constant
  candidates when their value is numeric:
  ```c
  #define FNO_HEALTH  0x0012
  #define REC_COUNT   32
  ```
  Prefer numeric literals (decimal or `0x…`, optional `u/U/l/L/f/F` suffix) for
  any macro whose value must be *resolved* to a concrete number.
- A macro is only usable in the call graph if it ultimately reduces to a single
  direct **named** call. Macros expanding to function‑pointer calls, multiple
  statements, or token soup are not followed. Full C preprocessing / macro
  data‑flow is **not** performed — keep macros shallow.
- Because macros are read from headers only, define any macro you expect to be
  resolved in a `.h` that is included on the path (not inline in a `.c`).

---

## 7. Argument‑value traceability (so the backward tracer succeeds)

For each detected API, `mpf_data.json` (`FUNCTION_TYPES`) configures which
argument **indices** (1‑based) to resolve. Author call sites so those arguments
trace back to a **concrete literal**. The tracer walks backward through
assignments, parameters, and callers and stops at the first literal. Make that
possible:

- **Traceable value sources:** numeric/string/char/enum literals, `NULL`,
  numeric `#define` constants (in a reachable header), and values threaded
  through function **parameters** from a caller that ultimately supplies a
  literal.
- **Provide a literal somewhere on the path.** A value that originates from
  runtime input, an un‑analysable expression, or an external function with no
  definition in context will (correctly) come back `UNRESOLVED`. Use that
  deliberately for negative tests.
- **Argument‑index shifts across macros:** when a function‑like macro injects
  leading arguments (§6), the downstream argument indices shift. Document the
  expected mapping in the test's ground truth.
- **Return‑value tests (`get_upper: false`):** for APIs configured to be traced
  by how their **return value** is used, arrange the call site so the return is
  clearly read (`x = api(...); use(x);`) or written through (`p = api(...);
  *p = v;`) — these map to `READF`/`WRITEF` respectively.

Relevant `mpf_data.json` entry shape per detected function:

```json
{
  "mpf_mfs_open": {
    "type": "OPENF",
    "launch": "FORK",
    "indices": [3, 4],
    "get_upper": true,
    "dependent_functions": []
  }
}
```

`combined_data.json` (`FUNCTION_MAP`) may additionally provide prototypes the
`find_definition` tool returns; supply prototypes for external framework APIs so
the model can reason about arg positions.

---

## 8. Runtime configuration coupling

The pipeline will not run without the config files under `json_data/`
(see `state/load_data.py`). Every test project needs, consistent with its code:

- `json_data/mpf_data.json` — the APIs to detect and how (§4, §7).
- `json_data/function_callback_info.json` — callback registrars (§5).
- `json_data/combined_data.json` — function prototype map (optional but
  recommended for external APIs).

The set of API names in `mpf_data.json` **is** the detector. If your test code
calls `mpf_mfs_open` but the config doesn't list it, nothing is traced. Keep the
config and the C in lockstep, and ship both with each test project.

Also required at runtime (environmental, not part of the C): `unifdef`,
`libclang`, and a reachable Ollama service. Test *code* does not need to satisfy
these, but the harness does.

---

## 9. Minimal worked example

A single test project that exercises: direct calls, a `static` helper, a
numeric macro constant, a file API with a traceable argument, and a
`call_number` via `pmf_addevent`.

`headers/dio.h`
```c
#ifndef DIO_H
#define DIO_H
#define FNO_HEALTH   0x0012          /* numeric macro → resolvable */
#define EVT_STARTUP  2003            /* becomes call_number       */
void *mpf_mfs_open(void *fcb, void *name, int filenum, int sub, int a, int mode);
void  pmf_addevent(int evt, void *handler);
#endif
```

`main.c`
```c
#include "dio.h"

void *DioGetPtr(int filenum) {
    void *fcb;
    return mpf_mfs_open(&fcb, 0, filenum, 0, 0, 1); /*CONSIDER THIS CALL*/
}

static void health_boot(void) {
    (void)DioGetPtr(FNO_HEALTH);      /* arg 3 of mpf_mfs_open traces to 0x0012 */
}

int main(void) {
    pmf_addevent(EVT_STARTUP, 0);     /* call_number = 2003 */
    health_boot();
    return 0;
}
```

`Makefile`
```make
SRCS    = main.c
INCLUDE = -Iheaders
LIBS    =
```

Config (`json_data/`):
```json
// mpf_data.json
{ "mpf_mfs_open": { "type": "OPENF", "launch": "FORK",
                    "indices": [3], "get_upper": true, "dependent_functions": [] } }
// function_callback_info.json
{}
```

**Expected ground truth for the `mpf_mfs_open` path:**
- path: `main → health_boot → DioGetPtr → mpf_mfs_open`
- `type`: `OPENF`
- `launch_via`: `FORK` (no callback on the path)
- resolved arg 3: `0x0012` (i.e. `18`)
- `call_number`: `2003`

To add a callback/event variant, register a handler function through a
`func_argument` entry in `function_callback_info.json`, pass the handler as the
argument, and expect `launch_via` to follow the registrar (e.g. `EVENT`).

---

## 10. Quick checklist per test file

- [ ] Reachable from `SRCS` and the include graph; unique basename.
- [ ] Plain C, one `main`, definitions (not just prototypes) for traced funcs.
- [ ] Target reached only via direct named calls or a registered callback.
- [ ] No function‑pointer/field/expression calls on the intended path
      (unless testing that limitation).
- [ ] Detected API names match `mpf_data.json`.
- [ ] Traced argument indices reach a literal / numeric header macro.
- [ ] Macros that must resolve live in an included `.h` and are numeric.
- [ ] `pmf_addevent`/`pmd_addvarevt` present iff a `call_number` is expected.
- [ ] The specific call site is annotated when a caller repeats a callee.
- [ ] A written‑down expected result: path, type, launch_via, resolved args,
      call_number.

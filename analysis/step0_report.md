# Step 0 — Direct constants and macros

## Scope and status

This report compares the existing c-visualizer and legacy indexes for direct
target arguments. It does not rerun either analysis pipeline.

Step 0 includes a target argument that is directly:

- an integer or string literal;
- a directly named macro; or
- a directly named enum constant whose value can be proved from source syntax.

It excludes variables, helper parameters, FCB/handle matching, proximity
matching, LLM results, and other propagated values. Those are Step 1 cases.

A **site** is the exact absolute source file and line containing the target
call. A **record** is one site, operation, and resolved value. A **resolution**
is one concrete value reported for one site. The comparison below uses final
aggregate-index records unless explicitly identified as c-visualizer evidence.

## 1. Direct comparison

| Population | Records | Source sites |
| --- | ---: | ---: |
| c-visualizer direct records in the final aggregate index | 933 | 933 |
| legacy direct records | 1,240 | 1,240 |
| same site, operation, and value in both | 655 | 655 |
| c-visualizer-only records | 278 | 278 |
| legacy-only records | 585 | 585 |

The c-visualizer discovery evidence contains 1,100 direct exact rows. Of those,
167 were not promoted into the final aggregate index because of scope or
reachability filtering. The 933-versus-1,240 comparison therefore must not mix
the evidence population with the final-index population.

The 13 shared source locations with different values are all MFS-file cases;
there are no queue or forkproc disagreements in this subset. Some locations
contribute more than one record, so the disagreement is 20 records when
counted at record level.

## 2. Why legacy has more final-index records

The raw difference is 307 records, but that is not a count of c-visualizer
discovery misses: c-visualizer also has 278 records absent from the legacy
index.

Among the 585 legacy-only records, 322 did not have a matching c-visualizer
final record under the original comparison key. That 322-record population was
manually checked against the active source tree and divides as follows:

| Classification | Count | Interpretation |
| --- | ---: | --- |
| SOURCE_MAPPING_MISMATCH | 225 | The same open call was found by c-visualizer, but legacy labels the lock as READ/WRITE while c-visualizer labels the target operation OPEN_LOCK; the c-visualizer fact is UNREACHABLE and is therefore absent from the final exact index. |
| CVIZ_SCOPE_OR_INPUT_EXCLUSION | 58 | Legacy records the caller-side queue wrapper; c-visualizer records the inner mpf_mfs_addque target. |
| LEGACY_STALE_VALUE | 14 | The legacy value matches an archived Dyn header, not the active source header. |
| DISABLED_OR_COMMENTED | 25 | The source is disabled, primarily under #if 0. |
| **Total** | **322** | |

The 322 records contain 297 active-looking locations and 25 disabled locations.
The active-looking records contain zero confirmed ordinary c-visualizer
discovery misses. The major remaining issue is reachability and source-model
interpretation, not failure to find the target call text.

### 2.1 Wrapper-location differences

The 58 queue records are location differences, not missing values. Legacy
records calls such as:

```c
Dac_EnqSem(forkname, DifKoshoInfoQNo, (char *)&johoq, ...);
```

C-visualizer targets the inner operation:

```c
mpf_mfs_addque(NULL, fileno, enqdata);
```

The relevant wrapper mappings are:

| Wrapper | FNO argument at wrapper | Inner target |
| --- | ---: | --- |
| Dac_EnqSem | 2 | mpf_mfs_addque argument 2 |
| Dac_EnqSem2 | 2 | mpf_mfs_addque argument 2 |
| SimEnqueSem | 3 | mpf_mfs_addque argument 2 |
| MsgEnqSem | 2 | mpf_mfs_addque argument 2 |
| DxiEnqEvent | 2 | mpf_mfs_addque argument 2 |
| DxiEnqEvent2 | 2 | mpf_mfs_addque argument 2 |

If caller-level attribution is required, c-visualizer should retain the inner
call as the canonical queue operation and add wrapper metadata. Treating both
as independent operations would double-count the same queue access.

### 2.2 Disabled source

The 25 disabled records include:

- 20 queue calls in `dif122d` under an outer `#if 0`;
- three Dxi open calls, including disabled twins of active calls;
- one Cha open call;
- one disabled `pmf_forkproc_H("msg500d", ...)` call.

The legacy scanner is text-based and therefore reports these records even
though the active preprocessor configuration excludes them.

## 3. Value provenance and stale legacy data

The 13 shared locations with different values all use Dyn file-number enum
constants. C-visualizer follows the active header:

`/home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h:209-219`

The legacy values come from the archived header:

`/home/chukyu_exe/include/Dyn.260114/DynReEneFileDef.h:79-152`

Representative values are:

| Symbol | c-visualizer/current | Legacy/archived | Correct source value |
| --- | ---: | ---: | --- |
| DynReCtlMainteFNO | 3973 | 1077 | c-visualizer |
| DynAdvCtlLogFNO | 3984 | 3915 | c-visualizer |
| DynReAtEmeKanFNO | 3976 | 1343 | c-visualizer |
| DynReEmeKanIndFNO | 3974 | 1079 | c-visualizer |
| DynReEmeStaIndFNO | 3975 | 1080 | c-visualizer |
| DynReCtlNtcDtPvFNO | 3981 | 3906 | c-visualizer |

The active header marks the old entries as dummy/deleted entries and defines
the current values later in the enum. The legacy index is therefore stale for
these records. A correct legacy rebuild must resolve definitions through each
source file's actual include/configuration context, reject headers outside the
selected source root, record the supplying header path, and flag duplicate
definitions instead of silently selecting the first match.

## 4. Examples where c-visualizer finds more

These are direct Step 0 examples, not propagated Step 1 resolutions.

### Tool source outside the legacy collector

`/home/chukyu/t-rep/tool/msgreq/msgreq.c:421` contains an ADDQUE call with
the literal `1055`. C-visualizer records it; the legacy source collector
scans ordinary `t-*/src` files and does not collect this `t-*/tool` file.

### Direct macro from an external header

`/home/chukyu/t-tmm/src/tmm910/tmm910_main.c:58` directly uses
`FfeMntInfoFileNo`, resolved to `3652` from
`/home/chukyu_exe/include/ffe/FfeMntInfo.h:25`. The target argument itself is
the macro, so this remains a direct Step 0 case.

### Local macro resolution

At `/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:78`, c-visualizer
resolves the local `PROC_NAME` macro to `dyn600`; the legacy index has no
matching record. This is a direct local-definition discovery difference.

These examples show why the count alone is not a correctness metric. A
c-visualizer-only record can represent better source coverage, a scope
difference, or an over-approximation; each case requires source verification.

## 5. Investigation of the 225 apparent open-call gaps

The 225 SOURCE_MAPPING_MISMATCH records were audited individually at the source
and call-graph level. Every one has:

- an active open call at the recorded absolute file and line;
- the same target expression in the source;
- a c-visualizer discovery fact at that physical call;
- operation `OPEN_LOCK`;
- status `UNREACHABLE`;
- `path_count = 0`.

Therefore these 225 are not ordinary discovery misses. In c-visualizer,
UNREACHABLE means that the value-flow resolver could not find a path from one
of its recognized lifecycle roots to the enclosing function. It is a
call-graph result, not a statement that the source call was never discovered.

### Method

The read-only audit:

1. Replayed c-visualizer preprocessing and function/call extraction over the
   source tree.
2. Walked callers backward from each target's enclosing function to graph roots
   and lifecycle entry points.
3. Searched the unpreprocessed active source for missing ordinary calls,
   function-pointer uses, and callback registrations.
4. Compared source callers with c-visualizer's per-process Makefile boundaries.
5. Classified each record by the first concrete cause supported by the source
   evidence.

The replay used a global graph, which is a superset of any individual
per-process graph. This makes the conclusion conservative in the safe
direction: a missing caller in the global view cannot become available inside a
smaller process graph. Macro-generated call edges may be under-counted.

### Verdict summary

| Verdict | Count | Share | Meaning |
| --- | ---: | ---: | --- |
| DEAD_CODE | 85 | 37.8% | No active caller or function-pointer use exists anywhere in the source. |
| PARSE_CORRUPTION | 80 | 35.6% | A real same-project path exists, but preprocessing/parser corruption removes an entry edge. |
| CALLBACK_DISPATCH | 52 | 23.1% | The function is live through runtime callback registration that static BFS does not cross. |
| CROSS_PROJECT_CALLERS_ONLY | 8 | 3.6% | A real caller chain exists, but it crosses a Makefile/process boundary. |
| **Total** | **225** | **100%** | **Zero ordinary discovery misses.** |

### 5.1 Parse corruption: 80 records

#### Pattern A: dual K&R/ANSI main definitions — 65 records

Many Dyn GUI entry files contain:

```c
#ifdef _NO_PROTO
int main(argc, argv)
        int argc;
        char *argv[];
#else
int main(int argc, char *argv[])
#endif
{
    dyn730Initialize(argbuf);
}
```

`_NO_PROTO` is not defined in the source tree. C-visualizer invokes
`unifdef -t -k -b` without a `-D` or `-U` for this symbol, so both
declarations survive preprocessing. The C grammar cannot reliably parse the
two definitions separated by `#else`; error recovery produces a truncated
`main` body.

For example, in
`/home/chukyu/t-dyn/src/dyn730/dyn730Main.c`, the source contains roughly
18 top-level calls in `main`, but only a small subset survives in the parsed
call graph. The edge from `main` to `dyn730Initialize` at line 230 is lost,
so the open calls below that initializer become UNREACHABLE.

The 65 affected records are distributed across 13 Dyn GUI entry files,
including dyn700, dyn710, dyn720, dyn730, dyn731, dyn732, dyn740, dyn750,
dyn760, dyn770, dyn772, dyn773, dyn780, and dyn790 process families.

#### Pattern B: preprocessor directives splitting a braceless if — 15 records

Several entry files contain a directive inside a statement sequence:

```c
if (pmf_time.sec % 10 == 0)
{
#ifdef NOP
    if (exe_time.TimDat != now_time.TimDat)
#endif
    if (ChaForkTm.TimDat != now_time.TimDat)
    {
        /* body */
    }
}
```

In `cha100dMain.c`, this structure causes the parser to collapse the
`pmf_main_H` region and the `cha100Init` function into an ERROR node. The
edge from `pmf_main_H` to `cha100Init` is lost. Similar cases occur in
dif700 and the sim800/sim801/sim810 entry files.

#### Repair priority for parse corruption

1. Pass the actual project macro state to preprocessing. At minimum,
   `-U_NO_PROTO` produces one clean ANSI `main`; deriving `-D/-U` from
   each Makefile's flags is preferable. This addresses 65 records.
2. Normalize or otherwise tolerate preprocessor pairs that split a single
   statement. This addresses 15 records.
3. Add a post-preprocessing check for duplicate function definitions and for
   lifecycle entry names present in source but absent from the parsed function
   list.

### 5.2 Callback dispatch: 52 records

These functions are live, but their invocation is indirect. The registration
site is in reachable code while the callback body has no ordinary static call
edge.

The registration mechanisms observed were:

| Mechanism | Observed root counts |
| --- | ---: |
| Xt/Motif callback tables | 51 |
| `pmf_addevent` and related PMF event registration | 26 |
| `SimAddSemCallback` | 13 |
| `MmiAddEvent` | 8 |
| Other indirect value use | 2 |

These mechanism counts overlap because one target can have multiple callback
roots; they are not intended to sum to 52.

Representative registrations include:

- `pmf_addevent(..., cha702Event, ...)` leading to
  `/home/chukyu/t-cha/src/cha702/cha702Event.c:974`;
- an `XtCallbackProc` entry for `chaDlg01SaveKindBtn` leading to
  `/home/chukyu/t-cha/src/libChaDlg/ChaDialog01CtlCB.c:67`;
- `SimAddSemCallback(..., sim_Choku, ...)` leading to
  `/home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:52`;
- `pmf_addevent(..., dyn730EventInterrupt, ...)` leading to a Dyn open
  call in `dyn730Init.c`.

C-visualizer already stores callback information in
`function_callback_info.json` and has a `FUNCTION_POINTER_ARGS` mechanism.
Wiring Xt/Motif, PMF events, Mmi events, and simulation semaphore callbacks
into reachability would convert these from generic UNREACHABLE rows into
reachable-via-callback rows.

### 5.3 Cross-project callers: 8 records

The source contains complete caller chains, but the caller and target do not
coexist in any one c-visualizer process run.

| Records | Target/caller example | Boundary |
| ---: | --- | --- |
| 1 | `t-dif/src/libdif/difGetF1Data.c:55`, called from tmm200d | t-dif library versus t-tmm process |
| 1 | `t-dif/src/libdif/difGetNamaData2.c:61`, called from svm200d | t-dif library versus t-svm process |
| 1 | `t-dif/src/libdif/difGetNamaData3.c:61`, called from tmm210d | t-dif library versus t-tmm process |
| 2 | `t-svm/src/svm000/svm000SendInt.c:288,311`, called by IWATE tools | svm000 process versus maintenance tools |
| 3 | `t-cha/src/libCha/ChaGetJisseki.c:64,492,506`, called by chatestlib | libCha processes versus chatest tool |

Possible fixes are cross-project caller attribution or a separate status such
as `UNREACHABLE_IN_PROCESS` that distinguishes a process boundary from dead
code and unmodeled dispatch.

### 5.4 Dead code: 85 records

The enclosing function has no active caller, registration, or function-pointer
use in the source. In these cases c-visualizer's UNREACHABLE result is correct
and the legacy text scanner over-reports the call.

Examples include:

- `dif901InitDllData`: its only caller is commented out in dif901Main.c;
- `TmmSysInit`: only a header prototype remains;
- `Sim570dHyoji01`, `TmmV3Check`, and `TmmV4Check`: definitions only;
- `ChaGetJissekiAvgORS`, `TmmVoltCheck`, and `DifGetGamenTime`:
  no active source caller.

The legacy side should filter dead or inactive source, or label these records
as DEAD, rather than treating textual presence as evidence of a live access.

## 6. Conclusions and recommended order of work

1. **Do not call the 322 active-looking records discovery misses.** The
   detailed classification found no ordinary active-source discovery gap.
2. **Fix preprocessing first.** Correcting the two parser-corruption patterns
   addresses 80 of the 225 UNREACHABLE records.
3. **Model callback dispatch.** Existing callback metadata can support the 52
   live callback cases.
4. **Distinguish process boundaries.** Add cross-project attribution or
   `UNREACHABLE_IN_PROCESS` for the eight library cases.
5. **Repair the legacy provenance model.** Resolve macros through the active
   include/configuration graph and stop using archived headers as current
   truth.
6. **Keep genuinely dead code unreachable.** Legacy should filter or label the
   85 dead-code records rather than forcing them into the live index.

The key Step 0 result is therefore:

> C-visualizer's lower direct final-index count is not explained by 300 ordinary
> missed calls. The apparent gap is a mixture of operation-label/index-scope
> differences, stale legacy values, disabled code, parser-corrupted
> reachability, callback dispatch, process boundaries, and genuine dead code.

## 7. Reproduction

The script reads existing indexes and discovery facts; it does not run the
full c-visualizer or legacy pipeline:

```bash
python3 analysis/step0.py \
  --cvisualizer-index results/csv_results/index \
  --legacy-index ../index \
  --source-root /home/chukyu \
  --output /tmp/step0_generated_baseline.md
```

The generated file is the machine-derived direct comparison. This curated
report additionally preserves the manually verified source and reachability
audit of the 322 and 225 record populations.

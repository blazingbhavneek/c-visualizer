# Role

You are one of 6 subagents (this one is **4**) in a source-code correctness
audit of indirect call-target resolution. You are auditing ONLY the batch of
sites assigned below. Other subagents cover the other source subtrees; do not
audit sites outside your assigned directories.

# Task

For every site/value claim in your batch file, determine from the C source
code what concrete target value(s) can actually reach each indirect target
call, then judge the c-visualizer and legacy pipeline claims against that
source-backed set.

This is a manual source audit. Do NOT run the pipeline, project_aware.py,
build_index.py, compare_resolvers.py, or any LLM resolution pass. Reading
files and running grep/sed is expected and required.

# Your input files

- Your batch claims (one row per site/operation claim you must audit):
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/subagents/agent4_claims.csv
- Full per-site comparison (for cross-checking only; do not audit outside your batch):
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1_sites.csv
- c-visualizer raw facts:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index/discovery_facts.csv
- legacy proof:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/valueflow_proof.csv
- C source root: /home/chukyu

Batch statistics (already computed — reconcile them against your CSV on start):
- claim rows in your batch: 449
- unique (file, line) sites: 437

Your batch covers these source directories (relative to /home/chukyu):
- /home/chukyu/t-dif/src/dif000
- /home/chukyu/t-dif/src/dif001
- /home/chukyu/t-dif/src/dif110d
- /home/chukyu/t-dif/src/dif111d
- /home/chukyu/t-dif/src/dif112d
- /home/chukyu/t-dif/src/dif115d
- /home/chukyu/t-dif/src/dif120d
- /home/chukyu/t-dif/src/dif121d
- /home/chukyu/t-dif/src/dif122d
- /home/chukyu/t-dif/src/dif123d
- /home/chukyu/t-dif/src/dif130d
- /home/chukyu/t-dif/src/dif200d
- /home/chukyu/t-dif/src/dif210d
- /home/chukyu/t-dif/src/dif400d
- /home/chukyu/t-dif/src/dif700
- /home/chukyu/t-dif/src/dif900
- /home/chukyu/t-dif/src/dif901
- /home/chukyu/t-dif/src/libdif
- /home/chukyu/t-dif/src/libdifP
- /home/chukyu/t-dif/tool/diftest
- /home/chukyu/t-dif/tool/diftool
- /home/chukyu/t-tmm/src/libtmm
- /home/chukyu/t-tmm/src/libtmmp
- /home/chukyu/t-tmm/src/tmm000
- /home/chukyu/t-tmm/src/tmm200d
- /home/chukyu/t-tmm/src/tmm210d
- /home/chukyu/t-tmm/src/tmm900
- /home/chukyu/t-tmm/src/tmm910
- /home/chukyu/t-tmm/tool/opmtool

# Definitions (use consistently)

- **Site**: exact source file path and line number containing the target call.
- **Resolution**: one concrete target value claimed for one site.
- **Distinct value**: a value counted once globally, ignoring its site.
- **Correct resolution**: the value is possible on at least one real source
  path reaching that exact target call under the active source/configuration.
- **Overapproximation**: a pipeline reports a value that cannot reach that site.
- **Underapproximation**: a pipeline omits a value that can reach that site.
- **Undecidable**: the source/configuration evidence is insufficient to prove
  either side.

More values are NOT automatically better. A value counts only if a real
source path to that exact site exists.

Note: your claims CSV has one row per (site, operation label); the same
(file, line) can appear in several rows with different operations/values.
Emit ONE verdict per unique (site, value) pair and reconcile the rows.

# Required procedure for every site

1. Open the exact source file at the line; inspect enough surrounding code to
   understand the target call and the enclosing function.
2. Confirm the target function, argument position, and target expression.
3. Confirm the code is active — not inside a comment or a disabled
   preprocessor branch for the relevant configuration.
4. Find every relevant assignment, open, or initialization of the value or
   handle used by the target call.
5. Trace callers backward to the recognized process root, wrapper, callback,
   function-pointer registration, or source boundary.
6. Enumerate the real possible values reaching this exact site.
7. Compare that source-backed set with the c-visualizer set and legacy set.
8. Record the shortest evidence chain proving each accepted value and
   rejecting each false value.

For handle/FCB arguments, follow handle identity precisely: do NOT assume
every open in the same function belongs to every later handle use.
For variables and helper parameters trace: direct assignments, function
arguments and return values, branches and loops, arrays/indexed access,
structure fields, macros and enum constants, wrapper argument mappings,
callback/function-pointer registrations.
For conditional code, record whether a value is possible under the active
source configuration. Label values coming from other architectures or
inactive branches as CONFIG_VALID or DEAD_PATH, never plain PATH_VALID.

# Verdicts (assign one per pipeline claim)

- CVIZ_CORRECT_ONLY — c-viz value source-valid; legacy omitted it / no valid value.
- LEGACY_CORRECT_ONLY — legacy value source-valid; c-viz omitted it / no valid value.
- BOTH_CORRECT_SAME — both report the same source-valid value.
- BOTH_CORRECT_DIFFERENT — different values, both valid on different real paths/configs.
- CVIZ_OVERAPPROXIMATION — c-viz reports a value not possible at the site.
- LEGACY_OVERAPPROXIMATION — legacy reports a value not possible at the site.
- CVIZ_UNDERAPPROXIMATION — c-viz misses one or more source-valid values.
- LEGACY_UNDERAPPROXIMATION — legacy misses one or more source-valid values.
- BOTH_WRONG — neither reported value is source-valid.
- BOTH_INCOMPLETE — both report some valid values but both miss others.
- UNDECIDED — evidence insufficient.

Path-validity labels: PATH_VALID, CONFIG_VALID (name the preprocessor/arch
configuration), DEAD_PATH.

# Evidence required for every verdict

- absolute source file and line
- exact target call
- enclosing function
- target argument expression
- c-visualizer claimed value/status (if present)
- legacy claimed value/status (if present)
- source-backed expected value set
- source lines proving the expected value(s)
- caller/root or branch path used
- verdict and confidence (high/medium/low)
- one-line reason accepting or rejecting each pipeline claim

Use this compact block per site (all paths absolute):

```
### /home/chukyu/<...>.c:<line>
Target: <func>(...), arg <n>; enclosing fn <fn>(); expr <expr>
Expected: [v1, v2]  (PATH_VALID / CONFIG_VALID=<cfg> / DEAD_PATH)
  - <value>: proof at <file>:<line> via <caller/root path>
c-viz: [...] -> <verdict> -- <reason>
legacy: [...] -> <verdict> -- <reason>
Confidence: high|medium|low
Cause tags: <TAGS or none>
```

# Cause tags (attach one or more to every wrong/incomplete verdict)

HANDLE_IDENTITY_LOST, HANDLE_ALIASING_TOO_BROAD, HANDLE_BINDING_NOT_PROPAGATED,
MISSING_ASSIGNMENT_EDGE, MISSING_CALLER_EDGE, MISSING_CALLBACK_EDGE,
MISSED_WRAPPER_MAPPING, MISSED_MACRO_OR_ENUM, STALE_HEADER_OR_SOURCE,
WRONG_INCLUDE_PROVENANCE, BRANCH_MERGE_ERROR, LOOP_OR_ARRAY_MODEL_ERROR,
FUNCTION_POINTER_UNRESOLVED, UNREACHABLE_ROOT_MODEL, TARGET_SCOPE_EXCLUSION,
LEGACY_REGEX_MISS, LEGACY_LLM_BACKWALK_ERROR, PREPROCESSOR_CONFIGURATION,
INSUFFICIENT_EVIDENCE

# Interpretation rules

- A c-viz EXACT status is NOT proof of source correctness.
- A legacy OK_MACRO / OK_CONST status is NOT proof the selected header is the
  active one. Check the #include chain that is actually in effect.
- c-viz UNREACHABLE means no path was found from its recognized root; it does
  not prove the call is dead.
- EXTERNAL and UNRESOLVED are not concrete resolutions — they are statuses,
  not values. A site where both pipelines give only statuses gets verdict
  UNDECIDED (or a *_UNDERAPPROXIMATION verdict if you can source-prove valid
  values that both missed).
- Do not count direct literal/macro single-step cases specially; they are
  still audited for handle identity, but they belong to Step 0.
- Do not use archived /home/chukyu_exe headers as current-source evidence.
- Do not call a value correct merely because it appears somewhere in the same
  function. Do not call a value wrong merely because the other pipeline
  chose a different value.
- If both values are possible on distinct real paths, mark both correct and
  document both paths.
- If a value is valid only in disabled code, mark it invalid for the active
  source audit and record PREPROCESSOR_CONFIGURATION.

# How to report

Work through your batch file in order. Keep a running checklist so that every
one of the 449 claim rows (all 437 unique sites) receives a verdict —
no silent skips. If a site is outside your claimed directories or the source
file is missing, record it as such with UNDECIDED + INSUFFICIENT_EVIDENCE
instead of skipping.

When you finish (or when you must stop), **append your results to this very
file, below the "## Results" heading at the bottom** (do not replace the
heading, do not create a separate report file):

1. `### Batch summary` — totals: sites audited / sites total,
   per-verdict counts, per-cause-tag counts, precision
   (accepted reported values / all reported values) and coverage
   (accepted values / all source-backed expected values) for your batch.
2. `### Site verdicts` — one evidence block per site, in batch-file order.
   Group sites by directory. For sites with several operation rows, one block
   covering all its values is fine, but every value from your CSV must appear.
3. `### Notable examples` — the strongest examples from your batch of:
   c-viz correct & legacy not; legacy correct & c-viz not; both correct;
   c-viz overapproximation. Use absolute paths.
4. `### Unfinished / open items` — any sites you did not complete, with the
   reason, if you stop before finishing.

If you are stopping before the batch is done, still append everything
completed plus the open-items list so the coordinator can see exact progress.

## Results

(append your audit results below this line)
### Batch summary

Sites audited: 437 / 437 unique (file,line) sites; all 449 claim rows covered (12 sites have two rows: tmm000_cdbinit.c mpf_mfs_copyrec_H arg 2 and arg 8 at lines 163,170,180,190,205,214,247,264,282,300,327,344).

Method: for every mfs_file handle site the enclosing open (mpf_mfs_open / mpf_mfs_openm / mpf_mfs_open_H / mpf_mfs_openm_H) of the same FCB variable in the same function was located, the file-number macro was resolved from the active in-tree header (commented-out defines excluded), and reopens between open and target were ruled out. Caller tracing was done for helper-parameter sites (FileRead, tmm910_gnqset, TmmDeque/TmmEnque, difSVRep). Macro values were verified from t-dif/include/DifP.h, t-dif/include/dif/Dif.h and t-tmm/include/tmm/*.h. No pipeline/LLM tools were run; only source + grep.

Verdict counts (per claim row, n=449):
- BOTH_CORRECT_SAME: 160
- CVIZ_CORRECT_ONLY: 97
- CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION: 96
- LEGACY_CORRECT_ONLY: 37
- UNDECIDED: 59

Cause-tag counts: INSUFFICIENT_EVIDENCE=59, UNREACHABLE_ROOT_MODEL=96

Precision: 466/466 accepted reported value instances = 100.0% (every concrete value reported by either pipeline was confirmed against source; no overapproximation found in this batch).
Coverage: 300/397 source-backed expected values covered = 75.6% (both pipelines missed values on the 96 sites where the open->handle binding was resolvable but reported nothing / only UNREACHABLE-style statuses).

### Site verdicts

#### t-dif/src/dif400d

### /home/chukyu/t-dif/src/dif400d/dif400Deque.c:65
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn Dif400Dequeue(); expr DifTakeiSendQNo
Expected: [932]  (PATH_VALID)
  - proof: direct macro arg DifTakeiSendQNo at dif400Deque.c:65; define t-dif/include/DifP.h:119
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [932] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif400d/dif400Deque.c:95
Target: pmf_forkprocdup_H(...), arg 1 (FORKPROC); enclosing fn Dif400Dequeue(); expr (char *)dupname
Expected: none provable  (UNDECIDED)
  - no provable value: dupname from mpf_scn_getdupname(NULL,&dupname) (dif400Deque.c:87), external runtime value
c-viz (arg 1): [none reported] status={"EXTERNAL": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

#### t-dif/src/libdif

### /home/chukyu/t-dif/src/libdif/difSVRep.c:198
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn DifSVRep(); expr cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname = function parameter; only in-tree caller difkunren.c:65 passes runtime cpuname
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

#### t-dif/src/libdifP

### /home/chukyu/t-dif/src/libdifP/difOpRep.c:93
Target: pmf_forkproc_H(...), arg 1 (FORKPROC); enclosing fn DifOpReport(); expr P_NAME
Expected: none provable  (UNDECIDED)
  - no provable value: P_NAME defined nowhere in this TU headers (only <DifP.h> included); per-process build-time macro
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

#### t-dif/tool/diftest

### /home/chukyu/t-dif/tool/diftest/diftest101.c:57
Target: pmf_forkproc_H(...), arg 1 (FORKPROC); enclosing fn diftest101(); expr proc
Expected: none provable  (UNDECIDED)
  - no provable value: proc read from console via scanf (diftest101.c:39)
c-viz (arg 1): [none reported] status={"EXTERNAL": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-dif/tool/diftest/diftest900.c:45
Target: pmf_forkproc_H(...), arg 1 (FORKPROC); enclosing fn diftest900(); expr proc
Expected: none provable  (UNDECIDED)
  - no provable value: proc read from console via scanf (diftest900.c:42)
c-viz (arg 1): [none reported] status={"EXTERNAL": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

#### t-tmm/src/libtmm

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:169
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr mcs_a.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:183
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr mcs_b.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:267
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr mcs_b.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:294
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr mcs_a.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:314
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr kds_b.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:334
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr kds_a.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:352
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr dms.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:379
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr dms.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:394
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr tmcs.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:455
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr mcs_a.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:472
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr mcs_b.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:490
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr mcs_a.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInput.c:504
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInput(); expr mcs_b.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: cpuname struct filled by scn_getrcpu("ECS-A"/"ECS-B"/"KDS-A"/"KDS-B"/"DMS"/"TMCS",...) (TmmInput.c), runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInputK.c:105
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInputK(); expr kds_a.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: kds_a/kds_b.cpuname from scn_getrcpu, runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmInputK.c:115
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn TmmInputK(); expr kds_b.cpuname
Expected: none provable  (UNDECIDED)
  - no provable value: kds_a/kds_b.cpuname from scn_getrcpu, runtime SCN data
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

#### t-tmm/src/tmm000

### /home/chukyu/t-tmm/src/tmm000/tmm000_deamon.c:56
Target: pmf_forkproc_H(...), arg 1 (FORKPROC); enclosing fn tmm000_deamon(); expr tmm000_prc[cpukind][i].prgname
Expected: [tmm200d, tmm210d]  (PATH_VALID)
  - proof: tmm000_prc static table tmm000_main.c:22-41; only active entries {"tmm200d",0},{"tmm210d",1} (rest commented out); loop tmm000_deamon.c:43, else-branch (mode!=TMM_ON) line 56
c-viz (arg 1): [none reported] status={"EXTERNAL": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: medium
Cause tags: UNREACHABLE_ROOT_MODEL

#### t-tmm/src/tmm200d

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_trans.c:297
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn tmm200d_trans_send(); expr name1
Expected: none provable  (UNDECIDED)
  - no provable value: name1 = kds_a.cpuname/kds_b.cpuname (tmm200d_trans.c:132-217), runtime SCN data; call active (#else of #if 0 at :270)
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_trans.c:340
Target: pmf_forkprocbs_H(...), arg 1 (FORKPROC); enclosing fn tmm200d_trans_send(); expr name2
Expected: none provable  (UNDECIDED)
  - no provable value: name2 = kds_b.cpuname/kds_a.cpuname (tmm200d_trans.c:137+), runtime SCN data; call active (#else of #if 0 at :313)
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

#### t-dif/src/dif000

### /home/chukyu/t-dif/src/dif000/dif000Main.c:290
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:279 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2026] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:428
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:417 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:637
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2045]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:626 opens &fcb with DifBackUpNo; DifBackUpNo=2045 at t-dif/include/DifP.h:96; no intervening reopen of fcb
c-viz (arg 1): [2045] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2045] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:664
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif000BackUp(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:653 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:734
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif000TMNamaCreate(); expr &fcb
Expected: [2036]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:723 opens &fcb with DifF1FlugNo; DifF1FlugNo=2036 at t-dif/include/dif/Dif.h:47; no intervening reopen of fcb
c-viz (arg 1): [2036] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2036] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:874
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif000SagyoLockUpdate(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:863 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:907
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif000SagyoLockUpdate(); expr &fcb
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:890 opens &fcb with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:914
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif000SagyoLockUpdate(); expr &fcb
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:890 opens &fcb with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:917
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif000SagyoLockUpdate(); expr &fcb
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:890 opens &fcb with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1001
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif000SagyoLockClear(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:990 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1039
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif000SagyoLockClear(); expr &fcb
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1017 opens &fcb with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1042
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif000SagyoLockClear(); expr &fcb
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1017 opens &fcb with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1128
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif000LampInit(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1117 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1213
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif000F1Clear(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1202 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1240
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif000F1Clear(); expr &fcb
Expected: [2036]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1229 opens &fcb with DifF1FlugNo; DifF1FlugNo=2036 at t-dif/include/dif/Dif.h:47; no intervening reopen of fcb
c-viz (arg 1): [2036] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2036] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1309
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif000F1Clear(); expr &fcb
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1256 opens &fcb with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1311
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif000F1Clear(); expr &fcb
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1256 opens &fcb with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1391
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif000HyojiSeigyoRep(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1381 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2026] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1413
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif000HyojiSeigyoRep(); expr &fcb2
Expected: [2046]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1373 opens &fcb2 with DifHozonKoshoNo; DifHozonKoshoNo=2046 at t-dif/include/DifP.h:97; no intervening reopen of fcb2
c-viz (arg 1): [2046] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2046] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1422
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif000HyojiSeigyoRep(); expr &fcb2
Expected: [2046]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1373 opens &fcb2 with DifHozonKoshoNo; DifHozonKoshoNo=2046 at t-dif/include/DifP.h:97; no intervening reopen of fcb2
c-viz (arg 1): [2046] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2046] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1428
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif000HyojiSeigyoRep(); expr &fcb2
Expected: [2046]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1373 opens &fcb2 with DifHozonKoshoNo; DifHozonKoshoNo=2046 at t-dif/include/DifP.h:97; no intervening reopen of fcb2
c-viz (arg 1): [2046] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2046] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif000/dif000Main.c:1503
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif000HyojiSvmTmRep(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/src/dif000/dif000Main.c:1493 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2026] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif001

### /home/chukyu/t-dif/src/dif001/dif001Main.c:186
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2021]  (PATH_VALID)
  - proof: open at t-dif/src/dif001/dif001Main.c:175 opens &fcb with DifDefineNo; DifDefineNo=2021 at t-dif/include/DifP.h:75; no intervening reopen of fcb
c-viz (arg 1): [2021] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2021] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif001/dif001Main.c:213
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2031]  (PATH_VALID)
  - proof: open at t-dif/src/dif001/dif001Main.c:202 opens &fcb with DifItcOyaDefNo; DifItcOyaDefNo=2031 at t-dif/include/DifP.h:84; no intervening reopen of fcb
c-viz (arg 1): [2031] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2031] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif001/dif001Main.c:240
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif001/dif001Main.c:229 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif110d

### /home/chukyu/t-dif/src/dif110d/dif110dReturnInit.c:167
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif110dReturnInit(); expr &fcb
Expected: [2034]  (PATH_VALID)
  - proof: open at t-dif/src/dif110d/dif110dReturnInit.c:156 opens &fcb with DifSsAdressDefNo; DifSsAdressDefNo=2034 at t-dif/include/DifP.h:87; no intervening reopen of fcb
c-viz (arg 1): [2034] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2034] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif112d

### /home/chukyu/t-dif/src/dif112d/dif112dReturnInit.c:160
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif112dReturnInit(); expr &fcb
Expected: [2034]  (PATH_VALID)
  - proof: open at t-dif/src/dif112d/dif112dReturnInit.c:149 opens &fcb with DifSsAdressDefNo; DifSsAdressDefNo=2034 at t-dif/include/DifP.h:87; no intervening reopen of fcb
c-viz (arg 1): [2034] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2034] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif115d

### /home/chukyu/t-dif/src/dif115d/dif115dMain.c:101
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2034]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dMain.c:90 opens &fcb with DifSsAdressDefNo; DifSsAdressDefNo=2034 at t-dif/include/DifP.h:87; no intervening reopen of fcb
c-viz (arg 1): [2034] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2034] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dMain.c:147
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dMain.c:136 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dMain.c:220
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif115dProc(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dMain.c:209 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2024] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dModeEnd.c:158
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif115dModeEnd(); expr &fcb
Expected: [2025]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dModeEnd.c:150 opens &fcb with DifModeEndMngNo; DifModeEndMngNo=2025 at t-dif/include/DifP.h:78; no intervening reopen of fcb
c-viz (arg 1): [2025] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2025] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dModeEnd.c:200
Target: mpf_mfs_open(...), arg 3 (READ); enclosing fn FileRead(); expr file_no
Expected: [2025, 2031, 2032, 2033]  (PATH_VALID)
  - proof: target is the mpf_mfs_open itself (arg3=file_no); callers FileRead() dif115dModeEnd.c:45,49,53,57 pass DifModeEndMngNo(2025)/DifItcOyaDefNo(2031)/DifDvHasIdxDefNo(2032)/DifDvHasDefNo(2033)
c-viz (arg 3): [2025, 2031, 2032, 2033] status={"EXACT": 4} -> part of BOTH_CORRECT_SAME
legacy (arg 3): [2025, 2031, 2032, 2033] status={"ADDED": 4, "OK_MACRO": 4} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dModeEnd.c:208
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn FileRead(); expr &fcb
Expected: [2025, 2031, 2032, 2033]  (PATH_VALID)
  - proof: helper FileRead(int file_no,...) opens at dif115dModeEnd.c:200; callers :45/:49/:53/:57 pass DifModeEndMngNo(2025), DifItcOyaDefNo(2031), DifDvHasIdxDefNo(2032), DifDvHasDefNo(2033)
c-viz (arg 1): [2025, 2031, 2032, 2033] status={"EXACT": 4} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2025, 2031, 2032, 2033] status={"ADDED": 1, "CONFLICT": 3, "OK_MACRO": 4} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dRtnChk.c:141
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif115dRtnChk(); expr &def_fcb
Expected: [2021]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dRtnChk.c:122 opens &def_fcb with DifDefineNo; DifDefineNo=2021 at t-dif/include/DifP.h:75; no intervening reopen of def_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2021] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dRtnChk.c:149
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif115dRtnChk(); expr &mng_fcb
Expected: [2025]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dRtnChk.c:129 opens &mng_fcb with DifModeEndMngNo; DifModeEndMngNo=2025 at t-dif/include/DifP.h:78; no intervening reopen of mng_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2025] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dRtnChk.c:914
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif115dInitEndReset(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dRtnChk.c:905 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2026] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dSend.c:100
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif115dSend(); expr &fcb
Expected: [2031]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dSend.c:92 opens &fcb with DifItcOyaDefNo; DifItcOyaDefNo=2031 at t-dif/include/DifP.h:84; no intervening reopen of fcb
c-viz (arg 1): [2031] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2031] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dSend.c:122
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif115dSend(); expr &fcb
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dSend.c:114 opens &fcb with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb
c-viz (arg 1): [2032] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2032] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dSend.c:144
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif115dSend(); expr &fcb
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/dif115d/dif115dSend.c:136 opens &fcb with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb
c-viz (arg 1): [2033] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2033] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif115d/dif115dSend.c:1033
Target: mpf_mfs_open(...), arg 3 (READ); enclosing fn dif115dMakeITCPaket(); expr DifOutputNo
Expected: none provable  (UNDECIDED)
  - no provable value: no concrete value provable from in-tree source
c-viz (arg 3): [none reported] status={"EXTERNAL": 1} -> part of UNDECIDED
legacy (arg 3): [none reported] status={"OK_CONST": 1} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-dif/src/dif115d/dif115dSend.c:1041
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif115dMakeITCPaket(); expr &fcb
Expected: none provable  (UNDECIDED)
  - no provable value: opened with DifOutputNo (dif115dSend.c:1033) but DifOutputNo is defined nowhere in /home/chukyu (external macro)
c-viz (arg 1): [none reported] status={"EXTERNAL": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={"OK_CONST": 1} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-dif/src/dif115d/dif115dSend.c:1086
Target: mpf_mfs_open(...), arg 3 (READ); enclosing fn dif115dClrITCPaket(); expr DifOutputNo
Expected: none provable  (UNDECIDED)
  - no provable value: no concrete value provable from in-tree source
c-viz (arg 3): [none reported] status={"EXTERNAL": 1} -> part of UNDECIDED
legacy (arg 3): [none reported] status={"OK_CONST": 1} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-dif/src/dif115d/dif115dSend.c:1094
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif115dClrITCPaket(); expr &fcb
Expected: none provable  (UNDECIDED)
  - no provable value: opened with DifOutputNo (dif115dSend.c:1086) but DifOutputNo defined nowhere in /home/chukyu
c-viz (arg 1): [none reported] status={"EXTERNAL": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={"OK_CONST": 1} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

#### t-dif/src/dif120d

### /home/chukyu/t-dif/src/dif120d/dif120dGetPtr.c:57
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif120dGetPtr(); expr &fcb
Expected: [2035]  (PATH_VALID)
  - proof: open at t-dif/src/dif120d/dif120dGetPtr.c:46 opens &fcb with DifSVNamaDataNo; DifSVNamaDataNo=2035 at t-dif/include/dif/Dif.h:46; no intervening reopen of fcb
c-viz (arg 1): [2035] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2035] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif120d/dif120dGetPtr.c:84
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif120dGetPtr(); expr &fcb
Expected: [2045]  (PATH_VALID)
  - proof: open at t-dif/src/dif120d/dif120dGetPtr.c:73 opens &fcb with DifBackUpNo; DifBackUpNo=2045 at t-dif/include/DifP.h:96; no intervening reopen of fcb
c-viz (arg 1): [2045] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2045] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif120d/dif120dMain.c:157
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn dif120dproc(); expr DifSVJohenQNo
Expected: [939]  (PATH_VALID)
  - proof: direct macro arg DifSVJohenQNo at target line; define at t-dif/include/dif/Dif.h:48
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [939] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif120d/dif120dMain.c:373
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn dif120dJyouhen(); expr &fcb
Expected: [2030]  (PATH_VALID)
  - proof: open at t-dif/src/dif120d/dif120dMain.c:371 opens &fcb with DifGamenDefNo; DifGamenDefNo=2030 at t-dif/include/DifP.h:83; no intervening reopen of fcb
c-viz (arg 1): [2030] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2030] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif120d/dif120dMain.c:631
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn dif120dInit(); expr &fcb
Expected: [2030]  (PATH_VALID)
  - proof: open at t-dif/src/dif120d/dif120dMain.c:629 opens &fcb with DifGamenDefNo; DifGamenDefNo=2030 at t-dif/include/DifP.h:83; no intervening reopen of fcb
c-viz (arg 1): [2030] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2030] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif120d/dif120dOffJh.c:163
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn _dif120dOffJhDlyGet(); expr &DefFcb
Expected: [2021]  (PATH_VALID)
  - proof: open at t-dif/src/dif120d/dif120dOffJh.c:151 opens &DefFcb with DifDefineNo; DifDefineNo=2021 at t-dif/include/DifP.h:75; no intervening reopen of DefFcb
c-viz (arg 1): [2021] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2021] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif120d/dif120dOffJh.c:215
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn _dif120dOffJhMngSet(); expr &MngFcb
Expected: [2047]  (PATH_VALID)
  - proof: open at t-dif/src/dif120d/dif120dOffJh.c:201 opens &MngFcb with DifOffJohenMngNo; DifOffJohenMngNo=2047 at t-dif/include/DifP.h:107; no intervening reopen of MngFcb
c-viz (arg 1): [2047] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2047] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif120d/dif120dOffJh.c:283
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn _dif120dOffJhMngSet(); expr &MngFcb
Expected: [2047]  (PATH_VALID)
  - proof: open at t-dif/src/dif120d/dif120dOffJh.c:201 opens &MngFcb with DifOffJohenMngNo; DifOffJohenMngNo=2047 at t-dif/include/DifP.h:107; no intervening reopen of MngFcb
c-viz (arg 1): [2047] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2047] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif121d

### /home/chukyu/t-dif/src/dif121d/dif121dGetPtr.c:63
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif121dGetPtr(); expr &fcb
Expected: [2036]  (PATH_VALID)
  - proof: open at t-dif/src/dif121d/dif121dGetPtr.c:52 opens &fcb with DifF1FlugNo; DifF1FlugNo=2036 at t-dif/include/dif/Dif.h:47; no intervening reopen of fcb
c-viz (arg 1): [2036] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2036] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif122d

### /home/chukyu/t-dif/src/dif122d/dif122dMain.c:155
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn main(); expr &fcb
Expected: [2034]  (PATH_VALID)
  - proof: open at t-dif/src/dif122d/dif122dMain.c:144 opens &fcb with DifSsAdressDefNo; DifSsAdressDefNo=2034 at t-dif/include/DifP.h:87; no intervening reopen of fcb
c-viz (arg 1): [2034] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2034] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif122d/dif122dMain.c:246
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif122dproc(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/src/dif122d/dif122dMain.c:234 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2026] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif122d/dif122dMain.c:271
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif122dproc(); expr &fcb1
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/dif122d/dif122dMain.c:259 opens &fcb1 with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb1
c-viz (arg 1): [2032] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2032] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif122d/dif122dMain.c:301
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif122dproc(); expr &fcb1
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/dif122d/dif122dMain.c:289 opens &fcb1 with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb1
c-viz (arg 1): [2033] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2033] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif122d/dif122dMain.c:326
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn dif122dproc(); expr DifKoshoJohenQNo
Expected: [941]  (PATH_VALID)
  - proof: direct macro arg DifKoshoJohenQNo at target line; define at t-dif/include/DifP.h:127
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [941] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif122d/dif122dMain.c:365
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif122dproc(); expr &fcb5
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif122d/dif122dMain.c:356 opens &fcb5 with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb5
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif122d/dif122dMain.c:1263
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif122did6(); expr &fcb2
Expected: [2046]  (PATH_VALID)
  - proof: open at t-dif/src/dif122d/dif122dMain.c:1259 opens &fcb2 with DifHozonKoshoNo; DifHozonKoshoNo=2046 at t-dif/include/DifP.h:97; no intervening reopen of fcb2
c-viz (arg 1): [2046] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2046] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif122d/dif122dMain.c:1265
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif122did6(); expr &fcb2
Expected: [2046]  (PATH_VALID)
  - proof: open at t-dif/src/dif122d/dif122dMain.c:1259 opens &fcb2 with DifHozonKoshoNo; DifHozonKoshoNo=2046 at t-dif/include/DifP.h:97; no intervening reopen of fcb2
c-viz (arg 1): [2046] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2046] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif123d

### /home/chukyu/t-dif/src/dif123d/dif123dSndJh.c:130
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn _dif123dGetMng(); expr &MngFcb
Expected: [2047]  (PATH_VALID)
  - proof: open at t-dif/src/dif123d/dif123dSndJh.c:116 opens &MngFcb with DifOffJohenMngNo; DifOffJohenMngNo=2047 at t-dif/include/DifP.h:107; no intervening reopen of MngFcb
c-viz (arg 1): [2047] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2047] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif130d

### /home/chukyu/t-dif/src/dif130d/dif130Deque.c:269
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif130dDeqInputQ(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/dif130d/dif130Deque.c:258 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif130d/dif130Deque.c:295
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif130dDeqInputQ(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif130d/dif130Deque.c:287 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif130d/dif130Deque.c:405
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif130dDeqRcvQ(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/dif130d/dif130Deque.c:394 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif130d/dif130Deque.c:442
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif130dDeqRcvQ(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif130d/dif130Deque.c:434 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif130d/dif130Event.c:68
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif130SetTime(); expr &fcb
Expected: [2021]  (PATH_VALID)
  - proof: open at t-dif/src/dif130d/dif130Event.c:58 opens &fcb with DifDefineNo; DifDefineNo=2021 at t-dif/include/DifP.h:75; no intervening reopen of fcb
c-viz (arg 1): [2021] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif130d/dif130Event.c:144
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn dif130Timeout(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/dif130d/dif130Event.c:133 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2024] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif130d/dif130Event.c:224
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif130RtryOver(); expr &fcb
Expected: [2021]  (PATH_VALID)
  - proof: open at t-dif/src/dif130d/dif130Event.c:214 opens &fcb with DifDefineNo; DifDefineNo=2021 at t-dif/include/DifP.h:75; no intervening reopen of fcb
c-viz (arg 1): [2021] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2021] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif200d

### /home/chukyu/t-dif/src/dif200d/dif200dGetPtr.c:57
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif200dGetPtr(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dGetPtr.c:46 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dMain.c:175
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn dif200dproc(); expr DifKoshoInfoQNo
Expected: [942]  (PATH_VALID)
  - proof: direct macro arg DifKoshoInfoQNo at target line; define at t-dif/include/DifP.h:128
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [942] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dMain.c:453
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif200dKokyokuRep(); expr &fcb1
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dMain.c:445 opens &fcb1 with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb1
c-viz (arg 1): [2032] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2032] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dMain.c:474
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif200dKokyokuRep(); expr &fcb1
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dMain.c:466 opens &fcb1 with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb1
c-viz (arg 1): [2033] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2033] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dOutMsg.c:280
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif200dRtrySet(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dOutMsg.c:269 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2024] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dStatus.c:91
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif200dStatus(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dStatus.c:80 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dStatus.c:168
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif200dStatus(); expr &fcb2
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dStatus.c:103 opens &fcb2 with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb2
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dStatus.c:170
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif200dStatus(); expr &fcb2
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dStatus.c:103 opens &fcb2 with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb2
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dSyogaiRep.c:96
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif200dSyogaiRep(); expr &fcb
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dSyogaiRep.c:89 opens &fcb with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb
c-viz (arg 1): [2032] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2032] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dSyogaiRep.c:115
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif200dSyogaiRep(); expr &fcb
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dSyogaiRep.c:108 opens &fcb with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb
c-viz (arg 1): [2033] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2033] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif200d/dif200dSyogaiRep.c:134
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn Dif200dSyogaiRep(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/src/dif200d/dif200dSyogaiRep.c:127 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2026] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif210d

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:192
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif210LockOp(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:181 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:268
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif210LockOp(); expr &fcb2
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:203 opens &fcb2 with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb2
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:270
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif210LockOp(); expr &fcb2
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:203 opens &fcb2 with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb2
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:453
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif210TestModeOp(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:442 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:609
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif210InitSetOp(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:598 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:665
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif210InitSetOp(); expr &fcb1
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:657 opens &fcb1 with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb1
c-viz (arg 1): [2032] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:686
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif210InitSetOp(); expr &fcb1
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:678 opens &fcb1 with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb1
c-viz (arg 1): [2033] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:898
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif210InitReq(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:887 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:958
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif210InitReq(); expr &fcb2
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:909 opens &fcb2 with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb2
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Deque.c:960
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif210InitReq(); expr &fcb2
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Deque.c:909 opens &fcb2 with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb2
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Event.c:112
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif210DisConInit(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Event.c:101 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2022] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Event.c:142
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif210DisConInit(); expr &fcb2
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Event.c:123 opens &fcb2 with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb2
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif210d/dif210Event.c:148
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif210DisConInit(); expr &fcb2
Expected: [2023]  (PATH_VALID)
  - proof: open at t-dif/src/dif210d/dif210Event.c:123 opens &fcb2 with DifHozonStatusNo; DifHozonStatusNo=2023 at t-dif/include/DifP.h:76; no intervening reopen of fcb2
c-viz (arg 1): [2023] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2023] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif700

### /home/chukyu/t-dif/src/dif700/dif700getdata.c:399
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn dif700fileread(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/dif700/dif700getdata.c:392 opens &fcb with DifStatusNo=2022 (define t-dif/include/dif/Dif.h:45); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif700/dif700getdata.c:414
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn dif700deffileread(); expr &fcb
Expected: [2030]  (PATH_VALID)
  - proof: open at t-dif/src/dif700/dif700getdata.c:407 opens &fcb with DifGamenDefNo=2030 (define t-dif/include/DifP.h:83); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

#### t-dif/src/dif900

### /home/chukyu/t-dif/src/dif900/dif900IntBackUp.c:86
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitBackUp(); expr &fcb
Expected: [2045]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntBackUp.c:75 opens &fcb with DifBackUpNo; DifBackUpNo=2045 at t-dif/include/DifP.h:96; no intervening reopen of fcb
c-viz (arg 1): [2045] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2045] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntChchg.c:86
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitChChangeInf(); expr &fcb
Expected: [2027]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntChchg.c:75 opens &fcb with DifChChangeInfNo; DifChChangeInfNo=2027 at t-dif/include/DifP.h:80; no intervening reopen of fcb
c-viz (arg 1): [2027] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2027] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:181
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitDllData(); expr &fcb
Expected: [2028]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:170 opens &fcb with DifDvChangeInfNo; DifDvChangeInfNo=2028 at t-dif/include/DifP.h:81; no intervening reopen of fcb
c-viz (arg 1): [2028] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2028] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:620
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900IntSclDll(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:609 opens &fcb with DifSclDllDbNo; DifSclDllDbNo=2041 at t-dif/include/DifP.h:92; no intervening reopen of fcb
c-viz (arg 1): [2041] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2041] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:621
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900IntSclDll(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:609 opens &fcb with DifSclDllDbNo; DifSclDllDbNo=2041 at t-dif/include/DifP.h:92; no intervening reopen of fcb
c-viz (arg 1): [2041] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2041] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:667
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900IntSclDll(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:609 opens &fcb with DifSclDllDbNo; DifSclDllDbNo=2041 at t-dif/include/DifP.h:92; no intervening reopen of fcb
c-viz (arg 1): [2041] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2041] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:673
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900IntSclDll(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:609 opens &fcb with DifSclDllDbNo; DifSclDllDbNo=2041 at t-dif/include/DifP.h:92; no intervening reopen of fcb
c-viz (arg 1): [2041] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2041] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:744
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SvWorkTblSave(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:733 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:762
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SvWorkTblSave(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:733 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:834
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900SvWorkTblSave(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:733 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:842
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900SvWorkTblSave(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:733 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:959
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900TmWorkTblSave(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:948 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:977
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900TmWorkTblSave(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:948 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1049
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900TmWorkTblSave(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:948 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1057
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900TmWorkTblSave(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:948 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1166
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SclDbLastUpdate(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1155 opens &fcb with DifSclDllDbNo; DifSclDllDbNo=2041 at t-dif/include/DifP.h:92; no intervening reopen of fcb
c-viz (arg 1): [2041] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2041] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1176
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SclDbLastUpdate(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1155 opens &fcb with DifSclDllDbNo; DifSclDllDbNo=2041 at t-dif/include/DifP.h:92; no intervening reopen of fcb
c-viz (arg 1): [2041] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2041] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1179
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SclDbLastUpdate(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1155 opens &fcb with DifSclDllDbNo; DifSclDllDbNo=2041 at t-dif/include/DifP.h:92; no intervening reopen of fcb
c-viz (arg 1): [2041] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2041] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1184
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900SclDbLastUpdate(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1155 opens &fcb with DifSclDllDbNo; DifSclDllDbNo=2041 at t-dif/include/DifP.h:92; no intervening reopen of fcb
c-viz (arg 1): [2041] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2041] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1243
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SvDbLastUpdate(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1232 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1253
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SvDbLastUpdate(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1232 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1258
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900SvDbLastUpdate(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1232 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1314
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900TmDbLastUpdate(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1303 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1323
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900TmDbLastUpdate(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1303 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1328
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900TmDbLastUpdate(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1303 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1389
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SvDbKanNinShite(); expr &fcb0
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1382 opens &fcb0 with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb0
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1421
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SvDbKanNinShite(); expr &fcb0
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1414 opens &fcb0 with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb0
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1441
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900SvDbKanNinShite(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1434 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1462
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900SvDbKanNinShite(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1455 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1470
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900SvDbKanNinShite(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1455 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1497
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900SvDbKanNinShite(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1490 opens &fcb with DifSvDllDbNo; DifSvDllDbNo=2039 at t-dif/include/DifP.h:90; no intervening reopen of fcb
c-viz (arg 1): [2039] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2039] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1566
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900TmDbKanNinShite(); expr &fcb0
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1559 opens &fcb0 with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb0
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1597
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900TmDbKanNinShite(); expr &fcb0
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1590 opens &fcb0 with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb0
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1617
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900TmDbKanNinShite(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1610 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1638
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn Dif900TmDbKanNinShite(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1631 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1646
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900TmDbKanNinShite(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1631 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDll.c:1672
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn Dif900TmDbKanNinShite(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDll.c:1665 opens &fcb with DifTmDllDbNo; DifTmDllDbNo=2040 at t-dif/include/DifP.h:91; no intervening reopen of fcb
c-viz (arg 1): [2040] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2040] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDvHas.c:80
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitDvHasDef(); expr &fcb
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDvHas.c:69 opens &fcb with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb
c-viz (arg 1): [2033] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2033] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDvHas.c:102
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitDvHasDef(); expr &fcb2
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDvHas.c:91 opens &fcb2 with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb2
c-viz (arg 1): [2032] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2032] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntDvchg.c:77
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitDvChangeInf(); expr &fcb
Expected: [2028]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntDvchg.c:66 opens &fcb with DifDvChangeInfNo; DifDvChangeInfNo=2028 at t-dif/include/DifP.h:81; no intervening reopen of fcb
c-viz (arg 1): [2028] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2028] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntGamen.c:99
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitGamenDef(); expr &fcb
Expected: [2030]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntGamen.c:88 opens &fcb with DifGamenDefNo; DifGamenDefNo=2030 at t-dif/include/DifP.h:83; no intervening reopen of fcb
c-viz (arg 1): [2030] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2030] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntItcOya.c:69
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitItcOyaDef(); expr &fcb
Expected: [2031]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntItcOya.c:58 opens &fcb with DifItcOyaDefNo; DifItcOyaDefNo=2031 at t-dif/include/DifP.h:84; no intervening reopen of fcb
c-viz (arg 1): [2031] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2031] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntNwchg.c:81
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitNwChangeInf(); expr &fcb
Expected: [2029]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntNwchg.c:70 opens &fcb with DifNwChangeInfNo; DifNwChangeInfNo=2029 at t-dif/include/DifP.h:82; no intervening reopen of fcb
c-viz (arg 1): [2029] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2029] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntSpeDef.c:232
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn dif900IntSpeDef(); expr &sFcb
Expected: [2048]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntSpeDef.c:106 opens &sFcb with DifSpeDvDefNo; DifSpeDvDefNo=2048 at t-dif/include/DifP.h:111; no intervening reopen of sFcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2048] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif900/dif900IntSsDef.c:69
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn Dif900InitSsAdressDef(); expr &fcb
Expected: [2034]  (PATH_VALID)
  - proof: open at t-dif/src/dif900/dif900IntSsDef.c:58 opens &fcb with DifSsAdressDefNo; DifSsAdressDefNo=2034 at t-dif/include/DifP.h:87; no intervening reopen of fcb
c-viz (arg 1): [2034] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2034] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/dif901

### /home/chukyu/t-dif/src/dif901/dif901IntBackUp.c:96
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitBackUp(); expr &fcb
Expected: [2045]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntBackUp.c:85 opens &fcb with DifBackUpNo=2045 (define t-dif/include/DifP.h:96); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntChchg.c:91
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitChChangeInf(); expr &fcb
Expected: [2027]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntChchg.c:80 opens &fcb with DifChChangeInfNo; DifChChangeInfNo=2027 at t-dif/include/DifP.h:80; no intervening reopen of fcb
c-viz (arg 1): [2027] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2027] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:211
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitDllData(); expr &fcb
Expected: [2028]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:200 opens &fcb with DifDvChangeInfNo=2028 (define t-dif/include/DifP.h:81); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:656
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901IntSclDll(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:645 opens &fcb with DifSclDllDbNo=2041 (define t-dif/include/DifP.h:92); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:657
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901IntSclDll(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:645 opens &fcb with DifSclDllDbNo=2041 (define t-dif/include/DifP.h:92); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:703
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901IntSclDll(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:645 opens &fcb with DifSclDllDbNo=2041 (define t-dif/include/DifP.h:92); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:709
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901IntSclDll(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:645 opens &fcb with DifSclDllDbNo=2041 (define t-dif/include/DifP.h:92); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:780
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SvWorkTblSave(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:769 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:798
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SvWorkTblSave(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:769 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:870
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901SvWorkTblSave(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:769 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:878
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901SvWorkTblSave(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:769 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:995
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901TmWorkTblSave(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:984 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1013
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901TmWorkTblSave(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:984 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1085
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901TmWorkTblSave(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:984 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1093
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901TmWorkTblSave(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:984 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1202
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SclDbLastUpdate(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1191 opens &fcb with DifSclDllDbNo=2041 (define t-dif/include/DifP.h:92); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1212
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SclDbLastUpdate(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1191 opens &fcb with DifSclDllDbNo=2041 (define t-dif/include/DifP.h:92); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1215
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SclDbLastUpdate(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1191 opens &fcb with DifSclDllDbNo=2041 (define t-dif/include/DifP.h:92); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1220
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901SclDbLastUpdate(); expr &fcb
Expected: [2041]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1191 opens &fcb with DifSclDllDbNo=2041 (define t-dif/include/DifP.h:92); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1291
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SvDbLastUpdate(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1280 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1359
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901TmDbLastUpdate(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1348 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1430
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SvDbKanNinShite(); expr &fcb0
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1423 opens &fcb0 with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1462
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SvDbKanNinShite(); expr &fcb0
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1455 opens &fcb0 with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1479
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901SvDbKanNinShite(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1472 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1500
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901SvDbKanNinShite(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1493 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1508
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901SvDbKanNinShite(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1493 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1534
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901SvDbKanNinShite(); expr &fcb
Expected: [2039]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1527 opens &fcb with DifSvDllDbNo=2039 (define t-dif/include/DifP.h:90); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1608
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901TmDbKanNinShite(); expr &fcb0
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1601 opens &fcb0 with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1639
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901TmDbKanNinShite(); expr &fcb0
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1632 opens &fcb0 with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1656
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901TmDbKanNinShite(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1649 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1677
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif901TmDbKanNinShite(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1670 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1685
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901TmDbKanNinShite(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1670 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDll.c:1710
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn dif901TmDbKanNinShite(); expr &fcb
Expected: [2040]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDll.c:1703 opens &fcb with DifTmDllDbNo=2040 (define t-dif/include/DifP.h:91); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/dif901/dif901IntDvHas.c:82
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitDvHasDef(); expr &fcb
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDvHas.c:71 opens &fcb with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb
c-viz (arg 1): [2033] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2033] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif901/dif901IntDvHas.c:104
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitDvHasDef(); expr &fcb2
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDvHas.c:93 opens &fcb2 with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb2
c-viz (arg 1): [2032] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2032] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif901/dif901IntDvchg.c:80
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitDvChangeInf(); expr &fcb
Expected: [2028]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntDvchg.c:69 opens &fcb with DifDvChangeInfNo; DifDvChangeInfNo=2028 at t-dif/include/DifP.h:81; no intervening reopen of fcb
c-viz (arg 1): [2028] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2028] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif901/dif901IntGamen.c:101
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitGamenDef(); expr &fcb
Expected: [2030]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntGamen.c:90 opens &fcb with DifGamenDefNo; DifGamenDefNo=2030 at t-dif/include/DifP.h:83; no intervening reopen of fcb
c-viz (arg 1): [2030] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2030] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif901/dif901IntItcOya.c:71
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitItcOyaDef(); expr &fcb
Expected: [2031]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntItcOya.c:60 opens &fcb with DifItcOyaDefNo; DifItcOyaDefNo=2031 at t-dif/include/DifP.h:84; no intervening reopen of fcb
c-viz (arg 1): [2031] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2031] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif901/dif901IntNwchg.c:82
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitNwChangeInf(); expr &fcb
Expected: [2029]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntNwchg.c:71 opens &fcb with DifNwChangeInfNo; DifNwChangeInfNo=2029 at t-dif/include/DifP.h:82; no intervening reopen of fcb
c-viz (arg 1): [2029] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2029] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif901/dif901IntSpeDef.c:233
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn dif901IntSpeDef(); expr &sFcb
Expected: [2048]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntSpeDef.c:108 opens &sFcb with DifSpeDvDefNo; DifSpeDvDefNo=2048 at t-dif/include/DifP.h:111; no intervening reopen of sFcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2048] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif901/dif901IntSsDef.c:71
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn dif901InitSsAdressDef(); expr &fcb
Expected: [2034]  (PATH_VALID)
  - proof: open at t-dif/src/dif901/dif901IntSsDef.c:60 opens &fcb with DifSsAdressDefNo; DifSsAdressDefNo=2034 at t-dif/include/DifP.h:87; no intervening reopen of fcb
c-viz (arg 1): [2034] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2034] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-dif/src/libdif

### /home/chukyu/t-dif/src/libdif/difGetF1Data.c:66
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn DifGetF1Data(); expr &fcb
Expected: [2036]  (PATH_VALID)
  - proof: open at t-dif/src/libdif/difGetF1Data.c:55 opens &fcb with DifF1FlugNo=2036 (define t-dif/include/dif/Dif.h:47); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdif/difGetKosho.c:71
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn DifGetKosho(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/libdif/difGetKosho.c:61 opens &fcb with DifStatusNo=2022 (define t-dif/include/dif/Dif.h:45); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdif/difGetKouikiSel.c:45
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn DifGetKouikiSel(); expr &fcb_Sel
Expected: [2049]  (PATH_VALID)
  - proof: open at t-dif/src/libdif/difGetKouikiSel.c:42 opens &fcb_Sel with DifKouikiSelNo=2049 (define t-dif/include/dif/Dif.h:53); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdif/difGetNamaData2.c:72
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn DifGetNamaData2(); expr &fcb
Expected: [2035]  (PATH_VALID)
  - proof: open at t-dif/src/libdif/difGetNamaData2.c:61 opens &fcb with DifSVNamaDataNo=2035 (define t-dif/include/dif/Dif.h:46); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdif/difGetNamaData3.c:72
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn DifGetNamaData3(); expr &fcb
Expected: [2035]  (PATH_VALID)
  - proof: open at t-dif/src/libdif/difGetNamaData3.c:61 opens &fcb with DifSVNamaDataNo=2035 (define t-dif/include/dif/Dif.h:46); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdif/difGetNamaData4.c:127
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn DifGetNamaData4(); expr &fcb
Expected: [2035]  (PATH_VALID)
  - proof: open at t-dif/src/libdif/difGetNamaData4.c:119 opens &fcb with DifSVNamaDataNo=2035 (define t-dif/include/dif/Dif.h:46); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdif/difSetF1Data.c:64
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn DifSetF1Data(); expr &fcb
Expected: [2036]  (PATH_VALID)
  - proof: open at t-dif/src/libdif/difSetF1Data.c:53 opens &fcb with DifF1FlugNo=2036 (define t-dif/include/dif/Dif.h:47); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdif/difSetNamaData.c:74
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn DifSetNamaData(); expr &fcb
Expected: [2035]  (PATH_VALID)
  - proof: open at t-dif/src/libdif/difSetNamaData.c:63 opens &fcb with DifSVNamaDataNo; DifSVNamaDataNo=2035 at t-dif/include/dif/Dif.h:46; no intervening reopen of fcb
c-viz (arg 1): [2035] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

#### t-dif/src/libdifP

### /home/chukyu/t-dif/src/libdifP/difEnqFork.c:68
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifEnqFork(); expr &fcb
Expected: [2021]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difEnqFork.c:57 opens &fcb with DifDefineNo; DifDefineNo=2021 at t-dif/include/DifP.h:75; no intervening reopen of fcb
c-viz (arg 1): [2021] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difGetChNo.c:63
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifGetChNo(); expr &fcb
Expected: [2027]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetChNo.c:52 opens &fcb with DifChChangeInfNo; DifChChangeInfNo=2027 at t-dif/include/DifP.h:80; no intervening reopen of fcb
c-viz (arg 1): [2027] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difGetDvNo.c:65
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifGetDvNo(); expr &fcb
Expected: [2028]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetDvNo.c:54 opens &fcb with DifDvChangeInfNo; DifDvChangeInfNo=2028 at t-dif/include/DifP.h:81; no intervening reopen of fcb
c-viz (arg 1): [2028] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difGetShu.c:52
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifGetShu(); expr &fcb
Expected: [2031]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetShu.c:45 opens &fcb with DifItcOyaDefNo; DifItcOyaDefNo=2031 at t-dif/include/DifP.h:84; no intervening reopen of fcb
c-viz (arg 1): [2031] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difGetShu.c:71
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifGetShu(); expr &fcb
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetShu.c:64 opens &fcb with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb
c-viz (arg 1): [2032] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difGetShu.c:90
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifGetShu(); expr &fcb
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetShu.c:83 opens &fcb with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb
c-viz (arg 1): [2033] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difGetStatus.c:72
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifGetStatus(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetStatus.c:61 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difGetTime.c:105
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn dif_deffileread(); expr &fcb
Expected: [2030]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetTime.c:98 opens &fcb with DifGamenDefNo=2030 (define t-dif/include/DifP.h:83); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdifP/difGetTime.c:123
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif_dllheadfileread(); expr &fcb
Expected: [2037]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetTime.c:116 opens &fcb with DifDllMngNo=2037 (define t-dif/include/DifP.h:88); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdifP/difGetTime.c:140
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn dif_dllfileread(); expr &fcb
Expected: [2037]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difGetTime.c:133 opens &fcb with DifDllMngNo=2037 (define t-dif/include/DifP.h:88); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdifP/difItcRtn.c:96
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn DifItcRtn(); expr &fcb
Expected: [2037]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difItcRtn.c:83 opens &fcb with DifDllMngNo=2037 (define t-dif/include/DifP.h:88); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdifP/difItcRtn.c:135
Target: mpf_mfs_addque(...), arg 2 (ADDQUE); enclosing fn DifItcRtn(); expr DifDllInfQNo
Expected: [943]  (PATH_VALID)
  - proof: direct macro arg DifDllInfQNo at target line; define at t-dif/include/DifP.h:129
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 2): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dif/src/libdifP/difKosyoRcv.c:89
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifKosyoRcv(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difKosyoRcv.c:78 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difKosyoReq.c:127
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifKosyoReq(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difKosyoReq.c:116 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difPutLamp.c:101
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn DifPutLamp(); expr &fcb
Expected: [2030]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difPutLamp.c:90 opens &fcb with DifGamenDefNo; DifGamenDefNo=2030 at t-dif/include/DifP.h:83; no intervening reopen of fcb
c-viz (arg 1): [2030] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSikenRcv.c:83
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifSikenRcv(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSikenRcv.c:72 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSikenReq.c:106
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifSikenReq(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSikenReq.c:94 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSpeDvChk.c:69
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn DifSpeDvChk(); expr &sFcb
Expected: [2048]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSpeDvChk.c:61 opens &sFcb with DifSpeDvDefNo; DifSpeDvDefNo=2048 at t-dif/include/DifP.h:111; no intervening reopen of sFcb
c-viz (arg 1): [2048] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvRcv.c:98
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifSvDvRcv(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvRcv.c:87 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:338
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifBitSet(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:327 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:417
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifBitSet(); expr &fcb
Expected: [2024]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:406 opens &fcb with DifSendMngNo; DifSendMngNo=2024 at t-dif/include/DifP.h:77; no intervening reopen of fcb
c-viz (arg 1): [2024] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:444
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifBitSet(); expr &fcb1
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:436 opens &fcb1 with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb1
c-viz (arg 1): [2022] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:510
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifOyaReq(); expr &fcb1
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:502 opens &fcb1 with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb1
c-viz (arg 1): [2032] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:532
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifOyaReq(); expr &fcb1
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:524 opens &fcb1 with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb1
c-viz (arg 1): [2033] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:615
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifAllReq(); expr &fcb1
Expected: [2031]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:607 opens &fcb1 with DifItcOyaDefNo; DifItcOyaDefNo=2031 at t-dif/include/DifP.h:84; no intervening reopen of fcb1
c-viz (arg 1): [2031] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:637
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifAllReq(); expr &fcb1
Expected: [2032]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:629 opens &fcb1 with DifDvHasIdxDefNo; DifDvHasIdxDefNo=2032 at t-dif/include/DifP.h:85; no intervening reopen of fcb1
c-viz (arg 1): [2032] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:659
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifAllReq(); expr &fcb1
Expected: [2033]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:651 opens &fcb1 with DifDvHasDefNo; DifDvHasDefNo=2033 at t-dif/include/DifP.h:86; no intervening reopen of fcb1
c-viz (arg 1): [2033] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:703
Target: mpf_mfs_getrec(...), arg 1 (GETREC); enclosing fn DifAllReq(); expr &fcb1
Expected: [2025]  (PATH_VALID)
  - proof: open at t-dif/src/libdifP/difSvDvReq.c:692 opens &fcb1 with DifModeEndMngNo; DifModeEndMngNo=2025 at t-dif/include/DifP.h:78; no intervening reopen of fcb1
c-viz (arg 1): [2025] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

#### t-dif/tool/diftool

### /home/chukyu/t-dif/tool/diftool/fileInit_DifKoshoKanri.c:73
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn fileInit_DifKoshoKanri(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileInit_DifKoshoKanri.c:57 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileInit_DifKoshoKanri.c:147
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn initial_DifKoshoKanri(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileInit_DifKoshoKanri.c:137 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileInit_DifStatus.c:73
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn fileInit_DifStatus(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileInit_DifStatus.c:57 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileInit_DifStatus.c:147
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn initial_DifStatus(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileInit_DifStatus.c:137 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileOut_DifKoshoKanri.c:56
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn fileOut_DifKoshoKanri(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileOut_DifKoshoKanri.c:45 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileOut_DifKoshoKanri.c:96
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn fileOut_DifKoshoKanri(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileOut_DifKoshoKanri.c:86 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileOut_DifStatus.c:54
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn fileOut_DifStatus(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileOut_DifStatus.c:44 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileOut_DifStatus.c:94
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn fileOut_DifStatus(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileOut_DifStatus.c:84 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:93
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn fileWrite_DifKoshoKanri(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:82 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:410
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_system1(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:399 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:481
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_system2(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:470 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:552
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_system3(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:541 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:647
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_sequence1(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:636 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:746
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_sequence2(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:735 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:845
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_sequence3(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:834 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:950
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat1(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:939 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1067
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat2(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1056 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1184
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat3(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1173 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1301
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat4(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1290 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1418
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat5(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1407 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1535
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat7(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1524 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1652
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat8(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1641 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1769
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat9(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1758 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1886
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat10(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1875 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2003
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat11(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:1992 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2120
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat15(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2109 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2237
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_stat16(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2226 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2335
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_sequence_cpu(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2324 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2395
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeKosho_init_end(); expr &fcb
Expected: [2026]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifKoshoKanri.c:2384 opens &fcb with DifKoshoKanriNo; DifKoshoKanriNo=2026 at t-dif/include/DifP.h:79; no intervening reopen of fcb
c-viz (arg 1): [2026] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:68
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn fileWrite_DifStatus(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:58 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:201
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_lockflg(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:191 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:269
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_hyojiflg(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:259 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:337
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_f1flg(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:327 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:405
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_buflg(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:395 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:473
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_shikenflg(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:463 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:541
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_reqflg(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:531 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:609
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_initflg(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:599 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:677
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_seqflg(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:667 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:745
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_hyojiflk(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:735 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:813
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn writeStatus_f1flk(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: open at t-dif/tool/diftool/fileWrite_DifStatus.c:803 opens &fcb with DifStatusNo; DifStatusNo=2022 at t-dif/include/dif/Dif.h:45; no intervening reopen of fcb
c-viz (arg 1): [2022] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

#### t-tmm/src/libtmm

### /home/chukyu/t-tmm/src/libtmm/TmmBSUnTypeChk.c:87
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmBSUnTypeChk(); expr &sFcb
Expected: [2728]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmm/TmmBSUnTypeChk.c:60 opens &sFcb with TMM_VUNYOTOKU_FNO=2728 (define t-tmm/include/tmm/TmmFileNo.h:48); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmm/TmmBSUnTypeChk.c:107
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmBSUnTypeChk(); expr &sFcb
Expected: [2728]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmm/TmmBSUnTypeChk.c:60 opens &sFcb with TMM_VUNYOTOKU_FNO=2728 (define t-tmm/include/tmm/TmmFileNo.h:48); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmm/TmmFile.c:141
Target: mpf_mfs_openm_H(...), arg 2 (OPEN_LOCK); enclosing fn TmmFileOpen(); expr tmm_flist[tmm_fnum].fno
Expected: none provable  (UNDECIDED)
  - no provable value: fno = tmm_flist[tmm_fnum].fno, runtime table filled by TmmFileOpen(fno,...) (TmmFile.c:137)
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 2): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmFile.c:146
Target: mpf_mfs_openm(...), arg 3 (OPEN_LOCK); enclosing fn TmmFileOpen(); expr tmm_flist[tmm_fnum].fno
Expected: none provable  (UNDECIDED)
  - no provable value: mpf_mfs_openm(&tmm_flist[..].fcb, access_name, tmm_flist[..].fno,...) (TmmFile.c:146); fno runtime table value
c-viz (arg 3): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 3): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmFile.c:238
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn TmmFileRead(); expr &tmm_flist[i].fcb
Expected: none provable  (UNDECIDED)
  - no provable value: &tmm_flist[i].fcb; fno runtime table value (TmmFile.c:137)
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmFile.c:275
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn TmmFileWrite(); expr &tmm_flist[i].fcb
Expected: none provable  (UNDECIDED)
  - no provable value: &tmm_flist[i].fcb; fno runtime table value (TmmFile.c:137)
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmm/TmmGetComSet.c:139
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmGetComSet(); expr &fcb
Expected: [2727]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmm/TmmGetComSet.c:129 opens &fcb with TMM_COMMONSET2_FNO=2727 (define t-tmm/include/tmm/TmmFileNo.h:47); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmm/TmmGetConst.c:45
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmGetConst(); expr &fcb
Expected: [2719]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmm/TmmGetConst.c:39 opens &fcb with TMM_CONSTGEN_FNO=2719 (define t-tmm/include/tmm/TmmFileNo.h:66); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmm/TmmGetDef.c:45
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmGetDef(); expr &fcb
Expected: [2703]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmm/TmmGetDef.c:39 opens &fcb with TMM_DEF_FNO; TMM_DEF_FNO=2703 at t-tmm/include/tmm/TmmFileNo.h:39; no intervening reopen of fcb
c-viz (arg 1): [2703] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmm/TmmGetExConst.c:45
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmGetExConst(); expr &fcb
Expected: [2726]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmm/TmmGetExConst.c:39 opens &fcb with TMM_EXCONSTGEN_FNO=2726 (define t-tmm/include/tmm/TmmFileNo.h:81); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmm/TmmGetSaveTM.c:50
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmGetSaveTM(); expr &save_fcb
Expected: [2722]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmm/TmmGetSaveTM.c:45 opens &save_fcb with TMM_TMSAVE_FNO=2722 (define t-tmm/include/tmm/TmmFileNo.h:70); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

#### t-tmm/src/libtmmp

### /home/chukyu/t-tmm/src/libtmmp/TmmBandCheck_GNP.c:106
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmBandCheck_GNP(); expr &gndef_fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmBandCheck_GNP.c:90 opens &gndef_fcb with TMM_GNQDEF_FNO=2715 (define t-tmm/include/tmm/TmmFileNo.h:61); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmBandCheck_GNP.c:109
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmBandCheck_GNP(); expr &gnset_fcb
Expected: [2716]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmBandCheck_GNP.c:96 opens &gnset_fcb with TMM_GNQSET_FNO=2716 (define t-tmm/include/tmm/TmmFileNo.h:62); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmGNQSetInit.c:89
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmGNQSetInit(); expr &def_fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmGNQSetInit.c:75 opens &def_fcb with TMM_GNQDEF_FNO=2715 (define t-tmm/include/tmm/TmmFileNo.h:61); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1, "UNRESOLVED": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmGNQSetInit.c:98
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmGNQSetInit(); expr &fcb
Expected: [2716]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmGNQSetInit.c:81 opens &fcb with TMM_GNQSET_FNO; TMM_GNQSET_FNO=2716 at t-tmm/include/tmm/TmmFileNo.h:62; no intervening reopen of fcb
c-viz (arg 1): [2716] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmGNQSetInit.c:171
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmGNQSetInit(); expr &gt_fcb
Expected: [2723]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmGNQSetInit.c:166 opens &gt_fcb with TMM_DBGT_FNO; TMM_DBGT_FNO=2723 at t-tmm/include/tmm/TmmFileNo.h:71; no intervening reopen of gt_fcb
c-viz (arg 1): [2723] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmGNQSetInit.c:184
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmGNQSetInit(); expr &fcb
Expected: [2716]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmGNQSetInit.c:81 opens &fcb with TMM_GNQSET_FNO; TMM_GNQSET_FNO=2716 at t-tmm/include/tmm/TmmFileNo.h:62; no intervening reopen of fcb
c-viz (arg 1): [2716] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmGNQSetInit.c:199
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmGNQSetInit(); expr &fcb
Expected: [2716]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmGNQSetInit.c:81 opens &fcb with TMM_GNQSET_FNO; TMM_GNQSET_FNO=2716 at t-tmm/include/tmm/TmmFileNo.h:62; no intervening reopen of fcb
c-viz (arg 1): [2716] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmGetSklNo.c:45
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmGetSklNo(); expr &fcb
Expected: [2721]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmGetSklNo.c:39 opens &fcb with TMM_SKLDEF_FNO=2721 (define t-tmm/include/tmm/TmmFileNo.h:69); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmLocalInit.c:59
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmRTStatInit(); expr &fcb
Expected: [2707]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmLocalInit.c:51 opens &fcb with TMM_RTSTAT_FNO; TMM_RTSTAT_FNO=2707 at t-tmm/include/tmm/TmmFileNo.h:53; no intervening reopen of fcb
c-viz (arg 1): [2707] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmLocalInit.c:85
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmRTStatInit(); expr &def_fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmLocalInit.c:45 opens &def_fcb with TMM_RTDEF_FNO=2705 (define t-tmm/include/tmm/TmmFileNo.h:51); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1, "UNRESOLVED": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmLocalInit.c:169
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmRTQStatInit(); expr &fcb
Expected: [2708]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmLocalInit.c:162 opens &fcb with TMM_RTQSTAT_FNO; TMM_RTQSTAT_FNO=2708 at t-tmm/include/tmm/TmmFileNo.h:54; no intervening reopen of fcb
c-viz (arg 1): [2708] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmLocalInit.c:209
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmTRStatInit(); expr &fcb
Expected: [2710]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmLocalInit.c:202 opens &fcb with TMM_TRSTAT_FNO; TMM_TRSTAT_FNO=2710 at t-tmm/include/tmm/TmmFileNo.h:56; no intervening reopen of fcb
c-viz (arg 1): [2710] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmLocalInit.c:264
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmSSVoltStatInit(); expr &fcb
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmLocalInit.c:256 opens &fcb with TMM_SSVOLTSTAT_FNO; TMM_SSVOLTSTAT_FNO=2713 at t-tmm/include/tmm/TmmFileNo.h:59; no intervening reopen of fcb
c-viz (arg 1): [2713] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmLocalInit.c:331
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmPSVoltStatInit(); expr &fcb
Expected: [2714]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmLocalInit.c:323 opens &fcb with TMM_PSVOLTSTAT_FNO; TMM_PSVOLTSTAT_FNO=2714 at t-tmm/include/tmm/TmmFileNo.h:60; no intervening reopen of fcb
c-viz (arg 1): [2714] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmLocalInit.c:384
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn TmmGNQStatInit(); expr &fcb
Expected: [2717]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmLocalInit.c:377 opens &fcb with TMM_GNQSTAT_FNO; TMM_GNQSTAT_FNO=2717 at t-tmm/include/tmm/TmmFileNo.h:63; no intervening reopen of fcb
c-viz (arg 1): [2717] status={"EXACT": 1, "UNREACHABLE": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/libtmmp/TmmRTCheck.c:116
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmRT_LV2PickUp(); expr &def_fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmRTCheck.c:109 opens &def_fcb with TMM_RTDEF_FNO=2705 (define t-tmm/include/tmm/TmmFileNo.h:51); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:159
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &gen_fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:125 opens &gen_fcb with TMM_RTDEF_FNO=2705 (define t-tmm/include/tmm/TmmFileNo.h:51); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:163
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb
Expected: [2707]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:131 opens &stat_fcb with TMM_RTSTAT_FNO=2707 (define t-tmm/include/tmm/TmmFileNo.h:53); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:252
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb2
Expected: [2708]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:139 opens &stat_fcb2 with TMM_RTQSTAT_FNO=2708 (define t-tmm/include/tmm/TmmFileNo.h:54); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:379
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &gen_fcb
Expected: [2709]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:356 opens &gen_fcb with TMM_TRDEF_FNO=2709 (define t-tmm/include/tmm/TmmFileNo.h:55); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:383
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb
Expected: [2710]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:362 opens &stat_fcb with TMM_TRSTAT_FNO=2710 (define t-tmm/include/tmm/TmmFileNo.h:56); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:511
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &gen_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:487 opens &gen_fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:520
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:493 opens &stat_fcb with TMM_SSVOLTSTAT_FNO=2713 (define t-tmm/include/tmm/TmmFileNo.h:59); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:528
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:493 opens &stat_fcb with TMM_SSVOLTSTAT_FNO=2713 (define t-tmm/include/tmm/TmmFileNo.h:59); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:623
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &gen_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:487 opens &gen_fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:632
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:493 opens &stat_fcb with TMM_SSVOLTSTAT_FNO=2713 (define t-tmm/include/tmm/TmmFileNo.h:59); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:640
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:493 opens &stat_fcb with TMM_SSVOLTSTAT_FNO=2713 (define t-tmm/include/tmm/TmmFileNo.h:59); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:795
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &gen_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:753 opens &gen_fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:804
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb
Expected: [2714]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:759 opens &stat_fcb with TMM_PSVOLTSTAT_FNO=2714 (define t-tmm/include/tmm/TmmFileNo.h:60); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:812
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb
Expected: [2714]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:759 opens &stat_fcb with TMM_PSVOLTSTAT_FNO=2714 (define t-tmm/include/tmm/TmmFileNo.h:60); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:907
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &gen_fcb2
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:767 opens &gen_fcb2 with TMM_GNQDEF_FNO=2715 (define t-tmm/include/tmm/TmmFileNo.h:61); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c:911
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmSysInit(); expr &stat_fcb2
Expected: [2717]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmSysInit.c:775 opens &stat_fcb2 with TMM_GNQSTAT_FNO=2717 (define t-tmm/include/tmm/TmmFileNo.h:63); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmTRCheck.c:95
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmTRCheck(); expr &trdef_fcb
Expected: [2709]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmTRCheck.c:72 opens &trdef_fcb with TMM_TRDEF_FNO=2709 (define t-tmm/include/tmm/TmmFileNo.h:55); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVoltCheck.c:156
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVoltCheck(); expr &stat_fcb
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVoltCheck.c:151 opens &stat_fcb with TMM_SSVOLTSTAT_FNO=2713 (define t-tmm/include/tmm/TmmFileNo.h:59); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVoltCheck.c:169
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVoltCheck(); expr &stat_fcb
Expected: [2714]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVoltCheck.c:164 opens &stat_fcb with TMM_PSVOLTSTAT_FNO=2714 (define t-tmm/include/tmm/TmmFileNo.h:60); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:111
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vdef_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:74 opens &vdef_fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:171
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vset_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:79 opens &vset_fcb with TMM_VOLTSET_FNO=2712 (define t-tmm/include/tmm/TmmFileNo.h:58); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:199
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vset_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:79 opens &vset_fcb with TMM_VOLTSET_FNO=2712 (define t-tmm/include/tmm/TmmFileNo.h:58); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:226
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vdef_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:74 opens &vdef_fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:287
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vset_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:79 opens &vset_fcb with TMM_VOLTSET_FNO=2712 (define t-tmm/include/tmm/TmmFileNo.h:58); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:315
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vset_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:79 opens &vset_fcb with TMM_VOLTSET_FNO=2712 (define t-tmm/include/tmm/TmmFileNo.h:58); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:353
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vdef_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:74 opens &vdef_fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:437
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vset_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:79 opens &vset_fcb with TMM_VOLTSET_FNO=2712 (define t-tmm/include/tmm/TmmFileNo.h:58); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:465
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vset_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:79 opens &vset_fcb with TMM_VOLTSET_FNO=2712 (define t-tmm/include/tmm/TmmFileNo.h:58); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:532
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vset_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:79 opens &vset_fcb with TMM_VOLTSET_FNO=2712 (define t-tmm/include/tmm/TmmFileNo.h:58); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:558
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn TmmVolt_LV2PickUp(); expr &vset_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/libtmmp/TmmVolt_LV2PickUp.c:79 opens &vset_fcb with TMM_VOLTSET_FNO=2712 (define t-tmm/include/tmm/TmmFileNo.h:58); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

#### t-tmm/src/tmm000

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:163
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr KDCCURFNo
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:170
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr KDCCURFNo
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:180
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr KDCCURFNo
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:190
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr KDCCURFNo
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:205
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr KDCCURFNo
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:214
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr KDCCURFNo
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:247
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr API_GENZAIDB
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:264
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr API_GENZAIDB
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:282
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr API_GENZAIDB
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:300
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr API_GENZAIDB
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:327
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr API_GENZAIDB
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm000/tmm000_cdbinit.c:344
Target: mpf_mfs_copyrec_H(...), arg 2 (COPYREC_FROM), arg 8 (COPYREC_TO); enclosing fn tmm000_cdbcopy(); expr API_GENZAIDB
Expected: none provable  (UNDECIDED)
  - no provable value: copyrec args KDCCURFNo (a2) / API_GENZAIDB (a8) defined only in external API headers, not in /home/chukyu
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1}; legacy (arg 2): [none reported] status={} -> both: UNDECIDED
c-viz (arg 8): [none reported] status={"UNREACHABLE": 1}; legacy (arg 8): [none reported] status={} -> both: UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

#### t-tmm/src/tmm200d

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_chstatus.c:118
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm200d_chstatus(); expr &fcb
Expected: [2720]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm200d/tmm200d_chstatus.c:110 opens &fcb with TMM_TMBITGEN_FNO; TMM_TMBITGEN_FNO=2720 at t-tmm/include/tmm/TmmFileNo.h:67; no intervening reopen of fcb
c-viz (arg 1): [2720] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2720] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_gen.c:48
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn tmm200d_gen(); expr &fcb1
Expected: [2701]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm200d/tmm200d_gen.c:41 opens &fcb1 with TMM_TMMIXGEN_FNO; TMM_TMMIXGEN_FNO=2701 at t-tmm/include/tmm/TmmFileNo.h:28; no intervening reopen of fcb1
c-viz (arg 1): [2701] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2701] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_gen.c:59
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn tmm200d_gen(); expr &fcb2
Expected: [2737]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm200d/tmm200d_gen.c:52 opens &fcb2 with TMM_TMSYKGEN_FNO; TMM_TMSYKGEN_FNO=2737 at t-tmm/include/tmm/TmmFileNo.h:36; no intervening reopen of fcb2
c-viz (arg 1): [2737] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2737] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_gen.c:75
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn tmm200d_gen(); expr &fcb3
Expected: [2728]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm200d/tmm200d_gen.c:63 opens &fcb3 with TMM_VUNYOTOKU_FNO; TMM_VUNYOTOKU_FNO=2728 at t-tmm/include/tmm/TmmFileNo.h:48; no intervening reopen of fcb3
c-viz (arg 1): [2728] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2728] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_gen.c:91
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn tmm200d_gen(); expr &fcb3
Expected: [2735]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm200d/tmm200d_gen.c:79 opens &fcb3 with TMM_VLIMITDEF_FNO; TMM_VLIMITDEF_FNO=2735 at t-tmm/include/tmm/TmmFileNo.h:75; no intervening reopen of fcb3
c-viz (arg 1): [2735] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2735] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_status.c:145
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn tmm200d_status_g(); expr &fcb_mixsyk
Expected: [2718]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm200d/tmm200d_status.c:138 opens &fcb_mixsyk with TMM_TMMIXSYKGEN_FNO; TMM_TMMIXSYKGEN_FNO=2718 at t-tmm/include/tmm/TmmFileNo.h:65; no intervening reopen of fcb_mixsyk
c-viz (arg 1): [2718] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2718] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm200d/tmm200d_value.c:225
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm200d_value(); expr &save_fcb
Expected: [2722]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm200d/tmm200d_value.c:217 opens &save_fcb with TMM_TMSAVE_FNO; TMM_TMSAVE_FNO=2722 at t-tmm/include/tmm/TmmFileNo.h:70; no intervening reopen of save_fcb
c-viz (arg 1): [2722] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2722] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-tmm/src/tmm210d

### /home/chukyu/t-tmm/src/tmm210d/tmm210d_gen.c:46
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn tmm210d_gen(); expr &fcb1
Expected: [2701]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm210d/tmm210d_gen.c:39 opens &fcb1 with TMM_TMMIXGEN_FNO; TMM_TMMIXGEN_FNO=2701 at t-tmm/include/tmm/TmmFileNo.h:28; no intervening reopen of fcb1
c-viz (arg 1): [2701] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2701] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm210d/tmm210d_gen.c:57
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn tmm210d_gen(); expr &fcb2
Expected: [2737]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm210d/tmm210d_gen.c:50 opens &fcb2 with TMM_TMSYKGEN_FNO; TMM_TMSYKGEN_FNO=2737 at t-tmm/include/tmm/TmmFileNo.h:36; no intervening reopen of fcb2
c-viz (arg 1): [2737] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2737] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm210d/tmm210d_reqcb.c:143
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm210d_reqcb(); expr &fcb
Expected: [2720]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm210d/tmm210d_reqcb.c:134 opens &fcb with TMM_TMBITGEN_FNO; TMM_TMBITGEN_FNO=2720 at t-tmm/include/tmm/TmmFileNo.h:67; no intervening reopen of fcb
c-viz (arg 1): [2720] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2720] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm210d/tmm210d_reqcb.c:808
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm210d_reqcb(); expr &fcb1
Expected: [2734]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm210d/tmm210d_reqcb.c:797 opens &fcb1 with TMM_SCDEF_FNO; TMM_SCDEF_FNO=2734 at t-tmm/include/tmm/TmmFileNo.h:74; no intervening reopen of fcb1
c-viz (arg 1): [2734] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2734] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm210d/tmm210d_reqcb.c:817
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm210d_reqcb(); expr &fcb2
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm210d/tmm210d_reqcb.c:803 opens &fcb2 with TMM_SSVOLTSTAT_FNO; TMM_SSVOLTSTAT_FNO=2713 at t-tmm/include/tmm/TmmFileNo.h:59; no intervening reopen of fcb2
c-viz (arg 1): [2713] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2713] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-tmm/src/tmm900

### /home/chukyu/t-tmm/src/tmm900/tmm900_VUnyoToku.c:267
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn tmm900_VUnyoToku(); expr &sFcb
Expected: [2728]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_VUnyoToku.c:259 opens &sFcb with TMM_VUNYOTOKU_FNO; TMM_VUNYOTOKU_FNO=2728 at t-tmm/include/tmm/TmmFileNo.h:48; no intervening reopen of sFcb
c-viz (arg 1): [2728] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2728] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_bittm.c:98
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_bittm(); expr &fcb
Expected: [2720]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_bittm.c:57 opens &fcb with TMM_TMBITGEN_FNO; TMM_TMBITGEN_FNO=2720 at t-tmm/include/tmm/TmmFileNo.h:67; no intervening reopen of fcb
c-viz (arg 1): [2720] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2720] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_bittm.c:146
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_bittm(); expr &fcb
Expected: [2720]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_bittm.c:57 opens &fcb with TMM_TMBITGEN_FNO; TMM_TMBITGEN_FNO=2720 at t-tmm/include/tmm/TmmFileNo.h:67; no intervening reopen of fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2720] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_cdttmgen.c:287
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn tmm900_cdttmgen(); expr &fcb_cdttm
Expected: [2739]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_cdttmgen.c:279 opens &fcb_cdttm with TMM_CDTTMGEN_FNO; TMM_CDTTMGEN_FNO=2739 at t-tmm/include/tmm/TmmCDTTmGen.h:32; no intervening reopen of fcb_cdttm
c-viz (arg 1): [2739] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2739] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:89
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_defgen(); expr &fcb
Expected: [2703]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:80 opens &fcb with TMM_DEF_FNO; TMM_DEF_FNO=2703 at t-tmm/include/tmm/TmmFileNo.h:39; no intervening reopen of fcb
c-viz (arg 1): [2703] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2703] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:191
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_def_rt(); expr &fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:181 opens &fcb with TMM_RTDEF_FNO; TMM_RTDEF_FNO=2705 at t-tmm/include/tmm/TmmFileNo.h:51; no intervening reopen of fcb
c-viz (arg 1): [2705] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:438
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_def_rtq(); expr &fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:428 opens &fcb with TMM_RTDEF_FNO; TMM_RTDEF_FNO=2705 at t-tmm/include/tmm/TmmFileNo.h:51; no intervening reopen of fcb
c-viz (arg 1): [2705] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2705] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:522
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_def_tr(); expr &fcb
Expected: [2709]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:512 opens &fcb with TMM_TRDEF_FNO; TMM_TRDEF_FNO=2709 at t-tmm/include/tmm/TmmFileNo.h:55; no intervening reopen of fcb
c-viz (arg 1): [2709] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2709] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:719
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_def_ssv(); expr &fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:709 opens &fcb with TMM_VOLTDEF_FNO; TMM_VOLTDEF_FNO=2711 at t-tmm/include/tmm/TmmFileNo.h:57; no intervening reopen of fcb
c-viz (arg 1): [2711] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2711] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:1162
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_def_psv(); expr &fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:1152 opens &fcb with TMM_VOLTDEF_FNO; TMM_VOLTDEF_FNO=2711 at t-tmm/include/tmm/TmmFileNo.h:57; no intervening reopen of fcb
c-viz (arg 1): [2711] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2711] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:1352
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_def_gnq(); expr &fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:1342 opens &fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of fcb
c-viz (arg 1): [2715] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2715] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:1480
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_def_gnq(); expr &v_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:1391 opens &v_fcb with TMM_VOLTDEF_FNO; TMM_VOLTDEF_FNO=2711 at t-tmm/include/tmm/TmmFileNo.h:57; no intervening reopen of v_fcb
c-viz (arg 1): [2711] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2711] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_defgen.c:1511
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_def_gnq(); expr &v_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_defgen.c:1391 opens &v_fcb with TMM_VOLTDEF_FNO; TMM_VOLTDEF_FNO=2711 at t-tmm/include/tmm/TmmFileNo.h:57; no intervening reopen of v_fcb
c-viz (arg 1): [2711] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2711] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_gngen.c:110
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_gngen(); expr &fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_gngen.c:97 opens &fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of fcb
c-viz (arg 1): [2715] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2715] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_gngen.c:158
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_gngen(); expr &fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_gngen.c:97 opens &fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2715] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_gngen.c:265
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_gngen(); expr &fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_gngen.c:97 opens &fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2715] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_gngen.c:515
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_gngen(); expr &fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_gngen.c:97 opens &fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2715] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_mixtm.c:124
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn tmm900_mixtm(); expr &fcb_mix
Expected: [2701]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_mixtm.c:117 opens &fcb_mix with TMM_TMMIXGEN_FNO; TMM_TMMIXGEN_FNO=2701 at t-tmm/include/tmm/TmmFileNo.h:28; no intervening reopen of fcb_mix
c-viz (arg 1): [2701] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2701] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_mixtm.c:138
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn tmm900_mixtm(); expr &fcb_mixkob
Expected: [2737]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_mixtm.c:131 opens &fcb_mixkob with TMM_TMSYKGEN_FNO; TMM_TMSYKGEN_FNO=2737 at t-tmm/include/tmm/TmmFileNo.h:36; no intervening reopen of fcb_mixkob
c-viz (arg 1): [2737] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2737] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_mixtm.c:152
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn tmm900_mixtm(); expr &fcb_mixsyk
Expected: [2718]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_mixtm.c:145 opens &fcb_mixsyk with TMM_TMMIXSYKGEN_FNO; TMM_TMMIXSYKGEN_FNO=2718 at t-tmm/include/tmm/TmmFileNo.h:65; no intervening reopen of fcb_mixsyk
c-viz (arg 1): [2718] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2718] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_rtgen.c:120
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_rtgen(); expr &fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_rtgen.c:102 opens &fcb with TMM_RTDEF_FNO; TMM_RTDEF_FNO=2705 at t-tmm/include/tmm/TmmFileNo.h:51; no intervening reopen of fcb
c-viz (arg 1): [2705] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2705] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_rtgen.c:179
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_rtgen(); expr &fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_rtgen.c:102 opens &fcb with TMM_RTDEF_FNO; TMM_RTDEF_FNO=2705 at t-tmm/include/tmm/TmmFileNo.h:51; no intervening reopen of fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2705] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_rtgen.c:474
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_rtgen(); expr &fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_rtgen.c:102 opens &fcb with TMM_RTDEF_FNO; TMM_RTDEF_FNO=2705 at t-tmm/include/tmm/TmmFileNo.h:51; no intervening reopen of fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2705] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_scgen.c:75
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_scgen(); expr &fcb1
Expected: [2734]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_scgen.c:67 opens &fcb1 with TMM_SCDEF_FNO; TMM_SCDEF_FNO=2734 at t-tmm/include/tmm/TmmFileNo.h:74; no intervening reopen of fcb1
c-viz (arg 1): [2734] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2734] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_scgen.c:114
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_scgen(); expr &fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_scgen.c:59 opens &fcb with TMM_VOLTDEF_FNO; TMM_VOLTDEF_FNO=2711 at t-tmm/include/tmm/TmmFileNo.h:57; no intervening reopen of fcb
c-viz (arg 1): [2711] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2711] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_sklgen.c:73
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_sklgen(); expr &fcb
Expected: [2721]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_sklgen.c:64 opens &fcb with TMM_SKLDEF_FNO; TMM_SKLDEF_FNO=2721 at t-tmm/include/tmm/TmmFileNo.h:69; no intervening reopen of fcb
c-viz (arg 1): [2721] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_sklgen.c:237
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_sklchk_rt(); expr &gen_fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_sklgen.c:226 opens &gen_fcb with TMM_RTDEF_FNO; TMM_RTDEF_FNO=2705 at t-tmm/include/tmm/TmmFileNo.h:51; no intervening reopen of gen_fcb
c-viz (arg 1): [2705] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_sklgen.c:284
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_sklchk_tr(); expr &gen_fcb
Expected: [2709]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_sklgen.c:278 opens &gen_fcb with TMM_TRDEF_FNO; TMM_TRDEF_FNO=2709 at t-tmm/include/tmm/TmmFileNo.h:55; no intervening reopen of gen_fcb
c-viz (arg 1): [2709] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_sklgen.c:335
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_sklchk_volt(); expr &gen_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_sklgen.c:327 opens &gen_fcb with TMM_VOLTDEF_FNO; TMM_VOLTDEF_FNO=2711 at t-tmm/include/tmm/TmmFileNo.h:57; no intervening reopen of gen_fcb
c-viz (arg 1): [2711] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_sklgen.c:356
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_sklchk_volt(); expr &gen_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_sklgen.c:327 opens &gen_fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/tmm900/tmm900_sklgen.c:403
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_sklchk_gn(); expr &gen_fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_sklgen.c:396 opens &gen_fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of gen_fcb
c-viz (arg 1): [2715] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_trgen.c:136
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_trgen(); expr &fcb
Expected: [2709]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_trgen.c:123 opens &fcb with TMM_TRDEF_FNO; TMM_TRDEF_FNO=2709 at t-tmm/include/tmm/TmmFileNo.h:55; no intervening reopen of fcb
c-viz (arg 1): [2709] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2709] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_trgen.c:188
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_trgen(); expr &fcb
Expected: [2709]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_trgen.c:123 opens &fcb with TMM_TRDEF_FNO; TMM_TRDEF_FNO=2709 at t-tmm/include/tmm/TmmFileNo.h:55; no intervening reopen of fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2709] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_trgen.c:315
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_trgen(); expr &fcb
Expected: [2709]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_trgen.c:123 opens &fcb with TMM_TRDEF_FNO; TMM_TRDEF_FNO=2709 at t-tmm/include/tmm/TmmFileNo.h:55; no intervening reopen of fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2709] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_trgen.c:351
Target: mpf_mfs_writerecm(...), arg 1 (WRITEREC); enclosing fn tmm900_trgen(); expr &fcb
Expected: [2736]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_trgen.c:342 opens &fcb with TMM_BNAME_FNO; TMM_BNAME_FNO=2736 at t-tmm/include/tmm/TmmBkName.h:29; no intervening reopen of fcb
c-viz (arg 1): [2736] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2736] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_trgen.c:940
Target: mpf_mfs_writerecn(...), arg 1 (WRITEREC); enclosing fn tmm900_getgnname(); expr &fcb
Expected: [2738]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_trgen.c:933 opens &fcb with TMM_GNNAME_FNO; TMM_GNNAME_FNO=2738 at t-tmm/include/tmm/TmmGnName.h:29; no intervening reopen of fcb
c-viz (arg 1): [2738] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2738] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_voltgen.c:106
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_voltgen(); expr &fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_voltgen.c:94 opens &fcb with TMM_VOLTDEF_FNO; TMM_VOLTDEF_FNO=2711 at t-tmm/include/tmm/TmmFileNo.h:57; no intervening reopen of fcb
c-viz (arg 1): [2711] status={"EXACT": 1} -> part of CVIZ_CORRECT_ONLY
legacy (arg 1): [none reported] status={} -> part of CVIZ_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm900/tmm900_voltgen.c:231
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_voltgen(); expr &fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_voltgen.c:94 opens &fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/tmm900/tmm900_voltgen.c:458
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm900_voltgen(); expr &fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm900/tmm900_voltgen.c:94 opens &fcb with TMM_VOLTDEF_FNO=2711 (define t-tmm/include/tmm/TmmFileNo.h:57); no intervening reopen
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

#### t-tmm/src/tmm910

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:103
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_gnqmnt(); expr &gen_fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_gnqmnt.c:77 opens &gen_fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of gen_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2715] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:112
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_gnqmnt(); expr &set_fcb
Expected: [2716]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_gnqmnt.c:84 opens &set_fcb with TMM_GNQSET_FNO; TMM_GNQSET_FNO=2716 at t-tmm/include/tmm/TmmFileNo.h:62; no intervening reopen of set_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2716] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:119
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_gnqmnt(); expr &stat_fcb
Expected: [2717]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_gnqmnt.c:92 opens &stat_fcb with TMM_GNQSTAT_FNO; TMM_GNQSTAT_FNO=2717 at t-tmm/include/tmm/TmmFileNo.h:63; no intervening reopen of stat_fcb
c-viz (arg 1): [2717] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2717] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:224
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_gnqmnt(); expr &gen_fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_gnqmnt.c:77 opens &gen_fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of gen_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2715] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:233
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_gnqmnt(); expr &set_fcb
Expected: [2716]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_gnqmnt.c:84 opens &set_fcb with TMM_GNQSET_FNO; TMM_GNQSET_FNO=2716 at t-tmm/include/tmm/TmmFileNo.h:62; no intervening reopen of set_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2716] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:435
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_gnqclear(); expr &def_fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_gnqmnt.c:428 opens &def_fcb with TMM_GNQDEF_FNO; TMM_GNQDEF_FNO=2715 at t-tmm/include/tmm/TmmFileNo.h:61; no intervening reopen of def_fcb
c-viz (arg 1): [2715] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2715] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:512
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn tmm910_gnqclear(); expr &gt_fcb
Expected: [2723]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_gnqmnt.c:507 opens &gt_fcb with TMM_DBGT_FNO; TMM_DBGT_FNO=2723 at t-tmm/include/tmm/TmmFileNo.h:71; no intervening reopen of gt_fcb
c-viz (arg 1): [2723] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2723] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:617
Target: mpf_mfs_readrecm(...), arg 1 (READREC); enclosing fn tmm910_gnqclear(); expr &gt_fcb
Expected: [2723]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_gnqmnt.c:612 opens &gt_fcb with TMM_DBGT_FNO; TMM_DBGT_FNO=2723 at t-tmm/include/tmm/TmmFileNo.h:71; no intervening reopen of gt_fcb
c-viz (arg 1): [2723] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2723] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:636
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_gnqset(); expr set_fcb
Expected: [2716]  (PATH_VALID)
  - proof: set_fcb = 5th param (MPF_MFS_FCB*); sole callers tmm910_gnqmnt.c:284,314 pass &set_fcb opened with TMM_GNQSET_FNO(=2716, TmmFileNo.h) at tmm910_gnqmnt.c:84; NOTE close at :96 precedes call
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2716] status={"ADDED": 1, "ALREADY_PRESENT": 1, "OK_CONST": 2} -> part of LEGACY_CORRECT_ONLY
Confidence: medium
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_main.c:58
Target: mpf_mfs_open(...), arg 3 (READ); enclosing fn main(); expr FfeMntInfoFileNo
Expected: none provable  (UNDECIDED)
  - no provable value: no concrete value provable from in-tree source
c-viz (arg 3): [none reported] status={} -> part of UNDECIDED
legacy (arg 3): [none reported] status={"OK_CONST": 1} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm910/tmm910_main.c:66
Target: mpf_mfs_readrec(...), arg 1 (READREC); enclosing fn main(); expr &ffe_fcb
Expected: none provable  (UNDECIDED)
  - no provable value: opened with FfeMntInfoFileNo (tmm910_main.c:58) but macro defined nowhere in /home/chukyu
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of UNDECIDED
legacy (arg 1): [none reported] status={"OK_CONST": 1} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/tmm910/tmm910_rtmnt.c:143
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_rtmnt(); expr &com_fcb
Expected: [2727]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_rtmnt.c:120 opens &com_fcb with TMM_COMMONSET2_FNO; TMM_COMMONSET2_FNO=2727 at t-tmm/include/tmm/TmmFileNo.h:47; no intervening reopen of com_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2727] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_rtmnt.c:157
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_rtmnt(); expr &gen_fcb
Expected: [2705]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_rtmnt.c:87 opens &gen_fcb with TMM_RTDEF_FNO; TMM_RTDEF_FNO=2705 at t-tmm/include/tmm/TmmFileNo.h:51; no intervening reopen of gen_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2705] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_rtmnt.c:166
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_rtmnt(); expr &set_fcb
Expected: [2706]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_rtmnt.c:94 opens &set_fcb with TMM_RTSET_FNO; TMM_RTSET_FNO=2706 at t-tmm/include/tmm/TmmFileNo.h:52; no intervening reopen of set_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2706] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_rtmnt.c:173
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_rtmnt(); expr &stat_fcb
Expected: [2707]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_rtmnt.c:102 opens &stat_fcb with TMM_RTSTAT_FNO; TMM_RTSTAT_FNO=2707 at t-tmm/include/tmm/TmmFileNo.h:53; no intervening reopen of stat_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2707] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_rtmnt.c:181
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_rtmnt(); expr &qstat_fcb
Expected: [2708]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_rtmnt.c:132 opens &qstat_fcb with TMM_RTQSTAT_FNO; TMM_RTQSTAT_FNO=2708 at t-tmm/include/tmm/TmmFileNo.h:54; no intervening reopen of qstat_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2708] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_tmmnt.c:137
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn tmm910_tmoffmnt(); expr &fcb1
Expected: [2701]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_tmmnt.c:130 opens &fcb1 with TMM_TMMIXGEN_FNO=2701 (define t-tmm/include/tmm/TmmFileNo.h:28); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/tmm910/tmm910_tmmnt.c:148
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn tmm910_tmoffmnt(); expr &fcb2
Expected: [2737]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_tmmnt.c:141 opens &fcb2 with TMM_TMSYKGEN_FNO=2737 (define t-tmm/include/tmm/TmmFileNo.h:36); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/src/tmm910/tmm910_trmnt.c:66
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_trmnt(); expr &gen_fcb
Expected: [2709]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_trmnt.c:48 opens &gen_fcb with TMM_TRDEF_FNO; TMM_TRDEF_FNO=2709 at t-tmm/include/tmm/TmmFileNo.h:55; no intervening reopen of gen_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2709] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_trmnt.c:75
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_trmnt(); expr &stat_fcb
Expected: [2710]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_trmnt.c:55 opens &stat_fcb with TMM_TRSTAT_FNO; TMM_TRSTAT_FNO=2710 at t-tmm/include/tmm/TmmFileNo.h:56; no intervening reopen of stat_fcb
c-viz (arg 1): [2710] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2710] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_voltmnt.c:109
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_voltmnt(); expr &gen_fcb
Expected: [2711]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_voltmnt.c:73 opens &gen_fcb with TMM_VOLTDEF_FNO; TMM_VOLTDEF_FNO=2711 at t-tmm/include/tmm/TmmFileNo.h:57; no intervening reopen of gen_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2711] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_voltmnt.c:119
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_voltmnt(); expr &set_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_voltmnt.c:80 opens &set_fcb with TMM_VOLTSET_FNO; TMM_VOLTSET_FNO=2712 at t-tmm/include/tmm/TmmFileNo.h:58; no intervening reopen of set_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2712] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_voltmnt.c:126
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_voltmnt(); expr &sstat_fcb
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_voltmnt.c:88 opens &sstat_fcb with TMM_SSVOLTSTAT_FNO; TMM_SSVOLTSTAT_FNO=2713 at t-tmm/include/tmm/TmmFileNo.h:59; no intervening reopen of sstat_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2713] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_voltmnt.c:133
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_voltmnt(); expr &pstat_fcb
Expected: [2714]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_voltmnt.c:97 opens &pstat_fcb with TMM_PSVOLTSTAT_FNO; TMM_PSVOLTSTAT_FNO=2714 at t-tmm/include/tmm/TmmFileNo.h:60; no intervening reopen of pstat_fcb
c-viz (arg 1): [2714] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2714] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_voltmnt.c:279
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_voltmnt(); expr &set_fcb
Expected: [2712]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_voltmnt.c:80 opens &set_fcb with TMM_VOLTSET_FNO; TMM_VOLTSET_FNO=2712 at t-tmm/include/tmm/TmmFileNo.h:58; no intervening reopen of set_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2712] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_voltmnt.c:285
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_voltmnt(); expr &sstat_fcb
Expected: [2713]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_voltmnt.c:88 opens &sstat_fcb with TMM_SSVOLTSTAT_FNO; TMM_SSVOLTSTAT_FNO=2713 at t-tmm/include/tmm/TmmFileNo.h:59; no intervening reopen of sstat_fcb
c-viz (arg 1): [none reported] status={"UNRESOLVED": 1} -> part of LEGACY_CORRECT_ONLY
legacy (arg 1): [2713] status={"ALREADY_PRESENT": 1, "OK_CONST": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-tmm/src/tmm910/tmm910_voltmnt.c:292
Target: mpf_mfs_getrecm(...), arg 1 (GETREC); enclosing fn tmm910_voltmnt(); expr &pstat_fcb
Expected: [2714]  (PATH_VALID)
  - proof: open at t-tmm/src/tmm910/tmm910_voltmnt.c:97 opens &pstat_fcb with TMM_PSVOLTSTAT_FNO; TMM_PSVOLTSTAT_FNO=2714 at t-tmm/include/tmm/TmmFileNo.h:60; no intervening reopen of pstat_fcb
c-viz (arg 1): [2714] status={"EXACT": 1} -> part of BOTH_CORRECT_SAME
legacy (arg 1): [2714] status={"ADDED": 1, "OK_MACRO": 1} -> part of BOTH_CORRECT_SAME
Confidence: high
Cause tags: none

#### t-tmm/tool/opmtool

### /home/chukyu/t-tmm/tool/opmtool/tmmtool.c:69
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn TmmGNQDump(); expr &fcb
Expected: [2715]  (PATH_VALID)
  - proof: open at t-tmm/tool/opmtool/tmmtool.c:65 opens &fcb with fno 2715=2715 (literal); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-tmm/tool/opmtool/tmmtool.c:76
Target: mpf_mfs_readrecn(...), arg 1 (READREC); enclosing fn TmmGNQDump(); expr &fcb
Expected: [2716]  (PATH_VALID)
  - proof: open at t-tmm/tool/opmtool/tmmtool.c:72 opens &fcb with fno 2716=2716 (literal); no intervening reopen
c-viz (arg 1): [none reported] status={"UNREACHABLE": 1} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
legacy (arg 1): [none reported] status={} -> part of CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

#### t-dif/src/dif110d

### /home/chukyu/t-dif/src/dif110d/dif110dMain.c:150
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn dif110dproc(); expr DifSVInputQNo
Expected: [935]  (PATH_VALID)
  - proof: direct macro arg DifSVInputQNo at target line; define at t-dif/include/DifP.h:122
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [935] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

#### t-dif/src/dif111d

### /home/chukyu/t-dif/src/dif111d/dif111dMain.c:118
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn dif111dproc(); expr DifTMInputQNo
Expected: [936]  (PATH_VALID)
  - proof: direct macro arg DifTMInputQNo at target line; define at t-dif/include/DifP.h:123
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [936] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

#### t-dif/src/dif112d

### /home/chukyu/t-dif/src/dif112d/dif112dMain.c:200
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn dif112dDeqInputQ(); expr DifKoshoInputQNo
Expected: [937]  (PATH_VALID)
  - proof: direct macro arg DifKoshoInputQNo at target line; define at t-dif/include/DifP.h:124
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [937] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

### /home/chukyu/t-dif/src/dif112d/dif112dMain.c:546
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn dif112dDeqRcvQ(); expr DifDvInfRcvQNo
Expected: [938]  (PATH_VALID)
  - proof: direct macro arg DifDvInfRcvQNo at target line; define at t-dif/include/DifP.h:125
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [938] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

#### t-dif/src/dif121d

### /home/chukyu/t-dif/src/dif121d/dif121dMain.c:143
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn dif121dproc(); expr DifTMJohenQNo
Expected: [940]  (PATH_VALID)
  - proof: direct macro arg DifTMJohenQNo at target line; define at t-dif/include/DifP.h:126
c-viz (arg 2): [none reported] status={} -> part of LEGACY_CORRECT_ONLY
legacy (arg 2): [940] status={"ADDED": 1, "OK_MACRO": 1} -> part of LEGACY_CORRECT_ONLY
Confidence: high
Cause tags: none

#### t-tmm/src/libtmmp

### /home/chukyu/t-tmm/src/libtmmp/TmmDeque.c:51
Target: mpf_mfs_delque(...), arg 2 (DELQUE); enclosing fn TmmDeque(); expr file_no
Expected: none provable  (UNDECIDED)
  - no provable value: file_no = param of TmmDeque(); no callers of TmmDeque anywhere in t-tmm tree
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 2): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmmp/TmmEnque.c:72
Target: mpf_mfs_addque(...), arg 2 (ADDQUE); enclosing fn TmmEnque(); expr queno
Expected: none provable  (UNDECIDED)
  - no provable value: queno = param of TmmEnque(); no callers in t-tmm tree
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 2): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### /home/chukyu/t-tmm/src/libtmmp/TmmEnque.c:110
Target: mpf_mfs_addque(...), arg 2 (ADDQUE); enclosing fn TmmEnque(); expr queno
Expected: none provable  (UNDECIDED)
  - no provable value: queno = param of TmmEnque(); no callers in t-tmm tree
c-viz (arg 2): [none reported] status={"UNREACHABLE": 1} -> part of UNDECIDED
legacy (arg 2): [none reported] status={} -> part of UNDECIDED
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE

### Notable examples

**c-viz correct & legacy not (97 sites, all mfs_file handle sites where legacy reported nothing)** — e.g.:
- /home/chukyu/t-dif/src/dif130d/dif130Deque.c:269 — mpf_mfs_getrecm(&fcb,0); fcb opened at :258 with DifSendMngNo=2024 (t-dif/include/DifP.h:77). c-viz EXACT 2024 correct; legacy had no claim at all.
- /home/chukyu/t-dif/src/dif210d/dif210Deque.c:192 — fcb opened at :181 with DifStatusNo=2022; c-viz 2022 correct, legacy silent.
- /home/chukyu/t-dif/src/libdifP/difSvDvReq.c:338 (and 10 sibling sites) — c-viz correctly resolves DifSendMngNo=2024 / DifStatusNo=2022 / DifDvHasIdxDefNo=2032 etc. via the local open; legacy never claimed these sites.
- /home/chukyu/t-tmm/src/libtmmp/TmmLocalInit.c:59 — c-viz 2707 (TMM_RTSTAT_FNO) correct via open at :51; legacy silent.
- /home/chukyu/t-dif/tool/diftool/fileWrite_DifStatus.c:68 (12 sibling sites) — c-viz 2022 correct; legacy silent.

**legacy correct & c-viz not (37 sites)** — e.g.:
- /home/chukyu/t-dif/src/dif115d/dif115dRtnChk.c:141 — mpf_mfs_getrecm(&def_fcb,0); def_fcb opened in same function with DifDefineNo=2021 (DifP.h:75). legacy OK_CONST 2021 correct; c-viz UNRESOLVED.
- /home/chukyu/t-dif/src/dif400d/dif400Deque.c:65 — mpf_mfs_delque(NULL, DifTakeiSendQNo, &data), direct macro arg = 932 (DifP.h:119). legacy correct; c-viz reported nothing.
- /home/chukyu/t-tmm/src/tmm900/tmm900_gngen.c:158, 265, 515 and tmm900_rtgen.c:179, 474 — legacy resolves TMM_GENDEF_FNO/TMM_RTDEF_FNO-family values from the local opens; c-viz UNRESOLVED.
- /home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:636 — set_fcb pointer parameter bound by sole callers (:284/:314) to the TMM_GNQSET_FNO (2716) FCB opened at :84; legacy 2716 is the only source-provable binding (caveat: handle is closed at :96 before the call). c-viz UNRESOLVED (missed the non-& pointer expression).

**both correct (160 sites)** — the bulk of the batch: e.g. /home/chukyu/t-dif/src/dif000/dif000Main.c:290 (DifKoshoKanriNo=2026), :1413/:1428 (fcb2, DifHozonKoshoNo=2046), /home/chukyu/t-tmm/src/tmm200d/tmm200d_gen.c:59 (TMM_TMSYKGEN_FNO=2737 — active define at t-tmm/include/tmm/TmmFileNo.h:36; the commented-out 2702 at :34 is stale and correctly ignored by both pipelines), /home/chukyu/t-dif/src/dif115d/dif115dModeEnd.c:200 and :208 (helper FileRead; both pipelines enumerate all four caller-supplied file numbers 2025/2031/2032/2033).

**c-viz overapproximation**: none found in this batch (0 of 466 reported value instances rejected).

**both underapproximation (96 sites)** — strongest examples:
- /home/chukyu/t-tmm/src/tmm000/tmm000_deamon.c:56 — pmf_forkproc_H(tmm000_prc[cpukind][i].prgname, ...); the static table (tmm000_main.c:22-41) has exactly two active entries, "tmm200d" and "tmm210d" (all other rows commented out for the Linux configuration). Both pipelines returned only statuses (EXTERNAL/none).
- /home/chukyu/t-tmm/tool/opmtool/tmmtool.c:69, :76 — mpf_mfs_openm_H(&fcb, 2715/2716, ...) literal file numbers 4 lines above the readrecn calls; both pipelines UNREACHABLE/none.
- /home/chukyu/t-dif/src/dif901/dif901IntDll.c (31 sites) and dif900IntDll.c siblings — plain mpf_mfs_open(&fcb, NULL, DifSvDllDbNo/DifTmDllDbNo/DifSclDllDbNo, ...) in the same function; both pipelines gave only UNREACHABLE/none despite a one-step macro resolution (2039/2040/2041).
- /home/chukyu/t-tmm/src/libtmmp/TmmSysInit.c (10 sites), TmmVolt_LV2PickUp.c (10 sites) — same pattern: local open with TMM_*_FNO macro, both pipelines silent.

### Unfinished / open items

None — all 437 sites / 449 rows received a verdict.

Caveats recorded on specific sites:
- 59 UNDECIDED sites split into: 21 forkproc sites whose process name is runtime data (scn_getrcpu/SCN CPU info, scanf input, mpf_scn_getdupname, function parameters — e.g. all TmmInput.c/TmmInputK.c sites and tmm200d_trans.c:297,:340); 24 tmm000_cdbinit.c mpf_mfs_copyrec_H sites where KDCCURFNo / API_GENZAIDB are defined only in external API headers not present under /home/chukyu; 4 dif115dSend.c sites where DifOutputNo is not defined anywhere in the tree; 4 TmmFile.c sites (runtime tmm_flist[] table); 2 tmm910_main.c sites (FfeMntInfoFileNo not defined in-tree); 3 libtmmp TmmDeque/TmmEnque helper sites with no in-tree callers.
- tmm910_gnqmnt.c:636 carries a stale-handle caveat (set_fcb closed at :96 before use at :636 via tmm910_gnqset); 2716 remains the only source-provable binding.
- Function names for sites in very long single-function files (TmmSysInit.c, tmm210d_reqcb.c, dif000Main.c) were determined by column-0 header scanning; a small number may be off by one inner block but the open/close evidence lines are exact.
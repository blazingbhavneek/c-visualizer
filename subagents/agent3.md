# Role

You are one of 6 subagents (this one is **3**) in a source-code correctness
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
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/subagents/agent3_claims.csv
- Full per-site comparison (for cross-checking only; do not audit outside your batch):
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1_sites.csv
- c-visualizer raw facts:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index/discovery_facts.csv
- legacy proof:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/valueflow_proof.csv
- C source root: /home/chukyu

Batch statistics (already computed — reconcile them against your CSV on start):
- claim rows in your batch: 410
- unique (file, line) sites: 392

Your batch covers these source directories (relative to /home/chukyu):
- /home/chukyu/t-dyn/src/dyn010
- /home/chukyu/t-dyn/src/dyn011
- /home/chukyu/t-dyn/src/dyn012
- /home/chukyu/t-dyn/src/dyn014
- /home/chukyu/t-dyn/src/dyn235d
- /home/chukyu/t-dyn/src/dyn240d
- /home/chukyu/t-dyn/src/dyn251d
- /home/chukyu/t-dyn/src/dyn255d
- /home/chukyu/t-dyn/src/dyn260
- /home/chukyu/t-dyn/src/dyn261
- /home/chukyu/t-dyn/src/dyn262
- /home/chukyu/t-dyn/src/dyn263
- /home/chukyu/t-dyn/src/dyn264
- /home/chukyu/t-dyn/src/dyn266
- /home/chukyu/t-dyn/src/dyn267
- /home/chukyu/t-dyn/src/dyn311d
- /home/chukyu/t-dyn/src/dyn322d
- /home/chukyu/t-dyn/src/dyn431
- /home/chukyu/t-dyn/src/dyn432d
- /home/chukyu/t-dyn/src/dyn441
- /home/chukyu/t-dyn/src/dyn500
- /home/chukyu/t-dyn/src/dyn510d
- /home/chukyu/t-dyn/src/dyn532
- /home/chukyu/t-dyn/src/dyn561
- /home/chukyu/t-dyn/src/dyn564
- /home/chukyu/t-dyn/src/dyn574
- /home/chukyu/t-dyn/src/dyn575
- /home/chukyu/t-dyn/src/dyn590
- /home/chukyu/t-dyn/src/dyn591
- /home/chukyu/t-dyn/src/dyn700
- /home/chukyu/t-dyn/src/dyn720
- /home/chukyu/t-dyn/src/dyn731
- /home/chukyu/t-dyn/src/dyn732
- /home/chukyu/t-dyn/src/dyn740
- /home/chukyu/t-dyn/src/dyn750
- /home/chukyu/t-dyn/src/dyn760
- /home/chukyu/t-dyn/src/dyn761
- /home/chukyu/t-dyn/src/dyn770
- /home/chukyu/t-dyn/src/dyn772
- /home/chukyu/t-dyn/src/dyn773
- /home/chukyu/t-dyn/src/dyn780
- /home/chukyu/t-dyn/src/dyn790
- /home/chukyu/t-dyn/src/dyn820d
- /home/chukyu/t-dyn/src/dyn831
- /home/chukyu/t-dyn/src/dyn832
- /home/chukyu/t-dyn/src/dyn833
- /home/chukyu/t-dyn/src/dyn910
- /home/chukyu/t-dyn/tool/2612
- /home/chukyu/t-dyn/tool/CtlMainteDmp
- /home/chukyu/t-dyn/tool/DynReEmeKanIndDmp
- /home/chukyu/t-dyn/tool/SetGrpIdx
- /home/chukyu/t-dyn/tool/SetGrpSet
- /home/chukyu/t-dyn/tool/dyntest

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
one of the 410 claim rows (all 392 unique sites) receives a verdict —
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
## Audit report — subagent 3 (appended)

### Batch summary

- Sites audited: **392 / 392** (all unique (file,line) sites in agent3_claims.csv; all 410 claim rows reconciled — multi-row sites carry one block covering every operation row).
- Batch statistics reconcile: 410 claim rows -> 392 unique sites (sites with two operation rows, e.g. READ+WRITE on the same open, counted once).

Per-verdict counts (primary site verdict, c-viz side):
- BOTH_CORRECT_SAME: 151
- CVIZ_CORRECT_ONLY (c-viz value source-valid; legacy absent): 57  (of these, 7 sites also carry LEGACY_OVERAPPROXIMATION on the legacy side — stale enum values)
- CVIZ_UNDERAPPROXIMATION where legacy side IS correct (legacy-correct-only sites): 3
- CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION (both pipelines status-only, source values provable): 180
- UNDECIDED: 1

Legacy-side verdict counts: BOTH_CORRECT_SAME 151, none/under-approximation 230, LEGACY_OVERAPPROXIMATION 7, LEGACY_CORRECT_ONLY 3, UNDECIDED 1.

Per-cause-tag counts (sites carrying the tag):
- UNREACHABLE_ROOT_MODEL: 154
- MISSING_ASSIGNMENT_EDGE: 52
- MISSING_WRAPPER_MAPPING: 24
- STALE_HEADER_OR_SOURCE: 7
- open site itself: 5
- HANDLE_BINDING_NOT_PROPAGATED: 1
- INSUFFICIENT_EVIDENCE: 1

- Precision: 362/369 = 98.1%  (accepted reported values / all reported values; a legacy OK_CONST macro name counts as the reported value)
- Coverage: 47/112 = 42.0%  (accepted distinct values / all source-backed distinct expected values; distinct counted once globally per definitions; runtime range sets expanded)
- (per-site-occurrence view: 362/658 accepted value-occurrences of 658 expected value-occurrences = 32.5% note: occurrences double-count shared values; the distinct-value view above is the one used for the batch metric)

Method notes: all FNO constants resolved from the single active header /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum, current revision after <#31214> file-number migration); no /home/chukyu_exe archived headers used. Handle identity was checked per site (open -> use interval, error-path closes excluded). Table-lookup wrappers (DynREGetPfmfno / DynREGetSchfno / DynREGetSchKKfno / DynREGetSchKKLCfno) were unwrapped from /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c and DynREGetScheKKPos.c. No site in this batch lies in a disabled preprocessor branch (checked `#if 0` / guard structure in every file; the only conditional value in the batch, dyn432dAdvCtrl iFnoInd, is a live runtime branch).

### Site verdicts

#### src/dyn010/

### /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:161
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn010CtlMainte(); expr `DynReCtlInfFNO`
Expected: [3918]  (PATH_VALID)
  - proof: open DynReCtlInfFNO at dyn010Main.c:161; DynReCtlInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn010CtlMainte() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3918 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3918
legacy: DynReCtlInfFNO (OK_CONST) = 3918 -> BOTH_CORRECT_SAME -- same source value via DynReCtlInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:167
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn010CtlMainte(); expr `&fcb`
Expected: [3918]  (PATH_VALID)
  - proof: open DynReCtlInfFNO at dyn010Main.c:161; DynReCtlInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn010CtlMainte() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3918 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3918
legacy: DynReCtlInfFNO (OK_CONST) = 3918 -> BOTH_CORRECT_SAME -- same source value via DynReCtlInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:171
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn010CtlMainte(); expr `DynReGnInfFNO`
Expected: [3970]  (PATH_VALID)
  - proof: open DynReGnInfFNO at dyn010Main.c:171; DynReGnInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn010CtlMainte() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3970 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3970
legacy: DynReGnInfFNO (OK_CONST) = 3970 -> BOTH_CORRECT_SAME -- same source value via DynReGnInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:177
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn010CtlMainte(); expr `&fcb`
Expected: [3970]  (PATH_VALID)
  - proof: open DynReGnInfFNO at dyn010Main.c:171; DynReGnInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn010CtlMainte() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3970 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3970
legacy: DynReGnInfFNO (OK_CONST) = 3970 -> BOTH_CORRECT_SAME -- same source value via DynReGnInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:191
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn010CtlMainte(); expr `&fcb`
Expected: [3973]  (PATH_VALID)
  - proof: open DynReCtlMainteFNO at dyn010Main.c:181; DynReCtlMainteFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (current value 3973) (dyn010CtlMainte() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3973 (EXACT) -> CVIZ_CORRECT_ONLY -- equals current enum value 3973
legacy: 1077 (macro DynReCtlMainteFNO OK_CONST, numeric 1077) -> LEGACY_OVERAPPROXIMATION -- 1077 is the pre-<#31214> dummy position of DynReCtlMainteFNO; current source value is 3973; 1077 cannot reach this site
Confidence: high
Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:195
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn010CtlMainte(); expr `&fcb`
Expected: [3973]  (PATH_VALID)
  - proof: open DynReCtlMainteFNO at dyn010Main.c:181; DynReCtlMainteFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (current value 3973) (dyn010CtlMainte() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3973 (EXACT) -> CVIZ_CORRECT_ONLY -- equals current enum value 3973
legacy: 1077 (macro DynReCtlMainteFNO OK_CONST, numeric 1077) -> LEGACY_OVERAPPROXIMATION -- 1077 is the pre-<#31214> dummy position of DynReCtlMainteFNO; current source value is 3973; 1077 cannot reach this site
Confidence: high
Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:200
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn010CtlMainte(); expr `&fcb`
Expected: [3973]  (PATH_VALID)
  - proof: open DynReCtlMainteFNO at dyn010Main.c:181; DynReCtlMainteFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (current value 3973) (dyn010CtlMainte() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3973 (EXACT) -> CVIZ_CORRECT_ONLY -- equals current enum value 3973
legacy: 1077 (macro DynReCtlMainteFNO OK_CONST, numeric 1077) -> LEGACY_OVERAPPROXIMATION -- 1077 is the pre-<#31214> dummy position of DynReCtlMainteFNO; current source value is 3973; 1077 cannot reach this site
Confidence: high
Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:202
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn010CtlMainte(); expr `&fcb`
Expected: [3973]  (PATH_VALID)
  - proof: open DynReCtlMainteFNO at dyn010Main.c:181; DynReCtlMainteFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (current value 3973) (dyn010CtlMainte() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3973 (EXACT) -> CVIZ_CORRECT_ONLY -- equals current enum value 3973
legacy: 1077 (macro DynReCtlMainteFNO OK_CONST, numeric 1077) -> LEGACY_OVERAPPROXIMATION -- 1077 is the pre-<#31214> dummy position of DynReCtlMainteFNO; current source value is 3973; 1077 cannot reach this site
Confidence: high
Cause tags: STALE_HEADER_OR_SOURCE


#### src/dyn011/

### /home/chukyu/t-dyn/src/dyn011/dyn011InitSts.c:107
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn011ReEneHesCtrl(); expr `DynReSndStaDFSFNO`
Expected: [3949]  (PATH_VALID)
  - proof: open DynReSndStaDFSFNO at dyn011InitSts.c:107; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn011ReEneHesCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3949 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3949
legacy: DynReSndStaDFSFNO (OK_CONST) = 3949 -> BOTH_CORRECT_SAME -- same source value via DynReSndStaDFSFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn011/dyn011InitSts.c:118
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn011ReEneHesCtrl(); expr `&fcb`
Expected: [3949]  (PATH_VALID)
  - proof: open DynReSndStaDFSFNO at dyn011InitSts.c:107; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn011ReEneHesCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3949 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3949
legacy: DynReSndStaDFSFNO (OK_CONST) = 3949 -> BOTH_CORRECT_SAME -- same source value via DynReSndStaDFSFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn011/dyn011InitSts.c:123
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn011ReEneHesCtrl(); expr `DynReHESStaUpdDFNO`
Expected: [3972]  (PATH_VALID)
  - proof: open DynReHESStaUpdDFNO at dyn011InitSts.c:123; DynReHESStaUpdDFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn011ReEneHesCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3972 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3972
legacy: DynReHESStaUpdDFNO (OK_CONST) = 3972 -> BOTH_CORRECT_SAME -- same source value via DynReHESStaUpdDFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn011/dyn011InitSts.c:132
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn011ReEneHesCtrl(); expr `&fcb`
Expected: [3972]  (PATH_VALID)
  - proof: open DynReHESStaUpdDFNO at dyn011InitSts.c:123; DynReHESStaUpdDFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn011ReEneHesCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3972 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3972
legacy: DynReHESStaUpdDFNO (OK_CONST) = 3972 -> BOTH_CORRECT_SAME -- same source value via DynReHESStaUpdDFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn011/dyn011InitSts.c:175
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn011ReEneHesCtrl(); expr `&fcb`
Expected: [1075]  (PATH_VALID)
  - proof: open DynReMyPageStaFNO at dyn011InitSts.c:168; DynReMyPageStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn011ReEneHesCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1075 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1075
legacy: DynReMyPageStaFNO (OK_CONST) = 1075 -> BOTH_CORRECT_SAME -- same source value via DynReMyPageStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn011/dyn011InitSts.c:231
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn011ReEneHesHealthCtrl(); expr `&fcb`
Expected: [1048]  (PATH_VALID)
  - proof: open DynReHESHealthFNO at dyn011InitSts.c:214; DynReHESHealthFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn011ReEneHesHealthCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1048 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1048
legacy: DynReHESHealthFNO (OK_CONST) = 1048 -> BOTH_CORRECT_SAME -- same source value via DynReHESHealthFNO
Confidence: high
Cause tags: none


#### src/dyn012/

### /home/chukyu/t-dyn/src/dyn012/dyn012InitSts.c:67
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn012InitSts(); expr `&sFcb`
Expected: [3909]  (PATH_VALID)
  - proof: open DynReTaikoSetFNO at dyn012InitSts.c:61; DynReTaikoSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn012InitSts() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3909 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3909
legacy: DynReTaikoSetFNO (OK_CONST) = 3909 -> BOTH_CORRECT_SAME -- same source value via DynReTaikoSetFNO
Confidence: high
Cause tags: none


#### src/dyn014/

### /home/chukyu/t-dyn/src/dyn014/dyn014CyclicProc.c:181
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn014CyclicProc(); expr `DynReITCInfFNO`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn014CyclicProc.c:181; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn014CyclicProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn014/dyn014CyclicProc.c:189
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn014CyclicProc(); expr `&fcb`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn014CyclicProc.c:181; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn014CyclicProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn014/dyn014CyclicProc.c:193
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn014CyclicProc(); expr `DynReOutStaFNO`
Expected: [3937]  (PATH_VALID)
  - proof: open DynReOutStaFNO at dyn014CyclicProc.c:193; DynReOutStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn014CyclicProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3937 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3937
legacy: DynReOutStaFNO (OK_CONST) = 3937 -> BOTH_CORRECT_SAME -- same source value via DynReOutStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn014/dyn014CyclicProc.c:201
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn014CyclicProc(); expr `&fcb`
Expected: [3937]  (PATH_VALID)
  - proof: open DynReOutStaFNO at dyn014CyclicProc.c:193; DynReOutStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn014CyclicProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3937 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3937
legacy: DynReOutStaFNO (OK_CONST) = 3937 -> BOTH_CORRECT_SAME -- same source value via DynReOutStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn014/dyn014CyclicProc.c:222
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn014CyclicProc(); expr `&fcb`
Expected: [3937]  (PATH_VALID)
  - proof: open DynReOutStaFNO at dyn014CyclicProc.c:193; DynReOutStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn014CyclicProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3937 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3937
legacy: DynReOutStaFNO (OK_CONST) = 3937 -> BOTH_CORRECT_SAME -- same source value via DynReOutStaFNO
Confidence: high
Cause tags: none


#### src/dyn235d/

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:91
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn235dReEneCtl(); expr `DynReITCInfFNO`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn235dReEneCtl.c:91; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:99
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn235dReEneCtl(); expr `&fcb`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn235dReEneCtl.c:91; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:118
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn235dReEneCtl(); expr `DynReCtlStaFNO`
Expected: [3919]  (PATH_VALID)
  - proof: open DynReCtlStaFNO at dyn235dReEneCtl.c:118; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3919 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3919
legacy: DynReCtlStaFNO (OK_CONST) = 3919 -> BOTH_CORRECT_SAME -- same source value via DynReCtlStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:126
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn235dReEneCtl(); expr `&fcb`
Expected: [3919]  (PATH_VALID)
  - proof: open DynReCtlStaFNO at dyn235dReEneCtl.c:118; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3919 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3919
legacy: DynReCtlStaFNO (OK_CONST) = 3919 -> BOTH_CORRECT_SAME -- same source value via DynReCtlStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:129
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn235dReEneCtl(); expr `DynReKansiStaFNO`
Expected: [3945]  (PATH_VALID)
  - proof: open DynReKansiStaFNO at dyn235dReEneCtl.c:129; DynReKansiStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3945 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3945
legacy: DynReKansiStaFNO (OK_CONST) = 3945 -> BOTH_CORRECT_SAME -- same source value via DynReKansiStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:138
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn235dReEneCtl(); expr `&fcb_Kansi`
Expected: [3945]  (PATH_VALID)
  - proof: open DynReKansiStaFNO at dyn235dReEneCtl.c:129; DynReKansiStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3945 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3945
legacy: DynReKansiStaFNO (OK_CONST) = 3945 -> BOTH_CORRECT_SAME -- same source value via DynReKansiStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:151
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn235dReEneCtl(); expr `&fcb_Alzn`
Expected: [4012]  (PATH_VALID)
  - proof: open DynReCtlStaAlznFNO at dyn235dReEneCtl.c:141; DynReCtlStaAlznFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 4012 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 4012
legacy: DynReCtlStaAlznFNO (OK_CONST) = 4012 -> BOTH_CORRECT_SAME -- same source value via DynReCtlStaAlznFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:299
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn235dReEneCtl(); expr `&fcb`
Expected: [3919]  (PATH_VALID)
  - proof: &fcb opened on DynReCtlStaFNO at line 118; close only after the write at line 300; error closes (135,147-148,165-167,184-186) return before line 299 (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNRESOLVED) -> CVIZ_UNDERAPPROXIMATION -- handle identity from same-function open not propagated
legacy: DynReCtlStaFNO (OK_CONST, LLM_HANDLE) = 3919 -> LEGACY_CORRECT_ONLY -- legacy traced handle to correct open
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:301
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn235dReEneCtl(); expr `&fcb_Kansi`
Expected: [3945]  (PATH_VALID)
  - proof: &fcb_Kansi opened on DynReKansiStaFNO at line 129; close only after the write at line 302; error closes (135,147-148,165-167,184-186) return before line 301 (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNRESOLVED) -> CVIZ_UNDERAPPROXIMATION -- handle identity from same-function open not propagated
legacy: DynReKansiStaFNO (OK_CONST, LLM_HANDLE) = 3945 -> LEGACY_CORRECT_ONLY -- legacy traced handle to correct open
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:303
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn235dReEneCtl(); expr `&fcb_Alzn`
Expected: [4012]  (PATH_VALID)
  - proof: &fcb_Alzn opened on DynReCtlStaAlznFNO at line 141; close only after the write at line 304; error closes (135,147-148,165-167,184-186) return before line 303 (dyn235dReEneCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNRESOLVED) -> CVIZ_UNDERAPPROXIMATION -- handle identity from same-function open not propagated
legacy: DynReCtlStaAlznFNO (OK_CONST, LLM_HANDLE) = 4012 -> LEGACY_CORRECT_ONLY -- legacy traced handle to correct open
Confidence: high
Cause tags: none


#### src/dyn240d/

### /home/chukyu/t-dyn/src/dyn240d/dyn240d.c:150
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReSndStaDFSFNO`
Expected: [3949]  (PATH_VALID)
  - proof: open DynReSndStaDFSFNO at dyn240d.c:150; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3949 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3949
legacy: DynReSndStaDFSFNO (OK_CONST) = 3949 -> BOTH_CORRECT_SAME -- same source value via DynReSndStaDFSFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn240d/dyn240d.c:161
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3949]  (PATH_VALID)
  - proof: open DynReSndStaDFSFNO at dyn240d.c:150; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3949 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3949
legacy: DynReSndStaDFSFNO (OK_CONST) = 3949 -> BOTH_CORRECT_SAME -- same source value via DynReSndStaDFSFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn240d/dyn240d.c:177
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3949]  (PATH_VALID)
  - proof: open DynReSndStaDFSFNO at dyn240d.c:150; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3949 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3949
legacy: DynReSndStaDFSFNO (OK_CONST) = 3949 -> BOTH_CORRECT_SAME -- same source value via DynReSndStaDFSFNO
Confidence: high
Cause tags: none


#### src/dyn251d/

### /home/chukyu/t-dyn/src/dyn251d/dyn251d.c:127
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReSndStaDFSFNO`
Expected: [3949]  (PATH_VALID)
  - proof: open DynReSndStaDFSFNO at dyn251d.c:127; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3949 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3949
legacy: DynReSndStaDFSFNO (OK_CONST) = 3949 -> BOTH_CORRECT_SAME -- same source value via DynReSndStaDFSFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn251d/dyn251d.c:135
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3949]  (PATH_VALID)
  - proof: open DynReSndStaDFSFNO at dyn251d.c:127; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3949 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3949
legacy: DynReSndStaDFSFNO (OK_CONST) = 3949 -> BOTH_CORRECT_SAME -- same source value via DynReSndStaDFSFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn251d/dyn251d.c:175
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3949]  (PATH_VALID)
  - proof: open DynReSndStaDFSFNO at dyn251d.c:127; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3949 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3949
legacy: DynReSndStaDFSFNO (OK_CONST) = 3949 -> BOTH_CORRECT_SAME -- same source value via DynReSndStaDFSFNO
Confidence: high
Cause tags: none


#### src/dyn255d/

### /home/chukyu/t-dyn/src/dyn255d/dyn255d.c:100
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1342]  (PATH_VALID)
  - proof: open DynReAtEmeSvStaFNO at dyn255d.c:94; DynReAtEmeSvStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1342 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1342
legacy: DynReAtEmeSvStaFNO (OK_CONST) = 1342 -> BOTH_CORRECT_SAME -- same source value via DynReAtEmeSvStaFNO
Confidence: high
Cause tags: none


#### src/dyn260/

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:108
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn260Main.c:108; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:113
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn260Main.c:108; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:122
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn260Main.c:117; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:131
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3986]  (PATH_VALID)
  - proof: open DynReCtlMntStaFNO at dyn260Main.c:126; DynReCtlMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3986 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3986
legacy: DynReCtlMntStaFNO (OK_CONST) = 3986 -> BOTH_CORRECT_SAME -- same source value via DynReCtlMntStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:140
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3987]  (PATH_VALID)
  - proof: open DynReCtlMntSetFNO at dyn260Main.c:135; DynReCtlMntSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3987 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3987
legacy: DynReCtlMntSetFNO (OK_CONST) = 3987 -> BOTH_CORRECT_SAME -- same source value via DynReCtlMntSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:149
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3989]  (PATH_VALID)
  - proof: open DynReKoteMntStaFNO at dyn260Main.c:144; DynReKoteMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3989 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3989
legacy: DynReKoteMntStaFNO (OK_CONST) = 3989 -> BOTH_CORRECT_SAME -- same source value via DynReKoteMntStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:156
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3990]  (PATH_VALID)
  - proof: open DynReKoteMntSetFNO at dyn260Main.c:151; DynReKoteMntSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3990 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3990
legacy: DynReKoteMntSetFNO (OK_CONST) = 3990 -> BOTH_CORRECT_SAME -- same source value via DynReKoteMntSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:165
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [4013]  (PATH_VALID)
  - proof: open DynReKoTeiHtSetFNO at dyn260Main.c:160; DynReKoTeiHtSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 4013 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 4013
legacy: DynReKoTeiHtSetFNO (OK_CONST) = 4013 -> BOTH_CORRECT_SAME -- same source value via DynReKoTeiHtSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn260/dyn260Main.c:254
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1034]  (PATH_VALID)
  - proof: open DynReSchCsvRedFNO at dyn260Main.c:246; DynReSchCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1034 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1034
legacy: DynReSchCsvRedFNO (OK_CONST) = 1034 -> BOTH_CORRECT_SAME -- same source value via DynReSchCsvRedFNO
Confidence: high
Cause tags: none


#### src/dyn261/

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:134
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn261Main.c:134; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:139
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn261Main.c:134; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:148
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn261Main.c:143; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:157
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3986]  (PATH_VALID)
  - proof: open DynReCtlMntStaFNO at dyn261Main.c:152; DynReCtlMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3986 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3986
legacy: DynReCtlMntStaFNO (OK_CONST) = 3986 -> BOTH_CORRECT_SAME -- same source value via DynReCtlMntStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:166
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3987]  (PATH_VALID)
  - proof: open DynReCtlMntSetFNO at dyn261Main.c:161; DynReCtlMntSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3987 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3987
legacy: DynReCtlMntSetFNO (OK_CONST) = 3987 -> BOTH_CORRECT_SAME -- same source value via DynReCtlMntSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:175
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3989]  (PATH_VALID)
  - proof: open DynReKoteMntStaFNO at dyn261Main.c:170; DynReKoteMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3989 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3989
legacy: DynReKoteMntStaFNO (OK_CONST) = 3989 -> BOTH_CORRECT_SAME -- same source value via DynReKoteMntStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:182
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3990]  (PATH_VALID)
  - proof: open DynReKoteMntSetFNO at dyn261Main.c:177; DynReKoteMntSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3990 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3990
legacy: DynReKoteMntSetFNO (OK_CONST) = 3990 -> BOTH_CORRECT_SAME -- same source value via DynReKoteMntSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:191
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [4013]  (PATH_VALID)
  - proof: open DynReKoTeiHtSetFNO at dyn261Main.c:186; DynReKoTeiHtSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 4013 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 4013
legacy: DynReKoTeiHtSetFNO (OK_CONST) = 4013 -> BOTH_CORRECT_SAME -- same source value via DynReKoTeiHtSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn261/dyn261Main.c:289
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1500]  (PATH_VALID)
  - proof: open DynReSchCsvRed2FNO at dyn261Main.c:281; DynReSchCsvRed2FNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1500 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1500
legacy: DynReSchCsvRed2FNO (OK_CONST) = 1500 -> BOTH_CORRECT_SAME -- same source value via DynReSchCsvRed2FNO
Confidence: high
Cause tags: none


#### src/dyn262/

### /home/chukyu/t-dyn/src/dyn262/dyn262Main.c:95
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3909]  (PATH_VALID)
  - proof: open DynReTaikoSetFNO at dyn262Main.c:94; DynReTaikoSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3909 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3909
legacy: DynReTaikoSetFNO (OK_CONST) = 3909 -> BOTH_CORRECT_SAME -- same source value via DynReTaikoSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn262/dyn262Main.c:112
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn262Main.c:107; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn262/dyn262Main.c:121
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3986]  (PATH_VALID)
  - proof: open DynReCtlMntStaFNO at dyn262Main.c:116; DynReCtlMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3986 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3986
legacy: DynReCtlMntStaFNO (OK_CONST) = 3986 -> BOTH_CORRECT_SAME -- same source value via DynReCtlMntStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn262/dyn262Main.c:130
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3987]  (PATH_VALID)
  - proof: open DynReCtlMntSetFNO at dyn262Main.c:125; DynReCtlMntSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3987 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3987
legacy: DynReCtlMntSetFNO (OK_CONST) = 3987 -> BOTH_CORRECT_SAME -- same source value via DynReCtlMntSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn262/dyn262Main.c:216
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3901]  (PATH_VALID)
  - proof: open DynReGstCsvRedFNO at dyn262Main.c:208; DynReGstCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3901 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3901
legacy: DynReGstCsvRedFNO (OK_CONST) = 3901 -> BOTH_CORRECT_SAME -- same source value via DynReGstCsvRedFNO
Confidence: high
Cause tags: none


#### src/dyn263/

### /home/chukyu/t-dyn/src/dyn263/dyn263Main.c:93
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn263Main.c:88; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn263/dyn263Main.c:173
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3902]  (PATH_VALID)
  - proof: open DynReGmjCsvRedFNO at dyn263Main.c:165; DynReGmjCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3902 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3902
legacy: DynReGmjCsvRedFNO (OK_CONST) = 3902 -> BOTH_CORRECT_SAME -- same source value via DynReGmjCsvRedFNO
Confidence: high
Cause tags: none


#### src/dyn264/

### /home/chukyu/t-dyn/src/dyn264/dyn264Main.c:88
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3909]  (PATH_VALID)
  - proof: open DynReTaikoSetFNO at dyn264Main.c:87; DynReTaikoSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3909 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3909
legacy: DynReTaikoSetFNO (OK_CONST) = 3909 -> BOTH_CORRECT_SAME -- same source value via DynReTaikoSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn264/dyn264Main.c:174
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3903]  (PATH_VALID)
  - proof: open DynReHatuCsvRedFNO at dyn264Main.c:166; DynReHatuCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3903 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3903
legacy: DynReHatuCsvRedFNO (OK_CONST) = 3903 -> BOTH_CORRECT_SAME -- same source value via DynReHatuCsvRedFNO
Confidence: high
Cause tags: none


#### src/dyn266/

### /home/chukyu/t-dyn/src/dyn266/dyn266Main.c:138
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3991]  (PATH_VALID)
  - proof: open DynReKoteCsvRedFNO at dyn266Main.c:130; DynReKoteCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3991 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3991
legacy: DynReKoteCsvRedFNO (OK_CONST) = 3991 -> BOTH_CORRECT_SAME -- same source value via DynReKoteCsvRedFNO
Confidence: high
Cause tags: none


#### src/dyn267/

### /home/chukyu/t-dyn/src/dyn267/dyn267Main.c:92
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn267Main.c:87; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn267/dyn267Main.c:101
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3988]  (PATH_VALID)
  - proof: open DynReKoteMainteFNO at dyn267Main.c:96; DynReKoteMainteFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3988 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3988
legacy: DynReKoteMainteFNO (OK_CONST) = 3988 -> BOTH_CORRECT_SAME -- same source value via DynReKoteMainteFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn267/dyn267Main.c:160
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3992]  (PATH_VALID)
  - proof: open DynReGstCsvRed2FNO at dyn267Main.c:152; DynReGstCsvRed2FNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3992 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3992
legacy: DynReGstCsvRed2FNO (OK_CONST) = 3992 -> BOTH_CORRECT_SAME -- same source value via DynReGstCsvRed2FNO
Confidence: high
Cause tags: none


#### src/dyn311d/

### /home/chukyu/t-dyn/src/dyn311d/dyn311d.c:123
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReITCInfFNO`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn311d.c:123; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn311d/dyn311d.c:124
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn311d.c:123; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none


#### src/dyn322d/

### /home/chukyu/t-dyn/src/dyn322d/dyn322dReadOutData.c:66
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn322dReadOutData(); expr `&Fcb`
Expected: [1028]  (PATH_VALID)
  - proof: open DynReSsAdrDefFNO at dyn322dReadOutData.c:55; DynReSsAdrDefFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn322dReadOutData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1028 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1028
legacy: DynReSsAdrDefFNO (OK_CONST) = 1028 -> BOTH_CORRECT_SAME -- same source value via DynReSsAdrDefFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn322d/dyn322dReadOutData.c:74
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn322dReadOutData(); expr `DynReOutStaFNO`
Expected: [3937]  (PATH_VALID)
  - proof: open DynReOutStaFNO at dyn322dReadOutData.c:74; DynReOutStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn322dReadOutData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3937 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3937
legacy: DynReOutStaFNO (OK_CONST) = 3937 -> BOTH_CORRECT_SAME -- same source value via DynReOutStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn322d/dyn322dReadOutData.c:83
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn322dReadOutData(); expr `&Fcb`
Expected: [3937]  (PATH_VALID)
  - proof: open DynReOutStaFNO at dyn322dReadOutData.c:74; DynReOutStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn322dReadOutData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3937 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3937
legacy: DynReOutStaFNO (OK_CONST) = 3937 -> BOTH_CORRECT_SAME -- same source value via DynReOutStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn322d/dyn322dReadOutData.c:97
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn322dReadOutData(); expr `&Fcb`
Expected: [3937]  (PATH_VALID)
  - proof: Fcb opened WRITELOCK on DynReOutStaFNO at line 74; the close at 93 is only on the error path of dyn322dSireiClearRestore(1,...) (returns), so line 97 executes with the same handle (dyn322dReadOutData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNRESOLVED) -> CVIZ_UNDERAPPROXIMATION -- same-function open->use edge missed
legacy: no value (raw &Fcb only) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no numeric value although 3937 is provable
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE; HANDLE_BINDING_NOT_PROPAGATED

### /home/chukyu/t-dyn/src/dyn322d/dyn322dReadOutData.c:114
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn322dReadOutData(); expr `DynReITCInfFNO`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn322dReadOutData.c:114; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn322dReadOutData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn322d/dyn322dReadOutData.c:122
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn322dReadOutData(); expr `&Fcb`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn322dReadOutData.c:114; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn322dReadOutData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none


#### src/dyn431/

### /home/chukyu/t-dyn/src/dyn431/dyn431Main.c:184
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn431Main.c:176; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn431/dyn431Main.c:189
Target: mpf_mfs_open_H(...), arg 2; enclosing fn main(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn431Main.c:189; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn431/dyn431Main.c:201
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn main(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn431Main.c:189; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn431/dyn431Main.c:210
Target: mpf_mfs_open_H(...), arg 2; enclosing fn main(); expr `DynREGetPfmfno(nFnoidx)`
Expected: [3952-3967]  (PATH_VALID (runtime date-dependent))
  - proof: open at dyn431Main.c:210 via DynREGetPfmfno(nFnoidx); /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:260-265 returns ScheFnoTbl[nFnoidx].Pfmfno; table at DynREGetSchePos.c:41-56 = DynReHESPfmKbtFNO..16FNO; nFnoidx = 0..15 from DynREGetSchePos2 (DynREGetSchePos.c:223) (main() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- table-lookup wrapper DynREGetPfmfno not unwrapped
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- both pipelines left wrapper unresolved although full 16-value set is source-derivable
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn431/dyn431Main.c:219
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn main(); expr `&fcb`
Expected: [3952-3967]  (PATH_VALID (runtime date-dependent))
  - proof: open at dyn431Main.c:210 via DynREGetPfmfno(nFnoidx); /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:260-265 returns ScheFnoTbl[nFnoidx].Pfmfno; table at DynREGetSchePos.c:41-56 = DynReHESPfmKbtFNO..16FNO; nFnoidx = 0..15 from DynREGetSchePos2 (DynREGetSchePos.c:223) (main() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- table-lookup wrapper DynREGetPfmfno not unwrapped
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- both pipelines left wrapper unresolved although full 16-value set is source-derivable
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn431/dyn431Main.c:228
Target: mpf_mfs_open_H(...), arg 2; enclosing fn main(); expr `DynREGetPfmfno(nFnoidx)`
Expected: [3952-3967]  (PATH_VALID (runtime date-dependent))
  - proof: open at dyn431Main.c:228 via DynREGetPfmfno(nFnoidx); /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:260-265 returns ScheFnoTbl[nFnoidx].Pfmfno; table at DynREGetSchePos.c:41-56 = DynReHESPfmKbtFNO..16FNO; nFnoidx = 0..15 from DynREGetSchePos2 (DynREGetSchePos.c:223) (main() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- table-lookup wrapper DynREGetPfmfno not unwrapped
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- both pipelines left wrapper unresolved although full 16-value set is source-derivable
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn431/dyn431Main.c:240
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn main(); expr `&fcb`
Expected: [3952-3967]  (PATH_VALID (runtime date-dependent))
  - proof: open at dyn431Main.c:228 via DynREGetPfmfno(nFnoidx); /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:260-265 returns ScheFnoTbl[nFnoidx].Pfmfno; table at DynREGetSchePos.c:41-56 = DynReHESPfmKbtFNO..16FNO; nFnoidx = 0..15 from DynREGetSchePos2 (DynREGetSchePos.c:223) (main() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- table-lookup wrapper DynREGetPfmfno not unwrapped
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- both pipelines left wrapper unresolved although full 16-value set is source-derivable
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING


#### src/dyn432d/

### /home/chukyu/t-dyn/src/dyn432d/dyn432dAdvCtrl.c:108
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn432dAdvCtrl(); expr `iFnoInd`
Expected: [{3946, 3983}]  (PATH_VALID (branch on nTaiko))
  - proof: iFnoInd = DynAdvCtlStaITkFNO (3983) if nTaiko else DynAdvCtlStaIndFNO (3946) at dyn432dAdvCtrl.c:66-73; caller passes both 0 and 1; fcb opened at line 108 and used at 116/269 (close at 271) (dyn432dAdvCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: {3946, 3983} (EXACT x2) -> CVIZ_CORRECT_ONLY -- both branch values present, both reachable
legacy: no value (statuses empty) -> LEGACY_UNDERAPPROXIMATION -- legacy missed both branch values
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dAdvCtrl.c:116
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn432dAdvCtrl(); expr `&fcb`
Expected: [{3946, 3983}]  (PATH_VALID (branch on nTaiko))
  - proof: iFnoInd = DynAdvCtlStaITkFNO (3983) if nTaiko else DynAdvCtlStaIndFNO (3946) at dyn432dAdvCtrl.c:66-73; caller passes both 0 and 1; fcb opened at line 108 and used at 116/269 (close at 271) (dyn432dAdvCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: {3946, 3983} (EXACT x2) -> CVIZ_CORRECT_ONLY -- both branch values present, both reachable
legacy: no value (statuses empty) -> LEGACY_UNDERAPPROXIMATION -- legacy missed both branch values
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dAdvCtrl.c:269
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn432dAdvCtrl(); expr `&fcb`
Expected: [{3946, 3983}]  (PATH_VALID (branch on nTaiko))
  - proof: iFnoInd = DynAdvCtlStaITkFNO (3983) if nTaiko else DynAdvCtlStaIndFNO (3946) at dyn432dAdvCtrl.c:66-73; caller passes both 0 and 1; fcb opened at line 108 and used at 116/269 (close at 271) (dyn432dAdvCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: {3946, 3983} (EXACT x2) -> CVIZ_CORRECT_ONLY -- both branch values present, both reachable
legacy: no value (statuses empty) -> LEGACY_UNDERAPPROXIMATION -- legacy missed both branch values
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:95
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn432dReEneCtrl(); expr `&fcb`
Expected: [3909]  (PATH_VALID)
  - proof: open DynReTaikoSetFNO at dyn432dReEneCtrl.c:88 (closes only at 354/356 after use or on error returns); DynReTaikoSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3909 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReTaikoSetFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:106
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn432dReEneCtrl(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn432dReEneCtrl.c:100 (closes only at 354/356 after use or on error returns); DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReGrpIdxFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:110
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn432dReEneCtrl(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn432dReEneCtrl.c:110 (closes only at 354/356 after use or on error returns); DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReGrpSetFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:116
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn432dReEneCtrl(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn432dReEneCtrl.c:110 (closes only at 354/356 after use or on error returns); DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReGrpSetFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:162
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn432dReEneCtrl(); expr `DynReCtlStaFNO`
Expected: [3919]  (PATH_VALID)
  - proof: open DynReCtlStaFNO at dyn432dReEneCtrl.c:162 (closes only at 354/356 after use or on error returns); DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3919 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReCtlStaFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:170
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn432dReEneCtrl(); expr `&fcb`
Expected: [3919]  (PATH_VALID)
  - proof: open DynReCtlStaFNO at dyn432dReEneCtrl.c:162 (closes only at 354/356 after use or on error returns); DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3919 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReCtlStaFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:181
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn432dReEneCtrl(); expr `&fcb_Alzn`
Expected: [4012]  (PATH_VALID)
  - proof: open DynReCtlStaAlznFNO at dyn432dReEneCtrl.c:173 (closes only at 354/356 after use or on error returns); DynReCtlStaAlznFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 4012 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReCtlStaAlznFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:353
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn432dReEneCtrl(); expr `&fcb_Alzn`
Expected: [4012]  (PATH_VALID)
  - proof: open DynReCtlStaAlznFNO at dyn432dReEneCtrl.c:173 (closes only at 354/356 after use or on error returns); DynReCtlStaAlznFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 4012 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReCtlStaAlznFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/src/dyn432d/dyn432dReEneCtrl.c:355
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn432dReEneCtrl(); expr `&fcb`
Expected: [3919]  (PATH_VALID)
  - proof: open DynReCtlStaFNO at dyn432dReEneCtrl.c:162 (closes only at 354/356 after use or on error returns); DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn432dReEneCtrl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3919 (EXACT) -> CVIZ_CORRECT_ONLY -- equals open of DynReCtlStaFNO
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE


#### src/dyn441/

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:85
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn441AtComProc(); expr `&sFcb`
Expected: [1342]  (PATH_VALID)
  - proof: open DynReAtEmeSvStaFNO at dyn441AtComProc.c:79; DynReAtEmeSvStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1342 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1342
legacy: DynReAtEmeSvStaFNO (OK_CONST) = 1342 -> BOTH_CORRECT_SAME -- same source value via DynReAtEmeSvStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:109
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn441AtComProc(); expr `&sFcb`
Expected: [1341]  (PATH_VALID)
  - proof: open DynReAtEmeSetFNO at dyn441AtComProc.c:103; DynReAtEmeSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1341 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1341
legacy: DynReAtEmeSetFNO (OK_CONST) = 1341 -> BOTH_CORRECT_SAME -- same source value via DynReAtEmeSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:126
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn441AtComProc(); expr `&sFcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn441AtComProc.c:120; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:130
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn441AtComProc(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn441AtComProc.c:130; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:136
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn441AtComProc(); expr `&sFcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn441AtComProc.c:130; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:142
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn441AtComProc(); expr `DynReCtlStaFNO`
Expected: [3919]  (PATH_VALID)
  - proof: open DynReCtlStaFNO at dyn441AtComProc.c:142; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3919 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3919
legacy: DynReCtlStaFNO (OK_CONST) = 3919 -> BOTH_CORRECT_SAME -- same source value via DynReCtlStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:148
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn441AtComProc(); expr `&sFcb`
Expected: [3919]  (PATH_VALID)
  - proof: open DynReCtlStaFNO at dyn441AtComProc.c:142; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3919 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3919
legacy: DynReCtlStaFNO (OK_CONST) = 3919 -> BOTH_CORRECT_SAME -- same source value via DynReCtlStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:152
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn441AtComProc(); expr `DynAdvCtlStaIndFNO`
Expected: [3946]  (PATH_VALID)
  - proof: open DynAdvCtlStaIndFNO at dyn441AtComProc.c:152; DynAdvCtlStaIndFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3946 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3946
legacy: DynAdvCtlStaIndFNO (OK_CONST) = 3946 -> BOTH_CORRECT_SAME -- same source value via DynAdvCtlStaIndFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:158
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn441AtComProc(); expr `&sFcb`
Expected: [3946]  (PATH_VALID)
  - proof: open DynAdvCtlStaIndFNO at dyn441AtComProc.c:152; DynAdvCtlStaIndFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3946 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3946
legacy: DynAdvCtlStaIndFNO (OK_CONST) = 3946 -> BOTH_CORRECT_SAME -- same source value via DynAdvCtlStaIndFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:168
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn441AtComProc(); expr `&sFcb`
Expected: [3976]  (PATH_VALID)
  - proof: open DynReAtEmeKanFNO at dyn441AtComProc.c:162; DynReAtEmeKanFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (current value 3976) (dyn441AtComProc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3976 (EXACT) -> CVIZ_CORRECT_ONLY -- equals current enum value 3976
legacy: 1343 (macro DynReAtEmeKanFNO OK_CONST, numeric 1343) -> LEGACY_OVERAPPROXIMATION -- 1343 is the pre-<#31214> dummy position of DynReAtEmeKanFNO; current source value is 3976; 1343 cannot reach this site
Confidence: high
Cause tags: STALE_HEADER_OR_SOURCE


#### src/dyn500/

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:95
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn500TransSchdule(); expr `DynReTrnDataInfFNO`
Expected: [1073]  (PATH_VALID)
  - proof: open DynReTrnDataInfFNO at dyn500TransSchdule.c:95; DynReTrnDataInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1073 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1073
legacy: DynReTrnDataInfFNO (OK_CONST) = 1073 -> BOTH_CORRECT_SAME -- same source value via DynReTrnDataInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:100
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn500TransSchdule(); expr `&fcb`
Expected: [1073]  (PATH_VALID)
  - proof: open DynReTrnDataInfFNO at dyn500TransSchdule.c:95; DynReTrnDataInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1073 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1073
legacy: DynReTrnDataInfFNO (OK_CONST) = 1073 -> BOTH_CORRECT_SAME -- same source value via DynReTrnDataInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:111
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn500TransSchdule(); expr `&fcb`
Expected: [1071]  (PATH_VALID)
  - proof: open DynReCtlNtcInfFNO at dyn500TransSchdule.c:106; DynReCtlNtcInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1071 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1071
legacy: DynReCtlNtcInfFNO (OK_CONST) = 1071 -> BOTH_CORRECT_SAME -- same source value via DynReCtlNtcInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:117
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn500TransSchdule(); expr `DynReCtlNtcDatFNO`
Expected: [3971]  (PATH_VALID)
  - proof: open DynReCtlNtcDatFNO at dyn500TransSchdule.c:117; DynReCtlNtcDatFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3971 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3971
legacy: DynReCtlNtcDatFNO (OK_CONST) = 3971 -> BOTH_CORRECT_SAME -- same source value via DynReCtlNtcDatFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:125
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn500TransSchdule(); expr `&fcb`
Expected: [3971]  (PATH_VALID)
  - proof: open DynReCtlNtcDatFNO at dyn500TransSchdule.c:117; DynReCtlNtcDatFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3971 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3971
legacy: DynReCtlNtcDatFNO (OK_CONST) = 3971 -> BOTH_CORRECT_SAME -- same source value via DynReCtlNtcDatFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:140
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn500TransSchdule(); expr `DynReCtlNtcDatFNO`
Expected: [3971]  (PATH_VALID)
  - proof: open DynReCtlNtcDatFNO at dyn500TransSchdule.c:140; DynReCtlNtcDatFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3971 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3971
legacy: DynReCtlNtcDatFNO (OK_CONST) = 3971 -> BOTH_CORRECT_SAME -- same source value via DynReCtlNtcDatFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:147
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn500TransSchdule(); expr `&fcb`
Expected: [3971]  (PATH_VALID)
  - proof: open DynReCtlNtcDatFNO at dyn500TransSchdule.c:140; DynReCtlNtcDatFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3971 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3971
legacy: DynReCtlNtcDatFNO (OK_CONST) = 3971 -> BOTH_CORRECT_SAME -- same source value via DynReCtlNtcDatFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:160
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn500TransSchdule(); expr `&fcb`
Expected: [3981]  (PATH_VALID)
  - proof: open DynReCtlNtcDtPvFNO at dyn500TransSchdule.c:155; DynReCtlNtcDtPvFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (current value 3981) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3981 (EXACT) -> CVIZ_CORRECT_ONLY -- equals current enum value 3981
legacy: 3906 (macro DynReCtlNtcDtPvFNO OK_CONST, numeric 3906) -> LEGACY_OVERAPPROXIMATION -- 3906 is the pre-<#31214> dummy position of DynReCtlNtcDtPvFNO; current source value is 3981; 3906 cannot reach this site
Confidence: high
Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:177
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn500TransSchdule(); expr `&fcb`
Expected: [3981]  (PATH_VALID)
  - proof: open DynReCtlNtcDtPvFNO at dyn500TransSchdule.c:155; DynReCtlNtcDtPvFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (current value 3981) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3981 (EXACT) -> CVIZ_CORRECT_ONLY -- equals current enum value 3981
legacy: 3906 (macro DynReCtlNtcDtPvFNO OK_CONST, numeric 3906) -> LEGACY_OVERAPPROXIMATION -- 3906 is the pre-<#31214> dummy position of DynReCtlNtcDtPvFNO; current source value is 3981; 3906 cannot reach this site
Confidence: high
Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:187
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn500TransSchdule(); expr `&fcb`
Expected: [3905]  (PATH_VALID)
  - proof: open DynReTrnSndPfmFNO at dyn500TransSchdule.c:182; DynReTrnSndPfmFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3905 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3905
legacy: DynReTrnSndPfmFNO (OK_CONST) = 3905 -> BOTH_CORRECT_SAME -- same source value via DynReTrnSndPfmFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:454
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn500TransSchdule(); expr `&fcb`
Expected: [3905]  (PATH_VALID)
  - proof: open DynReTrnSndPfmFNO at dyn500TransSchdule.c:445; DynReTrnSndPfmFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn500TransSchdule() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3905 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3905
legacy: DynReTrnSndPfmFNO (OK_CONST) = 3905 -> BOTH_CORRECT_SAME -- same source value via DynReTrnSndPfmFNO
Confidence: high
Cause tags: none


#### src/dyn510d/

### /home/chukyu/t-dyn/src/dyn510d/dyn510dCsvLoad.c:380
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn510dFtpRetQSend(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn510dCsvLoad.c:380; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dCsvLoad.c:390
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn510dFtpRetQSend(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn510dCsvLoad.c:380; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dCsvLoad.c:557
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn510dFtpRetQSend(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn510dCsvLoad.c:557; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dCsvLoad.c:570
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn510dFtpRetQSend(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn510dCsvLoad.c:557; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dCsvLoad.c:594
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn510dFtpRetQSend(); expr `&fcb`
Expected: [1075]  (PATH_VALID)
  - proof: open DynReMyPageStaFNO at dyn510dCsvLoad.c:585; DynReMyPageStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1075 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1075
legacy: DynReMyPageStaFNO (OK_CONST) = 1075 -> BOTH_CORRECT_SAME -- same source value via DynReMyPageStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dCsvLoad.c:598
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn510dFtpRetQSend(); expr `&fcb`
Expected: [1075]  (PATH_VALID)
  - proof: open DynReMyPageStaFNO at dyn510dCsvLoad.c:585; DynReMyPageStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1075 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1075
legacy: DynReMyPageStaFNO (OK_CONST) = 1075 -> BOTH_CORRECT_SAME -- same source value via DynReMyPageStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dCsvLoad.c:626
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn510dFtpRetQSend(); expr `&fcb`
Expected: [1048]  (PATH_VALID)
  - proof: open DynReHESHealthFNO at dyn510dCsvLoad.c:617; DynReHESHealthFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1048 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1048
legacy: DynReHESHealthFNO (OK_CONST) = 1048 -> BOTH_CORRECT_SAME -- same source value via DynReHESHealthFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dCsvLoad.c:631
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn510dFtpRetQSend(); expr `&fcb`
Expected: [1048]  (PATH_VALID)
  - proof: open DynReHESHealthFNO at dyn510dCsvLoad.c:617; DynReHESHealthFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1048 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1048
legacy: DynReHESHealthFNO (OK_CONST) = 1048 -> BOTH_CORRECT_SAME -- same source value via DynReHESHealthFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dFtpGet.c:311
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn510dFtpRetWrite(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn510dFtpGet.c:311; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetWrite() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dFtpGet.c:318
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn510dFtpRetWrite(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn510dFtpGet.c:311; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetWrite() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dFtpGet.c:480
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn510dFtpRetWrite(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn510dFtpGet.c:480; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetWrite() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dFtpGet.c:489
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn510dFtpRetWrite(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn510dFtpGet.c:480; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dFtpRetWrite() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dFtpGet.c:615
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn510dCsvCpy(); expr `DynReTrnDataInfFNO`
Expected: [1073]  (PATH_VALID)
  - proof: open DynReTrnDataInfFNO at dyn510dFtpGet.c:615; DynReTrnDataInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dCsvCpy() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1073 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1073
legacy: DynReTrnDataInfFNO (OK_CONST) = 1073 -> BOTH_CORRECT_SAME -- same source value via DynReTrnDataInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn510d/dyn510dFtpGet.c:621
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn510dCsvCpy(); expr `&fcb`
Expected: [1073]  (PATH_VALID)
  - proof: open DynReTrnDataInfFNO at dyn510dFtpGet.c:615; DynReTrnDataInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn510dCsvCpy() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1073 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1073
legacy: DynReTrnDataInfFNO (OK_CONST) = 1073 -> BOTH_CORRECT_SAME -- same source value via DynReTrnDataInfFNO
Confidence: high
Cause tags: none


#### src/dyn532/

### /home/chukyu/t-dyn/src/dyn532/dyn532FtpFile.c:169
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn532FtpFile(); expr `DynReTrnDataInfFNO`
Expected: [1073]  (PATH_VALID)
  - proof: open DynReTrnDataInfFNO at dyn532FtpFile.c:169; DynReTrnDataInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn532FtpFile() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1073 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1073
legacy: DynReTrnDataInfFNO (OK_CONST) = 1073 -> BOTH_CORRECT_SAME -- same source value via DynReTrnDataInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn532/dyn532FtpFile.c:175
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn532FtpFile(); expr `&fcb`
Expected: [1073]  (PATH_VALID)
  - proof: open DynReTrnDataInfFNO at dyn532FtpFile.c:169; DynReTrnDataInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn532FtpFile() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1073 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1073
legacy: DynReTrnDataInfFNO (OK_CONST) = 1073 -> BOTH_CORRECT_SAME -- same source value via DynReTrnDataInfFNO
Confidence: high
Cause tags: none


#### src/dyn561/

### /home/chukyu/t-dyn/src/dyn561/dyn561FtpRcv.c:480
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn561CSVRecvprc(); expr `&fcb`
Expected: [3993]  (PATH_VALID)
  - proof: open DynReGpIdStaFNO at dyn561FtpRcv.c:472; DynReGpIdStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn561CSVRecvprc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3993 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3993
legacy: DynReGpIdStaFNO (OK_CONST) = 3993 -> BOTH_CORRECT_SAME -- same source value via DynReGpIdStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn561/dyn561FtpRcv.c:542
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn561CSVRecvprc(); expr `&fcb`
Expected: [3993]  (PATH_VALID)
  - proof: open DynReGpIdStaFNO at dyn561FtpRcv.c:531; DynReGpIdStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn561CSVRecvprc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3993 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3993
legacy: DynReGpIdStaFNO (OK_CONST) = 3993 -> BOTH_CORRECT_SAME -- same source value via DynReGpIdStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn561/dyn561FtpRcv.c:599
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn561CSVRecvprc(); expr `&fcb`
Expected: [3994]  (PATH_VALID)
  - proof: open DynReGpIdInfFNO at dyn561FtpRcv.c:590; DynReGpIdInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn561CSVRecvprc() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3994 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3994
legacy: DynReGpIdInfFNO (OK_CONST) = 3994 -> BOTH_CORRECT_SAME -- same source value via DynReGpIdInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn561/dyn561Main.c:135
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn561Main.c:135; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn561/dyn561Main.c:143
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn561Main.c:135; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn561/dyn561Main.c:146
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn561Main.c:135; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none


#### src/dyn564/

### /home/chukyu/t-dyn/src/dyn564/dyn564Main.c:123
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn564Main.c:123; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn564/dyn564Main.c:138
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn564Main.c:123; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn564/dyn564Main.c:142
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn564Main.c:123; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none


#### src/dyn574/

### /home/chukyu/t-dyn/src/dyn574/dyn574Main.c:144
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn574Main.c:144; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn574/dyn574Main.c:152
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn574Main.c:144; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn574/dyn574Main.c:155
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn574Main.c:144; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none


#### src/dyn575/

### /home/chukyu/t-dyn/src/dyn575/dyn575Main.c:135
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn575Main.c:135; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn575/dyn575Main.c:143
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn575Main.c:135; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn575/dyn575Main.c:146
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn575Main.c:135; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none


#### src/dyn590/

### /home/chukyu/t-dyn/src/dyn590/dyn590CsvLoad.c:402
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn590FtpRetQSend(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn590CsvLoad.c:402; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn590FtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn590/dyn590CsvLoad.c:410
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn590FtpRetQSend(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn590CsvLoad.c:402; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn590FtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn590/dyn590CsvLoad.c:536
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn590FtpRetQSend(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn590CsvLoad.c:536; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn590FtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn590/dyn590CsvLoad.c:543
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn590FtpRetQSend(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: open DynReTrnMngInfFNO at dyn590CsvLoad.c:536; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn590FtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1074 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1074
legacy: DynReTrnMngInfFNO (OK_CONST) = 1074 -> BOTH_CORRECT_SAME -- same source value via DynReTrnMngInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn590/dyn590CsvLoad.c:563
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn590FtpRetQSend(); expr `&fcb`
Expected: [1075]  (PATH_VALID)
  - proof: open DynReMyPageStaFNO at dyn590CsvLoad.c:555; DynReMyPageStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn590FtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1075 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1075
legacy: DynReMyPageStaFNO (OK_CONST) = 1075 -> BOTH_CORRECT_SAME -- same source value via DynReMyPageStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn590/dyn590CsvLoad.c:567
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn590FtpRetQSend(); expr `&fcb`
Expected: [1075]  (PATH_VALID)
  - proof: open DynReMyPageStaFNO at dyn590CsvLoad.c:555; DynReMyPageStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn590FtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1075 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1075
legacy: DynReMyPageStaFNO (OK_CONST) = 1075 -> BOTH_CORRECT_SAME -- same source value via DynReMyPageStaFNO
Confidence: high
Cause tags: none


#### src/dyn591/

### /home/chukyu/t-dyn/src/dyn591/dyn591CsvLoad.c:432
Target: pmf_forkproc_H(...), arg 1; enclosing fn dyn591FtpRetQSend(); expr `cProcName`
Expected: [<process name from CSV input>]  (PATH_VALID (data-dependent))
  - proof: cProcName filled by strncpy from CSV column (case 17) at dyn591CsvLoad.c:419-420; content is external data read from the input CSV file, no fixed compile-time value (dyn591FtpRetQSend() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> UNDECIDED -- value is runtime CSV data; not a concrete resolvable constant
legacy: no value (UNRESOLVED) -> UNDECIDED -- same; neither pipeline can name a concrete value and neither can be refuted
Confidence: low
Cause tags: INSUFFICIENT_EVIDENCE


#### src/dyn700/

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:231
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcbSchColor`
Expected: [1487]  (PATH_VALID)
  - proof: SFcbSchColor opened READLOCK on DynReSchColorFNO at line 228; DynReSchColorFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:237
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn700GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:242
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcbGrpSet`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 237 (DynReGrpSetFNO) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:251
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcbTaiko`
Expected: [3909]  (PATH_VALID)
  - proof: openm at line 249 (DynReTaikoSetFNO) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:257
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcbGrpIdx`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 256 (DynReGrpIdxFNO) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:262
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcb`
Expected: [3986]  (PATH_VALID)
  - proof: open at line 261 (DynReCtlMntStaFNO) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:267
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcb`
Expected: [3987]  (PATH_VALID)
  - proof: open at line 266 (DynReCtlMntSetFNO) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:273
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcb`
Expected: [3989]  (PATH_VALID)
  - proof: open at line 272 (DynReKoteMntStaFNO) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:279
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcb`
Expected: [3990]  (PATH_VALID)
  - proof: open at line 276 (DynReKoteMntSetFNO) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:286
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn700GetData(); expr `&SFcb`
Expected: [4013]  (PATH_VALID)
  - proof: open at line 285 (DynReKoTeiHtSetFNO) (dyn700GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:547
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn700CalcCtlValue(); expr `DynREGetSchfno(nFnoidx)`
Expected: [3921-3936 (DynReSchSetFNO..DynReSchSet16FNO via DynREGetSchfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:41-56,243-248)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (dyn700CalcCtlValue() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:549
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700CalcCtlValue(); expr `&SFcbSchSet`
Expected: [3921-3936 (DynReSchSetFNO..DynReSchSet16FNO via DynREGetSchfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:41-56,243-248)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 547 (dyn700CalcCtlValue() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:556
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn700CalcCtlValue(); expr `DynREGetSchKKfno(nFnoidxKK)`
Expected: [3995-4002 (DynReSchSetKK01..08FNO via DynREGetSchKKfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (dyn700CalcCtlValue() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:557
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700CalcCtlValue(); expr `&SFcbSchSet`
Expected: [3995-4002 (DynReSchSetKK01..08FNO via DynREGetSchKKfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 556 (dyn700CalcCtlValue() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:559
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn700CalcCtlValue(); expr `DynREGetSchKKLCfno(nFnoidxKK)`
Expected: [4003-4010 (DynReScStKKLC01..08FNO via DynREGetSchKKLCfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (dyn700CalcCtlValue() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn700/dyn700Init.c:560
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700CalcCtlValue(); expr `&SFcbSchSet`
Expected: [4003-4010 (DynReScStKKLC01..08FNO via DynREGetSchKKLCfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 559 (dyn700CalcCtlValue() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn700/dyn700ScheduleCsvDlg.c:283
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700ShowCsvReadResult(); expr `&fcb`
Expected: [1034]  (PATH_VALID)
  - proof: open at line 282 (DynReSchCsvRedFNO); DynReSchCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn700ShowCsvReadResult() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn700/dyn700UpdFile.c:76
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn700UpdateAll(); expr `&fcb1`
Expected: [1041]  (PATH_VALID)
  - proof: openm at line 70 (DynReRlSvSetFNO); DynReRlSvSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn700UpdateAll() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn720/

### /home/chukyu/t-dyn/src/dyn720/dyn720GrpMkjCsvDlg.c:372
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn720ShowCsvReadResult(); expr `&fcb`
Expected: [3902]  (PATH_VALID)
  - proof: open at line 371 (DynReGmjCsvRedFNO); DynReGmjCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720ShowCsvReadResult() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:223
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn720GetData(); expr `DynReSndStaDFSFNO`
Expected: [3949]  (PATH_VALID)
  - proof: open site itself; DynReSndStaDFSFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:226
Target: mpf_mfs_readrec(...), arg 1; enclosing fn dyn720GetData(); expr `&SfcbHesSnd`
Expected: [3949]  (PATH_VALID)
  - proof: open at line 223 (DynReSndStaDFSFNO) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:246
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn720GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:251
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn720GetData(); expr `&SfcbGrpSet`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 246 (DynReGrpSetFNO) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:273
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn720GetData(); expr `DynReCtlStaFNO`
Expected: [3919]  (PATH_VALID)
  - proof: open site itself; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:276
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn720GetData(); expr `&SfcbCtl`
Expected: [3919]  (PATH_VALID)
  - proof: open at line 273 (DynReCtlStaFNO) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:298
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn720GetData(); expr `DynRePfmCtlFNO`
Expected: [3941]  (PATH_VALID)
  - proof: open site itself; DynRePfmCtlFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:302
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn720GetData(); expr `&SfcbRePfmCtl`
Expected: [3941]  (PATH_VALID)
  - proof: open at line 298 (DynRePfmCtlFNO) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:326
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn720GetData(); expr `DynReOutKanStaFNO`
Expected: [3944]  (PATH_VALID)
  - proof: open site itself; DynReOutKanStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:330
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn720GetData(); expr `&SfcbReOutKanSta`
Expected: [3944]  (PATH_VALID)
  - proof: open at line 326 (DynReOutKanStaFNO) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:355
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn720GetData(); expr `&SfcbReGrpSet3`
Expected: [3978]  (PATH_VALID)
  - proof: open at line 351 (DynReGrpSet3FNO); DynReGrpSet3FNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:374
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn720GetData(); expr `DynReHESPfmStaFNO`
Expected: [3950]  (PATH_VALID)
  - proof: open site itself; DynReHESPfmStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:380
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn720GetData(); expr `&fcb`
Expected: [3950]  (PATH_VALID)
  - proof: open at line 374 (DynReHESPfmStaFNO) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:391
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn720GetData(); expr `DynReHESPfmSetFNO`
Expected: [3951]  (PATH_VALID)
  - proof: open site itself; DynReHESPfmSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:397
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn720GetData(); expr `&fcb`
Expected: [3951]  (PATH_VALID)
  - proof: open at line 391 (DynReHESPfmSetFNO) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:431
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn720GetData(); expr `DynREGetPfmfno(nFnoidx)`
Expected: [3952-3967 (DynReHESPfmKbtFNO..16FNO via DynREGetPfmfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:41-56,260-265)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:434
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn720GetData(); expr `&SFcbReHESPfmKbt`
Expected: [3952-3967 (DynReHESPfmKbtFNO..16FNO via DynREGetPfmfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:41-56,260-265)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 431 (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:455
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn720GetData(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 452 (DynReGrpIdxFNO) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:471
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn720GetData(); expr `&fcb`
Expected: [4011]  (PATH_VALID)
  - proof: openm at line 470 (DynReGrpSetCmnFNO); DynReGrpSetCmnFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn720/dyn720Init.c:485
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn720GetData(); expr `&fcb`
Expected: [1039]  (PATH_VALID)
  - proof: openm at line 484 (DynReSireiTSetFNO); DynReSireiTSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn720GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn731/

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:212
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn731GetData(); expr `DynReCtlStaFNO`
Expected: [3919]  (PATH_VALID)
  - proof: open site itself; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:218
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3919]  (PATH_VALID)
  - proof: open at line 212 (DynReCtlStaFNO) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:233
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn731GetData(); expr `DynAdvCtlStaIndFNO`
Expected: [3946]  (PATH_VALID)
  - proof: open site itself; DynAdvCtlStaIndFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:239
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3946]  (PATH_VALID)
  - proof: open at line 233 (DynAdvCtlStaIndFNO) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:254
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn731GetData(); expr `DynRePfmCtlFNO`
Expected: [3941]  (PATH_VALID)
  - proof: open site itself; DynRePfmCtlFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:260
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3941]  (PATH_VALID)
  - proof: open at line 254 (DynRePfmCtlFNO) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:281
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3974]  (PATH_VALID)
  - proof: open at line 275 (DynReEmeKanIndFNO); DynReEmeKanIndFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:302
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3975]  (PATH_VALID)
  - proof: open at line 296 (DynReEmeStaIndFNO); DynReEmeStaIndFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:315
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn731GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:323
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 315 (DynReGrpSetFNO) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:337
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn731GetData(); expr `DynRePfmStaFNO`
Expected: [3939]  (PATH_VALID)
  - proof: open site itself; DynRePfmStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:343
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3939]  (PATH_VALID)
  - proof: open at line 337 (DynRePfmStaFNO) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:354
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn731GetData(); expr `DynRePfmSetFNO`
Expected: [3940]  (PATH_VALID)
  - proof: open site itself; DynRePfmSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:360
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3940]  (PATH_VALID)
  - proof: open at line 354 (DynRePfmSetFNO) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:380
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [1341]  (PATH_VALID)
  - proof: openm at line 373 (DynReAtEmeSetFNO); DynReAtEmeSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:398
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [1342]  (PATH_VALID)
  - proof: openm at line 391 (DynReAtEmeSvStaFNO); DynReAtEmeSvStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:414
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3909]  (PATH_VALID)
  - proof: openm at line 409 (DynReTaikoSetFNO); DynReTaikoSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn731/dyn731Init.c:432
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn731GetData(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 426 (DynReGrpIdxFNO) (dyn731GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn732/

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:167
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn732GetData(); expr `DynReCtlStaFNO`
Expected: [3919]  (PATH_VALID)
  - proof: open site itself; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:173
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3919]  (PATH_VALID)
  - proof: open at line 167 (DynReCtlStaFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:188
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn732GetData(); expr `DynAdvCtlStaIndFNO`
Expected: [3946]  (PATH_VALID)
  - proof: open site itself; DynAdvCtlStaIndFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:194
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3946]  (PATH_VALID)
  - proof: open at line 188 (DynAdvCtlStaIndFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:209
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn732GetData(); expr `DynRePfmCtlFNO`
Expected: [3941]  (PATH_VALID)
  - proof: open site itself; DynRePfmCtlFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:215
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3941]  (PATH_VALID)
  - proof: open at line 209 (DynRePfmCtlFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:236
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3974]  (PATH_VALID)
  - proof: open at line 230 (DynReEmeKanIndFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:257
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3975]  (PATH_VALID)
  - proof: open at line 251 (DynReEmeStaIndFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:270
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn732GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:278
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 270 (DynReGrpSetFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:292
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn732GetData(); expr `DynRePfmStaFNO`
Expected: [3939]  (PATH_VALID)
  - proof: open site itself; DynRePfmStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:298
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3939]  (PATH_VALID)
  - proof: open at line 292 (DynRePfmStaFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:309
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn732GetData(); expr `DynRePfmSetFNO`
Expected: [3940]  (PATH_VALID)
  - proof: open site itself; DynRePfmSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:315
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3940]  (PATH_VALID)
  - proof: open at line 309 (DynRePfmSetFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:336
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3976]  (PATH_VALID)
  - proof: open at line 330 (DynReAtEmeKanFNO); DynReAtEmeKanFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:356
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [1341]  (PATH_VALID)
  - proof: openm at line 349 (DynReAtEmeSetFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:374
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [1342]  (PATH_VALID)
  - proof: openm at line 367 (DynReAtEmeSvStaFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn732/dyn732Init.c:391
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn732GetData(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 385 (DynReGrpIdxFNO) (dyn732GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn740/

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:169
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn740GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:174
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn740GetData(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 169 (DynReGrpSetFNO) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:194
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn740GetData(); expr `DynRePfmStaFNO`
Expected: [3939]  (PATH_VALID)
  - proof: open site itself; DynRePfmStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:200
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn740GetData(); expr `&fcb`
Expected: [3939]  (PATH_VALID)
  - proof: open at line 194 (DynRePfmStaFNO) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:211
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn740GetData(); expr `DynRePfmSetFNO`
Expected: [3940]  (PATH_VALID)
  - proof: open site itself; DynRePfmSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:217
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn740GetData(); expr `&fcb`
Expected: [3940]  (PATH_VALID)
  - proof: open at line 211 (DynRePfmSetFNO) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:240
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn740GetData(); expr `&fcb`
Expected: [3977]  (PATH_VALID)
  - proof: open at line 234 (DynRePGCtlSetFNO); DynRePGCtlSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:257
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn740GetData(); expr `&fcb`
Expected: [3909]  (PATH_VALID)
  - proof: openm at line 252 (DynReTaikoSetFNO) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn740/dyn740Init.c:271
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn740GetData(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 270 (DynReGrpIdxFNO) (dyn740GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn750/

### /home/chukyu/t-dyn/src/dyn750/dyn750Init.c:158
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn750GetData(); expr `DynReHESSndHisFNO`
Expected: [3968]  (PATH_VALID)
  - proof: open site itself; DynReHESSndHisFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn750GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn750/dyn750Init.c:161
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn750GetData(); expr `&fcb`
Expected: [3968]  (PATH_VALID)
  - proof: open at line 158 (DynReHESSndHisFNO) (dyn750GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn750/dyn750Init.c:193
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn750GetData(); expr `&fcb`
Expected: [1039]  (PATH_VALID)
  - proof: openm at line 182 (DynReSireiTSetFNO) (dyn750GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn750/dyn750Init.c:210
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn750GetData(); expr `DynReSireiInfFNO`
Expected: [3947]  (PATH_VALID)
  - proof: open site itself; DynReSireiInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn750GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn750/dyn750Init.c:218
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn750GetData(); expr `&fcb`
Expected: [3947]  (PATH_VALID)
  - proof: open at line 210 (DynReSireiInfFNO) (dyn750GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn750/dyn750Init.c:231
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn750GetData(); expr `&fcb`
Expected: [4011]  (PATH_VALID)
  - proof: openm at line 230 (DynReGrpSetCmnFNO) (dyn750GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn760/

### /home/chukyu/t-dyn/src/dyn760/dyn760Init.c:197
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn760GetData(); expr `&fcb`
Expected: [1071]  (PATH_VALID)
  - proof: openm at line 190 (DynReCtlNtcInfFNO); DynReCtlNtcInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn760GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn760/dyn760Init.c:208
Target: mpf_mfs_openm_H(...), arg 2; enclosing fn dyn760GetData(); expr `DynReTrnDataInfFNO`
Expected: [1073]  (PATH_VALID)
  - proof: open site itself; DynReTrnDataInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn760GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn760/dyn760Init.c:215
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn760GetData(); expr `&fcb`
Expected: [1073]  (PATH_VALID)
  - proof: openm at line 208 (DynReTrnDataInfFNO) (dyn760GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn760/dyn760Init.c:226
Target: mpf_mfs_openm_H(...), arg 2; enclosing fn dyn760GetData(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open site itself; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn760GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn760/dyn760Init.c:233
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn760GetData(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: openm at line 226 (DynReTrnMngInfFNO) (dyn760GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn760/dyn760Init.c:251
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn760GetData(); expr `&fcb`
Expected: [1041]  (PATH_VALID)
  - proof: openm at line 244 (DynReRlSvSetFNO) (dyn760GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn760/dyn760Init.c:269
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn760GetData(); expr `&fcb`
Expected: [1048]  (PATH_VALID)
  - proof: openm at line 262 (DynReHESHealthFNO) (dyn760GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn760/dyn760Init.c:287
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn760GetData(); expr `&fcb`
Expected: [1075]  (PATH_VALID)
  - proof: openm at line 280 (DynReMyPageStaFNO) (dyn760GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn761/

### /home/chukyu/t-dyn/src/dyn761/dyn761Init.c:87
Target: mpf_mfs_openm_H(...), arg 2; enclosing fn dyn761GetData(); expr `DynReTrnDataInfFNO`
Expected: [1073]  (PATH_VALID)
  - proof: open site itself; DynReTrnDataInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn761GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn761/dyn761Init.c:94
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn761GetData(); expr `&fcb`
Expected: [1073]  (PATH_VALID)
  - proof: openm at line 87 (DynReTrnDataInfFNO) (dyn761GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn761/dyn761Init.c:105
Target: mpf_mfs_openm_H(...), arg 2; enclosing fn dyn761GetData(); expr `DynReTrnMngInfFNO`
Expected: [1074]  (PATH_VALID)
  - proof: open site itself; DynReTrnMngInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn761GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn761/dyn761Init.c:112
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn761GetData(); expr `&fcb`
Expected: [1074]  (PATH_VALID)
  - proof: openm at line 105 (DynReTrnMngInfFNO) (dyn761GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn770/

### /home/chukyu/t-dyn/src/dyn770/dyn770GrpSetCsvDlg.c:475
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn770ShowCsvReadResultGrpSet(); expr `&fcb`
Expected: [3901]  (PATH_VALID)
  - proof: open at line 474 (DynReGstCsvRedFNO); DynReGstCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn770ShowCsvReadResultGrpSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770HtMntCsvDlg.c:377
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn770ShowCsvReadResult(); expr `&fcb`
Expected: [3903]  (PATH_VALID)
  - proof: open at line 376 (DynReHatuCsvRedFNO); DynReHatuCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn770ShowCsvReadResult() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:168
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn770GetData(); expr `&fcb`
Expected: [3909]  (PATH_VALID)
  - proof: openm at line 163 (DynReTaikoSetFNO) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:181
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn770GetData(); expr `DynReITCInfFNO`
Expected: [3938]  (PATH_VALID)
  - proof: open site itself; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:186
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn770GetData(); expr `&fcb`
Expected: [3938]  (PATH_VALID)
  - proof: open at line 181 (DynReITCInfFNO) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:203
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn770GetData(); expr `&fcb`
Expected: [2515]  (PATH_VALID)
  - proof: openm at line 198 on DYN770_DxiItcSSDefExFNo; #define (2515) at /home/chukyu/t-dyn/src/dyn770/dyn770.h:145 (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:216
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn770GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:221
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn770GetData(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 216 (DynReGrpSetFNO) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:236
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn770GetData(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 235 (DynReGrpIdxFNO) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:250
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn770GetData(); expr `&fcb`
Expected: [3986]  (PATH_VALID)
  - proof: open at line 245 (DynReCtlMntStaFNO) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:261
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn770GetData(); expr `&fcb`
Expected: [3987]  (PATH_VALID)
  - proof: open at line 256 (DynReCtlMntSetFNO) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:276
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn770GetData(); expr `DynReCtlStaFNO`
Expected: [3919]  (PATH_VALID)
  - proof: open site itself; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn770/dyn770Init.c:277
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn770GetData(); expr `&fcb`
Expected: [3919]  (PATH_VALID)
  - proof: open at line 276 (DynReCtlStaFNO) (dyn770GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn772/

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:148
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3993]  (PATH_VALID)
  - proof: open at line 142 (DynReGpIdStaFNO); DynReGpIdStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:169
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3994]  (PATH_VALID)
  - proof: open at line 158 (DynReGpIdInfFNO); DynReGpIdInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:182
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn772GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:191
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 182 (DynReGrpSetFNO) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:207
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn772GetData(); expr `DynREGetSchKKfno(nFnoidxKK)`
Expected: [3995-4002 (DynReSchSetKK01..08FNO via DynREGetSchKKfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:213
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3995-4002 (DynReSchSetKK01..08FNO via DynREGetSchKKfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 207 (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:229
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn772GetData(); expr `DynREGetSchKKLCfno(nFnoidxKK)`
Expected: [4003-4010 (DynReScStKKLC01..08FNO via DynREGetSchKKLCfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:235
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [4003-4010 (DynReScStKKLC01..08FNO via DynREGetSchKKLCfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 229 (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL/UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL/UNREACHABLE) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:252
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3986]  (PATH_VALID)
  - proof: open at line 246 (DynReCtlMntStaFNO) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:267
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3987]  (PATH_VALID)
  - proof: open at line 261 (DynReCtlMntSetFNO) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:283
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3989]  (PATH_VALID)
  - proof: open at line 277 (DynReKoteMntStaFNO) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:298
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3990]  (PATH_VALID)
  - proof: open at line 290 (DynReKoteMntSetFNO) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:314
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [4013]  (PATH_VALID)
  - proof: open at line 308 (DynReKoTeiHtSetFNO) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn772/dyn772Init.c:340
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn772GetData(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 334 (DynReGrpIdxFNO) (dyn772GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn773/

### /home/chukyu/t-dyn/src/dyn773/dyn773GrpSetCsvDlg.c:316
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn773ShowCsvReadResultGrpSet(); expr `&fcb`
Expected: [3992]  (PATH_VALID)
  - proof: open at line 315 (DynReGstCsvRed2FNO); DynReGstCsvRed2FNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn773ShowCsvReadResultGrpSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn773/dyn773HtMntCsvDlg.c:304
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn773ShowCsvReadResult(); expr `&fcb`
Expected: [3991]  (PATH_VALID)
  - proof: open at line 303 (DynReKoteCsvRedFNO); DynReKoteCsvRedFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn773ShowCsvReadResult() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn773/dyn773Init.c:141
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn773GetData(); expr `&fcb`
Expected: [3988]  (PATH_VALID)
  - proof: open at line 134 (DynReKoteMainteFNO); DynReKoteMainteFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn773GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn773/dyn773Init.c:155
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn773GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn773GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn773/dyn773Init.c:160
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn773GetData(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 155 (DynReGrpSetFNO) (dyn773GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn773/dyn773Init.c:175
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn773GetData(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 174 (DynReGrpIdxFNO) (dyn773GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn773/dyn773Init.c:189
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn773GetData(); expr `&fcb`
Expected: [3989]  (PATH_VALID)
  - proof: open at line 184 (DynReKoteMntStaFNO) (dyn773GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn773/dyn773Init.c:200
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn773GetData(); expr `&fcb`
Expected: [3990]  (PATH_VALID)
  - proof: open at line 193 (DynReKoteMntSetFNO) (dyn773GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn773/dyn773Init.c:216
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn773GetData(); expr `&fcb`
Expected: [4013]  (PATH_VALID)
  - proof: open at line 213 (DynReKoTeiHtSetFNO) (dyn773GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn780/

### /home/chukyu/t-dyn/src/dyn780/dyn780AdvOptDlg.c:1683
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn780SetAdvAutoRsv(); expr `&fcbAdvInd`
Expected: [3983]  (PATH_VALID)
  - proof: fcbAdvInd opened READLOCK on DynAdvCtlStaITkFNO at line 1677 (closed 1684) (dyn780SetAdvAutoRsv() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780AdvOptDlg.c:1716
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn780SetAdvAutoRsv(); expr `&fcbAdvInd`
Expected: [3983]  (PATH_VALID)
  - proof: fcbAdvInd opened WRITELOCK on DynAdvCtlStaITkFNO at line 1706 (closed 1717) (dyn780SetAdvAutoRsv() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:271
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn780GetData(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open site itself; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:278
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open at line 271 (DynReGrpSetFNO) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:311
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [3909]  (PATH_VALID)
  - proof: openm at line 306 (DynReTaikoSetFNO) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:343
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [2022]  (PATH_VALID)
  - proof: open at line 338 on DifStatusNo; #define (2022) at /home/chukyu/t-dif/include/dif/Dif.h:45 (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:361
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [3910]  (PATH_VALID)
  - proof: open at line 355 (DynReSchSetTkFNO); DynReSchSetTkFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:362
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [3910]  (PATH_VALID)
  - proof: same open at line 355 (DynReSchSetTkFNO) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:385
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [3913]  (PATH_VALID)
  - proof: open at line 380 (DynAdvCtlStaCTkFNO); DynAdvCtlStaCTkFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:407
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [3912]  (PATH_VALID)
  - proof: open at line 402 (DynReEmeKanITkFNO); DynReEmeKanITkFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:432
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn780GetData(); expr `DynReITCInfFNO`
Expected: [3938]  (PATH_VALID)
  - proof: open site itself; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:437
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [3938]  (PATH_VALID)
  - proof: open at line 432 (DynReITCInfFNO) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:454
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [2515]  (PATH_VALID)
  - proof: openm at line 449 on DYN780_DxiItcSSDefExFNo; #define (2515) at /home/chukyu/t-dyn/src/dyn780/dyn780.h:119 (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:473
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetData(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open at line 468 (DynReGrpIdxFNO) (dyn780GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:508
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn780GetDataDynRePfmCtl(); expr `DynRePfmCtlFNO`
Expected: [3941]  (PATH_VALID)
  - proof: open site itself; DynRePfmCtlFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetDataDynRePfmCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:513
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetDataDynRePfmCtl(); expr `&fcb`
Expected: [3941]  (PATH_VALID)
  - proof: open at line 508 (DynRePfmCtlFNO) (dyn780GetDataDynRePfmCtl() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:548
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn780GetDataDynReCtlSta(); expr `DynReCtlStaFNO`
Expected: [3919]  (PATH_VALID)
  - proof: open site itself; DynReCtlStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetDataDynReCtlSta() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:553
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetDataDynReCtlSta(); expr `&fcb`
Expected: [3919]  (PATH_VALID)
  - proof: open at line 548 (DynReCtlStaFNO) (dyn780GetDataDynReCtlSta() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:593
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetDataDynAdvCtlStaITk(); expr `&fcb`
Expected: [3983]  (PATH_VALID)
  - proof: open at line 588 (DynAdvCtlStaITkFNO); DynAdvCtlStaITkFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetDataDynAdvCtlStaITk() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:633
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetDataDynReEmeStaInd(); expr `&fcb`
Expected: [3975]  (PATH_VALID)
  - proof: open at line 628 (DynReEmeStaIndFNO) (dyn780GetDataDynReEmeStaInd() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn780/dyn780Init.c:673
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn780GetDataDynAdvCtlLog(); expr `&fcb`
Expected: [3984]  (PATH_VALID)
  - proof: open at line 668 (DynAdvCtlLogFNO); DynAdvCtlLogFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn780GetDataDynAdvCtlLog() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn790/

### /home/chukyu/t-dyn/src/dyn790/dyn790Init.c:127
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn790GetData(); expr `DynReITCInfFNO`
Expected: [3938]  (PATH_VALID)
  - proof: open site itself; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn790GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn790/dyn790Init.c:132
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn790GetData(); expr `&fcb`
Expected: [3938]  (PATH_VALID)
  - proof: open at line 127 (DynReITCInfFNO) (dyn790GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn790/dyn790Init.c:149
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn790GetData(); expr `&fcb`
Expected: [2515]  (PATH_VALID)
  - proof: openm at line 144 on DYN790_DxiItcSSDefExFNo; #define (2515) at /home/chukyu/t-dyn/src/dyn790/dyn790.h:82 (dyn790GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn790/dyn790Init.c:164
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn790GetData(); expr `&fcb`
Expected: [3986]  (PATH_VALID)
  - proof: open at line 159 (DynReCtlMntStaFNO) (dyn790GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn790/dyn790Init.c:175
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn790GetData(); expr `&fcb`
Expected: [3987]  (PATH_VALID)
  - proof: open at line 170 (DynReCtlMntSetFNO) (dyn790GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn790/dyn790Init.c:190
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn790GetData(); expr `DynRePfmCtlFNO`
Expected: [3941]  (PATH_VALID)
  - proof: open site itself; DynRePfmCtlFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn790GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn790/dyn790Init.c:195
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn790GetData(); expr `&fcb`
Expected: [3941]  (PATH_VALID)
  - proof: open at line 190 (DynRePfmCtlFNO) (dyn790GetData() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNREACHABLE) -> CVIZ_UNDERAPPROXIMATION -- c-viz found no root path (UNREACHABLE) but the call is active code and its value is source-derivable
legacy: no value (empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no value
Confidence: high
Cause tags: UNREACHABLE_ROOT_MODEL


#### src/dyn820d/

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:162
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn820dHTTPRequest.c:152; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:177
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [4011]  (PATH_VALID)
  - proof: open DynReGrpSetCmnFNO at dyn820dHTTPRequest.c:167; DynReGrpSetCmnFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 4011 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 4011
legacy: DynReGrpSetCmnFNO (OK_CONST) = 4011 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetCmnFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:190
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn820dHTTPRequest(); expr `DynREGetSchKKfno(nFnoidxKK)`
Expected: [3995-4002 (DynReSchSetKK01..08FNO via DynREGetSchKKfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:195
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [3995-4002 (DynReSchSetKK01..08FNO via DynREGetSchKKfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 190 (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:197
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn820dHTTPRequest(); expr `DynREGetSchKKLCfno(nFnoidxKK)`
Expected: [4003-4010 (DynReScStKKLC01..08FNO via DynREGetSchKKLCfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:202
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [4003-4010 (DynReScStKKLC01..08FNO via DynREGetSchKKLCfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:36-45)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 197 (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:213
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [3986]  (PATH_VALID)
  - proof: open DynReCtlMntStaFNO at dyn820dHTTPRequest.c:208; DynReCtlMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3986 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3986
legacy: DynReCtlMntStaFNO (OK_CONST) = 3986 -> BOTH_CORRECT_SAME -- same source value via DynReCtlMntStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:220
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [3987]  (PATH_VALID)
  - proof: open DynReCtlMntSetFNO at dyn820dHTTPRequest.c:215; DynReCtlMntSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3987 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3987
legacy: DynReCtlMntSetFNO (OK_CONST) = 3987 -> BOTH_CORRECT_SAME -- same source value via DynReCtlMntSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:228
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [3989]  (PATH_VALID)
  - proof: open DynReKoteMntStaFNO at dyn820dHTTPRequest.c:223; DynReKoteMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3989 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3989
legacy: DynReKoteMntStaFNO (OK_CONST) = 3989 -> BOTH_CORRECT_SAME -- same source value via DynReKoteMntStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:240
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [3990]  (PATH_VALID)
  - proof: open DynReKoteMntSetFNO at dyn820dHTTPRequest.c:231; DynReKoteMntSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3990 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3990
legacy: DynReKoteMntSetFNO (OK_CONST) = 3990 -> BOTH_CORRECT_SAME -- same source value via DynReKoteMntSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:250
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [4013]  (PATH_VALID)
  - proof: open DynReKoTeiHtSetFNO at dyn820dHTTPRequest.c:245; DynReKoTeiHtSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 4013 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 4013
legacy: DynReKoTeiHtSetFNO (OK_CONST) = 4013 -> BOTH_CORRECT_SAME -- same source value via DynReKoTeiHtSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:278
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn820dHTTPRequest(); expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn820dHTTPRequest.c:278; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:299
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn820dHTTPRequest.c:278; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn820d/dyn820dHTTPRequest.c:328
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn820dHTTPRequest(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyn820dHTTPRequest.c:278; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn820dHTTPRequest() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3917
legacy: DynReGrpSetFNO (OK_CONST) = 3917 -> BOTH_CORRECT_SAME -- same source value via DynReGrpSetFNO
Confidence: high
Cause tags: none


#### src/dyn831/

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:83
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn831UpdatePfm(); expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyn831UpdatePfm.c:74; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn831UpdatePfm() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3916
legacy: DynReGrpIdxFNO (OK_CONST) = 3916 -> BOTH_CORRECT_SAME -- same source value via DynReGrpIdxFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:119
Target: mpf_mfs_open_H(...), arg 2; enclosing fn UpdatePfmSta(); expr `DynReHESPfmStaFNO`
Expected: [3950]  (PATH_VALID)
  - proof: open DynReHESPfmStaFNO at dyn831UpdatePfm.c:119; DynReHESPfmStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (UpdatePfmSta() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3950 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3950
legacy: DynReHESPfmStaFNO (OK_CONST) = 3950 -> BOTH_CORRECT_SAME -- same source value via DynReHESPfmStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:131
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn UpdatePfmSta(); expr `&fcb_sta`
Expected: [3950]  (PATH_VALID)
  - proof: open DynReHESPfmStaFNO at dyn831UpdatePfm.c:119; DynReHESPfmStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (UpdatePfmSta() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3950 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3950
legacy: DynReHESPfmStaFNO (OK_CONST) = 3950 -> BOTH_CORRECT_SAME -- same source value via DynReHESPfmStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:140
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn UpdatePfmSta(); expr `&fcb_sta`
Expected: [3950]  (PATH_VALID)
  - proof: open DynReHESPfmStaFNO at dyn831UpdatePfm.c:119; DynReHESPfmStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (UpdatePfmSta() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3950 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3950
legacy: DynReHESPfmStaFNO (OK_CONST) = 3950 -> BOTH_CORRECT_SAME -- same source value via DynReHESPfmStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:149
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn UpdatePfmSta(); expr `&fcb_sta`
Expected: [3950]  (PATH_VALID)
  - proof: open DynReHESPfmStaFNO at dyn831UpdatePfm.c:119; DynReHESPfmStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (UpdatePfmSta() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3950 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3950
legacy: DynReHESPfmStaFNO (OK_CONST) = 3950 -> BOTH_CORRECT_SAME -- same source value via DynReHESPfmStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:214
Target: mpf_mfs_open_H(...), arg 2; enclosing fn UpdatePfmSet(); expr `DynReHESPfmSetFNO`
Expected: [3951]  (PATH_VALID)
  - proof: open DynReHESPfmSetFNO at dyn831UpdatePfm.c:214; DynReHESPfmSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (UpdatePfmSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3951 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3951
legacy: DynReHESPfmSetFNO (OK_CONST) = 3951 -> BOTH_CORRECT_SAME -- same source value via DynReHESPfmSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:223
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn UpdatePfmSet(); expr `&fcb_set`
Expected: [3951]  (PATH_VALID)
  - proof: open DynReHESPfmSetFNO at dyn831UpdatePfm.c:214; DynReHESPfmSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (UpdatePfmSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3951 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3951
legacy: DynReHESPfmSetFNO (OK_CONST) = 3951 -> BOTH_CORRECT_SAME -- same source value via DynReHESPfmSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:296
Target: mpf_mfs_open_H(...), arg 2; enclosing fn UpdatePfmSet(); expr `DynREGetPfmfno(nFnoidx)`
Expected: [3952-3967 (DynReHESPfmKbtFNO..16FNO via DynREGetPfmfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:41-56,260-265)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; wrapper table in libDynRe (UpdatePfmSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:308
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn UpdatePfmSet(); expr `&fcb_kbt`
Expected: [3952-3967 (DynReHESPfmKbtFNO..16FNO via DynREGetPfmfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:41-56,260-265)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 296 (UpdatePfmSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:389
Target: mpf_mfs_open_H(...), arg 2; enclosing fn UpdatePfmSet(); expr `DynReHESPfmSetFNO`
Expected: [3951]  (PATH_VALID)
  - proof: open DynReHESPfmSetFNO at dyn831UpdatePfm.c:389; DynReHESPfmSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (UpdatePfmSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3951 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3951
legacy: DynReHESPfmSetFNO (OK_CONST) = 3951 -> BOTH_CORRECT_SAME -- same source value via DynReHESPfmSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:397
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn UpdatePfmSet(); expr `&fcb_set`
Expected: [3951]  (PATH_VALID)
  - proof: open DynReHESPfmSetFNO at dyn831UpdatePfm.c:389; DynReHESPfmSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (UpdatePfmSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3951 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3951
legacy: DynReHESPfmSetFNO (OK_CONST) = 3951 -> BOTH_CORRECT_SAME -- same source value via DynReHESPfmSetFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:429
Target: mpf_mfs_open_H(...), arg 2; enclosing fn UpdatePfmSet(); expr `DynREGetPfmfno((nFnoidx + nCnt) % DYN_REENESCHE_IDXNUM)`
Expected: [3952-3967 (DynReHESPfmKbtFNO..16FNO via DynREGetPfmfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:41-56,260-265)]  (PATH_VALID (runtime date/index dependent))
  - proof: open site itself; (nFnoidx+nCnt)%16 ranges over all 16 table entries; wrapper table in libDynRe (UpdatePfmSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn831/dyn831UpdatePfm.c:436
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn UpdatePfmSet(); expr `&fcb_kbt`
Expected: [3952-3967 (DynReHESPfmKbtFNO..16FNO via DynREGetPfmfno, /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:41-56,260-265)]  (PATH_VALID (runtime date/index dependent))
  - proof: handle opened at line 429 (UpdatePfmSet() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (EXTERNAL) -> CVIZ_UNDERAPPROXIMATION -- c-viz status no value (EXTERNAL) but value set is source-derivable via table lookup
legacy: no value (UNRESOLVED) -> LEGACY_UNDERAPPROXIMATION -- legacy left wrapper/symbolic unresolved
Confidence: medium
Cause tags: MISSING_WRAPPER_MAPPING


#### src/dyn832/

### /home/chukyu/t-dyn/src/dyn832/dyn832Main.c:202
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn pmf_main_H(); expr `&sFcb`
Expected: [1048]  (PATH_VALID)
  - proof: open DynReHESHealthFNO at dyn832Main.c:181; DynReHESHealthFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1048 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1048
legacy: DynReHESHealthFNO (OK_CONST) = 1048 -> BOTH_CORRECT_SAME -- same source value via DynReHESHealthFNO
Confidence: high
Cause tags: none


#### src/dyn833/

### /home/chukyu/t-dyn/src/dyn833/dyn833Main.c:172
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1075]  (PATH_VALID)
  - proof: open DynReMyPageStaFNO at dyn833Main.c:164; DynReMyPageStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1075 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1075
legacy: DynReMyPageStaFNO (OK_CONST) = 1075 -> BOTH_CORRECT_SAME -- same source value via DynReMyPageStaFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn833/dyn833Main.c:179
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr `&fcb`
Expected: [1075]  (PATH_VALID)
  - proof: open DynReMyPageStaFNO at dyn833Main.c:164; DynReMyPageStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (pmf_main_H() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1075 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1075
legacy: DynReMyPageStaFNO (OK_CONST) = 1075 -> BOTH_CORRECT_SAME -- same source value via DynReMyPageStaFNO
Confidence: high
Cause tags: none


#### src/dyn910/

### /home/chukyu/t-dyn/src/dyn910/dyn910PktInfFileMake.c:256
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn910PktInfFileMake(); expr `DynReITCInfFNO`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn910PktInfFileMake.c:256; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn910PktInfFileMake() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn910/dyn910PktInfFileMake.c:261
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn910PktInfFileMake(); expr `&Fcb`
Expected: [3938]  (PATH_VALID)
  - proof: open DynReITCInfFNO at dyn910PktInfFileMake.c:256; DynReITCInfFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn910PktInfFileMake() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3938 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 3938
legacy: DynReITCInfFNO (OK_CONST) = 3938 -> BOTH_CORRECT_SAME -- same source value via DynReITCInfFNO
Confidence: high
Cause tags: none

### /home/chukyu/t-dyn/src/dyn910/dyn910SSAdrsDefFileMake.c:134
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn910SSAdrsDefFileMake(); expr `&Fcb`
Expected: [1028]  (PATH_VALID)
  - proof: open DynReSsAdrDefFNO at dyn910SSAdrsDefFileMake.c:126; DynReSsAdrDefFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dyn910SSAdrsDefFileMake() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1028 (EXACT) -> BOTH_CORRECT_SAME -- equals source value 1028
legacy: DynReSsAdrDefFNO (OK_CONST) = 1028 -> BOTH_CORRECT_SAME -- same source value via DynReSsAdrDefFNO
Confidence: high
Cause tags: none


#### tool/2612/

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/CnvDynReCtlNtcDat2/CnvDynReCtlNtcDat2.c:72
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReCtlNtcDat2.c:67; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 67
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/CnvDynReCtlNtcDtPv/CnvDynReCtlNtcDtPv.c:72
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReCtlNtcDtPv.c:67; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 67
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/CnvDynReGrpSet2/CnvDynReGrpSet2.c:72
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReGrpSet2.c:67; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 67
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/CnvDynReGrpSet3/CnvDynReGrpSet3.c:70
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReGrpSet3.c:65; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 65
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/CnvDynReHESPfmKbt2/CnvDynReHESPfmKbt2.c:81
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReHESPfmKbt2.c:76; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 76
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/CnvDynReHESPfmSet2/CnvDynReHESPfmSet2.c:70
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReHESPfmSet2.c:65; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 65
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/CnvDynReSchSet2/CnvDynReSchSet2.c:82
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReSchSet2.c:77; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 77
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/CnvDynReSetDspTgt/CnvDynReSetDspTgt.c:70
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReSetDspTgt.c:65; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 65
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/IniDynReCtlMntSet/IniDynReCtlMntSet.c:47
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3987]  (PATH_VALID)
  - proof: open DynReCtlMntSetFNO at IniDynReCtlMntSet.c:42; DynReCtlMntSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3987 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReCtlMntSetFNO at line 42
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/IniDynReCtlMntSta/IniDynReCtlMntSta.c:53
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3986]  (PATH_VALID)
  - proof: open DynReCtlMntStaFNO at IniDynReCtlMntSta.c:42; DynReCtlMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3986 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReCtlMntStaFNO at line 42
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/IniDynReGrpSetCmn/IniDynReGrpSetCmn.c:38
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [4011]  (PATH_VALID)
  - proof: open DynReGrpSetCmnFNO at IniDynReGrpSetCmn.c:29; DynReGrpSetCmnFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 4011 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetCmnFNO at line 29
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvdt/cnvtool/IniDynReKoteMntSta/IniDynReKoteMntSta.c:53
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3989]  (PATH_VALID)
  - proof: open DynReKoteMntStaFNO at IniDynReKoteMntSta.c:42; DynReKoteMntStaFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3989 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReKoteMntStaFNO at line 42
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvrev/cnvrevtool/CnvDynReCtlNtcDPvB/CnvDynReCtlNtcDPvB.c:64
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReCtlNtcDPvB.c:59; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 59
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvrev/cnvrevtool/CnvDynReCtlNtcDatB/CnvDynReCtlNtcDatB.c:64
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReCtlNtcDatB.c:59; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 59
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvrev/cnvrevtool/CnvDynReGrpSet3B/CnvDynReGrpSet3B.c:62
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReGrpSet3B.c:57; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 57
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvrev/cnvrevtool/CnvDynReGrpSetB/CnvDynReGrpSetB.c:62
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReGrpSetB.c:57; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 57
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvrev/cnvrevtool/CnvDynReHESPfKbB01/CnvDynReHESPfKbB01.c:73
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReHESPfKbB01.c:68; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 68
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvrev/cnvrevtool/CnvDynReHESPfmSetB/CnvDynReHESPfmSetB.c:62
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReHESPfmSetB.c:57; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 57
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvrev/cnvrevtool/CnvDynReSchSetB/CnvDynReSchSetB.c:73
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReSchSetB.c:68; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 68
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/2612/cnvrev/cnvrevtool/CnvDynReSetDspTgtB/CnvDynReSetDspTgtB.c:62
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at CnvDynReSetDspTgtB.c:57; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 57
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE


#### tool/CtlMainteDmp/

### /home/chukyu/t-dyn/tool/CtlMainteDmp/CtlMainteDmp.c:74
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3973]  (PATH_VALID)
  - proof: open DynReCtlMainteFNO at CtlMainteDmp.c:69; DynReCtlMainteFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3973 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReCtlMainteFNO at line 69
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE


#### tool/DynReEmeKanIndDmp/

### /home/chukyu/t-dyn/tool/DynReEmeKanIndDmp/DynReEmeKanIndDmp.c:71
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dynCmpRec; expr `&fcb`
Expected: [3974]  (PATH_VALID)
  - proof: open DynReEmeKanIndFNO at DynReEmeKanIndDmp.c:65; DynReEmeKanIndFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dynCmpRec is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3974 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReEmeKanIndFNO at line 65
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/DynReEmeKanIndDmp/DynReEmeKanIndDmp.c:82
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dynCmpRec; expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at DynReEmeKanIndDmp.c:82; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dynCmpRec is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 82
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE; open site itself

### /home/chukyu/t-dyn/tool/DynReEmeKanIndDmp/DynReEmeKanIndDmp.c:88
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dynCmpRec; expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at DynReEmeKanIndDmp.c:82; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dynCmpRec is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 82
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/DynReEmeKanIndDmp/DynReEmeKanIndDmp.c:97
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dynCmpRec; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at DynReEmeKanIndDmp.c:92; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (dynCmpRec is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 92
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE


#### tool/SetGrpIdx/

### /home/chukyu/t-dyn/tool/SetGrpIdx/SetGrpIdx.c:70
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at SetGrpIdx.c:66; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 66
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/SetGrpIdx/SetGrpIdx.c:73
Target: mpf_mfs_open_H(...), arg 2; enclosing fn main; expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at SetGrpIdx.c:73; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 73
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE; open site itself

### /home/chukyu/t-dyn/tool/SetGrpIdx/SetGrpIdx.c:79
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at SetGrpIdx.c:73; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 73
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/SetGrpIdx/SetGrpIdx.c:222
Target: mpf_mfs_open_H(...), arg 2; enclosing fn main; expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at SetGrpIdx.c:222; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 222
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE; open site itself

### /home/chukyu/t-dyn/tool/SetGrpIdx/SetGrpIdx.c:245
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at SetGrpIdx.c:222; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 222
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/SetGrpIdx/SetGrpIdx.c:273
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at SetGrpIdx.c:266; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 266
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE


#### tool/SetGrpSet/

### /home/chukyu/t-dyn/tool/SetGrpSet/SetGrpSet.c:164
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at SetGrpSet.c:158; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 158
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/SetGrpSet/SetGrpSet.c:175
Target: mpf_mfs_open_H(...), arg 2; enclosing fn main; expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at SetGrpSet.c:175; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 175
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE; open site itself

### /home/chukyu/t-dyn/tool/SetGrpSet/SetGrpSet.c:183
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at SetGrpSet.c:175; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 175
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/SetGrpSet/SetGrpSet.c:232
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn main(); expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: fcb opened WRITELOCK on DynReGrpSetFNO at SetGrpSet.c:175, not closed before line 232 (close at 234 after the write) (main() is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: no value (UNRESOLVED) -> CVIZ_UNDERAPPROXIMATION -- single in-function open->use edge missed
legacy: no value (statuses empty) -> LEGACY_UNDERAPPROXIMATION -- legacy reported nothing although 3917 is provable
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE


#### tool/dyntest/

### /home/chukyu/t-dyn/tool/dyntest/dyntest.c:90
Target: mpf_mfs_open_H(...), arg 2; enclosing fn main; expr `DynReGrpSetFNO`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyntest.c:90; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 90
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE; open site itself

### /home/chukyu/t-dyn/tool/dyntest/dyntest.c:96
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3917]  (PATH_VALID)
  - proof: open DynReGrpSetFNO at dyntest.c:90; DynReGrpSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3917 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpSetFNO at line 90
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/dyntest/dyntest.c:105
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb`
Expected: [3916]  (PATH_VALID)
  - proof: open DynReGrpIdxFNO at dyntest.c:100; DynReGrpIdxFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 3916 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReGrpIdxFNO at line 100
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### /home/chukyu/t-dyn/tool/dyntest/dyntest.c:131
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn main; expr `&fcb1`
Expected: [1041]  (PATH_VALID)
  - proof: open DynReRlSvSetFNO at dyntest.c:126; DynReRlSvSetFNO in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (DynReDirectFileNo enum) (main is called from the module's normal init/request path; call is active, not in a comment or disabled branch)
c-viz: 1041 (EXACT) -> CVIZ_CORRECT_ONLY -- matches open of DynReRlSvSetFNO at line 126
legacy: no value (statuses empty, llm_backwalk=False) -> LEGACY_UNDERAPPROXIMATION -- legacy reported no concrete value although open->use is a single in-function edge
Confidence: high
Cause tags: MISSING_ASSIGNMENT_EDGE

### Notable examples

1. **c-viz correct, legacy stale/wrong (LEGACY_OVERAPPROXIMATION, STALE_HEADER_OR_SOURCE)** — /home/chukyu/t-dyn/src/dyn010/dyn010Main.c:191 (and 195, 200, 202): `mpf_mfs_writerecm(&fcb,...)` where fcb was opened at line 181 on `DynReCtlMainteFNO`. Current header value is 3973; legacy reported 1077, which is the pre-<#31214> `DynReCtlMainteFNO_DUMMY` position in the old 1071-range table. c-viz 3973 is the only reachable value. Same pattern: /home/chukyu/t-dyn/src/dyn500/dyn500TransSchdule.c:160,177 (legacy 3906 = old `DynReCtlNtcDtPvFNO_DUMMY`; now 3981) and /home/chukyu/t-dyn/src/dyn441/dyn441AtComProc.c:168 (legacy 1343 = old `DynReAtEmeKanFNO_DUMMY`; now 3976).
2. **legacy correct, c-viz not (LEGACY_CORRECT_ONLY)** — /home/chukyu/t-dyn/src/dyn235d/dyn235dReEneCtl.c:299,301,303: three `mpf_mfs_writerecn` calls on handles opened earlier in the same function (lines 118/129/141 on DynReCtlStaFNO=3919, DynReKansiStaFNO=3945, DynReCtlStaAlznFNO=4012). Legacy's LLM handle back-walk found the right open for all three; c-viz returned UNRESOLVED for all three.
3. **both correct (BOTH_CORRECT_SAME)** — the dominant case, e.g. /home/chukyu/t-dyn/src/dyn014/dyn014CyclicProc.c:189-222 (`mpf_mfs_open_H(&fcb, DynReOutStaFNO,...)` at 193 with 3937; both pipelines agree) and all of /home/chukyu/t-dyn/src/dyn260/dyn260Main.c where c-viz EXACT numerics match legacy OK_CONST macros exactly.
4. **c-viz correct, legacy absent (CVIZ_CORRECT_ONLY)** — all standalone tool sites, e.g. /home/chukyu/t-dyn/tool/dyntest/dyntest.c:131 `mpf_mfs_readrecm(&fcb1,0,&sRlSvSet)` -> 1041 (DynReRlSvSetFNO, open at line 126): c-viz exact, legacy produced no value at all. Also /home/chukyu/t-dyn/src/dyn432d/dyn432dAdvCtrl.c:108,116,269 where c-viz correctly reports BOTH branch values {3946 (DynAdvCtlStaIndFNO), 3983 (DynAdvCtlStaITkFNO)} of `iFnoInd` and legacy reported nothing.
5. **both under-approximation, ranges source-derivable** — /home/chukyu/t-dyn/src/dyn431/dyn431Main.c:210,219,228,240: `DynREGetPfmfno(nFnoidx)` unwraps (via libDynRe/DynREGetSchePos.c:260) to the 16-entry table DynReHESPfmKbt{,02..16}FNO = 3952..3967; both pipelines left EXTERNAL/UNRESOLVED. Same for dyn700Init.c:547-560 (Schfno 3921-3936 / KK 3995-4002 / KKLC 4003-4010) and dyn831UpdatePfm.c:296,308,429,436.
6. **UNDECIDED (data-dependent)** — /home/chukyu/t-dyn/src/dyn591/dyn591CsvLoad.c:432 `pmf_forkproc_H(cProcName,...)`: cProcName is populated from CSV input text (line 419-420, case 17); no compile-time value exists, both pipelines status-only is the correct behavior; neither can be judged over/under without the actual CSV data.

### Unfinished / open items

- None. All 392 unique sites (410 claim rows) received verdicts.
- Caveats: (a) confidence is medium for the 24 table-lookup sites whose concrete element is selected at runtime by date/day index (the full reachable set is stated, the element is data-dependent); (b) legacy provenance line numbers in valueflow_proof.csv (e.g. "dyn010Main.c:5669") are internal offsets, not source lines — they were not used as evidence; (c) `legacy_llm_backwalk=False` rows mean legacy ran no LLM back-walk for that site, which explains the systematic legacy gaps on the tool/ and dyn432dReEneCtrl sites.

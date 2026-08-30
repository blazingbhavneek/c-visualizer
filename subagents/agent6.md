# Role

You are one of 6 subagents (this one is **6**) in a source-code correctness
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
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/subagents/agent6_claims.csv
- Full per-site comparison (for cross-checking only; do not audit outside your batch):
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1_sites.csv
- c-visualizer raw facts:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index/discovery_facts.csv
- legacy proof:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/valueflow_proof.csv
- C source root: /home/chukyu

Batch statistics (already computed — reconcile them against your CSV on start):
- claim rows in your batch: 396
- unique (file, line) sites: 393

Your batch covers these source directories (relative to /home/chukyu):
- /home/chukyu/t-rep/src/libmsg
- /home/chukyu/t-rep/src/libmsg1
- /home/chukyu/t-rep/src/libmsgreq
- /home/chukyu/t-rep/src/librep
- /home/chukyu/t-rep/src/msg001
- /home/chukyu/t-rep/src/msg200d
- /home/chukyu/t-rep/src/msg230d
- /home/chukyu/t-rep/src/msg240
- /home/chukyu/t-rep/src/msg242
- /home/chukyu/t-rep/src/msg400d
- /home/chukyu/t-rep/src/msg500d
- /home/chukyu/t-rep/src/msg700
- /home/chukyu/t-rep/tool/msgcrecon
- /home/chukyu/t-rep/tool/msgcredef
- /home/chukyu/t-rep/tool/msgcreptn
- /home/chukyu/t-rep/tool/msgtool
- /home/chukyu/t-sim/src/libopcp
- /home/chukyu/t-sim/src/libsim
- /home/chukyu/t-sim/src/libsim_kun
- /home/chukyu/t-sim/src/libsimutil
- /home/chukyu/t-sim/src/sim430d
- /home/chukyu/t-sim/src/sim440d
- /home/chukyu/t-sim/src/sim499
- /home/chukyu/t-sim/src/sim510d
- /home/chukyu/t-sim/src/sim520d
- /home/chukyu/t-sim/src/sim530d
- /home/chukyu/t-sim/src/sim540d
- /home/chukyu/t-sim/src/sim560
- /home/chukyu/t-sim/src/sim570d
- /home/chukyu/t-sim/src/sim730
- /home/chukyu/t-sim/src/sim735
- /home/chukyu/t-sim/src/sim740
- /home/chukyu/t-sim/src/sim770
- /home/chukyu/t-sim/src/sim780
- /home/chukyu/t-sim/src/sim800
- /home/chukyu/t-sim/src/sim801
- /home/chukyu/t-sim/src/sim810
- /home/chukyu/t-sim/src/sim_set_kosho
- /home/chukyu/t-svm/src/libDac
- /home/chukyu/t-svm/src/libSvmManSt
- /home/chukyu/t-svm/src/libsvm
- /home/chukyu/t-svm/src/libsvmG
- /home/chukyu/t-svm/src/libsvmP
- /home/chukyu/t-svm/src/libsvmskl_dlg
- /home/chukyu/t-svm/src/svm000
- /home/chukyu/t-svm/src/svm100d
- /home/chukyu/t-svm/src/svm101d
- /home/chukyu/t-svm/src/svm200d
- /home/chukyu/t-svm/src/svm500d
- /home/chukyu/t-svm/src/svm620
- /home/chukyu/t-svm/tool/IWATE
- /home/chukyu/t-svm/tool/SetFile
- /home/chukyu/t-svm/tool/apitop_test
- /home/chukyu/t-svm/tool/svmclr
- /home/chukyu/t-svm/tool/svmsetq
- /home/chukyu/t-svm/tool/test

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
one of the 396 claim rows (all 393 unique sites) receives a verdict —
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

- Sites audited: 393 unique (file,line) from 396 claim rows (3 duplicated rows covered above as extra row lines).
- Categories: both_unresolved=187, cvisualizer_resolved_only=58, equal=100, legacy_resolved_only=48

#### Pipeline verdicts (site-level, one per site)
- c-visualizer: CORRECT=150, CORRECT_INCOMPLETE=3, PARTIAL_OVERLAP=3, UNDECIDED_SITE=99, UNDERAPPROXIMATION=136, UNPROVABLE_CLAIM=2
- legacy:        CORRECT=140, CORRECT_INCOMPLETE=8, UNDECIDED_SITE=101, UNDERAPPROXIMATION=144

#### Site classes
- both_correct: 100
- cviz_only: 50
- legacy_only: 40
- neither_correct: 102
- undecided: 101


#### Value-level metrics
- c-visualizer reported values: 172; accepted (source-valid): 167 → precision 167/172 = 97.1%
- legacy reported values: 167; accepted (source-valid): 167 → precision 167/167 = 100.0%
- union reported: 339; union accepted: 334 → precision 334/339 = 98.5%
- coverage: accepted distinct values 78 / source-expected distinct values 99 = 78/99 = 78.8%

#### Site-level accuracy (per pipeline, sites where a value is provable)
- cvisualizer: sites with provable source value = 292; exact-match sites = 150 → site-accuracy 150/292 = 51.4%
- legacy: sites with provable source value = 292; exact-match sites = 140 → site-accuracy 140/292 = 47.9%

#### Undecided sites (no active source value provable)
- count: 101 (+2 sites with unprovable reported values counted under UNPROVABLE_CLAIM)
- reasons: (a) file-number macro used but #define absent from the active tree (stale header): KUNUNTVSAIGEN_NO, API_TOP_JOHEN_FILE, SvmJikoStatNo, SvmJikoSfNo, SvmKyoukyuNo, SvmHatudenNo, SvmSyunTeiMngNo, SvmSyunStatNo, SvmSyunTeiNo, SvmLSKTBtnDefNo, SvmRYKTBtnDefNo, SvmCspcDefNo, SvmSyunCyouDefNo, SvmKyoSishoTMNo, SvmHatSishoTMNo, SvmSWKumiDefNo, SvmSWRYDefNo, SvmJikoATMngNo/SvmJimATMngNo/SvmChoATMngNo/SvmSyunATMngNo; (b) parameter passed only by callers outside the tree (library exports) or by commented-out/static-dead callers; (c) input-driven values (argv/atoi, SCN dupname).

#### Overapproximation sites (false values reported)
- count: 3
  - cvisualizer @ /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:469
  - cvisualizer @ /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:968
  - cvisualizer @ /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:974

#### Incomplete (valid but missing values)
- cvisualizer: 3 sites: /home/chukyu/t-sim/src/libsim_kun/libsimk_SimEnqueSem.c:48, /home/chukyu/t-sim/src/sim430d/sim430d.c:836, /home/chukyu/t-svm/src/libDac/Dac_EnqSem.c:115
- legacy: 8 sites: /home/chukyu/t-sim/src/sim730/sim730.c:682, /home/chukyu/t-sim/src/sim730/sim730.c:697, /home/chukyu/t-sim/src/sim730/sim730.c:704, /home/chukyu/t-sim/src/sim735/sim735.c:1133, /home/chukyu/t-sim/src/sim735/sim735.c:1145, /home/chukyu/t-sim/src/sim735/sim735.c:1152, /home/chukyu/t-sim/src/sim735/sim735.c:1198, /home/chukyu/t-sim/src/sim735/sim735.c:1222

#### Cause-tag frequencies (site-level)
- UNREACHABLE_ROOT_MODEL: 98
- INSUFFICIENT_EVIDENCE: 97
- STALE_HEADER_OR_SOURCE: 34
- MISSING_CALLER_EDGE: 16
- DEAD_PATH: 11
- PREPROCESSOR_CONFIGURATION: 6
- MISSING_ASSIGNMENT_EDGE: 4
- HANDLE_IDENTITY_LOST: 3
- MISSING_WRAPPER_MAPPING: 1
- MISSING_CALLBACK_EDGE: 1
- BRANCH_MERGE_ERROR: 1


#### Confidence distribution
- high: 275
- low: 82
- medium: 36


#### Key findings
1. **UNREACHABLE_ROOT_MODEL is the dominant systematic gap.** 98 sites carry this tag: the dataflow walk stops at the `mpf_mfs_open*` root or at a wrapper handle and never constant-folds the file-number argument. This is why legacy UNDERAPPROXIMATES 144/393 sites (reporting only the handle, `OPEN_LOCK`, `OK_MACRO` status, or nothing) and c-visualizer UNDERAPPROXIMATES 136/393 (it resolves the same open-edge at most sites but not all).
2. **c-visualizer HANDLE_IDENTITY_LOST — the only outright false values in the batch (3).** msgrequest.c:469/968/974: c-viz reports 2913 (MsgIndexDvdNo) but `IDX_fcb` is opened at msgrequest.c:356 with `IDX_FNO`, a global assigned `MsgIndexNo` (2902) at :195 and never reassigned; 2913 belongs to the msg240 flow. Expected value at all three sites: 2902.
3. **c-visualizer CORRECT_INCOMPLETE (3) — dropped branches in caller unions.** sim430d.c:836 reports {1106,1107} vs source {1105,1106,1107} (misses Simpidx==0 → SIM_430DSEMQUENO_0); libsimk_SimEnqueSem.c:48 reports {1103,1104,1106,1107} vs {1103..1107} (misses sim470d.c:321 → 1105); libDac/Dac_EnqSem.c:115 reports {845} vs {845,843,844} (misses SvmFLReport.c:69 → SvmFLQNo 843, SvmKdcReport.c:77/89 → SvmMISetQNo 844). All reported values are source-valid; only the union is incomplete.
4. **legacy CORRECT_INCOMPLETE (8) — wrapper caller unions cut short.** sim730.c:682/697/704 report {3403} vs {3403,3411} (misses Simkenexec_fcb callers ken.c:496 / con.c:203); sim735.c:1133/1145/1152/1198 report {3404,3405} vs {3404,3405,3407} (misses SIM_TENKAI_BUF caller tejun.c:1918); sim735.c:1222 reports {3405} vs {3404,3405} (misses tejun.c:2047).
5. **STALE_HEADER_OR_SOURCE — 34 sites.** ~30 distinct file-number macros are used in source but have no `#define` anywhere in the active tree (KUNUNTVSAIGEN_NO, API_TOP_JOHEN_FILE, SvmJikoStatNo, SvmJikoSfNo, SvmKyoukyuNo, SvmHatudenNo, SvmSyunTeiMngNo, SvmSyunStatNo, SvmSyunTeiNo, SvmLSKTBtnDefNo, SvmRYKTBtnDefNo, SvmCspcDefNo, SvmSyunCyouDefNo, SvmKyoSishoTMNo, SvmHatSishoTMNo, SvmSWKumiDefNo, SvmSWRYDefNo, SvmJikoATMngNo/SvmJimATMngNo/SvmChoATMngNo/SvmSyunATMngNo). Two reported values resting on such macros are unprovable and counted as such: 4102 (msg700.org/msg700mmi.c:827) and 1413 (topOnJohen.c:175).
6. **DEAD_PATH / PREPROCESSOR_CONFIGURATION (11 + 6 sites).** msg700.org/ is a backup directory excluded from every Makefile SRCS list; svm000SendInt.c's static send/open functions have all call sites commented out. In-file values are noted where the macro resolves, but the paths are not live code.
7. **UNDECIDED (101 sites) is mostly correct conservatism.** Remaining undecidable sites fall into: (a) wrapper parameters whose only callers are outside the tree (library exports: libopcp/file.c, libDac/Dac_DelQue, Dac_EnqFork, SvmEnqFork, libsvmG/SvmUtility.c, SvmJikoku, SimAddSemCB) — for these no value is provable from the delivered source; (b) input-driven values (SetFile/svmsetq/setfile argv→atoi, msg200dCsvRq SCN dupname); (c) the stale-macro sites above. For parameter wrappers with an in-tree open (libsimk_SimChoku, libsvmP/SvmCtlCurVer, libsvmutil SimDll*/SimDevFailF, SvmJyuteiden, sim800/sim801/sim810, sim780_cb, sim570d, libsimutil) both pipelines report no value although the open argument is a resolvable constant — this is the actionable residual gap for both tools.
8. **Precision is very high where either pipeline reports.** c-visualizer 167/172 accepted values (97.1%, the 5 misses are the three 2913 values counted once per site-row plus 4102 and 1413); legacy 167/167 (100%). No legacy false value exists in the batch; legacy errors are all omissions.

Method: for each site the enclosing function was located, every `mpf_mfs_open*`/`open`/`addque`/`delque` binding of the target handle (or the wrapper parameter) was traced within the active preprocessor configuration, file-number macros were resolved to their `#define` values in the active header set, and wrapper parameters were unioned over all in-tree call sites. Sites whose only constant source is a macro with no in-tree definition, an out-of-tree caller, commented-out code, or unbounded input are reported UNDECIDED with the specific blocker stated per site. Site-level pipeline verdicts above are computed by direct set comparison of each pipeline's reported values against the source-expected set.

### Site verdicts
#### t-rep/src

##### /home/chukyu/t-rep/src/libmsg

##### /home/chukyu/t-rep/src/libmsg/MsgEnqSem.c:127

- Target: `quename` arg 2 of `mpf_mfs_addque` (ADDQUE); category both_unresolved
- Expected: {1051} [PATH_VALID]
  - proof: MsgSaveMsg.c:91 MsgEnqSem(...,MsgGetQNo,...) sole caller; MsgGetQNo=1051 (rep/Msg.h:55)
- c-viz (row 2489): expr `quename` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2489): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_CALLER_EDGE;UNREACHABLE_ROOT_MODEL | Confidence: medium
- Note: queue no is wrapper param; sole in-tree caller passes MsgGetQNo

##### /home/chukyu/t-rep/src/libmsg/MsgPtnGet.c:50

- Target: `&fcb_def` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2901} [PATH_VALID]
  - proof: MsgPtnGet.c:45 mpf_mfs_open(&fcb_def,...,MsgDefineNo); MsgDefineNo=2901 (rep/Msg.h:48)
- c-viz (row 1929): expr `&fcb_def` values {2901} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 1929): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/libmsg/MsgPtnGet.c:63

- Target: `&fcb_con` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2909} [PATH_VALID]
  - proof: MsgPtnGet.c:58 open(&fcb_con,MsgPtnConNo); MsgPtnConNo=2909 (rep/Msg.h:49)
- c-viz (row 1930): expr `&fcb_con` values {2909} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 1930): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/libmsg/MsgPtnGet.c:71

- Target: `&fcb_ptn` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2910} [PATH_VALID]
  - proof: MsgPtnGet.c:66 open(&fcb_ptn,MsgPtnDefNo); MsgPtnDefNo=2910 (rep/Msg.h:50)
- c-viz (row 1931): expr `&fcb_ptn` values {2910} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 1931): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/libmsg1

##### /home/chukyu/t-rep/src/libmsg1/MsgChkFlg.c:79

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: MsgChkFlg.c:71 open(&fcb,MsgIndexNo); line 69 open is commented; MsgIndexNo=2902 (MsgFile.h:57)
- c-viz (row 1932): expr `&fcb` values {2902} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 1932): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/libmsg1/Msg_SetSendLg.c:72

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2908} [PATH_VALID]
  - proof: Msg_SetSendLg.c:60 open_H(&fcb,MsgSendLgNo); MsgSendLgNo=2908 (MsgFile.h:63)
- c-viz (row 1933): expr `&fcb` values {2908} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 1933): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/libmsg1/Msg_SetSendLg.c:96

- Target: `&fcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {2908} [PATH_VALID]
  - proof: Msg_SetSendLg.c:60 open_H(&fcb,MsgSendLgNo); no close before 96
- c-viz (row 1934): expr `&fcb` values {} statuses {"UNREACHABLE": 1, "UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1934): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:356

- Target: `IDX_FNO` arg 2 of `mpf_mfs_open_H` (OPEN_LOCK); category both_unresolved
- Expected: {2902} [PATH_VALID]
  - proof: msgrequest.c:195 IDX_FNO=MsgIndexNo(2902); open_H(&IDX_fcb,IDX_FNO) :356
- c-viz (row 1935): expr `IDX_FNO` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1935): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high
- Note: IDX_FNO is global var assigned once at init

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:360

- Target: `&IDX_fcb` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {2902} [PATH_VALID]
  - proof: open_H at 356 (IDX_FNO=2902), same fn, no close before 360
- c-viz (row 1936): expr `&IDX_fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1936): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:469

- Target: `&IDX_fcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: IDX_fcb opened at 356 with IDX_FNO=MsgIndexNo=2902 (:195); still open (not closed) in _msg220SearchFile
- c-viz (row 1937): expr `&IDX_fcb` values {2913} statuses {"EXACT": 1, "UNREACHABLE": 1} → **PARTIAL_OVERLAP**
- legacy (row 1937): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: HANDLE_IDENTITY_LOST | Confidence: medium
- Note: c-viz 2913=MsgIndexDvdNo is the msg240 flow file, never bound to IDX_fcb here

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:968

- Target: `&IDX_fcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: as 469: IDX_fcb <- open_H :356 IDX_FNO=2902
- c-viz (row 1938): expr `&IDX_fcb` values {2913} statuses {"EXACT": 1, "UNREACHABLE": 1} → **PARTIAL_OVERLAP**
- legacy (row 1938): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: HANDLE_IDENTITY_LOST | Confidence: medium

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:974

- Target: `&IDX_fcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: as 469
- c-viz (row 1939): expr `&IDX_fcb` values {2913} statuses {"EXACT": 1, "UNREACHABLE": 1} → **PARTIAL_OVERLAP**
- legacy (row 1939): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: HANDLE_IDENTITY_LOST | Confidence: medium

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1083

- Target: `JOHEN_FNO` arg 2 of `mpf_mfs_open_H` (OPEN_LOCK); category both_unresolved
- Expected: {2904} [PATH_VALID]
  - proof: msgrequest.c:196 JOHEN_FNO=MsgJohenNo(2904)
- c-viz (row 1940): expr `JOHEN_FNO` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1940): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1098

- Target: `&johen_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {2904} [PATH_VALID]
  - proof: open_H(&johen_fcb,JOHEN_FNO=2904) at 1083, close at 1100
- c-viz (row 1941): expr `&johen_fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1941): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1171

- Target: `&fcb_result` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {2907} [PATH_VALID]
  - proof: open_H(&fcb_result,MsgResultNo=2907) at 1152 in _msg220ResultFile
- c-viz (row 1942): expr `&fcb_result` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1942): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1202

- Target: `&fcb_result` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {2907} [PATH_VALID]
  - proof: open_H(&fcb_result,MsgResultNo) at 1152
- c-viz (row 1943): expr `&fcb_result` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1943): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1219

- Target: `&fcb_result` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {2907} [PATH_VALID]
  - proof: open_H(&fcb_result,MsgResultNo) at 1152; close 1220 after
- c-viz (row 1944): expr `&fcb_result` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1944): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1378

- Target: `&fcb_result` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {2907} [PATH_VALID]
  - proof: open_H(&fcb_result,MsgResultNo) at 1342 in _msg220ResultPrint
- c-viz (row 1945): expr `&fcb_result` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1945): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1388

- Target: `&fcb_print` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {2906} [PATH_VALID]
  - proof: open_H(&fcb_print,MsgPrintNo=2906) at 1308
- c-viz (row 1946): expr `&fcb_print` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1946): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1408

- Target: `&fcb_result` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {2907} [PATH_VALID]
  - proof: open_H(&fcb_result,MsgResultNo) at 1342
- c-viz (row 1947): expr `&fcb_result` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1947): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/libmsgreq/msgrequest.c:1410

- Target: `&fcb_print` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {2906} [PATH_VALID]
  - proof: open_H(&fcb_print,MsgPrintNo) at 1308
- c-viz (row 1948): expr `&fcb_print` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1948): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/librep

##### /home/chukyu/t-rep/src/librep/RepGN3MGet.c:47

- Target: `RepManageNo` arg 2 of `mpf_mfs_open_H` (OPEN_LOCK); category both_unresolved
- Expected: {2951} [PATH_VALID]
  - proof: open_H(&fcb_kanri_onl,RepManageNo); RepManageNo=2951 (RepP.h:69)
- c-viz (row 1949): expr `RepManageNo` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1949): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/librep/RepGN3MGet.c:53

- Target: `&fcb_kanri_onl` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {2951} [PATH_VALID]
  - proof: open at 47 (RepManageNo=2951), close 54 after read
- c-viz (row 1950): expr `&fcb_kanri_onl` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1950): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/librep/RepGN3MGet.c:63

- Target: `fileno` arg 2 of `mpf_mfs_open_H` (OPEN_LOCK); category both_unresolved
- Expected: {2958, 2959} [PATH_VALID]
  - proof: fileno=RepSeigyoLog1No(2958)/RepSeigyoLog2No(2959) at :57/:60 (rep/RepDFS.h:29,44)
- c-viz (row 1951): expr `fileno` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1951): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_ASSIGNMENT_EDGE | Confidence: high
- Note: two-branch assignment to fileno

##### /home/chukyu/t-rep/src/librep/RepGN3MGet.c:69

- Target: `&fcb_seigyo` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {2958, 2959} [PATH_VALID]
  - proof: open at 63 (fileno in {2958,2959})
- c-viz (row 1952): expr `&fcb_seigyo` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1952): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_ASSIGNMENT_EDGE | Confidence: high

##### /home/chukyu/t-rep/src/librep/RepSojuyoGet.c:68

- Target: `RepManageNo` arg 2 of `mpf_mfs_open_H` (OPEN_LOCK); category both_unresolved
- Expected: {2951} [PATH_VALID]
  - proof: open_H(&fcb_kanri_onl,RepManageNo=2951)
- c-viz (row 1953): expr `RepManageNo` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1953): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/librep/RepSojuyoGet.c:74

- Target: `&fcb_kanri_onl` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {2951} [PATH_VALID]
  - proof: open at 68 (2951), close 75
- c-viz (row 1954): expr `&fcb_kanri_onl` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1954): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/librep/RepSojuyoGet.c:99

- Target: `fileno` arg 2 of `mpf_mfs_open_H` (OPEN_LOCK); category both_unresolved
- Expected: {2956, 2957} [PATH_VALID]
  - proof: fileno=RepJudenLog1No(2956)/RepJudenLog2No(2957) at :82/:85/:91/:94 (RepDFS.h:28,43)
- c-viz (row 1955): expr `fileno` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1955): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_ASSIGNMENT_EDGE | Confidence: high

##### /home/chukyu/t-rep/src/librep/RepSojuyoGet.c:105

- Target: `&fcb_juden` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {2956, 2957} [PATH_VALID]
  - proof: open at 99 (fileno in {2956,2957})
- c-viz (row 1956): expr `&fcb_juden` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1956): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_ASSIGNMENT_EDGE | Confidence: high

##### /home/chukyu/t-rep/src/msg001

##### /home/chukyu/t-rep/src/msg001/msg001ClrDvd.c:112

- Target: `&MngFcb` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {2911} [PATH_VALID]
  - proof: open_H(&MngFcb,MsgDvdMngNo=2911) at 101 (MsgFile.h:76)
- c-viz (row 1957): expr `&MngFcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1957): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/msg001/msg001ClrDvd.c:126

- Target: `&MngFcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {2911} [PATH_VALID]
  - proof: open at 101; close after write
- c-viz (row 1958): expr `&MngFcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1958): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/msg001/msg001MakeIDX.c:76

- Target: `MsgIndexDDNo; fileinf[i].indexdno` arg 2 of `mpf_mfs_copyfile` (COPYFILE_FROM, COPYFILE_TO); category legacy_resolved_only
- Expected: {arg2=2903, arg6=2902} [PATH_VALID]
  - proof: fileinf[0]={MsgIndexDDNo(2903),MsgIndexNo(2902),MsgJohenNo(2904),...} :58; loop terminates at -1 entry :59
- c-viz (row 1959): expr `fileinf[i].indexdno` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1959): expr `MsgIndexDDNo; fileinf[i].indexdno` values {2903} statuses {"ADDED": 1, "OK_CONST": 1} → **CORRECT**
- c-viz (row 1960): expr `fileinf[i].indexmno` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1960): expr `MsgIndexNo; fileinf[i].indexmno` values {2902} statuses {"ADDED": 1, "OK_CONST": 1} → **CORRECT**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high
- Note: one table entry only

##### /home/chukyu/t-rep/src/msg001/msg001MakeIDX.c:99

- Target: `MsgJohenNo; fileinf[i].jhenfno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {2904} [PATH_VALID]
  - proof: open(&fcb_johen,fileinf[0].jhenfno=MsgJohenNo=2904)
- c-viz (row 1961): expr `fileinf[i].jhenfno` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1961): expr `MsgJohenNo; fileinf[i].jhenfno` values {2904} statuses {"ADDED": 1, "OK_CONST": 1} → **CORRECT**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/msg001/msg001MakeIDX.c:117

- Target: `&fcb_johen` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {2904} [PATH_VALID]
  - proof: open(&fcb_johen,jhenfno=2904) at 99
- c-viz (row 1962): expr `&fcb_johen` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1962): expr `&fcb_johen` values {} statuses {"OK_CONST": 1} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL;MISSING_WRAPPER_MAPPING | Confidence: high
- Note: legacy OK_CONST gave handle only, no number

##### /home/chukyu/t-rep/src/msg001/msg001MakeIDX.c:123

- Target: `fileinf[i].indexmno` arg 3 of `mpf_mfs_open` (READ, WRITE); category both_unresolved
- Expected: {2902} [PATH_VALID]
  - proof: open(&fcb_index,fileinf[0].indexmno=MsgIndexNo=2902)
- c-viz (row 1963): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 1963): expr `fileinf[i].indexmno` values {} statuses {"OK_CONST": 1} → **UNDERAPPROXIMATION**
- c-viz (row 1964): expr `fileinf[i].indexmno` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1964): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/msg001/msg001MakeIDX.c:137

- Target: `&fcb_index` arg 1 of `mpf_mfs_getrecm` (GETREC); category legacy_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: open(&fcb_index,indexmno=2902) at 123
- c-viz (row 1965): expr `&fcb_index` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1965): expr `&fcb_index; MsgIndexNo` values {2902} statuses {"ADDED": 1, "OK_CONST": 1} → **CORRECT**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/msg001/msg001SetFlg.c:43

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category equal
- Expected: {2902} [PATH_VALID]
  - proof: open(&fcb,MsgIndexNo=2902) at 42
- c-viz (row 1966): expr `&fcb` values {2902} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1966): expr `&fcb; MsgIndexNo` values {2902} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg001/msg001SetFlg.c:47

- Target: `&fcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category equal
- Expected: {2902} [PATH_VALID]
  - proof: open at 42
- c-viz (row 1967): expr `&fcb` values {2902} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1967): expr `&fcb; MsgIndexNo` values {2902} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg200d

##### /home/chukyu/t-rep/src/msg200d/msg200dAdJohen.c:407

- Target: `&FCBJ` arg 1 of `mpf_mfs_writerec` (WRITEREC); category cvisualizer_resolved_only
- Expected: {2904} [PATH_VALID]
  - proof: open(&FCBJ,MsgJohenNo=2904) at 398; close 408
- c-viz (row 1968): expr `&FCBJ` values {2904} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1968): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/msg200d/msg200dCsvRq.c:197

- Target: `(char *)dupname` arg 1 of `pmf_forkprocdup_H` (FORKPROC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: dupname[] filled by mpf_scn_getdupname :183 (SCN runtime data); no static source value
- c-viz (row 44): expr `(char *)dupname` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 44): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low
- Note: FORKPROC target=process name, runtime-supplied

##### /home/chukyu/t-rep/src/msg200d/msg200dCsvRq.c:244

- Target: `&IDXFcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: open_H(&IDXFcb,MsgIndexNo=2902) at 233
- c-viz (row 1969): expr `&IDXFcb` values {2902} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1969): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/msg200d/msg200dFile.c:63

- Target: `&fcb_msgdef` arg 1 of `mpf_mfs_getrec` (GETREC); category cvisualizer_resolved_only
- Expected: {2901} [PATH_VALID]
  - proof: open(&fcb_msgdef,MsgDefineNo=2901) at 49
- c-viz (row 1970): expr `&fcb_msgdef` values {2901} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1970): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/msg200d/msg200dFile.c:87

- Target: `&FCBI` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: open(&FCBI,MsgIndexNo=2902) at 82
- c-viz (row 1971): expr `&FCBI` values {2902} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1971): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/src/msg230d

##### /home/chukyu/t-rep/src/msg230d/msg230d.c:132

- Target: `&fixed_fcb` arg 1 of `mpf_mfs_getrec` (GETREC); category equal
- Expected: {2905} [PATH_VALID]
  - proof: open(&fixed_fcb,MsgFixedNumNo=2905) at 127
- c-viz (row 1972): expr `&fixed_fcb` values {2905} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1972): expr `&fixed_fcb; MsgFixedNumNo` values {2905} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg230d/msg230d.c:161

- Target: `MsgBackUpQNo` arg 2 of `mpf_mfs_delque` (DELQUE); category legacy_resolved_only
- Expected: {1055} [PATH_VALID]
  - proof: delque(NULL,MsgBackUpQNo=1055) inline (MsgFile.h:89)
- c-viz (row 2490): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2490): expr `MsgBackUpQNo` values {1055} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg240

##### /home/chukyu/t-rep/src/msg240/msg240AtPro.c:154

- Target: `&MngFcb` arg 1 of `mpf_mfs_readrec` (READREC); category equal
- Expected: {2911} [PATH_VALID]
  - proof: open_H(&MngFcb,MsgDvdMngNo=2911) at 143
- c-viz (row 1973): expr `&MngFcb` values {2911} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1973): expr `&MngFcb; MsgDvdMngNo` values {2911} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg240/msg240AtPro.c:216

- Target: `&MngFcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category equal
- Expected: {2911} [PATH_VALID]
  - proof: open at 143
- c-viz (row 1974): expr `&MngFcb` values {2911} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1974): expr `&MngFcb; MsgDvdMngNo` values {2911} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg240/msg240GetMDt.c:63

- Target: `&IDX_fcb` arg 1 of `mpf_mfs_readrec` (READREC); category equal
- Expected: {2913} [PATH_VALID]
  - proof: open_H(&IDX_fcb,MsgIndexDvdNo=2913) at 58
- c-viz (row 1975): expr `&IDX_fcb` values {2913} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1975): expr `&IDX_fcb; MsgIndexDvdNo` values {2913} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg240/msg240GetMDt.c:110

- Target: `&johen_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {2912} [PATH_VALID]
  - proof: open_H(&johen_fcb,MsgJohenDvdNo=2912) at 100
- c-viz (row 1976): expr `&johen_fcb` values {2912} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1976): expr `&johen_fcb; MsgJohenDvdNo` values {2912} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg242

##### /home/chukyu/t-rep/src/msg242/msg242CsvDel.c:252

- Target: `&MngFcb` arg 1 of `mpf_mfs_readrec` (READREC); category equal
- Expected: {2911} [PATH_VALID]
  - proof: open_H(&MngFcb,MsgDvdMngNo=2911) at 241
- c-viz (row 1977): expr `&MngFcb` values {2911} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1977): expr `&MngFcb; MsgDvdMngNo` values {2911} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg242/msg242CsvDel.c:370

- Target: `&MngFcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category equal
- Expected: {2911} [PATH_VALID]
  - proof: open at 241; close 374
- c-viz (row 1978): expr `&MngFcb` values {2911} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1978): expr `&MngFcb; MsgDvdMngNo` values {2911} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg400d

##### /home/chukyu/t-rep/src/msg400d/msg400dDeq.c:63

- Target: `MsgGetQNo` arg 2 of `mpf_mfs_delque` (DELQUE); category legacy_resolved_only
- Expected: {1051} [PATH_VALID]
  - proof: delque(NULL,MsgGetQNo=1051) inline
- c-viz (row 2491): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2491): expr `MsgGetQNo` values {1051} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg400d/msg400dDeq.c:82

- Target: `MsgGetQNo` arg 2 of `mpf_mfs_delque` (DELQUE); category legacy_resolved_only
- Expected: {1051} [PATH_VALID]
  - proof: delque(NULL,MsgGetQNo=1051) inline
- c-viz (row 2492): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2492): expr `MsgGetQNo` values {1051} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg400d/msg400dMain.c:64

- Target: `&fixed_fcb` arg 1 of `mpf_mfs_getrec` (GETREC); category equal
- Expected: {2905} [PATH_VALID]
  - proof: open(&fixed_fcb,MsgFixedNumNo=2905) at 59
- c-viz (row 1979): expr `&fixed_fcb` values {2905} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1979): expr `&fixed_fcb; MsgFixedNumNo` values {2905} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg500d

##### /home/chukyu/t-rep/src/msg500d/msg500dOpBtn.c:55

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category equal
- Expected: {2914} [PATH_VALID]
  - proof: open_H(&fcb,MsgFlickerLevelNo=2914) at 51 (MsgFile.h:65)
- c-viz (row 1980): expr `&fcb` values {2914} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1980): expr `&fcb; MsgFlickerLevelNo` values {2914} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg500d/msg500dOpBtn.c:64

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category equal
- Expected: {2914} [PATH_VALID]
  - proof: open at 51
- c-viz (row 1981): expr `&fcb` values {2914} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1981): expr `&fcb; MsgFlickerLevelNo` values {2914} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg500d/msg500dOpBtn.c:119

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2914} [PATH_VALID]
  - proof: open_H(&fcb,MsgFlickerLevelNo=2914) at 115 in msg500dBtnFlicker
- c-viz (row 1982): expr `&fcb` values {2914} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1982): expr `&fcb; MsgFlickerLevelNo` values {2914} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg500d/msg500dOpBtn.c:133

- Target: `&fcb` arg 1 of `mpf_mfs_updaterecm` (UPDATEREC); category both_unresolved
- Expected: {2914} [PATH_VALID]
  - proof: open_H(&fcb,MsgFlickerLevelNo) at 115; fcb still open at 133
- c-viz (row 1983): expr `&fcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1983): expr `&fcb` values {} statuses {"OK_CONST": 1} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high
- Note: mpf_mfs_updaterecm

##### /home/chukyu/t-rep/src/msg700/msg700.org

##### /home/chukyu/t-rep/src/msg700/msg700.org/msg700KensakuData.c:64

- Target: `&RESULT_fcb` arg 1 of `mpf_mfs_readrec` (READREC); category equal
- Expected: {2907} [PATH_VALID]
  - proof: open_H(&RESULT_fcb,MsgResultNo) at 55; DEAD_PATH (backup dir not in SRCS)
- c-viz (row 1984): expr `&RESULT_fcb` values {2907} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1984): expr `&RESULT_fcb; MsgResultNo` values {2907} statuses {"ADDED": 1, "ALREADY_PRESENT": 1, "OK_MACRO": 2} → **CORRECT**
- Cause tags: PREPROCESSOR_CONFIGURATION | Confidence: high
- Note: value valid within file; dir not compiled

##### /home/chukyu/t-rep/src/msg700/msg700.org/msg700KensakuData.c:109

- Target: `&RESULT_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {2907} [PATH_VALID]
  - proof: as 64; DEAD_PATH
- c-viz (row 1985): expr `&RESULT_fcb` values {2907} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1985): expr `&RESULT_fcb; MsgResultNo` values {2907} statuses {"ADDED": 1, "ALREADY_PRESENT": 1, "OK_MACRO": 2} → **CORRECT**
- Cause tags: PREPROCESSOR_CONFIGURATION | Confidence: high

##### /home/chukyu/t-rep/src/msg700/msg700.org/msg700button.c:762

- Target: `&fcp` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {2911} [PATH_VALID]
  - proof: openm_H(&fcp,MsgDvdMngNo=2911) at 761; DEAD_PATH
- c-viz (row 1986): expr `&fcp` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1986): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: PREPROCESSOR_CONFIGURATION | Confidence: high

##### /home/chukyu/t-rep/src/msg700/msg700.org/msg700mmi.c:826

- Target: `KUNUNTVSAIGEN_NO` arg 2 of `mpf_mfs_openm_H` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: KUNUNTVSAIGEN_NO undefined; DEAD_PATH
- c-viz (row 1987): expr `` values {} statuses {} → **UNDECIDED_SITE**
- legacy (row 1987): expr `KUNUNTVSAIGEN_NO` values {} statuses {"OK_CONST": 2} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;PREPROCESSOR_CONFIGURATION | Confidence: low

##### /home/chukyu/t-rep/src/msg700/msg700.org/msg700mmi.c:827

- Target: `&fcp` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: no source-provable value [UNDECIDED]
  - reason: fcp opened at 826 with undefined macro; c-viz 4102 not provable from active source
- c-viz (row 1988): expr `&fcp` values {4102} statuses {"EXACT": 1} → **UNPROVABLE_CLAIM**
- legacy (row 1988): expr `&fcp` values {} statuses {"OK_CONST": 2} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low
- Note: 4102 likely from stale header

##### /home/chukyu/t-rep/src/msg700/msg700.org/msg700mmi.c:891

- Target: `&fcp` arg 1 of `mpf_mfs_readrecm` (READREC); category equal
- Expected: {2911} [PATH_VALID]
  - proof: openm_H(&fcp,MsgDvdMngNo=2911) at 890; DEAD_PATH
- c-viz (row 1989): expr `&fcp` values {2911} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 1989): expr `&fcp; MsgDvdMngNo` values {2911} statuses {"ADDED": 1, "ALREADY_PRESENT": 1, "OK_MACRO": 2} → **CORRECT**
- Cause tags: PREPROCESSOR_CONFIGURATION | Confidence: high

##### /home/chukyu/t-rep/src/msg700

##### /home/chukyu/t-rep/src/msg700/msg700KensakuData.c:73

- Target: `&RESULT_fcb` arg 1 of `mpf_mfs_readrec` (READREC); category legacy_resolved_only
- Expected: {2907} [PATH_VALID]
  - proof: open_H(&RESULT_fcb,MsgResultNo=2907) at 64
- c-viz (row 1990): expr `&RESULT_fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1990): expr `&RESULT_fcb; MsgResultNo` values {2907} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg700/msg700KensakuData.c:118

- Target: `&RESULT_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category legacy_resolved_only
- Expected: {2907} [PATH_VALID]
  - proof: open at 64
- c-viz (row 1991): expr `&RESULT_fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1991): expr `&RESULT_fcb; MsgResultNo` values {2907} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-rep/src/msg700/msg700button.c:794

- Target: `&fcp` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {2911} [PATH_VALID]
  - proof: openm_H(&fcp,MsgDvdMngNo=2911) at 793; close 795
- c-viz (row 1992): expr `&fcp` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1992): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/src/msg700/msg700mmi.c:952

- Target: `KUNUNTVSAIGEN_NO` arg 2 of `mpf_mfs_openm_H` (OPEN_LOCK, READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: KUNUNTVSAIGEN_NO not defined anywhere in active tree
- c-viz (row 1993): expr `KUNUNTVSAIGEN_NO` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 1993): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- c-viz (row 1994): expr `` values {} statuses {} → **UNDECIDED_SITE**
- legacy (row 1994): expr `KUNUNTVSAIGEN_NO` values {} statuses {"OK_CONST": 1} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low
- Note: macro used but definition absent

##### /home/chukyu/t-rep/src/msg700/msg700mmi.c:953

- Target: `&fcp` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcp opened at 952 with undefined macro KUNUNTVSAIGEN_NO
- c-viz (row 1995): expr `&fcp` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 1995): expr `&fcp` values {} statuses {"OK_CONST": 1} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-rep/src/msg700/msg700mmi.c:1031

- Target: `&fcp` arg 1 of `mpf_mfs_readrecm` (READREC); category legacy_resolved_only
- Expected: {2911} [PATH_VALID]
  - proof: openm_H(&fcp,MsgDvdMngNo=2911) at 1030
- c-viz (row 1996): expr `&fcp` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 1996): expr `&fcp; MsgDvdMngNo` values {2911} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

#### t-rep/tool

##### /home/chukyu/t-rep/tool/msgcrecon

##### /home/chukyu/t-rep/tool/msgcrecon/msgcrecon.c:190

- Target: `&mmfcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {2909} [PATH_VALID]
  - proof: mmfcb global opened at 89 (MsgPtnConNo=2909); cpy_data called from main :111/:147 between open/close(151)
- c-viz (row 1997): expr `&mmfcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1997): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/tool/msgcrecon/msgcrecon.c:215

- Target: `&mmfcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {2909} [PATH_VALID]
  - proof: same handle mmfcb (open 89, close 151)
- c-viz (row 1998): expr `&mmfcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1998): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/tool/msgcredef

##### /home/chukyu/t-rep/tool/msgcredef/msgcredef.c:226

- Target: `&mmfcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {2901} [PATH_VALID]
  - proof: mmfcb opened at 94 (MsgDefineNo=2901); cpy_data via main :118/:183
- c-viz (row 1999): expr `&mmfcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 1999): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/tool/msgcredef/msgcredef.c:338

- Target: `&mmfcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {2901} [PATH_VALID]
  - proof: same handle
- c-viz (row 2000): expr `&mmfcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2000): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/tool/msgcreptn

##### /home/chukyu/t-rep/tool/msgcreptn/msgcreptn.c:209

- Target: `&mmfcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {2910} [PATH_VALID]
  - proof: mmfcb opened at 93 (MsgPtnDefNo=2910); cpy_data via main :115/:171
- c-viz (row 2001): expr `&mmfcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2001): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/tool/msgcreptn/msgcreptn.c:240

- Target: `&mmfcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {2910} [PATH_VALID]
  - proof: same handle
- c-viz (row 2002): expr `&mmfcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2002): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-rep/tool/msgtool

##### /home/chukyu/t-rep/tool/msgtool/msgtool.c:813

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: open(&fcb,MsgIndexNo=2902) at 808 in index_disp
- c-viz (row 2003): expr `&fcb` values {2902} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2003): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/tool/msgtool/msgtool.c:845

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: open at 840 in index_init
- c-viz (row 2004): expr `&fcb` values {2902} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2004): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/tool/msgtool/msgtool.c:877

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: open at 872 in dmp_index
- c-viz (row 2005): expr `&fcb` values {2902} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2005): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/tool/msgtool/msgtool.c:899

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2902} [PATH_VALID]
  - proof: open at 872 (loop)
- c-viz (row 2006): expr `&fcb` values {2902} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2006): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/tool/msgtool/msgtool.c:924

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2904} [PATH_VALID]
  - proof: open(&fcb,MsgJohenNo=2904) at 919 in dmp_johen
- c-viz (row 2007): expr `&fcb` values {2904} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2007): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-rep/tool/msgtool/msgtool.c:927

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2904} [PATH_VALID]
  - proof: open at 919 (loop)
- c-viz (row 2008): expr `&fcb` values {2904} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2008): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

#### t-sim/src

##### /home/chukyu/t-sim/src/libopcp

##### /home/chukyu/t-sim/src/libopcp/file.c:59

- Target: `fno` arg 3 of `mpf_mfs_open` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fno is Simlib_FileOpen parameter; no in-tree callers (library export)
- c-viz (row 2009): expr `fno` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2009): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-sim/src/libopcp/file.c:97

- Target: `cm_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: cm_fcb bound by Simlib_FileOpen(fno) :59 with caller-supplied fno; no in-tree callers
- c-viz (row 2010): expr `cm_fcb` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2010): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-sim/src/libsim

##### /home/chukyu/t-sim/src/libsim/SimChgInit.c:88

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {3409} [PATH_VALID]
  - proof: open(&fcb,SIM_HENKOU=3409) at 77 in SimGetHenkou (SimHenkou.h:10)
- c-viz (row 2011): expr `&fcb` values {3409} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2011): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsim/SimChgInit.c:285

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {3412} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_ST=3412) at 279 in SimInitSV
- c-viz (row 2012): expr `&fcb` values {3412} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2012): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsim/SimChgInit.c:312

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category cvisualizer_resolved_only
- Expected: {3412} [PATH_VALID]
  - proof: open at 279; close 313 after write
- c-viz (row 2013): expr `&fcb` values {3412} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2013): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsim/SimChgInit.c:370

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {3412} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_ST=3412) at 364 in SimInitTM
- c-viz (row 2014): expr `&fcb` values {3412} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2014): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsim/SimChgInit.c:400

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category cvisualizer_resolved_only
- Expected: {3412} [PATH_VALID]
  - proof: open at 364
- c-viz (row 2015): expr `&fcb` values {3412} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2015): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:63

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {3409} [PATH_VALID]
  - proof: open(&fcb,SIM_HENKOU=3409) at 52 in SimkGetHenkou
- c-viz (row 2016): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2016): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:97

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3435} [PATH_VALID]
  - proof: openm(&fcb,SIM_HATU_POS=3435) at 92 in SimkGetHatuPos
- c-viz (row 2017): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2017): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:152

- Target: `SIM_ODOSTATUS` arg 3 of `mpf_mfs_open` (OPEN_LOCK); category both_unresolved
- Expected: {3415} [PATH_VALID]
  - proof: open(&fcb,SIM_ODOSTATUS=3415) inline (SimOdoStatus.h)
- c-viz (row 2018): expr `SIM_ODOSTATUS` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2018): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:158

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3415} [PATH_VALID]
  - proof: open at 152; close 159
- c-viz (row 2019): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2019): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:420

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB=3401) at 415 in SimDbGet
- c-viz (row 2020): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2020): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:446

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category cvisualizer_resolved_only
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB=3401) at 439 in SimDbGetn
- c-viz (row 2021): expr `&fcb` values {3401} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2021): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:475

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB) at 470 in SimDbPut
- c-viz (row 2022): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2022): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimChoku.c:500

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category cvisualizer_resolved_only
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB) at 495 in SimDbPutn
- c-viz (row 2023): expr `&fcb` values {3401} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2023): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsim_kun/libsimk_SimEnqueSem.c:48

- Target: `fno` arg 2 of `mpf_mfs_addque` (ADDQUE); category cvisualizer_resolved_only
- Expected: {1103, 1104, 1105, 1106, 1107} [PATH_VALID]
  - proof: callers pass SIM_520DSEMQUENO(1103), SIM_570DSEMQUENO(1104), SIM_430DSEMQUENO_0/1/2(1105/1106/1107 via sim470d.c:319-321)
- c-viz (row 2493): expr `fno` values {1103, 1104, 1106, 1107} statuses {"EXACT": 4, "UNREACHABLE": 1} → **CORRECT_INCOMPLETE**
- legacy (row 2493): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium
- Note: c-viz misses 1105 (sim470d pidx==0 branch)

##### /home/chukyu/t-sim/src/libsimutil

##### /home/chukyu/t-sim/src/libsimutil/SimAddSemCB.c:96

- Target: `fno` arg 2 of `mpf_mfs_delque` (DELQUE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fno = SimSemCallback param; registration (SimAddSemCallback) has no in-tree caller
- c-viz (row 2494): expr `fno` values {} statuses {"EXTERNAL": 1, "UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2494): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;MISSING_CALLBACK_EDGE | Confidence: low

##### /home/chukyu/t-sim/src/libsimutil/SimDevFailF.c:52

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {3425} [PATH_VALID]
  - proof: openm(&fcb,SIM_DEVFAILFLGNO=3425) at 42
- c-viz (row 2024): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2024): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllFile.c:187

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {3421} [PATH_VALID]
  - proof: openm(&fcb,SIM_DLLDATANO=3421) at 177 in SimAddDllData
- c-viz (row 2025): expr `&fcb` values {3421} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2025): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllFile.c:217

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category cvisualizer_resolved_only
- Expected: {3421} [PATH_VALID]
  - proof: open at 177
- c-viz (row 2026): expr `&fcb` values {3421} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2026): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllFile.c:235

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {3421} [PATH_VALID]
  - proof: open at 177
- c-viz (row 2027): expr `&fcb` values {} statuses {"UNREACHABLE": 1, "UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2027): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllFile.c:281

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {3421} [PATH_VALID]
  - proof: openm(&fcb,SIM_DLLDATANO=3421) at 272 in SimSearchDllData
- c-viz (row 2028): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2028): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllStat.c:60

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {3422} [PATH_VALID]
  - proof: openm(&fcb,SIM_DLLSTATUSNO=3422) at 53 in SimGetDllStatus
- c-viz (row 2029): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2029): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllStat.c:121

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {3422} [PATH_VALID]
  - proof: openm(&fcb,SIM_DLLSTATUSNO) at 114 in SimAddDllStatus
- c-viz (row 2030): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2030): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllStat.c:133

- Target: `&fcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {3422} [PATH_VALID]
  - proof: open at 114
- c-viz (row 2031): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2031): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllStat.c:146

- Target: `&fcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {3422} [PATH_VALID]
  - proof: open at 114
- c-viz (row 2032): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2032): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllStat.c:155

- Target: `&fcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {3422} [PATH_VALID]
  - proof: open at 114
- c-viz (row 2033): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2033): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllTestF.c:63

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {3423} [PATH_VALID]
  - proof: openm(&fcb,SIM_DLLTESTFLGNO=3423) at 53 in SimGetDllTestFlg
- c-viz (row 2034): expr `&fcb` values {3423} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2034): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllTestF.c:108

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {3423} [PATH_VALID]
  - proof: openm(&fcb,SIM_DLLTESTFLGNO) at 99 in SimAddDllTestFlg
- c-viz (row 2035): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2035): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllTestF.c:114

- Target: `&fcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {3423} [PATH_VALID]
  - proof: open at 99
- c-viz (row 2036): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2036): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimDllTestF.c:123

- Target: `&fcb` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category both_unresolved
- Expected: {3423} [PATH_VALID]
  - proof: open at 99
- c-viz (row 2037): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2037): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/libsimutil/SimITCMode.c:62

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category cvisualizer_resolved_only
- Expected: {3424} [PATH_VALID]
  - proof: openm(&fcb,SIM_ITCMODENO=3424) at 51
- c-viz (row 2038): expr `&fcb` values {3424} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT**
- legacy (row 2038): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/sim430d

##### /home/chukyu/t-sim/src/sim430d/sim430d.c:314

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {3401} [PATH_VALID]
  - proof: openm(&fcb,SIM_DB=3401) at 313
- c-viz (row 2039): expr `&fcb` values {3401} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2039): expr `&fcb; SIM_DB` values {3401} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim430d/sim430d.c:476

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {3401} [PATH_VALID]
  - proof: openm(&fcb,SIM_DB) at 475
- c-viz (row 2040): expr `&fcb` values {3401} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2040): expr `&fcb; SIM_DB` values {3401} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim430d/sim430d.c:836

- Target: `q_no` arg 2 of `mpf_mfs_delque` (DELQUE); category cvisualizer_resolved_only
- Expected: {1105, 1106, 1107} [PATH_VALID]
  - proof: q_no=SIM_430DSEMQUENO_0/1/2 (1105/1106/1107) per Simpidx at :819-828
- c-viz (row 2495): expr `q_no` values {1106, 1107} statuses {"EXACT": 2} → **CORRECT_INCOMPLETE**
- legacy (row 2495): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: BRANCH_MERGE_ERROR | Confidence: high
- Note: c-viz misses 1105 (Simpidx==0 branch)

##### /home/chukyu/t-sim/src/sim430d/sim430d.c:881

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category both_unresolved
- Expected: {3429} [PATH_VALID]
  - proof: open(&fcb,SIM_SNDPARAM=3429) at 874 in sim430d_GetParam
- c-viz (row 2041): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2041): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim430d/sim430d.c:934

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3419} [PATH_VALID]
  - proof: openm(&fcb,SIM_NEDOGAINO=3419) at 928
- c-viz (row 2042): expr `&fcb` values {3419} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2042): expr `&fcb; SIM_NEDOGAINO` values {3419} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim440d

##### /home/chukyu/t-sim/src/sim440d/Sim440dGenHatuPos.c:130

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3435} [PATH_VALID]
  - proof: openm(&fcb,SIM_HATU_POS=3435) at 124
- c-viz (row 2043): expr `&fcb` values {3435} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2043): expr `&fcb; SIM_HATU_POS` values {3435} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim440d/sim440d.c:716

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3439} [PATH_VALID]
  - proof: openm(&fcb,SIM_ODO_TIME=3439) at 712
- c-viz (row 2044): expr `&fcb` values {3439} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2044): expr `&fcb; SIM_ODO_TIME` values {3439} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim440d/sim440d.c:860

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3435} [PATH_VALID]
  - proof: openm(&fcb,SIM_HATU_POS=3435) at 856
- c-viz (row 2045): expr `&fcb` values {3435} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2045): expr `&fcb; SIM_HATU_POS` values {3435} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim440d/sim440d.c:955

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {3401} [PATH_VALID]
  - proof: openm(&fcb,SIM_DB=3401) at 951
- c-viz (row 2046): expr `&fcb` values {3401} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2046): expr `&fcb; SIM_DB` values {3401} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim440d/sim440d.c:1087

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3439} [PATH_VALID]
  - proof: openm(&fcb,SIM_ODO_TIME) at 1083
- c-viz (row 2047): expr `&fcb` values {3439} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2047): expr `&fcb; SIM_ODO_TIME` values {3439} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim440d/sim440d.c:1096

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {3401} [PATH_VALID]
  - proof: openm(&fcb,SIM_DB) at 1092
- c-viz (row 2048): expr `&fcb` values {3401} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2048): expr `&fcb; SIM_DB` values {3401} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim499

##### /home/chukyu/t-sim/src/sim499/sim499.c:477

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3419} [PATH_VALID]
  - proof: openm(&fcb,SIM_NEDOGAINO=3419) at 476 in sim499_SndAddrChk
- c-viz (row 2049): expr `&fcb` values {3419} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2049): expr `&fcb; SIM_NEDOGAINO` values {3419} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim499/sim499.c:522

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3419} [PATH_VALID]
  - proof: openm(&fcb,SIM_NEDOGAINO=3419) at 521 in sim499_SndAddrSet
- c-viz (row 2050): expr `&fcb` values {3419} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2050): expr `&fcb; SIM_NEDOGAINO` values {3419} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim499/sim499.c:541

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {3419} [PATH_VALID]
  - proof: open at 521; close 542 after write
- c-viz (row 2051): expr `&fcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2051): expr `&fcb; SIM_NEDOGAINO` values {3419} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d

##### /home/chukyu/t-sim/src/sim510d/sim510d.c:634

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open(&fcb,SIM_OPIFNO=3408) at 626 in sim510d_ReDisp
- c-viz (row 2052): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2052): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d.c:848

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category equal
- Expected: {3411} [PATH_VALID]
  - proof: open(&fcb,SIM_KEN_EXEC=3411) at 841 in sim510d_Simkenclr
- c-viz (row 2053): expr `&fcb` values {3411} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2053): expr `&fcb; SIM_KEN_EXEC` values {3411} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d.c:882

- Target: `&ken_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3403} [PATH_VALID]
  - proof: open(&ken_fcb,SIM_KEN_LST=3403) at 875 in sim510d_listfile_make
- c-viz (row 2054): expr `&ken_fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2054): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d.c:945

- Target: `&fcb_shoki` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3430} [PATH_VALID]
  - proof: open(&fcb_shoki,SIM_SHOKI_SAVE=3430) at 936 in sim510dInitKeitou
- c-viz (row 2055): expr `&fcb_shoki` values {3430} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2055): expr `&fcb_shoki; SIM_SHOKI_SAVE` values {3430} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d.c:959

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB=3401) at 950 in sim510dInitKeitou
- c-viz (row 2056): expr `&fcb` values {3401} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2056): expr `&fcb; SIM_DB` values {3401} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_Choku.c:171

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open(&fcb,SIM_OPIFNO=3408) at 164 in sim510d_JEnd
- c-viz (row 2057): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2057): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_Gamen.c:600

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open(&fcb,SIM_OPIFNO) at 592 in sim510d_ChkSimOpIf
- c-viz (row 2058): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2058): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_Gamen.c:689

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {3408} [PATH_VALID]
  - proof: open at 592; fcb still open at 689
- c-viz (row 2059): expr `&fcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2059): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_Gamen.c:757

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open(&fcb,SIM_OPIFNO) at 749 in sim510d_ClrSimOpIf
- c-viz (row 2060): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2060): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_Gamen.c:845

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open at 749
- c-viz (row 2061): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2061): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_Gamen.c:1292

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open(&fcb,SIM_OPIFNO) at 1280 in sim510d_EndDisp
- c-viz (row 2062): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2062): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_Gamen.c:1348

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open at 1280
- c-viz (row 2063): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2063): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_HatuChoku.c:129

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open(&fcb,SIM_OPIFNO) at 122 in sim510d_HatuJEnd
- c-viz (row 2064): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2064): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim510d/sim510d_HatuChoku.c:270

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3408} [PATH_VALID]
  - proof: open(&fcb,SIM_OPIFNO) at 263 in sim510d_HatuJEnd2
- c-viz (row 2065): expr `&fcb` values {3408} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2065): expr `&fcb; SIM_OPIFNO` values {3408} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d

##### /home/chukyu/t-sim/src/sim520d/sim520d_HatuChoku.c:53

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3434} [PATH_VALID]
  - proof: open(&fcb,SIM_HATU_HEN=3434) at 46 in Sim520dGetHatuHen
- c-viz (row 2066): expr `&fcb` values {3434} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2066): expr `&fcb; SIM_HATU_HEN` values {3434} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_HatuChoku.c:337

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB=3401) at 333 in sim520d_HatuChoku
- c-viz (row 2067): expr `&fcb` values {3401} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2067): expr `&fcb; SIM_DB` values {3401} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_HatuChoku.c:429

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB) at 425 in sim520d_HatuChoku2
- c-viz (row 2068): expr `&fcb` values {3401} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2068): expr `&fcb; SIM_DB` values {3401} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Jikkou.c:400

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3411} [PATH_VALID]
  - proof: open(&fcb,SIM_KEN_EXEC=3411) at 395 in sim520d_Next_TejunData
- c-viz (row 2069): expr `&fcb` values {3411} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2069): expr `&fcb; SIM_KEN_EXEC` values {3411} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Jikkou.c:452

- Target: `&fcb2` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3403} [PATH_VALID]
  - proof: open(&fcb2,SIM_KEN_LST=3403) at 446
- c-viz (row 2070): expr `&fcb2` values {3403} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2070): expr `&fcb2; SIM_KEN_LST` values {3403} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Jikkou.c:469

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3411} [PATH_VALID]
  - proof: open(&fcb,SIM_KEN_EXEC) at 395
- c-viz (row 2071): expr `&fcb` values {3411} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2071): expr `&fcb; SIM_KEN_EXEC` values {3411} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Jikkou.c:505

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {3411} [PATH_VALID]
  - proof: open(&fcb,SIM_KEN_EXEC) at 499 in sim520d_StopJikkou
- c-viz (row 2072): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2072): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Jikkou.c:540

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3435} [PATH_VALID]
  - proof: openm(&fcb,SIM_HATU_POS=3435) at 536 in sim520d_Jikkou
- c-viz (row 2073): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2073): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Jikkou.c:594

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3411} [PATH_VALID]
  - proof: open(&fcb,SIM_KEN_EXEC) at 588 in sim520d_TimeOut
- c-viz (row 2074): expr `&fcb` values {3411} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2074): expr `&fcb; SIM_KEN_EXEC` values {3411} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Jikkou.c:854

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3411} [PATH_VALID]
  - proof: open(&fcb,SIM_KEN_EXEC) at 851 in SimSetTimeOut
- c-viz (row 2075): expr `&fcb` values {3411} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2075): expr `&fcb; SIM_KEN_EXEC` values {3411} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Jikkou.c:1459

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3432} [PATH_VALID]
  - proof: open(&fcb,SIM_TEJUN_SAVE=3432,subno) at 1454 in sim520d_GetTejun
- c-viz (row 2076): expr `&fcb` values {3432} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2076): expr `&fcb; SIM_TEJUN_SAVE` values {3432} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Shoki.c:88

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3430} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_SAVE=3430,ino-1) at 81 in sim520d_SetShoki
- c-viz (row 2077): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2077): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim520d/sim520d_Shoki.c:100

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB=3401) at 93 in sim520d_SetShoki
- c-viz (row 2078): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2078): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim530d

##### /home/chukyu/t-sim/src/sim530d/sim530d.c:835

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3403, 3404, 3406, 3407} [PATH_VALID]
  - proof: FileOpen callers: SIM_KEN_LST(3403):387/948/1114/1193; CopyTejun no=SIM_KEN_BUF(3406):507/559, SIM_TENKAI_BUF(3407):687, SIM_TEJUN(3404):737; SavTejun/GetKenBuf no param
- c-viz (row 2079): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2079): expr `fno` values {3403, 3404, 3406, 3407} statuses {"OK_MACRO": 4} → **CORRECT**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium
- Note: fno is FileOpen param; union over in-tree callers

##### /home/chukyu/t-sim/src/sim530d/sim530d.c:869

- Target: `&sim530d_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3403, 3404, 3406, 3407} [PATH_VALID]
  - proof: sim530d_fcb bound by FileOpen :835 (caller set above)
- c-viz (row 2080): expr `&sim530d_fcb` values {3403, 3404, 3406, 3407} statuses {"EXACT": 4} → **CORRECT**
- legacy (row 2080): expr `&sim530d_fcb; SIM_KEN_BUF; SIM_KEN_LST; SIM_TEJUN; SIM_TENKAI_BUF` values {3403, 3404, 3406, 3407} statuses {"ADDED": 4, "OK_MACRO": 4} → **CORRECT**
- Confidence: medium

##### /home/chukyu/t-sim/src/sim530d/sim530d.c:898

- Target: `&sim530d_fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3403, 3404, 3406, 3407} [PATH_VALID]
  - proof: same
- c-viz (row 2081): expr `&sim530d_fcb` values {3403, 3404, 3406, 3407} statuses {"EXACT": 4} → **CORRECT**
- legacy (row 2081): expr `&sim530d_fcb; SIM_KEN_BUF; SIM_KEN_LST; SIM_TEJUN; SIM_TENKAI_BUF` values {3403, 3404, 3406, 3407} statuses {"ADDED": 4, "OK_MACRO": 4} → **CORRECT**
- Confidence: medium

##### /home/chukyu/t-sim/src/sim530d/sim530d.c:1033

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3432} [PATH_VALID]
  - proof: open(&fcb,SIM_TEJUN_SAVE=3432,cp_subno) at 1028 in sim530d_CopyTejun
- c-viz (row 2082): expr `&fcb` values {3432} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2082): expr `&fcb; SIM_TEJUN_SAVE` values {3432} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim530d/sim530d.c:1079

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3432} [PATH_VALID]
  - proof: open(&fcb,SIM_TEJUN_SAVE,subno) at 1074 in sim530d_SavTejun
- c-viz (row 2083): expr `&fcb` values {3432} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2083): expr `&fcb; SIM_TEJUN_SAVE` values {3432} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim530d/sim530d.c:1426

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3431} [PATH_VALID]
  - proof: open(&fcb,SIM_TJN_SUBNO=3431) at 1421 in Sim530dGetTjnSubno
- c-viz (row 2084): expr `&fcb` values {3431} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2084): expr `&fcb; SIM_TJN_SUBNO` values {3431} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim530d/sim530d.c:1473

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3431} [PATH_VALID]
  - proof: open(&fcb,SIM_TJN_SUBNO) at 1468 in Sim530dEntTjnSubno
- c-viz (row 2085): expr `&fcb` values {3431} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2085): expr `&fcb; SIM_TJN_SUBNO` values {3431} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim530d/sim530d.c:1479

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3431} [PATH_VALID]
  - proof: open at 1468
- c-viz (row 2086): expr `&fcb` values {3431} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2086): expr `&fcb; SIM_TJN_SUBNO` values {3431} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim540d

##### /home/chukyu/t-sim/src/sim540d/sim540d.c:756

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3401, 3402, 3412} [PATH_VALID]
  - proof: FileOpen callers: SIM_SHOKI_LST(3402):968/1034/1313; SIM_SHOKI_ST(3412):1128/1262/1387; SIM_DB(3401):1383 (via GetKeitouBuf no param)
- c-viz (row 2087): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2087): expr `fno` values {3401, 3402, 3412} statuses {"OK_MACRO": 3} → **CORRECT**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium
- Note: plus runtime evtdat.no values (dynamic, not enumerated)

##### /home/chukyu/t-sim/src/sim540d/sim540d.c:789

- Target: `&sim540d_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3401, 3402, 3412} [PATH_VALID]
  - proof: sim540d_fcb bound by FileOpen :756
- c-viz (row 2088): expr `&sim540d_fcb` values {3401, 3402, 3412} statuses {"EXACT": 3} → **CORRECT**
- legacy (row 2088): expr `&sim540d_fcb; SIM_DB; SIM_SHOKI_LST; SIM_SHOKI_ST` values {3401, 3402, 3412} statuses {"ADDED": 3, "OK_MACRO": 3} → **CORRECT**
- Confidence: medium

##### /home/chukyu/t-sim/src/sim540d/sim540d.c:818

- Target: `&sim540d_fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3401, 3402, 3412} [PATH_VALID]
  - proof: same
- c-viz (row 2089): expr `&sim540d_fcb` values {3401, 3402, 3412} statuses {"EXACT": 3} → **CORRECT**
- legacy (row 2089): expr `&sim540d_fcb; SIM_DB; SIM_SHOKI_LST; SIM_SHOKI_ST` values {3401, 3402, 3412} statuses {"ADDED": 3, "OK_MACRO": 3} → **CORRECT**
- Confidence: medium

##### /home/chukyu/t-sim/src/sim540d/sim540d.c:1141

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3430} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_SAVE=3430,ino-1) at 1133 in sim540d_SavKeitou
- c-viz (row 2090): expr `&fcb` values {3430} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2090): expr `&fcb; SIM_SHOKI_SAVE` values {3430} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim540d/sim540d.c:1180

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3430} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_SAVE) at 1173 in sim540d_GetKeitou
- c-viz (row 2091): expr `&fcb` values {3430} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2091): expr `&fcb; SIM_SHOKI_SAVE` values {3430} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim540d/sim540d.c:1280

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3430} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_SAVE) at 1273 in sim540d_CreateKeitou
- c-viz (row 2092): expr `&fcb` values {3430} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2092): expr `&fcb; SIM_SHOKI_SAVE` values {3430} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560

##### /home/chukyu/t-sim/src/sim560/sim560.c:287

- Target: `&sim560_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3402} [PATH_VALID]
  - proof: open(&sim560_fcb,cpu,SIM_SHOKI_LST=3402) at 282 in sim560_ShokiChk
- c-viz (row 2093): expr `&sim560_fcb` values {3402} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2093): expr `&sim560_fcb; SIM_SHOKI_LST` values {3402} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:288

- Target: `&sim560_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3402} [PATH_VALID]
  - proof: same handle
- c-viz (row 2094): expr `&sim560_fcb` values {3402} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2094): expr `&sim560_fcb; SIM_SHOKI_LST` values {3402} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:400

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3430} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_SAVE=3430,ino) at 393 in sim560_ShokiRead
- c-viz (row 2095): expr `&fcb` values {3430} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2095): expr `&fcb; SIM_SHOKI_SAVE` values {3430} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:432

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3430} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_SAVE) at 426 in sim560_ShokiWrite
- c-viz (row 2096): expr `&fcb` values {3430} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2096): expr `&fcb; SIM_SHOKI_SAVE` values {3430} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:504

- Target: `&sim560_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3403} [PATH_VALID]
  - proof: open(&sim560_fcb,cpu,SIM_KEN_LST=3403) at 500 in sim560_KenLstRead
- c-viz (row 2097): expr `&sim560_fcb` values {3403} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2097): expr `&sim560_fcb; SIM_KEN_LST` values {3403} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:505

- Target: `&sim560_fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3403} [PATH_VALID]
  - proof: same handle
- c-viz (row 2098): expr `&sim560_fcb` values {3403} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2098): expr `&sim560_fcb; SIM_KEN_LST` values {3403} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:535

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3432} [PATH_VALID]
  - proof: open(&fcb,SIM_TEJUN_SAVE=3432,cnt) at 529 in sim560_TjnRead
- c-viz (row 2099): expr `&fcb` values {3432} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2099): expr `&fcb; SIM_TEJUN_SAVE` values {3432} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:536

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3432} [PATH_VALID]
  - proof: same handle
- c-viz (row 2100): expr `&fcb` values {3432} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2100): expr `&fcb; SIM_TEJUN_SAVE` values {3432} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:567

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3432} [PATH_VALID]
  - proof: open(&fcb,SIM_TEJUN_SAVE,cnt) at 561 in sim560_TjnWrite
- c-viz (row 2101): expr `&fcb` values {3432} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2101): expr `&fcb; SIM_TEJUN_SAVE` values {3432} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:569

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3432} [PATH_VALID]
  - proof: same handle
- c-viz (row 2102): expr `&fcb` values {3432} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2102): expr `&fcb; SIM_TEJUN_SAVE` values {3432} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:954

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category equal
- Expected: {3439} [PATH_VALID]
  - proof: openm(&fcb,SIM_ODO_TIME=3439) at 950 in sim560_OdoChk
- c-viz (row 2103): expr `&fcb` values {3439} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2103): expr `&fcb; SIM_ODO_TIME` values {3439} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim560/sim560.c:987

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {3439} [PATH_VALID]
  - proof: same handle
- c-viz (row 2104): expr `&fcb` values {3439} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2104): expr `&fcb; SIM_ODO_TIME` values {3439} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim570d

##### /home/chukyu/t-sim/src/sim570d/Sim570dEvt.c:323

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: openm(&fcb,SIM_DB=3401) at 311 in Sim570dSVNamaSet
- c-viz (row 2105): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2105): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/Sim570dEvt.c:365

- Target: `&fcb_shoki` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3430} [PATH_VALID]
  - proof: open(&fcb_shoki,SIM_SHOKI_SAVE=3430,ino-1) at 358 in Sim570dTMNamaSet
- c-viz (row 2106): expr `&fcb_shoki` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2106): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/Sim570dEvt.c:377

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB=3401) at 370 in Sim570dTMNamaSet
- c-viz (row 2107): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2107): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/Sim570dEvt.c:701

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: openm(&fcb,SIM_DB) at 695 in Sim570dEditDspSystem
- c-viz (row 2108): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2108): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/Sim570dEvt.c:775

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: openm(&fcb,SIM_DB) at 769 in Sim570dEditDspJohen
- c-viz (row 2109): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2109): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/Sim570dEvt.c:2281

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3419} [PATH_VALID]
  - proof: openm(&fcb,SIM_NEDOGAINO=3419) at 2277 in sim570dSndAddrChk
- c-viz (row 2110): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2110): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/SimDevFailS.c:62

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {3426} [PATH_VALID]
  - proof: openm(&fcb,SIM_DEVFAILSTATNO=3426) at 53 in SimGetDevFailStatus
- c-viz (row 2111): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2111): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/SimSoeQue.c:67

- Target: `SIM_SOEQUENO` arg 2 of `mpf_mfs_delque` (DELQUE); category both_unresolved
- Expected: {1102} [PATH_VALID]
  - proof: delque(NULL,SIM_SOEQUENO=1102) inline (SimSoeQue.h:24)
- c-viz (row 2496): expr `SIM_SOEQUENO` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2496): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/SimSoeQue.c:75

- Target: `SIM_SOEQUENO` arg 2 of `mpf_mfs_addque` (ADDQUE); category both_unresolved
- Expected: {1102} [PATH_VALID]
  - proof: addque(NULL,SIM_SOEQUENO=1102) inline
- c-viz (row 2497): expr `SIM_SOEQUENO` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2497): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim570d/SimStat0Ch.c:54

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {3427} [PATH_VALID]
  - proof: openm(&fcb,SIM_STAT0CHNO=3427) at 46 in SimGetStatus0Ch
- c-viz (row 2112): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2112): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim730

##### /home/chukyu/t-sim/src/sim730/sim730.c:682

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3403, 3411} [PATH_VALID]
  - proof: FileOpen callers: SIM_KEN_LST(3403) sim730.c:795; SIM_KEN_EXEC(3411) ken.c:496 con.c:203
- c-viz (row 2113): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2113): expr `fno` values {3403} statuses {"OK_MACRO": 1} → **CORRECT_INCOMPLETE**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium
- Note: legacy misses 3411

##### /home/chukyu/t-sim/src/sim730/sim730.c:697

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3403, 3411} [PATH_VALID]
  - proof: same caller set (hname variant)
- c-viz (row 2114): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2114): expr `fno` values {3403} statuses {"OK_MACRO": 1} → **CORRECT_INCOMPLETE**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium

##### /home/chukyu/t-sim/src/sim730/sim730.c:704

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3403, 3411} [PATH_VALID]
  - proof: same
- c-viz (row 2115): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2115): expr `fno` values {3403} statuses {"OK_MACRO": 1} → **CORRECT_INCOMPLETE**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium

##### /home/chukyu/t-sim/src/sim730/sim730.c:747

- Target: `rfcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3403, 3411} [PATH_VALID]
  - proof: rfcb = Simkenlist_fcb(3403, sim730.c:795-799) or Simkenexec_fcb(3411, ken.c:496-506 con.c:203-210)
- c-viz (row 2116): expr `rfcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2116): expr `rfcb` values {} statuses {"OK_CONST": 1} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium

##### /home/chukyu/t-sim/src/sim730/sim730.c:772

- Target: `wfcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {3411} [PATH_VALID]
  - proof: FileWrite only caller con.c:218 with Simkenexec_fcb (SIM_KEN_EXEC=3411)
- c-viz (row 2117): expr `wfcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2117): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium

##### /home/chukyu/t-sim/src/sim735

##### /home/chukyu/t-sim/src/sim735/sim735.c:1133

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3404, 3405, 3407} [PATH_VALID]
  - proof: FileOpen callers (tejun.c): SIM_KEN_DB(3405):1676, SIM_TENKAI_BUF(3407):1918, SIM_TEJUN(3404):1985/2034/2054
- c-viz (row 2118): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2118): expr `fno` values {3404, 3405} statuses {"OK_MACRO": 2} → **CORRECT_INCOMPLETE**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium
- Note: legacy misses 3407

##### /home/chukyu/t-sim/src/sim735/sim735.c:1145

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3404, 3405, 3407} [PATH_VALID]
  - proof: same (hname variant)
- c-viz (row 2119): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2119): expr `fno` values {3404, 3405} statuses {"OK_MACRO": 2} → **CORRECT_INCOMPLETE**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium

##### /home/chukyu/t-sim/src/sim735/sim735.c:1152

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3404, 3405, 3407} [PATH_VALID]
  - proof: same
- c-viz (row 2120): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2120): expr `fno` values {3404, 3405} statuses {"OK_MACRO": 2} → **CORRECT_INCOMPLETE**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium

##### /home/chukyu/t-sim/src/sim735/sim735.c:1198

- Target: `SIM_KEN_DB; SIM_TEJUN; rfcb` arg 1 of `mpf_mfs_readrecn` (READREC); category legacy_resolved_only
- Expected: {3404, 3405, 3407} [PATH_VALID]
  - proof: FileRead callers tejun.c:1684(3405)/1924(3407)/1990,2056(3404)
- c-viz (row 2121): expr `rfcb` values {} statuses {"UNRESOLVED": 2} → **UNDERAPPROXIMATION**
- legacy (row 2121): expr `SIM_KEN_DB; SIM_TEJUN; rfcb` values {3404, 3405} statuses {"ADDED": 2, "OK_CONST": 2} → **CORRECT_INCOMPLETE**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium

##### /home/chukyu/t-sim/src/sim735/sim735.c:1222

- Target: `SIM_KEN_DB; wfcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {3404, 3405} [PATH_VALID]
  - proof: FileWrite callers tejun.c:1704(3405)/2047(3404)
- c-viz (row 2122): expr `wfcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2122): expr `SIM_KEN_DB; wfcb` values {3405} statuses {"ADDED": 1, "OK_CONST": 1} → **CORRECT_INCOMPLETE**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium
- Note: legacy misses 3404

##### /home/chukyu/t-sim/src/sim740

##### /home/chukyu/t-sim/src/sim740/sim740.c:371

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3402} [PATH_VALID]
  - proof: sole in-tree caller sim740.c:456 passes SIM_SHOKI_LST=3402
- c-viz (row 2123): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2123): expr `fno` values {3402} statuses {"OK_MACRO": 1} → **CORRECT**
- Confidence: medium

##### /home/chukyu/t-sim/src/sim740/sim740.c:384

- Target: `fno` arg 3 of `mpf_mfs_open` (READ); category legacy_resolved_only
- Expected: {3402} [PATH_VALID]
  - proof: same caller (hname variant)
- c-viz (row 2124): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2124): expr `fno` values {3402} statuses {"OK_MACRO": 1} → **CORRECT**
- Confidence: medium

##### /home/chukyu/t-sim/src/sim740/sim740.c:431

- Target: `SIM_SHOKI_LST; fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category legacy_resolved_only
- Expected: {3402} [PATH_VALID]
  - proof: FileRead caller sim740.c:462 passes &Simshst_fcb (opened 456 with 3402)
- c-viz (row 2125): expr `fcb` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2125): expr `SIM_SHOKI_LST; fcb` values {3402} statuses {"ADDED": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: medium

##### /home/chukyu/t-sim/src/sim770

##### /home/chukyu/t-sim/src/sim770/sim770.c:712

- Target: `fno` arg 3 of `mpf_mfs_open` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: FileOpen has no in-tree caller
- c-viz (row 2126): expr `fno` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2126): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-sim/src/sim770/sim770.c:720

- Target: `fno` arg 3 of `mpf_mfs_open` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same
- c-viz (row 2127): expr `fno` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2127): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-sim/src/sim770/sim770.c:767

- Target: `fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: FileRead has no in-tree caller
- c-viz (row 2128): expr `fcb` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2128): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-sim/src/sim780

##### /home/chukyu/t-sim/src/sim780/sim780_cb.c:1023

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {3409} [PATH_VALID]
  - proof: open(&fcb,SIM_HENKOU=3409) at 955 in Sim780TCSVSimHenkou
- c-viz (row 2129): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2129): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim780/sim780_cb.c:1331

- Target: `&fcb` arg 1 of `mpf_mfs_writerec` (WRITEREC); category both_unresolved
- Expected: {3409} [PATH_VALID]
  - proof: open(&fcb,SIM_HENKOU) at 1203 in Sim780TCTMSimHenkou
- c-viz (row 2130): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2130): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim780/sim780_dtset.c:82

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category equal
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,SIM_DB=3401) at 68/76 (branch) in Sim780SimDbRead
- c-viz (row 2131): expr `&fcb` values {3401} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2131): expr `&fcb; SIM_DB` values {3401} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim780/sim780_dtset.c:128

- Target: `&fcb` arg 1 of `mpf_mfs_readrec` (READREC); category equal
- Expected: {3412} [PATH_VALID]
  - proof: open(&fcb,SIM_SHOKI_ST=3412) at 124 in Sim780SimShokiDbRead
- c-viz (row 2132): expr `&fcb` values {3412} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2132): expr `&fcb; SIM_SHOKI_ST` values {3412} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-sim/src/sim800

##### /home/chukyu/t-sim/src/sim800/sim800CtrlCB.c:157

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {3434} [PATH_VALID]
  - proof: open(&fcb,cpu,SIM_HATU_HEN=3434) at 152 in Sim800PushSettei
- c-viz (row 2133): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2133): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim800/sim800DrawCB.c:1008

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,cpu,SIM_DB=3401) at 997 in Sim800ReDraw
- c-viz (row 2134): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2134): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim800/sim800Start.c:166

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,cpu,SIM_DB=3401) at 162 in Sim800GetGmnDefData
- c-viz (row 2135): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2135): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim801

##### /home/chukyu/t-sim/src/sim801/sim801CtrlCB.c:138

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {3434} [PATH_VALID]
  - proof: open(&fcb,cpu,SIM_HATU_HEN=3434) at 133 in Sim801PushSettei
- c-viz (row 2136): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2136): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim801/sim801DrawCB.c:369

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,cpu,SIM_DB=3401) at 358 in Sim801ReDraw
- c-viz (row 2137): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2137): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim801/sim801Start.c:139

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: {3401} [PATH_VALID]
  - proof: open(&fcb,cpu,SIM_DB=3401) at 135 in Sim801GetGmnDefData
- c-viz (row 2138): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2138): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim810

##### /home/chukyu/t-sim/src/sim810/sim810Start.c:147

- Target: `(MPF_MFS_FCB *)&odo_time_fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: {3439} [PATH_VALID]
  - proof: open(&odo_time_fcb,cpu,SIM_ODO_TIME=3439) at 141 in sim810_write_data
- c-viz (row 2139): expr `(MPF_MFS_FCB *)&odo_time_fcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2139): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-sim/src/sim_set_kosho

##### /home/chukyu/t-sim/src/sim_set_kosho/sim_set_kosho.c:173

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category cvisualizer_resolved_only
- Expected: {3426} [PATH_VALID]
  - proof: openm(&fcb,SIM_DEVFAILSTATNO=3426) at 143 in write_id04_06
- c-viz (row 2140): expr `&fcb` values {3426} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2140): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/sim_set_kosho/sim_set_kosho.c:227

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category cvisualizer_resolved_only
- Expected: {3428} [PATH_VALID]
  - proof: openm(&fcb,SIM_STAT08HNO=3428) at 199 in write_id08
- c-viz (row 2141): expr `&fcb` values {3428} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2141): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/sim_set_kosho/sim_set_kosho.c:279

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category cvisualizer_resolved_only
- Expected: {3427} [PATH_VALID]
  - proof: openm(&fcb,SIM_STAT0CHNO=3427) at 262 in write_id0C
- c-viz (row 2142): expr `&fcb` values {3427} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2142): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-sim/src/sim_set_kosho/sim_set_kosho.c:527

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {3428} [PATH_VALID]
  - proof: openm(&fcb,SIM_STAT08HNO=3428) at 522 in send_packet08
- c-viz (row 2143): expr `&fcb` values {3428} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2143): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

#### t-svm/src

##### /home/chukyu/t-svm/src/libDac

##### /home/chukyu/t-svm/src/libDac/Dac_DelQue.c:85

- Target: `filenum` arg 2 of `mpf_mfs_delque` (DELQUE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: filenum param; no in-tree callers of Dac_DelQue
- c-viz (row 2498): expr `filenum` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2498): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-svm/src/libDac/Dac_DelQue.c:94

- Target: `filenum` arg 2 of `mpf_mfs_delque` (DELQUE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same
- c-viz (row 2499): expr `filenum` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2499): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-svm/src/libDac/Dac_EnqFork.c:122

- Target: `quename` arg 2 of `mpf_mfs_addque` (ADDQUE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: quename param; only caller is test tool svm_enqtest.c:956 passing SvmDenSlockQNo (undefined in active tree)
- c-viz (row 2500): expr `quename` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2500): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-svm/src/libDac/Dac_EnqSem.c:115

- Target: `fileno` arg 2 of `mpf_mfs_addque` (ADDQUE); category cvisualizer_resolved_only
- Expected: {845, 843, 844} [PATH_VALID]
  - proof: callers: svm600dMain.c:314 SvmTakeiSendQNo(845); SvmFLReport.c:69 SvmFLQNo(843); SvmKdcReport.c:77/89 SvmMISetQNo(844)
- c-viz (row 2501): expr `fileno` values {845} statuses {"EXACT": 1, "UNREACHABLE": 1} → **CORRECT_INCOMPLETE**
- legacy (row 2501): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_CALLER_EDGE | Confidence: medium
- Note: c-viz has 845 only

##### /home/chukyu/t-svm/src/libDac/Dac_EnqSem2.c:115

- Target: `fileno` arg 2 of `mpf_mfs_addque` (ADDQUE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: only caller svm200dTmm.c:80 is inside #ifdef TMM_NOP (inactive config) and passes TmmCbJyouhenQ (not defined in tree)
- c-viz (row 2502): expr `fileno` values {} statuses {"EXTERNAL": 1, "UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2502): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;PREPROCESSOR_CONFIGURATION | Confidence: low
- Note: CONFIG_VALID=TMM_NOP if that config were active

##### /home/chukyu/t-svm/src/libSvmManSt

##### /home/chukyu/t-svm/src/libSvmManSt/SvmManStReport.c:53

- Target: `SVM350` arg 1 of `pmf_forkproc_H` (FORKPROC); category both_unresolved
- Expected: {"svm350"} [PATH_VALID]
  - proof: pmf_forkproc_H(SVM350,...); SVM350="svm350" (SvmManStDspReq.h:39)
- c-viz (row 45): expr `SVM350` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 45): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high
- Note: FORKPROC proc-name literal

##### /home/chukyu/t-svm/src/libsvm

##### /home/chukyu/t-svm/src/libsvm/SvmOpReport.c:232

- Target: `proc_name` arg 1 of `pmf_forkproc_H` (FORKPROC); category both_unresolved
- Expected: {"svm600d"} [PATH_VALID]
  - proof: SvmForkProc callers :172/:190 both pass "svm600d"
- c-viz (row 46): expr `proc_name` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 46): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: MISSING_CALLER_EDGE;UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-svm/src/libsvmG

##### /home/chukyu/t-svm/src/libsvmG/SvmUtility.c:891

- Target: `file_no` arg 2 of `mpf_mfs_openm_H` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: file_no is SvmReadFile param; no in-tree callers
- c-viz (row 2144): expr `file_no` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2144): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-svm/src/libsvmG/SvmUtility.c:895

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb bound by open at 891 (caller param); no in-tree callers
- c-viz (row 2145): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2145): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/src/libsvmP

##### /home/chukyu/t-svm/src/libsvmP/SvmCtlCurVer.c:72

- Target: `&SvmCurVerFcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: {2650} [PATH_VALID]
  - proof: open(&SvmCurVerFcb,SvmCurVerNo=2650) at 68 in SvmGetCurVer (SvmFile.h:156)
- c-viz (row 2146): expr `&SvmCurVerFcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2146): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-svm/src/libsvmP/SvmCtlCurVer.c:125

- Target: `&SvmCurVerFcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: {2650} [PATH_VALID]
  - proof: open(&SvmCurVerFcb,SvmCurVerNo) at 121 in SvmSetCurVer
- c-viz (row 2147): expr `&SvmCurVerFcb` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2147): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-svm/src/libsvmP/SvmEnqFork.c:121

- Target: `quename` arg 2 of `mpf_mfs_addque` (ADDQUE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: quename param; no in-tree callers
- c-viz (row 2503): expr `quename` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2503): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-svm/src/libsvmP/SvmJikoku.c:685

- Target: `file_no` arg 2 of `mpf_mfs_openm_H` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: file_no param; no in-tree callers of this SvmReadFile
- c-viz (row 2148): expr `file_no` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2148): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;UNREACHABLE_ROOT_MODEL | Confidence: low

##### /home/chukyu/t-svm/src/libsvmP/SvmJikoku.c:689

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same
- c-viz (row 2149): expr `&fcb` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2149): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/src/libsvmP/SvmJyuteiden.c:207

- Target: `SvmJyuteiQNo` arg 2 of `mpf_mfs_addque` (ADDQUE); category both_unresolved
- Expected: {830} [PATH_VALID]
  - proof: addque(NULL,SvmJyuteiQNo=830) inline (Svm.h:61)
- c-viz (row 2504): expr `SvmJyuteiQNo` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2504): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-svm/src/libsvmskl_dlg

##### /home/chukyu/t-svm/src/libsvmskl_dlg/svmsklDlg02Main.c:176

- Target: `&fcb_cbry` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {2690} [PATH_VALID]
  - proof: openm_H(&fcb_cbry,SvmSklCbRyDefNo=2690) at 170 in ssklDlg02Init (SvmFile.h)
- c-viz (row 2150): expr `&fcb_cbry` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2150): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-svm/src/libsvmskl_dlg/svmsklDlg03Main.c:208

- Target: `SvmSklNrDefNo` arg 2 of `mpf_mfs_openm_H` (OPEN_LOCK); category both_unresolved
- Expected: {2691} [PATH_VALID]
  - proof: openm_H(&fcb_nr,SvmSklNrDefNo=2691) at 208 inline (SvmFile.h)
- c-viz (row 2151): expr `SvmSklNrDefNo` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2151): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-svm/src/libsvmskl_dlg/svmsklDlg03Main.c:215

- Target: `&fcb_nr` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: {2691} [PATH_VALID]
  - proof: open at 208; close 216
- c-viz (row 2152): expr `&fcb_nr` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2152): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-svm/src/svm000

##### /home/chukyu/t-svm/src/svm000/SvmBtnInt.c:326

- Target: `&fcb_def` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2640} [PATH_VALID]
  - proof: openm(&fcb_def,SvmRyDosaDefNo=2640) at 307 in SvmRydLamp
- c-viz (row 2153): expr `&fcb_def` values {2640} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2153): expr `&fcb_def; SvmRyDosaDefNo` values {2640} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/SvmBtnInt.c:327

- Target: `&fcb_res` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2641} [PATH_VALID]
  - proof: openm(&fcb_res,SvmRyDosaResNo=2641) at 315
- c-viz (row 2154): expr `&fcb_res` values {2641} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2154): expr `&fcb_res; SvmRyDosaResNo` values {2641} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/SvmBtnInt.c:361

- Target: `&fcb_def` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2640} [PATH_VALID]
  - proof: open at 307
- c-viz (row 2155): expr `&fcb_def` values {2640} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2155): expr `&fcb_def; SvmRyDosaDefNo` values {2640} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/SvmBtnInt.c:619

- Target: `&fcb_kkkt` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2670} [PATH_VALID]
  - proof: openm(&fcb_kkkt,SvmKKKTBtnDefNo=2670) at 605 in SvmKTBtnHantei
- c-viz (row 2156): expr `&fcb_kkkt` values {2670} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2156): expr `&fcb_kkkt; SvmKKKTBtnDefNo` values {2670} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/SvmBtnInt.c:774

- Target: `SvmLSKTBtnDefNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmLSKTBtnDefNo not defined in active tree
- c-viz (row 2157): expr `SvmLSKTBtnDefNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2157): expr `SvmLSKTBtnDefNo` values {} statuses {"OK_CONST": 1} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low
- Note: macro used, definition absent

##### /home/chukyu/t-svm/src/svm000/SvmBtnInt.c:782

- Target: `&fcb_lskt` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_lskt opened at 774 with undefined SvmLSKTBtnDefNo
- c-viz (row 2158): expr `&fcb_lskt` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2158): expr `&fcb_lskt` values {} statuses {"OK_CONST": 1} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/src/svm000/SvmBtnInt.c:836

- Target: `SvmRYKTBtnDefNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmRYKTBtnDefNo not defined in active tree
- c-viz (row 2159): expr `SvmRYKTBtnDefNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2159): expr `SvmRYKTBtnDefNo` values {} statuses {"OK_CONST": 1} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/src/svm000/SvmBtnInt.c:844

- Target: `&fcb_rykt` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_rykt opened at 836 with undefined SvmRYKTBtnDefNo
- c-viz (row 2160): expr `&fcb_rykt` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2160): expr `&fcb_rykt` values {} statuses {"OK_CONST": 1} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:197

- Target: `&fcb_res` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2641} [PATH_VALID]
  - proof: openm(&fcb_res,SvmRyDosaResNo=2641) at 187 in SvmRyDosaInt
- c-viz (row 2161): expr `&fcb_res` values {2641} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2161): expr `&fcb_res; SvmRyDosaResNo` values {2641} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:372

- Target: `&fcb_mng` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2612} [PATH_VALID]
  - proof: openm(&fcb_mng,SvmJikoMngNo=2612) at 338 in svm000FileIntJiko
- c-viz (row 2162): expr `&fcb_mng` values {2612} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2162): expr `&fcb_mng; SvmJikoMngNo` values {2612} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:377

- Target: `&fcb_list` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2613} [PATH_VALID]
  - proof: openm(&fcb_list,SvmJikoListNo=2613) at 346
- c-viz (row 2163): expr `&fcb_list` values {2613} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2163): expr `&fcb_list; SvmJikoListNo` values {2613} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:384

- Target: `&fcb_hzidx` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2651} [PATH_VALID]
  - proof: openm(&fcb_hzidx,SvmHozonIdxNo=2651) at 354
- c-viz (row 2164): expr `&fcb_hzidx` values {2651} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2164): expr `&fcb_hzidx; SvmHozonIdxNo` values {2651} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:385

- Target: `&fcb_hzn` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2652} [PATH_VALID]
  - proof: openm(&fcb_hzn,SvmCurHozonNo=2652) at 362
- c-viz (row 2165): expr `&fcb_hzn` values {2652} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2165): expr `&fcb_hzn; SvmCurHozonNo` values {2652} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:404

- Target: `&fcb_list` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2613} [PATH_VALID]
  - proof: open at 346
- c-viz (row 2166): expr `&fcb_list` values {2613} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2166): expr `&fcb_list; SvmJikoListNo` values {2613} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:436

- Target: `&fcb_mng` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2612} [PATH_VALID]
  - proof: open at 338
- c-viz (row 2167): expr `&fcb_mng` values {2612} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2167): expr `&fcb_mng; SvmJikoMngNo` values {2612} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:451

- Target: `&fcb_mng` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2612} [PATH_VALID]
  - proof: open at 338
- c-viz (row 2168): expr `&fcb_mng` values {2612} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2168): expr `&fcb_mng; SvmJikoMngNo` values {2612} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:470

- Target: `&fcb_mng` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2612} [PATH_VALID]
  - proof: open at 338
- c-viz (row 2169): expr `&fcb_mng` values {2612} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2169): expr `&fcb_mng; SvmJikoMngNo` values {2612} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:476

- Target: `&fcb_mng` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2612} [PATH_VALID]
  - proof: open at 338
- c-viz (row 2170): expr `&fcb_mng` values {2612} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2170): expr `&fcb_mng; SvmJikoMngNo` values {2612} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:895

- Target: `&fcb_kansimng` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {2622} [PATH_VALID]
  - proof: openm(&fcb_kansimng,SvmKansiMngNo=2622) at 799 in svm000FileIntKansiJiko
- c-viz (row 2171): expr `&fcb_kansimng` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2171): expr `&fcb_kansimng; SvmKansiMngNo` values {2622} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:906

- Target: `&fcb_kansilist` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {2623} [PATH_VALID]
  - proof: openm(&fcb_kansilist,SvmKansiListNo=2623) at 807
- c-viz (row 2172): expr `&fcb_kansilist` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2172): expr `&fcb_kansilist; SvmKansiListNo` values {2623} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:907

- Target: `&fcb_cbrcls` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category legacy_resolved_only
- Expected: {2624} [PATH_VALID]
  - proof: openm(&fcb_cbrcls,SvmCBRclsKnrNo=2624) at 816
- c-viz (row 2173): expr `&fcb_cbrcls` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2173): expr `&fcb_cbrcls; SvmCBRclsKnrNo` values {2624} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:908

- Target: `&fcb_soujuyo` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category legacy_resolved_only
- Expected: {2628} [PATH_VALID]
  - proof: openm(&fcb_soujuyo,SvmSojuyoNo=2628) at 826
- c-viz (row 2174): expr `&fcb_soujuyo` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2174): expr `&fcb_soujuyo; SvmSojuyoNo` values {2628} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:909

- Target: `&fcb_jkrcls` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {2625} [PATH_VALID]
  - proof: openm(&fcb_jkrcls,SvmJKRclsKnrNo=2625) at 837
- c-viz (row 2175): expr `&fcb_jkrcls` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2175): expr `&fcb_jkrcls; SvmJKRclsKnrNo` values {2625} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:910

- Target: `&fcb_jkjokyo` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {2626} [PATH_VALID]
  - proof: openm(&fcb_jkjokyo,SvmJKJokyoKnrNo=2626) at 849
- c-viz (row 2176): expr `&fcb_jkjokyo` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2176): expr `&fcb_jkjokyo; SvmJKJokyoKnrNo` values {2626} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:911

- Target: `&fcb_teiden` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {2627} [PATH_VALID]
  - proof: openm(&fcb_teiden,SvmTeidenNo=2627) at 862
- c-viz (row 2177): expr `&fcb_teiden` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2177): expr `&fcb_teiden; SvmTeidenNo` values {2627} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:912

- Target: `&fcb_jkhantei` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category equal
- Expected: {2629} [PATH_VALID]
  - proof: openm(&fcb_jkhantei,SvmJKHanteiNo=2629) at 876
- c-viz (row 2178): expr `&fcb_jkhantei` values {2629} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2178): expr `&fcb_jkhantei; SvmJKHanteiNo` values {2629} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:920

- Target: `&fcb_kansistat` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category legacy_resolved_only
- Expected: {2621} [PATH_VALID]
  - proof: openm(&fcb_kansistat,SvmKansiStatNo=2621) at 792
- c-viz (row 2179): expr `&fcb_kansistat` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2179): expr `&fcb_kansistat; SvmKansiStatNo` values {2621} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:924

- Target: `&fcb_kansimng` arg 1 of `mpf_mfs_readrecn` (READREC); category legacy_resolved_only
- Expected: {2622} [PATH_VALID]
  - proof: open at 799
- c-viz (row 2180): expr `&fcb_kansimng` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2180): expr `&fcb_kansimng; SvmKansiMngNo` values {2622} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:925

- Target: `&fcb_kansilist` arg 1 of `mpf_mfs_readrecn` (READREC); category legacy_resolved_only
- Expected: {2623} [PATH_VALID]
  - proof: open at 807
- c-viz (row 2181): expr `&fcb_kansilist` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2181): expr `&fcb_kansilist; SvmKansiListNo` values {2623} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000FileInt.c:954

- Target: `&fcb_kansilist` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category legacy_resolved_only
- Expected: {2623} [PATH_VALID]
  - proof: open at 807
- c-viz (row 2182): expr `&fcb_kansilist` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2182): expr `&fcb_kansilist; SvmKansiListNo` values {2623} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000JidoMnt.c:92

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2611} [PATH_VALID]
  - proof: openm(&fcb,SvmJikoKenmeiNo=2611) at 86 in SvmJidoMnt
- c-viz (row 2183): expr `&fcb` values {2611} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2183): expr `&fcb; SvmJikoKenmeiNo` values {2611} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000JidoMnt.c:103

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2651} [PATH_VALID]
  - proof: openm(&fcb,SvmHozonIdxNo=2651) at 97 (re-open, fcb closed between)
- c-viz (row 2184): expr `&fcb` values {2651} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2184): expr `&fcb; SvmHozonIdxNo` values {2651} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000JidoMnt.c:115

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2652} [PATH_VALID]
  - proof: openm(&fcb,SvmCurHozonNo=2652) at 109
- c-viz (row 2185): expr `&fcb` values {2652} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2185): expr `&fcb; SvmCurHozonNo` values {2652} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000JuteiSet.c:119

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2632} [PATH_VALID]
  - proof: openm(&fcb,SvmJyuteiZMngNo=2632) at 93 in SvmJuteiSet
- c-viz (row 2186): expr `&fcb` values {2632} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2186): expr `&fcb; SvmJyuteiZMngNo` values {2632} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000MentInt.c:124

- Target: `&d_fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2699} [PATH_VALID]
  - proof: openm(&d_fcb,SvmDacJyosuDefNo=2699) at 122 in SvmMentJyuInt
- c-viz (row 2187): expr `&d_fcb` values {2699} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2187): expr `&d_fcb; SvmDacJyosuDefNo` values {2699} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000MentInt.c:131

- Target: `&j_fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2631} [PATH_VALID]
  - proof: openm(&j_fcb,SvmJyuteiMngNo=2631) at 128
- c-viz (row 2188): expr `&j_fcb` values {2631} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2188): expr `&j_fcb; SvmJyuteiMngNo` values {2631} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000MentInt.c:138

- Target: `SvmJyuteiQNo` arg 2 of `mpf_mfs_addque` (ADDQUE); category legacy_resolved_only
- Expected: {830} [PATH_VALID]
  - proof: addque(NULL,SvmJyuteiQNo=830) inline (Svm.h:61)
- c-viz (row 2505): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2505): expr `SvmJyuteiQNo` values {830} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000MentInt.c:226

- Target: `&d_fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2699} [PATH_VALID]
  - proof: openm(&d_fcb,SvmDacJyosuDefNo) at 225 in SvmMentJyuInt_1to2
- c-viz (row 2189): expr `&d_fcb` values {2699} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2189): expr `&d_fcb; SvmDacJyosuDefNo` values {2699} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000MentInt.c:240

- Target: `&j_fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2631} [PATH_VALID]
  - proof: openm(&j_fcb,SvmJyuteiMngNo) at 239
- c-viz (row 2190): expr `&j_fcb` values {2631} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2190): expr `&j_fcb; SvmJyuteiMngNo` values {2631} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000MentInt.c:253

- Target: `SvmJyuteiQNo` arg 2 of `mpf_mfs_addque` (ADDQUE); category legacy_resolved_only
- Expected: {830} [PATH_VALID]
  - proof: addque(NULL,SvmJyuteiQNo=830) inline
- c-viz (row 2506): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2506): expr `SvmJyuteiQNo` values {830} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:149

- Target: `&fcb_list` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoSendInt is static; all call sites (:96-99) commented out -> DEAD_PATH
- c-viz (row 2191): expr `&fcb_list` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2191): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;UNREACHABLE_ROOT_MODEL | Confidence: medium
- Note: fcb_list would be SvmJikoListNo=2613 (open 311) but no active path

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:199

- Target: `&fcb_list` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: DEAD_PATH (static fn, callers commented)
- c-viz (row 2192): expr `&fcb_list` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2192): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;UNREACHABLE_ROOT_MODEL | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:228

- Target: `&fcb_syun` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSyunSendInt static, callers commented -> DEAD_PATH
- c-viz (row 2193): expr `&fcb_syun` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2193): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;UNREACHABLE_ROOT_MODEL | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:252

- Target: `&fcb_syun` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: DEAD_PATH
- c-viz (row 2194): expr `&fcb_syun` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2194): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;UNREACHABLE_ROOT_MODEL | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:299

- Target: `SvmJikoStatNo` arg 3 of `mpf_mfs_openm` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoOpenInt static, callers commented -> DEAD_PATH; SvmJikoStatNo also undefined in tree
- c-viz (row 2195): expr `SvmJikoStatNo` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2195): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;INSUFFICIENT_EVIDENCE | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:324

- Target: `SvmJikoSfNo` arg 3 of `mpf_mfs_openm` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: DEAD_PATH; SvmJikoSfNo undefined
- c-viz (row 2196): expr `SvmJikoSfNo` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2196): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;INSUFFICIENT_EVIDENCE | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:338

- Target: `SvmKyoukyuNo` arg 3 of `mpf_mfs_openm` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: DEAD_PATH; SvmKyoukyuNo undefined
- c-viz (row 2197): expr `SvmKyoukyuNo` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2197): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;INSUFFICIENT_EVIDENCE | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:353

- Target: `SvmHatudenNo` arg 3 of `mpf_mfs_openm` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: DEAD_PATH; SvmHatudenNo undefined
- c-viz (row 2198): expr `SvmHatudenNo` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2198): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;INSUFFICIENT_EVIDENCE | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:439

- Target: `SvmSyunTeiMngNo` arg 3 of `mpf_mfs_openm` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSyunOpenInt static, callers commented -> DEAD_PATH; SvmSyunTeiMngNo undefined
- c-viz (row 2199): expr `SvmSyunTeiMngNo` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2199): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;INSUFFICIENT_EVIDENCE | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:450

- Target: `SvmSyunStatNo` arg 3 of `mpf_mfs_openm` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: DEAD_PATH; SvmSyunStatNo undefined
- c-viz (row 2200): expr `SvmSyunStatNo` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2200): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;INSUFFICIENT_EVIDENCE | Confidence: medium

##### /home/chukyu/t-svm/src/svm000/svm000SendInt.c:462

- Target: `SvmSyunTeiNo` arg 3 of `mpf_mfs_openm` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: DEAD_PATH; SvmSyunTeiNo undefined
- c-viz (row 2201): expr `SvmSyunTeiNo` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2201): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: DEAD_PATH;INSUFFICIENT_EVIDENCE | Confidence: medium

##### /home/chukyu/t-svm/src/svm100d

##### /home/chukyu/t-svm/src/svm100d/svm100dMain.c:1078

- Target: `SvmInitialMPQNo` arg 2 of `mpf_mfs_addque` (ADDQUE); category legacy_resolved_only
- Expected: {866} [PATH_VALID]
  - proof: addque(NULL,SvmInitialMPQNo=866) inline (SvmFile.h)
- c-viz (row 2507): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2507): expr `SvmInitialMPQNo` values {866} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm101d

##### /home/chukyu/t-svm/src/svm101d/svm101dMain.c:872

- Target: `SvmInitialMPQNo` arg 2 of `mpf_mfs_addque` (ADDQUE); category both_unresolved
- Expected: {866} [PATH_VALID]
  - proof: addque(NULL,SvmInitialMPQNo=866) inline
- c-viz (row 2508): expr `SvmInitialMPQNo` values {} statuses {"UNREACHABLE": 1} → **UNDERAPPROXIMATION**
- legacy (row 2508): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high

##### /home/chukyu/t-svm/src/svm200d

##### /home/chukyu/t-svm/src/svm200d/svm200dJyohen.c:147

- Target: `SvmSVRcvQNo` arg 2 of `mpf_mfs_delque` (DELQUE); category legacy_resolved_only
- Expected: {801} [PATH_VALID]
  - proof: delque(NULL,SvmSVRcvQNo=801) inline (SvmFile.h)
- c-viz (row 2509): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2509): expr `SvmSVRcvQNo` values {801} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dMain.c:93

- Target: `&fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2699} [PATH_VALID]
  - proof: openm(&fcb,SvmDacJyosuDefNo=2699) at 89 in main
- c-viz (row 2202): expr `&fcb` values {2699} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2202): expr `&fcb; SvmDacJyosuDefNo` values {2699} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dRyHold.c:175

- Target: `&fcb_ryhold` arg 1 of `mpf_mfs_getrecm` (GETREC); category legacy_resolved_only
- Expected: {2601} [PATH_VALID]
  - proof: openm(&fcb_ryhold,SvmRYHoldKanriNo=2601) at 70 (module init, static fcb)
- c-viz (row 2203): expr `&fcb_ryhold` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2203): expr `&fcb_ryhold; SvmRYHoldKanriNo` values {2601} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dRyHold.c:178

- Target: `&fcb_ryfukki` arg 1 of `mpf_mfs_getrecm` (GETREC); category legacy_resolved_only
- Expected: {2602} [PATH_VALID]
  - proof: openm(&fcb_ryfukki,SvmRYFukkiKanriNo=2602) at 77
- c-viz (row 2204): expr `&fcb_ryfukki` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2204): expr `&fcb_ryfukki; SvmRYFukkiKanriNo` values {2602} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dRyHold.c:238

- Target: `SvmRYHoldQNo` arg 2 of `mpf_mfs_addque` (ADDQUE); category legacy_resolved_only
- Expected: {803} [PATH_VALID]
  - proof: addque(NULL,SvmRYHoldQNo=803) inline
- c-viz (row 2510): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2510): expr `SvmRYHoldQNo` values {803} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dRyHold.c:292

- Target: `SvmRYHoldQNo` arg 2 of `mpf_mfs_addque` (ADDQUE); category legacy_resolved_only
- Expected: {803} [PATH_VALID]
  - proof: addque(NULL,SvmRYHoldQNo=803) inline
- c-viz (row 2511): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2511): expr `SvmRYHoldQNo` values {803} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dRyHold.c:319

- Target: `&fcb_ryfukki` arg 1 of `mpf_mfs_getrecm` (GETREC); category legacy_resolved_only
- Expected: {2602} [PATH_VALID]
  - proof: fcb_ryfukki (open 77, SvmRYFukkiKanriNo=2602)
- c-viz (row 2205): expr `&fcb_ryfukki` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2205): expr `&fcb_ryfukki; SvmRYFukkiKanriNo` values {2602} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dRyHold.c:401

- Target: `&fcb_ryhold` arg 1 of `mpf_mfs_getrecm` (GETREC); category legacy_resolved_only
- Expected: {2601} [PATH_VALID]
  - proof: fcb_ryhold (open 70, 2601)
- c-viz (row 2206): expr `&fcb_ryhold` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2206): expr `&fcb_ryhold; SvmRYHoldKanriNo` values {2601} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dRyHold.c:404

- Target: `&fcb_ryfukki` arg 1 of `mpf_mfs_getrecm` (GETREC); category legacy_resolved_only
- Expected: {2602} [PATH_VALID]
  - proof: fcb_ryfukki (open 77, 2602)
- c-viz (row 2207): expr `&fcb_ryfukki` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- legacy (row 2207): expr `&fcb_ryfukki; SvmRYFukkiKanriNo` values {2602} statuses {"ALREADY_PRESENT": 1, "OK_CONST": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm200d/svm200dRyHold.c:564

- Target: `SvmRYTienQNo` arg 2 of `mpf_mfs_addque` (ADDQUE); category legacy_resolved_only
- Expected: {804} [PATH_VALID]
  - proof: addque(NULL,SvmRYTienQNo=804) inline
- c-viz (row 2512): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2512): expr `SvmRYTienQNo` values {804} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm500d

##### /home/chukyu/t-svm/src/svm500d/svm500Main.c:180

- Target: `SvmTakeiSendQNo` arg 2 of `mpf_mfs_delque` (DELQUE); category legacy_resolved_only
- Expected: {845} [PATH_VALID]
  - proof: delque(NULL,SvmTakeiSendQNo=845) inline in svm500dDivide
- c-viz (row 2513): expr `` values {} statuses {} → **UNDERAPPROXIMATION**
- legacy (row 2513): expr `SvmTakeiSendQNo` values {845} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm500d/svm500Main.c:217

- Target: `rcpuname` arg 1 of `pmf_forkprocbs_H` (FORKPROC); category both_unresolved
- Expected: {"ECS-A", "ECS-B"} [PATH_VALID]
  - proof: rcpuname set at :154 ("ECS-B") / :158 ("ECS-A") in svm500dDivide
- c-viz (row 47): expr `rcpuname` values {} statuses {"EXTERNAL": 1} → **UNDERAPPROXIMATION**
- legacy (row 47): expr `rcpuname` values {} statuses {"UNRESOLVED": 1} → **UNDERAPPROXIMATION**
- Cause tags: UNREACHABLE_ROOT_MODEL | Confidence: high
- Note: FORKPROC proc name; two config branches

##### /home/chukyu/t-svm/src/svm620

##### /home/chukyu/t-svm/src/svm620/svm620Main.c:116

- Target: `&SvmCurVerFcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2650} [PATH_VALID]
  - proof: open(&SvmCurVerFcb,SvmCurVerNo=2650) at 114 in main
- c-viz (row 2208): expr `&SvmCurVerFcb` values {2650} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2208): expr `&SvmCurVerFcb; SvmCurVerNo` values {2650} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

##### /home/chukyu/t-svm/src/svm620/svm620Main.c:184

- Target: `&SvmCurVerFcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category equal
- Expected: {2650} [PATH_VALID]
  - proof: open(&SvmCurVerFcb,SvmCurVerNo) at 183
- c-viz (row 2209): expr `&SvmCurVerFcb` values {2650} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2209): expr `&SvmCurVerFcb; SvmCurVerNo` values {2650} statuses {"ADDED": 1, "OK_MACRO": 1} → **CORRECT**
- Confidence: high

#### t-svm/tool

##### /home/chukyu/t-svm/tool/IWATE/svmcspcdmp

##### /home/chukyu/t-svm/tool/IWATE/svmcspcdmp/svmcspcdmp.c:104

- Target: `SvmCspcDefNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmCspcDefNo not defined in active tree
- c-viz (row 2210): expr `SvmCspcDefNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2210): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmcspcdmp/svmcspcdmp.c:112

- Target: `&fcb_cspcdef` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_cspcdef opened at 104 with undefined macro
- c-viz (row 2211): expr `&fcb_cspcdef` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2211): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmcspcdmp/svmcspcdmp.c:233

- Target: `SvmSyunCyouDefNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSyunCyouDefNo not defined in active tree
- c-viz (row 2212): expr `SvmSyunCyouDefNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2212): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmcspcdmp/svmcspcdmp.c:241

- Target: `&fcb_cyoudef` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_cyoudef opened at 233 with undefined macro
- c-viz (row 2213): expr `&fcb_cyoudef` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2213): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:149

- Target: `&fcb_cbdef` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2603} [PATH_VALID]
  - proof: openm(&fcb_cbdef,SvmCBKumiDefNo=2603) at 143 in jiko_dmp
- c-viz (row 2214): expr `&fcb_cbdef` values {2603} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2214): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:150

- Target: `&fcb_cbrydef` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2605} [PATH_VALID]
  - proof: openm(&fcb_cbrydef,SvmCBRYDefNo=2605) at 144
- c-viz (row 2215): expr `&fcb_cbrydef` values {2605} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2215): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:151

- Target: `&fcb_scbrydef` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2607} [PATH_VALID]
  - proof: openm(&fcb_scbrydef,SvmSCBRYDefNo=2607) at 145
- c-viz (row 2216): expr `&fcb_scbrydef` values {2607} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2216): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:152

- Target: `&fcb_rydef` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2604} [PATH_VALID]
  - proof: openm(&fcb_rydef,SvmRYKumiDefNo=2604) at 146
- c-viz (row 2217): expr `&fcb_rydef` values {2604} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2217): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:153

- Target: `&fcb_rycbdef` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2606} [PATH_VALID]
  - proof: openm(&fcb_rycbdef,SvmRYCBDefNo=2606) at 147
- c-viz (row 2218): expr `&fcb_rycbdef` values {2606} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2218): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:154

- Target: `&fcb_srycbdef` arg 1 of `mpf_mfs_getrecm` (GETREC); category cvisualizer_resolved_only
- Expected: {2608} [PATH_VALID]
  - proof: openm(&fcb_srycbdef,SvmSRYCBDefNo=2608) at 148
- c-viz (row 2219): expr `&fcb_srycbdef` values {2608} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2219): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:425

- Target: `SvmKyoSishoTMNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmKyoSishoTMNo not defined in active tree
- c-viz (row 2220): expr `SvmKyoSishoTMNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2220): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:426

- Target: `SvmHatSishoTMNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmHatSishoTMNo not defined in active tree
- c-viz (row 2221): expr `SvmHatSishoTMNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2221): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:427

- Target: `&fcb_kyotm` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_kyotm opened at 425 with undefined macro
- c-viz (row 2222): expr `&fcb_kyotm` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2222): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:428

- Target: `&fcb_hattm` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_hattm opened at 426 with undefined macro
- c-viz (row 2223): expr `&fcb_hattm` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2223): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:642

- Target: `SvmSWKumiDefNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSWKumiDefNo not defined in active tree
- c-viz (row 2224): expr `SvmSWKumiDefNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2224): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:643

- Target: `SvmSWRYDefNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSWRYDefNo not defined in active tree
- c-viz (row 2225): expr `SvmSWRYDefNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2225): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:644

- Target: `&fcb_swdef` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_swdef opened at 642 with undefined macro
- c-viz (row 2226): expr `&fcb_swdef` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2226): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:645

- Target: `&fcb_swrydef` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_swrydef opened at 643 with undefined macro
- c-viz (row 2227): expr `&fcb_swrydef` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2227): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:791

- Target: `SvmCspcDefNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmCspcDefNo not defined in active tree
- c-viz (row 2228): expr `SvmCspcDefNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2228): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:792

- Target: `&fcb_cspc` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_cspc opened at 791 with undefined macro
- c-viz (row 2229): expr `&fcb_cspc` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2229): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:940

- Target: `SvmSyunCyouDefNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSyunCyouDefNo not defined in active tree
- c-viz (row 2230): expr `SvmSyunCyouDefNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2230): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmdmp/svmdmp.c:941

- Target: `&fcb_syun` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_syun opened at 940 with undefined macro
- c-viz (row 2231): expr `&fcb_syun` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2231): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmjimset

##### /home/chukyu/t-svm/tool/IWATE/svmjimset/svmjimset.c:114

- Target: `&fcb_kmng` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2612} [PATH_VALID]
  - proof: openm(&fcb_kmng,SvmJikoMngNo=2612) at 160 (SvmJikoOpenInt, called at 108)
- c-viz (row 2232): expr `&fcb_kmng` values {2612} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2232): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmjimset/svmjimset.c:119

- Target: `&fcb_list` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2613} [PATH_VALID]
  - proof: openm(&fcb_list,SvmJikoListNo=2613) at 176
- c-viz (row 2233): expr `&fcb_list` values {2613} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2233): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmjimset/svmjimset.c:133

- Target: `&fcb_list` arg 1 of `mpf_mfs_writerecm` (WRITEREC); category cvisualizer_resolved_only
- Expected: {2613} [PATH_VALID]
  - proof: open at 176
- c-viz (row 2234): expr `&fcb_list` values {2613} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2234): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmjimset/svmjimset.c:168

- Target: `SvmJikoStatNo` arg 3 of `mpf_mfs_openm` (WRITE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoStatNo not defined in active tree
- c-viz (row 2235): expr `SvmJikoStatNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2235): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmjimset/svmjimset.c:184

- Target: `SvmJikoSfNo` arg 3 of `mpf_mfs_openm` (WRITE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoSfNo not defined in active tree
- c-viz (row 2236): expr `SvmJikoSfNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2236): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmjimset/svmjimset.c:192

- Target: `SvmKyoukyuNo` arg 3 of `mpf_mfs_openm` (WRITE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmKyoukyuNo not defined in active tree
- c-viz (row 2237): expr `SvmKyoukyuNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2237): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmjimset/svmjimset.c:200

- Target: `SvmHatudenNo` arg 3 of `mpf_mfs_openm` (WRITE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmHatudenNo not defined in active tree
- c-viz (row 2238): expr `SvmHatudenNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2238): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmrecdmp

##### /home/chukyu/t-svm/tool/IWATE/svmrecdmp/svmrecdmp.c:108

- Target: `&fcb_kmng` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2612} [PATH_VALID]
  - proof: openm(&fcb_kmng,SvmJikoMngNo=2612) at 320 (SvmJikoOpenInt)
- c-viz (row 2239): expr `&fcb_kmng` values {2612} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2239): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmrecdmp/svmrecdmp.c:117

- Target: `&fcb_sf` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb_sf opened at 344 with undefined SvmJikoSfNo
- c-viz (row 2240): expr `&fcb_sf` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2240): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmrecdmp/svmrecdmp.c:328

- Target: `SvmJikoStatNo` arg 3 of `mpf_mfs_openm` (WRITE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoStatNo not defined
- c-viz (row 2241): expr `SvmJikoStatNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2241): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmrecdmp/svmrecdmp.c:344

- Target: `SvmJikoSfNo` arg 3 of `mpf_mfs_openm` (WRITE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoSfNo not defined
- c-viz (row 2242): expr `SvmJikoSfNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2242): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmrecdmp/svmrecdmp.c:352

- Target: `SvmKyoukyuNo` arg 3 of `mpf_mfs_openm` (WRITE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmKyoukyuNo not defined
- c-viz (row 2243): expr `SvmKyoukyuNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2243): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmrecdmp/svmrecdmp.c:360

- Target: `SvmHatudenNo` arg 3 of `mpf_mfs_openm` (WRITE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmHatudenNo not defined
- c-viz (row 2244): expr `SvmHatudenNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2244): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:63

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2603} [PATH_VALID]
  - proof: openm(&fcb,SvmCBKumiDefNo=2603) at 57 in svm2703file
- c-viz (row 2245): expr `&fcb` values {2603} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2245): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:79

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2605} [PATH_VALID]
  - proof: openm(&fcb,SvmCBRYDefNo=2605) at 73
- c-viz (row 2246): expr `&fcb` values {2605} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2246): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:110

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2607} [PATH_VALID]
  - proof: openm(&fcb,SvmSCBRYDefNo=2607) at 105
- c-viz (row 2247): expr `&fcb` values {2607} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2247): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:196

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2604} [PATH_VALID]
  - proof: openm(&fcb,SvmRYKumiDefNo=2604) at 190 in svm2704file
- c-viz (row 2248): expr `&fcb` values {2604} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2248): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:212

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2606} [PATH_VALID]
  - proof: openm(&fcb,SvmRYCBDefNo=2606) at 206
- c-viz (row 2249): expr `&fcb` values {2606} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2249): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:243

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category cvisualizer_resolved_only
- Expected: {2608} [PATH_VALID]
  - proof: openm(&fcb,SvmSRYCBDefNo=2608) at 238
- c-viz (row 2250): expr `&fcb` values {2608} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2250): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:328

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category cvisualizer_resolved_only
- Expected: {2612} [PATH_VALID]
  - proof: openm(&fcb,SvmJikoMngNo=2612) at 323 in svm2753file
- c-viz (row 2251): expr `&fcb` values {2612} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2251): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:504

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category cvisualizer_resolved_only
- Expected: {2613} [PATH_VALID]
  - proof: openm(&fcb,SvmJikoListNo=2613) at 499 in svmJikoList_prt
- c-viz (row 2252): expr `&fcb` values {2613} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2252): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:674

- Target: `SvmJikoSfNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoSfNo not defined in active tree
- c-viz (row 2253): expr `SvmJikoSfNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2253): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:679

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 674 with undefined macro
- c-viz (row 2254): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2254): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:775

- Target: `SvmKyoukyuNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmKyoukyuNo not defined
- c-viz (row 2255): expr `SvmKyoukyuNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2255): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:780

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 775 with undefined macro
- c-viz (row 2256): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2256): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:900

- Target: `SvmHatudenNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmHatudenNo not defined
- c-viz (row 2257): expr `SvmHatudenNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2257): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:905

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 900 with undefined macro
- c-viz (row 2258): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2258): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:1025

- Target: `SvmSyunTeiMngNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSyunTeiMngNo not defined
- c-viz (row 2259): expr `SvmSyunTeiMngNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2259): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:1030

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 1025 with undefined macro
- c-viz (row 2260): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2260): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:1135

- Target: `SvmSyunTeiNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSyunTeiNo not defined
- c-viz (row 2261): expr `SvmSyunTeiNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2261): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:1140

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 1135 with undefined macro
- c-viz (row 2262): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2262): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:1252

- Target: `SvmJikoStatNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoStatNo not defined
- c-viz (row 2263): expr `SvmJikoStatNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2263): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:1257

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 1252 with undefined macro
- c-viz (row 2264): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2264): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:1291

- Target: `SvmSyunStatNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSyunStatNo not defined
- c-viz (row 2265): expr `SvmSyunStatNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2265): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmfile.c:1296

- Target: `&fcb` arg 1 of `mpf_mfs_readrecn` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 1291 with undefined macro
- c-viz (row 2266): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2266): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:33

- Target: `SvmJikoATMngNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJikoATMngNo not defined in active tree
- c-viz (row 2267): expr `SvmJikoATMngNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2267): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:39

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 33 with undefined macro
- c-viz (row 2268): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2268): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:57

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same handle
- c-viz (row 2269): expr `&fcb` values {} statuses {"UNRESOLVED": 1} → **UNDECIDED_SITE**
- legacy (row 2269): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:125

- Target: `SvmJimATMngNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmJimATMngNo not defined
- c-viz (row 2270): expr `SvmJimATMngNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2270): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:131

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 125 with undefined macro
- c-viz (row 2271): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2271): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:149

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same handle
- c-viz (row 2272): expr `&fcb` values {} statuses {"UNRESOLVED": 1} → **UNDECIDED_SITE**
- legacy (row 2272): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:217

- Target: `SvmChoATMngNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmChoATMngNo not defined
- c-viz (row 2273): expr `SvmChoATMngNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2273): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:223

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 217 with undefined macro
- c-viz (row 2274): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2274): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:241

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same handle
- c-viz (row 2275): expr `&fcb` values {} statuses {"UNRESOLVED": 1} → **UNDECIDED_SITE**
- legacy (row 2275): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:309

- Target: `SvmSyunATMngNo` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: SvmSyunATMngNo not defined
- c-viz (row 2276): expr `SvmSyunATMngNo` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2276): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:315

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb opened at 309 with undefined macro
- c-viz (row 2277): expr `&fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2277): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/IWATE/svmtool/svmkojin.c:333

- Target: `&fcb` arg 1 of `mpf_mfs_readrecm` (READREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same handle
- c-viz (row 2278): expr `&fcb` values {} statuses {"UNRESOLVED": 1} → **UNDECIDED_SITE**
- legacy (row 2278): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/SetFile

##### /home/chukyu/t-svm/tool/SetFile/SetFile.c:23

- Target: `file_no` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: file_no = atoi(argv[1]) (main :14) - user input, unbounded
- c-viz (row 2279): expr `file_no` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2279): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: high
- Note: input-driven

##### /home/chukyu/t-svm/tool/SetFile/SetFile.c:53

- Target: `fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb param = main's fcb opened with argv file_no; SetSvmJikoKTFL is generic setter
- c-viz (row 2280): expr `fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2280): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: high

##### /home/chukyu/t-svm/tool/apitop_test

##### /home/chukyu/t-svm/tool/apitop_test/topOnJohen.c:81

- Target: `(int)API_TOP_JOHEN_FILE` arg 3 of `mpf_mfs_openm` (OPEN_LOCK); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: API_TOP_JOHEN_FILE not defined in active tree
- c-viz (row 2281): expr `(int)API_TOP_JOHEN_FILE` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2281): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/apitop_test/topOnJohen.c:93

- Target: `&API_TOP_johen_file` arg 1 of `mpf_mfs_getrec` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: API_TOP_johen_file opened at 81 with undefined macro
- c-viz (row 2282): expr `&API_TOP_johen_file` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2282): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/apitop_test/topOnJohen.c:96

- Target: `&API_TOP_johen_file` arg 1 of `mpf_mfs_getrec` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same handle
- c-viz (row 2283): expr `&API_TOP_johen_file` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2283): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/apitop_test/topOnJohen.c:99

- Target: `&API_TOP_johen_file` arg 1 of `mpf_mfs_getrec` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same handle
- c-viz (row 2284): expr `&API_TOP_johen_file` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2284): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/apitop_test/topOnJohen.c:102

- Target: `&API_TOP_johen_file` arg 1 of `mpf_mfs_getrec` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same handle
- c-viz (row 2285): expr `&API_TOP_johen_file` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2285): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/apitop_test/topOnJohen.c:105

- Target: `&API_TOP_johen_file` arg 1 of `mpf_mfs_getrec` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same handle
- c-viz (row 2286): expr `&API_TOP_johen_file` values {} statuses {"UNREACHABLE": 1} → **UNDECIDED_SITE**
- legacy (row 2286): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: low

##### /home/chukyu/t-svm/tool/apitop_test/topOnJohen.c:175

- Target: `API_TOP_JOHEN_FILE` arg 3 of `mpf_mfs_openm` (WRITE); category cvisualizer_resolved_only
- Expected: no source-provable value [UNDECIDED]
  - reason: API_TOP_JOHEN_FILE undefined; c-viz 1413 not provable from active source
- c-viz (row 2287): expr `API_TOP_JOHEN_FILE` values {1413} statuses {"EXACT": 1} → **UNPROVABLE_CLAIM**
- legacy (row 2287): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE;STALE_HEADER_OR_SOURCE | Confidence: low

##### /home/chukyu/t-svm/tool/svmclr

##### /home/chukyu/t-svm/tool/svmclr/svmclr.c:56

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category cvisualizer_resolved_only
- Expected: {2651} [PATH_VALID]
  - proof: openm(&fcb,SvmHozonIdxNo=2651) at 50 in SvmIntHozonIdx
- c-viz (row 2288): expr `&fcb` values {2651} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2288): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/svmclr/svmclr.c:79

- Target: `&fcb` arg 1 of `mpf_mfs_writerecn` (WRITEREC); category cvisualizer_resolved_only
- Expected: {2650} [PATH_VALID]
  - proof: openm(&fcb,SvmCurVerNo=2650) at 68 in SvmIntCurVer
- c-viz (row 2289): expr `&fcb` values {2650} statuses {"EXACT": 1} → **CORRECT**
- legacy (row 2289): expr `—` values {} statuses {} → **UNDERAPPROXIMATION**
- Confidence: high

##### /home/chukyu/t-svm/tool/svmsetq

##### /home/chukyu/t-svm/tool/svmsetq/svmsetq.c:118

- Target: `file_no` arg 1 of `mpf_mfs_addque_H` (ADDQUE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: file_no = atoi(argv) (main :69) - user input
- c-viz (row 2514): expr `file_no` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2514): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: high

##### /home/chukyu/t-svm/tool/svmsetq/svmsetq.c:130

- Target: `file_no` arg 1 of `mpf_mfs_addque_H` (ADDQUE); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same
- c-viz (row 2515): expr `file_no` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2515): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: high

##### /home/chukyu/t-svm/tool/svmsetq/svmsetq.c:146

- Target: `proc_name` arg 1 of `pmf_forkproc_H` (FORKPROC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: proc_name = argv (main :68) - user input; FORKPROC target dynamic
- c-viz (row 48): expr `proc_name` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 48): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: high

##### /home/chukyu/t-svm/tool/test/setfile

##### /home/chukyu/t-svm/tool/test/setfile/setfile.c:34

- Target: `file_no` arg 3 of `mpf_mfs_openm` (READ); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: file_no = atoi(argv) in main - user input
- c-viz (row 2290): expr `file_no` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2290): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: high

##### /home/chukyu/t-svm/tool/test/setfile/setfile.c:69

- Target: `fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: fcb param = main's fcb (argv file_no)
- c-viz (row 2291): expr `fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2291): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: high

##### /home/chukyu/t-svm/tool/test/setfile/setfile.c:136

- Target: `fcb` arg 1 of `mpf_mfs_getrecm` (GETREC); category both_unresolved
- Expected: no source-provable value [UNDECIDED]
  - reason: same
- c-viz (row 2292): expr `fcb` values {} statuses {"EXTERNAL": 1} → **UNDECIDED_SITE**
- legacy (row 2292): expr `—` values {} statuses {} → **UNDECIDED_SITE**
- Cause tags: INSUFFICIENT_EVIDENCE | Confidence: high


### Notable examples

#### c-viz correct & legacy not
- `/home/chukyu/t-rep/src/libmsg1/MsgChkFlg.c:79` — c-viz reports 2902 (EXACT); the open is `open(&fcb,MsgIndexNo)` at :71 and the earlier open at :69 is commented out. Legacy reports no value.
- `/home/chukyu/t-sim/src/sim510d/sim510d_Gamen.c:600` — c-viz reports 3408 (SIM_OPIFNO); legacy nothing.

#### legacy correct & c-viz not
- `/home/chukyu/t-sim/src/sim530d/sim530d.c:835` — legacy reports the full caller union {3403,3404,3406,3407} for the `sim530d_FileOpen(fno)` wrapper (SIM_KEN_LST/SIM_TEJUN/SIM_KEN_BUF/SIM_TENKAI_BUF callers); c-viz reports nothing here, yet resolves the same edge at the sibling readrec/writerec sites (:869/:898).
- `/home/chukyu/t-sim/src/sim730/sim730.c:747` — legacy reports 3403 (valid, source also allows 3411); c-viz nothing.

#### both correct
- `/home/chukyu/t-rep/src/msg500d/msg500dOpBtn.c:55` — both report 2914 (MsgFlickerLevelNo, open_H at :51).
- `/home/chukyu/t-svm/src/svm000/svm000FileInt.c:385` — both report 2652 (SvmCurHozonNo, openm at :362).

#### c-viz overapproximation (false value)
- `/home/chukyu/t-rep/src/libmsgreq/msgrequest.c:469` (and :968, :974) — c-viz reports 2913 (MsgIndexDvdNo); source proves `IDX_fcb` is opened at :356 with `IDX_FNO` = MsgIndexNo = 2902 (assigned at :195, never reassigned). 2913 is the msg240-flow file and never binds this handle.

#### c-viz correct but incomplete (valid subset)
- `/home/chukyu/t-sim/src/sim430d/sim430d.c:836` — c-viz {1106,1107}; source {1105,1106,1107} (misses Simpidx==0 → SIM_430DSEMQUENO_0).

#### legacy correct but incomplete
- `/home/chukyu/t-sim/src/sim735/sim735.c:1133` — legacy {3404,3405}; source {3404,3405,3407} (misses SIM_TENKAI_BUF caller at tejun.c:1918).

### Unfinished / open items

None. All 396 claim rows (393 unique sites) received a verdict; sites without any provable source value are recorded as UNDECIDED with the specific blocker stated (stale-macro, out-of-tree caller, input-driven, or dead path) rather than skipped.

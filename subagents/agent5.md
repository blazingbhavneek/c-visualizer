# Role

You are one of 6 subagents (this one is **5**) in a source-code correctness
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
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/subagents/agent5_claims.csv
- Full per-site comparison (for cross-checking only; do not audit outside your batch):
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1_sites.csv
- c-visualizer raw facts:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index/discovery_facts.csv
- legacy proof:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/valueflow_proof.csv
- C source root: /home/chukyu

Batch statistics (already computed — reconcile them against your CSV on start):
- claim rows in your batch: 359
- unique (file, line) sites: 330

Your batch covers these source directories (relative to /home/chukyu):
- /home/chukyu/t-cha/src/cha001
- /home/chukyu/t-cha/src/cha100d
- /home/chukyu/t-cha/src/cha101d
- /home/chukyu/t-cha/src/cha120
- /home/chukyu/t-cha/src/cha200d
- /home/chukyu/t-cha/src/cha301
- /home/chukyu/t-cha/src/cha400
- /home/chukyu/t-cha/src/cha702
- /home/chukyu/t-cha/src/cha900
- /home/chukyu/t-cha/src/libCha
- /home/chukyu/t-cha/src/libChaCom
- /home/chukyu/t-cha/src/libChaDlg
- /home/chukyu/t-cha/src/libChaLrg
- /home/chukyu/t-cha/src/libChaMmi
- /home/chukyu/t-cha/tool/ClrChaOnlineSV
- /home/chukyu/t-dxi/src/dxi000d
- /home/chukyu/t-dxi/src/dxi000d_31174
- /home/chukyu/t-dxi/src/dxi110d
- /home/chukyu/t-dxi/src/dxi150d
- /home/chukyu/t-dxi/src/dxi300d
- /home/chukyu/t-dxi/src/dxi310d
- /home/chukyu/t-dxi/src/dxi400d
- /home/chukyu/t-dxi/src/dxi500d
- /home/chukyu/t-dxi/src/dxi510d
- /home/chukyu/t-dxi/src/dxi800d
- /home/chukyu/t-dxi/src/dxi900
- /home/chukyu/t-dxi/src/dxi901
- /home/chukyu/t-dxi/src/libdxi
- /home/chukyu/t-dxi/src/libdxiinside
- /home/chukyu/t-dxi/tool/dxi700
- /home/chukyu/t-dxi/tool/dxi710
- /home/chukyu/t-dxi/tool/dxiinf
- /home/chukyu/t-dxi/tool/itcmode
- /home/chukyu/t-dxi/tool/itcten

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
one of the 359 claim rows (all 330 unique sites) receives a verdict —
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
Scope: 330 unique (file,line) sites / 359 claim rows in agent5_claims.csv (reconciled on start: 359 rows, 330 sites - matches the stated batch statistics). All 330 sites audited against C source under /home/chukyu; no pipeline was run.
Method: for each site the FCB/queue-name/parameter expression of the audited argument was identified; all `mpf_mfs_open*` calls binding that handle (same function, global FCB, or via wrapper/caller) were located; file-number macros were resolved from the active headers (t-cha/include/ChaDef.h, t-dxi/include/dxi_const.h), including disabled (#if 0 / commented) defines; wrapper functions (ChaGetFileInfo, Dxi_Up*FileOpen, Dxi_DnTbn*FileOpen) and caller argument sets were traced where the open used a variable.
| verdict | c-visualizer (330 sites) | legacy (330 sites) |
|---|---|---|
| BOTH_CORRECT_SAME | 85 | 85 |
| CVIZ_CORRECT_ONLY | 45 | 0 |
| LEGACY_CORRECT_ONLY | 0 | 8 |
| BOTH_INCOMPLETE | 2 | 2 |
| CVIZ_UNDERAPPROXIMATION | 166 | 0 |
| LEGACY_UNDERAPPROXIMATION | 0 | 213 |
| CVIZ_OVERAPPROXIMATION | 10 | 0 |
| LEGACY_OVERAPPROXIMATION | 0 | 2 |
| UNDECIDED | 22 | 20 |

Per-cause-tag counts (sites tagged):
- MISSING_CALLER_EDGE: 26
- INSUFFICIENT_EVIDENCE: 22
- MISSING_WRAPPER_MAPPING: 17
- BRANCH_MERGE_ERROR: 4
- STALE_HEADER_OR_SOURCE: 2

Precision (site-claims reporting values that were accepted / all site-claims reporting values): c-visualizer 154/164 = 93.9%; legacy 96/98 = 98.0%.
Coverage (sites with a concrete source-backed expected set where the pipeline reported at least one accepted value / 308 such sites): c-visualizer 152/308 = 49.4%; legacy 96/308 = 31.2%. The remaining 22 sites have no concrete statically-provable value set (external/config-fed values, or no active caller in the current tree).

Recurring patterns in this batch:
1. c-visualizer `EXACT` on same-function `open_H/openm(_H)(&fcb, MACRO, ...)` sites is reliably source-correct (all ~70 such sites verified).
2. c-visualizer `UNREACHABLE`-only sites are almost always underapproximations: the open is a plain in-function call the root-tracking did not reach.
3. Legacy `OK_MACRO` constant resolution is strong for direct macro arguments (queue numbers, FCB opens) but it (a) misses every wrapper-mediated value (iOpenFileNo via ChaGetFileInfo, fileno[] arrays, fno variables) and (b) once picked a value from a `#if 0`-disabled define (DXI_FNO_ITCSSDEF 2511 vs active 2515).
4. c-visualizer resolved `iOpenFileNo` to `0` on 6 ChaLrgCom.c sites - the value is set by ChaGetFileInfo() immediately before the open and its error path returns, so 0 is unreachable: genuine overapproximation.
5. Both pipelines systematically miss the `myshu/shu == 1` branch in the #30017 three-instance pattern (INITMNG2=2519 at dxi110d_parent.c/dxi_initmng.c; CIRMNG2=2517 at dxi_cirmng.c), reporting only the 1st/3rd instance values.
### Site verdicts
#### /home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c
### /home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c:106
Target: mpf_mfs_readrecm; enclosing fn cha001ClrCaseManMngNo; ops: READREC(arg1)
Expected: 2836  (PATH_VALID)
  - proof: open L97 mpf_mfs_openm_H(&sCaseManFcb, ChaCaseManageNo=2836)
c-viz: [2836] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2836] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c:147
Target: mpf_mfs_writerecm; enclosing fn cha001ClrCaseManMngNo; ops: WRITEREC(arg1)
Expected: 2836  (PATH_VALID)
  - proof: open L97 mpf_mfs_openm_H(&sCaseManFcb, ChaCaseManageNo=2836)
c-viz: [2836] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2836] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha001/cha001Main.c
### /home/chukyu/t-cha/src/cha001/cha001Main.c:171
Target: mpf_mfs_readrecm; enclosing fn pmf_main_H; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened at L165/L221/L277/L350/L378 with ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha001/cha001Main.c:177
Target: mpf_mfs_writerecm; enclosing fn pmf_main_H; ops: WRITEREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened at L165/L221/L277/L350/L378 with ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha001/cha001Main.c:227
Target: mpf_mfs_readrecm; enclosing fn cha001ChgMod; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened at L165/L221/L277/L350/L378 with ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha001/cha001Main.c:283
Target: mpf_mfs_writerecm; enclosing fn cha001ChgMod; ops: WRITEREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened at L165/L221/L277/L350/L378 with ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha001/cha001Main.c:356
Target: mpf_mfs_readrecm; enclosing fn cha001ChgSub; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened at L165/L221/L277/L350/L378 with ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha001/cha001Main.c:384
Target: mpf_mfs_writerecm; enclosing fn cha001ChgSub; ops: WRITEREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened at L165/L221/L277/L350/L378 with ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha001/cha001ModeInit.c
### /home/chukyu/t-cha/src/cha001/cha001ModeInit.c:102
Target: mpf_mfs_copyrec; enclosing fn cha001Shiyoh; ops: COPYREC_FROM(arg2)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: iOpenFileNo set by ChaGetFileInfo(1,...) at L96 -> ChaOnlineTMNo01..17 (libCha/ChaGetFileInfo.c: *pFileNo=ChaBunFileNo[0][iLp1])
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/cha001/cha001ModeInit.c:118
Target: mpf_mfs_copyrec; enclosing fn cha001Shiyoh; ops: COPYREC_FROM(arg2)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: iOpenFileNo set by ChaGetFileInfo(2,...) at L110 -> ChaOnlineSVNo01..17
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
#### /home/chukyu/t-cha/src/cha001/cha001Update.c
### /home/chukyu/t-cha/src/cha001/cha001Update.c:227
Target: mpf_mfs_writerecm; enclosing fn cha001ClearHole; ops: WRITEREC(arg1)
Expected: 2819  (PATH_VALID)
  - proof: holman_fcb open L206 ChaHoleManageNo=2819
c-viz: [2819] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2819] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha100d/cha100dMain.c
### /home/chukyu/t-cha/src/cha100d/cha100dMain.c:54
Target: mpf_mfs_readrecm; enclosing fn pmf_start_H; ops: READREC(arg1)
Expected: 2802  (PATH_VALID)
  - proof: onlman_fcb open L48 ChaOnlineManageNo=2802
c-viz: [2802] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha100d/cha100dMain.c:229
Target: mpf_mfs_readrecm; enclosing fn cha100Init; ops: READREC(arg1)
Expected: 2802  (PATH_VALID)
  - proof: onlman_fcb open L223 ChaOnlineManageNo=2802
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [2802] {"ADDED": 1, "OK_MACRO": 1} -> LEGACY_CORRECT_ONLY -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha101d/cha101dMain.c
### /home/chukyu/t-cha/src/cha101d/cha101dMain.c:197
Target: mpf_mfs_readrecm; enclosing fn cha101Init; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb open L191 ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dMain.c:255
Target: mpf_mfs_writerecm; enclosing fn cha101UpManage; ops: WRITEREC(arg1)
Expected: 2802  (PATH_VALID)
  - proof: onlman_fcb open L249 ChaOnlineManageNo=2802
c-viz: [2802] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2802] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dMain.c:266
Target: mpf_mfs_readrecm; enclosing fn cha101UpManage; ops: READREC(arg1)
Expected: 2819  (PATH_VALID)
  - proof: holman_fcb open L260 ChaHoleManageNo=2819
c-viz: [2819] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2819] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dMain.c:268
Target: mpf_mfs_writerecm; enclosing fn cha101UpManage; ops: WRITEREC(arg1)
Expected: 2819  (PATH_VALID)
  - proof: holman_fcb open L260 ChaHoleManageNo=2819
c-viz: [2819] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2819] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dMain.c:282
Target: mpf_mfs_writerecm; enclosing fn cha101UpManage; ops: WRITEREC(arg1)
Expected: 2819  (PATH_VALID)
  - proof: holman_fcb open L260 ChaHoleManageNo=2819
c-viz: [2819] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2819] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha101d/cha101dSVSave.c
### /home/chukyu/t-cha/src/cha101d/cha101dSVSave.c:56
Target: mpf_mfs_readrecm; enclosing fn cha101SVSave; ops: READREC(arg1)
Expected: 2853  (PATH_VALID)
  - proof: svdef_fcb open L51 ChaRecSVDefNo=2853
c-viz: [2853] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2853] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dSVSave.c:65
Target: mpf_mfs_readrecm; enclosing fn cha101SVSave; ops: READREC(arg1)
Expected: 2854  (PATH_VALID)
  - proof: svidx_fcb open L60 ChaRecSVIdxNo=2854
c-viz: [2854] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2854] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dSVSave.c:133
Target: mpf_mfs_open_H; enclosing fn cha101OnlSVSave; ops: READ(arg2); WRITE(arg2)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: onlsv_fcb open L133 iOpenFileNo from ChaGetFileInfo(2,...) L125; error path returns, 0 not reachable
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/cha101d/cha101dSVSave.c:224
Target: mpf_mfs_writerecm; enclosing fn cha101OnlSVSave; ops: WRITEREC(arg1)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: onlsv_fcb opened L133 with iOpenFileNo (SV set)
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/cha101d/cha101dSVSave.c:229
Target: mpf_mfs_writerecm; enclosing fn cha101OnlSVSave; ops: WRITEREC(arg1)
Expected: 2814  (PATH_VALID)
  - proof: worksv_fcb open L146 ChaOnlWorkSVNo=2814
c-viz: [2814] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2814] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha101d/cha101dTMSave.c
### /home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:67
Target: mpf_mfs_readrecm; enclosing fn cha101TMSave; ops: READREC(arg1)
Expected: 2837  (PATH_VALID)
  - proof: tmdef_fcb open L62 ChaRecTMDefNo=2837
c-viz: [2837] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2837] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:76
Target: mpf_mfs_readrecm; enclosing fn cha101TMSave; ops: READREC(arg1)
Expected: 2838  (PATH_VALID)
  - proof: tmidx_fcb open L71 ChaRecTMIdxNo=2838
c-viz: [2838] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2838] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:321
Target: mpf_mfs_open_H; enclosing fn cha101OnlTMSave; ops: READ(arg2); WRITE(arg2)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: onltm_fcb open L321 iOpenFileNo from ChaGetFileInfo(1,...) L313 (the L177 open is inside #if 0 = DEAD_PATH)
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:350
Target: mpf_mfs_writerecm; enclosing fn cha101OnlTMSave; ops: WRITEREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: onltm_fcb opened L321 (iOpenFileNo, TM set)
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:365
Target: mpf_mfs_writerecm; enclosing fn cha101OnlTMSave; ops: WRITEREC(arg1)
Expected: 2820  (PATH_VALID)
  - proof: worktm_fcb open L332 ChaOnlWorkTMNo=2820
c-viz: [2820] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2820] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:383
Target: mpf_mfs_writerecm; enclosing fn cha101OnlTMSave; ops: WRITEREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: onltm_fcb opened L321 (iOpenFileNo, TM set)
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
#### /home/chukyu/t-cha/src/cha120/cha120DayChg.c
### /home/chukyu/t-cha/src/cha120/cha120DayChg.c:55
Target: mpf_mfs_readrecm; enclosing fn cha120DayChg; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb open L49 ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha120/cha120DayChg.c:89
Target: mpf_mfs_writerecm; enclosing fn cha120DayChg; ops: WRITEREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb open L49 ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha200d/cha200dCom.c
### /home/chukyu/t-cha/src/cha200d/cha200dCom.c:82
Target: mpf_mfs_getrecm; enclosing fn cha200ComOpenPictMan; ops: GETREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: PictMan_idx open L74 ChaPictManageNo=2823
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dCom.c:112
Target: mpf_mfs_getrecm; enclosing fn cha200ComOpenPictDat; ops: GETREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: PictDat_idx open L104 ChaPictDataNo=2824
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dCom.c:551
Target: mpf_mfs_getrecm; enclosing fn cha200ComTmKind; ops: GETREC(arg1)
Expected: 2837  (PATH_VALID)
  - proof: Tm_idx open L544 ChaRecTMDefNo=2837
c-viz: [2837] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2837] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha200d/cha200dProc.c
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:95
Target: mpf_mfs_readrecm; enclosing fn cha200Start; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:96
Target: mpf_mfs_writerecm; enclosing fn cha200Start; ops: WRITEREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:175
Target: mpf_mfs_readrecm; enclosing fn cha200End; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:176
Target: mpf_mfs_writerecm; enclosing fn cha200End; ops: WRITEREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:286
Target: mpf_mfs_readrecm; enclosing fn cha200Delete; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:287
Target: mpf_mfs_writerecm; enclosing fn cha200Delete; ops: WRITEREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:400
Target: mpf_mfs_readrecm; enclosing fn cha200Move; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:401
Target: mpf_mfs_writerecm; enclosing fn cha200Move; ops: WRITEREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:402
Target: mpf_mfs_readrecm; enclosing fn cha200Move; ops: READREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:403
Target: mpf_mfs_writerecm; enclosing fn cha200Move; ops: WRITEREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:532
Target: mpf_mfs_readrecm; enclosing fn cha200Copy; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:533
Target: mpf_mfs_writerecm; enclosing fn cha200Copy; ops: WRITEREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:534
Target: mpf_mfs_readrecm; enclosing fn cha200Copy; ops: READREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:535
Target: mpf_mfs_writerecm; enclosing fn cha200Copy; ops: WRITEREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:666
Target: mpf_mfs_readrecm; enclosing fn cha200Save; ops: READREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:667
Target: mpf_mfs_writerecm; enclosing fn cha200Save; ops: WRITEREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:780
Target: mpf_mfs_readrecm; enclosing fn cha200Make; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:781
Target: mpf_mfs_writerecm; enclosing fn cha200Make; ops: WRITEREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:782
Target: mpf_mfs_readrecm; enclosing fn cha200Make; ops: READREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha200d/cha200dProc.c:783
Target: mpf_mfs_writerecm; enclosing fn cha200Make; ops: WRITEREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: global FCB opened only with ChaPictManageNo=2823 (PictMan_idx, cha200dCom.c L74) or ChaPictDataNo=2824 (PictDat_idx, L104) anywhere in t-cha
c-viz: [2824] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2824] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha301/cha301Proc.c
### /home/chukyu/t-cha/src/cha301/cha301Proc.c:852
Target: mpf_mfs_readrecm; enclosing fn cha301GetSvData; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb open L846 ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2839] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha400/cha400Main.c
### /home/chukyu/t-cha/src/cha400/cha400Main.c:262
Target: mpf_mfs_readrecm; enclosing fn Cha400DataRead; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: Rec_idx open L256 ChaPictManageNo=2823
c-viz: [2823] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2823] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha702/cha702Event.c
### /home/chukyu/t-cha/src/cha702/cha702Event.c:979
Target: mpf_mfs_readrecm; enclosing fn cha702PictManChgJdg; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: PictMan_idx open L974 ChaPictManageNo=2823
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha702/cha702Init.c
### /home/chukyu/t-cha/src/cha702/cha702Init.c:517
Target: mpf_mfs_readrecm; enclosing fn cha702PictManInit; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: PictMan_idx open L510 ChaPictManageNo=2823
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha702/cha702Init.c:654
Target: mpf_mfs_readrecm; enclosing fn cha702PictDatInit; ops: READREC(arg1)
Expected: 2824  (PATH_VALID)
  - proof: PictDat_idx open L647 ChaPictDataNo=2824
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha900/cha900FileAccs.c
### /home/chukyu/t-cha/src/cha900/cha900FileAccs.c:49
Target: mpf_mfs_readrecm; enclosing fn cha900FileRead; ops: READREC(arg1)
Expected: 2838  (PATH_VALID)
  - proof: tmidx_fcb open L37 ChaRecTMIdxNo=2838
c-viz: [2838] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2838] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha900/cha900FileAccs.c:50
Target: mpf_mfs_readrecm; enclosing fn cha900FileRead; ops: READREC(arg1)
Expected: 2854  (PATH_VALID)
  - proof: svidx_fcb open L42 ChaRecSVIdxNo=2854
c-viz: [2854] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2854] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha900/cha900FileAccs.c:96
Target: mpf_mfs_writerecm; enclosing fn cha900FileWrite; ops: WRITEREC(arg1)
Expected: 2837  (PATH_VALID)
  - proof: tmdef_fcb open L74 ChaRecTMDefNo=2837
c-viz: [2837] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2837] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha900/cha900FileAccs.c:97
Target: mpf_mfs_writerecm; enclosing fn cha900FileWrite; ops: WRITEREC(arg1)
Expected: 2838  (PATH_VALID)
  - proof: tmidx_fcb open L79 (write) ChaRecTMIdxNo=2838
c-viz: [2838] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2838] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha900/cha900FileAccs.c:98
Target: mpf_mfs_writerecm; enclosing fn cha900FileWrite; ops: WRITEREC(arg1)
Expected: 2853  (PATH_VALID)
  - proof: svdef_fcb open L84 ChaRecSVDefNo=2853
c-viz: [2853] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2853] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/cha900/cha900FileAccs.c:99
Target: mpf_mfs_writerecm; enclosing fn cha900FileWrite; ops: WRITEREC(arg1)
Expected: 2854  (PATH_VALID)
  - proof: svidx_fcb open L89 (write) ChaRecSVIdxNo=2854
c-viz: [2854] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2854] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha900/cha900Fukan.c
### /home/chukyu/t-cha/src/cha900/cha900Fukan.c:98
Target: mpf_mfs_writerecm; enclosing fn cha900Fukantai; ops: WRITEREC(arg1)
Expected: 2856  (PATH_VALID)
  - proof: fukan_fcb open L92 ChaFukanTMDefNo=2856
c-viz: [2856] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2856] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/cha900/cha900JYCre.c
### /home/chukyu/t-cha/src/cha900/cha900JYCre.c:98
Target: mpf_mfs_writerecm; enclosing fn cha900JYCre; ops: WRITEREC(arg1)
Expected: 2855  (PATH_VALID)
  - proof: jydef_fcb open L93 ChaRecJYDefNo=2855
c-viz: [2855] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2855] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:70
Target: mpf_mfs_readrecm; enclosing fn ChaGetJisseki; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened in same function (L64/L144/L678) with ChaRecManageNo=2839 (active "ECS"/_H branch; "ORS" open commented out)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:150
Target: mpf_mfs_readrecm; enclosing fn ChaGetJissekiORS; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened in same function (L64/L144/L678) with ChaRecManageNo=2839 (active "ECS"/_H branch; "ORS" open commented out)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:513
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskPowData; ops: READREC(arg1)
Expected: 2808  (PATH_VALID)
  - proof: pow_fcb opened same function (L492/L506) ChaPowProcNo=2808
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:514
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskPowData; ops: READREC(arg1)
Expected: 2808  (PATH_VALID)
  - proof: pow_fcb opened same function (L492/L506) ChaPowProcNo=2808
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:515
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskPowData; ops: READREC(arg1)
Expected: 2808  (PATH_VALID)
  - proof: pow_fcb opened same function (L492/L506) ChaPowProcNo=2808
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:516
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskPowData; ops: READREC(arg1)
Expected: 2808  (PATH_VALID)
  - proof: pow_fcb opened same function (L492/L506) ChaPowProcNo=2808
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:626
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskAvgData; ops: READREC(arg1)
Expected: 2809  (PATH_VALID)
  - proof: avg_fcb open L605/L619 ChaAvgTempNo=2809
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:685
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskAvgData; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb opened in same function (L64/L144/L678) with ChaRecManageNo=2839 (active "ECS"/_H branch; "ORS" open commented out)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:817
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskPowDataAvg; ops: READREC(arg1)
Expected: 2808  (PATH_VALID)
  - proof: pow_fcb opened same function (L791/L805) ChaPowProcNo=2808
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:818
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskPowDataAvg; ops: READREC(arg1)
Expected: 2808  (PATH_VALID)
  - proof: pow_fcb opened same function (L791/L805) ChaPowProcNo=2808
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:819
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskPowDataAvg; ops: READREC(arg1)
Expected: 2808  (PATH_VALID)
  - proof: pow_fcb opened same function (L791/L805) ChaPowProcNo=2808
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libCha/ChaGetJisseki.c:820
Target: mpf_mfs_readrecm; enclosing fn ChaGetJskPowDataAvg; ops: READREC(arg1)
Expected: 2808  (PATH_VALID)
  - proof: pow_fcb opened same function (L791/L805) ChaPowProcNo=2808
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaCom/ChaCase.c
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:504
Target: mpf_mfs_open_H; enclosing fn ChaReadRecm; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870} U {2816,2817,2818,2823,2837,2838,2839,2853,2854}  (PATH_VALID)
  - proof: ChaReadRecm(fileNo param): active callers cha301Proc.c L126/133/140/156/164/174 pass 2838/2854/2839/2837/2853/2823; L739/761/785 pass fileNo in {TM set, 2816,2817,2818}. cviz 7 values each reachable but incomplete
c-viz: [ 2823; 2837; 2838; 2839; 2853; 2854;2818] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:515
Target: mpf_mfs_readrecm; enclosing fn ChaReadRecm; ops: READREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870} U {2816,2817,2818,2823,2837,2838,2839,2853,2854}  (PATH_VALID)
  - proof: ChaReadRecm(fileNo param): active callers cha301Proc.c L126/133/140/156/164/174 pass 2838/2854/2839/2837/2853/2823; L739/761/785 pass fileNo in {TM set, 2816,2817,2818}. cviz 7 values each reachable but incomplete
c-viz: [ 2823; 2837; 2838; 2839; 2853; 2854;2818] {"EXACT": 7, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:539
Target: mpf_mfs_open_H; enclosing fn ChaWriteRecm; ops: OPEN_LOCK(arg2)
Expected: (no active caller)  (DEAD_PATH)
  - proof: ChaWriteRecm: only callers in source are commented out (cha301Proc.c L1129/1182/1297); no value demonstrably reaches site
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:546
Target: mpf_mfs_writerecm; enclosing fn ChaWriteRecm; ops: WRITEREC(arg1)
Expected: (no active caller)  (DEAD_PATH)
  - proof: ChaWriteRecm: only callers in source are commented out (cha301Proc.c L1129/1182/1297); no value demonstrably reaches site
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:579
Target: mpf_mfs_open_H; enclosing fn ChaReadRecn; ops: OPEN_LOCK(arg2)
Expected: (fileNo param, callers not enumerated)  (PATH_VALID)
  - proof: ChaReadRecn: fileNo is a parameter; single active caller uses iOpenFileNo (SV set via ChaGetFileInfo, cha301Proc.c L840) - not fully traced
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: low
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:588
Target: mpf_mfs_readrecn; enclosing fn ChaReadRecn; ops: READREC(arg1)
Expected: (fileNo param, callers not enumerated)  (PATH_VALID)
  - proof: ChaReadRecn: fileNo is a parameter; single active caller uses iOpenFileNo (SV set via ChaGetFileInfo, cha301Proc.c L840) - not fully traced
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: low
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:653
Target: mpf_mfs_open_H; enclosing fn ChaReadTm; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870} U {2816,2817,2818}  (PATH_VALID)
  - proof: ChaReadTm(fileNo param): caller cha301Proc.c L704 fileNo in {TM set (ChaGetFileInfo(1)), ChaOnlineOthNo=2817, ChaOnlineTempNo=2816, ChaOnlineELDNo=2818}; cviz {2818} valid but incomplete
c-viz: [2818] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:658
Target: mpf_mfs_readrecn; enclosing fn ChaReadTm; ops: READREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870} U {2816,2817,2818}  (PATH_VALID)
  - proof: ChaReadTm(fileNo param): caller cha301Proc.c L704 fileNo in {TM set (ChaGetFileInfo(1)), ChaOnlineOthNo=2817, ChaOnlineTempNo=2816, ChaOnlineELDNo=2818}; cviz {2818} valid but incomplete
c-viz: [2818] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:664
Target: mpf_mfs_open_H; enclosing fn ChaReadTm; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870} U {2816,2817,2818}  (PATH_VALID)
  - proof: ChaReadTm(fileNo param): caller cha301Proc.c L704 fileNo in {TM set (ChaGetFileInfo(1)), ChaOnlineOthNo=2817, ChaOnlineTempNo=2816, ChaOnlineELDNo=2818}; cviz {2818} valid but incomplete
c-viz: [2818] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:669
Target: mpf_mfs_readrecn; enclosing fn ChaReadTm; ops: READREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870} U {2816,2817,2818}  (PATH_VALID)
  - proof: ChaReadTm(fileNo param): caller cha301Proc.c L704 fileNo in {TM set (ChaGetFileInfo(1)), ChaOnlineOthNo=2817, ChaOnlineTempNo=2816, ChaOnlineELDNo=2818}; cviz {2818} valid but incomplete
c-viz: [2818] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:703
Target: mpf_mfs_openm_H; enclosing fn ChaReadTmHole; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: 2819  (PATH_VALID)
  - proof: ChaReadTmHole(fileNo): active caller passes ChaHoleManageNo=2819
c-viz: [2819] {"UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:708
Target: mpf_mfs_readrecm; enclosing fn ChaReadTmHole; ops: READREC(arg1)
Expected: 2819  (PATH_VALID)
  - proof: ChaReadTmHole(fileNo): active caller passes ChaHoleManageNo=2819
c-viz: [2819] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:799
Target: mpf_mfs_open_H; enclosing fn ChaReadSv; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: ChaReadSv(fileNo param): active caller cha301Proc.c L882 passes iOpenFileNo from ChaGetFileInfo(2) -> SV online set
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:804
Target: mpf_mfs_readrecn; enclosing fn ChaReadSv; ops: READREC(arg1)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: ChaReadSv(fileNo param): active caller cha301Proc.c L882 passes iOpenFileNo from ChaGetFileInfo(2) -> SV online set
c-viz: [(no value)] {"EXTERNAL": 1, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:810
Target: mpf_mfs_open_H; enclosing fn ChaReadSv; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: ChaReadSv(fileNo param): active caller cha301Proc.c L882 passes iOpenFileNo from ChaGetFileInfo(2) -> SV online set
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:815
Target: mpf_mfs_readrecn; enclosing fn ChaReadSv; ops: READREC(arg1)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: ChaReadSv(fileNo param): active caller cha301Proc.c L882 passes iOpenFileNo from ChaGetFileInfo(2) -> SV online set
c-viz: [(no value)] {"EXTERNAL": 1, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:849
Target: mpf_mfs_openm_H; enclosing fn ChaReadSvHole; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: 2819  (PATH_VALID)
  - proof: ChaReadSvHole(fileNo): active caller passes ChaHoleManageNo=2819
c-viz: [2819] {"UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:854
Target: mpf_mfs_readrecm; enclosing fn ChaReadSvHole; ops: READREC(arg1)
Expected: 2819  (PATH_VALID)
  - proof: ChaReadSvHole(fileNo): active caller passes ChaHoleManageNo=2819
c-viz: [2819] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:912
Target: mpf_mfs_open_H; enclosing fn ChaWriteRecn; ops: OPEN_LOCK(arg2); WRITE(arg2)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: ChaWriteRecn(fileNo param): active callers cha301Proc.c L1101/1115/1153/1167 pass iOpenFileNo (SV set via ChaGetFileInfo(2))
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaCom/ChaCase.c:921
Target: mpf_mfs_writerecn; enclosing fn ChaWriteRecn; ops: WRITEREC(arg1)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: ChaWriteRecn(fileNo param): active callers cha301Proc.c L1101/1115/1153/1167 pass iOpenFileNo (SV set via ChaGetFileInfo(2))
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 4} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
#### /home/chukyu/t-cha/src/libChaCom/ChaCaseCheck.c
### /home/chukyu/t-cha/src/libChaCom/ChaCaseCheck.c:48
Target: mpf_mfs_readrecm; enclosing fn ChaCaseChkEdit; ops: READREC(arg1)
Expected: 2836  (PATH_VALID)
  - proof: caseman_fcb opened same function (L42/L106) ChaCaseManageNo=2836
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaCom/ChaCaseCheck.c:112
Target: mpf_mfs_readrecm; enclosing fn ChaCaseChkSave; ops: READREC(arg1)
Expected: 2836  (PATH_VALID)
  - proof: caseman_fcb opened same function (L42/L106) ChaCaseManageNo=2836
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaCom/ChaGet.c
### /home/chukyu/t-cha/src/libChaCom/ChaGet.c:357
Target: mpf_mfs_readrecm; enclosing fn ChaGetTMName; ops: READREC(arg1)
Expected: 2837  (PATH_VALID)
  - proof: fcb open L351 ChaRecTMDefNo=2837
c-viz: [2837] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaCom/ChaGet.c:625
Target: mpf_mfs_readrecm; enclosing fn ChaGetSVName; ops: READREC(arg1)
Expected: 2853  (PATH_VALID)
  - proof: fcb open L619 ChaRecSVDefNo=2853 (own function)
c-viz: [2853] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaCom/ChaGet.c:865
Target: mpf_mfs_readrecm; enclosing fn ChaGetFukantai; ops: READREC(arg1)
Expected: 2856  (PATH_VALID)
  - proof: fcb open L860 ChaFukanTMDefNo=2856 (own function)
c-viz: [2856] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaCom/ChaGet.c:874
Target: mpf_mfs_readrecm; enclosing fn ChaGetFukantai; ops: READREC(arg1)
Expected: 2837  (PATH_VALID)
  - proof: fcb open L869 ChaRecTMDefNo=2837 (own function)
c-viz: [2837] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaDlg/ChaDialog01CtlCB.c
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog01CtlCB.c:75
Target: mpf_mfs_readrecm; enclosing fn chaDlg01SaveKindBtn; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: fcb open L67 ChaPictManageNo=2823
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaDlg/ChaDialog01Main.c
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog01Main.c:185
Target: mpf_mfs_readrecm; enclosing fn chaDlg01DataInit; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: fcb open L177 ChaPictManageNo=2823
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaDlg/ChaDialog05Main.c
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog05Main.c:370
Target: mpf_mfs_readrecm; enclosing fn ChaDlg05DataRead; ops: READREC(arg1)
Expected: 2810  (PATH_VALID)
  - proof: Rec_idx open L365 ChaTohokuResNo=2810
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog05Main.c:1296
Target: mpf_mfs_readrecm; enclosing fn chaGetRecEldDay; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: RecMan_idx open L1290 ChaRecManageNo=2839
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaDlg/ChaDialog06Main.c
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog06Main.c:279
Target: mpf_mfs_readrecn; enclosing fn ChaDlg06DataRead; ops: READREC(arg1)
Expected: 2811  (PATH_VALID)
  - proof: Rec_idx open L271 ChaOthResNo=2811
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaDlg/ChaDialog11Com.c
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog11Com.c:211
Target: mpf_mfs_readrecm; enclosing fn chaDlg11DspNowJisChk; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: PictMan_idx opened same file (L204/L446) ChaPictManageNo=2823
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog11Com.c:453
Target: mpf_mfs_readrecm; enclosing fn chaDlg11TblNomal; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: PictMan_idx opened same file (L204/L446) ChaPictManageNo=2823
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaDlg/ChaDialog11Main.c
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog11Main.c:281
Target: mpf_mfs_open_H; enclosing fn ChaKenRecm; ops: OPEN_LOCK(arg2)
Expected: (no active caller)  (DEAD_PATH)
  - proof: ChaKenRecm(fileNo param): no active caller of ChaKenRecm anywhere in current t-cha source
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog11Main.c:286
Target: mpf_mfs_readrecm; enclosing fn ChaKenRecm; ops: READREC(arg1)
Expected: (no active caller)  (DEAD_PATH)
  - proof: ChaKenRecm(fileNo param): no active caller of ChaKenRecm anywhere in current t-cha source
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-cha/src/libChaDlg/ChaDialog12Com.c
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog12Com.c:289
Target: mpf_mfs_readrecm; enclosing fn chaDlg12TblRead; ops: READREC(arg1)
Expected: 2823  (PATH_VALID)
  - proof: PictMan_idx open L282 ChaPictManageNo=2823
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog12Com.c:581
Target: mpf_mfs_readrecm; enclosing fn chaDlg12GetDef; ops: READREC(arg1)
Expected: 2837  (PATH_VALID)
  - proof: fcb open L575 ChaRecTMDefNo=2837
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog12Com.c:590
Target: mpf_mfs_readrecm; enclosing fn chaDlg12GetDef; ops: READREC(arg1)
Expected: 2853  (PATH_VALID)
  - proof: fcb open L584 ChaRecSVDefNo=2853
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaDlg/ChaDialog12Main.c
### /home/chukyu/t-cha/src/libChaDlg/ChaDialog12Main.c:366
Target: mpf_mfs_readrecm; enclosing fn chaDlg12DspInitSs; ops: READREC(arg1)
Expected: 2855  (PATH_VALID)
  - proof: JYDef_idx open L358 ChaRecJYDefNo=2855
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:64
Target: mpf_mfs_readrecm; enclosing fn chaLrgComRecMan; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: RecMan_idx open L57 ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:288
Target: mpf_mfs_open_H; enclosing fn chaLrgDataRead; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: U {2808,2809,2811,2816,2817,2818} (2811 proven via ChaLrgJis.c:313; rest via variable kind)  (PATH_VALID)
  - proof: chaLrgDataRead(kind param): callers pass variable kind (ChaLrgTm/ChaLrgJis) or ChaOthResNo=2811; cviz values plausible but full set not derivable in audit; legacy reports nothing
c-viz: [ 2809; 2811; 2816; 2817; 2818;2808] {"UNREACHABLE": 1} -> UNDECIDED -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: low
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:293
Target: mpf_mfs_readrecn; enclosing fn chaLrgDataRead; ops: READREC(arg1)
Expected: U {2808,2809,2811,2816,2817,2818} (2811 proven via ChaLrgJis.c:313; rest via variable kind)  (PATH_VALID)
  - proof: chaLrgDataRead(kind param): callers pass variable kind (ChaLrgTm/ChaLrgJis) or ChaOthResNo=2811; cviz values plausible but full set not derivable in audit; legacy reports nothing
c-viz: [ 2809; 2811; 2816; 2817; 2818;2808] {"EXACT": 6, "UNREACHABLE": 1} -> UNDECIDED -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: low
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:320
Target: mpf_mfs_open_H; enclosing fn chaLrgDataReadNoSub; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: 2810  (PATH_VALID)
  - proof: chaLrgDataReadNoSub(kind): only active callers pass ChaTohokuResNo=2810
c-viz: [2810] {"UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:325
Target: mpf_mfs_readrecm; enclosing fn chaLrgDataReadNoSub; ops: READREC(arg1)
Expected: 2810  (PATH_VALID)
  - proof: chaLrgDataReadNoSub(kind): only active callers pass ChaTohokuResNo=2810
c-viz: [2810] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:356
Target: mpf_mfs_open_H; enclosing fn chaLrgDataReadCate; ops: OPEN_LOCK(arg2)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870} U {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: chaLrgDataReadCate(kind): active caller ChaLrgOff.c L153/263/417/527 passes iOpenFileNo (ChaGetFileInfo TM/SV online set); ChaPicCaseDataNo callers are #ifdef NOP (dead)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:361
Target: mpf_mfs_readrecn; enclosing fn chaLrgDataReadCate; ops: READREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870} U {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: chaLrgDataReadCate(kind): active caller ChaLrgOff.c L153/263/417/527 passes iOpenFileNo (ChaGetFileInfo TM/SV online set); ChaPicCaseDataNo callers are #ifdef NOP (dead)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:444
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadTm; ops: READREC(arg1)
Expected: 2820  (PATH_VALID)
  - proof: fcb open L433 ChaOnlWorkTMNo=2820 (hit branch)
c-viz: [2820] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:446
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadTm; ops: READREC(arg1)
Expected: 2820  (PATH_VALID)
  - proof: fcb open L433 ChaOnlWorkTMNo=2820 (hit branch)
c-viz: [2820] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:458
Target: mpf_mfs_open_H; enclosing fn chaLrgReadTm; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: else branch: open L458 iOpenFileNo from ChaGetFileInfo(1) L452, error path returns -> iOpenFileNo in TM set, never 0; cviz value 0 impossible
c-viz: [0] {"UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:470
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadTm; ops: READREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: else branch: open L458 iOpenFileNo from ChaGetFileInfo(1) L452, error path returns -> iOpenFileNo in TM set, never 0; cviz value 0 impossible
c-viz: [0] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:477
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadTm; ops: READREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: else branch: open L458 iOpenFileNo from ChaGetFileInfo(1) L452, error path returns -> iOpenFileNo in TM set, never 0; cviz value 0 impossible
c-viz: [0] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:657
Target: mpf_mfs_open_H; enclosing fn chaLrgReadTmBef; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: open L657 iOpenFileNo from ChaGetFileInfo(1) L651; cviz value 0 impossible
c-viz: [0] {"UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:663
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadTmBef; ops: READREC(arg1)
Expected: {2845,2846,2847,2857,2858,2859,2860,2861,2862,2863,2864,2865,2866,2867,2868,2869,2870}  (PATH_VALID)
  - proof: open L657 iOpenFileNo from ChaGetFileInfo(1) L651; cviz value 0 impossible
c-viz: [0] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:711
Target: mpf_mfs_readrecm; enclosing fn chaLrgHole; ops: READREC(arg1)
Expected: 2819  (PATH_VALID)
  - proof: fcbHo open L706 ChaHoleManageNo=2819
c-viz: [2819] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:923
Target: mpf_mfs_readrecm; enclosing fn chaLrgReadSv; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb open L917 ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:982
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadSv; ops: READREC(arg1)
Expected: 2814  (PATH_VALID)
  - proof: fcb open L971 ChaOnlWorkSVNo=2814 (hit branch)
c-viz: [2814] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:984
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadSv; ops: READREC(arg1)
Expected: 2814  (PATH_VALID)
  - proof: fcb open L971 ChaOnlWorkSVNo=2814 (hit branch)
c-viz: [2814] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:996
Target: mpf_mfs_open_H; enclosing fn chaLrgReadSv; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: else branch: open L996 iOpenFileNo from ChaGetFileInfo(2) L990; cviz value 0 impossible
c-viz: [0] {"UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:1008
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadSv; ops: READREC(arg1)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: else branch: open L996 iOpenFileNo from ChaGetFileInfo(2) L990; cviz value 0 impossible
c-viz: [0] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:1015
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadSv; ops: READREC(arg1)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: else branch: open L996 iOpenFileNo from ChaGetFileInfo(2) L990; cviz value 0 impossible
c-viz: [0] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:1127
Target: mpf_mfs_open_H; enclosing fn chaLrgReadSvBef; ops: OPEN_LOCK(arg2); READ(arg2)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: open L1127 iOpenFileNo from ChaGetFileInfo(2) L1118; cviz value 0 impossible
c-viz: [0] {"UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:1133
Target: mpf_mfs_readrecn; enclosing fn chaLrgReadSvBef; ops: READREC(arg1)
Expected: {2803,2804,2805,2806,2807,2812,2813,2821,2822,2832,2833,2834,2835,2840,2850,2851,2852}  (PATH_VALID)
  - proof: open L1127 iOpenFileNo from ChaGetFileInfo(2) L1118; cviz value 0 impossible
c-viz: [0] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_OVERAPPROXIMATION -- rejected value(s)
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: MISSING_WRAPPER_MAPPING
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:1144
Target: mpf_mfs_readrecm; enclosing fn chaLrgReadSvBef; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: recman_fcb open L1138 ChaRecManageNo=2839
c-viz: [2839] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaLrg/ChaLrgSv.c
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgSv.c:112
Target: mpf_mfs_readrecm; enclosing fn chaLrgSvKindChk; ops: READREC(arg1)
Expected: 2854  (PATH_VALID)
  - proof: fcbsv_idx open L107 ChaRecSVIdxNo=2854
c-viz: [2854] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaLrg/ChaLrgTm.c
### /home/chukyu/t-cha/src/libChaLrg/ChaLrgTm.c:112
Target: mpf_mfs_readrecm; enclosing fn chaLrgTmKindChk; ops: READREC(arg1)
Expected: 2838  (PATH_VALID)
  - proof: fcbtm_idx open L106 ChaRecTMIdxNo=2838
c-viz: [2838] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/src/libChaMmi/chaGmnKen.c
### /home/chukyu/t-cha/src/libChaMmi/chaGmnKen.c:547
Target: mpf_mfs_open_H; enclosing fn ChaGmnKenRecm; ops: OPEN_LOCK(arg2)
Expected: (no active caller)  (DEAD_PATH)
  - proof: ChaGmnKenRecm(fileNo param): only callers in source are commented out (ChaDialog12Chu.c L295/322)
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/src/libChaMmi/chaGmnKen.c:552
Target: mpf_mfs_readrecm; enclosing fn ChaGmnKenRecm; ops: READREC(arg1)
Expected: (no active caller)  (DEAD_PATH)
  - proof: ChaGmnKenRecm(fileNo param): only callers in source are commented out (ChaDialog12Chu.c L295/322)
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-cha/src/libChaMmi/chaOnSub.c
### /home/chukyu/t-cha/src/libChaMmi/chaOnSub.c:337
Target: mpf_mfs_readrecm; enclosing fn chaOnSubGetRecAcc; ops: READREC(arg1)
Expected: 2839  (PATH_VALID)
  - proof: RecMan_idx open L332 ChaRecManageNo=2839
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-cha/tool/ClrChaOnlineSV/ClrChaOnlineSV.c
### /home/chukyu/t-cha/tool/ClrChaOnlineSV/ClrChaOnlineSV.c:68
Target: mpf_mfs_open_H; enclosing fn main; ops: WRITE(arg2)
Expected: ChaOnlineSVNo (macro not defined in current t-cha headers)  (PATH_VALID)
  - proof: fno = ChaOnlineSVNo at L55; ChaOnlineSVNo has no #define in current t-cha/include -> value unresolvable against active source
c-viz: [(no value)] {"EXTERNAL": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: low
Cause tags: STALE_HEADER_OR_SOURCE,INSUFFICIENT_EVIDENCE
### /home/chukyu/t-cha/tool/ClrChaOnlineSV/ClrChaOnlineSV.c:77
Target: mpf_mfs_writerecn; enclosing fn main; ops: WRITEREC(arg1)
Expected: ChaOnlineSVNo (macro not defined in current t-cha headers)  (PATH_VALID)
  - proof: fno = ChaOnlineSVNo at L55; ChaOnlineSVNo has no #define in current t-cha/include -> value unresolvable against active source
c-viz: [(no value)] {"EXTERNAL": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: low
Cause tags: STALE_HEADER_OR_SOURCE,INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-dxi/src/dxi000d/dxi000d_inf.c
### /home/chukyu/t-dxi/src/dxi000d/dxi000d_inf.c:354
Target: mpf_mfs_addque; enclosing fn dxi_failinfo_send; ops: ADDQUE(arg2)
Expected: external (config file: Dxi_RepfailInfoG[i].qno=strtol(...), dxi000d_main.c:499)  (PATH_VALID)
  - proof: qno values loaded from config data at runtime; no static value provable
c-viz: [(no value)] {"DYNAMIC": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dxi/src/dxi000d/dxi000d_inf.c:417
Target: mpf_mfs_addque; enclosing fn dxi_failinfo_send; ops: ADDQUE(arg2)
Expected: external (config file: Dxi_RepfailInfoG[i].qno=strtol(...), dxi000d_main.c:499)  (PATH_VALID)
  - proof: qno values loaded from config data at runtime; no static value provable
c-viz: [(no value)] {"DYNAMIC": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-dxi/src/dxi000d_31174/dxi000d_inf.c
### /home/chukyu/t-dxi/src/dxi000d_31174/dxi000d_inf.c:354
Target: mpf_mfs_addque; enclosing fn dxi_failinfo_send; ops: ADDQUE(arg2)
Expected: external (config file: Dxi_RepfailInfoG[i].qno=strtol(...), dxi000d_main.c:499)  (PATH_VALID)
  - proof: qno values loaded from config data at runtime; no static value provable
c-viz: [(no value)] {"DYNAMIC": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dxi/src/dxi000d_31174/dxi000d_inf.c:417
Target: mpf_mfs_addque; enclosing fn dxi_failinfo_send; ops: ADDQUE(arg2)
Expected: external (config file: Dxi_RepfailInfoG[i].qno=strtol(...), dxi000d_main.c:499)  (PATH_VALID)
  - proof: qno values loaded from config data at runtime; no static value provable
c-viz: [(no value)] {"DYNAMIC": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-dxi/src/dxi110d/dxi110d_child.c
### /home/chukyu/t-dxi/src/dxi110d/dxi110d_child.c:866
Target: mpf_mfs_addque; enclosing fn dxi_haisin; ops: ADDQUE(arg2)
Expected: {701,723,727}  (PATH_VALID)
  - proof: qno=DXI_QNO_RCVDATA/RCVDATA2/RCVDATA3 (701/723/727) on myshu 0/1/2 just above site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi110d/dxi110d_main.c
### /home/chukyu/t-dxi/src/dxi110d/dxi110d_main.c:668
Target: mpf_mfs_getrecm; enclosing fn dxi_clr_cirmng; ops: GETREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fcb opened in dxi_clr_cirmng per myshu: DXI_FNO_CIRMNG/CIRMNG2/CIRMNG3 (L643/L651/L660)
c-viz: [ 2517; 2523;2502] {"EXACT": 3} -> BOTH_CORRECT_SAME -- accepted
legacy: [ 2517; 2523;2502] {"ADDED": 3, "OK_MACRO": 3} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c
### /home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c:1687
Target: mpf_mfs_openm; enclosing fn dxi_send_blkpkt; ops: READ(arg3)
Expected: {2512,2519,2525}  (PATH_VALID)
  - proof: fno_initmng = DXI_FNO_INITMNG/INITMNG2/INITMNG3 (2512/2519/2525) at L1583-1589 per myshu; both pipelines miss 2519 (myshu==1)
c-viz: [ 2525;2512] {"EXACT": 2} -> BOTH_INCOMPLETE -- accepted
legacy: [ 2525;2512] {"ADDED": 2, "OK_MACRO": 2} -> BOTH_INCOMPLETE -- accepted
Confidence: high
Cause tags: BRANCH_MERGE_ERROR
### /home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c:1695
Target: mpf_mfs_getrecm; enclosing fn dxi_send_blkpkt; ops: GETREC(arg1)
Expected: {2512,2519,2525}  (PATH_VALID)
  - proof: fno_initmng = DXI_FNO_INITMNG/INITMNG2/INITMNG3 (2512/2519/2525) at L1583-1589 per myshu; both pipelines miss 2519 (myshu==1)
c-viz: [ 2525;2512] {"EXACT": 2} -> BOTH_INCOMPLETE -- accepted
legacy: [ 2525;2512] {"ADDED": 2, "OK_MACRO": 2} -> BOTH_INCOMPLETE -- accepted
Confidence: high
Cause tags: BRANCH_MERGE_ERROR
### /home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c:2298
Target: mpf_mfs_delque; enclosing fn dxi_reg_buff_data; ops: DELQUE(arg2)
Expected: 707  (PATH_VALID)
  - proof: DXI_QNO_DATABUFF=707 (dxi_const.h)
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [707] {"ADDED": 1, "OK_MACRO": 1} -> LEGACY_CORRECT_ONLY -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c:2316
Target: mpf_mfs_addque; enclosing fn dxi_reg_buff_data; ops: ADDQUE(arg2)
Expected: 707  (PATH_VALID)
  - proof: DXI_QNO_DATABUFF=707 (dxi_const.h)
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [707] {"ADDED": 1, "OK_MACRO": 1} -> LEGACY_CORRECT_ONLY -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi110d/dxi_buffqread.c
### /home/chukyu/t-dxi/src/dxi110d/dxi_buffqread.c:63
Target: mpf_mfs_delque; enclosing fn Dxi_BuffQread; ops: DELQUE(arg2)
Expected: 707  (PATH_VALID)
  - proof: DXI_QNO_DATABUFF=707
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [707] {"ADDED": 1, "OK_MACRO": 1} -> LEGACY_CORRECT_ONLY -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi110d/dxi_dnqread.c
### /home/chukyu/t-dxi/src/dxi110d/dxi_dnqread.c:71
Target: mpf_mfs_delque; enclosing fn Dxi_DnQread; ops: DELQUE(arg2)
Expected: {702,703,724,725,728,729}  (PATH_VALID)
  - proof: filenum[6] init at L54: DXI_QNO_SNDDATA1/2/12/22/13/23
c-viz: [(no value)] {"DYNAMIC": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_child.c
### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_child.c:936
Target: mpf_mfs_addque; enclosing fn dxi_haisin; ops: ADDQUE(arg2)
Expected: 731  (PATH_VALID)
  - proof: DXI_QNO_GRCVDATA=731
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [731] {"ADDED": 1, "OK_MACRO": 1} -> LEGACY_CORRECT_ONLY -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_cpumode.c
### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_cpumode.c:125
Target: mpf_mfs_getrecm; enclosing fn dxi_cpumode_mng; ops: GETREC(arg1)
Expected: 2555  (PATH_VALID)
  - proof: fcb open L77 DXI_FNO_GCPUMODE=2555
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_main.c
### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_main.c:923
Target: mpf_mfs_getrecm; enclosing fn dxi_clr_cirmng; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: dxi_clr_cirmng: fcb opened L916 DXI_FNO_GITCMNG=2554 (only open before site)
c-viz: [2554] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_main.c:1042
Target: mpf_mfs_getrecm; enclosing fn dxi_clr_cirmng; ops: GETREC(arg1)
Expected: 2552  (PATH_VALID)
  - proof: fcb reopened L1021 DXI_FNO_GCIRMNG=2552 before site; earlier 2554 open belongs to prior branch block
c-viz: [2552] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_parent.c
### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_parent.c:1108
Target: mpf_mfs_getrecm; enclosing fn dxi_cyclic_send; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L1100 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2554] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_parent.c:2411
Target: mpf_mfs_delque; enclosing fn dxi_reg_buff_data; ops: DELQUE(arg2)
Expected: 707  (PATH_VALID)
  - proof: DXI_QNO_DATABUFF=707
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [707] {"ADDED": 1, "OK_MACRO": 1} -> LEGACY_CORRECT_ONLY -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi150d/dxiG150d_parent.c:2431
Target: mpf_mfs_addque; enclosing fn dxi_reg_buff_data; ops: ADDQUE(arg2)
Expected: 707  (PATH_VALID)
  - proof: DXI_QNO_DATABUFF=707
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [707] {"ADDED": 1, "OK_MACRO": 1} -> LEGACY_CORRECT_ONLY -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi150d/dxiG_buffqread.c
### /home/chukyu/t-dxi/src/dxi150d/dxiG_buffqread.c:58
Target: mpf_mfs_delque; enclosing fn Dxi_BuffQread; ops: DELQUE(arg2)
Expected: 707  (PATH_VALID)
  - proof: DXI_QNO_DATABUFF=707
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [707] {"ADDED": 1, "OK_MACRO": 1} -> LEGACY_CORRECT_ONLY -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi150d/dxiG_dnqread.c
### /home/chukyu/t-dxi/src/dxi150d/dxiG_dnqread.c:69
Target: mpf_mfs_delque; enclosing fn Dxi_DnQread; ops: DELQUE(arg2)
Expected: {732,733,734,735,736}  (PATH_VALID)
  - proof: filenum[5] active (#else of #if 0) L51: DXI_QNO_GSNDDATA1..5; 4-element variant is DEAD_PATH
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi300d/dxi300d_apdiv.c
### /home/chukyu/t-dxi/src/dxi300d/dxi300d_apdiv.c:317
Target: mpf_mfs_addque; enclosing fn dxi_apdiv_send; ops: ADDQUE(arg2)
Expected: external (config: Dxi_ApdivInfoG[i].qno=strtol, dxi300d_main.c:474)  (PATH_VALID)
  - proof: qno from config data; no static value provable
c-viz: [(no value)] {"DYNAMIC": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-dxi/src/dxi300d/dxi300d_main.c
### /home/chukyu/t-dxi/src/dxi300d/dxi300d_main.c:797
Target: mpf_mfs_getrecm; enclosing fn dxi_kuninitevn; ops: GETREC(arg1)
Expected: 2513  (PATH_VALID)
  - proof: fcb opened via Dxi_UpTbnFileOpen(&fcb,onsub,1) L789 -> fileno[1]=DXI_FNO_UPMNGTON=2513 (dxi_uptbn.c L61/74)
c-viz: [(no value)] {"UNRESOLVED": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi300d/dxi300d_tbnmng.c
### /home/chukyu/t-dxi/src/dxi300d/dxi300d_tbnmng.c:560
Target: mpf_mfs_getrecm; enclosing fn dxi_get_upmng_addr; ops: GETREC(arg1)
Expected: {2503,2513,2520,2522,2526,2528}  (PATH_VALID)
  - proof: Dxi_FcbG global opened via Dxi_UpTbn(2/3)FileOpen (dxi300d_main.c L697-712, dxi300d_tbnmng.c L1285-1301) -> UPMNG/UPMNGTON{,2,3}; legacy 2503 valid but incomplete
c-viz: [(no value)] {"UNRESOLVED": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [2503] {"ADDED": 1, "OK_CONST": 1} -> LEGACY_UNDERAPPROXIMATION -- accepted
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
#### /home/chukyu/t-dxi/src/dxi300d/dxi_upqread.c
### /home/chukyu/t-dxi/src/dxi300d/dxi_upqread.c:75
Target: mpf_mfs_delque; enclosing fn Dxi_UpQread; ops: DELQUE(arg2)
Expected: {701,723,727}  (PATH_VALID)
  - proof: qno=DXI_QNO_RCVDATA/RCVDATA3/RCVDATA2 (701/727/723) on myshu 0/2/else L48-64; cviz {723,727} misses 701 (myshu==0)
c-viz: [ 727;723] {"EXACT": 2} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi310d/dxiG310d_apdiv.c
### /home/chukyu/t-dxi/src/dxi310d/dxiG310d_apdiv.c:224
Target: mpf_mfs_addque; enclosing fn dxi_apdiv_send; ops: ADDQUE(arg2)
Expected: external (config: Dxi_ApdivInfoG[i].qno=strtol)  (PATH_VALID)
  - proof: qno from config data; no static value provable
c-viz: [(no value)] {"DYNAMIC": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-dxi/src/dxi310d/dxiG310d_tbnmng.c
### /home/chukyu/t-dxi/src/dxi310d/dxiG310d_tbnmng.c:457
Target: mpf_mfs_getrecm; enclosing fn dxi_get_upmng_addr; ops: GETREC(arg1)
Expected: {2503,2513}  (PATH_VALID)
  - proof: Dxi_FcbG opened only via Dxi_UpTbnFileOpen (dxiG310d_main.c L202/L221, tbnmng L1086) -> fileno[t_flg] in {UPMNG 2503, UPMNGTON 2513}
c-viz: [(no value)] {"UNRESOLVED": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi400d/dxi400d_main.c
### /home/chukyu/t-dxi/src/dxi400d/dxi400d_main.c:249
Target: mpf_mfs_delque; enclosing fn dxi400dDivide; ops: DELQUE(arg2)
Expected: {721,726,730}  (PATH_VALID)
  - proof: qno=DXI_QNO_TAKEICIRREQ{,2,3} per myshu in dxi400dDividen (L206-221)
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi400d/dxi400d_main.c:278
Target: pmf_forkprocbs_H; enclosing fn dxi400dDivide; ops: FORKPROC(arg1)
Expected: external (cpname param = live CPU name, compared to "ECS-A"/"ECS-B")  (PATH_VALID)
  - proof: cpname is a function parameter fed from external CPU-name source; site L278 (pmf_forkprocbs_H arg1)
c-viz: [(no value)] {"EXTERNAL": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dxi/src/dxi400d/dxi400d_main.c:296
Target: pmf_forkprocbs_H; enclosing fn dxi400dDivide; ops: FORKPROC(arg1)
Expected: external (cpname param)  (PATH_VALID)
  - proof: same cpname parameter; note arg2 procname is literal "dxi510d" but audited arg is arg1
c-viz: [(no value)] {"EXTERNAL": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-dxi/src/dxi500d/dxi500d_main.c
### /home/chukyu/t-dxi/src/dxi500d/dxi500d_main.c:245
Target: mpf_mfs_open; enclosing fn pmf_main_H; ops: READ(arg3); WRITE(arg3)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname (DBLCIRMNG1/2/3) at top of function; fcb opened L245 with fno
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi500d/dxi500d_main.c:253
Target: mpf_mfs_readrecm; enclosing fn pmf_main_H; ops: READREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname (DBLCIRMNG1/2/3) at top of function; fcb opened L245 with fno
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi500d/dxi500d_main.c:269
Target: mpf_mfs_writerecm; enclosing fn pmf_main_H; ops: WRITEREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname (DBLCIRMNG1/2/3) at top of function; fcb opened L245 with fno
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi500d/dxi500d_main.c:282
Target: mpf_mfs_addque; enclosing fn pmf_main_H; ops: ADDQUE(arg2)
Expected: {721,726,730}  (PATH_VALID)
  - proof: qno=DXI_QNO_TAKEICIRREQ{,2,3} per myname
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:260
Target: mpf_mfs_open; enclosing fn pmf_main_H; ops: READ(arg3)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname at function top; open uses fno
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:267
Target: mpf_mfs_readrecm; enclosing fn pmf_main_H; ops: READREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:280
Target: mpf_mfs_open; enclosing fn pmf_main_H; ops: READ(arg3)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname at function top; open uses fno
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:288
Target: mpf_mfs_readrecm; enclosing fn pmf_main_H; ops: READREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:298
Target: mpf_mfs_open; enclosing fn pmf_main_H; ops: READ(arg3); WRITE(arg3)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname at function top; open uses fno
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:306
Target: mpf_mfs_readrecm; enclosing fn pmf_main_H; ops: READREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:313
Target: mpf_mfs_writerecm; enclosing fn pmf_main_H; ops: WRITEREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DXI_FNO_DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:320
Target: mpf_mfs_open; enclosing fn pmf_main_H; ops: READ(arg3)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname at function top; open uses fno
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:328
Target: mpf_mfs_readrecm; enclosing fn pmf_main_H; ops: READREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:361
Target: mpf_mfs_open; enclosing fn pmf_main_H; ops: READ(arg3); WRITE(arg3)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname at function top; open uses fno
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:369
Target: mpf_mfs_readrecm; enclosing fn pmf_main_H; ops: READREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:374
Target: mpf_mfs_writerecm; enclosing fn pmf_main_H; ops: WRITEREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DXI_FNO_DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:381
Target: mpf_mfs_open; enclosing fn pmf_main_H; ops: READ(arg3); WRITE(arg3)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fno=DXI_FNO_DBLCIRMNG{,2,3} per myname at function top; open uses fno
c-viz: [(no value)] {} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:389
Target: mpf_mfs_readrecm; enclosing fn pmf_main_H; ops: READREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:394
Target: mpf_mfs_writerecm; enclosing fn pmf_main_H; ops: WRITEREC(arg1)
Expected: {2516,2518,2524}  (PATH_VALID)
  - proof: fcb opened with fno (DBLCIRMNG{,2,3} per myname) just above each site
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:403
Target: mpf_mfs_addque; enclosing fn pmf_main_H; ops: ADDQUE(arg2)
Expected: {721,726,730}  (PATH_VALID)
  - proof: qno=DXI_QNO_TAKEICIRREQ{,2,3} per myname
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {"UNRESOLVED": 1} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:552
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2516  (PATH_VALID)
  - proof: fcb open L544 DXI_FNO_DBLCIRMNG=2516
c-viz: [2516] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2516] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:563
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2518  (PATH_VALID)
  - proof: fcb2 open L556 DXI_FNO_DBLCIRMNG2=2518
c-viz: [2518] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2518] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:575
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2524  (PATH_VALID)
  - proof: fcb3 open L568 DXI_FNO_DBLCIRMNG3=2524
c-viz: [2524] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2524] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:607
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2516  (PATH_VALID)
  - proof: fcb open L599 DXI_FNO_DBLCIRMNG
c-viz: [2516] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2516] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:613
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2516  (PATH_VALID)
  - proof: fcb open L599 DXI_FNO_DBLCIRMNG
c-viz: [2516] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2516] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:631
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2518  (PATH_VALID)
  - proof: fcb2 open L623 DXI_FNO_DBLCIRMNG2
c-viz: [2518] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2518] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:637
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2518  (PATH_VALID)
  - proof: fcb2 open L623 DXI_FNO_DBLCIRMNG2
c-viz: [2518] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2518] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:655
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2524  (PATH_VALID)
  - proof: fcb3 open L647 DXI_FNO_DBLCIRMNG3
c-viz: [2524] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2524] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:661
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2524  (PATH_VALID)
  - proof: fcb3 open L647 DXI_FNO_DBLCIRMNG3
c-viz: [2524] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2524] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:837
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2516  (PATH_VALID)
  - proof: fcb open L830 DXI_FNO_DBLCIRMNG
c-viz: [2516] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2516] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:843
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2516  (PATH_VALID)
  - proof: fcb open L830 DXI_FNO_DBLCIRMNG
c-viz: [2516] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2516] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:854
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2518  (PATH_VALID)
  - proof: fcb2 open L847 DXI_FNO_DBLCIRMNG2
c-viz: [2518] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2518] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:860
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2518  (PATH_VALID)
  - proof: fcb2 open L847 DXI_FNO_DBLCIRMNG2
c-viz: [2518] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2518] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:871
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2524  (PATH_VALID)
  - proof: fcb3 open L864 DXI_FNO_DBLCIRMNG3
c-viz: [2524] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2524] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:877
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2524  (PATH_VALID)
  - proof: fcb3 open L864 DXI_FNO_DBLCIRMNG3
c-viz: [2524] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2524] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:912
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2516  (PATH_VALID)
  - proof: fcb open L905 DXI_FNO_DBLCIRMNG
c-viz: [2516] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2516] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:916
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2516  (PATH_VALID)
  - proof: fcb open L905 DXI_FNO_DBLCIRMNG
c-viz: [2516] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2516] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:927
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2518  (PATH_VALID)
  - proof: fcb2 open L920 DXI_FNO_DBLCIRMNG2
c-viz: [2518] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2518] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:931
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2518  (PATH_VALID)
  - proof: fcb2 open L920 DXI_FNO_DBLCIRMNG2
c-viz: [2518] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2518] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:942
Target: mpf_mfs_readrecm; enclosing fn dxi510dTimechk; ops: READREC(arg1)
Expected: 2524  (PATH_VALID)
  - proof: fcb3 open L935 DXI_FNO_DBLCIRMNG3
c-viz: [2524] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2524] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:946
Target: mpf_mfs_writerecm; enclosing fn dxi510dTimechk; ops: WRITEREC(arg1)
Expected: 2524  (PATH_VALID)
  - proof: fcb3 open L935 DXI_FNO_DBLCIRMNG3
c-viz: [2524] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2524] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi800d/dxi800d_main.c
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_main.c:136
Target: mpf_mfs_readrecm; enclosing fn main; ops: READREC(arg1)
Expected: 2506  (PATH_VALID)
  - proof: fcb open L131 DXI_FNO_UPTRACE=2506
c-viz: [2506] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2506] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_main.c:139
Target: mpf_mfs_writerecm; enclosing fn main; ops: WRITEREC(arg1)
Expected: 2506  (PATH_VALID)
  - proof: fcb open L131 DXI_FNO_UPTRACE=2506
c-viz: [2506] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2506] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_main.c:148
Target: mpf_mfs_readrecm; enclosing fn main; ops: READREC(arg1)
Expected: 2507  (PATH_VALID)
  - proof: fcb open L143 DXI_FNO_DNTRACE=2507
c-viz: [2507] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2507] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_main.c:151
Target: mpf_mfs_writerecm; enclosing fn main; ops: WRITEREC(arg1)
Expected: 2507  (PATH_VALID)
  - proof: fcb open L143 DXI_FNO_DNTRACE=2507
c-viz: [2507] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2507] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_main.c:282
Target: mpf_mfs_getrecm; enclosing fn dxi_get_tracedef; ops: GETREC(arg1)
Expected: 2505  (PATH_VALID)
  - proof: fcb open L272 DXI_FNO_TRCMNG=2505
c-viz: [2505] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2505] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:115
Target: mpf_mfs_openm; enclosing fn dxi_trace_regist; ops: WRITE(arg3)
Expected: {2506,2507}  (PATH_VALID)
  - proof: filenum[2]={DXI_FNO_UPTRACE 2506, DXI_FNO_DNTRACE 2507} L86; openm filenum[updn]
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:300
Target: mpf_mfs_readrecm; enclosing fn dxi_upinfo_regist; ops: READREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: dxi_upinfo_regist(fcb param): sole caller dxi_trace_regist (L195) with fcb opened L115 filenum[updn]
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:318
Target: mpf_mfs_writerecm; enclosing fn dxi_upinfo_regist; ops: WRITEREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: dxi_upinfo_regist(fcb param): sole caller dxi_trace_regist (L195) with fcb opened L115 filenum[updn]
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:330
Target: mpf_mfs_writerecm; enclosing fn dxi_upinfo_regist; ops: WRITEREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: dxi_upinfo_regist(fcb param): sole caller dxi_trace_regist (L195) with fcb opened L115 filenum[updn]
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:403
Target: mpf_mfs_readrecm; enclosing fn dxi_dninfo_regist; ops: READREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: dxi_dninfo_regist(fcb param): sole caller dxi_trace_regist (L214) with fcb opened L115 filenum[updn]
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:421
Target: mpf_mfs_writerecm; enclosing fn dxi_dninfo_regist; ops: WRITEREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: dxi_dninfo_regist(fcb param): sole caller dxi_trace_regist (L214) with fcb opened L115 filenum[updn]
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:433
Target: mpf_mfs_writerecm; enclosing fn dxi_dninfo_regist; ops: WRITEREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: dxi_dninfo_regist(fcb param): sole caller dxi_trace_regist (L214) with fcb opened L115 filenum[updn]
c-viz: [(no value)] {"EXTERNAL": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi900/dxi900_ms.c
### /home/chukyu/t-dxi/src/dxi900/dxi900_ms.c:146
Target: mpf_mfs_getrecm; enclosing fn dxi_make_ms_data; ops: GETREC(arg1)
Expected: 2510  (PATH_VALID)
  - proof: fcb open L126 DXI_FNO_ITCMSDEF=2510
c-viz: [2510] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2510] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi900/dxi900_ss.c
### /home/chukyu/t-dxi/src/dxi900/dxi900_ss.c:148
Target: mpf_mfs_getrecm; enclosing fn dxi_make_ss_data; ops: GETREC(arg1)
Expected: 2515  (PATH_VALID)
  - proof: fcb open L129 DXI_FNO_ITCSSDEF; active define is 2515 (dxi_const.h L249; 2511 is inside #if 0 L247); legacy 2511 impossible
c-viz: [2515] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [2511] {"CONFLICT": 1, "OK_MACRO": 1} -> LEGACY_OVERAPPROXIMATION -- rejected value(s)
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi901/dxi901_ms.c
### /home/chukyu/t-dxi/src/dxi901/dxi901_ms.c:136
Target: mpf_mfs_getrecm; enclosing fn dxi_make_ms_data; ops: GETREC(arg1)
Expected: 2510  (PATH_VALID)
  - proof: fcb open L119 DXI_FNO_ITCMSDEF=2510
c-viz: [2510] {"EXACT": 1} -> BOTH_CORRECT_SAME -- accepted
legacy: [2510] {"ADDED": 1, "OK_MACRO": 1} -> BOTH_CORRECT_SAME -- accepted
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/dxi901/dxi901_ss.c
### /home/chukyu/t-dxi/src/dxi901/dxi901_ss.c:123
Target: mpf_mfs_getrecm; enclosing fn dxi_make_ss_data; ops: GETREC(arg1)
Expected: 2515  (PATH_VALID)
  - proof: fcb open L106 DXI_FNO_ITCSSDEF=2515 (2511 define disabled by #if 0)
c-viz: [2515] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [2511] {"CONFLICT": 1, "OK_MACRO": 1} -> LEGACY_OVERAPPROXIMATION -- rejected value(s)
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c
### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c:286
Target: mpf_mfs_readrecm; enclosing fn Dxi_DnTbnFileCtrl; ops: READREC(arg1)
Expected: {2504,2521,2527}  (PATH_VALID)
  - proof: Dxi_DnTbnFileCtrl(fcb param): callers pass &DxiDnTbnfcbG opened via Dxi_DnTbn(2/3)FileOpen (DxiMNP.c L544-560 -> DXI_FNO_DNMNG/DNMNG2/DNMNG3 = 2504/2521/2527; DxiMNPSim.c L577 -> 2504)
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 7} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c:298
Target: mpf_mfs_writerecm; enclosing fn Dxi_DnTbnFileCtrl; ops: WRITEREC(arg1)
Expected: {2504,2521,2527}  (PATH_VALID)
  - proof: Dxi_DnTbnFileCtrl(fcb param): callers pass &DxiDnTbnfcbG opened via Dxi_DnTbn(2/3)FileOpen (DxiMNP.c L544-560 -> DXI_FNO_DNMNG/DNMNG2/DNMNG3 = 2504/2521/2527; DxiMNPSim.c L577 -> 2504)
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 7} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c:308
Target: mpf_mfs_readrecm; enclosing fn Dxi_DnTbnFileCtrl; ops: READREC(arg1)
Expected: {2504,2521,2527}  (PATH_VALID)
  - proof: Dxi_DnTbnFileCtrl(fcb param): callers pass &DxiDnTbnfcbG opened via Dxi_DnTbn(2/3)FileOpen (DxiMNP.c L544-560 -> DXI_FNO_DNMNG/DNMNG2/DNMNG3 = 2504/2521/2527; DxiMNPSim.c L577 -> 2504)
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 7} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c:325
Target: mpf_mfs_writerecm; enclosing fn Dxi_DnTbnFileCtrl; ops: WRITEREC(arg1)
Expected: {2504,2521,2527}  (PATH_VALID)
  - proof: Dxi_DnTbnFileCtrl(fcb param): callers pass &DxiDnTbnfcbG opened via Dxi_DnTbn(2/3)FileOpen (DxiMNP.c L544-560 -> DXI_FNO_DNMNG/DNMNG2/DNMNG3 = 2504/2521/2527; DxiMNPSim.c L577 -> 2504)
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 7} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c:332
Target: mpf_mfs_readrecm; enclosing fn Dxi_DnTbnFileCtrl; ops: READREC(arg1)
Expected: {2504,2521,2527}  (PATH_VALID)
  - proof: Dxi_DnTbnFileCtrl(fcb param): callers pass &DxiDnTbnfcbG opened via Dxi_DnTbn(2/3)FileOpen (DxiMNP.c L544-560 -> DXI_FNO_DNMNG/DNMNG2/DNMNG3 = 2504/2521/2527; DxiMNPSim.c L577 -> 2504)
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 7} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c:348
Target: mpf_mfs_readrecm; enclosing fn Dxi_DnTbnFileCtrl; ops: READREC(arg1)
Expected: {2504,2521,2527}  (PATH_VALID)
  - proof: Dxi_DnTbnFileCtrl(fcb param): callers pass &DxiDnTbnfcbG opened via Dxi_DnTbn(2/3)FileOpen (DxiMNP.c L544-560 -> DXI_FNO_DNMNG/DNMNG2/DNMNG3 = 2504/2521/2527; DxiMNPSim.c L577 -> 2504)
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 7} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c:364
Target: mpf_mfs_writerecm; enclosing fn Dxi_DnTbnFileCtrl; ops: WRITEREC(arg1)
Expected: {2504,2521,2527}  (PATH_VALID)
  - proof: Dxi_DnTbnFileCtrl(fcb param): callers pass &DxiDnTbnfcbG opened via Dxi_DnTbn(2/3)FileOpen (DxiMNP.c L544-560 -> DXI_FNO_DNMNG/DNMNG2/DNMNG3 = 2504/2521/2527; DxiMNPSim.c L577 -> 2504)
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 7} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
### /home/chukyu/t-dxi/src/libdxi/DxiDntbn.c:388
Target: mpf_mfs_writerecm; enclosing fn Dxi_DnTbnFileCtrl; ops: WRITEREC(arg1)
Expected: {2504,2521,2527}  (PATH_VALID)
  - proof: Dxi_DnTbnFileCtrl(fcb param): callers pass &DxiDnTbnfcbG opened via Dxi_DnTbn(2/3)FileOpen (DxiMNP.c L544-560 -> DXI_FNO_DNMNG/DNMNG2/DNMNG3 = 2504/2521/2527; DxiMNPSim.c L577 -> 2504)
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 7} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
#### /home/chukyu/t-dxi/src/libdxi/DxiGChgMode.c
### /home/chukyu/t-dxi/src/libdxi/DxiGChgMode.c:215
Target: mpf_mfs_getrecm; enclosing fn DxiGChgMode; ops: GETREC(arg1)
Expected: (no active caller)  (DEAD_PATH)
  - proof: DxiGChgMode / DxiG_itcmodectrlbit: no callers of either function in current source tree; (in-function open would give 2554)
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dxi/src/libdxi/DxiGChgMode.c:362
Target: mpf_mfs_getrecm; enclosing fn DxiG_itcmodectrlbit; ops: GETREC(arg1)
Expected: (no active caller)  (DEAD_PATH)
  - proof: DxiGChgMode / DxiG_itcmodectrlbit: no callers of either function in current source tree; (in-function open would give 2554)
c-viz: [(no value)] {"UNREACHABLE": 1} -> UNDECIDED -- no value reported
legacy: [(no value)] {} -> UNDECIDED -- no value reported
Confidence: medium
Cause tags: INSUFFICIENT_EVIDENCE
#### /home/chukyu/t-dxi/src/libdxi/DxiGGetMode.c
### /home/chukyu/t-dxi/src/libdxi/DxiGGetMode.c:95
Target: mpf_mfs_getrecm; enclosing fn DxiGGetMode; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L83 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiGGetMode.c:245
Target: mpf_mfs_getrecm; enclosing fn DxiGGetMode_Dnno; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L231 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiGetAdr.c
### /home/chukyu/t-dxi/src/libdxi/DxiGetAdr.c:133
Target: mpf_mfs_getrecm; enclosing fn DxiGetMS; ops: GETREC(arg1)
Expected: 2510  (PATH_VALID)
  - proof: fcb open L124 DXI_FNO_ITCMSDEF=2510
c-viz: [2510] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiGetAdr.c:185
Target: mpf_mfs_getrecm; enclosing fn DxiGetSS; ops: GETREC(arg1)
Expected: 2515  (PATH_VALID)
  - proof: fcb open L176 DXI_FNO_ITCSSDEF=2515
c-viz: [2515] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiGetLS.c
### /home/chukyu/t-dxi/src/libdxi/DxiGetLS.c:75
Target: mpf_mfs_readrecm; enclosing fn DxiGetLanSts; ops: READREC(arg1)
Expected: 2502  (PATH_VALID)
  - proof: active #else branch open L66 openm_H DXI_FNO_CIRMNG=2502 (openm variant is #if 0 dead)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiGetMode.c
### /home/chukyu/t-dxi/src/libdxi/DxiGetMode.c:90
Target: mpf_mfs_readrecm; enclosing fn DxiGetMode; ops: READREC(arg1)
Expected: 2502  (PATH_VALID)
  - proof: active #else branch open L81 openm_H DXI_FNO_CIRMNG=2502
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiGetPInf.c
### /home/chukyu/t-dxi/src/libdxi/DxiGetPInf.c:54
Target: mpf_mfs_getrecm; enclosing fn DxiGetPacInfo; ops: GETREC(arg1)
Expected: 2501  (PATH_VALID)
  - proof: fcb open L46 DXI_FNO_PACDEF=2501
c-viz: [2501] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiGetTen.c
### /home/chukyu/t-dxi/src/libdxi/DxiGetTen.c:117
Target: mpf_mfs_openm_H; enclosing fn DxiGetTen; ops: OPEN_LOCK(arg2)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fileno set per shu at L69-77: DXI_FNO_CIRMNG/CIRMNG2/CIRMNG3; active open L117 openm_H (both inner #if 0 branches dead)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiGetTen.c:126
Target: mpf_mfs_readrecm; enclosing fn DxiGetTen; ops: READREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fileno set per shu at L69-77: DXI_FNO_CIRMNG/CIRMNG2/CIRMNG3; active open L117 openm_H (both inner #if 0 branches dead)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiItcReq2.c
### /home/chukyu/t-dxi/src/libdxi/DxiItcReq2.c:555
Target: mpf_mfs_getrecm; enclosing fn DxiItcReqSub2; ops: GETREC(arg1)
Expected: {2502,2517}  (PATH_VALID)
  - proof: fcb opened per mysnd: CIRMNG (L541) / CIRMNG2 (L548); no CIRMNG3 branch in this file
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiItcReq2.c:711
Target: mpf_mfs_addque; enclosing fn DxiItcReqSub2; ops: ADDQUE(arg2)
Expected: {708} U {702,703,724,725,728,729,732..}  (PATH_VALID)
  - proof: DxiEnqEvent2(filenum param): called by DxiSndHdr with DXI_QNO_SNDDMS=708 (L200) and DxiSndQueNum[] entries (702/703/724/725/728/729/... per DxiGlobal.c)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
#### /home/chukyu/t-dxi/src/libdxi/DxiMNPSim.c
### /home/chukyu/t-dxi/src/libdxi/DxiMNPSim.c:1242
Target: mpf_mfs_openm; enclosing fn DxiUpSetTbnSim; ops: OPEN_LOCK(arg3)
Expected: {2503,2513}  (PATH_VALID)
  - proof: filenoup[2]={DXI_FNO_UPMNG 2503, DXI_FNO_UPMNGTON 2513} L1224; filerec 0/1 by t_flg
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiMNPSim.c:1249
Target: mpf_mfs_getrecm; enclosing fn DxiUpSetTbnSim; ops: GETREC(arg1)
Expected: {2503,2513}  (PATH_VALID)
  - proof: filenoup[2]={DXI_FNO_UPMNG 2503, DXI_FNO_UPMNGTON 2513} L1224; filerec 0/1 by t_flg
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiQWrtEvn.c
### /home/chukyu/t-dxi/src/libdxi/DxiQWrtEvn.c:72
Target: mpf_mfs_addque; enclosing fn DxiEnqEvent; ops: ADDQUE(arg2)
Expected: {708} U {702,703,724,725,728,729,732..}  (PATH_VALID)
  - proof: DxiEnqEvent(filenum param): DxiSndHdr callers pass DXI_QNO_SNDDMS=708 (valid, reported) plus DxiSndQueNum[] queue numbers (not reported)
c-viz: [708] {"EXACT": 1, "EXTERNAL": 10, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
#### /home/chukyu/t-dxi/src/libdxi/DxiSimReq.c
### /home/chukyu/t-dxi/src/libdxi/DxiSimReq.c:739
Target: mpf_mfs_addque; enclosing fn DxiSimReq_Test; ops: ADDQUE(arg2)
Expected: 701  (PATH_VALID)
  - proof: DXI_QNO_RCVDATA=701
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiSndHdr.c
### /home/chukyu/t-dxi/src/libdxi/DxiSndHdr.c:265
Target: mpf_mfs_getrecm; enclosing fn DxiSendHdr; ops: GETREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fcb opened per myshu/mysnd: CIRMNG/CIRMNG2/CIRMNG3 (L239/247/256)
c-viz: [ 2517; 2523;2502] {"EXACT": 3, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiSndHdr.c:427
Target: mpf_mfs_readrecm; enclosing fn DxiChkTenso; ops: READREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fcb reopened per mysnd with cpuname: CIRMNG/CIRMNG2/CIRMNG3 (L401/409/418)
c-viz: [ 2517; 2523;2502] {"EXACT": 3, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiSndHdr.c:687
Target: mpf_mfs_readrecm; enclosing fn DxiSendSimHdr; ops: READREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L678 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiSndSim.c
### /home/chukyu/t-dxi/src/libdxi/DxiSndSim.c:146
Target: mpf_mfs_addque; enclosing fn DxiJudSendSim; ops: ADDQUE(arg2)
Expected: 1101  (PATH_VALID)
  - proof: DXI_QNO_SIMRCVQ=1101
c-viz: [1101] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxi/DxiWtrace.c
### /home/chukyu/t-dxi/src/libdxi/DxiWtrace.c:108
Target: mpf_mfs_getrecm; enclosing fn Dxi_Wrttrace; ops: GETREC(arg1)
Expected: 2505  (PATH_VALID)
  - proof: fcb open L101 DXI_FNO_TRCMNG=2505
c-viz: [2505] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiWtrace.c:215
Target: mpf_mfs_addque; enclosing fn Dxi_Wrttrace; ops: ADDQUE(arg2)
Expected: 704  (PATH_VALID)
  - proof: DXI_QNO_TRACE=704
c-viz: [704] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxi/DxiWtrace.c:293
Target: mpf_mfs_getrecm; enclosing fn Dxi_WrttraceSim; ops: GETREC(arg1)
Expected: 2505  (PATH_VALID)
  - proof: fcb open L286 DXI_FNO_TRCMNG=2505
c-viz: [2505] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c
### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c:146
Target: mpf_mfs_getrecm; enclosing fn DxiG_ksctrlbit; ops: GETREC(arg1)
Expected: {2552,2554}  (PATH_VALID)
  - proof: fcb opened per type: GCIRMNG (L97) if type!=ITCMODE else GITCMNG (L105)
c-viz: [ 2554;2552] {"EXACT": 2, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c:463
Target: mpf_mfs_getrecm; enclosing fn DxiG_CheckMode; ops: GETREC(arg1)
Expected: 2552  (PATH_VALID)
  - proof: fcb open L455 DXI_FNO_GCIRMNG=2552
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c:543
Target: mpf_mfs_getrecm; enclosing fn DxiG_CheckSendMode; ops: GETREC(arg1)
Expected: 2552  (PATH_VALID)
  - proof: fcb open L535 DXI_FNO_GCIRMNG=2552
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c:639
Target: mpf_mfs_getrecm; enclosing fn DxiG_CheckItcMode; ops: GETREC(arg1)
Expected: 2552  (PATH_VALID)
  - proof: fcb open L631 DXI_FNO_GCIRMNG=2552
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c:741
Target: mpf_mfs_getrecm; enclosing fn DxiG_SetModeData; ops: GETREC(arg1)
Expected: 2552  (PATH_VALID)
  - proof: fcb open L733 DXI_FNO_GCIRMNG=2552
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c:805
Target: mpf_mfs_getrecm; enclosing fn DxiG_CheckItcSimMode; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L797 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1, "UNREACHABLE": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cpumode.c
### /home/chukyu/t-dxi/src/libdxiinside/dxiG_cpumode.c:118
Target: mpf_mfs_getrecm; enclosing fn Dxi_GCpuMode; ops: GETREC(arg1)
Expected: 2555  (PATH_VALID)
  - proof: fcb open L72 DXI_FNO_GCPUMODE=2555
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:100
Target: mpf_mfs_openm; enclosing fn Dxi_Dksctrlbit; ops: OPEN_LOCK(arg3)
Expected: 2514  (PATH_VALID)
  - proof: openm L100 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:108
Target: mpf_mfs_getrecm; enclosing fn Dxi_Dksctrlbit; ops: GETREC(arg1)
Expected: 2514  (PATH_VALID)
  - proof: fcb opened L100 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:378
Target: mpf_mfs_openm; enclosing fn Dxi_DCheckMode; ops: OPEN_LOCK(arg3)
Expected: 2514  (PATH_VALID)
  - proof: openm L378 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:393
Target: mpf_mfs_getrecm; enclosing fn Dxi_DCheckMode; ops: GETREC(arg1)
Expected: 2514  (PATH_VALID)
  - proof: fcb opened L378 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:593
Target: mpf_mfs_openm; enclosing fn Dxi_DCheckSendMode; ops: OPEN_LOCK(arg3)
Expected: 2514  (PATH_VALID)
  - proof: openm L593 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:601
Target: mpf_mfs_getrecm; enclosing fn Dxi_DCheckSendMode; ops: GETREC(arg1)
Expected: 2514  (PATH_VALID)
  - proof: fcb opened L593 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:688
Target: mpf_mfs_openm; enclosing fn Dxi_DCheckItcMode; ops: OPEN_LOCK(arg3)
Expected: 2514  (PATH_VALID)
  - proof: openm L688 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:696
Target: mpf_mfs_getrecm; enclosing fn Dxi_DCheckItcMode; ops: GETREC(arg1)
Expected: 2514  (PATH_VALID)
  - proof: fcb opened L688 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:801
Target: mpf_mfs_openm; enclosing fn Dxi_DSetModeData; ops: OPEN_LOCK(arg3)
Expected: 2514  (PATH_VALID)
  - proof: openm L801 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirdmsmng.c:809
Target: mpf_mfs_getrecm; enclosing fn Dxi_DSetModeData; ops: GETREC(arg1)
Expected: 2514  (PATH_VALID)
  - proof: fcb opened L801 DXI_FNO_CIRDMSMNG=2514
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:120
Target: mpf_mfs_openm; enclosing fn Dxi_ksctrlbit; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fno set per myshu = DXI_FNO_CIRMNG/CIRMNG2/CIRMNG3 (L~107-118); cviz (2502, 2523) misses 2517 (myshu==1)
c-viz: [ 2523;2502] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:126
Target: mpf_mfs_getrecm; enclosing fn Dxi_ksctrlbit; ops: GETREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fcb opened L120 with fno in {2502,2517,2523} per myshu; cviz misses 2517
c-viz: [ 2523;2502] {"EXACT": 2, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:407
Target: mpf_mfs_openm; enclosing fn Dxi_CheckMode; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fno set per myshu = DXI_FNO_CIRMNG/CIRMNG2/CIRMNG3 (L~107-118); cviz (2502, 2523) misses 2517 (myshu==1)
c-viz: [ 2523;2502] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:413
Target: mpf_mfs_getrecm; enclosing fn Dxi_CheckMode; ops: GETREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fcb opened L407 with fno in {2502,2517,2523} per myshu; cviz misses 2517
c-viz: [ 2523;2502] {"EXACT": 2, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:657
Target: mpf_mfs_openm; enclosing fn Dxi_CheckSendMode; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fno set per myshu = DXI_FNO_CIRMNG/CIRMNG2/CIRMNG3 (L~107-118); cviz (2502, 2523) misses 2517 (myshu==1)
c-viz: [ 2523;2502] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:663
Target: mpf_mfs_getrecm; enclosing fn Dxi_CheckSendMode; ops: GETREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fcb opened L657 with fno in {2502,2517,2523} per myshu; cviz misses 2517
c-viz: [ 2523;2502] {"EXACT": 2, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:766
Target: mpf_mfs_openm; enclosing fn Dxi_CheckItcMode; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fno set per myshu = DXI_FNO_CIRMNG/CIRMNG2/CIRMNG3 (L~107-118); cviz (2502, 2523) misses 2517 (myshu==1)
c-viz: [ 2523;2502] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:772
Target: mpf_mfs_getrecm; enclosing fn Dxi_CheckItcMode; ops: GETREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fcb opened L766 with fno in {2502,2517,2523} per myshu; cviz misses 2517
c-viz: [ 2523;2502] {"EXACT": 2, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:898
Target: mpf_mfs_openm; enclosing fn Dxi_SetModeData; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fno set per myshu = DXI_FNO_CIRMNG/CIRMNG2/CIRMNG3 (L~107-118); cviz (2502, 2523) misses 2517 (myshu==1)
c-viz: [ 2523;2502] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_cirmng.c:904
Target: mpf_mfs_getrecm; enclosing fn Dxi_SetModeData; ops: GETREC(arg1)
Expected: {2502,2517,2523}  (PATH_VALID)
  - proof: fcb opened L898 with fno in {2502,2517,2523} per myshu; cviz misses 2517
c-viz: [ 2523;2502] {"EXACT": 2, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxiinside/dxi_dblcirreq.c
### /home/chukyu/t-dxi/src/libdxiinside/dxi_dblcirreq.c:100
Target: pmf_forkproc_H; enclosing fn Dxi_Dblcirreq; ops: FORKPROC(arg1)
Expected: "dxi500d","dxi501d","dxi502d"  (PATH_VALID)
  - proof: prcname=DXI_NAME_DBLCIRMNG1/2/3 per myshu just above site (dxi_const.h: dxi500d/dxi501d/dxi502d)
c-viz: [(no value)] {"EXTERNAL": 1, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/src/libdxiinside/dxi_initmng.c
### /home/chukyu/t-dxi/src/libdxiinside/dxi_initmng.c:72
Target: mpf_mfs_openm; enclosing fn Dxi_GetInitMng; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2512,2519,2525}  (PATH_VALID)
  - proof: fno set per shu = DXI_FNO_INITMNG/INITMNG2/INITMNG3 (2512/2519/2525); cviz {2512,2525} misses 2519 (shu==1)
c-viz: [ 2525;2512] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: BRANCH_MERGE_ERROR
### /home/chukyu/t-dxi/src/libdxiinside/dxi_initmng.c:80
Target: mpf_mfs_getrecm; enclosing fn Dxi_GetInitMng; ops: GETREC(arg1)
Expected: {2512,2519,2525}  (PATH_VALID)
  - proof: fno set per shu = DXI_FNO_INITMNG/INITMNG2/INITMNG3 (2512/2519/2525); cviz {2512,2525} misses 2519 (shu==1)
c-viz: [ 2525;2512] {"EXACT": 2, "UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: BRANCH_MERGE_ERROR
#### /home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c
### /home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:74
Target: mpf_mfs_openm; enclosing fn Dxi_UpTbnFileOpen; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2503,2513}  (PATH_VALID)
  - proof: Dxi_UpTbnFileOpen: fileno[2]={UPMNG 2503, UPMNGTON 2513}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:111
Target: mpf_mfs_openm; enclosing fn Dxi_UpTbn2FileOpen; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2520,2522}  (PATH_VALID)
  - proof: Dxi_UpTbn2FileOpen: fileno[2]={UPMNG2 2520, UPMNGTON2 2522}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:148
Target: mpf_mfs_openm; enclosing fn Dxi_UpTbn3FileOpen; ops: OPEN_LOCK(arg3); WRITE(arg3)
Expected: {2526,2528}  (PATH_VALID)
  - proof: Dxi_UpTbn3FileOpen: fileno[2]={UPMNG3 2526, UPMNGTON3 2528}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:211
Target: mpf_mfs_getrecm; enclosing fn Dxi_UpTbnFileCtrl; ops: GETREC(arg1)
Expected: {2503,2513,2520,2522,2526,2528}  (PATH_VALID)
  - proof: Dxi_UpTbnFileCtrl(fcb param): callers open fcb via the three UpTbn*FileOpen wrappers above
c-viz: [(no value)] {"UNREACHABLE": 1, "UNRESOLVED": 6} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: medium
Cause tags: MISSING_CALLER_EDGE
#### /home/chukyu/t-dxi/tool/dxi700/dxi700_cb.c
### /home/chukyu/t-dxi/tool/dxi700/dxi700_cb.c:627
Target: mpf_mfs_openm; enclosing fn dxi_trace_setchg_flow; ops: OPEN_LOCK(arg3)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2]={{UPTRACE 2506,DNTRACE 2507},{UPTRACECP 2508,DNTRACECP 2509}} L416; index [Dxi_now_trc_fkindG][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_cb.c:632
Target: mpf_mfs_readrecm; enclosing fn dxi_trace_setchg_flow; ops: READREC(arg1)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2]={{UPTRACE 2506,DNTRACE 2507},{UPTRACECP 2508,DNTRACECP 2509}} L416; index [Dxi_now_trc_fkindG][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_cb.c:1331
Target: mpf_mfs_openm; enclosing fn dxi_trace_fileclr_flow; ops: OPEN_LOCK(arg3)
Expected: {2506,2507}  (PATH_VALID)
  - proof: filenum[0][i] = {DXI_FNO_UPTRACE 2506, DXI_FNO_DNTRACE 2507}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_cb.c:1336
Target: mpf_mfs_readrecm; enclosing fn dxi_trace_fileclr_flow; ops: READREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: filenum[0][i] = {DXI_FNO_UPTRACE 2506, DXI_FNO_DNTRACE 2507}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_cb.c:1339
Target: mpf_mfs_writerecm; enclosing fn dxi_trace_fileclr_flow; ops: WRITEREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: filenum[0][i] = {DXI_FNO_UPTRACE 2506, DXI_FNO_DNTRACE 2507}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_cb.c:1535
Target: mpf_mfs_getrecm; enclosing fn dxi_trace_mnginfo_get; ops: GETREC(arg1)
Expected: 2505  (CONFIG_VALID=MP)
  - proof: site inside #ifdef MP; fcb opened L1525/1527 DXI_FNO_TRCMNG=2505 (either MP branch); MP macro not defined in source tree -> branch requires build -DMP
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_cb.c:1579
Target: mpf_mfs_getrecm; enclosing fn dxi_trace_mnginfo_set; ops: GETREC(arg1)
Expected: 2505  (PATH_VALID)
  - proof: fcb opened L1569/1571 DXI_FNO_TRCMNG=2505 (MP and non-MP branches)
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/tool/dxi700/dxi700_dt.c
### /home/chukyu/t-dxi/tool/dxi700/dxi700_dt.c:181
Target: mpf_mfs_openm; enclosing fn dxi_trace_data_bunkai; ops: OPEN_LOCK(arg3)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2] L154 = {{UPTRACE 2506,DNTRACE 2507},{UPTRACECP 2508,DNTRACECP 2509}}; [fkind][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_dt.c:187
Target: mpf_mfs_readrecm; enclosing fn dxi_trace_data_bunkai; ops: READREC(arg1)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2] L154 = {{UPTRACE 2506,DNTRACE 2507},{UPTRACECP 2508,DNTRACECP 2509}}; [fkind][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_dt.c:189
Target: mpf_mfs_readrecm; enclosing fn dxi_trace_data_bunkai; ops: READREC(arg1)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2] L154 = {{UPTRACE 2506,DNTRACE 2507},{UPTRACECP 2508,DNTRACECP 2509}}; [fkind][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi700/dxi700_dt.c:2262
Target: mpf_mfs_readrecm; enclosing fn dxi_id_data_get; ops: READREC(arg1)
Expected: 2501  (PATH_VALID)
  - proof: fcb open L2252 DXI_FNO_PACDEF=2501
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/tool/dxi710/dxi700_cb.c
### /home/chukyu/t-dxi/tool/dxi710/dxi700_cb.c:641
Target: mpf_mfs_openm; enclosing fn dxi_trace_setchg_flow; ops: OPEN_LOCK(arg3)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2] = {{UPTRACE,DNTRACE},{UPTRACECP,DNTRACECP}}; index [Dxi_now_trc_fkindG][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_cb.c:648
Target: mpf_mfs_readrecm; enclosing fn dxi_trace_setchg_flow; ops: READREC(arg1)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2] = {{UPTRACE,DNTRACE},{UPTRACECP,DNTRACECP}}; index [Dxi_now_trc_fkindG][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_cb.c:1404
Target: mpf_mfs_openm; enclosing fn dxi_trace_fileclr_flow; ops: OPEN_LOCK(arg3)
Expected: {2506,2507}  (PATH_VALID)
  - proof: filenum[0][i] = {2506, 2507}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_cb.c:1418
Target: mpf_mfs_readrecm; enclosing fn dxi_trace_fileclr_flow; ops: READREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: filenum[0][i] = {2506, 2507}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_cb.c:1421
Target: mpf_mfs_writerecm; enclosing fn dxi_trace_fileclr_flow; ops: WRITEREC(arg1)
Expected: {2506,2507}  (PATH_VALID)
  - proof: filenum[0][i] = {2506, 2507}
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_cb.c:1633
Target: mpf_mfs_getrecm; enclosing fn dxi_trace_mnginfo_get; ops: GETREC(arg1)
Expected: 2505  (CONFIG_VALID=MP)
  - proof: site inside #ifdef MP; fcb opened L1622/1624 DXI_FNO_TRCMNG=2505
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_cb.c:1681
Target: mpf_mfs_getrecm; enclosing fn dxi_trace_mnginfo_set; ops: GETREC(arg1)
Expected: 2505  (PATH_VALID)
  - proof: fcb opened L1671/1673 DXI_FNO_TRCMNG=2505
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/tool/dxi710/dxi700_dt.c
### /home/chukyu/t-dxi/tool/dxi710/dxi700_dt.c:176
Target: mpf_mfs_openm; enclosing fn dxi_trace_data_bunkai; ops: OPEN_LOCK(arg3)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2] = trace file numbers; [fkind][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_dt.c:182
Target: mpf_mfs_readrecm; enclosing fn dxi_trace_data_bunkai; ops: READREC(arg1)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2] = trace file numbers; [fkind][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_dt.c:184
Target: mpf_mfs_readrecm; enclosing fn dxi_trace_data_bunkai; ops: READREC(arg1)
Expected: {2506,2507,2508,2509}  (PATH_VALID)
  - proof: filenum[2][2] = trace file numbers; [fkind][i]
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxi710/dxi700_dt.c:2623
Target: mpf_mfs_readrecm; enclosing fn dxi_id_data_get; ops: READREC(arg1)
Expected: 2501  (PATH_VALID)
  - proof: fcb open L2613 DXI_FNO_PACDEF=2501
c-viz: [(no value)] {"UNREACHABLE": 1} -> CVIZ_UNDERAPPROXIMATION -- no value reported
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/tool/dxiinf/dxiinf.c
### /home/chukyu/t-dxi/tool/dxiinf/dxiinf.c:60
Target: mpf_mfs_getrecm; enclosing fn main; ops: GETREC(arg1)
Expected: 2502  (PATH_VALID)
  - proof: fcb open L52 DXI_FNO_CIRMNG=2502
c-viz: [2502] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/dxiinf/dxiinf.c:258
Target: mpf_mfs_getrecm; enclosing fn main; ops: GETREC(arg1)
Expected: 2512  (PATH_VALID)
  - proof: fcb open L250 DXI_FNO_INITMNG=2512 (L174 open is commented out)
c-viz: [2512] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/tool/itcmode/itcmode.c
### /home/chukyu/t-dxi/tool/itcmode/itcmode.c:64
Target: mpf_mfs_getrecm; enclosing fn dxi_dspmode; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L59/L165 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/itcmode/itcmode.c:170
Target: mpf_mfs_getrecm; enclosing fn dxi_setmode; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L59/L165 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
#### /home/chukyu/t-dxi/tool/itcten/itcten.c
### /home/chukyu/t-dxi/tool/itcten/itcten.c:84
Target: mpf_mfs_getrecm; enclosing fn dxi_dspten; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L79/L119 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### /home/chukyu/t-dxi/tool/itcten/itcten.c:124
Target: mpf_mfs_getrecm; enclosing fn dxi_setten; ops: GETREC(arg1)
Expected: 2554  (PATH_VALID)
  - proof: fcb open L79/L119 DXI_FNO_GITCMNG=2554
c-viz: [2554] {"EXACT": 1} -> CVIZ_CORRECT_ONLY -- accepted
legacy: [(no value)] {} -> LEGACY_UNDERAPPROXIMATION -- no value reported
Confidence: high
Cause tags: none
### Notable examples
**c-viz correct & legacy not (strongest):**
- /home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c:146 - both type branches (GCIRMNG 2552 / GITCMNG 2554) resolved exactly; legacy reported nothing.
- /home/chukyu/t-dxi/src/dxi150d/dxiG150d_main.c:1042 - c-viz correctly picked 2552 (DXI_FNO_GCIRMNG, open L1021) and did NOT include 2554 from the earlier open in the same function: clean handle-identity tracking; legacy nothing.
- /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:444/446 - 2820 (ChaOnlWorkTMNo, hit-branch open L433) resolved; legacy nothing.
**legacy correct & c-viz not (strongest):**
- /home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c:2298 and :2316 - DXI_QNO_DATABUFF=707 resolved by legacy (OK_MACRO); c-viz reported no value at all.
- /home/chukyu/t-dxi/src/dxi150d/dxiG150d_child.c:936 - DXI_QNO_GRCVDATA=731; c-viz nothing.
- /home/chukyu/t-cha/src/cha100d/cha100dMain.c:229 - 2802 (ChaOnlineManageNo, open L223); c-viz marked the site UNREACHABLE.
**both correct (strongest):**
- /home/chukyu/t-dxi/src/dxi110d/dxi110d_main.c:668 - full 3-way set {2502,2517,2523} (CIRMNG/CIRMNG2/CIRMNG3 by myshu) reported identically by both.
- /home/chukyu/t-dxi/src/dxi510d/dxi510d_main.c:552..946 - 21 fcb/fcb2/fcb3 sites, each exactly 2516/2518/2524 in both pipelines.
**c-viz overapproximation (strongest):**
- /home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c:458/470/477 (and 657/663, 996/1008/1015, 1127/1133) - c-viz value `0` for iOpenFileNo. ChaGetFileInfo() at L452/L651/L990/L1118 sets iOpenFileNo to a ChaOnlineTMNo01..17 / ChaOnlineSVNo01..17 constant and the open follows only on success (error path returns), so 0 cannot reach the open. True set: TM files {2845,2846,2847,2857..2870} or SV files {2803..2807,2812,2813,2821,2822,2832..2835,2840,2850..2852}.
**legacy overapproximation (strongest):**
- /home/chukyu/t-dxi/src/dxi900/dxi900_ss.c:148 and /home/chukyu/t-dxi/src/dxi901/dxi901_ss.c:123 - legacy 2511 comes from the `#if 0`-disabled `#define DXI_FNO_ITCSSDEF 2511` (t-dxi/include/dxi_const.h L247); the active define is 2515 (L249, "Chg by M.Murayama 14/03/21"). c-viz 2515 is correct.
### Unfinished / open items
No sites were left unfinished; all 330 sites / 359 rows received verdicts. Qualifications to be aware of:
- UNDECIDED sites (17): values are runtime/config-fed (Dxi_RepfailInfoG[i].qno, Dxi_ApdivInfoG[i].qno via strtol of config data; external CPU names at the two pmf_forkprocbs_H sites in dxi400d_main.c), functions with no active caller in the current tree (ChaWriteRecm, ChaKenRecm, ChaGmnKenRecm, DxiGChgMode, DxiG_itcmodectrlbit), or a macro absent from current headers (ClrChaOnlineSV.c: fno = ChaOnlineSVNo, undefined in t-cha/include - value unresolvable against active source). One site (libChaCom/ChaCase.c:579/588, ChaReadRecn) is UNDECIDED because its caller passes a runtime-set iOpenFileNo that was not fully traced.
- Medium/low-confidence sites: caller-enumerated sets for wrapper-parameter functions (ChaReadRecm/ChaReadTm/ChaReadSv/ChaWriteRecn in libChaCom/ChaCase.c; DxiEnqEvent/DxiEnqEvent2; Dxi_DnTbnFileCtrl; Dxi_UpTbnFileCtrl; Dxi_FcbG users) assume the enumerated call sites are the complete active caller set; additional callers outside this tree would only enlarge the expected sets (verdicts remain underapproximations for both pipelines).
- `#ifdef MP` sites (dxi700/dxi710 dxi700_cb.c 1535/1633): the MP macro is not defined anywhere in the source tree; those values are labelled CONFIG_VALID=MP. The file number (2505) is the same in both MP branches, so the value is correct regardless of the flag; only the liveness of that exact call line depends on the build flag.


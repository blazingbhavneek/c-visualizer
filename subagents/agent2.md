# Role

You are one of 6 subagents (this one is **2**) in a source-code correctness
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
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/subagents/agent2_claims.csv
- Full per-site comparison (for cross-checking only; do not audit outside your batch):
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1_sites.csv
- c-visualizer raw facts:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index/discovery_facts.csv
- legacy proof:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/valueflow_proof.csv
- C source root: /home/chukyu

Batch statistics (already computed — reconcile them against your CSV on start):
- claim rows in your batch: 441
- unique (file, line) sites: 383

Your batch covers these source directories (relative to /home/chukyu):
- /home/chukyu/t-dyn/src/dyn232d
- /home/chukyu/t-dyn/src/dyn402d
- /home/chukyu/t-dyn/src/dyn430d
- /home/chukyu/t-dyn/src/dyn562
- /home/chukyu/t-dyn/src/dyn563
- /home/chukyu/t-dyn/src/dyn710
- /home/chukyu/t-dyn/src/dyn810d
- /home/chukyu/t-dyn/src/dyn812d
- /home/chukyu/t-dyn/src/libDynDspCom
- /home/chukyu/t-dyn/src/libDynRe

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
one of the 441 claim rows (all 383 unique sites) receives a verdict —
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

### Batch summary

- Subagent: 2 (t-dyn dyn232d/402d/430d/562/563/710/810d/812d/libDynDspCom/libDynRe)
- Claim rows in batch: 441; unique (file,line) sites: 383
- Sites audited: 383 / 383 (100%)

Per-verdict counts (per unique site):
  - BOTH_CORRECT_SAME: 40
  - CVIZ_CORRECT_ONLY: 186
  - LEGACY_CORRECT_ONLY: 0
  - BOTH_CORRECT_DIFFERENT: 0
  - CVIZ_OVERAPPROXIMATION: 0
  - LEGACY_OVERAPPROXIMATION: 0
  - BOTH_UNDERAPPROXIMATION: 67
  - CVIZ_UNDERAPPROXIMATION: 0
  - LEGACY_UNDERAPPROXIMATION: 0
  - BOTH_WRONG: 0
  - BOTH_INCOMPLETE: 0
  - UNDECIDED: 90

Per-cause-tag counts (attached to wrong/incomplete/undecided sites):
  - INSUFFICIENT_EVIDENCE: 105
  - MISSING_ASSIGNMENT_EDGE: 57

Pipeline precision & coverage (this batch):
  - Precision (accepted reported values / all reported concrete values): 271/271 = 100.0%  (no reported value was found to be an overapproximation)
  - Coverage (source-resolvable sites whose value was reported by >=1 pipeline / source-resolvable sites): 226/293 = 77.1%
    - Note: the remaining resolvable-but-unreported sites are the BOTH_UNDERAPPROXIMATION cases (macro/define FNO or PROC_NAME that both pipelines left unresolved). The UNDECIDED remainder are data-dependent helper/variable FNOs (lookup-table or runtime-computed) where no single concrete value is statically provable.

Key cross-cutting findings:
  1. No c-visualizer or legacy value in this batch was a source-invalid (overapproximated) FNO. Every EXACT/OK value emitted by either pipeline matches the FNO that actually binds the handle (or open arg) at the site.
  2. Legacy's provenance LINE NUMBERS are stale/incorrect (e.g. it cites dyn232dMsg.c:6033 in a file that is 545 lines; dyn232dReEneCtl.c:24565 in a 739-line file). The legacy pipeline clearly ran against a different/monolithic source snapshot. Its FNO macro selections are nonetheless usually correct; only its line references and its numeric emission are unreliable.
  3. c-visualizer's UNREACHABLE/UNRESOLVED/EXTERNAL statuses (the both_unresolved rows) correspond to (a) macro/define FNOs it failed to numerically emit (both missed a provable constant) and (b) FNOs computed by the lookup helpers DynREGet{Sch,SchKK,SchKKLC,Pfm}fno() or held in runtime variables - genuinely data-dependent.
  4. FNO numeric values verified against the active header t-dyn/include/Dyn/DynReEneFileDef.h (enum, e.g. DynReGrpIdxFNO=3916, DynReCtlMntStaFNO=3986, DynReKoTeiHtSetFNO=4013). External constants (DifStatusNo=2022) verified against t-dif/include/dif/Dif.h.

### Site verdicts

(One block per unique (file,line) site, grouped by directory, in batch-file order. For a `&fcb`-style handle the "Expected" value is the FNO of the *live* open binding that handle at the site — the most recent `mpf_mfs_open*(&handle,...)` after the last `mpf_mfs_close(&handle)`. For `OPEN`/`READ`/`WRITE`/`OPEN_LOCK` sites the value is the FNO argument of the open itself. FNO numbers below are the concrete file numbers; the macro name is shown in the proof line.)

#### dyn232d

### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:134
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dMsg(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:134
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:142
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:134 mpf_mfs_open*(&fcb, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:158
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [3910]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:149 mpf_mfs_open*(&fcb, DynReSchSetTkFNO)
c-viz: [3910] (status {"EXACT": 1}) | legacy: [3910] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:169
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dMsg(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:169
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:177
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:169 mpf_mfs_open*(&fcb, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:212
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dMsg(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:212
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:220
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:212 mpf_mfs_open*(&fcb, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:222
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dMsg(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:222
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:230
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:222 mpf_mfs_open*(&fcb, DynREGetSchKKLCfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:241
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:235 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1}) | legacy: [3916] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:245
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dMsg(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:245
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:253
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:245 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:262
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:256 mpf_mfs_open*(&fcb, DynReCtlMntStaFNO)
c-viz: [3986] (status {"EXACT": 1}) | legacy: [3986] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:270
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:264 mpf_mfs_open*(&fcb, DynReCtlMntSetFNO)
c-viz: [3987] (status {"EXACT": 1}) | legacy: [3987] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:279
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:273 mpf_mfs_open*(&fcb, DynReKoteMntStaFNO)
c-viz: [3989] (status {"EXACT": 1}) | legacy: [3989] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:287
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:281 mpf_mfs_open*(&fcb, DynReKoteMntSetFNO)
c-viz: [3990] (status {"EXACT": 1}) | legacy: [3990] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:298
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dMsg(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:290 mpf_mfs_open*(&fcb, DynReKoTeiHtSetFNO)
c-viz: [4013] (status {"EXACT": 1}) | legacy: [4013] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:119
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dReEneCtl(); expr DynReITCInfFNO
Expected: [3938]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:119
c-viz: [3938] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:127
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb
Expected: [3938]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:119 mpf_mfs_open*(&fcb, DynReITCInfFNO)
c-viz: [3938] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:149
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb
Expected: [3909]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:142 mpf_mfs_open*(&fcb, DynReTaikoSetFNO)
c-viz: [3909] (status {"EXACT": 1}) | legacy: [3909] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:163
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dReEneCtl(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:163
c-viz: [3919] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:171
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:163 mpf_mfs_open*(&fcb, DynReCtlStaFNO)
c-viz: [3919] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:176
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dReEneCtl(); expr DynReKansiStaFNO
Expected: [3945]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:176
c-viz: [3945] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:185
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb_Kansi
Expected: [3945]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:176 mpf_mfs_open*(&fcb_Kansi, DynReKansiStaFNO)
c-viz: [3945] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:565
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dReEneCtl(); expr DynReOutKanSetFNO
Expected: [3943]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:565
c-viz: [3943] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:568
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb_KanSet
Expected: [3943]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:565 mpf_mfs_open*(&fcb_KanSet, DynReOutKanSetFNO)
c-viz: [3943] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:579
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn232dReEneCtl(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:579
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:582
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb_Pfm
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:579 mpf_mfs_open*(&fcb_Pfm, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:617
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb_Pfm
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:579 mpf_mfs_open*(&fcb_Pfm, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:628
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - note: fcb live-open @163 DynReCtlStaFNO(3919); close@221 is inside iJisso!=1 branch (non-dominant). use-after-close on that branch = source defect
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn232d/dyn232dReEneCtl.c:631
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn232dReEneCtl(); expr &fcb_Kansi
Expected: [3945]  (PATH_VALID)
  - note: fcb_Kansi live-open @176 DynReKansiStaFNO(3945); close@223 in branch
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE

#### dyn402d

### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:87
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dKanCtl(); expr DynReITCInfFNO
Expected: [3938]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:87
c-viz: [3938] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:95
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dKanCtl(); expr &fcb
Expected: [3938]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:87 mpf_mfs_open*(&fcb, DynReITCInfFNO)
c-viz: [3938] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:211
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dFile(); expr DynReOutKanStaFNO
Expected: [3944]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:211
c-viz: [(none/status-only)] (status {}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:220
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dFile(); expr DynReKansiStaFNO
Expected: [3945]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:220
c-viz: [(none/status-only)] (status {}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:230
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dFile(); expr DynReOutKanSetFNO
Expected: [3943]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:230
c-viz: [(none/status-only)] (status {}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:248
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn402dFile(); expr &fcb_OutKanSta
Expected: [3944]  (PATH_VALID)
  - note: fcb_OutKanSta open @211 DynReOutKanStaFNO(3944); closes@223/233 in error branches only
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:253
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn402dFile(); expr &fcb_KansiSta
Expected: [3945]  (PATH_VALID)
  - note: fcb_KansiSta open @220 DynReKansiStaFNO(3945)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:261
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dFile(); expr &fcb_OutKanSta
Expected: [3944]  (PATH_VALID)
  - note: fcb_OutKanSta open @211 DynReOutKanStaFNO(3944)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:263
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dFile(); expr &fcb_KansiSta
Expected: [3945]  (PATH_VALID)
  - note: fcb_KansiSta open @220 DynReKansiStaFNO(3945)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:265
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dFile(); expr &fcb_OutKanSet
Expected: [3943]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanCtl.c:230 mpf_mfs_open*(&fcb_OutKanSet, DynReOutKanSetFNO)
c-viz: [3943] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:134
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dKanValGet(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:134
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:142
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dKanValGet(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:134 mpf_mfs_open*(&fcb, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:186
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dKanValGet(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:186
c-viz: [3919] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:194
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dKanValGet(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:186 mpf_mfs_open*(&fcb, DynReCtlStaFNO)
c-viz: [3919] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:315
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:310 mpf_mfs_open*(&Refcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1}) | legacy: [3916] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:319
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dGetSchVal(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:319
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:326
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:319 mpf_mfs_open*(&Refcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:335
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [3986]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:330 mpf_mfs_open*(&Refcb, DynReCtlMntStaFNO)
c-viz: [3986] (status {"EXACT": 1}) | legacy: [3986] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:342
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [3987]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:337 mpf_mfs_open*(&Refcb, DynReCtlMntSetFNO)
c-viz: [3987] (status {"EXACT": 1}) | legacy: [3987] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:351
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:346 mpf_mfs_open*(&Refcb, DynReKoteMntStaFNO)
c-viz: [3989] (status {"EXACT": 1}) | legacy: [3989] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:358
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:353 mpf_mfs_open*(&Refcb, DynReKoteMntSetFNO)
c-viz: [3990] (status {"EXACT": 1}) | legacy: [3990] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:369
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:362 mpf_mfs_open*(&Refcb, DynReKoTeiHtSetFNO)
c-viz: [4013] (status {"EXACT": 1}) | legacy: [4013] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:424
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dGetSchVal(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:424
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:431
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:424 mpf_mfs_open*(&Refcb, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:445
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dGetSchVal(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:445
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:450
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:445 mpf_mfs_open*(&Refcb, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:452
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn402dGetSchVal(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:452
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:457
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn402dGetSchVal(); expr &Refcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn402d/dyn402dKanValGet.c:452 mpf_mfs_open*(&Refcb, DynREGetSchKKLCfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE

#### dyn430d

### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:178
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePmfLogInfFNO
Expected: [3969]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:178
c-viz: [3969] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:183
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3969]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:178 mpf_mfs_open*(&fcb, DynRePmfLogInfFNO)
c-viz: [3969] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:190
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3969]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:178 mpf_mfs_open*(&fcb, DynRePmfLogInfFNO)
c-viz: [3969] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:201
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePfmStaFNO
Expected: [3939]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:201
c-viz: [3939] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:209
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3939]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:201 mpf_mfs_open*(&fcb, DynRePfmStaFNO)
c-viz: [3939] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:223
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:223
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:231
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:223 mpf_mfs_open*(&fcb, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:235
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePfmSetFNO
Expected: [3940]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:235
c-viz: [3940] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:243
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3940]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:235 mpf_mfs_open*(&fcb, DynRePfmSetFNO)
c-viz: [3940] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:247
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:247
c-viz: [3919] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:255
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:247 mpf_mfs_open*(&fcb, DynReCtlStaFNO)
c-viz: [3919] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:261
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePmfLogInfFNO
Expected: [3969]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:261
c-viz: [3969] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:266
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3969]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:261 mpf_mfs_open*(&fcb, DynRePmfLogInfFNO)
c-viz: [3969] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:361
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:361
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:369
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:361 mpf_mfs_open*(&fcb, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:373
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePfmSetFNO
Expected: [3940]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:373
c-viz: [3940] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:381
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3940]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:373 mpf_mfs_open*(&fcb, DynRePfmSetFNO)
c-viz: [3940] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:387
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePmfLogInfFNO
Expected: [3969]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:387
c-viz: [3969] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:392
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3969]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:387 mpf_mfs_open*(&fcb, DynRePmfLogInfFNO)
c-viz: [3969] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:399
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn430dPfmCtrl(); expr DynRePfmStaFNO
Expected: [3939]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:399
c-viz: [3939] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:407
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn dyn430dPfmCtrl(); expr &fcb
Expected: [3939]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:399 mpf_mfs_open*(&fcb, DynRePfmStaFNO)
c-viz: [3939] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none

#### dyn562

### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:543
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:537 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1}) | legacy: [3916] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:546
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn562CSVRecvprc(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:546
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:556
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:546 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:576
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:570 mpf_mfs_open*(&fcb, DynReCtlMntStaFNO)
c-viz: [3986] (status {"EXACT": 1}) | legacy: [3986] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:586
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:580 mpf_mfs_open*(&fcb, DynReCtlMntSetFNO)
c-viz: [3987] (status {"EXACT": 1}) | legacy: [3987] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:599
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcb
Expected: [3988]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:591 mpf_mfs_open*(&fcb, DynReKoteMainteFNO)
c-viz: [3988] (status {"EXACT": 1}) | legacy: [3988] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:609
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:603 mpf_mfs_open*(&fcb, DynReKoteMntStaFNO)
c-viz: [3989] (status {"EXACT": 1}) | legacy: [3989] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:619
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:611 mpf_mfs_open*(&fcb, DynReKoteMntSetFNO)
c-viz: [3990] (status {"EXACT": 1}) | legacy: [3990] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:631
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:624 mpf_mfs_open*(&fcb, DynReKoTeiHtSetFNO)
c-viz: [4013] (status {"EXACT": 1}) | legacy: [4013] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:706
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcbSchKK
Expected: [data-dependent (helper/variable)]  (PATH_VALID)
  - proof: no live open (branch/close)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:717
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn562CSVRecvprc(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:717
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:724
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcbSch
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:717 mpf_mfs_open*(&fcbSch, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:743
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcbSch
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:717 mpf_mfs_open*(&fcbSch, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:767
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn562CSVRecvprc(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:767
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:771
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn562CSVRecvprc(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:771
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:779
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcbSchKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:771 mpf_mfs_open*(&fcbSchKK, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 2}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 2})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:925
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcbSchKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:771 mpf_mfs_open*(&fcbSchKK, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 2}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 2})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:937
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn562CSVRecvprc(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:937
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:943
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcbSch
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:937 mpf_mfs_open*(&fcbSch, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:962
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn562CSVRecvprc(); expr &fcbSch
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:937 mpf_mfs_open*(&fcbSch, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn562/dyn562Main.c:134
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReTrnMngInfFNO
Expected: [1074]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn562/dyn562Main.c:134
c-viz: [1074] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562Main.c:142
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562Main.c:134 mpf_mfs_open*(&fcb, DynReTrnMngInfFNO)
c-viz: [1074] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn562/dyn562Main.c:145
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn562/dyn562Main.c:134 mpf_mfs_open*(&fcb, DynReTrnMngInfFNO)
c-viz: [1074] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none

#### dyn563

### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:544
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:538 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1}) | legacy: [3916] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:547
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn563CSVRecvprc(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:547
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:557
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:547 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:577
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:571 mpf_mfs_open*(&fcb, DynReCtlMntStaFNO)
c-viz: [3986] (status {"EXACT": 1}) | legacy: [3986] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:587
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:581 mpf_mfs_open*(&fcb, DynReCtlMntSetFNO)
c-viz: [3987] (status {"EXACT": 1}) | legacy: [3987] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:600
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcb
Expected: [3988]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:592 mpf_mfs_open*(&fcb, DynReKoteMainteFNO)
c-viz: [3988] (status {"EXACT": 1}) | legacy: [3988] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:610
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:604 mpf_mfs_open*(&fcb, DynReKoteMntStaFNO)
c-viz: [3989] (status {"EXACT": 1}) | legacy: [3989] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:620
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:612 mpf_mfs_open*(&fcb, DynReKoteMntSetFNO)
c-viz: [3990] (status {"EXACT": 1}) | legacy: [3990] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:633
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:625 mpf_mfs_open*(&fcb, DynReKoTeiHtSetFNO)
c-viz: [4013] (status {"EXACT": 1}) | legacy: [4013] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:708
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcbSchKK
Expected: [data-dependent (helper/variable)]  (PATH_VALID)
  - proof: no live open (branch/close)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:719
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn563CSVRecvprc(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:719
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:726
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcbSch
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:719 mpf_mfs_open*(&fcbSch, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:745
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcbSch
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:719 mpf_mfs_open*(&fcbSch, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:769
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn563CSVRecvprc(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:769
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:773
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn563CSVRecvprc(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:773
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:781
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcbSchKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:773 mpf_mfs_open*(&fcbSchKK, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 2}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 2})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:927
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcbSchKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:773 mpf_mfs_open*(&fcbSchKK, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 2}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 2})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:939
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn563CSVRecvprc(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:939
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:945
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcbSch
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:939 mpf_mfs_open*(&fcbSch, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:964
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn563CSVRecvprc(); expr &fcbSch
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563FtpRcv.c:939 mpf_mfs_open*(&fcbSch, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn563/dyn563Main.c:134
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReTrnMngInfFNO
Expected: [1074]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn563/dyn563Main.c:134
c-viz: [1074] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563Main.c:142
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563Main.c:134 mpf_mfs_open*(&fcb, DynReTrnMngInfFNO)
c-viz: [1074] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn563/dyn563Main.c:145
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn563/dyn563Main.c:134 mpf_mfs_open*(&fcb, DynReTrnMngInfFNO)
c-viz: [1074] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none

#### dyn710

### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:292
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710GetData(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:292
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:295
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:292 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:314
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710GetData(); expr DynRePtnSetNO
Expected: [3942]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:314
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:315
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3942]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:314 mpf_mfs_open*(&fcb, DynRePtnSetNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:327
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710GetData(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:327
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:328
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:327 mpf_mfs_open*(&fcb, DynReCtlStaFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:339
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710GetData(); expr DynREGetPfmfno(nFnoidx[0]
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:339
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:340
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:339 mpf_mfs_open*(&fcb, DynREGetPfmfno(nFnoidx[0])
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:343
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710GetData(); expr DynREGetPfmfno(nFnoidx[1]
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:343
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:344
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:343 mpf_mfs_open*(&fcb, DynREGetPfmfno(nFnoidx[1])
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:368
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710GetData(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:368
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:372
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:368 mpf_mfs_open*(&fcb, DynRePfmCtlFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:390
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [1037]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:387 mpf_mfs_open*(&fcb, DynAdvCtlStaCmnFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:405
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710GetData(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:405
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:406
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3946]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:405 mpf_mfs_open*(&fcb, DynAdvCtlStaIndFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:438
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3988]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:435 mpf_mfs_open*(&fcb, DynReKoteMainteFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:454
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3980]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:453 mpf_mfs_open*(&fcb, DynReSetDspTgtFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:465
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3909]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:464 mpf_mfs_open*(&fcb, DynReTaikoSetFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:475
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:474 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:484
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:483 mpf_mfs_open*(&fcb, DynReCtlMntStaFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:489
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:488 mpf_mfs_open*(&fcb, DynReCtlMntSetFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:500
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:499 mpf_mfs_open*(&fcb, DynReKoteMntStaFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:505
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:502 mpf_mfs_open*(&fcb, DynReKoteMntSetFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:516
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710GetData(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:515 mpf_mfs_open*(&fcb, DynReKoTeiHtSetFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:652
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710UpdSchSetBufKKmg(); expr DynREGetSchfno(g_nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:652
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:653
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710UpdSchSetBufKKmg(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:652 mpf_mfs_open*(&fcb, DynREGetSchfno(g_nFnoidx)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:664
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710UpdSchSetBufKKmg(); expr DynREGetSchKKfno(g_nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:664
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:665
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710UpdSchSetBufKKmg(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:664 mpf_mfs_open*(&fcb, DynREGetSchKKfno(g_nFnoidxKK)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:667
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn710UpdSchSetBufKKmg(); expr DynREGetSchKKLCfno(g_nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:667
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:668
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn710UpdSchSetBufKKmg(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710Init.c:667 mpf_mfs_open*(&fcb, DynREGetSchKKLCfno(g_nFnoidxKK)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn710/dyn710ScheduleCsvDlg.c:510
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn710ShowCsvReadResult(); expr &fcb
Expected: [1500]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn710/dyn710ScheduleCsvDlg.c:509 mpf_mfs_open*(&fcb, DynReSchCsvRed2FNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE

#### dyn810d

### /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:242
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn810dCreateBody(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:242
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:251
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn810dCreateBody(); expr DynREGetPfmfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:251
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:269
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn810dCreateBody(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:269
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:278
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn810dCreateBody(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:278
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:294
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn810dCreateBody(); expr &fcb2
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:251 mpf_mfs_open*(&fcb2, DynREGetPfmfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:297
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn810dCreateBody(); expr &fcb
Expected: [data-dependent (helper/variable)]  (PATH_VALID)
  - proof: no live open (branch/close)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:301
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn810dCreateBody(); expr &fcb3
Expected: [data-dependent (helper/variable)]  (PATH_VALID)
  - proof: no live open (branch/close)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:302
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn810dCreateBody(); expr &fcb4
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:278 mpf_mfs_open*(&fcb4, DynREGetSchKKLCfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:220
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:214 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1}) | legacy: [3916] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:223
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:223
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:231
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:223 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:242
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:236 mpf_mfs_open*(&fcb, DynReCtlMntStaFNO)
c-viz: [3986] (status {"EXACT": 1}) | legacy: [3986] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:250
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:244 mpf_mfs_open*(&fcb, DynReCtlMntSetFNO)
c-viz: [3987] (status {"EXACT": 1}) | legacy: [3987] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:260
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:254 mpf_mfs_open*(&fcb, DynReKoteMntStaFNO)
c-viz: [3989] (status {"EXACT": 1}) | legacy: [3989] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:270
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:262 mpf_mfs_open*(&fcb, DynReKoteMntSetFNO)
c-viz: [3990] (status {"EXACT": 1}) | legacy: [3990] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:281
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:275 mpf_mfs_open*(&fcb, DynReKoTeiHtSetFNO)
c-viz: [4013] (status {"EXACT": 1}) | legacy: [4013] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:340
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReHESStaUpdDFNO
Expected: [3972]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:340
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:346
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb2
Expected: [3972]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:340 mpf_mfs_open*(&fcb2, DynReHESStaUpdDFNO)
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:367
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb2
Expected: [3972]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:340 mpf_mfs_open*(&fcb2, DynReHESStaUpdDFNO)
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:377
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReHESStaUpdDFNO
Expected: [3972]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:377
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:383
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb2
Expected: [3972]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:377 mpf_mfs_open*(&fcb2, DynReHESStaUpdDFNO)
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:523
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb2
Expected: [3972]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn810d/dyn810dMain.c:377 mpf_mfs_open*(&fcb2, DynReHESStaUpdDFNO)
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none

#### dyn812d

### /home/chukyu/t-dyn/src/dyn812d/dyn812dCsvSendQ.c:60
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn812dCsvSendQ(); expr DynReTrnDataInfFNO
Expected: [1073]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dCsvSendQ.c:60
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dCsvSendQ.c:75
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn812dCsvSendQ(); expr &fcb
Expected: [1073]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dCsvSendQ.c:60 mpf_mfs_open*(&fcb, DynReTrnDataInfFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:267
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReSndStaDFSFNO
Expected: [3949]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:267
c-viz: [3949] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:274
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3949]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:267 mpf_mfs_open*(&fcb, DynReSndStaDFSFNO)
c-viz: [3949] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:279
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReHESStaUpdDFNO
Expected: [3972]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:279
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:285
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3972]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:279 mpf_mfs_open*(&fcb, DynReHESStaUpdDFNO)
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:420
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3972]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:279 mpf_mfs_open*(&fcb, DynReHESStaUpdDFNO)
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:431
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReHESStaUpdDFNO
Expected: [3972]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:431
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:437
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3972]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:431 mpf_mfs_open*(&fcb, DynReHESStaUpdDFNO)
c-viz: [3972] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:446
Target: mpf_mfs_open_H(...), arg 2; enclosing fn pmf_main_H(); expr DynReSndStaDFSFNO
Expected: [3949]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:446
c-viz: [3949] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:453
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn pmf_main_H(); expr &fcb
Expected: [3949]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dMain.c:446 mpf_mfs_open*(&fcb, DynReSndStaDFSFNO)
c-viz: [3949] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:141
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:135 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1}) | legacy: [3916] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:145
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn812dSavePfmKbt(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:145
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:155
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:145 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:165
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:160 mpf_mfs_open*(&fcb, DynReCtlMntStaFNO)
c-viz: [3986] (status {"EXACT": 1}) | legacy: [3986] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:172
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:167 mpf_mfs_open*(&fcb, DynReCtlMntSetFNO)
c-viz: [3987] (status {"EXACT": 1}) | legacy: [3987] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:181
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:176 mpf_mfs_open*(&fcb, DynReKoteMntStaFNO)
c-viz: [3989] (status {"EXACT": 1}) | legacy: [3989] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:190
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:183 mpf_mfs_open*(&fcb, DynReKoteMntSetFNO)
c-viz: [3990] (status {"EXACT": 1}) | legacy: [3990] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:203
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:195 mpf_mfs_open*(&fcb, DynReKoTeiHtSetFNO)
c-viz: [4013] (status {"EXACT": 1}) | legacy: [4013] (status {"ALREADY_PRESENT": 1, "OK_CONST": 1})
Verdict: BOTH_CORRECT_SAME  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:252
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn812dSavePfmKbt(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:252
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:257
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn812dSavePfmKbt(); expr DynREGetPfmfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:257
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:268
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:257 mpf_mfs_open*(&fcb, DynREGetPfmfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:283
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn812dSavePfmKbt(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:283
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:290
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn812dSavePfmKbt(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:290
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:303
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb2
Expected: [data-dependent (helper/variable)]  (PATH_VALID)
  - proof: no live open (branch/close)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:308
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcbKK
Expected: [data-dependent (helper/variable)]  (PATH_VALID)
  - proof: no live open (branch/close)
c-viz: [(none/status-only)] (status {"UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {"OK_CONST": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:309
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcbKK2
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:290 mpf_mfs_open*(&fcbKK2, DynREGetSchKKLCfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:499
Target: mpf_mfs_open_H(...), arg 2; enclosing fn dyn812dSavePfmKbt(); expr DynREGetPfmfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:499
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:508
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:499 mpf_mfs_open*(&fcb, DynREGetPfmfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:556
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn dyn812dSavePfmKbt(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/dyn812d/dyn812dSavePfmKbt.c:499 mpf_mfs_open*(&fcb, DynREGetPfmfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {"UNRESOLVED": 1})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE

#### libDynDspCom

### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:151
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdatePGCtlSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:212
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateGrpCtlSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:285
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateScheSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:343
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdatePtnSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:398
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateKanSetSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:443
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateAdvCmnSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:491
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateSireiTSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:528
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateRlSvSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:565
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateAtEmeSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:602
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateEmeKanCmn(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:666
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateEmeKanInd(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:706
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateTaikoSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:756
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateScheSetTk(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:793
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateEmeKanCTk(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:836
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateEmeKanITk(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:873
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateSetDspTgt(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:930
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateAdvKanInd(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:967
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateGrpSetCmn(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:1000
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynInitScheSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:1034
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynInitPtnSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:1530
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynTransReq(); expr PROC_NAME_RELAY
Expected: [dyn501d]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn501d']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:1557
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynTransReq(); expr PROC_NAME_RELAY
Expected: [dyn501d]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn501d']
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:1460
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynTransReq(); expr DynReTrnDataInfFNO
Expected: [1073]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:1460
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:1466
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynTransReq(); expr &fcb
Expected: [1073]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:1460 mpf_mfs_open*(&fcb, DynReTrnDataInfFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE

#### libDynRe

### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:78
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateScheColor(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:174
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateGrpSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:222
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateKoTeiHtSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:282
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateOutStaSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:342
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateKanStaSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:401
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateCtlMainte(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:463
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateCtlMntSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:513
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateKoteMainte(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:564
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateKoteMntSet(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:611
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateKoteMainteAdd(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:656
Target: pmf_forkproc_H(...), arg 1; enclosing fn DynUpdateKoteMainteDel(); expr PROC_NAME
Expected: [dyn600]  (PATH_VALID)
  - proof: PROC_NAME/PROC_NAME_RELAY local `#define` -> ['dyn600']
c-viz: [dyn600] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReMsgSub.c:118
Target: pmf_forkprocbs_H(...), arg 1; enclosing fn DynReMsgSub(); expr ?
Expected: [data-dependent (helper/variable)]  (PATH_VALID)
  - proof: PROC name literal
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:175
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynAdvReadAdvCtlStaCmn(); expr &fcb
Expected: [1037]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:170 mpf_mfs_open*(&fcb, DynAdvCtlStaCmnFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:193
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynAdvWriteAdvCtlStaCmn(); expr &fcb
Expected: [1037]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:188 mpf_mfs_open*(&fcb, DynAdvCtlStaCmnFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:214
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynAdvReadAdvCtlStaInd(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:214
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:219
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynAdvReadAdvCtlStaInd(); expr &fcb
Expected: [3946]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:214 mpf_mfs_open*(&fcb, DynAdvCtlStaIndFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:240
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynAdvWriteAdvCtlStaInd(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:240
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:245
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynAdvWriteAdvCtlStaInd(); expr &fcb
Expected: [3946]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynAdvFunc.c:240 mpf_mfs_open*(&fcb, DynAdvCtlStaIndFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynRe/DynREGetGtypeOfId.c:93
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynREGetGtypeOfId(); expr DynReCtlInfFNO
Expected: [3918]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynREGetGtypeOfId.c:93
c-viz: [3918] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynREGetGtypeOfId.c:99
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynREGetGtypeOfId(); expr &fcb
Expected: [3918]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynREGetGtypeOfId.c:93 mpf_mfs_open*(&fcb, DynReCtlInfFNO)
c-viz: [3918] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:88
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynREGetScheKKPos(); expr &fcb
Expected: [1489]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:80 mpf_mfs_open*(&fcb, DynReSchStaKKFNO)
c-viz: [1489] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:98
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynREGetSchePos(); expr DynReSchStaFNO
Expected: [3920]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:98
c-viz: [3920] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:106
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynREGetSchePos(); expr &fcb
Expected: [3920]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:98 mpf_mfs_open*(&fcb, DynReSchStaFNO)
c-viz: [3920] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:160
Target: mpf_mfs_open_H(...), arg 2; enclosing fn No(); expr DynReSchStaFNO
Expected: [3920]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:160
c-viz: [3920] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:167
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn No(); expr &fcb
Expected: [3920]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:160 mpf_mfs_open*(&fcb, DynReSchStaFNO)
c-viz: [3920] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynRERequest.c:71
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynRERequest(); expr DynReCtlInfFNO
Expected: [3918]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynRERequest.c:71
c-viz: [3918] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynRERequest.c:78
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynRERequest(); expr &fcb
Expected: [3918]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynRERequest.c:71 mpf_mfs_open*(&fcb, DynReCtlInfFNO)
c-viz: [3918] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:46
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReEneOutStaGet(); expr DynReOutStaFNO
Expected: [3937]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:46
c-viz: [3937] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:62
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReEneOutStaGet(); expr &SFcbRE
Expected: [3937]  (PATH_VALID)
  - note: SFcbRE open @46 DynReOutStaFNO(3937); close@56 in early-return branch, non-dominant
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1, "UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:66
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReEneOutStaGet(); expr &SFcbRE
Expected: [3937]  (PATH_VALID)
  - note: SFcbRE open @46 DynReOutStaFNO(3937)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1, "UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:131
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynReEneOutStaPut(); expr &SFcbRE
Expected: [3937]  (PATH_VALID)
  - note: SFcbRE is file-static FCB (line27) opened in sibling DynReEneOutStaGet @46 DynReOutStaFNO(3937); cross-function handle
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1, "UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:143
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynReEneOutStaPut(); expr &SFcbRE
Expected: [3937]  (PATH_VALID)
  - note: SFcbRE static FCB open @46 DynReOutStaFNO(3937); close@138 in invalid-index branch
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1, "UNRESOLVED": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReGetAlznSirei.c:59
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGetAlznSirei(); expr &fcb
Expected: [4012]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetAlznSirei.c:54 mpf_mfs_open*(&fcb, DynReCtlStaAlznFNO)
c-viz: [4012] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:69
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGetCtlMainte(); expr DynReCtlInfFNO
Expected: [3918]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:69
c-viz: [3918] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:76
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGetCtlMainte(); expr &fcb
Expected: [3918]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:69 mpf_mfs_open*(&fcb, DynReCtlInfFNO)
c-viz: [3918] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:88
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGetCtlMainte(); expr &fcb
Expected: [3973]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:81 mpf_mfs_open*(&fcb, DynReCtlMainteFNO)
c-viz: [3973] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:153
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGetCtlMainteGn(); expr DynReGnInfFNO
Expected: [3970]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:153
c-viz: [3970] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:160
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGetCtlMainteGn(); expr &fcb
Expected: [3970]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:153 mpf_mfs_open*(&fcb, DynReGnInfFNO)
c-viz: [3970] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:172
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGetCtlMainteGn(); expr &fcb
Expected: [3973]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetCtlMainte.c:165 mpf_mfs_open*(&fcb, DynReCtlMainteFNO)
c-viz: [3973] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetOutValue.c:277
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReGetOutValueSche(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetOutValue.c:273 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:75
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGetPfmDayOfGrp(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:75
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:81
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReGetPfmDayOfGrp(); expr &sFcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:75 mpf_mfs_open*(&sFcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:84
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGetPfmDayOfGrp(); expr DynRePfmStaFNO
Expected: [3939]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:84
c-viz: [3939] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:90
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReGetPfmDayOfGrp(); expr &sFcb
Expected: [3939]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:84 mpf_mfs_open*(&sFcb, DynRePfmStaFNO)
c-viz: [3939] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:93
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGetPfmDayOfGrp(); expr DynRePfmSetFNO
Expected: [3940]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:93
c-viz: [3940] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:107
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReGetPfmDayOfGrp(); expr &sFcb
Expected: [3940]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGetPfmDayOfGrp.c:93 mpf_mfs_open*(&sFcb, DynRePfmSetFNO)
c-viz: [3940] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpMkjCsvLoad.c:119
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGrpMkjCsvLoad(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpMkjCsvLoad.c:119
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpMkjCsvLoad.c:126
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpMkjCsvLoad(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpMkjCsvLoad.c:119 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:163
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGrpSetCsvLoad(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:163
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:170
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpSetCsvLoad(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:163 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:368
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGrpSetCsvLoad(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:368
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:373
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpSetCsvLoad(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:368 mpf_mfs_open*(&fcb, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:383
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGrpSetCsvLoad(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:383
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:390
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpSetCsvLoad(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:383 mpf_mfs_open*(&fcb, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:401
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGrpSetCsvLoad(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:401
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:407
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpSetCsvLoad(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:401 mpf_mfs_open*(&fcb, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:409
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReGrpSetCsvLoad(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:409
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:415
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpSetCsvLoad(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:409 mpf_mfs_open*(&fcb, DynREGetSchKKLCfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:426
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReGrpSetCsvLoad(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:420 mpf_mfs_open*(&fcb, DynReKoteMntStaFNO)
c-viz: [3989] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:436
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpSetCsvLoad(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:428 mpf_mfs_open*(&fcb, DynReKoteMntSetFNO)
c-viz: [3990] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:447
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpSetCsvLoad(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c:441 mpf_mfs_open*(&fcb, DynReKoTeiHtSetFNO)
c-viz: [4013] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad2.c:124
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGrpSetCsvLoad2(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad2.c:119 mpf_mfs_open*(&fcb, DynReKoTeiHtSetFNO)
c-viz: [4013] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:156
Target: mpf_mfs_open_H(...), arg 2; enclosing fn hashimoto(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:156
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:166
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn hashimoto(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:156 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:178
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn hashimoto(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:171 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:185
Target: mpf_mfs_open_H(...), arg 2; enclosing fn hashimoto(); expr DynReSndStaDFSFNO
Expected: [3949]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:185
c-viz: [3949] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:193
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn hashimoto(); expr &fcb
Expected: [3949]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReHesErrCtl.c:185 mpf_mfs_open*(&fcb, DynReSndStaDFSFNO)
c-viz: [3949] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHesSireiTFunc.c:70
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGetHesSireiNext(); expr &fcb
Expected: [1039]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReHesSireiTFunc.c:63 mpf_mfs_open*(&fcb, DynReSireiTSetFNO)
c-viz: [1039] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHesSireiTFunc.c:177
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReGetHesSireiPrev(); expr &fcb
Expected: [1039]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReHesSireiTFunc.c:170 mpf_mfs_open*(&fcb, DynReSireiTSetFNO)
c-viz: [1039] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHtMntCsvLoad.c:155
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReHtMntCsvLoad(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReHtMntCsvLoad.c:149 mpf_mfs_open*(&fcb, DynReCtlMntStaFNO)
c-viz: [3986] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReHtMntCsvLoad.c:166
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReHtMntCsvLoad(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReHtMntCsvLoad.c:160 mpf_mfs_open*(&fcb, DynReCtlMntSetFNO)
c-viz: [3987] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReITCLock.c:88
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReITCLock(); expr &fcb
Expected: [2022]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReITCLock.c:83 mpf_mfs_open*(&fcb, DifStatusNo)
c-viz: [2022] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:97
Target: mpf_mfs_open_H(...), arg 2; enclosing fn or²ò½ü(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:97
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:103
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:97 mpf_mfs_open*(&sFcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:114
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3974]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:108 mpf_mfs_open*(&sFcb, DynReEmeKanIndFNO)
c-viz: [3974] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:117
Target: mpf_mfs_open_H(...), arg 2; enclosing fn or²ò½ü(); expr DynReCtlInfFNO
Expected: [3918]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:117
c-viz: [3918] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:123
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3918]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:117 mpf_mfs_open*(&sFcb, DynReCtlInfFNO)
c-viz: [3918] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:126
Target: mpf_mfs_open_H(...), arg 2; enclosing fn or²ò½ü(); expr DynReOutKanStaFNO
Expected: [3944]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:126
c-viz: [3944] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:132
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3944]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:126 mpf_mfs_open*(&sFcb, DynReOutKanStaFNO)
c-viz: [3944] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:142
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:136 mpf_mfs_open*(&sFcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:173
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:147 mpf_mfs_open*(&sFcb, DynReEmeStaIndFNO)
c-viz: [3975] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:182
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:147 mpf_mfs_open*(&sFcb, DynReEmeStaIndFNO)
c-viz: [3975] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:208
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:147 mpf_mfs_open*(&sFcb, DynReEmeStaIndFNO)
c-viz: [3975] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:295
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3909]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:289 mpf_mfs_open*(&sFcb, DynReTaikoSetFNO)
c-viz: [3909] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:305
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3912]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:299 mpf_mfs_open*(&sFcb, DynReEmeKanITkFNO)
c-viz: [3912] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:320
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:314 mpf_mfs_open*(&sFcb, DynReEmeStaIndFNO)
c-viz: [3975] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:330
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:314 mpf_mfs_open*(&sFcb, DynReEmeStaIndFNO)
c-viz: [3975] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:357
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn or²ò½ü(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReIkkatuReq.c:314 mpf_mfs_open*(&sFcb, DynReEmeStaIndFNO)
c-viz: [3975] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReKoteHtMntCsvLoad.c:140
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReKoteHtMntCsvLoad(); expr &fcb
Expected: [3988]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReKoteHtMntCsvLoad.c:132 mpf_mfs_open*(&fcb, DynReKoteMainteFNO)
c-viz: [3988] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReKoteHtMntCsvLoad.c:152
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReKoteHtMntCsvLoad(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReKoteHtMntCsvLoad.c:146 mpf_mfs_open*(&fcb, DynReKoteMntStaFNO)
c-viz: [3989] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReKoteHtMntCsvLoad.c:165
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReKoteHtMntCsvLoad(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReKoteHtMntCsvLoad.c:157 mpf_mfs_open*(&fcb, DynReKoteMntSetFNO)
c-viz: [3990] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReOutKanMsg.c:55
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReOutKanMsg(); expr DynReCtlInfFNO
Expected: [3918]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReOutKanMsg.c:55
c-viz: [3918] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReOutKanMsg.c:63
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReOutKanMsg(); expr &fcb
Expected: [3918]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReOutKanMsg.c:55 mpf_mfs_open*(&fcb, DynReCtlInfFNO)
c-viz: [3918] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynRePfmCSVOut.c:185
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynRePfmCSVOut(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynRePfmCSVOut.c:178 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynRePfmCSVOut.c:188
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynRePfmCSVOut(); expr nPfmOpenFileNO
Expected: [3940, 3951]  (PATH_VALID)
  - note: nPfmOpenFileNO = DynReHESPfmSetFNO(3951) if nIsHes else DynRePfmSetFNO(3940) @159/167
c-viz: [3940, 3951] (status {"EXACT": 2}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynRePfmCSVOut.c:195
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynRePfmCSVOut(); expr nInfOpenFileNO
Expected: [3917, 3918]  (PATH_VALID)
  - note: nInfOpenFileNO = DynReGrpSetFNO(3917) if nIsHes else DynReCtlInfFNO(3918) @158/166
c-viz: [3917, 3918] (status {"EXACT": 2}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynRePfmCSVOut.c:203
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynRePfmCSVOut(); expr &fcb_Pfm
Expected: [3940, 3951]  (PATH_VALID)
  - note: &fcb_Pfm bound via nPfmOpenFileNO {3940,3951}
c-viz: [3940, 3951] (status {"EXACT": 2, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynRePfmCSVOut.c:209
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynRePfmCSVOut(); expr &fcb_Inf
Expected: [3917, 3918]  (PATH_VALID)
  - note: &fcb_Inf bound via nInfOpenFileNO {3917,3918}
c-viz: [3917, 3918] (status {"EXACT": 2, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynRePfmCSVOut.c:212
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynRePfmCSVOut(); expr &fcb_Inf
Expected: [3917, 3918]  (PATH_VALID)
  - note: &fcb_Inf bound via nInfOpenFileNO {3917,3918}
c-viz: [3917, 3918] (status {"EXACT": 2, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:446
Target: mpf_mfs_open_H(...), arg 2; enclosing fn WriteSchedule(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:446
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:450
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn WriteSchedule(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:446 mpf_mfs_open*(&fcb, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:459
Target: mpf_mfs_open_H(...), arg 2; enclosing fn WriteSchedule(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:459
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:464
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn WriteSchedule(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:459 mpf_mfs_open*(&fcb, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:466
Target: mpf_mfs_open_H(...), arg 2; enclosing fn WriteSchedule(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:466
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:471
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn WriteSchedule(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:466 mpf_mfs_open*(&fcb, DynREGetSchKKLCfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:510
Target: mpf_mfs_open_H(...), arg 2; enclosing fn WriteSchedule(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:510
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:514
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn WriteSchedule(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad.c:510 mpf_mfs_open*(&fcb, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:133
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReSchSetCsvLoad2(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:133
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:139
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReSchSetCsvLoad2(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:133 mpf_mfs_open*(&fcb, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:494
Target: mpf_mfs_open_H(...), arg 2; enclosing fn WriteSchedule(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:494
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:498
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn WriteSchedule(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:494 mpf_mfs_open*(&fcb, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:504
Target: mpf_mfs_open_H(...), arg 2; enclosing fn WriteSchedule(); expr DynREGetSchKKfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:504
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:509
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn WriteSchedule(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:504 mpf_mfs_open*(&fcb, DynREGetSchKKfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:511
Target: mpf_mfs_open_H(...), arg 2; enclosing fn WriteSchedule(); expr DynREGetSchKKLCfno(nFnoidxKK
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:511
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:516
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn WriteSchedule(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:511 mpf_mfs_open*(&fcb, DynREGetSchKKLCfno(nFnoidxKK)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:604
Target: mpf_mfs_open_H(...), arg 2; enclosing fn WriteSchedule(); expr DynREGetSchfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:604
c-viz: [(none/status-only)] (status {"EXTERNAL": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:608
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn WriteSchedule(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetCsvLoad2.c:604 mpf_mfs_open*(&fcb, DynREGetSchfno(nFnoidx)
c-viz: [(none/status-only)] (status {"EXTERNAL": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetKKCsvExport.c:81
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReSchSetKKCsvExport(); expr DynREGetSchKKfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetKKCsvExport.c:81
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetKKCsvExport.c:86
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReSchSetKKCsvExport(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetKKCsvExport.c:81 mpf_mfs_open*(&fcb, DynREGetSchKKfno(nFnoidx)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetKKCsvExport.c:88
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReSchSetKKCsvExport(); expr DynREGetSchKKLCfno(nFnoidx
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetKKCsvExport.c:88
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSchSetKKCsvExport.c:93
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReSchSetKKCsvExport(); expr &fcb
Expected: [data-dependent (helper/variable)]  (DATA_DEPENDENT (UNDECIDED))
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSchSetKKCsvExport.c:88 mpf_mfs_open*(&fcb, DynREGetSchKKLCfno(nFnoidx)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: UNDECIDED  Conf: medium  Tags: INSUFFICIENT_EVIDENCE
### /home/chukyu/t-dyn/src/libDynRe/DynReSetHESSndhis.c:57
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReSetHESSndHis(); expr DynReHESSndHisFNO
Expected: [3968]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSetHESSndhis.c:57
c-viz: [3968] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReSetHESSndhis.c:62
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReSetHESSndHis(); expr &fcb
Expected: [3968]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSetHESSndhis.c:57 mpf_mfs_open*(&fcb, DynReHESSndHisFNO)
c-viz: [3968] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReSetHESSndhis.c:95
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynReSetHESSndHis(); expr &fcb
Expected: [3968]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSetHESSndhis.c:57 mpf_mfs_open*(&fcb, DynReHESSndHisFNO)
c-viz: [3968] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReSireiKaijoMsg.c:56
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReSireiKaijoMsg(); expr DynReCtlInfFNO
Expected: [3918]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSireiKaijoMsg.c:56
c-viz: [3918] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReSireiKaijoMsg.c:64
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReSireiKaijoMsg(); expr &fcb
Expected: [3918]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSireiKaijoMsg.c:56 mpf_mfs_open*(&fcb, DynReCtlInfFNO)
c-viz: [3918] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReSireiKaijoMsg.c:67
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReSireiKaijoMsg(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReSireiKaijoMsg.c:67
c-viz: [3941] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReSireiKaijoMsg.c:75
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReSireiKaijoMsg(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReSireiKaijoMsg.c:67 mpf_mfs_open*(&fcb, DynRePfmCtlFNO)
c-viz: [3941] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReTaiko.c:114
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn DynReChkTaikoElement(); expr &fcb
Expected: [3909]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReTaiko.c:109 mpf_mfs_open*(&fcb, DynReTaikoSetFNO)
c-viz: [(none/status-only)] (status {"UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: BOTH_UNDERAPPROXIMATION  Conf: medium  Tags: MISSING_ASSIGNMENT_EDGE
### /home/chukyu/t-dyn/src/libDynRe/DynReTaikoMsg.c:52
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynReTaikoMsg(); expr DynReCtlInfFNO
Expected: [3918]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReTaikoMsg.c:52
c-viz: [3918] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReTaikoMsg.c:60
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn DynReTaikoMsg(); expr &fcb
Expected: [3918]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReTaikoMsg.c:52 mpf_mfs_open*(&fcb, DynReCtlInfFNO)
c-viz: [3918] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:121
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn UpdOff(); expr &fcb
Expected: [1342]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:114 mpf_mfs_open*(&fcb, DynReAtEmeSvStaFNO)
c-viz: [1342] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:136
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn UpdOff(); expr &fcb
Expected: [3976]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:130 mpf_mfs_open*(&fcb, DynReAtEmeKanFNO)
c-viz: [3976] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:201
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn UpdOn(); expr &fcb
Expected: [1341]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:195 mpf_mfs_open*(&fcb, DynReAtEmeSetFNO)
c-viz: [1341] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:205
Target: mpf_mfs_open_H(...), arg 2; enclosing fn UpdOn(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:205
c-viz: [3917] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:211
Target: mpf_mfs_readrecn(...), arg 1; enclosing fn UpdOn(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:205 mpf_mfs_open*(&fcb, DynReGrpSetFNO)
c-viz: [3917] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:231
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn UpdOn(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:226 mpf_mfs_open*(&fcb, DynReGrpIdxFNO)
c-viz: [3916] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:255
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn UpdOn(); expr &fcb
Expected: [1342]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:235 mpf_mfs_open*(&fcb, DynReAtEmeSvStaFNO)
c-viz: [1342] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:352
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn UpdOn(); expr &fcb
Expected: [3976]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:346 mpf_mfs_open*(&fcb, DynReAtEmeKanFNO)
c-viz: [3976] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:385
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn UpdWaitInt(); expr &fcb
Expected: [1342]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:378 mpf_mfs_open*(&fcb, DynReAtEmeSvStaFNO)
c-viz: [1342] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:387
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn UpdWaitInt(); expr &fcb
Expected: [1342]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:378 mpf_mfs_open*(&fcb, DynReAtEmeSvStaFNO)
c-viz: [1342] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:418
Target: mpf_mfs_readrecm(...), arg 1; enclosing fn UpdNextTimCode(); expr &fcb
Expected: [1342]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:411 mpf_mfs_open*(&fcb, DynReAtEmeSvStaFNO)
c-viz: [1342] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:420
Target: mpf_mfs_writerecm(...), arg 1; enclosing fn UpdNextTimCode(); expr &fcb
Expected: [1342]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynReUpdAtEmeSvSta.c:411 mpf_mfs_open*(&fcb, DynReAtEmeSvStaFNO)
c-viz: [1342] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynSetReEneCtrlInfo.c:608
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynSetReEneCtrlInfo(); expr DynReCtlInfFNO
Expected: [3918]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynSetReEneCtrlInfo.c:608
c-viz: [3918] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynSetReEneCtrlInfo.c:609
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynSetReEneCtrlInfo(); expr &fcb
Expected: [3918]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynSetReEneCtrlInfo.c:608 mpf_mfs_open*(&fcb, DynReCtlInfFNO)
c-viz: [3918] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynSetReEneCtrlInfo.c:613
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynSetReEneCtrlInfo(); expr DynReGnInfFNO
Expected: [3970]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynSetReEneCtrlInfo.c:613
c-viz: [3970] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynSetReEneCtrlInfo.c:614
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynSetReEneCtrlInfo(); expr &fcb
Expected: [3970]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynSetReEneCtrlInfo.c:613 mpf_mfs_open*(&fcb, DynReGnInfFNO)
c-viz: [3970] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynSetReEneScheSta.c:171
Target: mpf_mfs_open_H(...), arg 2; enclosing fn DynSetReEneScheSta(); expr DynReSchStaFNO
Expected: [3920]  (PATH_VALID)
  - proof: open arg @ /home/chukyu/t-dyn/src/libDynRe/DynSetReEneScheSta.c:171
c-viz: [3920] (status {"EXACT": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynSetReEneScheSta.c:172
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynSetReEneScheSta(); expr &fcb
Expected: [3920]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynSetReEneScheSta.c:171 mpf_mfs_open*(&fcb, DynReSchStaFNO)
c-viz: [3920] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none
### /home/chukyu/t-dyn/src/libDynRe/DynSetReEneScheStaKK.c:164
Target: mpf_mfs_writerecn(...), arg 1; enclosing fn DynSetReEneScheStaKK(); expr &fcb
Expected: [1489]  (PATH_VALID)
  - proof: live open @ /home/chukyu/t-dyn/src/libDynRe/DynSetReEneScheStaKK.c:163 mpf_mfs_open*(&fcb, DynReSchStaKKFNO)
c-viz: [1489] (status {"EXACT": 1, "UNREACHABLE": 1}) | legacy: [(none/status-only)] (status {})
Verdict: CVIZ_CORRECT_ONLY  Conf: high  Tags: none

### Notable examples

**c-visualizer correct, legacy not (CVIZ_CORRECT_ONLY)**
- `/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:78` — `pmf_forkproc_H(PROC_NAME,...)`. `#define PROC_NAME "dyn600"` (line 33). c-viz emitted `dyn600` (EXACT); legacy reported nothing. Source-valid.
- `/home/chukyu/t-dyn/src/dyn430d/dyn430dPfmCtrl.c:183` — `mpf_mfs_readrecn(&fcb,...)`; live open @178 `mpf_mfs_open_H(&fcb, DynRePmfLogInfFNO)` = 3969. c-viz EXACT 3969; legacy none. Source-valid.
- `/home/chukyu/t-dyn/src/libDynRe/DynRePfmCSVOut.c:188` — `mpf_mfs_open_H(&fcb_Pfm, nPfmOpenFileNO,...)` where the variable `nPfmOpenFileNO` is `DynReHESPfmSetFNO`(3951) if `nIsHes` else `DynRePfmSetFNO`(3940) (lines 159/167). c-viz correctly reported BOTH `3940; 3951`; legacy none. Best example of c-viz handling a branch-assigned variable.
- `/home/chukyu/t-dyn/src/libDynRe/DynReITCLock.c:83` — `mpf_mfs_openm_H(&fcb, DifStatusNo,...)`; `DifStatusNo` is an external `#define (2022)` in `t-dif/include/dif/Dif.h`. c-viz 2022; legacy none. c-viz resolved a cross-module header constant.

**legacy correct, c-visualizer not (LEGACY_CORRECT_ONLY)**
- None. In this batch legacy essentially never emitted a concrete numeric value on a site that c-visualizer also left empty (legacy's OK_CONST/ALREADY_PRESENT statuses carried the macro name but not the resolved number, and those sites land in BOTH_UNDERAPPROXIMATION or BOTH_CORRECT_SAME rather than legacy-only).

**both correct (BOTH_CORRECT_SAME)**
- `/home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:158` — `mpf_mfs_readrecn(&fcb,...)`; live open @149 `DynReSchSetTkFNO`=3910. Both c-viz (EXACT 3910) and legacy (OK_CONST DynReSchSetTkFNO 3910) agree and match source.
- `/home/chukyu/t-dyn/src/dyn562/dyn562FtpRcv.c:543` — `&fcb` bound to `DynReGrpIdxFNO`=3916; both pipelines 3916, matches source.

**c-visualizer overapproximation**
- NONE. Across all 383 sites, no value emitted by c-visualizer (or legacy) was source-invalid. Every EXACT value equals the FNO that actually binds the handle / open argument at the site (verified via live-open identity, including multi-reopen FCB handles).

**strongest both-missed (BOTH_UNDERAPPROXIMATION)**
- `/home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:151` (and 19 sibling sites) — `pmf_forkproc_H(PROC_NAME,...)` with `#define PROC_NAME "dyn600"` (line 47). Both pipelines left it UNREACHABLE/empty although the concrete value `dyn600` is a one-step local macro.
- `/home/chukyu/t-dyn/src/dyn710/dyn710Init.c:292` — `mpf_mfs_open_H(&fcb, DynReGrpSetFNO,...)`; `DynReGrpSetFNO`=3917 is a plain enum constant. Both left it unresolved.
### Unfinished / open items

- All 383 unique sites (441 claim rows) received a verdict; none were skipped.
- 90 sites are recorded as UNDECIDED, not because the audit was incomplete, but because the concrete target value is **data-dependent** and no single value is statically provable at the site:
  - ~83 sites: FNO computed by the lookup helpers `DynREGetSchfno(nFnoidx)`, `DynREGetSchKKfno(nFnoidxKK)`, `DynREGetSchKKLCfno(nFnoidxKK)` or `DynREGetPfmfno(nFnoidx)` (e.g. `/home/chukyu/t-dyn/src/dyn710/dyn710Init.c:339`, `/home/chukyu/t-dyn/src/dyn810d/dyn810dCreateBody.c:242`, the `dyn562/dyn563 FtpRcv.c` KK blocks, and the `libDynRe/DynRe{Sch,Grp}SetCsvLoad*.c` loaders). These return `ScheFnoTbl[idx].{Schfno,Pfmfno}` — a bounded table (e.g. DynReSchSetFNO..16FNO = 3921..3936) indexed at run time; both pipelines correctly flagged EXTERNAL/UNRESOLVED.
  - `/home/chukyu/t-dyn/src/libDynRe/DynReMsgSub.c:118` — `pmf_forkprocbs_H(rcpuname, "dyn233",...)`: arg1 `rcpuname` is a function parameter (remote CPU name), not statically determinable.
  - 6 sites: FCB used where the nearest same-function open/close is inside a non-dominant branch and the binding open is in a *sibling* function via a file-static FCB (e.g. `/home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:131,143` use static `SFcbRE` opened in `DynReEneOutStaGet`). These were resolved to 3937 (DynReOutStaFNO) and counted as BOTH_UNDERAPPROXIMATION; flagged here only because they require cross-function static-FCB tracking.
- Legacy provenance line numbers throughout this batch are unreliable (stale source snapshot, see Batch summary finding 2); they were NOT used as evidence. All verdicts rest on the current /home/chukyu source.

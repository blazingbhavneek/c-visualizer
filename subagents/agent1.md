# Role

You are one of 6 subagents (this one is **1**) in a source-code correctness
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
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/subagents/agent1_claims.csv
- Full per-site comparison (for cross-checking only; do not audit outside your batch):
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/analysis/step1_results/step1_sites.csv
- c-visualizer raw facts:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/c-visualizer/results/csv_results/index/discovery_facts.csv
- legacy proof:
  /home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/valueflow_proof.csv
- C source root: /home/chukyu

Batch statistics (already computed — reconcile them against your CSV on start):
- claim rows in your batch: 464
- unique (file, line) sites: 417

Your batch covers these source directories (relative to /home/chukyu):
- /home/chukyu/t-dyn/src/dyn234d
- /home/chukyu/t-dyn/src/dyn401d
- /home/chukyu/t-dyn/src/dyn501d
- /home/chukyu/t-dyn/src/dyn600
- /home/chukyu/t-dyn/src/dyn730

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
one of the 464 claim rows (all 417 unique sites) receives a verdict —
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
- Sites audited: 417 / 417 (all 464 claim rows reconciled; multi-row sites consolidated)
- Per-verdict counts (primary verdict per site):
  - BOTH_CORRECT_SAME: 100
  - LEGACY_OVERAPPROXIMATION: 21 (legacy also under-approximates each of these; c-viz value is the correct one)
  - LEGACY_UNDERAPPROXIMATION: 165 (c-viz correct; legacy gave symbol-only OK_CONST rows or nothing)
  - CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION (both status-only, source proves values): 131
- Per-cause-tag counts:
  - STALE_HEADER_OR_SOURCE: 21
  - MISSED_MACRO_OR_ENUM: 112
  - MISSED_WRAPPER_MAPPING: 85
  - UNREACHABLE_ROOT_MODEL: 100
- Precision (accepted reported concrete values / all reported concrete values):
  - c-viz: 296/296 = 100% (no overapproximation found in this batch)
  - legacy: 100/121 = 82.6% (all 21 wrong values are stale pre-#31214 file-number positions)
  - combined: 396/417 = 95.0%
- Coverage (accepted values / source-backed expected values in batch, expected counted at value level):
  - Expected value instances: 100 (same-sites) + 186 (c-viz-only single-value sites) + 975 (both-status sites,
    incl. 1262 forkproc string pair and 81 table-lookup sites x 8/16 values) = 1261
  - c-viz coverage: 296/1261 = 23.5%; legacy coverage: 100/1261 = 7.9%; combined: 396/1261 = 31.4%
- Global findings:
  1. The single FNO table in /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h (current, #31214 numbering) is the
     authoritative source of all file-number constants. Legacy's LLM backwalk consistently resolved symbols to their
     pre-#31214 positions (e.g. DynReEmeStaIndFNO=1080, DynReAtEmeKanFNO=1343, DynReCtlMainteFNO=1077,
     DynReEmeKanIndFNO=1079, DynRePGCtlSetFNO=1344, DynReGrpSet3FNO=1345, DynReSetDspTgtFNO=1499,
     DynReCtlNtcDtPvFNO=3906, DynAdvCtlStaITkFNO=3914) — a stale-header problem in the legacy macro resolver.
  2. Legacy frequently stops at the constant name (OK_CONST with the symbol as "resolved_value") and never expands
     the enum arithmetic, causing underapproximation at ~112 sites.
  3. Neither pipeline resolves the static table-lookup wrappers DynREGetSchfno/DynREGetSchKKfno/
     DynREGetSchKKLCfno/DynREGetPfmfno (t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-265 and
     DynREGetScheKKPos.c:36-44); these yield bounded constant sets (3921..3936, 3995..4002, 4003..4010, 3952..3967)
     at 85 sites.
  4. c-viz marked all of dyn730 UNREACHABLE (roots not recognized) — 75 sites where direct constants are trivially
     source-provable.

### Site verdicts
## /home/chukyu/t-dyn/src/dyn234d

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:195
Target: mpf_mfs_open_H(&fcb_ReEne, DynReCtlStaFNO, nPower, 0, READLOCK), arg as per claims; enclosing fn dyn234dAdvGetSign(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - open arg at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:195; DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [3919] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:204
Target: mpf_mfs_readrecn(&fcb_ReEne, ...), arg as per claims; enclosing fn dyn234dAdvGetSign(); expr &fcb_ReEne
Expected: [3919]  (PATH_VALID)
  - fcb_ReEne opened at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:195 with DynReCtlStaFNO; closed 206; handle identity holds
c-viz: [3919] EXACT -> correct
legacy: [3919] OK_CONST (traced to :195) -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:208
Target: mpf_mfs_open_H(&fcb_AdvInd, iFnoInd, nPower, 0, READLOCK), arg as per claims; enclosing fn dyn234dAdvGetSign(); expr iFnoInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:187 (nTaiko branch) or DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:191 (else); both branches active (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:208
c-viz: [3946,3983] EXACT -> both correct (one per branch)
legacy: [3914] ADDED (DynAdvCtlStaITkFNO) -> WRONG: 3914 is only DynAdvCtlStaITkFNO_DUMMY (deleted, #31214); current DynAdvCtlStaITkFNO=3983. Legacy also omits 3946/3983
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE
Note: legacy's LLM backwalk used pre-#31214 numbering

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:216
Target: mpf_mfs_readrecn(&fcb_AdvInd, ...), arg as per claims; enclosing fn dyn234dAdvGetSign(); expr &fcb_AdvInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:187 (nTaiko branch) or DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:191 (else); both branches active (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:208
c-viz: [3946,3983] EXACT -> both correct (one per branch)
legacy: [3914] ADDED (DynAdvCtlStaITkFNO) -> WRONG: 3914 is only DynAdvCtlStaITkFNO_DUMMY (deleted, #31214); current DynAdvCtlStaITkFNO=3983. Legacy also omits 3946/3983
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE
Note: legacy's LLM backwalk used pre-#31214 numbering

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:407
Target: mpf_mfs_open_H(&fcb_AdvInd, iFnoInd, p, 0, READLOCK), arg as per claims; enclosing fn dyn234dAdvClearSendReq(); expr iFnoInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 / DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:383/388; open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:407
c-viz: [3946,3983] EXACT -> both correct
legacy: [no value, UNREACHABLE] -> misses 3946 & 3983
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:415
Target: mpf_mfs_readrecn(&fcb_AdvInd, ...), arg as per claims; enclosing fn dyn234dAdvClearSendReq(); expr &fcb_AdvInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 / DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:383/388; open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:407
c-viz: [3946,3983] EXACT -> both correct
legacy: [no value, UNREACHABLE] -> misses 3946 & 3983
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:446
Target: mpf_mfs_open_H(&fcb_AdvInd, iFnoInd, p, 0, WRITELOCK), arg as per claims; enclosing fn dyn234dAdvClearSendReq(); expr iFnoInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 / DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:383/388; open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:446
c-viz: [3946,3983] EXACT -> both correct
legacy: [no value, UNREACHABLE] -> misses 3946 & 3983
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:455
Target: mpf_mfs_writerecn(&fcb_AdvInd, ...), arg as per claims; enclosing fn dyn234dAdvClearSendReq(); expr &fcb_AdvInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 / DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:383/388; open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:446
c-viz: [3946,3983] EXACT -> both correct
legacy: [no value, UNREACHABLE] -> misses 3946 & 3983
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:578
Target: mpf_mfs_open_H(&fcb_AdvInd, iFnoInd, nPower, 0, READLOCK), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr iFnoInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 / DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:516/521; open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:578
c-viz: [3946,3983] EXACT -> both correct
legacy: [no value, UNREACHABLE] -> misses 3946 & 3983
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:586
Target: mpf_mfs_readrecn(&fcb_AdvInd, ...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_AdvInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 / DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:516/521; open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:578
c-viz: [3946,3983] EXACT -> both correct
legacy: [no value, UNREACHABLE] -> misses 3946 & 3983
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:696
Target: mpf_mfs_open_H(&fcb_AdvInd, iFnoInd, nPower, 0, WRITELOCK), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr iFnoInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 / DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:516/521; open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:696
c-viz: [3946,3983] EXACT -> both correct
legacy: [no value, UNREACHABLE] -> misses 3946 & 3983
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:705
Target: mpf_mfs_writerecn(&fcb_AdvInd, ...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_AdvInd
Expected: [3946; 3983]  (PATH_VALID)
  - iFnoInd = DynAdvCtlStaITkFNO=3983 / DynAdvCtlStaIndFNO=3946 at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:516/521; open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:696
c-viz: [3946,3983] EXACT -> both correct
legacy: [no value, UNREACHABLE] -> misses 3946 & 3983
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:559
Target: mpf_mfs_readrecn(&fcb_AdvCmn,...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:551 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3913
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:573
Target: mpf_mfs_readrecn(&fcb_AdvCmn,...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:565 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 1037
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:603
Target: mpf_mfs_open_H(&fcb_ReEne, DynReCtlStaFNO,...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_Adv
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:603 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:611
Target: mpf_mfs_readrecn(&fcb_ReEne,...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_Adv
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:603 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:677
Target: mpf_mfs_writerecn(&fcb_AdvCmn,...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:671 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3913
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:690
Target: mpf_mfs_writerecn(&fcb_AdvCmn,...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:684 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 1037
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:719
Target: mpf_mfs_readrecm(&fcb_AdvLog,...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_Adv
Expected: [3984]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:710 with DynAdvCtlLogFNO=3984 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3984] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3984
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:764
Target: mpf_mfs_writerecm(&fcb_AdvLog,...), arg as per claims; enclosing fn dyn234dAdvSendReq(); expr &fcb_Adv
Expected: [3984]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:710 with DynAdvCtlLogFNO=3984 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3984] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3984
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:850
Target: mpf_mfs_readrecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:841 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3913
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:865
Target: mpf_mfs_readrecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:856 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 1037
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:920
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:911 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3913
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:936
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:927 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 1037
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1001
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:992 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3913
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1022
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1013 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 1037
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1081
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1075 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3916
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1086
Target: mpf_mfs_open_H(&fcb, DynReGrpSetFNO,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1086 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1092
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1086 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1207
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1198 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 3913
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1223
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dTimeOut(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1214 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [no value, UNREACHABLE] -> misses 1037
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1412
Target: mpf_mfs_readrecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dAdvCtl(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1404 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [3913] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1487
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dAdvCtl(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1478 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [3913] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1503
Target: mpf_mfs_readrecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dAdvCtl(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1495 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [1037] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1539
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dAdvCtl(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1530 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [1037] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1644
Target: mpf_mfs_readrecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dStopAdvCtl(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1636 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [3913] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1648
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dStopAdvCtl(); expr &fcb_Adv
Expected: [3913]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1636 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [3913] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1663
Target: mpf_mfs_readrecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dStopAdvCtl(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1655 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [1037] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1667
Target: mpf_mfs_writerecn(&fcb_Adv,...), arg as per claims; enclosing fn dyn234dStopAdvCtl(); expr &fcb_Adv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:1655 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [1037] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none


## /home/chukyu/t-dyn/src/dyn401d

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:75
Target: mpf_mfs_open_H(&fcb, DynReSchStaFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynReSchStaFNO
Expected: [3920]  (PATH_VALID)
  - open arg at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:75; DynReSchStaFNO=3920 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3920] EXACT -> correct
legacy: [3920] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:83
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [3920]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:75 (DynReSchStaFNO=3920); closed 86
c-viz: [3920] EXACT -> correct
legacy: [3920] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:110
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [1489]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:102 with DynReSchStaKKFNO=1489 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1489] EXACT -> correct
legacy: [1489] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:158
Target: mpf_mfs_open_H(&fcb, DynReSchStaFNO, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynReSchStaFNO
Expected: [3920]  (PATH_VALID (inside if(nCalc_val!=0) at :145, active))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:158 with DynReSchStaFNO=3920 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3920] EXACT -> correct
legacy: [DynReSchStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3920
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:168
Target: mpf_mfs_writerecn(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [3920]  (PATH_VALID (inside if(nCalc_val!=0) at :145, active))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:158 with DynReSchStaFNO=3920 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3920] EXACT -> correct
legacy: [DynReSchStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3920
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:190
Target: mpf_mfs_open_H(&fcb, DynREGetSchfno(nFnoidx), 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynREGetSchfno(nFnoidx)
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (nFnoidx data-dependent via nUpd_pos from file state, mod 16))
  - DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
  - nFnoidx computed at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:186; loop :188
c-viz: [UNRESOLVED, no value] -> misses all 16 values
legacy: [UNRESOLVED, no value] -> misses all 16 values
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:200
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (same open :190, fcb closed after loop))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:190; DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:226
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [1487]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:215 with DynReSchColorFNO=1487 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1487] EXACT -> correct
legacy: [1487] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:243
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [1489]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:235 with DynReSchStaKKFNO=1489 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1489] EXACT -> correct
legacy: [1489] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:272
Target: mpf_mfs_writerecn(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [1489]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:262 with DynReSchStaKKFNO=1489 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1489] EXACT -> correct
legacy: [1489] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:283
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKfno(0), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynREGetSchKKfno(0)
Expected: [3995]  (PATH_VALID (constant index 0 -> table row 0))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:283; KKfno(0)=DynReSchSetKK01FNO=3995 (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37; hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses 3995
legacy: [UNRESOLVED, no value] -> misses 3995
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:291
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [3995]  (PATH_VALID (constant index 0 -> table row 0))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:283; KKfno(0)=DynReSchSetKK01FNO=3995 (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37; hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses 3995
legacy: [UNRESOLVED, no value] -> misses 3995
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:322
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKfno(0), 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynREGetSchKKfno(0)
Expected: [3995]  (PATH_VALID (constant index 0 -> table row 0))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:322; KKfno(0)=DynReSchSetKK01FNO=3995 (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37; hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses 3995
legacy: [UNRESOLVED, no value] -> misses 3995
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:330
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [3995]  (PATH_VALID (constant index 0 -> table row 0))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:322; KKfno(0)=DynReSchSetKK01FNO=3995 (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37; hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses 3995
legacy: [UNRESOLVED, no value] -> misses 3995
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:299
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKfno(nFnoidx), 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynREGetSchKKfno(nFnoidx)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (nFnoidx = f(nUpd_pos) mod 8, loop :298))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:299; DynREGetSchKKfno(nFnoidx) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:309
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (nFnoidx = f(nUpd_pos) mod 8, loop :298))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:299; DynREGetSchKKfno(nFnoidx) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:314
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (nFnoidx = f(nUpd_pos) mod 8, loop :298))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:299; DynREGetSchKKfno(nFnoidx) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:334
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKLCfno(0), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynREGetSchKKLCfno(0)
Expected: [4003]  (PATH_VALID (constant index 0 -> table row 0))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:334; KKLCfno(0)=DynReScStKKLC01FNO=4003 (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37; hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses 4003
legacy: [UNRESOLVED, no value] -> misses 4003
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:342
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [4003]  (PATH_VALID (constant index 0 -> table row 0))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:334; KKLCfno(0)=DynReScStKKLC01FNO=4003 (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37; hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses 4003
legacy: [UNRESOLVED, no value] -> misses 4003
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:373
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKLCfno(0), 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynREGetSchKKLCfno(0)
Expected: [4003]  (PATH_VALID (constant index 0 -> table row 0))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:373; KKLCfno(0)=DynReScStKKLC01FNO=4003 (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37; hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses 4003
legacy: [UNRESOLVED, no value] -> misses 4003
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:381
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [4003]  (PATH_VALID (constant index 0 -> table row 0))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:373; KKLCfno(0)=DynReScStKKLC01FNO=4003 (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37; hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses 4003
legacy: [UNRESOLVED, no value] -> misses 4003
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:350
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKLCfno(nFnoidx), 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr DynREGetSchKKLCfno(nFnoidx)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (nFnoidx data-dependent mod 8, loop :349))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:350; DynREGetSchKKLCfno(nFnoidx) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:360
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (nFnoidx data-dependent mod 8, loop :349))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:350; DynREGetSchKKLCfno(nFnoidx) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:365
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheStaUpd(); expr &fcb
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (nFnoidx data-dependent mod 8, loop :349))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheStaUpd.c:350; DynREGetSchKKLCfno(nFnoidx) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:149
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3909]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:141 with DynReTaikoSetFNO=3909 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3909] EXACT -> correct
legacy: [3909] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:181
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:175 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:208
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3910]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:199 with DynReSchSetTkFNO=3910 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3910] EXACT -> correct
legacy: [3910] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:280
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:275 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3986] EXACT -> correct
legacy: [3986] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:287
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:282 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3987] EXACT -> correct
legacy: [3987] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:296
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:291 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3989] EXACT -> correct
legacy: [3989] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:303
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:298 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:328
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:320 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [4013] EXACT -> correct
legacy: [4013] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:185
Target: mpf_mfs_open_H(&fcb, DynReGrpSetFNO,...), arg as per claims; enclosing fn dyn401dChkSign(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:185 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:193
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:185 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:227
Target: mpf_mfs_open_H(&fcb, DynReCtlStaFNO,...), arg as per claims; enclosing fn dyn401dChkSign(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:227 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:235
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:227 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:239
Target: mpf_mfs_open_H(&fcb, DynAdvCtlStaIndFNO,...), arg as per claims; enclosing fn dyn401dChkSign(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:239 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:247
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:239 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:259
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3975]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:251 with DynReEmeStaIndFNO=3975 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3975] EXACT -> correct
legacy: [1080 (via DynReEmeStaIndFNO, stale pre-#31214 value)] -> WRONG at this site; also omits 3975
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE
Note: current header has DynReEmeStaIndFNO=3975; 1080 is its deleted *_DUMMY position

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:271
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3976]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:263 with DynReAtEmeKanFNO=3976 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3976] EXACT -> correct
legacy: [1343 (via DynReAtEmeKanFNO, stale pre-#31214 value)] -> WRONG at this site; also omits 3976
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE
Note: current header has DynReAtEmeKanFNO=3976; 1343 is its deleted *_DUMMY position

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:513
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [3975]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:451 with DynReEmeStaIndFNO=3975 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3975] EXACT -> correct
legacy: [1080 (via DynReEmeStaIndFNO, stale pre-#31214 value)] -> WRONG at this site; also omits 3975
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE
Note: current header has DynReEmeStaIndFNO=3975; 1080 is its deleted *_DUMMY position

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:214
Target: mpf_mfs_open_H(&fcb, DynREGetSchfno(nFnoidx), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dChkSign(); expr DynREGetSchfno(nFnoidx)
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (else-branch of nGroupNo test, :196; nFnoidx data-dependent))
  - DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:214
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:222
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (same open :214))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:214; DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:363
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dChkSign(); expr DynREGetSchKKfno(nFnoidxKK)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:363; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:371
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (open :363))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:363; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:373
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKLCfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dChkSign(); expr DynREGetSchKKLCfno(nFnoidxKK)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:373; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:381
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dChkSign(); expr &fcb
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (open :373))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:373; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:70
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, READLOCK), arg as per claims; enclosing fn dyn401dSetAdvAutoCoverage(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:70 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:79
Target: mpf_mfs_readrecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn401dSetAdvAutoCoverage(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:70 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [&fcbAdvInd symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:293
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dSetAdvAutoCoverage(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:293 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:302
Target: mpf_mfs_writerecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn401dSetAdvAutoCoverage(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:293 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [&fcbAdvInd symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:370
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, READLOCK), arg as per claims; enclosing fn dyn401dGetAdvAutoStartKoma(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:370 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:379
Target: mpf_mfs_readrecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn401dGetAdvAutoStartKoma(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:370 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [&fcbAdvInd symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:486
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, READLOCK), arg as per claims; enclosing fn dyn401dGetAvailableKomaNum(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:486 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:495
Target: mpf_mfs_readrecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn401dGetAvailableKomaNum(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:486 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [&fcbAdvInd symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:594
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, READLOCK), arg as per claims; enclosing fn dyn401dSetAdvAutoRsv(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:594 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:603
Target: mpf_mfs_readrecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn401dSetAdvAutoRsv(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:594 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [&fcbAdvInd symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:658
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dSetAdvAutoRsv(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:658 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:670
Target: mpf_mfs_writerecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn401dSetAdvAutoRsv(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:658 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [&fcbAdvInd symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:708
Target: mpf_mfs_open_H(&fcb_ReEne, DynReCtlStaFNO, p, 0, READLOCK), arg as per claims; enclosing fn dyn401dAdvGetReEneEmeSign(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:708 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:717
Target: mpf_mfs_readrecn(&fcb_ReEne,...), arg as per claims; enclosing fn dyn401dAdvGetReEneEmeSign(); expr &fcb_ReEne
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:708 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3919] EXACT -> correct
legacy: [&fcb_ReEne symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:936
Target: mpf_mfs_open_H(&fcbGrp, DynReGrpSetFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dAdvScheCtrl(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:936 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:945
Target: mpf_mfs_readrecn(&fcbGrp,...), arg as per claims; enclosing fn dyn401dAdvScheCtrl(); expr &fcbGrp
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:936 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3917] EXACT -> correct
legacy: [&fcbGrp symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:1084
Target: mpf_mfs_open_H(&fcb, DynAdvCtlStaIndFNO, p, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dAdvCtlStaDailyUp(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:1084 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:1091
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAdvCtlStaDailyUp(); expr &fcb
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:1084 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:1103
Target: mpf_mfs_writerecn(&fcb,...), arg as per claims; enclosing fn dyn401dAdvCtlStaDailyUp(); expr &fcb
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:1084 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); (commented-out open at :151-161 is dead text, not counted)
c-viz: [3946] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:923
Target: mpf_mfs_readrecn(&fcbAdv,...), arg as per claims; enclosing fn dyn401dAdvScheCtrl(); expr &fcbAdv
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:914 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [1037] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:957
Target: mpf_mfs_readrecm(&SFcbGrpIdx,...), arg as per claims; enclosing fn dyn401dAdvScheCtrl(); expr &SFcbGrpIdx
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvScheCtrl.c:949 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:118
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:112 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:142
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:134 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb)
c-viz: [4013] EXACT -> correct
legacy: [4013] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:182
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:177 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb)
c-viz: [3986] EXACT -> correct
legacy: [3986] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:189
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:184 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb)
c-viz: [3987] EXACT -> correct
legacy: [3987] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:198
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:193 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb)
c-viz: [3989] EXACT -> correct
legacy: [3989] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:205
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:200 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb)
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:227
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [4011]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:222 with DynReGrpSetCmnFNO=4011 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb)
c-viz: [4011] EXACT -> correct
legacy: [4011] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:284
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [4012]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:276 with DynReCtlStaAlznFNO=4012 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb)
c-viz: [4012] EXACT -> correct
legacy: [4012] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:470
Target: mpf_mfs_writerecn(&fcb_StaAlzn,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb_StaAlzn
Expected: [4012]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:276 with DynReCtlStaAlznFNO=4012 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb kept open until this use (no intervening close of &fcb_StaAlzn)
c-viz: [4012] EXACT -> correct
legacy: [4012] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:122
Target: mpf_mfs_open_H(&fcb, DynReGrpSetFNO,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:122 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:130
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:122 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:153
Target: mpf_mfs_open_H(&fcb, DynReCtlStaFNO,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:153 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:161
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:153 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:165
Target: mpf_mfs_open_H(&fcb, DynAdvCtlStaIndFNO,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:165 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:173
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:165 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:245
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr DynREGetSchKKfno(nFnoidxKK)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:245; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:253
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (open :245))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:245; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:255
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKLCfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr DynREGetSchKKLCfno(nFnoidxKK)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:255; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:263
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAlznChkSign(); expr &fcb
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (open :255))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznRequest.c:255; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:101
Target: mpf_mfs_readrecm(&fcbGrpIdx,...), arg as per claims; enclosing fn dyn401dInit(); expr &fcbGrpIdx
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:95 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:105
Target: mpf_mfs_open_H(&fcbGrp, DynReGrpSetFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dInit(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:105 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:113
Target: mpf_mfs_readrecn(&fcbGrp,...), arg as per claims; enclosing fn dyn401dInit(); expr &fcbGrp
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:105 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:119
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, READLOCK), arg as per claims; enclosing fn dyn401dInit(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:119 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:127
Target: mpf_mfs_readrecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn401dInit(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:119 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:165
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dInit(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:165 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:173
Target: mpf_mfs_writerecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn401dInit(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:165 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3946] EXACT -> correct
legacy: [DynAdvCtlStaIndFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3946
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:371
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn401dInit(); expr &sFcb
Expected: [1342]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:365 with DynReAtEmeSvStaFNO=1342 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1342] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 1342
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:579
Target: mpf_mfs_open_H(&fcb, DynReSndStaDFSFNO, yPw, 0, READLOCK), arg as per claims; enclosing fn dyn401dInit(); expr DynReSndStaDFSFNO
Expected: [3949]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:579 with DynReSndStaDFSFNO=3949 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3949] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3949
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:590
Target: mpf_mfs_readrecn(&fcb, 0, 0, 1, ...), arg as per claims; enclosing fn dyn401dInit(); expr &fcb
Expected: [3949]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:579 with DynReSndStaDFSFNO=3949 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3949] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3949
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:591
Target: mpf_mfs_readrecn(&fcb, 0, DYN_REQ_HES_TOMO, 1, ...), arg as per claims; enclosing fn dyn401dInit(); expr &fcb
Expected: [3949]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:579 with DynReSndStaDFSFNO=3949 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3949] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3949
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:598
Target: mpf_mfs_open_H(&fcbSirei, DynReSireiInfFNO, yPw, 0, READLOCK), arg as per claims; enclosing fn dyn401dInit(); expr DynReSireiInfFNO
Expected: [3947]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:598 with DynReSireiInfFNO=3947 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3947] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3947
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:606
Target: mpf_mfs_readrecm(&fcbSirei,...), arg as per claims; enclosing fn dyn401dInit(); expr &fcbSirei
Expected: [3947]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:598 with DynReSireiInfFNO=3947 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3947] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3947
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:743
Target: mpf_mfs_open_H(&fcbSirei, DynReSireiInfFNO, yPw, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dInit(); expr DynReSireiInfFNO
Expected: [3947]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:743 with DynReSireiInfFNO=3947 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3947] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3947
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:751
Target: mpf_mfs_writerecm(&fcbSirei,...), arg as per claims; enclosing fn dyn401dInit(); expr &fcbSirei
Expected: [3947]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMain.c:743 with DynReSireiInfFNO=3947 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3947] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3947
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:128
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:122 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:148
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:142 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [4013] EXACT -> correct
legacy: [4013] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:199
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcb
Expected: [3985]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:193 with DynAdvCtlKanIndFNO=3985 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3985] EXACT -> correct
legacy: [3985] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:209
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:204 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3986] EXACT -> correct
legacy: [3986] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:218
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:213 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3987] EXACT -> correct
legacy: [3987] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:228
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:223 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3989] EXACT -> correct
legacy: [3989] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:235
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:230 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:132
Target: mpf_mfs_open_H(&fcb, DynReGrpSetFNO,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:132 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:138
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:132 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:177
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchfno(nFnoidx), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dAdvRequest(); expr DynREGetSchfno(nFnoidx)
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (nFnoidx data-dependent))
  - DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:177
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:187
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcbSch
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (open :177))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:177; DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:307
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchKKfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dAdvRequest(); expr DynREGetSchKKfno(nFnoidxKK)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:307; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:313
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcbSch
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (open :307))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:307; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:315
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchKKLCfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dAdvRequest(); expr DynREGetSchKKLCfno(nFnoidxKK)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:315; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:321
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn401dAdvRequest(); expr &fcbSch
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (open :315))
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAdvRequest.c:315; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:53
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dCtlMntStaUpd(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:47 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3986] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3986
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:71
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dCtlMntStaUpd(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:61 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3986] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3986
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:84
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dCtlMntStaUpd(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:78 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3987] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3987
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:93
Target: mpf_mfs_writerecn(&fcb,...), arg as per claims; enclosing fn dyn401dCtlMntStaUpd(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:78 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3987] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3987
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:126
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dKoteMntStaUpd(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:120 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3989] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3989
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:144
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dKoteMntStaUpd(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:134 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3989] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3989
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:154
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dKoteMntStaUpd(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:148 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3990] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3990
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:165
Target: mpf_mfs_writerecn(&fcb,...), arg as per claims; enclosing fn dyn401dKoteMntStaUpd(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dMntCtrl.c:148 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3990] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3990
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dGrpUpd.c:76
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dGrpUpd(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dGrpUpd.c:70 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dGrpUpd.c:80
Target: mpf_mfs_open_H(&fcb, DynReGrpSetFNO, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn401dGrpUpd(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open arg at /home/chukyu/t-dyn/src/dyn401d/dyn401dGrpUpd.c:80; DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dGrpUpd.c:88
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dGrpUpd(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn401d/dyn401dGrpUpd.c:80 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); still open at :88
c-viz: [3917] EXACT -> correct
legacy: [&fcb/DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dGrpUpd.c:131
Target: mpf_mfs_writerecn(&fcb,...), arg as per claims; enclosing fn dyn401dGrpUpd(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn401d/dyn401dGrpUpd.c:80 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); still open at :131
c-viz: [3917] EXACT -> correct
legacy: [&fcb/DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:84
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dEmReq(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:78 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:88
Target: mpf_mfs_open_H(&fcb, DynReGrpSetFNO,...), arg as per claims; enclosing fn dyn401dEmReq(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:88 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:96
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dEmReq(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:88 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:100
Target: mpf_mfs_open_H(&fcb, DynReCtlStaFNO,...), arg as per claims; enclosing fn dyn401dEmReq(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:100 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:108
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dEmReq(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dEmReq.c:100 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn401d/dyn401dHesCtrl.c:81
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dHesCtrl(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dHesCtrl.c:75 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3916
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dHesCtrl.c:85
Target: mpf_mfs_open_H(&fcb, DynReGrpSetFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn401dHesCtrl(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dHesCtrl.c:85 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dHesCtrl.c:93
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn401dHesCtrl(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dHesCtrl.c:85 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dHesCtrl.c:125
Target: mpf_mfs_readrecm(&fcb1,...), arg as per claims; enclosing fn dyn401dHesCtrl(); expr &fcb1
Expected: [1041]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dHesCtrl.c:119 with DynReRlSvSetFNO=1041 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1041] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 1041
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheCtrl.c:191
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheCtrl(); expr &fcb
Expected: [3910]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheCtrl.c:184 with DynReSchSetTkFNO=3910 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb closed at :198
c-viz: [3910] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3910
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dScheCtrl.c:196
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn401dScheCtrl(); expr &fcb
Expected: [3910]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dScheCtrl.c:184 with DynReSchSetTkFNO=3910 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); fcb closed at :198
c-viz: [3910] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3910
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznScheCtrl.c:83
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn401dAlphaScheCtrl(); expr &fcb
Expected: [4011]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn401d/dyn401dAlznScheCtrl.c:77 with DynReGrpSetCmnFNO=4011 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [4011] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 4011
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL


## /home/chukyu/t-dyn/src/dyn501d

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:628
Target: mpf_mfs_open_H(&fcb, DynReCtlNtcDatFNO, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn501dCreatYokoku(); expr DynReCtlNtcDatFNO
Expected: [3971]  (PATH_VALID)
  - open arg at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:628; DynReCtlNtcDatFNO=3971 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3971] EXACT -> correct
legacy: [DynReCtlNtcDatFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3971
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:636
Target: mpf_mfs_writerecn(&fcb,...), arg as per claims; enclosing fn dyn501dCreatYokoku(); expr &fcb
Expected: [3971]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:628 with DynReCtlNtcDatFNO=3971 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3971] EXACT -> correct
legacy: [symbol only, no numeric value] -> misses concrete 3971
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:1184
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn501dCreatYokokuPv(); expr &fcb
Expected: [3981]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:1176 with DynReCtlNtcDtPvFNO=3981 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3981] EXACT -> correct
legacy: [3906 (via DynReCtlNtcDtPvFNO, stale pre-#31214 value)] -> WRONG at this site; also omits 3981
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE
Note: current header has DynReCtlNtcDtPvFNO=3981; 3906 is its old position

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2354
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr &fcb
Expected: [3981]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2348 with DynReCtlNtcDtPvFNO=3981 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3981] EXACT -> correct
legacy: [3906 (via DynReCtlNtcDtPvFNO, stale pre-#31214 value)] -> WRONG at this site; also omits 3981
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE
Note: current header has DynReCtlNtcDtPvFNO=3981; 3906 is its old position

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2035
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2030 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2057
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2051 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3986] EXACT -> correct
legacy: [3986] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2067
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2061 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3987] EXACT -> correct
legacy: [3987] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2078
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2072 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3989] EXACT -> correct
legacy: [3989] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2088
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2080 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2114
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [4013]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2108 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [4013] EXACT -> correct
legacy: [4013] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2308
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr &fcb
Expected: [3988]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2300 with DynReKoteMainteFNO=3988 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3988] EXACT -> correct
legacy: [3988] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2038
Target: mpf_mfs_open_H(&fcb, DynReGrpSetFNO,...), arg as per claims; enclosing fn dyn501dFFRead(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2038 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2046
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2038 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [DynReGrpSetFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2222
Target: mpf_mfs_open_H(&fcb, DynReCtlNtcDatFNO,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr DynReCtlNtcDatFNO
Expected: [3971]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2222 with DynReCtlNtcDatFNO=3971 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3971] EXACT -> correct
legacy: [DynReCtlNtcDatFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3971
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2228
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr &fcb
Expected: [3971]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2222 with DynReCtlNtcDatFNO=3971 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3971] EXACT -> correct
legacy: [DynReCtlNtcDatFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3971
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2256
Target: mpf_mfs_open_H(&fcb, DynRePmfLogInfFNO, nPw, 0, READLOCK), arg as per claims; enclosing fn dyn501dFFReadOther(); expr DynRePmfLogInfFNO
Expected: [3969]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2256 with DynRePmfLogInfFNO=3969 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3969] EXACT -> correct
legacy: [DynRePmfLogInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3969
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2268
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr &fcb
Expected: [3969]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2256 with DynRePmfLogInfFNO=3969 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3969] EXACT -> correct
legacy: [DynRePmfLogInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3969
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2273
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr &fcb
Expected: [3969]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2256 with DynRePmfLogInfFNO=3969 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3969] EXACT -> correct
legacy: [DynRePmfLogInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3969
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2319
Target: mpf_mfs_open_H(&fcb, DynRePfmCtlFNO, nPw, 0, READLOCK), arg as per claims; enclosing fn dyn501dFFReadOther(); expr DynRePfmCtlFNO
Expected: [3941]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2319 with DynRePfmCtlFNO=3941 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3941] EXACT -> correct
legacy: [DynRePfmCtlFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3941
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2325
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr &fcb
Expected: [3941]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2319 with DynRePfmCtlFNO=3941 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3941] EXACT -> correct
legacy: [DynRePfmCtlFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3941
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2330
Target: mpf_mfs_open_H(&fcb, DynReCtlStaFNO, nPw, 0, READLOCK), arg as per claims; enclosing fn dyn501dFFReadOther(); expr DynReCtlStaFNO
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2330 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2336
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr &fcb
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2330 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3919] EXACT -> correct
legacy: [DynReCtlStaFNO symbol only, OK_CONST, no numeric value] -> misses concrete 3919
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2132
Target: mpf_mfs_open_H(&fcb, DynREGetSchfno(nFnoidx), 0, 0, READLOCK), arg as per claims; enclosing fn dyn501dFFRead(); expr DynREGetSchfno(nFnoidx)
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (nFnoidx from DynREGetSchePos2(:2129), time-dependent))
  - DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2132
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2138
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (open :2132))
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2132; DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2152
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn501dFFRead(); expr DynREGetSchKKfno(nFnoidxKK)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (guarded by nFnoidxKK>=0, :2151))
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2152; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2159
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (open :2152))
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2152; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2161
Target: mpf_mfs_open_H(&fcb, DynREGetSchKKLCfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn501dFFRead(); expr DynREGetSchKKLCfno(nFnoidxKK)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2161; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2168
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFRead(); expr &fcb
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (open :2161))
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2161; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2290
Target: mpf_mfs_open_H(&fcb, DynREGetPfmfno(nFnoidx), 0, 0, READLOCK), arg as per claims; enclosing fn dyn501dFFReadOther(); expr DynREGetPfmfno(nFnoidx)
Expected: [{ 3952..3967 (DynReHESPfmKbtFNO..16FNO) }]  (PATH_VALID (nFnoidx data-dependent))
  - DynREGetPfmfno(nFnoidx) = ScheFnoTbl[idx].Pfmfno = 3952..3967 (DynReHESPfmKbtFNO..16FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,260-265)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2290
c-viz: [UNRESOLVED, no value] -> misses all 16
legacy: [UNRESOLVED, no value] -> misses all 16
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2296
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFFReadOther(); expr &fcb
Expected: [{ 3952..3967 (DynReHESPfmKbtFNO..16FNO) }]  (PATH_VALID (open :2290))
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dDataCreate.c:2290; DynREGetPfmfno(nFnoidx) = ScheFnoTbl[idx].Pfmfno = 3952..3967 (DynReHESPfmKbtFNO..16FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,260-265)
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:183
Target: mpf_mfs_open_H(&fcb, DynReTrnMngInfFNO, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn501dStoreDat(); expr DynReTrnMngInfFNO
Expected: [1074]  (PATH_VALID)
  - open arg at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:183; DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [DynReTrnMngInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:190
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn501dStoreDat(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:183 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [symbol only, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:203
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn501dStoreDat(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:183 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [symbol only, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:364
Target: mpf_mfs_open_H(&fcb, DynReTrnMngInfFNO, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn501dStoreDatPv(); expr DynReTrnMngInfFNO
Expected: [1074]  (PATH_VALID)
  - open arg at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:364; DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [DynReTrnMngInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:371
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn501dStoreDatPv(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:364 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [symbol only, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:384
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn501dStoreDatPv(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:364 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [symbol only, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:544
Target: mpf_mfs_open_H(&fcb, DynReTrnMngInfFNO, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn501dStoreDatZisekiChukyu(); expr DynReTrnMngInfFNO
Expected: [1074]  (PATH_VALID)
  - open arg at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:544; DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [DynReTrnMngInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:551
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn501dStoreDatZisekiChukyu(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:544 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [symbol only, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:570
Target: mpf_mfs_writerecm(&fcb,...), arg as per claims; enclosing fn dyn501dStoreDatZisekiChukyu(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn501d/dyn501dStoreDat.c:544 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [symbol only, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:179
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFtpCreate(); expr &fcb
Expected: [1041]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:173 with DynReRlSvSetFNO=1041 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1041] EXACT -> correct
legacy: [1041] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:541
Target: mpf_mfs_open_H(&fcb, DynReTrnMngInfFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn501dFtpResult(); expr DynReTrnMngInfFNO
Expected: [1074]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:541 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [DynReTrnMngInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:550
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn501dFtpResult(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:541 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [DynReTrnMngInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:641
Target: mpf_mfs_open_H(&fcb, DynReTrnMngInfFNO, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn501dFtpResult(); expr DynReTrnMngInfFNO
Expected: [1074]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:641 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [DynReTrnMngInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:648
Target: mpf_mfs_writerecn(&fcb,...), arg as per claims; enclosing fn dyn501dFtpResult(); expr &fcb
Expected: [1074]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn501d/dyn501dFtpCreate.c:641 with DynReTrnMngInfFNO=1074 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1074] EXACT -> correct
legacy: [DynReTrnMngInfFNO symbol only, OK_CONST, no numeric value] -> misses concrete 1074
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM


## /home/chukyu/t-dyn/src/dyn600

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1262
Target: pmf_forkprocbs_H(rcpuname, "dyn600", 0, NULL, p_sUpdQ, sizeof(DynReSetfUpdQ)), arg as per claims; enclosing fn dyn600CallIkkatu(); expr rcpuname
Expected: ["ECS-A"; "ECS-B"]  (PATH_VALID (branch on controller role at :1225-1235))
  - rcpuname[] local, memset :1221; strcpy(rcpuname,"ECS-B") at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1227 (else-branch); strcpy(rcpuname,"ECS-A") at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1233
c-viz: [EXTERNAL, no value] -> misses both string literals
legacy: [UNRESOLVED, no value] -> misses both string literals
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL
Note: forkproc target-argument site; both pipelines treated buffer as external

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:266
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr &sFcb
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:259 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3916] EXACT -> correct
legacy: [3916] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:279
Target: mpf_mfs_open_H(&sFcb, iFno, 0, 0, READLOCK), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr iFno
Expected: [3917]  (PATH_VALID)
  - iFno = DynReGrpSetFNO=3917 at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:243; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:279
c-viz: [3917] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:289
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr &sFcb
Expected: [3917]  (PATH_VALID)
  - iFno = DynReGrpSetFNO=3917 at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:243; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:279
c-viz: [3917] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:295
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr &sFcb
Expected: [3917]  (PATH_VALID)
  - iFno = DynReGrpSetFNO=3917 at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:243; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:279
c-viz: [3917] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:361
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr iFno
Expected: [3975]  (PATH_VALID)
  - iFno = DynReEmeStaIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:302; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:302; DynReEmeStaIndFNO=3975 in current hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [3975] EXACT -> correct
legacy: [1080 (via DynReEmeStaIndFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3975
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:373
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - iFno = DynReEmeStaIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:302; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:361; DynReEmeStaIndFNO=3975 in current hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [3975] EXACT -> correct
legacy: [1080 (via DynReEmeStaIndFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3975
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:381
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - iFno = DynReEmeStaIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:302; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:361; DynReEmeStaIndFNO=3975 in current hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [3975] EXACT -> correct
legacy: [1080 (via DynReEmeStaIndFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3975
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:389
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - iFno = DynReEmeStaIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:302; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:361; DynReEmeStaIndFNO=3975 in current hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [3975] EXACT -> correct
legacy: [1080 (via DynReEmeStaIndFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3975
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:397
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpSet(); expr &sFcb
Expected: [3975]  (PATH_VALID)
  - iFno = DynReEmeStaIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:302; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:361; DynReEmeStaIndFNO=3975 in current hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [3975] EXACT -> correct
legacy: [1080 (via DynReEmeStaIndFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3975
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:517
Target: mpf_mfs_open_H(&sFcb, DynReGrpSetFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn600UpdScheSet(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:517 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:523
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:517 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:532
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:527 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3986] EXACT -> correct
legacy: [3986] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:541
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:536 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3987] EXACT -> correct
legacy: [3987] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:551
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:546 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3989] EXACT -> correct
legacy: [3989] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:558
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:553 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:581
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [4013]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:575 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [4013] EXACT -> correct
legacy: [4013] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:599
Target: mpf_mfs_open_H(&sFcb, DynREGetSchKKfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn600UpdScheSet(); expr DynREGetSchKKfno(nFnoidxKK)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:599; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:604
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (open :599))
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:599; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:606
Target: mpf_mfs_open_H(&sFcb, DynREGetSchKKLCfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn600UpdScheSet(); expr DynREGetSchKKLCfno(nFnoidxKK)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:606; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:611
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (open :606))
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:606; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:616
Target: mpf_mfs_open_H(&sFcb, iFno, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdScheSet(); expr iFno
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (iFno = DynREGetSchfno((Recno-1)/MAX2) at :496; Recno runtime))
  - iFno assigned at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:496; DynREGetSchfno((p_sUpdQ->Recno-1)/DYN_REENESCHE_MAX2)) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [EXTERNAL/UNREACHABLE, no value] -> misses all
legacy: [EXTERNAL, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:624
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (open :616))
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:616 (iFno from :496); DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [EXTERNAL, no value] -> misses all
legacy: [EXTERNAL, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:653
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheSet(); expr &sFcb
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (open :616))
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:616 (iFno from :496); DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [EXTERNAL, no value] -> misses all
legacy: [EXTERNAL, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:761
Target: mpf_mfs_open_H(&sFcb, DynReGrpSetFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn600UpdScheColor(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:761 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:767
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:761 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3917] EXACT -> correct
legacy: [symbol only, OK_CONST, no numeric value] -> misses concrete 3917
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:771
Target: mpf_mfs_open_H(&sFcb, DynREGetSchfno(nFnoidx), 0, 0, READLOCK), arg as per claims; enclosing fn dyn600UpdScheColor(); expr DynREGetSchfno(nFnoidx)
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (nFnoidx data-dependent))
  - DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:771
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:777
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (open :771))
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:771; DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:783
Target: mpf_mfs_open_H(&sFcb, DynREGetSchKKfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn600UpdScheColor(); expr DynREGetSchKKfno(nFnoidxKK)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:783; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:789
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (open :783))
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:783; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:791
Target: mpf_mfs_open_H(&sFcb, DynREGetSchKKLCfno(nFnoidxKK), 0, 0, READLOCK), arg as per claims; enclosing fn dyn600UpdScheColor(); expr DynREGetSchKKLCfno(nFnoidxKK)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:791; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all 8
legacy: [UNRESOLVED, no value] -> misses all 8
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:797
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (open :791))
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:791; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:807
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:802 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3986] EXACT -> correct
legacy: [3986] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:816
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:811 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3987] EXACT -> correct
legacy: [3987] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:826
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:821 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3989] EXACT -> correct
legacy: [3989] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:833
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:828 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:856
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [4013]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:850 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [4013] EXACT -> correct
legacy: [4013] OK_CONST -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:916
Target: mpf_mfs_open_H(&sFcb, iFno, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdScheColor(); expr iFno
Expected: [1487]  (PATH_VALID)
  - iFno = DynReSchColorFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:744; DynReSchColorFNO=1487 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:916
c-viz: [1487] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 1487
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:975
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdPtnSet(); expr iFno
Expected: [3942]  (PATH_VALID)
  - iFno = DynRePtnSetNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:964; DynRePtnSetNO=3942 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:975
c-viz: [3942] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3942
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:983
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdPtnSet(); expr &sFcb
Expected: [3942]  (PATH_VALID)
  - iFno = DynRePtnSetNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:964; DynRePtnSetNO=3942 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:975
c-viz: [3942] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3942
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1111
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600InitPtnSet(); expr iFno
Expected: [3942]  (PATH_VALID)
  - iFno = DynRePtnSetNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1096; DynRePtnSetNO=3942 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1111
c-viz: [3942] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3942
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1123
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600InitPtnSet(); expr &sFcb
Expected: [3942]  (PATH_VALID)
  - iFno = DynRePtnSetNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1096; DynRePtnSetNO=3942 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1111
c-viz: [3942] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3942
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1274
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdOutSet(); expr iFno
Expected: [3944]  (PATH_VALID)
  - iFno = DynReOutKanStaFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1205; DynReOutKanStaFNO=3944 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1274
c-viz: [3944] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3944
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1281
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdOutSet(); expr &sFcb
Expected: [3944]  (PATH_VALID)
  - iFno = DynReOutKanStaFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1205; DynReOutKanStaFNO=3944 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1274
c-viz: [3944] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3944
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1302
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdOutSet(); expr &sFcb
Expected: [3944]  (PATH_VALID)
  - iFno = DynReOutKanStaFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1205; DynReOutKanStaFNO=3944 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1274
c-viz: [3944] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3944
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1350
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdKstSet(); expr iFno
Expected: [3945]  (PATH_VALID)
  - iFno = DynReKansiStaFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1341; DynReKansiStaFNO=3945 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1350
c-viz: [3945] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3945
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1363
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKstSet(); expr &sFcb
Expected: [3945]  (PATH_VALID)
  - iFno = DynReKansiStaFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1341; DynReKansiStaFNO=3945 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1350
c-viz: [3945] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3945
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1412
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdKanSet(); expr iFno
Expected: [3943]  (PATH_VALID)
  - iFno = DynReOutKanSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1403; DynReOutKanSetFNO=3943 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1412
c-viz: [3943] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3943
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1429
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKanSet(); expr &sFcb
Expected: [3943]  (PATH_VALID)
  - iFno = DynReOutKanSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1403; DynReOutKanSetFNO=3943 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1412
c-viz: [3943] EXACT -> correct
legacy: [no value, no legacy row] -> misses concrete 3943
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1476
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdAdvCmnSet(); expr iFno
Expected: [1037]  (PATH_VALID)
  - iFno = DynAdvCtlStaCmnFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1467; DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1476
c-viz: [1037] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 1037
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1611
Target: mpf_mfs_openm_H(&sFcb, iFno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdSireiTSet(); expr iFno
Expected: [1039]  (PATH_VALID)
  - iFno = DynReSireiTSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1537; DynReSireiTSetFNO=1039 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1611
c-viz: [1039] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 1039
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1671
Target: mpf_mfs_openm_H(&sFcb, iFno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdRlSvSet(); expr iFno
Expected: [1041]  (PATH_VALID)
  - iFno = DynReRlSvSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1664; DynReRlSvSetFNO=1041 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1671
c-viz: [1041] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 1041
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1795
Target: mpf_mfs_openm_H(&sFcb, iFno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdCtlNtcSet(); expr iFno
Expected: [1071]  (PATH_VALID)
  - iFno = DynReCtlNtcInfFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1783; DynReCtlNtcInfFNO=1071 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1795
c-viz: [1071] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 1071
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1858
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdCtlMainte(); expr iFno
Expected: [3973]  (PATH_VALID)
  - iFno = DynReCtlMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1848; DynReCtlMainteFNO=3973 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1858
c-viz: [3973] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3973
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1942
Target: mpf_mfs_openm_H(&sFcb, iFno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdAtEmeSet(); expr iFno
Expected: [1341]  (PATH_VALID)
  - iFno = DynReAtEmeSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1932; DynReAtEmeSetFNO=1341 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1942
c-viz: [1341] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 1341
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1994
Target: mpf_mfs_openm_H(&sFcb, iFno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdEmeKanCmn(); expr iFno
Expected: [1078]  (PATH_VALID)
  - iFno = DynReEmeKanCmnFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1985; DynReEmeKanCmnFNO=1078 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1994
c-viz: [1078] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 1078
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2062
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdEmeKanInd(); expr iFno
Expected: [3974]  (PATH_VALID)
  - iFno = DynReEmeKanIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2048; DynReEmeKanIndFNO=3974 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2062
c-viz: [3974] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3974
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2166
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdPGCtlSet(); expr iFno
Expected: [3977]  (PATH_VALID)
  - iFno = DynRePGCtlSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2155; DynRePGCtlSetFNO=3977 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2166
c-viz: [3977] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3977
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2228
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdGrpCtlSet(); expr iFno
Expected: [3978]  (PATH_VALID)
  - iFno = DynReGrpSet3FNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2217; DynReGrpSet3FNO=3978 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2228
c-viz: [3978] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3978
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2301
Target: mpf_mfs_openm_H(&sFcb, iFno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdTaikoSet(); expr iFno
Expected: [3909]  (PATH_VALID)
  - iFno = DynReTaikoSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2290; DynReTaikoSetFNO=3909 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2301
c-viz: [3909] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3909
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2511
Target: mpf_mfs_openm_H(&sFcb, iFno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdEmeKanCTk(); expr iFno
Expected: [3911]  (PATH_VALID)
  - iFno = DynReEmeKanCTkFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2502; DynReEmeKanCTkFNO=3911 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2511
c-viz: [3911] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3911
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2573
Target: mpf_mfs_open_H(&sFcb, iFno, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdEmeKanITk(); expr iFno
Expected: [3912]  (PATH_VALID)
  - iFno = DynReEmeKanITkFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2561; DynReEmeKanITkFNO=3912 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2573
c-viz: [3912] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3912
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2663
Target: mpf_mfs_open_H(&sFcb, iFno, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdSetDspTgt(); expr iFno
Expected: [3980]  (PATH_VALID)
  - iFno = DynReSetDspTgtFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2658; DynReSetDspTgtFNO=3980 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2663
c-viz: [3980] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3980
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2713
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdAdvKanInd(); expr iFno
Expected: [3985]  (PATH_VALID)
  - iFno = DynAdvCtlKanIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2704; DynAdvCtlKanIndFNO=3985 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2713
c-viz: [3985] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3985
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2770
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdCtlMntSet(); expr iFno
Expected: [3987]  (PATH_VALID)
  - iFno = DynReCtlMntSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2760; DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2770
c-viz: [3987] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3987
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2823
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdKoteMainte(); expr iFno
Expected: [3988]  (PATH_VALID)
  - iFno = DynReKoteMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2815; DynReKoteMainteFNO=3988 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2823
c-viz: [3988] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3988
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2873
Target: mpf_mfs_open_H(&sFcb, iFno, iSubno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdKoteMntSet(); expr iFno
Expected: [3990]  (PATH_VALID)
  - iFno = DynReKoteMntSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2864; DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2873
c-viz: [3990] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3990
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2954
Target: mpf_mfs_open_H(&sFcb, iFno, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdKoteMainteAdd(); expr iFno
Expected: [3988]  (PATH_VALID)
  - iFno = DynReKoteMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2921; DynReKoteMainteFNO=3988 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2954
c-viz: [3988] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3988
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3016
Target: mpf_mfs_open_H(&sFcb, iFno, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdKoteMainteDel(); expr iFno
Expected: [3988]  (PATH_VALID)
  - iFno = DynReKoteMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3008; DynReKoteMainteFNO=3988 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3016
c-viz: [3988] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 3988
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3088
Target: mpf_mfs_openm_H(&sFcb, iFno, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdGrpSetCmn(); expr iFno
Expected: [4011]  (PATH_VALID)
  - iFno = DynReGrpSetCmnFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3078; DynReGrpSetCmnFNO=4011 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3088
c-viz: [4011] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 4011
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3135
Target: mpf_mfs_open_H(&sFcb, iFno, 0, 0, WRITELOCK), arg as per claims; enclosing fn dyn600UpdKoTeiHtSet(); expr iFno
Expected: [4013]  (PATH_VALID)
  - iFno = DynReKoTeiHtSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3128; DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h); open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3135
c-viz: [4013] EXACT -> correct
legacy: [iFno OK_CONST, symbol only, no numeric value] -> misses concrete 4013
Verdict: LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_MACRO_OR_ENUM

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:924
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdScheColor(); expr &sFcb
Expected: [1487]  (PATH_VALID)
  - iFno = DynReSchColorFNO=1487 at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:744; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:916
c-viz: [1487] EXACT -> correct
legacy: [1487] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1864
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdCtlMainte(); expr &sFcb
Expected: [3973]  (PATH_VALID)
  - iFno = DynReCtlMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1848; DynReCtlMainteFNO=3973 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1858
c-viz: [3973] EXACT -> correct
legacy: [1077 (via DynReCtlMainteFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3973
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1897
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdCtlMainte(); expr &sFcb
Expected: [3973]  (PATH_VALID)
  - iFno = DynReCtlMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1848; DynReCtlMainteFNO=3973 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1858
c-viz: [3973] EXACT -> correct
legacy: [1077 (via DynReCtlMainteFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3973
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2070
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdEmeKanInd(); expr &sFcb
Expected: [3974]  (PATH_VALID)
  - iFno = DynReEmeKanIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2048; DynReEmeKanIndFNO=3974 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2062
c-viz: [3974] EXACT -> correct
legacy: [1079 (via DynReEmeKanIndFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3974
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2116
Target: mpf_mfs_clearfile(iFno, iSubno, 0)(...), arg as per claims; enclosing fn dyn600UpdEmeKanInd(); expr iFno
Expected: [3974]  (PATH_VALID)
  - iFno = DynReEmeKanIndFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2048; DynReEmeKanIndFNO=3974 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2062
c-viz: [3974] EXACT -> correct
legacy: [1079 (via DynReEmeKanIndFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3974
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2173
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdPGCtlSet(); expr &sFcb
Expected: [3977]  (PATH_VALID)
  - iFno = DynRePGCtlSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2155; DynRePGCtlSetFNO=3977 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2166
c-viz: [3977] EXACT -> correct
legacy: [1344 (via DynRePGCtlSetFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3977
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2181
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdPGCtlSet(); expr &sFcb
Expected: [3977]  (PATH_VALID)
  - iFno = DynRePGCtlSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2155; DynRePGCtlSetFNO=3977 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2166
c-viz: [3977] EXACT -> correct
legacy: [1344 (via DynRePGCtlSetFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3977
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2235
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpCtlSet(); expr &sFcb
Expected: [3978]  (PATH_VALID)
  - iFno = DynReGrpSet3FNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2217; DynReGrpSet3FNO=3978 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2228
c-viz: [3978] EXACT -> correct
legacy: [1345 (via DynReGrpSet3FNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3978
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2243
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpCtlSet(); expr &sFcb
Expected: [3978]  (PATH_VALID)
  - iFno = DynReGrpSet3FNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2217; DynReGrpSet3FNO=3978 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2228
c-viz: [3978] EXACT -> correct
legacy: [1345 (via DynReGrpSet3FNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3978
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2669
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdSetDspTgt(); expr &sFcb
Expected: [3980]  (PATH_VALID)
  - iFno = DynReSetDspTgtFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2658; DynReSetDspTgtFNO=3980 in current hdr; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2663
c-viz: [3980] EXACT -> correct
legacy: [1499 (via DynReSetDspTgtFNO, stale pre-#31214 value; legacy flagged CONFLICT)] -> WRONG; also omits 3980
Verdict: LEGACY_OVERAPPROXIMATION | Confidence: high | Cause tags: STALE_HEADER_OR_SOURCE

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1483
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdAdvCmnSet(); expr &sFcb
Expected: [1037]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1476 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [1037] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1492
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdAdvCmnSet(); expr &sFcb
Expected: [1037]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1476 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1037] EXACT -> correct
legacy: [1037] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1547
Target: mpf_mfs_openm_H(iFno,...), arg as per claims; enclosing fn dyn600UpdSireiTSet(); expr iFno
Expected: [1039]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1547 with DynReSireiTSetFNO=1039 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1039] EXACT -> correct
legacy: [1039] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1553
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdSireiTSet(); expr &sFcb
Expected: [1039]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1547 with DynReSireiTSetFNO=1039 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1039] EXACT -> correct
legacy: [1039] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1617
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdSireiTSet(); expr &sFcb
Expected: [1039]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1611 with DynReSireiTSetFNO=1039 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1039] EXACT -> correct
legacy: [1039] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1678
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdRlSvSet(); expr &sFcb
Expected: [1041]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1671 with DynReRlSvSetFNO=1041 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1041] EXACT -> correct
legacy: [1041] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1682
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdRlSvSet(); expr &sFcb
Expected: [1041]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1671 with DynReRlSvSetFNO=1041 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1041] EXACT -> correct
legacy: [1041] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1802
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdCtlNtcSet(); expr &sFcb
Expected: [1071]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1795 with DynReCtlNtcInfFNO=1071 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1071] EXACT -> correct
legacy: [1071] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1808
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdCtlNtcSet(); expr &sFcb
Expected: [1071]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1795 with DynReCtlNtcInfFNO=1071 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1071] EXACT -> correct
legacy: [1071] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1949
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdAtEmeSet(); expr &sFcb
Expected: [1341]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1942 with DynReAtEmeSetFNO=1341 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1341] EXACT -> correct
legacy: [1341] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2001
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdEmeKanCmn(); expr &sFcb
Expected: [1078]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1994 with DynReEmeKanCmnFNO=1078 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1078] EXACT -> correct
legacy: [1078] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2086
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdEmeKanInd(); expr &sFcb
Expected: [1078]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2080 with DynReEmeKanCmnFNO=1078 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [1078] EXACT -> correct
legacy: [1078] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2308
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdTaikoSet(); expr &sFcb
Expected: [3909]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2301 with DynReTaikoSetFNO=3909 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3909] EXACT -> correct
legacy: [3909] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2309
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdTaikoSet(); expr &sFcb
Expected: [3909]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2301 with DynReTaikoSetFNO=3909 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3909] EXACT -> correct
legacy: [3909] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2366
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdTaikoSet(); expr &sFcb
Expected: [3910]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2360 with DynReSchSetTkFNO=3910 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3910] EXACT -> correct
legacy: [3910] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2395
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdTaikoSet(); expr &sFcb
Expected: [3913]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2389 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [3913] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2404
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdTaikoSet(); expr &sFcb
Expected: [3913]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2389 with DynAdvCtlStaCTkFNO=3913 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3913] EXACT -> correct
legacy: [3913] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2458
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdTaikoSet(); expr &sFcb
Expected: [3910]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2450 with DynReSchSetTkFNO=3910 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3910] EXACT -> correct
legacy: [3910] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2518
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdEmeKanCTk(); expr &sFcb
Expected: [3911]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2511 with DynReEmeKanCTkFNO=3911 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3911] EXACT -> correct
legacy: [3911] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2581
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdEmeKanITk(); expr &sFcb
Expected: [3912]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2573 with DynReEmeKanITkFNO=3912 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3912] EXACT -> correct
legacy: [3912] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2597
Target: mpf_mfs_readrecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdEmeKanITk(); expr &sFcb
Expected: [3911]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2591 with DynReEmeKanCTkFNO=3911 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3911] EXACT -> correct
legacy: [3911] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2625
Target: mpf_mfs_clearfile(iFno, 0, 0)(iFno,...), arg as per claims; enclosing fn dyn600UpdEmeKanITk(); expr iFno
Expected: [3912]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2573 with DynReEmeKanITkFNO=3912 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3912] EXACT -> correct
legacy: [3912] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2723
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdAdvKanInd(); expr &sFcb
Expected: [3985]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2713 with DynAdvCtlKanIndFNO=3985 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3985] EXACT -> correct
legacy: [3985] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2778
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdCtlMntSet(); expr &sFcb
Expected: [3987]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2770 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3987] EXACT -> correct
legacy: [3987] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2829
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoteMainte(); expr &sFcb
Expected: [3988]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2823 with DynReKoteMainteFNO=3988 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3988] EXACT -> correct
legacy: [3988] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2881
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoteMntSet(); expr &sFcb
Expected: [3990]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2873 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2929
Target: mpf_mfs_open_H(iFno,...), arg as per claims; enclosing fn dyn600UpdKoteMainteAdd(); expr iFno
Expected: [3988]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2929 with DynReKoteMainteFNO=3988 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [3988] EXACT -> correct
legacy: [3988] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2935
Target: mpf_mfs_readrecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoteMainteAdd(); expr &sFcb
Expected: [3988]  (PATH_VALID)
  - iFno = DynReKoteMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2929; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2929
c-viz: [3988] EXACT -> correct
legacy: [3988] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2960
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoteMainteAdd(); expr &sFcb
Expected: [3988]  (PATH_VALID)
  - iFno = DynReKoteMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2954; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2954
c-viz: [3988] EXACT -> correct
legacy: [3988] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2973
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoteMainteAdd(); expr &sFcb
Expected: [3990]  (PATH_VALID)
  - iFno = DynReKoteMntSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2967; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:2967
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3022
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoteMainteDel(); expr &sFcb
Expected: [3988]  (PATH_VALID)
  - iFno = DynReKoteMainteFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3016; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3016
c-viz: [3988] EXACT -> correct
legacy: [3988] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3034
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoteMainteDel(); expr &sFcb
Expected: [3990]  (PATH_VALID)
  - iFno = DynReKoteMntSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3028; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3028
c-viz: [3990] EXACT -> correct
legacy: [3990] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3046
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoteMainteDel(); expr &sFcb
Expected: [4013]  (PATH_VALID)
  - iFno = DynReKoTeiHtSetFNO at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3040; open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3040
c-viz: [4013] EXACT -> correct
legacy: [4013] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3095
Target: mpf_mfs_writerecm(&sFcb,...), arg as per claims; enclosing fn dyn600UpdGrpSetCmn(); expr &sFcb
Expected: [4011]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3088 with DynReGrpSetCmnFNO=4011 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [4011] EXACT -> correct
legacy: [4011] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3143
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600UpdKoTeiHtSet(); expr &sFcb
Expected: [4013]  (PATH_VALID)
  - fcb opened at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:3135 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [4013] EXACT -> correct
legacy: [4013] OK_CONST/ADDED -> correct
Verdict: BOTH_CORRECT_SAME | Confidence: high | Cause tags: none

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1042
Target: mpf_mfs_open_H(&sFcb, DynREGetSchfno(iIdxno), 0, 0, READLOCK), arg as per claims; enclosing fn dyn600InitScheSet(); expr DynREGetSchfno(iIdxno)
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (iIdxno loops 0..DYN_REENESCHE_IDXNUM-1 at :1011; every table row hit))
  - DynREGetSchfno(iIdxno) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1042
c-viz: [UNRESOLVED, no value] -> misses all 16
legacy: [UNRESOLVED, no value] -> misses all 16
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1056
Target: mpf_mfs_writerecn(&sFcb,...), arg as per claims; enclosing fn dyn600InitScheSet(); expr &sFcb
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (same open :1042, fcb closed :1058))
  - open at /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1042; DynREGetSchfno(iIdxno) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNRESOLVED, no value] -> misses all
legacy: [UNRESOLVED, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: MISSED_WRAPPER_MAPPING


## /home/chukyu/t-dyn/src/dyn730

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:478
Target: mpf_mfs_open_H(&SFcbGroupSet, DynReGrpSetFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:478 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3917
legacy: [no legacy row, no value] -> misses concrete 3917
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:487
Target: mpf_mfs_readrecn(&SFcbGroupSet,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:478 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3917
legacy: [no legacy row, no value] -> misses concrete 3917
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:515
Target: mpf_mfs_open_H(&SFcbCtlSta, DynReCtlStaFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:515 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3919
legacy: [no legacy row, no value] -> misses concrete 3919
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:518
Target: mpf_mfs_readrecn(&SFcbCtlSta,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3919]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:515 with DynReCtlStaFNO=3919 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3919
legacy: [no legacy row, no value] -> misses concrete 3919
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:532
Target: mpf_mfs_open_H(&SFcbRePfmSet, DynRePfmSetFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3940]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:532 with DynRePfmSetFNO=3940 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3940
legacy: [no legacy row, no value] -> misses concrete 3940
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:535
Target: mpf_mfs_readrecn(&SFcbRePfmSet,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3940]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:532 with DynRePfmSetFNO=3940 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3940
legacy: [no legacy row, no value] -> misses concrete 3940
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:550
Target: mpf_mfs_open_H(&SFcbReHESPfmSet, DynReHESPfmSetFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3951]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:550 with DynReHESPfmSetFNO=3951 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3951
legacy: [no legacy row, no value] -> misses concrete 3951
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:553
Target: mpf_mfs_readrecn(&SFcbReHESPfmSet,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3951]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:550 with DynReHESPfmSetFNO=3951 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3951
legacy: [no legacy row, no value] -> misses concrete 3951
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:573
Target: mpf_mfs_open_H(&SFcbRePfmSta, DynRePfmStaFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3939]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:573 with DynRePfmStaFNO=3939 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3939
legacy: [no legacy row, no value] -> misses concrete 3939
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:576
Target: mpf_mfs_readrecn(&SFcbRePfmSta,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3939]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:573 with DynRePfmStaFNO=3939 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3939
legacy: [no legacy row, no value] -> misses concrete 3939
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:590
Target: mpf_mfs_open_H(&SFcbRePfmCtl, DynRePfmCtlFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3941]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:590 with DynRePfmCtlFNO=3941 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3941
legacy: [no legacy row, no value] -> misses concrete 3941
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:593
Target: mpf_mfs_readrecn(&SFcbRePfmCtl,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3941]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:590 with DynRePfmCtlFNO=3941 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3941
legacy: [no legacy row, no value] -> misses concrete 3941
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:625
Target: mpf_mfs_open_H(&SFcbReHESPfmSta, DynReHESPfmStaFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3950]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:625 with DynReHESPfmStaFNO=3950 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3950
legacy: [no legacy row, no value] -> misses concrete 3950
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:628
Target: mpf_mfs_readrecn(&SFcbReHESPfmSta,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3950]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:625 with DynReHESPfmStaFNO=3950 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3950
legacy: [no legacy row, no value] -> misses concrete 3950
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:651
Target: mpf_mfs_open_H(&SFcbReOutKanSta, DynReOutKanStaFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3944]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:651 with DynReOutKanStaFNO=3944 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3944
legacy: [no legacy row, no value] -> misses concrete 3944
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:654
Target: mpf_mfs_readrecn(&SFcbReOutKanSta,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3944]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:651 with DynReOutKanStaFNO=3944 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3944
legacy: [no legacy row, no value] -> misses concrete 3944
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:711
Target: mpf_mfs_open_H(&SFcbReKansiSta, DynReKansiStaFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3945]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:711 with DynReKansiStaFNO=3945 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3945
legacy: [no legacy row, no value] -> misses concrete 3945
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:714
Target: mpf_mfs_readrecn(&SFcbReKansiSta,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3945]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:711 with DynReKansiStaFNO=3945 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3945
legacy: [no legacy row, no value] -> misses concrete 3945
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:728
Target: mpf_mfs_open_H(&SFcbReOutKanSet, DynReOutKanSetFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3943]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:728 with DynReOutKanSetFNO=3943 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3943
legacy: [no legacy row, no value] -> misses concrete 3943
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:731
Target: mpf_mfs_readrecn(&SFcbReOutKanSet,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3943]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:728 with DynReOutKanSetFNO=3943 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3943
legacy: [no legacy row, no value] -> misses concrete 3943
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:749
Target: mpf_mfs_readrecn(&SFcbReEmeStaInd,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3975]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:746 with DynReEmeStaIndFNO=3975 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3975
legacy: [no legacy row, no value] -> misses concrete 3975
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:766
Target: mpf_mfs_readrecn(&SFcbDifStatus,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [2022]  (PATH_VALID (constant defined in external t-dif header))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:763 with DifStatusNo=2022 (hdr /home/chukyu/t-dif/include/dif/Dif.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 2022
legacy: [no legacy row, no value] -> misses concrete 2022
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:784
Target: mpf_mfs_readrecn(&SFcbAdvCtlStaCmn,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [1037]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:781 with DynAdvCtlStaCmnFNO=1037 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 1037
legacy: [no legacy row, no value] -> misses concrete 1037
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:798
Target: mpf_mfs_open_H(&SFcbAdvCtlStaInd, DynAdvCtlStaIndFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:798 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3946
legacy: [no legacy row, no value] -> misses concrete 3946
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:801
Target: mpf_mfs_readrecn(&SFcbAdvCtlStaInd,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:798 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3946
legacy: [no legacy row, no value] -> misses concrete 3946
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:883
Target: mpf_mfs_readrecm(&SFcbTaiko,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3909]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:882 with DynReTaikoSetFNO=3909 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3909
legacy: [no legacy row, no value] -> misses concrete 3909
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:898
Target: mpf_mfs_open_H(&SFcbITCInf, DynReITCInfFNO, ...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3938]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:898 with DynReITCInfFNO=3938 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3938
legacy: [no legacy row, no value] -> misses concrete 3938
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:899
Target: mpf_mfs_readrecn(&SFcbITCInf,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3938]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:898 with DynReITCInfFNO=3938 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3938
legacy: [no legacy row, no value] -> misses concrete 3938
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:912
Target: mpf_mfs_readrecn(&SFcbItcSSDef,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [2515]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:911 with DYN730_DxiItcSSDefExFNo=2515 (hdr /home/chukyu/t-dyn/src/dyn730/dyn730.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 2515
legacy: [no legacy row, no value] -> misses concrete 2515
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:926
Target: mpf_mfs_readrecm(&SFcbGrpIdx,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3916]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:925 with DynReGrpIdxFNO=3916 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3916
legacy: [no legacy row, no value] -> misses concrete 3916
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:940
Target: mpf_mfs_readrecn(&SFcbAdvCtlKanInd,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3985]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:939 with DynAdvCtlKanIndFNO=3985 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3985
legacy: [no legacy row, no value] -> misses concrete 3985
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:953
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3986]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:952 with DynReCtlMntStaFNO=3986 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3986
legacy: [no legacy row, no value] -> misses concrete 3986
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:958
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3987]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:957 with DynReCtlMntSetFNO=3987 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3987
legacy: [no legacy row, no value] -> misses concrete 3987
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:969
Target: mpf_mfs_readrecm(&fcb,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3989]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:968 with DynReKoteMntStaFNO=3989 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3989
legacy: [no legacy row, no value] -> misses concrete 3989
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:974
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [3990]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:971 with DynReKoteMntSetFNO=3990 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3990
legacy: [no legacy row, no value] -> misses concrete 3990
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:990
Target: mpf_mfs_readrecn(&fcb,...), arg as per claims; enclosing fn dyn730GetData(); expr fcb arg as in claims
Expected: [4013]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:987 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 4013
legacy: [no legacy row, no value] -> misses concrete 4013
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1112
Target: mpf_mfs_open_H(&SFcbSchSet, DynREGetSchfno(nFnoidx), ...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr DynREGetSchfno(nFnoidx)
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1112; DynREGetSchfno(idx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1115
Target: mpf_mfs_readrecm(&SFcbSchSet,...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr &SFcbSchSet
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1112; DynREGetSchfno(idx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1147
Target: mpf_mfs_open_H(&SFcbSchSet, DynREGetSchKKfno(nFnoidxKK), ...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr DynREGetSchKKfno(nFnoidxKK)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1147; DynREGetSchKKfno(idx) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1149
Target: mpf_mfs_readrecm(&SFcbSchSet,...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr &SFcbSchSet
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1147; DynREGetSchKKfno(idx) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1153
Target: mpf_mfs_open_H(&SFcbSchSet, DynREGetSchKKLCfno(nFnoidxKK), ...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr DynREGetSchKKLCfno(nFnoidxKK)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1153; DynREGetSchKKLCfno(idx) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1155
Target: mpf_mfs_readrecm(&SFcbSchSet,...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr &SFcbSchSet
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1153; DynREGetSchKKLCfno(idx) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1215
Target: mpf_mfs_open_H(&SFcbSchSet, DynREGetSchfno(nFnoidxNext), ...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr DynREGetSchfno(nFnoidxNext)
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1215; DynREGetSchfno(idx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1218
Target: mpf_mfs_readrecm(&SFcbSchSet,...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr &SFcbSchSet
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1215; DynREGetSchfno(idx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1230
Target: mpf_mfs_open_H(&SFcbSchSet, DynREGetSchKKfno(nFnoidxNextKK), ...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr DynREGetSchKKfno(nFnoidxNextKK)
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1230; DynREGetSchKKfno(idx) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1232
Target: mpf_mfs_readrecm(&SFcbSchSet,...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr &SFcbSchSet
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1230; DynREGetSchKKfno(idx) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1236
Target: mpf_mfs_open_H(&SFcbSchSet, DynREGetSchKKLCfno(nFnoidxNextKK), ...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr DynREGetSchKKLCfno(nFnoidxNextKK)
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1236; DynREGetSchKKLCfno(idx) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1238
Target: mpf_mfs_readrecm(&SFcbSchSet,...), arg as per claims; enclosing fn dyn730CreateDrawData(); expr &SFcbSchSet
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1236; DynREGetSchKKLCfno(idx) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1560
Target: mpf_mfs_open_H(&SFcbReHESPfmKbt, DynREGetPfmfno(p_nFnoidx), ...), arg as per claims; enclosing fn dyn730CreateHiLowVol(); expr DynREGetPfmfno(p_nFnoidx)
Expected: [{ 3952..3967 (DynReHESPfmKbtFNO..16FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1560; DynREGetPfmfno(idx) = ScheFnoTbl[idx].Pfmfno = 3952..3967 (DynReHESPfmKbtFNO..16FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,260-265)
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1563
Target: mpf_mfs_readrecm(&SFcbReHESPfmKbt,...), arg as per claims; enclosing fn dyn730CreateHiLowVol(); expr &SFcbReHESPfmKbt
Expected: [{ 3952..3967 (DynReHESPfmKbtFNO..16FNO) }]  (PATH_VALID (index data-dependent via DynREGetSchePos*/time))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Init.c:1560; DynREGetPfmfno(idx) = ScheFnoTbl[idx].Pfmfno = 3952..3967 (DynReHESPfmKbtFNO..16FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,260-265)
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1867
Target: mpf_mfs_open_H(&fcbGrp, DynReGrpSetFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1867 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3917
legacy: [no legacy row, no value] -> misses concrete 3917
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1878
Target: mpf_mfs_readrecn(&fcbGrp,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbGrp
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1867 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3917
legacy: [no legacy row, no value] -> misses concrete 3917
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1886
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, READLOCK), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1886 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3946
legacy: [no legacy row, no value] -> misses concrete 3946
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1894
Target: mpf_mfs_readrecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1886 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3946
legacy: [no legacy row, no value] -> misses concrete 3946
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1938
Target: mpf_mfs_open_H(&fcbAdvInd, DynAdvCtlStaIndFNO, p, 0, WRITELOCK), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynAdvCtlStaIndFNO
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1938 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3946
legacy: [no legacy row, no value] -> misses concrete 3946
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1950
Target: mpf_mfs_writerecn(&fcbAdvInd,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbAdvInd
Expected: [3946]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:1938 with DynAdvCtlStaIndFNO=3946 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3946
legacy: [no legacy row, no value] -> misses concrete 3946
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2114
Target: mpf_mfs_open_H(&fcbGrp, DynReGrpSetFNO, 0, 0, READLOCK), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynReGrpSetFNO
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2114 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3917
legacy: [no legacy row, no value] -> misses concrete 3917
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2125
Target: mpf_mfs_readrecn(&fcbGrp,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbGrp
Expected: [3917]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2114 with DynReGrpSetFNO=3917 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 3917
legacy: [no legacy row, no value] -> misses concrete 3917
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2138
Target: mpf_mfs_readrecn(&fcbGrp,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbGrp
Expected: [4013]  (PATH_VALID)
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2130 with DynReKoTeiHtSetFNO=4013 (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses concrete 4013
legacy: [no legacy row, no value] -> misses concrete 4013
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: high | Cause tags: UNREACHABLE_ROOT_MODEL

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2178
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchfno(nFnoidx[0]), ...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynREGetSchfno(nFnoidx[0])
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2178; DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2187
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbSch
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2178; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2190
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchfno(nFnoidx[1]), ...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynREGetSchfno(nFnoidx[1])
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2190; DynREGetSchfno(nFnoidx) = ScheFnoTbl[idx].Schfno (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,243-248); table = {DynReSchSetFNO..DynReSchSet16FNO} = 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) (hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h)
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2198
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbSch
Expected: [{ 3921..3936 (DynReSchSetFNO..DynReSchSet16FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2190; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2253
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchKKfno(nFnoidxKK[0]), ...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynREGetSchKKfno(nFnoidxKK[0])
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2253; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2259
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbSch
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2253; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2261
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchKKLCfno(nFnoidxKK[0]), ...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynREGetSchKKLCfno(nFnoidxKK[0])
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2261; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2267
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbSch
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2261; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2272
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchKKfno(nFnoidxKK[1]), ...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynREGetSchKKfno(nFnoidxKK[1])
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2272; DynREGetSchKKfno(nFnoidxKK) = KKFnoTbl[idx] = 3995..4002 (DynReSchSetKK01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2278
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbSch
Expected: [{ 3995..4002 (DynReSchSetKK01FNO..08FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2272; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2280
Target: mpf_mfs_open_H(&fcbSch, DynREGetSchKKLCfno(nFnoidxKK[1]), ...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr DynREGetSchKKLCfno(nFnoidxKK[1])
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2280; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2286
Target: mpf_mfs_readrecn(&fcbSch,...), arg as per claims; enclosing fn dyn730SetAdvAutoRsv(); expr &fcbSch
Expected: [{ 4003..4010 (DynReScStKKLC01FNO..08FNO) }]  (PATH_VALID (index data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730AdvOptDlg.c:2280; DynREGetSchKKLCfno(nFnoidxKK) = KKLCFnoTbl[idx] = 4003..4010 (DynReScStKKLC01FNO..08FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetScheKKPos.c:37-44); hdr /home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h
c-viz: [UNREACHABLE, no value] -> misses all
legacy: [no legacy row, no value] -> misses all
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Draw.c:1831
Target: mpf_mfs_open_H(&SFcbReHESPfmKbt, DynREGetPfmfno(nFnoidx), ...), arg as per claims; enclosing fn dyn730AllControlVariable(); expr DynREGetPfmfno(nFnoidx)
Expected: [{ 3952..3967 (DynReHESPfmKbtFNO..16FNO) }]  (PATH_VALID (nFnoidx data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Draw.c:1831; DynREGetPfmfno(nFnoidx) = ScheFnoTbl[idx].Pfmfno = 3952..3967 (DynReHESPfmKbtFNO..16FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,260-265)
c-viz: [UNREACHABLE, no value] -> misses all 16
legacy: [no legacy row, no value] -> misses all 16
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Draw.c:1834
Target: mpf_mfs_readrecm(&SFcbReHESPfmKbt,...), arg as per claims; enclosing fn dyn730AllControlVariable(); expr &SFcbReHESPfmKbt
Expected: [{ 3952..3967 (DynReHESPfmKbtFNO..16FNO) }]  (PATH_VALID (nFnoidx data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Draw.c:1831; DynREGetPfmfno(nFnoidx) = ScheFnoTbl[idx].Pfmfno = 3952..3967 (DynReHESPfmKbtFNO..16FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,260-265)
c-viz: [UNREACHABLE, no value] -> misses all 16
legacy: [no legacy row, no value] -> misses all 16
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Draw.c:2107
Target: mpf_mfs_open_H(&SFcbReHESPfmKbt, DynREGetPfmfno(nFnoidx), ...), arg as per claims; enclosing fn dyn730GroupControlVariable(); expr DynREGetPfmfno(nFnoidx)
Expected: [{ 3952..3967 (DynReHESPfmKbtFNO..16FNO) }]  (PATH_VALID (nFnoidx data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Draw.c:2107; DynREGetPfmfno(nFnoidx) = ScheFnoTbl[idx].Pfmfno = 3952..3967 (DynReHESPfmKbtFNO..16FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,260-265)
c-viz: [UNREACHABLE, no value] -> misses all 16
legacy: [no legacy row, no value] -> misses all 16
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING

### /home/chukyu/t-dyn/src/dyn730/dyn730Draw.c:2110
Target: mpf_mfs_readrecm(&SFcbReHESPfmKbt,...), arg as per claims; enclosing fn dyn730GroupControlVariable(); expr &SFcbReHESPfmKbt
Expected: [{ 3952..3967 (DynReHESPfmKbtFNO..16FNO) }]  (PATH_VALID (nFnoidx data-dependent))
  - open at /home/chukyu/t-dyn/src/dyn730/dyn730Draw.c:2107; DynREGetPfmfno(nFnoidx) = ScheFnoTbl[idx].Pfmfno = 3952..3967 (DynReHESPfmKbtFNO..16FNO) (/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57,260-265)
c-viz: [UNREACHABLE, no value] -> misses all 16
legacy: [no legacy row, no value] -> misses all 16
Verdict: CVIZ_UNDERAPPROXIMATION + LEGACY_UNDERAPPROXIMATION | Confidence: medium | Cause tags: MISSED_WRAPPER_MAPPING


### Notable examples
- c-viz correct & legacy wrong (overapproximation, stale header):
  /home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c:259 — mpf_mfs_readrecn(&fcb): source-backed 3975
  (open :251 DynReEmeStaIndFNO, current header); legacy reported 1080 (pre-#31214 value, now *_DUMMY).
  Same pattern at dyn401dRequest.c:271 (1343 vs 3976), dyn501dDataCreate.c:1184 & 2354 (3906 vs 3981),
  dyn600MainProc.c:373/381/389/397 (1080 vs 3975), dyn600MainProc.c:2669 (1499 vs 3980),
  dyn234dAdvCtl.c:208 (3914 vs 3946/3983).
- c-viz correct & legacy silent/under (no concrete value):
  /home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:208 — iFnoInd two-branch constant: c-viz {3946,3983} both
  PATH_VALID; legacy had the right symbols but no current numeric value. Also dyn730/dyn730Init.c:515 (3919)
  and the whole dyn730 tree (c-viz UNREACHABLE on direct constants).
- Both correct (identical value):
  /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1553 — mpf_mfs_readrecm(&sFcb) <- open :1547 iFno=DynReSireiTSetFNO=1039;
  both report 1039. Also dyn401dMain.c:101 (3916), dyn501dFtpCreate.c:179 (1041), dyn234dAdvCtl.c:1667 (1037).
- c-viz overapproximation: none found in this batch (c-viz precision 100%).
- Strongest both-pipelines-wrong (both under) example:
  /home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1042 — DynREGetSchfno(iIdxno) with iIdxno looping 0..15
  (:1012): all 16 of {3921..3936} reachable; both pipelines reported only UNRESOLVED status.
  Also the forkproc site dyn600MainProc.c:1262 (rcpuname in {"ECS-A","ECS-B"}, :1227/:1233).

### Unfinished / open items
- None. All 417 unique sites (464 claim rows) received a verdict.
- Caveats (medium-confidence items): (a) data-dependent indices into the DynREGetSch* tables are bounded but the
  exact reachable subset varies with file state — the full table range was treated as the expected set;
  (b) dyn730Init.c:766 (DifStatusNo=2022) relies on t-dif/include/dif/Dif.h being the active include;
  (c) dyn401dScheCtrl.c claim lines 214/222/363/371/373/381 belong to dyn401dRequest.c in the current source
  (grep substring collision in batch prep); the two real dyn401dScheCtrl.c sites (191,196) were audited.

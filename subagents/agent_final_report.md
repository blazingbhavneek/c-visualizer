# Final consolidated report — c-visualizer resolution failure points

Compiled 2026-07-09 from the completed subagent audits
(`agent1.md` … `agent5.md` in this directory). Agent 6 (t-sim / t-svm / t-rep,
396 claim rows / 393 sites) was **not run**; all numbers below cover agents 1–5.

Every example in this report cites: the absolute source path, the line in the
subagent file where the verdict was written, and — where marked
**(re-verified)** — a direct re-check of the source I performed while writing
this report, so the claims can be audited without trusting the subagents.

---

## 1. Audited population

| Agent | Scope (under /home/chukyu) | Claim rows | Unique sites | Audited |
|---|---|---:|---:|---:|
| 1 | t-dyn/src: dyn234d, dyn401d, dyn501d, dyn600, dyn730 | 464 | 417 | 417 |
| 2 | t-dyn/src: libDynRe, libDynDspCom, dyn232d/402d/430d/562/563/710/810d/812d | 441 | 383 | 383 |
| 3 | t-dyn remaining ~40 dirs + t-dyn/tool | 410 | 392 | 392 |
| 4 | t-dif + t-tmm (src + tool) | 449 | 437 | 437 |
| 5 | t-dxi + t-cha (src + tool) | 359 | 330 | 330 |
| 6 | t-sim + t-svm + t-rep | 396 | 393 | **0 (not run)** |
| **Total** | | **2123** | **1959** | **1959 (83.3% of the 2352-site union)** |

## 2. Per-agent scorecard (as reported by each agent)

| Agent | c-viz precision | c-viz coverage | Dominant c-viz-side verdicts |
|---|---|---|---|
| 1 | 296/296 = **100%** | 296/1261 = 23.5%* | UNREACHABLE on 100 sites (whole dyn730 tree = 75 of them); both-miss on 131 sites |
| 2 | 271/271 = **100%** | 226/293 = 77.1% | CVIZ_CORRECT_ONLY 186; both-miss on 67; UNDECIDED 90 (mostly table-lookup/data-dependent) |
| 3 | 362/369 = 98.1% (all 7 rejects are legacy stale-enum values) | 47/112 distinct = 42.0% | both-miss 180; UNREACHABLE on 154 sites; 3 sites where legacy correct & c-viz empty |
| 4 | 466/466 = **100%** | 300/397 = 75.6% | both-miss 96 (UNREACHABLE tag 97); 37 sites legacy-correct-only |
| 5 | 154/164 = **93.9%** | 152/308 = 49.4% | CVIZ_UNDERAPPROXIMATION 166; **CVIZ_OVERAPPROXIMATION 10** (only overapproximation found in any batch); 8 legacy-correct-only |

\* Agent 1's coverage denominator includes the 81 table-lookup sites where the
source-backed set is a full 8- or 16-element bounded range; it is the most
coverage-penalized batch by construction.

**Headline:** across 1,500+ concrete c-viz value claims, only **10 rejected
c-viz values exist in the entire audited population**, and all 10 are the same
bug (failure mode F5 below). Every other c-viz error found is a **miss**
(underapproximation): a provably reachable value that c-viz reported as
UNREACHABLE / UNRESOLVED / EXTERNAL instead of a value.

---

## 3. c-visualizer failure points, grouped

Failure modes are ordered by (estimated sites affected) × (severity).
"Est. sites" is derived from each agent's per-tag counts and is an estimate,
not an exact census.

### F1 — UNREACHABLE root model: same-function opens not reachable from any recognized root
**Est. 400–450 sites. Coverage impact: severe. Precision impact: none.**

c-viz emits `UNREACHABLE` (status only, no value) for sites whose binding
`mpf_mfs_open*()` call is a plain in-function call a few lines away. The
root-recognition step evidently does not cover the entry points of whole
subtrees, and once root tracking fails there is no local fallback.

Grounding (all re-verified against source by this report's author unless noted):

1. **The entire dyn730 tree (75 sites).**
   `/home/chukyu/t-dyn/src/dyn730/dyn730Init.c:478` — **(re-verified)**:
   ```c
   mpf_mfs_open_H(&SFcbGroupSet, DynReGrpSetFNO, 0, 0, MPF_MFS_READLOCK);
   ```
   one step below the read site at :487. `DynReGrpSetFNO = 3917` in
   `/home/chukyu/t-dyn/include/Dyn/DynReEneFileDef.h`. c-viz: `UNREACHABLE`,
   no value. Same for :515 (DynReCtlStaFNO=3919), :532 (DynRePfmSetFNO=3940),
   and every other dyn730 site. Verdicts: agent1.md lines 2999–3597.
2. **dif901IntDll.c, 31 sites.** `/home/chukyu/t-dif/src/dif901/dif901IntDll.c`
   — **(re-verified)**: 20 `mpf_mfs_open(&fcb, NULL, DifSclDllDbNo /
   DifSvDllDbNo / DifTmDllDbNo / DifDvChangeInfNo, ...)` calls at lines 200,
   645, 769, 984, 1191, 1280, 1348, 1423, … each followed by getrecm/readrec
   calls on `&fcb`. Both pipelines status-only. agent4 notable examples.
3. **Literals four lines away.**
   `/home/chukyu/t-tmm/tool/opmtool/tmmtool.c:69, :76` —
   `mpf_mfs_openm_H(&fcb, 2715/2716, ...)` with plain integer literals 4 lines
   above the `readrecn(&fcb, ...)` sites; c-viz UNREACHABLE/none (agent4).
4. **cha100dMain.c:229** — open at L223 with `ChaOnlineManageNo` (2802);
   legacy correct, c-viz UNREACHABLE (agent5 notable examples; the strongest
   legacy-wins case in its batch).
5. **TmmSysInit.c (10 sites), TmmVolt_LV2PickUp.c (10 sites)** — local open
   with `TMM_*_FNO` macro, both pipelines silent (agent4).
6. **libDynDspCom.c:151** (19 sibling sites) — **(re-verified)**:
   ```c
   #define PROC_NAME "dyn600"            // line 47
   (void)pmf_forkproc_H(PROC_NAME, ...); // line 151
   ```
   c-viz UNREACHABLE, legacy empty (agent2.md:1517).
7. **dyn710Init.c:292** — `mpf_mfs_open_H(&fcb, DynReGrpSetFNO, ...)` plain
   enum constant = 3917; c-viz UNREACHABLE (agent2.md:1010).

**Why it happens:** the resolver's "recognized process root / wrapper /
callback" set does not include the actual entry points of these functions
(main-loop style single-function modules, tools, lib* helpers). Sites whose
root is unknown get status UNREACHABLE with no value, even though the answer
is one local open away.

**Mitigations (see ranked table §5):** local back-walk fallback when root is
UNREACHABLE; expand root set; never return empty for a handle that has a
visible same-function open.

### F2 — Wrapper / table-lookup helpers not unwrapped (bounded ranges left unreported)
**Est. 125–130 sites (agent1: 85–86, agent3: 24–25, agent5: 17–18). Coverage impact: high.**

Functions that return an element of a small **compile-time constant table**
are reported as EXTERNAL/UNREACHABLE instead of the bounded constant set.

Grounding:
1. **`DynREGetSchfno / DynREGetSchKKfno / DynREGetSchKKLCfno / DynREGetPfmfno`** —
   **(re-verified)** `/home/chukyu/t-dyn/src/libDynRe/DynREGetSchePos.c:40-57`:
   ```c
   static DynReScheFno ScheFnoTbl[] = {
       { DynReSchSetFNO,   DynReHESPfmKbtFNO },
       { DynReSchSet02FNO, DynReHESPfmKbt02FNO },
       ... 16 entries total ...
   };
   ```
   The reachable sets are bounded: Schfno = {3921..3936}, Pfmfno =
   {3952..3967} (agent3, via :260), KK = {3995..4002}, KKLC = {4003..4010}.
   Call sites: `/home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1042`
   (`DynREGetSchfno(iIdxno)` with `iIdxno` looping 0..15 at :1012 — all 16
   values reachable), `dyn431/dyn431Main.c:210,219,228,240`,
   `dyn431`/`dyn700Init.c:547-560`, `dyn831UpdatePfm.c:296,308,429,436`
   (agent1.md:3617, agent3.md:3967). **Both** pipelines report only
   UNRESOLVED/EXTERNAL at ~85 (agent1) + ~24 (agent3) sites.
2. **`ChaGetFileInfo`** — `*pFileNo = ChaBunFileNo[type][idx]`
   (`/home/chukyu/t-cha/src/libCha/ChaGetFileInfo.c`); bounded sets
   ChaOnlineTMNo01..17 / ChaOnlineSVNo01..17 (agent5.md:326-334).
3. **`Dxi_UpTbnFileOpen`** — **(see agent5.md:2727)** `fileno[2] =
   {DXI_FNO_UPMNG (2503), DXI_FNO_UPMNGTON (2513)}`; c-viz UNREACHABLE at
   `/home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:74`.
4. **Static table → forkproc name**: `/home/chukyu/t-tmm/src/tmm000/tmm000_deamon.c:56` —
   `pmf_forkproc_H(tmm000_prc[cpukind][i].prgname, ...)`; the table
   (tmm000_main.c:22-41) has exactly two active entries, `"tmm200d"` and
   `"tmm210d"`; both pipelines status-only (agent4).

**Mitigation:** return a *bounded range/enum-set* abstraction for calls that
index constant tables; add explicit wrapper mappings for the ~6 known
wrappers in this codebase. This is the single largest *joint* gap — legacy
fails here identically, so fixing it in c-viz is pure gain.

### F3 — Direct macro/enum/#define argument values not emitted
**Est. 150–170 sites (agent1 MISSED_MACRO_OR_ENUM 107–112, agent2
MISSING_ASSIGNMENT_EDGE 58, agent3 53). Coverage impact: high. Overlaps F1:
these are the cases where the missed value is a one-step constant.**

Grounding:
1. `#define PROC_NAME "dyn600"` → `pmf_forkproc_H(PROC_NAME,...)`:
   `/home/chukyu/t-dyn/src/libDynDspCom/LibDynDspCom.c:151` (re-verified, §3/F1.6).
   Contrast: c-viz *does* resolve the same pattern at
   `/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:78` (agent2 notable
   examples) — so the capability exists but is not applied uniformly.
2. Direct queue-macro argument: `/home/chukyu/t-dif/src/dif400d/dif400Deque.c:65` —
   `mpf_mfs_delque(NULL, DifTakeiSendQNo, &data)`; `DifTakeiSendQNo = 932`
   (`t-dif/include/DifP.h:119`); legacy correct, c-viz reported nothing
   (agent4.md, notable examples).
3. Queue-number macros in dxi: `dxi110d_parent.c:2298` (`DXI_QNO_DATABUFF=707`),
   `dxiG150d_child.c:936` (`DXI_QNO_GRCVDATA=731`) — legacy OK_MACRO correct,
   c-viz empty (agent5 notable examples).
4. Enum constants: `DynReGrpSetFNO=3917` at `dyn710Init.c:292`
   (agent2.md:1010); the whole dyn730 tree (F1.1).

**Possible contributing factor:** the active headers
(`t-dyn/include/Dyn/DynReEneFileDef.h`, `t-dxi/include/dxi_const.h`) are
SJIS-encoded and grep reports them as *binary*. If c-viz's include/macro
indexing skips or mis-parses non-UTF8 headers in some include chains, direct
macro resolution silently fails while handle tracking (which needs no macro
expansion) still works — consistent with c-viz finding the *handle* but not
the *value*.

**Mitigation:** verify the macro index actually parses the active (SJIS)
headers; unit-test one-step `#define`/enum expansion for each target header;
treat "open arg is a bare identifier that is a known macro in an active
header" as an EXACT resolution.

### F4 — Overapproximation: guaranteed-overwritten variable keeps its initializer value `0`
**10 value claims on ~8 sites, all in one file. The only c-viz precision loss
found in the entire 1,959-site audit. Precision impact: small but real.**

All in `/home/chukyu/t-cha/src/libChaLrg/ChaLrgCom.c` at lines
458/470/477, 657/663, 996/1008/1015, 1127/1133.
**(Re-verified, lines 451-458):**
```c
iRetChg = ChaGetFileInfo( 1, sub, &iOpenFileNo, &iOpenSubNo );
if ( iRetChg == -1 )
{
    ChaPrintf( ... );
    return ( CHA_ERR );            /* error path exits the function */
}
if ( mpf_mfs_open_H( &fcb, iOpenFileNo, iOpenSubNo, 0, MPF_MFS_READLOCK ))
```
`ChaGetFileInfo` writes a positive ChaOnlineTMNo*/SVNo* constant into
`iOpenFileNo` on success and the failure path returns, so `0` (the variable's
declared initializer) **cannot** reach `mpf_mfs_open_H`. c-viz reported
`[0]` (status `UNREACHABLE` or `EXACT+UNREACHABLE`) at all of these sites;
expected sets are the 17 TM constants {2845,2846,2847,2857..2870} or 17 SV
constants {2803..2807,2812,2813,2821,2822,2832..2835,2840,2850..2852}.
Verdicts: agent5.md:1303-1400 (`CVIZ_OVERAPPROXIMATION`, tag
MISSING_WRAPPER_MAPPING).

**Mechanism:** c-viz sees `iOpenFileNo` (declared `= 0`) as the open argument
and cannot connect the wrapper call that overwrites it (F2) — so it falls
back to the initializer. The two failure modes are the same root cause viewed
from two sides: no wrapper write → reports stale initializer (wrong value)
instead of no value.

**Mitigation:** (a) model "call writes &var and non-error implies write
happened" for known wrappers; (b) when a variable's only other value source
is a failed/returned-on call, do not emit the initializer as an exact value —
emit the wrapper's range or status-only.

### F5 — Branch-merge error: middle arm of `if / else if / else` dropped
**4–5 sites (agent5 BRANCH_MERGE_ERROR). Precision of the *reported* values is
fine (2 of 3 accepted); coverage loses one value per site.**

**(Re-verified)** `/home/chukyu/t-dxi/src/dxi110d/dxi110d_parent.c:1582-1591`:
```c
if( myshu == 1 ){
    fno_initmng = DXI_FNO_INITMNG2;      /* 2519 */
} else if( myshu == 2 ){
    fno_initmng = DXI_FNO_INITMNG3;      /* 2525, added by #30017 2025-09-29 */
} else {
    fno_initmng = DXI_FNO_INITMNG;       /* 2512 */
}
```
c-viz reports `{2512, 2525}` at `dxi110d_parent.c:1687, :1695` and
`dxi_initmng.c:72, :80` — i.e. first and third arms, **missing the
`myshu == 1` arm (2519)**. Legacy makes the identical mistake (BOTH_INCOMPLETE
at :1687/:1695; at dxi_initmng.c only c-viz reported the partial set). The
dropped arm is the one added by a recent change (#30017), which suggests the
branch enumeration cached/prefers original + latest arms.
Verdicts: agent5.md:1537-1553, 2710-2725.

**Mitigation:** regression-test multi-arm `else if` chains (3+ arms) in the
branch-merge pass; assert |merged set| == number of live arms when every arm
assigns the same variable.

### F6 — Function-pointer-parameter handles not resolved (parameter ≠ `&local`)
**Est. 25–30 sites (agent4 notable + agent5 MISSING_CALLER_EDGE 26-27,
agent3 HANDLE_BINDING_NOT_PROPAGATED 1-2). Coverage impact: moderate.**

1. `/home/chukyu/t-tmm/src/tmm910/tmm910_gnqmnt.c:636` — `mpf_mfs_getrecm(set_fcb, 0)`
   where `set_fcb` is an `MPF_MFS_FCB*` **parameter** of `tmm910_gnqset()`.
   Sole callers (:284, :314) pass `&set_fcb` opened with
   `TMM_GNQSET_FNO (2716)` at :84 (caveat recorded by agent4: closed at :96
   before the call — the value remains the only source-provable binding).
   c-viz UNRESOLVED; legacy 2716 correct. agent4.md:3974.
2. Wrapper-parameter functions in t-cha: `ChaReadRecm(fileNo)`,
   `ChaReadTm/ChaReadSv(fileNo)`, `ChaWriteRecn(fileNo)` in
   `/home/chukyu/t-cha/src/libChaCom/ChaCase.c` — the fileNo comes from
   callers (cha301Proc.c L840/882/1101/1115/1153/1167) via
   `ChaGetFileInfo`-filled variables; c-viz reports nothing (agent5.md:1007-1063).
3. `DxiEnqEvent/DxiEnqEvent2`, `Dxi_DnTbnFileCtrl`, `Dxi_FcbG` users — same
   caller-enumeration gap (agent5.md:2989 qualifications).

**Mitigation:** when the target argument is a pointer *parameter*, enumerate
in-tree callers and resolve the passed expression (agent5's manual procedure
succeeded on every one of these — the value is statically determinable).
This is a bounded, mechanical fix.

### F7 — File-static (cross-function) FCB variables not tracked
**A few sites (agent2 open-items; agent3 tag HANDLE_BINDING_NOT_PROPAGATED).**

`/home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c:131, :143` use the
file-static `SFcbRE`, which is opened (with `DynReOutStaFNO` = 3937) in the
*sibling* function `DynReEneOutStaGet`. Both pipelines gave no value; the
agents resolved it manually (agent2.md:2586-2593, counted as
BOTH_UNDERAPPROXIMATION with a cross-function caveat).

**Mitigation:** track file-scope `static MPF_MFS_FCB` variables across
functions (open in fn A, use in fn B). Low site count today, but it is a
general C pattern that will recur in t-sim/t-svm/t-rep (agent 6 scope).

### F8 — String-literal flow to forkproc argument (local char buffer + strcpy)
**A handful of sites; both pipelines fail identically (joint gap, but worth a
dedicated fix since forkproc correctness is the point of this tool).**

1. `/home/chukyu/t-dyn/src/dyn600/dyn600MainProc.c:1262` — **(cited
   agent1.md:2048)** `pmf_forkprocbs_H(rcpuname, "dyn600", ...)`: `rcpuname`
   is a local buffer, `memset` at :1221, `strcpy(rcpuname,"ECS-B")` at :1227
   (else branch) / `strcpy(rcpuname,"ECS-A")` at :1233. Expected
   `{"ECS-A","ECS-B"}`; c-viz EXTERNAL, legacy UNRESOLVED.
2. `/home/chukyu/t-dxi/src/libdxiinside/dxi_dblcirreq.c:100` — `prcname =
   DXI_NAME_DBLCIRMNG1/2/3 per myshu` just above the site →
   `{"dxi500d","dxi501d","dxi502d"}`; c-viz EXTERNAL+UNREACHABLE, legacy empty
   (agent5.md:2700).
3. Contrast (works): `PROC_NAME` #define at `libDynDspCom.c:47`→:151 fails
   (F3.1) while `DynReEneLib.c:78` succeeds — string handling is
   inconsistent even for the same syntactic pattern.

**Mitigation:** constant-propagate string literals through
`memset/strcpy/strncpy` of local buffers within a function; treat
`forkproc(arg)` with arg = local char array as a first-class case.

---

## 4. What c-visualizer gets right (do not regress while fixing)

- **100% precision on numeric FNOs in 4 of 5 batches** — every EXACT value
  checked matched the live open's FNO. 0 spurious values in agents 1, 2, 3
  (c-viz side), 4.
- **Correct handle identity across reopens** —
  `/home/chukyu/t-dxi/src/dxi150d/dxiG150d_main.c:1042`: c-viz picked 2552
  (open L1021) and correctly did **not** include 2554 from an earlier open in
  the same function (agent5 notable examples).
- **Branch-union on local variables** — `libDynRe/DynRePfmCSVOut.c:188`
  reports both `{3940, 3951}` for `nPfmOpenFileNO` assigned in two branches
  (agent2); `dyn432dAdvCtrl.c:108,116,269` reports both `{3946, 3983}`
  (agent3).
- **Cross-module header constants** — `DifStatusNo = 2022` from
  `t-dif/include/dif/Dif.h` resolved in t-dyn code
  (`libDynRe/DynReITCLock.c:83`, agent2).
- **Both type-branch values** — `dxiG_cirmng.c:146` reports exactly
  `{2552 (GCIRMNG), 2554 (GITCMNG)}` where legacy reported nothing (agent5).

## 5. Ranked mitigation table

| # | Failure mode | Est. sites (agents 1–5) | Example paths | Proposed fix | Risk |
|---|---|---:|---|---|---|
| 1 | F1 UNREACHABLE root model → empty result despite visible local open | 400–450 | t-dyn/src/dyn730/dyn730Init.c:478,487; t-dif/src/dif901/dif901IntDll.c:200+; t-tmm/tool/opmtool/tmmtool.c:69,76 | When root tracking yields UNREACHABLE, fall back to same-function back-walk: find the live `mpf_mfs_open*` of the target handle between the last `close` and the target, and resolve its file-number argument. Never emit empty for a handle with a visible local open. | Low — strictly additive (new values only on sites currently empty); keep the fallback value tagged `LOCAL_BACKWALK` so it can be audited |
| 2 | F3 direct macro/enum/#define arg not emitted (possible SJIS header parse gap) | 150–170 | t-dyn/src/libDynDspCom/LibDynDspCom.c:151; t-dif/src/dif400d/dif400Deque.c:65; t-dyn/src/dyn710/dyn710Init.c:292 | Verify the macro index parses the active non-UTF8 (SJIS) headers end-to-end; add per-header unit tests (one known enum value per active header: DynReEneFileDef.h, Dif.h, DifP.h, dxi_const.h, TmmFileNo.h, ChaDef.h); emit EXACT for a bare-identifier open arg that is a macro in an active header | Low — additive; the parser-encoding check may reveal a systemic bug, which is the point |
| 3 | F2 wrapper/table-lookup helpers not unwrapped (bounded constant sets) | 125–130 | t-dyn/src/libDynRe/DynREGetSchePos.c:40-57 (tables); call site t-dyn/src/dyn600/dyn600MainProc.c:1042; t-cha/src/libCha/ChaGetFileInfo.c; t-dxi/src/libdxiinside/dxi_uptbn.c:74 | Add a "constant-table range" abstraction: if a callee returns `tbl[i]` of a static constant array, its abstract value is the array's element set. Hand-map the ~6 known wrappers (DynREGet{Sch,SchKK,SchKKLC,Pfm}fno, ChaGetFileInfo, Dxi_{Up,Dn}Tbn*FileOpen) | Medium — new value family (sets); must be labeled as range-abstract so downstream consumers don't treat 16 values as 16 exact paths |
| 4 | F4 stale-initializer overapproximation (`0`) | 8–10 (1 file) | t-cha/src/libChaLrg/ChaLrgCom.c:458,470,477,657,663,996,1008,1015,1127,1133 | Model "wrapper writes &var; error path returns" ⇒ initializer value killed before use. Until then: suppress emitting a variable's zero-initializer as an EXACT value when the last pre-use event is an unresolved call writing the variable — emit status/wrapper-range instead | Medium — removes values; verify no site relies on the 0 as a legitimate "no file" open (none found in this codebase: all 10 opens follow a successful ChaGetFileInfo) |
| 5 | F6 pointer-parameter handles / caller edges | 25–30 | t-tmm/src/tmm910/tmm910_gnqmnt.c:636; t-cha/src/libChaCom/ChaCase.c (ChaReadRecm/ChaReadSv/ChaWriteRecn) | For target args that are pointer parameters, enumerate in-tree callers and resolve the passed expression (and its open). Agents did this manually with 100% success on all such sites | Low — additive; bounded by caller count in this codebase |
| 6 | F5 branch-merge drops middle `else if` arm | 4–5 | t-dxi/src/dxi110d/dxi110d_parent.c:1582-1591 → sites 1687,1695; t-dxi/src/libdxiinside/dxi_initmng.c:72,80 | Assert merged value-set size == live arm count for single-assignment if/else-if chains; regression-test 3-arm chains incl. recently-added arms (#30017) | Low |
| 7 | F7 file-static FCB tracking | few (will recur) | t-dyn/src/libDynRe/DynReEneOutStaFunc.c:131,143 (SFcbRE opened in DynReEneOutStaGet → 3937) | Track file-scope `static MPF_MFS_FCB` vars across functions | Low |
| 8 | F8 string-literal flow to forkproc | few | t-dyn/src/dyn600/dyn600MainProc.c:1262 {"ECS-A","ECS-B"}; t-dxi/src/libdxiinside/dxi_dblcirreq.c:100 {"dxi500d","dxi501d","dxi502d"} | Constant-propagate literals through memset/strcpy of local char buffers; special-case forkproc's name argument | Low |

## 6. Bottom line (agents 1–5 evidence only)

- **c-viz is more precise than legacy on this population**: c-viz had 10
  rejected values (all one bug, F4); legacy had 30 (agent1: 21 pre-#31214
  stale FNOs + agent3: 7) plus 2 `#if 0`-define picks in agent5
  (`dxi900_ss.c:148`: legacy 2511 from disabled `#define DXI_FNO_ITCSSDEF 2511`
  vs active 2515, t-dxi/include/dxi_const.h:246-249).
- **c-viz is also more complete**: it is the *only* pipeline with a concrete
  value on ~186 (agent2) + ~97 (agent4) + ~57 (agent3) + ~45 (agent5)
  sites where legacy gave nothing.
- **Its dominant weakness is recall, not precision**: roughly 400–450 sites
  where a same-function open makes the value trivially provable but c-viz
  says UNREACHABLE (F1), plus the wrapper/table and macro-emission gaps
  (F2/F3). Fixes #1–#3 in §5 are additive-only and together address the
  large majority of missed values.

## 7. Caveats / known limitations of this consolidation

1. **Agent 6 (t-sim, t-svm, t-rep — 393 sites) was never run.** Failure-mode
   frequencies may shift when it completes; F7 (static FCB) and F8
   (forkproc strings) are expected to recur there.
2. Agent 1's batch prep had a grep-substring collision: claim rows attributed
   to `dyn401dScheCtrl.c` (lines 214/222/363/371/373/381) actually belong to
   `dyn401dRequest.c` in the current source; the two real `dyn401dScheCtrl.c`
   sites (191, 196) were audited (agent1.md open items).
3. Coverage percentages are not directly comparable across agents: the
   denominators differ in how table-lookup expected sets are counted
   (value-level in agent1, distinct-value in agent3, site-level in
   agents 2/4/5).
4. Agent 3's precision denominator (369) includes legacy macro-name values;
   the other agents report c-viz-only denominators. The claim "10 rejected
   c-viz values total" holds under either reading (agent 3's 7 rejects are
   explicitly attributed to legacy stale enums).
5. Legacy provenance line numbers in `valueflow_proof.csv` are offsets into a
   stale monolithic snapshot (e.g. "dyn232dMsg.c:6033" in a 545-line file) and
   were not usable as evidence by any agent; all verdicts rest on the current
   `/home/chukyu` source.
6. Medium-confidence items: runtime-table-indexed sites (the *element* is
   data-dependent; the full bounded set is what was judged), and
   caller-enumerated sets that assume the in-tree caller list is complete.

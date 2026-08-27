# Step 1 — Indirect value-flow comparison

This report compares only active target calls whose argument is not a literal or a single directly passed macro. These are the cases that require value-flow tracing, helper-parameter backwalking, handle/FCB matching, or LLM assistance.

## What the words mean

- A **site** is one target call location, operation, and argument position.
- An **indirect site** has an argument such as `file_no`, `&fcb`, a helper parameter, or an expression instead of a direct literal/macro.
- A **value** is a concrete numeric file/queue number or a concrete fork-process name.
- **c-visualizer-only site** means c-visualizer discovered the active indirect call but the legacy proof file has no matching site.
- **legacy-only site** means the legacy proof file has the active indirect call but c-visualizer has no matching site.
- The value comparison uses sets: if one site can have several possible values, all values are compared together.

## What each number means

| What the number means | c-visualizer | legacy |
| --- | --- | --- |
| Active indirect comparison sites (location + operation) | 2,355 | 1,122 |
| Concrete value possibilities found across those locations | 508 | 698 |
| Unique concrete values, ignoring where they were found | 122 | 193 |
| Legacy indirect sites with LLM-assisted proof | not applicable | 724 |

These rows count different things and must not be added together. Direct constants/macros are deliberately absent here; they belong to Step 0.

### 1. Active indirect comparison sites

c-visualizer counted **2,355 comparison sites** where the target argument is indirect—for example `&fcb`, `file_no`, a helper parameter, or another expression. Legacy has **1,122**. A comparison site includes the operation label, so the same physical call can appear separately when the tools describe its operation differently.

### 2. Concrete value possibilities

c-visualizer found **508 value-at-location entries**; legacy found **698**. A single location can contribute several entries. For example, `/home/chukyu/t-svm/src/svm000/svm000FileInt.c:895` contributes nine c-visualizer possibilities (`2621` through `2629`) but one legacy possibility (`2622`).

This is why the value count can be larger than the location count. It measures how many possible values were attached to source locations, not how many unique numbers exist.

### 3. Unique values across the whole comparison

After removing repeated values from different locations, c-visualizer has **122 unique values** and legacy has **193**. For example, if `2622` appears at 100 different locations, it still counts as one unique value here. This number says nothing by itself about which tool is correct.

### 4. Legacy LLM-assisted proof

The legacy proof marks **724 indirect sites** as having LLM involvement. In plain English: at 724 source call locations, the legacy pipeline used or recorded an LLM-assisted backwalk while trying to determine the argument’s value. This is a count of locations—not 724 LLM calls and not 724 successfully resolved values. For example, `/home/chukyu/t-dyn/src/dyn010/dyn010Main.c:195` has two legacy proof rows for the same call, but it counts as one LLM-assisted site. The c-visualizer cell says `not applicable` because this row describes a legacy-specific proof flag.

## Why the numbers differ

### Why does c-visualizer have more comparison sites?

There are **1,455 c-visualizer-only operation-aware sites**. Of these, **1,368** are marked `UNREACHABLE`. That means c-visualizer found the target call in active source code, but did not find a path to it from a recognized entry point. These are discovered call locations, not successful value resolutions. Legacy also has **1,470** proof locations with no original argument expression; those are excluded because we cannot tell whether their argument was indirect.

For example, `/home/chukyu/t-dif/src/libdif/difSVRep.c:198` calls `pmf_forkprocbs_H(cpuname)`. c-visualizer records this active target call as `UNREACHABLE`; the legacy proof file has no corresponding row. This increases c-visualizer’s discovery count even though no value was resolved.

There is also an operation-label issue. Ignoring the operation name, the tools share **1,103 physical call locations**; c-visualizer has **1,252 physical locations** legacy does not have, and legacy has **19**. **203 shared physical locations** use different operation labels. For example, `/home/chukyu/t-cha/src/cha101d/cha101dSVSave.c:133` is labeled `OPEN_LOCK` by c-visualizer and `READ` by legacy. It is one source call, not two calls.

### Why does legacy have more concrete value entries?

The total can be reconstructed like this:

| Operation-aware site group | c-visualizer values | legacy values |
| --- | --- | --- |
| Sites present in both | 344 | 667 |
| c-visualizer-only sites | 164 | 0 |
| legacy-only sites | 0 | 31 |
| Total | 508 | 698 |

On shared sites, legacy has a concrete value at **647 sites**, while c-visualizer has one at **264 sites**. This is why legacy’s total is larger despite having fewer sites overall. Legacy contributes **479 shared sites** where it has a value and c-visualizer currently has none. c-visualizer contributes **96 shared sites** in the opposite direction, plus its c-visualizer-only sites.

A concrete legacy example is `/home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c:106`: the indirect argument is `&sCaseManFcb`. Legacy backwalking reaches `ChaCaseManageNo` and records `2836`; the current c-visualizer facts have no concrete value for that site. Conversely, at `/home/chukyu/t-svm/src/svm000/svm000FileInt.c:895`, c-visualizer produces nine possible values while legacy produces one.

### Why does legacy have more unique values?

Legacy has **193 different concrete values** across its entries, while c-visualizer has **122**. On the shared operation-aware sites, legacy contains **188 unique values** and c-visualizer contains **87**. The shared value sets overlap on **62 values**; the rest come from different resolutions or from sites only one tool recorded.

For example, `/home/chukyu/t-dyn/src/dyn010/dyn010Main.c:195` is the same indirect `&fcb` call in both outputs, but c-visualizer gives `1081` and legacy gives `1077`. A difference like this increases the unique-value count on both sides, but it is a disagreement that needs source inspection—it does not prove either value is correct.

## Did both tools discover the same indirect calls?

| Plain-English measure | Count |
| --- | --- |
| Present in both active indirect populations | 900 |
| Found only by c-visualizer | 1,455 |
| Found only by legacy | 222 |

The common-site comparison has **900 sites**. The c-visualizer site coverage of the legacy indirect population is **80.2%**; this is a discovery measure, not a correctness score.

## Did they resolve the same values at the same sites?

| What happened at a shared site | Sites |
| --- | --- |
| Both produced exactly the same value set | 128 |
| c-visualizer produced a strict superset | 7 |
| Legacy produced a strict superset | 0 |
| Both overlap but disagree | 0 |
| Both resolved, but values are disjoint | 33 |
| Only c-visualizer produced a concrete value | 96 |
| Only legacy produced a concrete value | 479 |
| Neither produced a concrete value | 157 |

A c-visualizer superset means it found every legacy value plus additional possible values at that same call site. That is the main category to inspect for the hypothesis that source-tree path enumeration finds more legitimate possibilities. It is not automatically proof that every extra value is correct.

## Legacy LLM-backwalk subset

Among the **522 shared sites** where the legacy proof records LLM involvement, the value-set categories are:

| Category | Sites |
| --- | --- |
| both unresolved | 154 |
| cvisualizer resolved only | 96 |
| cvisualizer superset | 4 |
| disjoint | 33 |
| equal | 21 |
| legacy resolved only | 214 |

c-visualizer has **76 distinct indirect values** whose fact was resolved without `resolved_by=LLM`. The report also retains all exact values separately, so LLM-assisted c-visualizer rows are not silently mixed into that deterministic count.

## Examples

### Same values

- `/home/chukyu/t-dif/src/dif000/dif000Main.c:428` — `mpf_mfs_getrec` / `GETREC` / argument `1`.
  - c-visualizer expression(s): `&fcb`; values: `2022`.
  - legacy raw expression(s): `&fcb`, `DifStatusNo`; values: `2022`; statuses: `ADDED`, `OK_MACRO`.
  - Source review: Both results are supported. `fcb` is opened with `DifStatusNo` at line 417, and the target call at line 428 uses that same handle. The legacy macro table maps `DifStatusNo` to 2022.
- `/home/chukyu/t-dif/src/dif000/dif000Main.c:637` — `mpf_mfs_getrec` / `GETREC` / argument `1`.
  - c-visualizer expression(s): `&fcb`; values: `2045`.
  - legacy raw expression(s): `&fcb`, `DifBackUpNo`; values: `2045`; statuses: `ADDED`, `OK_MACRO`.
  - Source review: Both results are supported. `fcb` is opened with `DifBackUpNo` at line 626, and the target call at line 637 uses that handle. The legacy macro table maps `DifBackUpNo` to 2045.
- `/home/chukyu/t-dif/src/dif000/dif000Main.c:664` — `mpf_mfs_getrec` / `GETREC` / argument `1`.
  - c-visualizer expression(s): `&fcb`; values: `2022`.
  - legacy raw expression(s): `&fcb`, `DifStatusNo`; values: `2022`; statuses: `ADDED`, `OK_MACRO`.
  - Source review: Both results are supported. After the first handle is closed, the same `fcb` is reopened with `DifStatusNo` at line 653; line 664 then reads through it. The 2022 result is source-consistent.

### c-visualizer found more values

- `/home/chukyu/t-svm/src/svm000/svm000FileInt.c:895` — `mpf_mfs_writerecn` / `WRITEREC` / argument `1`.
  - c-visualizer expression(s): `&fcb_kansimng`; values: `2621`, `2622`, `2623`, `2624`, `2625`, `2626`, `2627`, `2628`, `2629`.
  - legacy raw expression(s): `&fcb_kansimng`, `SvmKansiMngNo`; values: `2622`; statuses: `ALREADY_PRESENT`, `OK_CONST`.
  - Source review: The legacy result is the source-backed one. `fcb_kansimng` is opened with `SvmKansiMngNo` at line 799, and `SvmKansiMngNo` is 2622 in `/home/chukyu/t-svm/include/svm/SvmFile.h:172`. The c-visualizer values 2621-2629 are an overapproximation caused by matching other file numbers used in the same function; they are not nine real possibilities for this handle.
- `/home/chukyu/t-svm/src/svm000/svm000FileInt.c:906` — `mpf_mfs_writerecn` / `WRITEREC` / argument `1`.
  - c-visualizer expression(s): `&fcb_kansilist`; values: `2621`, `2622`, `2623`, `2624`, `2625`, `2626`, `2627`, `2628`, `2629`.
  - legacy raw expression(s): `&fcb_kansilist`, `SvmKansiListNo`; values: `2623`; statuses: `ADDED`, `OK_MACRO`.
  - Source review: The legacy result is the source-backed one. `fcb_kansilist` is opened with `SvmKansiListNo` at line 807, and that macro is 2623 in `/home/chukyu/t-svm/include/svm/SvmFile.h:173`. The c-visualizer nine-value set is the same handle-matching overapproximation.
- `/home/chukyu/t-svm/src/svm000/svm000FileInt.c:909` — `mpf_mfs_writerecn` / `WRITEREC` / argument `1`.
  - c-visualizer expression(s): `&fcb_jkrcls`; values: `2621`, `2622`, `2623`, `2624`, `2625`, `2626`, `2627`, `2628`, `2629`.
  - legacy raw expression(s): `&fcb_jkrcls`, `SvmJKRclsKnrNo`; values: `2625`; statuses: `ADDED`, `OK_MACRO`.
  - Source review: The legacy result is the source-backed one. `fcb_jkrcls` is opened with `SvmJKRclsKnrNo` at line 837, and that macro is 2625 in `/home/chukyu/t-svm/include/svm/SvmFile.h:175`. The c-visualizer values 2621-2629 are therefore too broad here.

### Both resolved different values

- `/home/chukyu/t-dyn/src/dyn010/dyn010Main.c:195` — `mpf_mfs_writerecn` / `WRITEREC` / argument `1`.
  - c-visualizer expression(s): `&fcb`; values: `1081`.
  - legacy raw expression(s): `&fcb`, `DynReCtlMainteFNO`; values: `1077`; statuses: `ALREADY_PRESENT`, `OK_CONST`.
  - Source review: The legacy linkage is better supported. The same `fcb` is opened with `DynReCtlMainteFNO` at line 181, immediately before this write. The c-visualizer value 1081 is not supported by that handle-open path. The legacy table maps the macro to 1077, although this source tree also contains a newer 3973 file-number table, so the numeric value must be interpreted with the pipeline's table version.
- `/home/chukyu/t-dyn/src/dyn232d/dyn232dMsg.c:158` — `mpf_mfs_readrecn` / `READREC` / argument `1`.
  - c-visualizer expression(s): `&fcb`; values: `3911`.
  - legacy raw expression(s): `&fcb`, `DynReSchSetTkFNO`; values: `3910`; statuses: `ALREADY_PRESENT`, `OK_CONST`.
  - Source review: The legacy result is supported for this branch. Lines 146-149 show that `fcb` is opened with `DynReSchSetTkFNO` before line 158; the source header identifies that file as 3910. The c-visualizer 3911 does not match the macro used by this open.
- `/home/chukyu/t-dyn/src/dyn234d/dyn234dAdvCtl.c:216` — `mpf_mfs_readrecn` / `READREC` / argument `1`.
  - c-visualizer expression(s): `&fcb_AdvInd`; values: `0`.
  - legacy raw expression(s): `&fcb_AdvInd`, `DynAdvCtlStaITkFNO`; values: `3914`; statuses: `ADDED`, `OK_CONST`.
  - Source review: Neither single value is a complete answer. At lines 185-191, `iFnoInd` is selected from `DynAdvCtlStaITkFNO` or `DynAdvCtlStaIndFNO`, and line 208 opens `fcb_AdvInd` with that variable. Legacy 3914 captures the old taiko macro-table entry, while c-visualizer 0 means it did not resolve the variable; the source requires both conditional possibilities (current header values are 3983 and 3946).

### Only c-visualizer resolved a value

- `/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:78` — `pmf_forkproc_H` / `FORKPROC` / argument `1`.
  - c-visualizer expression(s): `PROC_NAME`; values: `dyn600`.
  - legacy raw expression(s): none; values: none; statuses: none.
  - Source review: c-visualizer is right here. `PROC_NAME` is defined as `"dyn600"` at `/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:33`, so the call at line 78 has a direct source definition. The legacy index has no row for this call.
- `/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:174` — `pmf_forkproc_H` / `FORKPROC` / argument `1`.
  - c-visualizer expression(s): `PROC_NAME`; values: `dyn600`.
  - legacy raw expression(s): none; values: none; statuses: none.
  - Source review: c-visualizer is right here for the same reason: `PROC_NAME` is defined as `"dyn600"` at line 33. Legacy missed this direct macro use entirely.
- `/home/chukyu/t-dyn/src/libDynRe/DynReEneLib.c:222` — `pmf_forkproc_H` / `FORKPROC` / argument `1`.
  - c-visualizer expression(s): `PROC_NAME`; values: `dyn600`.
  - legacy raw expression(s): none; values: none; statuses: none.
  - Source review: c-visualizer is right here for the same reason: `PROC_NAME` is defined as `"dyn600"` at line 33. Legacy missed this direct macro use entirely.

### Only legacy resolved a value

- `/home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c:106` — `mpf_mfs_readrecm` / `READREC` / argument `1`.
  - c-visualizer expression(s): `&sCaseManFcb`; values: none.
  - legacy raw expression(s): `&sCaseManFcb`, `ChaCaseManageNo`; values: `2836`; statuses: `ADDED`, `OK_MACRO`.
  - Source review: The legacy result is source-backed. `sCaseManFcb` is opened with `ChaCaseManageNo` at line 97, then read at line 106. `ChaCaseManageNo` is 2836, so c-visualizer missed the deterministic handle-to-open connection.
- `/home/chukyu/t-cha/src/cha001/cha001ClrCaseMan.c:147` — `mpf_mfs_writerecm` / `WRITEREC` / argument `1`.
  - c-visualizer expression(s): `&sCaseManFcb`; values: none.
  - legacy raw expression(s): `&sCaseManFcb`, `ChaCaseManageNo`; values: `2836`; statuses: `ADDED`, `OK_MACRO`.
  - Source review: The legacy result is source-backed. The same `sCaseManFcb` opened with `ChaCaseManageNo` at line 97 is written at line 147, so 2836 is the correct propagated value and c-visualizer missed it.
- `/home/chukyu/t-cha/src/cha001/cha001Main.c:171` — `mpf_mfs_readrecm` / `READREC` / argument `1`.
  - c-visualizer expression(s): `&recman_fcb`; values: none.
  - legacy raw expression(s): `&recman_fcb`, `ChaRecManageNo`; values: `2839`; statuses: `ADDED`, `OK_MACRO`.
  - Source review: The legacy result is source-backed. Lines 164-166 open `recman_fcb` with `ChaRecManageNo`, and line 171 immediately reads through that handle. `ChaRecManageNo` is 2839; c-visualizer did not propagate the open into this target call.

## What these examples show

This small sample does not mean that one tool always wins. It shows three different behaviors:

- The three `dif000` examples agree, and the source confirms both results by following the handle back to the matching `mpf_mfs_open` call.
- The SVM examples are a warning: c-visualizer reported nine candidates, but the source opens each named handle with one specific macro. Legacy is correct there; c-visualizer was too broad.
- In `dyn010` and `dyn232d`, legacy follows the handle to the specific open call while c-visualizer selects an unsupported number. In `dyn234d`, the source has two conditional possibilities, so legacy is only partially right and c-visualizer is incomplete.
- The `dyn600` fork-process examples are genuine c-visualizer wins: the source defines `PROC_NAME` as `"dyn600"`, while legacy has no record.
- The CHA examples are genuine legacy wins in this comparison: the source directly opens the same handle with `ChaCaseManageNo` or `ChaRecManageNo`, but c-visualizer did not carry that value from the open to the later read/write call.

The main lesson is that a larger set is useful only when every value can be tied to a real source path. A source-backed single value is better than an unproven list of nearby values.

## Excluded source lines

Commented, blank, `#if 0`-disabled, and missing-source locations are excluded from the active Step 1 denominator. Their counts are retained in the JSON report under `populations.cvisualizer.excluded_sites` and `populations.legacy.excluded_sites`.

## Limitations

- This comparison measures equivalence and discovery; it does not by itself prove which extra value is correct.
- A source-backed review of representative c-visualizer-superset, legacy-superset, and disjoint cases is still required.
- Legacy rows without an original argument expression are not called indirect; they are classified as unknown and excluded rather than being used as a misleading denominator.

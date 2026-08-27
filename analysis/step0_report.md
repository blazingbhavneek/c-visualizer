# Step 0 — Direct CONST/MACRO comparison

This report compares only target calls where the target argument itself is a literal or a directly named macro. It uses the existing c-visualizer and legacy outputs; it does not run either pipeline.

## What is included

- A **constant** is a number or string written directly in the target argument, such as `1055` or `"cha001"`.
- A **direct macro** is a macro name written directly in the target argument, such as `DifDefineNo`, with a `#define` proof for its value.
- A **record** means one source location, operation, and resolved value in an index.
- A **shared record** is present in both indexes with the same file, line, operation, and value.
- A **c-viz-only record** is in the c-visualizer index but not the legacy index.
- A **legacy-only record** is in the legacy index but not the c-visualizer index.

## What is deliberately excluded

This step does not count values that arrive through a helper parameter or variable, such as `file_no`, `filenum`, or `fno`. It also excludes `&fcb`/handle matching, proximity matching, LLM results, and other data-flow propagation. Those are Step 1 cases.

For example, c-visualizer may eventually resolve `file_no` to four macros, but the target argument is still the variable `file_no`; it is not a direct CONST/MACRO target argument.

## The direct comparison

| What the number means | Records | Source locations |
| --- | --- | --- |
| c-visualizer direct values in final aggregate index | 318 | 318 |
| legacy direct values | 1,218 | 1,218 |
| same value in both indexes | 239 | 239 |
| found only by c-visualizer | 79 | 79 |
| found only by legacy | 979 | 979 |

The final c-visualizer index has **318 direct records**. The legacy index has **1,218 direct records**. They share **239 records**. c-visualizer has **79 additional records**, while legacy has **979 records that c-visualizer does not have**.

The c-visualizer evidence file contains **377 direct exact rows** before aggregate-index filtering. **59** of those were not promoted into the final aggregate index, so the comparison above uses the final index rather than mixing evidence rows with index rows.

## Counts by target type

| Target type | c-visualizer | legacy | shared | c-viz-only | legacy-only |
| --- | --- | --- | --- | --- | --- |
| MFS file operations | 241 | 950 | 191 | 50 | 759 |
| MFS queue operations | 12 | 124 | 10 | 2 | 114 |
| forkproc calls | 65 | 144 | 38 | 27 | 106 |

## Examples you can open directly

### Same direct macro in both indexes

Target call: **`/home/chukyu/t-dif/src/dif001/dif001Main.c:175` — `READ`, value `2021`**.

c-visualizer proof: target expression `DifDefineNo`; proof at `/home/chukyu/t-dif/include/DifP.h:75`. The macro definition is `/home/chukyu/t-dif/include/DifP.h:75`, where `DifDefineNo` is `2021`. This is the expected agreement case.

### c-viz-only direct constant in a `tool/` file

Target call: **`/home/chukyu/t-rep/tool/msgreq/msgreq.c:421` — `ADDQUE`, value `1055`**.

c-visualizer proof: target expression `1055`; proof at `/home/chukyu/t-rep/tool/msgreq/msgreq.c:421`. The argument is the literal `1055`. The legacy `build_index.py` source collector scans `t-*/src`, so it does not scan this `t-*/tool` file.

This is a genuine direct-constant discovery difference, not a propagated value.

### c-viz-only direct macro from an external header

Target call: **`/home/chukyu/t-tmm/src/tmm910/tmm910_main.c:58` — `READ`, value `3652`**.

c-visualizer proof: target expression `FfeMntInfoFileNo`; proof at `/home/chukyu_exe/include/ffe/FfeMntInfo.h:25`. The macro `FfeMntInfoFileNo` resolves to `3652` at `/home/chukyu_exe/include/ffe/FfeMntInfo.h:25`. The target argument itself is the macro, so this is still Step 0.

The old index has no matching record for this direct call. This example shows c-viz resolving a direct macro whose definition is outside the ordinary `t-*/src` scan.

### Legacy-only direct macro where c-viz missed the target site

Target call: **`/home/chukyu/t-dif/src/dif900/dif900IntBackUp.c:70` — `CLEAR`, value `2045`**. The macro definition is `/home/chukyu/t-dif/include/DifP.h:96`, where `DifBackUpNo` is `2045`.

c-visualizer has a fact for this direct target but its status is `UNREACHABLE`. Therefore it does not promote a value into the final index. This does **not** prove that the source call is unreachable.

The source call is inside `Dif900InitBackUp()`, which is called by `pmf_main_H()` at `/home/chukyu/t-dif/src/dif900/dif900Main.c:208`. The existing c-viz per-process output also traces that same function from `pmf_main_H` to its `mpf_mfs_open` at `/home/chukyu/t-dif/src/dif900/dif900IntBackUp.c:75` and `mpf_mfs_getrec` at line 86. The correct interpretation is: **the function is reachable, but c-viz failed to establish reachability for this particular `mpf_mfs_clearfile` target record**.

### Legacy-only direct macro inside disabled code

Target call: **`/home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:188` — `WRITE`, value `2820`**. This call is inside a `#if 0` block beginning at `/home/chukyu/t-cha/src/cha101d/cha101dTMSave.c:168`; the call itself is at line 188. The macro is `ChaOnlWorkTMNo`, defined at `/home/chukyu/t-cha/include/ChaDef.h:76`.

The old index records the value, but the preprocessor disables this code. This is one concrete reason legacy-only records cannot all be treated as live targets.

## Legacy-only records that are visibly not live

The source check classified the legacy-only direct records as follows:

| What this means | Records | Source locations |
| --- | --- | --- |
| Active-looking source code | 954 | 954 |
| Inside `#if 0` (disabled code) | 25 | 25 |

At least **25 legacy-only direct records** are visibly disabled or commented. The remaining legacy-only records are active-looking source records; they need separate target-level reachability or discovery analysis and must not be dismissed as no-op automatically. A c-viz `UNREACHABLE` status by itself is not proof that the surrounding function is unreachable.

## Bottom line

This is the clean baseline comparison for direct constants and direct macros. Step 0 shows which simple values both tools agree on, which direct values c-viz adds, and which direct values legacy has that c-viz has not promoted. Propagated values such as the `file_no` example are intentionally excluded and belong in Step 1.

## Reproduction from existing outputs

This command reads existing files and writes only the Markdown report; it does not run the analysis pipeline:

```bash
python analysis/step0.py --cvisualizer-index results/csv_results/index \
  --legacy-index ../index --source-root /home/chukyu \
  --output analysis/step0_report.md
```

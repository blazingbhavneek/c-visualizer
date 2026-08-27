# Step 0: `dif900` direct constant/macro comparison

This is a small process-level check. It compares only direct target arguments in:

`/home/chukyu/t-dif/src/dif900`

It does not rerun the full repository pipeline. The fixed c-visualizer output was produced by the already completed isolated `dif900` run at:

`/tmp/cviz-dif900-fixed2.QgLIe9/dif900/index`

The legacy comparison input is:

`/home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index`

## What is being counted

- A **direct constant/macro record** means the target argument itself is a number, string, or macro name. For example, `DifBackUpNo` is written directly as the target argument.
- A **record** means one source file, line, operation, and resolved value. For example, `dif900IntBackUp.c:70`, `CLEAR`, `2045` is one record.
- **Shared** means both indexes contain the same record.
- **Legacy-only** means the legacy index contains the record but the fixed c-visualizer index does not contain that exact resolved record.

Values passed through variables or helper parameters are not counted here. Those belong to Step 1.

## Result

| Plain-English measure | Fixed c-visualizer | Legacy | Meaning |
| --- | ---: | ---: | --- |
| Direct constant/macro records | 43 | 43 | How many simple, directly written values each index recorded |
| Same record in both | 43 | 43 | Every direct c-viz record agrees exactly with legacy |
| Only c-visualizer | 0 | — | c-viz did not invent a different direct result in this process |
| Only legacy | — | 0 | No direct legacy record is missing from fixed c-viz |

The fixed c-visualizer result matches **all 43 legacy direct records (100%)**. Every record agrees on the file, line, operation, and value.

This is not a 900-record direct-value failure in `dif900`. For this process the direct gap is **zero** after the target-only macro fix.

## Before and after the fix

The old checked-in c-visualizer aggregate was also filtered to the same `dif900` source directory:

| Version | Direct c-viz records | Shared with legacy | Legacy-only records |
| --- | ---: | ---: | ---: |
| Old c-visualizer result | 26 | 26 | 17 |
| Fixed c-visualizer result | 43 | 43 | 0 |

The fix added **17 legitimate direct records** in this process:

- **12 `CLEAR` macro calls**, including `/home/chukyu/t-dif/src/dif900/dif900IntBackUp.c:70` → `2045`.
- **2 `COPYFILE_FROM` macro arguments**, at `/home/chukyu/t-dif/src/dif900/dif900IntDll.c:1503` → `2039` and line `1678` → `2040`.
- **2 `COPYFILE_TO` macro arguments**, at the same two call sites → `2039` and `2040`.
- **1 `OPEN_LOCK` macro argument**, at `/home/chukyu/t-dif/src/dif900/dif900IntSpeDef.c:106` → `2048`.

These are real active source calls, not comments or `#if 0` code. The macro values are defined in `/home/chukyu/t-dif/include/DifP.h`, and the wrapper definitions are in `/home/seigyo/opt-modern/include/mpf_mfs.h`.

## Direct proof that the previously missing call is now fixed

Source call:

`/home/chukyu/t-dif/src/dif900/dif900IntBackUp.c:70`

```c
mpf_mfs_clearfile( DifBackUpNo, -1,fonsub );
```

Macro value:

`/home/chukyu/t-dif/include/DifP.h:96` defines `DifBackUpNo` as `2045`.

Wrapper expansion:

`/home/seigyo/opt-modern/include/mpf_mfs.h:862` expands `mpf_mfs_clearfile(...)` to `mpf_mfs_clearcc(...)` while preserving the file-number argument.

Old c-viz fact:

`UNREACHABLE`, with no value.

Fixed c-viz fact:

`EXACT`, target expression `DifBackUpNo`, value `2045`, proof source `/home/chukyu/t-dif/include/DifP.h:96`.

The surrounding function is reachable: `/home/chukyu/t-dif/src/dif900/dif900Main.c:208` calls `Dif900InitBackUp()`, which contains the target call. So this specific record was missed because of the macro-wrapper identity problem, not because `pmf_main_H` was an invalid starting root.

## The formerly missing macro-wrapper records

The previous run had three legacy-only records. After resolving configured target macros against their original source-call arguments, all three now resolve exactly:

| Source call | Legacy value | Fixed c-viz result |
| --- | ---: | --- |
| `/home/chukyu/t-dif/src/dif900/dif900IntDll.c:1503` `COPYFILE_TO` | 2039 | `EXACT`, value `2039` |
| `/home/chukyu/t-dif/src/dif900/dif900IntDll.c:1678` `COPYFILE_TO` | 2040 | `EXACT`, value `2040` |
| `/home/chukyu/t-dif/src/dif900/dif900IntSpeDef.c:106` `OPEN_LOCK` | 2048 | `EXACT`, value `2048` |

The relevant wrapper definitions are:

- `/home/seigyo/opt-modern/include/mpf_mfs.h:787`: `mpf_mfs_copyfile` expands to `mpf_mfs_copyrec`, whose destination argument has a different position.
- `/home/seigyo/opt-modern/include/mpf_mfs.h:809`: `mpf_mfs_openm_H` expands to `mpf_mfs_open` and inserts `MPF_MFS_SEARCH_CPU`.
- `/home/chukyu/t-dif/include/DifP.h:111`: `DifSpeDvDefNo` is `2048`.

The resolver now preserves the original source arguments for configured target macros, while still retaining expanded arguments for ordinary parameter-flow traversal.

## Cross-check: `dif901`

I ran the same isolated fixed resolver on:

`/home/chukyu/t-dif/src/dif901`

Its Step 0 comparison was:

| Plain-English measure | Fixed c-visualizer | Legacy |
| --- | ---: | ---: |
| Direct constant/macro records | 17 | 43 |
| Same record in both | 17 | 17 |
| Fixed c-viz-only records | 0 | — |
| Legacy-only records | — | 26 |

The important cross-check is that **all 17 records c-viz did resolve match legacy exactly**, including `/home/chukyu/t-dif/src/dif901/dif901IntSpeDef.c:108` `mpf_mfs_openm_H(..., DifSpeDvDefNo, ...)` → `2048`.

The 26 legacy-only records are a separate reachability/source-scope issue. For example, `/home/chukyu/t-dif/src/dif901/dif901Main.c:253` has `dif901InitBackUp()` inside a commented-out block. The backup target at `/home/chukyu/t-dif/src/dif901/dif901IntBackUp.c:80` is therefore not reached from the active `pmf_main_H` path. This is the kind of legacy row that must be separated from a macro-resolution failure.

The fixed `dif901` output is at `/tmp/cviz-dif901-fixed.ashvkS/dif901/index`.

## Cross-check: `cha001`

I also ran the fixed resolver on:

`/home/chukyu/t-cha/src/cha001`

This process contains multiline target calls, so it checks both macro expansion and source-location handling:

| Plain-English measure | Fixed c-visualizer | Legacy |
| --- | ---: | ---: |
| Direct constant/macro records | 21 | 21 |
| Same record in both | 21 | 21 |
| c-viz-only records | 0 | — |
| Legacy-only records | — | 0 |

Examples include `/home/chukyu/t-cha/src/cha001/cha001Main.c:165` → `2839` and `/home/chukyu/t-cha/src/cha001/cha001ModeInit.c:175` → `2808` for both copy directions. All 21 direct records agree exactly. The Step 0 checker was also corrected to recognize a direct macro argument on a following line of the same target statement; this avoids undercounting multiline legacy records.

The fixed `cha001` output is at `/tmp/cviz-cha001-fixed.DluASG/cha001/index`.

## Conclusion for the 900-record concern

For this known process, the fixed resolver is now bringing in the legitimate direct macro calls. The direct comparison went from **26/43** to **43/43**, and the previously suspicious backup call now resolves exactly to `2045`.

There is now no direct-value difference for `dif900`. The `dif901` cross-check shows why larger repository-wide gaps must be split by cause: some legacy rows come from inactive/commented call paths, while configured macro-wrapper argument remapping is now handled correctly.

The `cha001` cross-check confirms the same result on a different package: no direct legacy record is missing after accounting for multiline calls.

## Files containing the fixed evidence

- Fixed process index: `/tmp/cviz-dif900-fixed2.QgLIe9/dif900/index`
- Fixed facts CSV: `/tmp/cviz-dif900-fixed2.QgLIe9/dif900/index/discovery_facts.csv`
- Fixed aggregate file index: `/tmp/cviz-dif900-fixed2.QgLIe9/dif900/index/mfs_file_access.json`
- Fixed execution log for the backup call: `/tmp/cviz-dif900-fixed2.QgLIe9/dif900/logs/001_mpf_mfs_clearfile_dif900IntBackUp.c_70_arg1_2045.log`
- Legacy file index: `/home/seigyo/c-parse/source_research_tool-linux/forkproc_checker/index/mfs_file_access.json`

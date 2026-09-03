# Target-function discovery: legacy vs C-visualizer

Legacy index: `../index_baseline`

New index: `results_backup/csv_results6/index`

Source root: `/home/chukyu`

Before the comparison, here are the few terms used below:

- A **site** is one target call at one file and line. If many processes reach that line, it still counts as one site.
- A **usable result** means the new tool found something about the call. An **exact result** means it proved one value.
- `DYNAMIC`, `EXTERNAL`, and `UNREACHABLE` are useful results, but they are not exact values.
- `mpf_mfs_close` and `mpf_mfs_closeall` are left out because the old index has no matching records.

## 1. Legacy

Legacy is a **regex-based pipeline**. It starts with a fixed set of source paths and scans their text for known MFS and fork function names. This first scan finds possible matches, not always real calls. A match can be inside a comment, disabled code, or a wrapper name. The saved [builder log](../../build_index.log) gives the first-pass counts: **7,131 MFS file-access hits**, **70 direct queue hits**, and **208 fork calls**. These are raw category counts, not one deduplicated site count.

Next, it tries to find the value for each possible call. Numbers and macro names are looked up directly. A handle such as `&sCaseManFcb` is matched to an earlier `open` in the same file. Queue wrappers such as `Dac_EnqSem2` and `SimEnqueSem` work because they are listed in a fixed mapping. If this step finds a value, the call is written to the index. If not, the call disappears. In the file-access pass, **1,715** values could not be resolved and **5,416** became saved file-access records. Wrapper processing added 120 indirect queue hits; the final queue index contains 126 records.

The old index contains **2,494 site locations** and **5,686 value records**. Those records are made up of 5,416 file records, 126 queue records, and 144 fork-target records. There are more records than sites because one call can get several values when the same handle is opened for different files. The old tool does not save calls that it found but could not resolve. So every call in the old index looks solved, even though many failed calls are simply missing.

### Why the first number is so large, and why it gets smaller

The first-pass number is large because the builder scans the whole source tree and checks many MFS operations: open, read, write, get, clear, copy, and queue calls. It also checks every fork call. It is counting possible value records, not just one row per source line. If one handle or variable may refer to several file numbers, the builder keeps several possible records for that one call.

Then the builder applies a value check. A file record is kept only when its number is already numeric or its macro can be found in the FNO definitions. The 1,715 file values that did not meet that rule were printed as unresolved and left out of `mfs_file_access.json`. The same rule was used for queues: the 70 direct queue calls plus 120 calls through wrapper functions made 190 candidates, but 64 queue values could not be mapped to a number, leaving 126 saved queue records.

Fork calls have a similar filter. Of the 208 raw calls, 109 used a literal target, 48 looked like macros, and 51 used a variable or another expression. The macro search resolved 35 of the 48 macro candidates. That leaves 109 + 35 = **144 saved fork records**; the 51 variable calls and 13 unresolved macros are not in the old fork index.

The old JSON files are grouped by value and keep records, not a clean list of calls. We therefore deduplicate by `(file, line)` when comparing sites. This is needed because four values on one source line are still one call, and a shared library line can be reached from several processes. After that grouping, the 5,686 saved records become 2,494 site locations. The deduplication changes how we count locations; it does not claim that the old tool found only 2,494 records.

There are 50 sites in the old index that are not in the new list. Looking at the source shows that 27 are inside `#if 0`, 21 are inside `#ifdef NOP`, and two are comments. They are not live calls. That leaves **2,444 active old sites**.

## 2. C-visualizer (new)

C-visualizer uses the C program itself, not just matching text. It starts with the process list and target registry, which select the files for each process. It then parses the C files into an AST—a tree that shows the real code—so comments and disabled text are not treated as calls. For each real call, it follows callers and assignments backward to see where the target value came from.

Registry 1.2 also includes the six queue wrappers and the fork variants `pmf_forkprocbs_H` and `pmf_forkprocdup_H`. Each process run saves a `target_sites.csv`, so “we found a call” and “we solved its value” are kept separate.

The new run found **3,755 target sites**. Every site has a result row. **2,980** have an exact result. **392** have no exact result yet. The rest have another kind of useful result, such as dynamic or external input. The run covered 385 processes; 383 finished and `dyn811d` plus `dyn830` failed. Neither failed process has an old-index site, so this does not change the comparison.

The final JSON index is smaller than the result CSV. It keeps only exact values proved inside the process. Other evidence, including cross-process evidence, stays in `discovery_facts.csv`. That is why the JSON index has 2,388 sites while the result data has 2,980 exact sites: they serve different purposes.

### What `RUNTIME` means

In each new per-process CSV, `target_number->status = RUNTIME` means the call's target depends on data or a choice made at run time. The tool found the call, but it cannot say that one fixed file or queue number is always used. This is not the same as “the tool failed.” It is an honest result about the program.

The current run has **25,584 `RUNTIME` rows** across the 383 process CSVs. Those rows reduce to **265 source locations**. The rows are much more numerous because the same source line can appear in several process runs, and one runtime-selected call can produce many possible values. For example, rows with values `3921` through `3936` are possible table choices; they do not mean the call always uses all of those numbers. Other rows show a variable such as `file_no` or `iOpenFileNo`, where the value comes from input or another function at run time.

In the aggregate `discovery_facts.csv`, the corresponding count is **25,546 rows**, all marked `status = DYNAMIC` and `resolution_status = RUNTIME`. Most come from a constant table or set: 24,016 rows are `CONST_TABLE`, 691 are `MACRO`, 498 are `CONST`, 312 are `BOUNDED_SET`, and 29 come from direct runtime data. The report's site-level `dynamic` count is **261**, because four of the 265 runtime locations also have an exact result and are counted with the exact sites.

The legacy index has no `RUNTIME` label. It tries to turn each value into a fixed number or macro. For the 265 runtime locations, the old index has a record for only **69** and has no record for **196**. The 69 were included because the old resolver happened to find a static-looking macro or handle match at those lines; it did not know that the value could change at run time. Those 69 locations contribute 376 old records, but only 33 distinct values.

The missing 196 are exactly where the new pipeline adds useful coverage. Most are ordinary MFS calls whose value comes from a table, a constant choice, an enum-like definition, or runtime input: 138 sites are table-based, 19 macro-based, 19 constant-based, 17 runtime-data sites, and three bounded sets. There are also seven fork sites, six queue/wrapper sites, and other MFS operations that the old static index could not turn into a record. The new tool keeps these as runtime evidence instead of dropping them. This is an increase in **explained coverage**, not 196 new exact answers.

The unique-value count also grows. Across all 265 runtime locations, the new facts contain **107 distinct value strings**, including **97 numeric possible values**, and **307 operation/value pairs**. The old records at those same locations contain only **33 distinct values** and **55 operation/value pairs**. Even when comparing only the 69 locations that both sides indexed, the new side has 62 distinct values and 121 operation/value pairs, while the old side has 33 and 55. The new numbers are higher because it keeps all the possible table/set choices and labels them as runtime-dependent; the old side either kept a smaller static set or dropped the location.

### How many values does one site get?

We can also measure the average number of values attached to a call site. For each site, we count its different raw values, add those counts for all sites, and divide by the number of sites. This is a measure of how much value information is attached to a site. It is not a correctness score.

The all-operation ratio is useful as a warning, but it is not the main comparison. It mixes direct arguments with legacy's handle-derived records.

For both sides, we exclude the handle-dependent record functions: read-record, write-record, get-record, and update-record calls. Legacy's remaining direct calls contain **1,271 values across 1,232 sites**, or **1.03 values per site**. The new pipeline's remaining non-handle family has **1,907 sites**. Its `RESOLVED` and `RUNTIME` facts contain **2,781 values**, or **1.46 values per site**. This is a **41.4% increase** over the legacy baseline.

The handle family is excluded because legacy does not resolve those calls from the actual path to the call. A record call receives only an FCB handle, so legacy searches at file scope for opens of the same handle. If that handle is opened for three different files, legacy can attach all three file numbers to every later record call. That multiplies the apparent value count even when a given path uses only one file. It measures the weakness of the old approximation, not three independently proven values.

We remove that family from both sides so the headline compares the same direct-value kind of call. This does not hide the problem: legacy's excluded handle family is shown separately as **4,401 values across 1,262 sites**, or **3.49 per site**. The new handle facts remain available in the audit, but they do not distort the main density comparison.

The new denominator includes all **1,907** non-handle sites, including the **711** sites that legacy never indexed. Those new-only sites are not automatically `UNRESOLVED`; **574** have `RESOLVED` or `RUNTIME` evidence. Sites without those facts remain in the denominator and are reported separately.

The final new JSON export is a narrower view. It promotes only exact values, so it has **2,410 values across 2,388 sites**, or **1.01 values per site**. That export ratio is only a diagnostic because it leaves out the fact-backed runtime table and array possibilities.

The **1.46** number is the useful comparison here because it uses the same non-handle family on both sides, includes all new non-handle sites, and keeps the new fact-backed runtime table and array possibilities.

The old pipeline can look richer because it approximates handle values. Some guesses may be right, but some may belong to another path; the old index does not mark the difference. The new pipeline can also have analysis errors, but it keeps uncertainty visible as `UNRESOLVED`, `DYNAMIC`, `EXTERNAL`, or `UNREACHABLE` instead of presenting those guesses as exact.

For example, at `t-dxi/src/dxi110d/dxi110d_main.c:668`, the new result is runtime-dependent around `2502`, while the old index lists `2502`, `2517`, and `2523` as if they were all ordinary results. At `t-svm/tool/SetFile/SetFile.c:53`, the new result comes from `atoi(*++argv)` and the old index has no record.

## 3. Put the two journeys side by side

### 3.1 Discovery

The fairest comparison starts with the **2,444 active sites** in the old index. The new list contains all of them and adds **1,311 more sites**. The 50 sites that appear only in the old index are disabled or commented code, not live calls missed by the new tool.

This is better than adding up raw scan counters. The 7,131, 70, and 208 counts include calls that later failed resolution, and they are not deduplicated sites. This comparison uses the saved old index and the saved new call list.

The wrapper result is different from the earlier report too. The old index has 78 wrapper locations, but 20 are disabled. The new registry covers all 58 live wrapper locations and finds 27 more. The earlier claim that wrappers were missing from the new setup is no longer true for `csv_results6`.

The earlier report also called `svm000SendInt.c` and `tmmsend.c` missed live code. Looking at the source shows that the calls in `svm000SendInt.c` are under `#ifdef NOP`, and the fork calls in `tmmsend.c` are under `#if 0`. Their empty new lists are correct because the code is disabled.

### 3.2 Resolution

The old index has a value for all 2,444 active sites because calls without values were never saved. The new tool has a usable result for **3,363 of 3,755 sites**, including **2,980 exact results**. Among the sites shared by both tools, **2,329** have a usable new result and **2,262** have an exact result.

The 115 shared sites without an exact result are not all the same problem. In 79, the tool cannot tell which `open` belongs to the handle. In 22, the value is passed in a form the tool does not support yet. In 14, the fork target is visible—such as `OPC1-1` or `ECS-A`—but the name checker rejects it. The new report keeps these calls and explains the reason.

Across all 3,755 new sites, the 392 without an exact result break down into 266 handle ambiguities, 104 unsupported forms, 14 rejected fork names, five numeric macros still marked unresolved, and three numeric enums still marked unresolved.

The important difference is that the new tool does not make up an exact value. It can say:

- the value is **dynamic** (261 sites without an exact alternative);
- it comes from an **external** entry (104 sites without an exact or dynamic alternative); or
- the target is **unreachable** from the process root (18 sites).

The old tool must attach one value or drop the call. Its count therefore looks complete, but it cannot show whether the value was direct, guessed from a reused handle, or copied from another `open`.

### 3.3 Why the new pipeline is better for this codebase

The old tool is fast and works well for simple literals and macros. But it looks mostly at text and file scope. When a handle is reused, it may attach every nearby value to the call. Its output does not show which values are proven and which are guesses.

The new tool follows the code. That gives it five advantages:

1. **It keeps calls visible.** A call stays in the results even when its exact file or queue number is not known.
2. **It follows values through the code.** It can trace callers, callbacks, and calls between processes.
3. **It keeps uncertainty honest.** Dynamic values, outside inputs, and unclear handles are marked instead of being forced into one number.
4. **It ignores dead text.** Comments and disabled blocks do not become live calls.
5. **It can choose the right value.** It understands enums and can choose the `open` that actually leads to the call.

The value comparison shows the effect. At 514 shared sites, the new tool gives a smaller set of values than the old tool. This usually means the old tool attached extra values from other opens. At 238 sites, the two tools give completely different values. Those need source review; the old value is not automatically correct.

Two checks illustrate the distinction:

- `t-tmm/src/libtmmp/TmmSysInit.c:632`: the old tool attaches `2707`, `2710`, `2713`, and `2714` to the read. The new tool keeps only `2713`, which comes from the `TMM_SSVOLTSTAT_FNO` open used by that path.
- `t-dyn/src/dyn441/dyn441AtComProc.c:162`: the old tool reports dummy value `1343`. The new tool follows enum `DynReAtEmeKanFNO` to `DynReEneFileDef.h:212` and gets `3976`.

The run also made 671 LLM transfer queries. An LLM suggestion becomes `EXACT` only when the code analysis confirms it. The model cannot turn an unclear value into a final index record.

## 4. A few concrete examples

Here are a few simple cases where both tools agree. At `t-cha/src/cha100d/cha100dFork.c:90`, both see a live `pmf_forkproc_H` call that starts `cha101d`. At `t-dif/src/dif120d/dif120dOffJh.c:151`, both follow `DifDefineNo` to file 2021. At `t-cha/src/cha001/cha001ClrCaseMan.c:106`, both connect `sCaseManFcb` to file 2836. At `t-dxi/src/dxi110d/dxi110d_parent.c:2316`, both resolve `DXI_QNO_DATABUFF` to queue 707. These are the easy cases where the old text search works and the new code-based analysis confirms it.

The old tool also reports locations that are not live. For example, `t-rep/src/msg001/msg001Main.c:82` is inside `#if 0`, `t-rep/src/msg700/msg700KensakuData.c:95` is inside a block comment, and `t-dif/src/dif900/dif900IntDll.c:1253` is inside `#ifdef NOP`. This is what the 50 old-only locations look like.

The new tool also finds real calls that the old index never recorded. In `t-rep/tool/msgtool/msgtool.c:1020`, it follows `MsgBackUpQNo` to queue 1055. In `t-svm/src/libDac/Dac_DelQue.c:85`, it keeps the queue call as outside-input evidence because the value comes from another interface. In `t-cha/src/libChaCom/ChaCase.c:504`, it follows the file number through a process boundary even though the old index has no record for that library call.

## 5. Numeric checkpoint

The story above explains the results. The small table below checks the main numbers. It is produced by `analysis/scripts/1-compare-sites.py`. The detailed site-by-site audit is saved in `analysis/1-sites-data.json` for the next analysis agent.

<!-- BEGIN GENERATED: 1-site-comparison -->
_Generated by `analysis/scripts/1-compare-sites.py`; this table is the machine-checked numeric checkpoint for the narrative above._
_The main value comparison excludes handle-dependent record functions from both sides. It includes all new non-handle sites and their RESOLVED/RUNTIME facts. The export and handle rows are diagnostics._

| Checkpoint | Legacy | New | Shared |
|---|---:|---:|---:|
| Site locations | 2,494 | 3,755 | 2,444 |
| Active old sites / all new sites | 2,444 | 3,755 | 2,444 |
| Sites with a usable result | 2,444 | 3,363 | 2,329 |
| Exact result (new) | — | 2,980 | 2,262 |
| Only on one side | 50 | 1,311 | — |
| Main comparison: legacy non-handle values/site | 1,271 / 1,232 = 1.03 | — | — |
| Main comparison: new non-handle RESOLVED + RUNTIME values/site | — | 2,781 / 1,907 = 1.46 | — |
| New density increase over legacy | — | +41.4% | — |
| New final export (diagnostic) | — | 2,410 / 2,388 = 1.01 | — |
| Legacy handle multiplication (diagnostic) | 4,401 / 1,262 = 3.49 | — | — |

<!-- END GENERATED: 1-site-comparison -->

## Takeaway

The old pipeline searches fixed text and saves values when its simple rules succeed. The new pipeline reads the actual C code, follows values to their source, and keeps calls when an exact answer is not possible. In this run it covers every active old site, removes the old dead-text locations, finds 1,311 additional sites, and explains the remaining uncertainty. That makes it more useful for understanding and improving the codebase.

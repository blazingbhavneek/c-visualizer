# Value provenance: why the values differ

This is the second analysis for the C-visualizer results. The first report
counted sites and explained coverage. This report follows the values behind
those sites.

This version uses the provisional `results_backup/csv_results7` run, which
contains the four Dxi processes. The comparison baseline is still
`../index_baseline`. When the main run finishes, rerun the script with the new
results directory and review the examples again.

The old index is mainly a regex and file-scope resolver. For a record call, it
often sees only an FCB handle. It collects file numbers opened for that handle
elsewhere in the file and attaches them to the record call. That can create a
larger set than the path really uses.

C-visualizer follows the C code. It traces the local handle, assignments,
callers, callbacks, and tables. When one path proves one value, it reports
`EXACT`. When a runtime selector can choose from a source-backed table or set,
it reports `DYNAMIC` with `resolution_status=RUNTIME`. An external input stays
`EXTERNAL` instead of being turned into a guess.

## 1. When the source proves one value

The simplest difference is a reused FCB. Legacy can join values from several
opens because it works at file scope. C-visualizer keeps the value attached to
the path that reaches the call.

At `DxiGetAdr.c:133`, legacy reports `{2510, 2515}`. The function `DxiGetMS()`
opens `DXI_FNO_ITCMSDEF`, which is `2510`; C-visualizer reports only `2510`
as `EXACT`.

At `DxiGetAdr.c:185`, legacy again reports `{2510, 2515}`. This function uses
`DxiGetSS()`, which opens `DXI_FNO_ITCSSDEF`, or `2515`. C-visualizer keeps
only `2515`.

The same pattern appears in `DxiSndHdr.c`. At line 265, the source can use
`2502`, `2517`, or `2523`, so the new result keeps those three runtime
possibilities. The legacy index adds `2554`, which belongs to another FCB flow.
At line 687, the source opens `DXI_FNO_GITCMNG` immediately before the read;
the new result is the single value `2554`, while legacy still carries the
unrelated values.

At `dxiG_cirmng.c:805`, legacy reports `{2552, 2554}`. The local source path
opens `DXI_FNO_GITCMNG`, which is `2554`, and C-visualizer narrows the result
to that value.

These are not cases where the new tool simply returns fewer values. The source
itself gives fewer values for that path. The smaller set is the result of
following the right handle and the right open.

Source locations for these checks are listed in the generated example table
below and can be opened under `/home/chukyu`.

## 2. When the source proves a set of runtime values

Some calls do not have one fixed answer. The program selects an array entry or
table entry using runtime data. In these cases, C-visualizer should keep the
whole source-backed set and label it as runtime-dependent.

At `DxiSndHdr.c:291`, the network address selects `mysnd`, and the code indexes
`DxiSndQueNum[(mysnd * 2) + 0]`. The table gives six possible queue numbers:
`{702, 703, 724, 725, 728, 729}`. The new CSV records them as
`DYNAMIC/RUNTIME`. Legacy has no exact site entry for this call.

The dxi300d update-table functions work in the same way:

- `dxi_uptbn.c:74` -> `{2503, 2513}`
- `dxi_uptbn.c:111` -> `{2520, 2522}`
- `dxi_uptbn.c:148` -> `{2526, 2528}`

Each function indexes a two-entry local table using `t_flg`. The values are
not guesses; they are the entries present in the table. The selector is still
runtime-dependent, so the result is not labelled `EXACT`.

At `dxi800d_reg.c:115`, `up_down` selects one of two entries and produces
`{2506, 2507}`. At `dxi_dblcirreq.c:100`, the process name is selected from
`myshu`, giving `{dxi500d, dxi501d, dxi502d}`. These are different kinds of
runtime sets, but both preserve the source evidence instead of flattening it
into one value.

## 3. When the provenance stops at an external input

Not every value can be followed to a concrete table entry. At
`DxiItcReq2.c:711`, the file number arrives as the parameter `filenum` from
outside the proven caller scope. C-visualizer records
`EXTERNAL/EXTERNAL_ENTRY`. That is useful provenance: it tells us where the
static proof ends. It is not an exact file number, and it should not be filled
with a nearby legacy value.

The same boundary appears in the UPTBN examples when a caller does not provide
enough information to determine `t_flg`. The table values can still be shown,
but the selector's origin remains external for that process.

This is the main difference in how uncertainty is represented. Legacy often
has no separate unresolved record: a call either gets a value or disappears.
C-visualizer keeps the call and says whether the uncertainty is runtime data,
an external entry, an unreachable path, or an unresolved syntax/handle case.

## 4. Runtime sets that still need work

Keeping all possible values is safer than choosing one, but a set can still be
too wide. The current run exposes three cases that should not be called wins
until loop and index constraints are propagated:

- `DxiSndHdr.c:567` currently emits `{732, 733, 734, 735, 736}`, while the
  source loop uses `i=0..1`, so the expected set is `{732, 733}`.
- `DxiSndHdr.c:622` currently emits the same five values, while the source
  uses `i+2`, so the expected set is `{734, 735}`.
- `DxiItcReq2.c:575` currently emits six queue values, while the source limits
  `mysnd` to `0..1` and the `+0` table index gives `{702, 724}`.

These are not reasons to return to legacy's single guessed value. They show
the next improvement: carry loop bounds and selector constraints into the
runtime table resolver. Until then, keep the larger set marked `RUNTIME` and
call it an over-approximation, not an exact answer.

## 5. What the provenance fields preserve

The facts retain the path needed to inspect a result later. For example:

- `DxiSndHdr.c:291` records the callback path, the table in `DxiGlobal.c`,
  macro sources in `dxi_const.h`, and the `TABLE_SET` termination reason.
- `dxi_uptbn.c:74` records the callback into `Dxi_UpTbnFileOpen()`, the table
  lookup, and the two macro entries from `dxi_const.h`.
- `dxi800d_reg.c:115` records the callback, the `updn` selector, and the two
  macro-backed table entries.

This makes a future correction local. We can tighten the selector or loop
constraint and see which values change, instead of rediscovering why a number
was placed in the index.

## 6. Numeric checkpoint

The small tables below are generated from `csv_results7`. The selected examples
and the warning cases are checked by
`analysis/scripts/2-value-provenance.py`; the surrounding explanation is
written by the analysis agent.

<!-- BEGIN GENERATED: 2-value-provenance -->
_Generated by `analysis/scripts/2-value-provenance.py`; the prose and source explanations above are written by the analysis agent._

| Checkpoint | Result |
|---|---:|
| Fact rows after close exclusion | 957 |
| Unique target sites | 144 |
| `EXACT` rows / sites | 248 / 75 |
| `DYNAMIC` rows / sites | 647 / 52 |
| `RESOLVED` rows / sites | 248 / 75 |
| `RUNTIME` rows / sites | 647 / 52 |
| Exact + dynamic values summed per site | 265 / 144 = 1.84 |

### Example checkpoint

| Site | Legacy values | New exact values | New runtime values | Status |
|---|---|---|---|---|
| `DxiGetAdr.c:133` | 2510, 2515 | 2510 | — | EXACT |
| `DxiGetAdr.c:185` | 2510, 2515 | 2515 | — | EXACT |
| `DxiSndHdr.c:265` | 2502, 2517, 2523, 2554 | — | 2502, 2517, 2523 | DYNAMIC |
| `DxiSndHdr.c:687` | 2502, 2517, 2523, 2554 | 2554 | — | EXACT |
| `dxiG_cirmng.c:805` | 2552, 2554 | 2554 | — | EXACT |
| `DxiSndHdr.c:291` | — | — | 702, 703, 724, 725, 728, 729 | DYNAMIC |
| `dxi_uptbn.c:74` | — | — | 2503, 2513 | DYNAMIC, EXTERNAL |
| `dxi_uptbn.c:111` | — | — | 2520, 2522 | DYNAMIC, EXTERNAL |
| `dxi_uptbn.c:148` | — | — | 2526, 2528 | DYNAMIC, EXTERNAL |
| `dxi800d_reg.c:115` | — | — | 2506, 2507 | DYNAMIC |
| `dxi_dblcirreq.c:100` | — | — | dxi500d, dxi501d, dxi502d | DYNAMIC |
| `DxiItcReq2.c:711` | — | — | — | EXTERNAL |

### Runtime warning checkpoint

| Site | Current runtime values | Status |
|---|---|---|
| `DxiSndHdr.c:567` | 732, 733, 734, 735, 736 | DYNAMIC |
| `DxiSndHdr.c:622` | 732, 733, 734, 735, 736 | DYNAMIC |
| `DxiItcReq2.c:575` | 702, 703, 724, 725, 728, 729 | DYNAMIC |

<!-- END GENERATED: 2-value-provenance -->

## Takeaway

Legacy is often broader because it joins values by file-scope handle name.
C-visualizer is more useful for this question because it preserves the reason
for each value: exact local path, runtime table choice, callback provenance, or
an external boundary. Its runtime sets still need tighter bounds in a few
places, but those cases are visible and correctable instead of silently
presented as fixed answers.

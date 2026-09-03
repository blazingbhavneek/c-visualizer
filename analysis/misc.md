# Legacy index comparison: process-specific resolutions

This is provisional evidence for a future comparison document.

The current LLM/value-flow pipeline was compared with the legacy regex-based
index in:

- `forkproc_checker/index_baseline/mfs_file_access.json`
- the latest process CSVs under `results_backup/csv_results7/`

The comparison is accuracy-oriented. The legacy index often attaches every
file number seen at a source location, while the current pipeline follows the
local FCB assignment and call path. Therefore, fewer current candidates can
mean better precision rather than worse recall.

## Source-proven examples

### `DxiGetAdr.c`

At `DxiGetAdr.c:133`, the legacy index reports `{2510, 2515}`. The function
`DxiGetMS()` opens `DXI_FNO_ITCMSDEF`, which is `2510`; the current pipeline
reports only `2510 RESOLVED`.

At `DxiGetAdr.c:185`, the legacy index again reports `{2510, 2515}`. The
function `DxiGetSS()` opens `DXI_FNO_ITCSSDEF`, which is `2515`; the current
pipeline reports only `2515 RESOLVED`.

Source: `/home/chukyu/t-dxi/src/libdxi/DxiGetAdr.c:124`,
`/home/chukyu/t-dxi/src/libdxi/DxiGetAdr.c:176`, and
`/home/chukyu/t-dxi/include/dxi_const.h:243`.

### `DxiSndHdr.c:265`

The legacy index reports `{2502, 2517, 2523, 2554}`. In `DxiSendHdr()`, the
local FCB is opened only with `DXI_FNO_CIRMNG`, `DXI_FNO_CIRMNG2`, or
`DXI_FNO_CIRMNG3`, producing `{2502, 2517, 2523}`. The current pipeline
correctly excludes `2554`.

Source: `/home/chukyu/t-dxi/src/libdxi/DxiSndHdr.c:239`.

### `DxiSndHdr.c:687`

The legacy index reports `{2502, 2517, 2523, 2554}`. `DxiGChkTenso()` opens
`DXI_FNO_GITCMNG` immediately before the read, and that macro is `2554`. The
current pipeline reports only `2554 RESOLVED`.

Source: `/home/chukyu/t-dxi/src/libdxi/DxiSndHdr.c:678` and
`/home/chukyu/t-dxi/include/dxi_const.h:314`.

### `dxiG_cirmng.c:805`

The legacy index reports `{2552, 2554}`. `DxiG_CheckItcSimMode()` opens
`DXI_FNO_GITCMNG`, which is `2554`; the current pipeline reports only
`2554 RESOLVED`.

Source: `/home/chukyu/t-dxi/src/libdxiinside/dxiG_cirmng.c:797`.

These examples show the core improvement: the legacy index aggregates broad
candidates from different FCB flows, while the current pipeline preserves
multiple values only when the source path genuinely permits them and narrows
values when local source context proves a single target.

## Runtime-resolution examples

These examples are different from the single-value narrowing cases above: one
target site has several source-backed runtime possibilities, and the legacy
index has no exact source-location entry for the site.

### `DxiSndHdr.c:291`

The current pipeline emits:

```text
{702, 703, 724, 725, 728, 729}
```

`DxiSendHdr()` computes `mysnd` from the runtime network address, with values
`0..2`, and indexes `DxiSndQueNum[(mysnd * 2) + 0]`. The table in
`DxiGlobal.c` therefore produces six possible queue numbers. The current CSV
records each value as `RUNTIME/TABLE_SET`; the legacy queue index has no exact
entry for `DxiSndHdr.c:291`.

Source: `/home/chukyu/t-dxi/src/libdxi/DxiSndHdr.c:86`,
`/home/chukyu/t-dxi/src/libdxi/DxiSndHdr.c:291`, and
`/home/chukyu/t-dxi/src/libdxi/DxiGlobal.c:55`.

### dxi300d UPTBN tables

For dxi300d, the current pipeline traces the callback into
`Dxi_UpTbnFileOpen()` and emits:

- `dxi_uptbn.c:74` -> `{2503, 2513}`
- `dxi_uptbn.c:111` -> `{2520, 2522}`
- `dxi_uptbn.c:148` -> `{2526, 2528}`

Each function indexes a local two-entry `fileno[]` table using `t_flg`. These
are `RUNTIME/TABLE_SET` results, and the legacy file-access index has no exact
entry for these array-indexed opens.

Source: `/home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:59`,
`/home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:100`, and
`/home/chukyu/t-dxi/src/libdxiinside/dxi_uptbn.c:137`.

### dxi800d trace files

At `dxi800d_reg.c:115`, the current pipeline emits `{2506, 2507}`. The
callback validates `trchd->up_down`, converts it to `updn = 0` or `1`, and
indexes `filenum[updn]`. The CSV records both values as `RUNTIME/TABLE_SET`.

Source: `/home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:86` and
`/home/chukyu/t-dxi/src/dxi800d/dxi800d_reg.c:105`.

### Runtime fork target names

At `dxi_dblcirreq.c:100`, the current pipeline emits
`{dxi500d, dxi501d, dxi502d}` as `RUNTIME/LOCAL_ASSIGNMENT`. The source
selects `prcname` from `myshu`; the legacy fork index has no dxi entries for
this site.

Source: `/home/chukyu/t-dxi/src/libdxiinside/dxi_dblcirreq.c:88`.

## Value-genesis tracking

The CSV retains enough provenance to track how a value was produced later:

- `DxiSndHdr.c:291`: call path through `DxiQWrtEvn.c`, table source
  `DxiGlobal.c`, macro source in `dxi_const.h`, and reason `TABLE_SET`.
- dxi300d `dxi_uptbn.c:74`: callback path from `dxi300d_main.c` into
  `Dxi_UpTbnFileOpen()`, then table entries `DXI_FNO_UPMNG` and
  `DXI_FNO_UPMNGTON` from `dxi_const.h`.
- dxi800d `dxi800d_reg.c:115`: callback from `dxi800d_main.c`, selector
  `updn`, table `filenum[]`, and macro sources `DXI_FNO_UPTRACE` and
  `DXI_FNO_DNTRACE`.
- `DxiGetTen.c:117/126`: `shu` and mode branches converge on the four file
  numbers `{2502, 2514, 2517, 2523}`; each emitted row records its macro
  source and line.

An `EXTERNAL` result also records a useful provenance boundary. For example,
`DxiItcReq2.c:711` reports `filenum` as `EXTERNAL/EXTERNAL_ENTRY`: the value
is a function parameter whose caller is outside the proven source context.
Similarly, UPTBN lines 74/111/148 are marked external for processes whose
callers were not traced far enough to determine `t_flg`. These should be
tracked as unresolved provenance edges rather than converted into guesses.

## Accuracy warning for runtime sets

Not every larger runtime set is automatically a correct improvement. The
current output still over-approximates some queue sites:

- `DxiSndHdr.c:567` currently emits `{732..736}`, but the source loop uses
  `i = 0..1`, so this site should be `{732,733}`.
- `DxiSndHdr.c:622` currently emits `{732..736}`, but the source indexes
  `i + 2`, so this site should be `{734,735}`.
- `DxiItcReq2.c:575` currently emits all six queue values, while its source
  restricts `mysnd` to `0..1` and the `+0` index gives `{702,724}`.

These are runtime-analysis opportunities, but should not be counted as
accuracy wins until the index and loop constraints are propagated.

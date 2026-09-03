# dyn401d value-flow run — expert brief on wrong/missing FNO answers

Self-contained: all source excerpts below are copied verbatim from the
original tree (`/home/chukyu/t-dyn/src`, SVN ids in Appendix A). Japanese
comments in the originals are omitted from excerpts; code text is unchanged.
No file in this repository needs to be opened to verify any claim here.

## 0. Inventory of the run

Tool: `c-visualizer` (this repo), resolver `valueflow`, model
`gemma-4-31B`, prompt `valueflow-transfer-v3-opaque`, run 103.4 s,
79 LLM calls (31 unique call sites), 897k tokens.

936 facts produced. Bucketed by what the answer column actually contains:

| bucket | facts | what the value really is |
|---|---|---|
| `CONST` with a real number | 894 | hardcoded literal or local constant at the call site |
| `MACRO` with a real number | 13 | macro that expands to a constant |
| **`CONST` with a raw C expression as the value** (Class 3) | **75** | e.g. `DynREGetSchKKfno(nFnoidxKK)` — nothing was resolved; the argument text was copied verbatim and mislabelled `CONST` |
| **`UNRESOLVED`** (Classes 1+2) | **29** | resolution genuinely failed (25 + 4) |

Everything below concerns the bottom two buckets (104 facts). Their union is
not 104 independent problems: it is **two root causes** plus **one output
gate** that turns root cause 1 into two different symptoms.

The FNOs in play are members of one enum, `DynReDirectFileNo`
(`include/Dyn/DynReEneFileDef.h`, first member pinned to 1021, the rest
sequential; the `/* nnnn */` comments are the actual values — cross-checked
against this run's own resolved facts, e.g. `DynReOutStaFNO` resolved to 3937
in log `091_mpf_mfs_open_H_DynReEneOutStaFunc.c_46_arg2_3937.log`, matching
its comment):

```c
// include/Dyn/DynReEneFileDef.h (typedef enum { DynReCtlInfFNO_DUMMY = (1021) ... } DynReDirectFileNo;)
    ,DynReSchSetFNO              /* 3921 */
    ,DynReSchSet02FNO            /* 3922 */
    ,DynReSchSet03FNO            /* 3923 */
    ,DynReSchSet04FNO            /* 3924 */
    ,DynReSchSet05FNO            /* 3925 */
    ,DynReSchSet06FNO            /* 3926 */
    ,DynReSchSet07FNO            /* 3927 */
    ,DynReSchSet08FNO            /* 3928 */
    ,DynReSchSet09FNO            /* 3929 */
    ,DynReSchSet10FNO            /* 3930 */
    ,DynReSchSet11FNO            /* 3931 */
    ,DynReSchSet12FNO            /* 3932 */
    ,DynReSchSet13FNO            /* 3933 */
    ,DynReSchSet14FNO            /* 3934 */
    ,DynReSchSet15FNO            /* 3935 */
    ,DynReSchSet16FNO            /* 3936 */
    ,DynReOutStaFNO              /* 3937 */
    ...
    ,DynReSchSetKK01FNO          /* 3995 */
    ,DynReSchSetKK02FNO          /* 3996 */
    ,DynReSchSetKK03FNO          /* 3997 */
    ,DynReSchSetKK04FNO          /* 3998 */
    ,DynReSchSetKK05FNO          /* 3999 */
    ,DynReSchSetKK06FNO          /* 4000 */
    ,DynReSchSetKK07FNO          /* 4001 */
    ,DynReSchSetKK08FNO          /* 4002 */
    ,DynReScStKKLC01FNO          /* 4003 */
    ,DynReScStKKLC02FNO          /* 4004 */
    ,DynReScStKKLC03FNO          /* 4005 */
    ,DynReScStKKLC04FNO          /* 4006 */
    ,DynReScStKKLC05FNO          /* 4007 */
    ,DynReScStKKLC06FNO          /* 4008 */
    ,DynReScStKKLC07FNO          /* 4009 */
    ,DynReScStKKLC08FNO          /* 4010 */
    ,DynReGrpSetCmnFNO           /* 4011 */
    ,DynReCtlStaAlznFNO          /* 4012 */
    ,DynReKoTeiHtSetFNO          /* 4013 */
} DynReDirectFileNo;
```

---

## 1. Root cause A — FNO = table lookup over a runtime index (100 facts: 25 UNRESOLVED + 75 mislabelled-CONST echoes)

### 1.1 The full source trace, target to table

**Step 1 — the target call sites.** `dyn401dRequest()` receives the file
index as a *parameter* and feeds it to a wrapper:

```c
// dyn401d/dyn401dRequest.c
64:  int
65:  dyn401dRequest(
66:      int           nOffset,       /* schedule position  */
67:      int           nFnoidx,       /* schedule file INDEX  */
68:      int           nOffsetKK,
69:      int           nFnoidxKK,
70:      PMF_TIME      *ptTgtTime,
71:      int           nCtrlCode,
72:      int           nGroupNo,
73:      int           nReene_kind
74:  )
...
212:    else
213:    {
214:        nRet = mpf_mfs_open_H(&fcb, DynREGetSchfno(nFnoidx), 0, 0, MPF_MFS_READLOCK);
215:        if ( nRet != 0 )
216:        {
218:            DynPrintf( __FILE__, __LINE__, "mpf_mfs_open_H Err\n" );
219:
220:            return -1;
221:        }
222:        mpf_mfs_readrecn( &fcb, 0, nOffset, 1, (void *)&sDynReSchSet);
223:        mpf_mfs_close( &fcb );
224:    }
...
361:    if(nFnoidxKK >= 0)
362:    {
363:        nRet = mpf_mfs_open_H(&fcb, DynREGetSchKKfno(nFnoidxKK), 0, 0, MPF_MFS_READLOCK);
...
371:        mpf_mfs_readrecn(&fcb, 0, nOffsetKK, 1, (void *)&sDynReSchSetKK);
372:        mpf_mfs_close(&fcb);
373:        nRet = mpf_mfs_open_H(&fcb, DynREGetSchKKLCfno(nFnoidxKK), 0, 0, MPF_MFS_READLOCK);
...
381:        mpf_mfs_readrecn(&fcb, 0, nOffsetKK, 1, (void *)&sDynReSchSetKKLC);
382:        mpf_mfs_close(&fcb);
383:    }
```

The identical pattern at `dyn401d/dyn401dAlznRequest.c:245,253,255,263` and
`dyn401d/dyn401dAdvRequest.c:177,307,315`, plus call sites with a **literal
index 0** at `dyn401d/dyn401dScheStaUpd.c:283,322,334,373`
(`DynREGetSchKKfno(0)` / `DynREGetSchKKLCfno(0)`).

**Step 2 — where the index comes from** (one caller level up):

```c
// dyn401d/dyn401dScheCtrl.c
 99:        DynREGetSchePos2(&tgt_date, DYN_LIB_NML_YEAR, &nDatpos, &nFnoidx);
...
134:    nRtn = dyn401dRequest( nDatpos, nFnoidx, nDatposKK, nFnoidxKK, &tgt_date, nCtrlcode, GroupNo, (int)nPw );
```

**Step 3 — the index computation** (date + one file read):

```c
// libDynRe/DynREGetSchePos.c
122:    /* compute schedule position for (fiscal) year */
123:    nCval    = Fis_In_date.year - sDynScheStaBuf.Upd_Year;
124:    nScheofs = (DYN_REENESCHE_MAX + (nNowYY_Offset + (nCval * 372))) % DYN_REENESCHE_MAX;
127:    nRtn = nScheofs + ( ((pi_pmf_time->mon + 8 ) % 12) * 31) + (pi_pmf_time->day - 1);
129:    return nRtn;   // 1..1488 or <=0 on error

208: void
209: DynREGetSchePos2(
210: const PMF_TIME *pi_pmf_time,
211:       int       nIs_fisyear,
212:       int       *nOffset,         /* (o) position 1..93 (0 on error) */
213:       int       *nFnoidx          /* (o) file INDEX 0..15 (-1 on error) */
214: )
215: {
218:     nScheofs = DynREGetSchePos(pi_pmf_time, nIs_fisyear);
220:     if ((0 < nScheofs) && (nScheofs <= DYN_REENESCHE_MAX))
221:     {
222:         *nOffset = ((nScheofs - 1) % DYN_REENESCHE_MAX2) + 1;
223:         *nFnoidx = ((nScheofs - 1) / DYN_REENESCHE_MAX2);
224:     }
225:     else
226:     {
227:         *nOffset = 0;
228:         *nFnoidx = -1;
229:     }
230:     return;
231: }
```

```c
// include/Dyn/DynReEneComDef.h
636: #define DYN_REENESCHE_MAX (1488)   // total schedule records (31 days * 12 months * 4 years)
638: #define DYN_REENESCHE_MAX2  (93)    // records per schedule file (31 * 3 months)
640: #define DYN_REENESCHE_IDXNUM  (DYN_REENESCHE_MAX/DYN_REENESCHE_MAX2)  // = 16 files
```

So `nFnoidx = (position-1)/93 ∈ {0..15}`: **which of 16 rotation files** the
date falls into. Runtime inputs: the date, and `Upd_Year`/`Offset` read from
file `DynReSchStaFNO` (3920) inside `DynREGetSchePos`.

**Step 4 — the wrapper** (the expression that appears in the CSV):

```c
// libDynRe/DynREGetSchePos.c
243: DynREGetSchfno(
244:       int       nFnoidx
245: )
246: {
247:     return ScheFnoTbl[nFnoidx].Schfno;
248: }

// libDynRe/DynREGetScheKKPos.c
182: DynREGetSchKKfno(
183:       int       nFnoidx
184: )
185: {
186:     return ScheKKFnoTbl[nFnoidx].SchKKfno;
187: }
199: DynREGetSchKKLCfno(
200:       int       nFnoidx
201: )
202: {
204:     return ScheKKFnoTbl[nFnoidx].SchKKLCfno;
205: }
```

**Step 5 — the tables** (static const, entire contents shown):

```c
// libDynRe/DynREGetSchePos.c
32: typedef struct  DynReScheFnoSt {
33:     int Schfno;
34:     int Pfmfno;
35: } DynReScheFno;
36: static DynReScheFno ScheFnoTbl[] = {
37:     { DynReSchSetFNO,   DynReHESPfmKbtFNO },      // 3921
38:     { DynReSchSet02FNO, DynReHESPfmKbt02FNO },    // 3922
39:     { DynReSchSet03FNO, DynReHESPfmKbt03FNO },    // 3923
40:     { DynReSchSet04FNO, DynReHESPfmKbt04FNO },    // 3924
41:     { DynReSchSet05FNO, DynReHESPfmKbt05FNO },    // 3925
42:     { DynReSchSet06FNO, DynReHESPfmKbt06FNO },    // 3926
43:     { DynReSchSet07FNO, DynReHESPfmKbt07FNO },    // 3927
44:     { DynReSchSet08FNO, DynReHESPfmKbt08FNO },    // 3928
45:     { DynReSchSet09FNO, DynReHESPfmKbt09FNO },    // 3929
46:     { DynReSchSet10FNO, DynReHESPfmKbt10FNO },    // 3930
47:     { DynReSchSet11FNO, DynReHESPfmKbt11FNO },    // 3931
48:     { DynReSchSet12FNO, DynReHESPfmKbt12FNO },    // 3932
49:     { DynReSchSet13FNO, DynReHESPfmKbt13FNO },    // 3933
50:     { DynReSchSet14FNO, DynReHESPfmKbt14FNO },    // 3934
51:     { DynReSchSet15FNO, DynReHESPfmKbt15FNO },    // 3935
52:     { DynReSchSet16FNO, DynReHESPfmKbt16FNO },    // 3936
53: };

// libDynRe/DynREGetScheKKPos.c
32: typedef struct  DynReScheKKFnoSt {
33:     int SchKKfno;
34:     int SchKKLCfno;
35: } DynReScheKKFno;
36: static DynReScheKKFno ScheKKFnoTbl[] = {
37:     { DynReSchSetKK01FNO, DynReScStKKLC01FNO },   // 3995, 4003
38:     { DynReSchSetKK02FNO, DynReScStKKLC02FNO },   // 3996, 4004
39:     { DynReSchSetKK03FNO, DynReScStKKLC03FNO },   // 3997, 4005
40:     { DynReSchSetKK04FNO, DynReScStKKLC04FNO },   // 3998, 4006
41:     { DynReSchSetKK05FNO, DynReScStKKLC05FNO },   // 3999, 4007
42:     { DynReSchSetKK06FNO, DynReScStKKLC06FNO },   // 4000, 4008
43:     { DynReSchSetKK07FNO, DynReScStKKLC07FNO },   // 4001, 4009
44:     { DynReSchSetKK08FNO, DynReScStKKLC08FNO },   // 4002, 4010
45: };
```

### 1.2 The statically-known answer

- `DynREGetSchfno(nFnoidx)` ∈ **{3921..3936}** (16 enum constants; index is
  `(date-position-1)/93`, so exactly one of them at any instant, determined
  by the date + one status-file read).
- `DynREGetSchKKfno(nFnoidxKK)` ∈ **{3995..4002}** (8 constants).
- `DynREGetSchKKLCfno(nFnoidxKK)` ∈ **{4003..4010}** (8 constants).
- The literal-index sites are single values, fully decidable *today*:
  `DynREGetSchKKfno(0)` = 3995, `DynREGetSchKKLCfno(0)` = 4003.

The resolver's answer format supports sets (see 1.3), so none of this is
fundamentally beyond the tool.

### 1.3 The mechanical path that would have answered this — and is disabled

`value_flow/value_rules.py` (complete file, 40 lines) registers exactly
these wrappers:

```python
DEFAULT_VALUE_RULES: dict[str, dict[str, Any]] = {
    "DynREGetSchfno": {"kind": "return_table"},
    "DynREGetSchKKfno": {"kind": "return_table"},
    "DynREGetSchKKLCfno": {"kind": "return_table"},
    "DynREGetPfmfno": {"kind": "return_table"},
    "Dxi_UpTbnFileOpen": {"kind": "writes_table"},
    "Dxi_DnTbnFileOpen": {"kind": "writes_table"},
    "Dxi_UpTbnFileOpen2": {"kind": "writes_table"},
    "Dxi_DnTbnFileOpen2": {"kind": "writes_table"},
    # ChaGetFileInfo writes TM/SV output arguments and returns -1 on failure.
    "ChaGetFileInfo": {
        "kind": "writes_table",
        "output_args": [3, 4],
        "error_values": ["-1"],
    },
}
```

`value_flow/resolver.py` implements the consumer: `_table_values_for_function`
(~line 1414) finds the `subscript_expression` inside the `return` of the
named function, reads the table's initialiser from the parsed AST, and emits
one `Fact` per table element with `origin_kind="CONST_TABLE"`,
`link_method="TABLE_LOOKUP"`, shared `set_id`, and metadata
`{table_file, table_line, table_symbol, index_expression, bound, wrapper}` —
i.e. a native "set of constants, indexed by runtime expression" answer.

But the constructor kills it whenever any LLM transfer resolver is present
(`value_flow/resolver.py:352-359`):

```python
        # Named table/wrapper semantics belong only to the explicit legacy
        # compatibility engine. Production valueflow always supplies the
        # transfer callback (including the disabled/offline callback), so it
        # must not load those rules as a semantic input.
        self.transfer_resolver = transfer_resolver or transfer_callback
        self.value_rules = (
            merge_value_rules(value_rules) if self.transfer_resolver is None else {}
        )
```

Production always supplies a transfer resolver (this run: gemma-4-31B), so
`value_rules == {}` and the table path is unreachable. Note the asymmetry:
the rules file names these exact functions from this exact source family,
yet the gate makes them dead code in every production run. Either the gate
or the rules file is stale.

### 1.4 What happens instead — the LLM fallback, and its two outcomes

With the table path dead, the argument expression `DynREGetSchfno(nFnoidx)`
goes through the LLM transfer engine. Two outcomes, both wrong:

**(a) 25 facts → UNRESOLVED.** The model answered, the answer failed the
formula validator, every arm was dropped, and the fact was emitted
UNRESOLVED with the raw expression as `source_expr`. Proof of the 1:1
mapping — `run_stats.json`:

```json
"transfer_rejections": { "guard_formula": 4, "binding_formula": 25, "all_arms_rejected": 25 }
```

`binding_formula` 25 = `all_arms_rejected` 25 = the 25 UNRESOLVED facts
with a `DynREGetSch*` expression (18 in dyn401dRequest/AlznRequest, 1
AlznRequest:245 readrecn, 6 more via the 255/263/371/381 readrecn siblings —
exact per-site table in Appendix B). The LLM queries for these sites are in
`run_stats.json` under `queries[]` (call_site ids `dyn401dRequest.c:8178,
13074, 13422`, `dyn401dAlznRequest.c:9532`, etc.). **Audit gap:** rejected
arms are not persisted anywhere (`transfer_diagnostics: []`, rejected answers
are not cached), so the exact model output that failed validation is
unrecoverable after the run.

The validator that rejected them (`_validate_transfer_answer`,
`value_flow/resolver.py:~2900-2935`) only accepts bindings whose expression
is valid in a small formula grammar (`validate_formula`,
`value_flow/transfers.py:300`) over names visible in the current function.
A table/subscript expression like `ScheFnoTbl[#1].Schfno`, or per-entry arms
with guards the grammar rejects, cannot pass. (The 4 `guard_formula`
rejections belong to root cause B, below — invalid guards are *demoted to
`true`*, they do not by themselves kill a fact.)

**(b) 75 facts → raw expression emitted as the value, labelled `CONST`.**
See section 2 — this is the output gate.

---

## 2. Root cause B — the output gate: raw expressions laundered into `CONST` answers (75 facts)

These are the rows where the legacy CSV's answer column literally contains
`DynREGetSchfno(nFnoidx)` etc. They are **not literals, not macros, not
resolved values**. The call-site argument text is copied verbatim into the
answer and stamped `CONST`.

Full site list (75 facts, 22 call sites, 7 files) in Appendix B.

### 2.1 The five-step chain (with the exact code of each step)

**Step 1 — seeding stamps every argument `CONST`.**
`value_flow/resolver.py:2580-2624`:

```python
    def initial_route_arm(self, *, route, site, indices):
        """Build one correlated bundle from exact source arguments."""
        bindings: list[Binding] = []
        sources: dict[int, dict[str, Any]] = {}
        for raw_index in indices:
            index = int(raw_index)
            expression = (...)
            ...
            bindings.append(Binding(index, "EXPRESSION", expression.text.strip()))
            sources[index] = self._expression_source(expression)
        ...

    def _expression_source(self, expression: Expression) -> dict[str, Any]:
        return {
            "file": expression.file_path,
            "line": expression.line,
            "expr": expression.text.strip(),
            "source_site_id": f"{expression.file_name}:{expression.line}:{expression.text.strip()}",
            "origin_kind": "CONST",          # <-- stamped unconditionally, no proof
        }
```

**Step 2 — the prompt invites non-tracing.** `project_aware.py:718`
(the transfer prompt sent to gemma-4-31B):

```
A fast EXTERNAL or UNKNOWN is a GOOD answer. Never invent a number.
```

**Step 3 — the validator accepts the echo.** `_validate_transfer_answer`
(`value_flow/resolver.py:~2916-2933`) checks EXTERNAL bindings for only two
things — the text must not be a literal, and `#N` placeholders must be in
range. It never checks whether the expression is a call into a
project-defined function that could (and should) have been traced. An
identity echo passes.

**Step 4 — emission copies the text into `value`.**
`value_flow/resolver.py:3250-3273` (`_fact_from_arm`):

```python
        if binding.kind == "EXACT":
            value = binding.text
            origin = str(source.get("origin_kind") or "CONST")
        elif binding.kind == "EXTERNAL":
            value = binding.text or "EXTERNAL"                    # <-- raw text becomes the answer
            origin = str(source.get("origin_kind") or ("EXTERNAL_ENTRY" if "$" in value else "EXTERNAL_DATA"))
        else:
            sentinel = binding.text in {
                "RECURSIVE", "UNRESOLVED", "missing argument", "HANDLE_AMBIGUOUS",
            }
            if self.external_unknown and not sentinel and binding.text.strip():
                # An expression we could not trace further is still an
                # answer: the legacy engine reports it as EXTERNAL_DATA
                # rather than discarding it (P17).
                value = binding.text                              # <-- P17 legacy-compat: any expr is "an answer"
                origin = "UNKNOWN_INDIRECT" if "(*" in binding.text else "EXTERNAL_DATA"
            else:
                value = "UNRESOLVED"
                origin = "RECURSIVE" if binding.text == "RECURSIVE" else "UNRESOLVED"
        ...
        source_expr = str(source.get("expr") or binding.text)     # provenance text kept here
        return Fact(value=value, origin_kind=origin, ..., source_expr=source_expr, ...)
```

`origin` then comes out as `CONST` because Step 1 stamped the source entry
`CONST`. Provenance is not lost: `source_expr` and `metadata["unresolved_expr"]`
still carry the raw text.

**Step 5 — the CSV copies `fact.value` verbatim.** `value_flow/outputs.py:172-185`:
`target_number->ans` = `fact.value` (joined with `_` only when a target has
multiple configured arguments).

### 2.2 Proof that the echo needs no model at all

Log `logs/598_mpf_mfs_open_H_dyn401dAlznRequest.c_245_arg2_DynREGetSchKKfno_nFnoidxKK.log`
(complete):

```
TARGET   mpf_mfs_open_H  dyn401dAlznRequest.c:245  arg 2
RESULT   DynREGetSchKKfno(nFnoidxKK)  (CONST)  type=OPENMF  link=LLM_TRANSFER
SOURCE   dyn401dAlznRequest.c:245  DynREGetSchKKfno(nFnoidxKK)
TOTAL    0.000s over 1 step(s), 0 model call(s)
PATHS    1 source-to-target path(s)

chain (target -> source):

transfer chain (local formulas):
  [dyn401dAlznRequest.c]dyn401dAlznRequest:dyn401dAlznRequest.c:9184 2=DynREGetSchKKfno(nFnoidxKK)
  [1]    0.000s  SYNTAX  [dyn401dMain.c]main[39:55] -> [dyn401dMain.c:47]dyn401dTimeOut[210:786] -> [dyn401dAlznScheCtrl.c:454]dyn401dZenScheCtrl[144:219] -> [dyn401dAlznRequest.c:205]dyn401dAlznRequest[41:511] -> [253]mpf_mfs_readrecn
```

"0 model call(s)" — when the route terminates at the seed site, the initial
arm's EXPRESSION binding is converted to EXTERNAL/UNKNOWN and P17 emits it.
The `resolved_by=LLM` flag on these facts is a configuration label (an LLM
resolver is attached to the run), not a record of a model actually deciding
the value.

### 2.3 Representative raw fact rows (verbatim from `facts.csv`)

Echo (Class 3):

```
fact:caf33bf5e13155cbc1a3,dyn401d,mpf_mfs_open_H,/home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c,401,DynReGrpSetCsvLoad.c:15788,2,DynREGetSchKKfno(nFnoidxKK),CONST,/home/chukyu/t-dyn/src/libDynRe/DynReGrpSetCsvLoad.c,401,DynREGetSchKKfno(nFnoidxKK),OPENMF,NO DATA,DynReGrpSetCsvLoad,NA,LOCAL_BACKWALK,"{""correlation_id"": ""corr:5e81b7e31150d765d22b"", ""evidence"": [{""end_byte"": 15862, ""file"": ""DynReGrpSetCsvLoad.c"", ""start_byte"": 15781}], ""guards"": [], ""reachability"": ""LOCAL_BACKWALK"", ""route_id"": ""route:486818eef44d54547c9a"", ""transfer_chain"": [""[DynReGrpSetCsvLoad.c]DynReGrpSetCsvLoad:DynReGrpSetCsvLoad.c:15788 2=DynREGetSchKKfno(nFnoidxKK)""]}",1,LLM
```

UNRESOLVED (Class 1):

```
fact:268afe780bfe80d2231c,dyn401d,mpf_mfs_open_H,/home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c,214,dyn401dRequest.c:8178,2,UNRESOLVED,UNRESOLVED,/home/chukyu/t-dyn/src/dyn401d/dyn401dRequest.c,214,DynREGetSchfno(nFnoidx),OPENMF,NO DATA,dyn401dTimeOut,NA,,"{...""reachability"": ""CALLBACK"", ""registrar"": ""pmf_addtimeout"", ...""transfer_chain"": []}",1,SYNTAX
```

HANDLE_AMBIGUOUS (root cause C):

```
fact:b627ae5c59455856d35c,dyn401d,mpf_mfs_readrecn,/home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c,62,DynReEneOutStaFunc.c:2538,1,UNRESOLVED,UNRESOLVED,/home/chukyu/t-dyn/src/libDynRe/DynReEneOutStaFunc.c,62,HANDLE_AMBIGUOUS,RECF,NO DATA,DynReEneOutStaGet,NA,LOCAL_BACKWALK,"{""correlation_id"": ""corr:d6fb5409a1f5d6326a6a"", ""evidence"": [], ""guards"": [], ""reachability"": ""LOCAL_BACKWALK"", ""route_id"": ""route:d6fb5409a1f5d6326a6a"", ""transfer_chain"": []}",1,SYNTAX
```

---

## 3. Root cause C — branch-blind close invalidation: `HANDLE_AMBIGUOUS` (4 facts)

Sites: `libDynRe/DynReEneOutStaFunc.c:62, 66` (`mpf_mfs_readrecn`) and
`131, 143` (`mpf_mfs_writerecn`). All use the file-static handle `SFcbRE`.

### 3.1 The complete source (all of it — the file has 4 functions; only these two matter)

```c
// libDynRe/DynReEneOutStaFunc.c
25: /* static variables */
26: static DynReOutStaB    sSREOutSta[DYN_REENEKIND_MAX][DYN_REENE_MAX];
27: static MPF_MFS_FCB     SFcbRE;                       // <- the only FCB in this file

37: int
38: DynReEneOutStaGet(
39:     int nGNo ,
40:     int nReene_kind
41: )
42: {
43:     int nRtn;
45:     /* open the output-status file */
46:     nRtn = mpf_mfs_open_H(&SFcbRE, DynReOutStaFNO,     // 3937  -- the ONLY open in the file
47:                                   nReene_kind, 0, MPF_MFS_WRITELOCK);
48:     if (nRtn == -1)
49:     {
50:         return(-1);
51:     }
52:
53:     if ((nGNo < -1)||
54:         (nGNo >= DYN_REENE_MAX))
55:     {
56:         mpf_mfs_close(&SFcbRE);                        // <- defensive close, error branch ONLY
57:         return(-1);
58:     }
59:
60:     if (nGNo == -1)
61:     {
62:         mpf_mfs_readrecn(&SFcbRE, 0, 0, DYN_REENE_MAX, (void *)&sSREOutSta[nReene_kind]);   // UNRESOLVED
63:     }
64:     else
65:     {
66:         mpf_mfs_readrecn(&SFcbRE, 0, nGNo, 1, (void *)&sSREOutSta[nReene_kind][nGNo]);      // UNRESOLVED
67:     }
69:     return (0);
70: }

120: int
121: DynReEneOutStaPut
122: (
123:     int nGNo,
124:     int nReene_kind )
125: {
126:     char            aReqData[1];
127:
128:     if (nGNo == -1)
129:     {
131:         mpf_mfs_writerecn(&SFcbRE, 0, 0,                    // UNRESOLVED
132:                           DYN_REENE_MAX, 0, (void *)&sSREOutSta[nReene_kind]);
133:     }
134:     else
135:     {
136:         if ((nGNo < 0) || (nGNo >= DYN_REENE_MAX))
137:         {
138:             mpf_mfs_close(&SFcbRE);
139:             return(-1);
140:         }
142:         /* write one record */
143:         mpf_mfs_writerecn(&SFcbRE, 0, nGNo, 1, 0, (void *)&sSREOutSta[nReene_kind][nGNo]);   // UNRESOLVED
144:     }
145:     mpf_mfs_close(&SFcbRE);
148:     (void)pmf_forkproc_H( "dyn322d", 0, NULL, aReqData, sizeof(aReqData) );
150:     return (0);
```

Note: `DynReEneOutStaPut` opens nothing itself; it relies on the
file-static `SFcbRE` (the one open is in `DynReEneOutStaGet`, line 46).
The open at line 46 WAS resolved correctly in this run:
`091_mpf_mfs_open_H_DynReEneOutStaFunc.c_46_arg2_3937.log` — answer 3937
= `DynReOutStaFNO`, matching the enum comment.

### 3.2 Why the resolver still failed

For readrecn/writerecn the target "value" is the FNO of the file the handle
refers to (target spec: `handle_index`, `dependent_functions:
[mpf_mfs_open_H, mpf_mfs_openm_H, mpf_mfs_open, mpf_mfs_openm]`). Resolution
finds the open that owns the handle. The ownership filter is
`_binding_opens` (`value_flow/resolver.py:2036-2071`), and its close rule is
branch-blind:

```python
        close_sites = [
            site
            for site in self.sites_by_caller.get(caller_id, [])
            if self.function_configs.get(site.callee_name, {}).get("type") == "CLOSEF"
            and site.start_byte < before_byte
            and any(normalise_handle(argument.text) == root for argument in (...))
        ]
        if close_sites:
            last_close = max(item.start_byte for item in close_sites)
            candidates = [item for item in candidates if item.start_byte > last_close]
```

Any earlier close of the same handle discards the open — regardless of
control flow. Concretely:

- Sites 62/66 (inside `DynReEneOutStaGet`): the only open (line 46) precedes
  the error-branch close (line 56), which itself is followed by `return`.
  The close can never execute on the path that reaches the readrecn calls,
  but the filter does not know that. Open discarded → no binding.
- Sites 131/143 (inside `DynReEneOutStaPut`): no open in the function at
  all. The file-static global search (`static_scope` branch of
  `_resolve_handle`, `resolver.py:~1975-1995`) scans same-file functions,
  finds only `DynReEneOutStaGet`'s open, which the same filter discards.
- Both then fall to the LLM handle fallback, which produced only invalid
  guards — `guard_formula` ×4 in `run_stats.json`, exactly these 4 facts —
  and the resolver emitted `HANDLE_AMBIGUOUS`
  (`_unresolved_fact(query, "HANDLE_AMBIGUOUS")`, resolver.py:1920/2038).

True answer for all four facts: **3937 (`DynReOutStaFNO`)** — there is
exactly one open of `SFcbRE` in the file, and it is already correctly
resolved in the same run.

---

## 4. Minimal change: always say `UNRESOLVED` instead of emitting a variable/expression (analysis only, NOT applied)

Goal: a fact's `value` must never be a bare identifier, call expression, or
other non-literal C text.

The entire leak flows through one function: `_fact_from_arm`
(`value_flow/resolver.py:3250-3273`). Raw text reaches `value` in exactly
two branches: the `EXTERNAL` branch and the P17 `external_unknown` branch.
A ready-made predicate already exists for the gate — `_literal`
(`resolver.py:4353`, the same one the validator uses to reject
literal-disguises):

```python
    def _literal(self, value: str) -> bool:
        value = strip_outer_parens(value.strip())
        return bool(
            _NUMBER.fullmatch(value)
            or _STRING_OR_CHAR.fullmatch(value)
            or value in {"NULL", "true", "false", "nullptr"}
        )
```

Minimal shape (two value-assignments gated, nothing else):

```python
        elif binding.kind == "EXTERNAL":
            value = (binding.text or "EXTERNAL").strip()
            if not self._literal(value):
                value, origin = "UNRESOLVED", "UNRESOLVED"
            else:
                origin = str(source.get("origin_kind") or ("EXTERNAL_ENTRY" if "$" in value else "EXTERNAL_DATA"))
```

and in the P17 branch, replace the unconditional `value = binding.text` with
the same `_literal` gate (non-literal falls through to the existing
`value = "UNRESOLVED"` arm).

Properties:

- No provenance lost: `source_expr` (line ~3285:
  `source_expr = str(source.get("expr") or binding.text)`) and
  `metadata["unresolved_expr"]` already carry the raw text. `facts.csv`,
  logs, and the audit trail keep `DynREGetSchKKfno(nFnoidxKK)`; only the
  answer column changes.
- `outputs.py` needs no change: the legacy CSV copies `fact.value`, which
  would then read `UNRESOLVED`.
- The sentinel list (`RECURSIVE`/`UNRESOLVED`/`missing argument`/
  `HANDLE_AMBIGUOUS`) and the `EXACT` fast path are untouched.
- Resulting inventory: 894 CONST + 13 MACRO + **104 UNRESOLVED**
  (29 existing + 75 echoes). The 75 stop wearing a `CONST` costume.

Caveats to weigh before applying:

1. Cosmetic honesty, not resolution. The 75 echoes still have no real
   answer; the substantive fix is re-enabling the `return_table` path
   (root cause A). This gate only stops the tool from asserting a value it
   does not have.
2. Over-reach: an EXTERNAL binding that is a resolvable *macro name* also
   becomes UNRESOLVED. If that matters, the gate becomes
   "try `resolve_constant` first, else `_literal`, else UNRESOLVED" —
   strictly larger change.
3. Residual hole: the `EXACT` branch trusts `binding.text`. EXACT bindings
   are normally minted by `_settle_transfer_arm` only after
   `evaluate_formula` returns a concrete int/str, but the model's answer
   schema (`kind: Literal["EXPRESSION","EXACT","EXTERNAL","UNKNOWN"]`,
   `value_flow/transfers.py:33`) allows the model to return `EXACT` directly
   and nothing re-validates it. Airtight version adds the same one-line
   `_literal` gate there too.
4. The 29 already-UNRESOLVED and the 907 legitimate const/macro facts are
   unaffected.

---

## 5. Candidate fixes, per root cause (for the expert's judgement)

A. Table-lookup wrappers (100 facts)
   1. Re-enable `value_rules` in LLM mode, or decouple
      `self.value_rules` from `self.transfer_resolver is None`
      (resolver.py:358). The rule engine is source-grounded (values read
      from the parsed table initialiser, no model involved), so it does not
      conflict with LLM transfer; it would simply answer these sites
      mechanically as `CONST_TABLE` sets and the LLM would never see them.
      This single change covers all 100 facts, including the 4
      literal-index sites which become exact single values.
   2. Alternatively, extend the transfer formula grammar to accept
      `table[expr].field` validated against the parsed table.
   3. Independently: persist rejected LLM arms (raw answer + rejection
      reason) into `transfer_diagnostics`. The 25-vs-4 counter split in
      `run_stats.json` is currently the only forensic evidence left.

B. Output gate (75 facts) — the minimal `_literal` gate from section 4.

C. Branch-blind close invalidation (4 facts)
   1. Make the close filter in `_binding_opens` dominance-aware: a close
      only invalidates an open if it dominates the read site (i.e. is not
      on a branch that `return`s before the read). Cheap heuristic: ignore
      closes whose enclosing `if` body contains nothing but the close and a
      `return`.
   2. Or model open/close as guarded intervals instead of
      "last close wins".

D. Labelling: `_expression_source` (resolver.py:2609) should not stamp
   `origin_kind: "CONST"` on an unproved expression — use a neutral origin
   (e.g. `EXPRESSION`) that the emission path only keeps if the value is
   actually proven.

E. Prompt: `project_aware.py:718` ("A fast EXTERNAL or UNKNOWN is a GOOD
   answer") should be conditional — an EXTERNAL echo is acceptable only
   when the expression does not name a project-local function with an
   in-tree definition.

---

## Appendix A — file map (tool side)

| path | role |
|---|---|
| `c-visualizer/project_aware.py` | entry point; legacy prompts; transfer prompt at ~line 688-722 |
| `c-visualizer/value_flow/resolver.py` (4675 lines) | value-flow engine. Key lines: 352-359 (value_rules gate), 1414-1470 (`_table_values_for_function`), 1852-1876 (`_handle_candidates`), 1904-1925 (`handle_query_for_seed`), 1913-2039 (`_resolve_handle`), 2036-2071 (`_binding_opens`), 2580-2624 (`initial_route_arm`/`_expression_source`), ~2900-2935 (`_validate_transfer_answer`), 3250-3290 (`_fact_from_arm`), 4353 (`_literal`) |
| `c-visualizer/value_flow/transfers.py` | `Binding` schema (line 33), `validate_formula` (300), `_literal_value` (162), `placeholder_indices` (86) |
| `c-visualizer/value_flow/value_rules.py` | `DEFAULT_VALUE_RULES` (complete file quoted in 1.3) |
| `c-visualizer/value_flow/outputs.py` | `facts.csv` writer (~288-360); legacy CSV `target_number->ans` = `fact.value` (172-185) |
| `c-visualizer/target_specs/build_index_targets.json` | per-target arg config: `mpf_mfs_open_H` index 2; readrecn/writerecn `handle_index` 1, `dependent_functions` = the 4 open variants |

Run artifacts (`c-visualizer/results/csv_results/dyn401d/`):
`facts.csv` (936 rows, the ground truth), `paths.csv`, `run_stats.json`
(rejections, LLM query list, tokens), `query_cache.json`, `logs/` (one log
per fact), `summary.md`, `_const_verify_failures.txt`, and the legacy feed
`../dyn401d.csv` (one row per (target invocation, arg, source); answer
column = `fact.value`).

## Appendix B — exact per-site fact tables

Class 1 — UNRESOLVED with a `DynREGetSch*` expression (25 facts):

| facts | function | file:line | expr |
|---|---|---|---|
| 3 | mpf_mfs_open_H | dyn401d/dyn401dRequest.c:214 | DynREGetSchfno(nFnoidx) |
| 3 | mpf_mfs_readrecn | dyn401d/dyn401dRequest.c:214 (via handle from the open) | DynREGetSchfno(nFnoidx) |
| 3 | mpf_mfs_open_H | dyn401d/dyn401dRequest.c:363 | DynREGetSchKKfno(nFnoidxKK) |
| 3 | mpf_mfs_readrecn | dyn401d/dyn401dRequest.c:363 (via handle) | DynREGetSchKKfno(nFnoidxKK) |
| 3 | mpf_mfs_open_H | dyn401d/dyn401dRequest.c:373 | DynREGetSchKKLCfno(nFnoidxKK) |
| 3 | mpf_mfs_readrecn | dyn401d/dyn401dRequest.c:373 (via handle) | DynREGetSchKKLCfno(nFnoidxKK) |
| 3 | mpf_mfs_open_H | dyn401d/dyn401dAlznRequest.c:255 | DynREGetSchKKLCfno(nFnoidxKK) |
| 3 | mpf_mfs_readrecn | dyn401d/dyn401dAlznRequest.c:255 (via handle) | DynREGetSchKKLCfno(nFnoidxKK) |
| 1 | mpf_mfs_readrecn | dyn401d/dyn401dAlznRequest.c:245 (via handle) | DynREGetSchKKfno(nFnoidxKK) |

Class 3 — expression-as-value labelled CONST (75 facts, 22 call sites):

| facts | function | file:line | expr-as-value |
|---|---|---|---|
| 2+2 | open_H + readrecn | dyn401d/dyn401dAdvRequest.c:177 | DynREGetSchfno(nFnoidx) |
| 2+2 | open_H + readrecn | dyn401d/dyn401dAdvRequest.c:307 | DynREGetSchKKfno(nFnoidxKK) |
| 2+2 | open_H + readrecn | dyn401d/dyn401dAdvRequest.c:315 | DynREGetSchKKLCfno(nFnoidxKK) |
| 3+2 | open_H + readrecn | dyn401d/dyn401dAlznRequest.c:245 | DynREGetSchKKfno(nFnoidxKK) |
| 2+2 | open_H + writerecm | dyn401d/dyn401dScheStaUpd.c:190 | DynREGetSchfno(nFnoidx) |
| 2+2 | open_H + readrecm | dyn401d/dyn401dScheStaUpd.c:283 | DynREGetSchKKfno(0)  → exact value 3995 |
| 2+4 | open_H + writerecm | dyn401d/dyn401dScheStaUpd.c:299 | DynREGetSchKKfno(nFnoidx) |
| 2+2 | open_H + writerecm | dyn401d/dyn401dScheStaUpd.c:322 | DynREGetSchKKfno(0)  → exact value 3995 |
| 2+2 | open_H + readrecm | dyn401d/dyn401dScheStaUpd.c:334 | DynREGetSchKKLCfno(0)  → exact value 4003 |
| 2+4 | open_H + writerecm | dyn401d/dyn401dScheStaUpd.c:350 | DynREGetSchKKLCfno(nFnoidx) |
| 2+2 | open_H + writerecm | dyn401d/dyn401dScheStaUpd.c:373 | DynREGetSchKKLCfno(0)  → exact value 4003 |
| 1+1 | open_H + readrecn | libDynRe/DynReGrpSetCsvLoad.c:383 | DynREGetSchfno(nFnoidx) |
| 1+1 | open_H + readrecn | libDynRe/DynReGrpSetCsvLoad.c:401 | DynREGetSchKKfno(nFnoidxKK) |
| 1+1 | open_H + readrecn | libDynRe/DynReGrpSetCsvLoad.c:409 | DynREGetSchKKLCfno(nFnoidxKK) |
| 1+1 | open_H + readrecn | libDynRe/DynReSchSetCsvLoad.c:446 | DynREGetSchfno(nFnoidx) |
| 1+1 | open_H + readrecn | libDynRe/DynReSchSetCsvLoad.c:459 | DynREGetSchKKfno(nFnoidxKK) |
| 1+1 | open_H + readrecn | libDynRe/DynReSchSetCsvLoad.c:466 | DynREGetSchKKLCfno(nFnoidxKK) |
| 1+1 | open_H + writerecn | libDynRe/DynReSchSetCsvLoad.c:510 | DynREGetSchfno(nFnoidx) |
| 1+1 | open_H + readrecn | libDynRe/DynReSchSetCsvLoad2.c:494 | DynREGetSchfno(nFnoidx) |
| 1+1 | open_H + readrecn | libDynRe/DynReSchSetCsvLoad2.c:504 | DynREGetSchKKfno(nFnoidxKK) |
| 1+1 | open_H + readrecn | libDynRe/DynReSchSetCsvLoad2.c:511 | DynREGetSchKKLCfno(nFnoidxKK) |
| 1+1 | open_H + writerecn | libDynRe/DynReSchSetCsvLoad2.c:604 | DynREGetSchfno(nFnoidx) |
| 1+1 | open_H + readrecn | libDynRe/DynReSchSetKKCsvExport.c:81 | DynREGetSchKKfno(nFnoidx) |
| 1+1 | open_H + readrecn | libDynRe/DynReSchSetKKCsvExport.c:88 | DynREGetSchKKLCfno(nFnoidx) |

(Counting convention: "a+b" = a open_H facts + b readrecn/writerecm/
readrecm sibling facts that inherited the same value through the `&fcb`
handle → open binding. Per-function totals: open_H 36, readrecn 19,
writerecm 14, readrecm 4, writerecn 2 = 75.)

Class C — HANDLE_AMBIGUOUS (4 facts):

| facts | function | file:line | true answer |
|---|---|---|---|
| 1 | mpf_mfs_readrecn | libDynRe/DynReEneOutStaFunc.c:62 | 3937 (DynReOutStaFNO, open at line 46) |
| 1 | mpf_mfs_readrecn | libDynRe/DynReEneOutStaFunc.c:66 | 3937 |
| 1 | mpf_mfs_writerecn | libDynRe/DynReEneOutStaFunc.c:131 | 3937 |
| 1 | mpf_mfs_writerecn | libDynRe/DynReEneOutStaFunc.c:143 | 3937 |

## Appendix C — target-source SVN ids (for pinning the excerpt provenance)

```
$Id: DynReEneFileDef.h 10603 2026-06-04 01:26:38Z t-dyn $
$Id: DynREGetSchePos.c 10581 2026-06-04 00:53:12Z t-dyn $
```

(Other files carry the same SVN-id banner; line numbers in this brief were
verified against the working copy at `/home/chukyu/t-dyn/src`.)

## Appendix D — how to reproduce the counts

```bash
cd c-visualizer/results/csv_results/dyn401d
# total
wc -l facts.csv
# Class 3: expression-as-value
python3 -c "import csv; rows=list(csv.DictReader(open('facts.csv'))); print(sum('DynREGetSch' in r['value'] for r in rows))"
# Class 1 + C: UNRESOLVED
python3 -c "import csv; rows=list(csv.DictReader(open('facts.csv'))); print(sum(r['value']=='UNRESOLVED' for r in rows))"
# rejections
python3 -c "import json; print(json.load(open('run_stats.json'))['transfer_rejections'])"
# one raw fact + its log
grep '^fact:caf33bf5e13155cbc1a3,' facts.csv
cat logs/598_mpf_mfs_open_H_dyn401dAlznRequest.c_245_arg2_DynREGetSchKKfno_nFnoidxKK.log
```

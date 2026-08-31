# Value-Flow Transfer Resolver — Problem Inventory and Repair Plan

Scope: `value_flow/resolver.py`, `value_flow/transfers.py`, `models.py`,
`project_aware.py`, `client/llm.py`.

Symptoms being addressed:

1. High UNRESOLVED rate on real projects (resolved answers are accurate).
2. Very long prompts / high prefill time per LLM hop.
3. Wasted LLM calls — answers that are computed and then discarded.

Ground rule for every change below: **minimal, additive, reversible.** No
refactors, no renames, no schema field removals. Every new model field has a
default so old cache entries still validate. Every behavioural change is
either (a) strictly more permissive on a path that currently discards data, or
(b) gated so the old path remains reachable.

Nothing here has been executed. Line numbers are from the working tree at the
time of writing and should be confirmed before editing.

---

## Part 1 — Problem inventory

Each item is marked **Confirmed** (read directly in the code) or **Likely**
(strongly implied but not executed).

### A. Prompt / context problems

**P1 — `function_source` is the entire file, not the function. (Confirmed)**

`FunctionInfo.source` is assigned the whole file's bytes:

- `value_flow/resolver.py:471` — `source = self.trees.get(function_node.file_name, (None, b""))[1]`
- `value_flow/resolver.py:503` — `source=source,`

It must be the whole file, because `_local_reaching_definitions` and
`node_text()` index it with absolute Tree-sitter byte offsets.

But it is then handed straight to the model:

- `value_flow/resolver.py:2809` — `function_source=current_function.source.decode("latin-1", errors="replace")`
- rendered in `project_aware.py` under the label `CURRENT FUNCTION SOURCE:`

Consequences:

- Every transfer hop ships an entire C translation unit. This is the direct
  cause of the prefill-time problem.
- `num_ctx` is 110000 (`client/llm.py:74`). Large files silently truncate, and
  what gets cut is the tail — which may include the schema instructions.
- The model is told it is looking at one function and given a whole file.
- It also poisons the cache key (see P2).

**P2 — Cache key digests the whole file. (Confirmed)**

`value_flow/resolver.py:2810` passes `function_source=current_function.source`
into `make_transfer_cache_key`. Editing *any* function in a file invalidates
every cached transfer for *every* function in that file.

**P3 — Whole-file decode and SHA run before the cache lookup. (Confirmed)**

In `request_local_transfer` the order is: build `macro_context` → sha256 →
`make_transfer_cache_key` (whole-file sha256) → build `TransferRequest`
(whole-file `.decode("latin-1")`) → *then* check `self.transfer_cache`
(`value_flow/resolver.py:2790-2827`). Every cache hit still pays a full
whole-file decode plus two whole-file digests. With high route fan-out this is
likely the dominant CPU cost of a "mostly cached" run.

**P4 — Macro/enum values are not supplied to the model. (Confirmed)**

The transfer prompt allows macro and enum identifiers in a formula
(`_transfer_visible_names`, `value_flow/resolver.py:2552`) but never tells the
model what those names expand to. The repo already has this capability —
`parser/parser_files.py:177 all_macros_in_file()` plus the
`//NAME=value` filtered-macro block emitted at the end of `parse_for_path` —
but it is only wired into the *legacy* one-hop prompt via `context_for`
(`project_aware.py:1732`), not into the transfer prompt.

Note: `parseFiles` reads from **disk** and runs `_format_code()`, so its output
does not share byte offsets with `resolver.trees`. It cannot be dropped into
the transfer prompt as-is without breaking evidence spans. The plan below
reuses the *idea* (trimmed body + `//NAME=value` block) using data the resolver
already holds.

### B. Evidence / answer-validation problems

**P5 — A single degenerate byte span discards the entire answer. (Confirmed — this is the reported `start_byte == end_byte` failure)**

`models.py:33-40`:

```python
start_byte: int = Field(ge=0)
end_byte: int = Field(gt=0)

@model_validator(mode="after")
def validate_range(self):
    if self.end_byte <= self.start_byte:
        raise ValueError("end_byte must be greater than start_byte")
```

That raise propagates out of `TransferAnswerModel.model_validate` in
`_validate_transfer_answer` (`value_flow/resolver.py:2688-2694`), which returns
`None`, which makes `request_local_transfer` return `None`, which marks every
pending binding `UNKNOWN / "UNRESOLVED"` (`value_flow/resolver.py:3219-3226`).

So: the model does the work, gets the *bindings* right, emits one span with
`start == end`, and the whole hop is thrown away. This is the single most
wasteful failure mode in the pipeline — it is pure discarded compute.

**P6 — One bad span discards a whole arm. (Confirmed)**

`value_flow/resolver.py:2708-2714`: an unresolvable file or an out-of-range
`end_byte` sets `valid_spans = False` and `break`s, dropping the arm even when
other spans were fine.

**P7 — `_resolve_project_file` fails on ambiguous basenames. (Confirmed)**

`value_flow/resolver.py:2663-2675`. Resolution order is exact key → resolved
absolute path → basename match, and the basename match requires
`len(matches) == 1`. Any project with several `common.h` / `main.c` / `def.h`
copies fails here, and P6 then drops the arm.

**P8 — Arms must cover the pending set exactly. (Confirmed)**

`value_flow/resolver.py:2700`: `set(indices) != pending_set` → `continue`. If
the model resolves two of three requested arguments, the two correct bindings
are discarded along with the third.

**P9 — An inexpressible guard destroys valid bindings. (Confirmed)**

`value_flow/resolver.py:2727-2762`: the guard is validated first, inside the
same `try` as the bindings. `if (ctx->state == READY)` is outside the formula
grammar → `FormulaError` → `continue` → the arm's bindings are lost. A guard
can only ever *narrow* an answer; discarding the answer because the guard is
inexpressible is backwards.

**P10 — The formula grammar excludes ordinary C. (Confirmed)**

`value_flow/transfers.py:196-236` (`_validate_node`) accepts only
`parenthesized_expression`, literals, identifiers, `unary_expression`,
`binary_expression`. No field access, subscript, dereference, ternary, or call.

**P11 — Literal/evidence check is a raw substring match. (Confirmed)**

`value_flow/transfers.py:255-262`: `if literal not in evidence: raise`. `0x10`
vs `16`, `1U` vs `1`, `'\n'` vs `10` all fail even when the answer is right.

### C. Structural UNRESOLVED that never reaches the model

**P12 — Missing `ast_node` ⇒ `parameters = []` ⇒ every arm rejected. (Confirmed mechanism, Likely frequency)**

`_build_function_index` (`value_flow/resolver.py:472-479`) matches a registry
function to a Tree-sitter `function_definition` **by name only**. Anything
Tree-sitter does not parse as a plain `function_definition` — macro-decorated
signatures (`EXTERN`, `CALLBACK`, `PASCAL`, `__declspec`), K&R definitions, a
definition inside an unresolved conditional — leaves `ast_node = None` and
therefore `parameters = []`. Then:

- the prompt reports `FORMAL PARAMETERS (1-based): (void)`;
- `validate_formula(parameter_count=0)` rejects any `$N` with
  "parameter $N does not exist" (`value_flow/transfers.py:222-224`);
- `_mark_external_or_unknown` with empty `parameter_names` yields UNKNOWN
  instead of EXTERNAL_ENTRY (`value_flow/resolver.py:2988-2997`);
- the entry-point shortcut at `value_flow/resolver.py:3179-3195` can never fire.

One index miss turns every hop through that function into UNRESOLVED, silently.

**P13 — Handle-dependent targets fail before any model call. (Confirmed)**

`_opening_for_route` (`value_flow/resolver.py:3312`) accepts only
`len(bindings) == 1`. Zero candidate opens *and also* two-or-more both return
`None`; `_resolve_seed_with_transfers` then emits
`Binding(index, "UNKNOWN", "HANDLE_AMBIGUOUS")` for the whole seed
(`value_flow/resolver.py:3484-3493`). Two opens in an if/else branch on the
same FCB is ordinary C, and the engine already supports multiple arms.

**P14 — Macro sites poison arms that do not depend on them. (Confirmed)**

`_substitute_arm` (`value_flow/resolver.py:2928-2931`) returns `None` on
`site.macro_args_unmapped` **before** checking whether the arm contains any
`$N` placeholder at all. And the caller routes that `None` to
`_mark_external_or_unknown(child, external=False)`
(`value_flow/resolver.py:3266-3268`) → **UNKNOWN**, whereas the structurally
equivalent callback bail-out uses `external=True` → EXTERNAL_ENTRY.

`macro_args_unmapped` is set generously by `_macro_call_arguments`: macro not in
`builder_macros`, any `##` or stringification, variadic, or arity mismatch.

**P15 — `_macro_call_arguments` can return an empty argument list marked reliable. (Confirmed)**

`value_flow/resolver.py:648` — `return [], True`. Every `site.argument(i)` is
then `None`, so `initial_route_arm` emits `Binding(index, "UNKNOWN", "missing argument")`
(`value_flow/resolver.py:2530`) with no model call. This looks like a plain bug.

**P16 — `start_byte` falls back to a list ordinal. (Confirmed)**

`_build_call_index`: when `call_site.start_byte < 0` and `ast_node is None`,
`start_byte = ordinal` — an index used as a byte offset. That produces a
garbage `site_id`, a garbage `SELECTED OUTGOING CALL (n:m)` in the prompt, and
an empty `selected_site_source` slice in the cache key. `call_text` also
degrades to the bare `callee_name`, so the model is asked about a call it
cannot see.

### D. Information destroyed at the output boundary

**P17 — UNKNOWN bindings discard the traced expression. (Confirmed)**

`_fact_from_transfer_binding` (`value_flow/resolver.py:3049-3050`):

```python
value = "UNRESOLVED"
origin = "RECURSIVE" if binding.text == "RECURSIVE" else "UNRESOLVED"
```

`_mark_external_or_unknown` carefully preserves the substituted expression in
`binding.text`, and this then throws it away.

Compare the legacy engine for the same situation — `_resolve_expression`
(`value_flow/resolver.py:1284-1298`) returns
`Fact(value=raw, origin_kind="EXTERNAL_DATA" | "UNKNOWN_INDIRECT")`, i.e. it
hands back `cfg->file_no`. This asymmetry is a plausible reason the transfer
engine *feels* far more unresolved than what it replaced.

**P18 — `_legacy_rows` silently drops whole groups. (Confirmed)**

`value_flow/outputs.py:157-163`: if a correlated group's argument indices do
not exactly equal the configured `indices`, `continue` — the target invocation
vanishes from the legacy CSV entirely. Some rows believed "unresolved" may
actually be missing.

### E. Bugs

**P19 — `active` set leaks on transfer failure, mislabelling later arms RECURSIVE. (Confirmed)**

`active.add(state_key)` at `value_flow/resolver.py:3212`;
`active.discard(state_key)` at `3278`; but the failure path at `3219-3226`
`continue`s and skips the discard. Any later arm in the same route walk with an
identical state is then labelled `RECURSIVE` rather than retried. This also
corrupts the diagnostics you would use to debug all of the above.

### F. Speed

**P20 — Every LLM hop forks a process. (Confirmed)**

`run_with_retry` (`project_aware.py:812`) uses `multiprocessing` fork with
`process.join(timeout=600)` and `retries=2`. Each child copy-on-writes a parent
holding all trees, ASTs and the registry; CPython refcounting dirties those
pages for real. Worst case per hop is 20 minutes before returning `None` →
UNRESOLVED. There is also a pipe-capacity hazard: the child `conn.send`s while
the parent is inside `join()`, so a payload exceeding the pipe buffer blocks the
child, the join times out, and a *successful* answer is killed and recorded as
a timeout.

**P21 — The whole cache is discarded whenever any file changes. (Confirmed)**

`_load_cache` (`value_flow/resolver.py:993-998`) returns early on a
`cache_fingerprint` mismatch, and `cache_fingerprint` digests every byte of
every project file (`value_flow/resolver.py:427-433`). One edit throws away
every transfer answer — even though `make_transfer_cache_key` already digests
the function source, the site source, the prompt version and the model id, and
is therefore self-validating per entry.

**P22 — `routes_for_seed` is an uncached exponential DFS called repeatedly. (Confirmed)**

Five call sites (`value_flow/resolver.py:3363, 3423, 3459, 3483, 3486`), and
`_resolve_seed_with_transfers` reaches it twice for a single seed. Cap is 10000
routes, each re-walking shared suffixes.

**P23 — `_transfer_visible_names` is rebuilt 2N times per arm. (Confirmed)**

Called once for the guard and once per binding inside `_validate_transfer_answer`
(`value_flow/resolver.py:2731, 2742`), each time copying the file's macro set
and unioning the enum set.

**P24 — The transfer prompt runs an agentic tool loop plus a second prose→JSON pass. (Confirmed)**

`client/llm.py:463-471` calls `chat.completions.create(..., tools=self.tools,
tool_choice="auto")` in a loop of up to 100 iterations × 5 attempts. When the
model finally answers in prose, a **second** model call converts that prose to
JSON (`client/llm.py:494-560`), so byte spans must survive a prose round-trip.

**P25 — The prose→JSON pass injects the legacy scalar contract into transfer requests. (Confirmed)**

`client/llm.py:513-527`: the guard is
`if self.output_model.__name__ != "outputModelForReturn"`, which is **true** for
`TransferAnswerModel`. So a transfer request is told:

> "For answer use argument number and its value like 1:value,2:value" …
> "If argument's value is not resolved then report as UNRESOLVED" …
> "DONT RETURN A LIST."

while simultaneously being handed the `arms: [...]` schema. Additionally
`argument_number_to_track` is `None` for transfer prompts
(`client/llm.py:174-176`), so it prints "we are only tracking these arguments
None". This is a direct contract collision on every transfer hop, and is a
strong candidate for the bulk of `model_validate` failures.

---

## Part 2 — Repair plan

Five phases. Phases 0–2 are the ones that should move the numbers. Phases 3–4
are follow-ups to run only after Phase 0 gives you measurements.

### Phase 0 — Measure and stop the bleeding (zero behavioural risk)

Do this first. Every later decision depends on knowing which failure actually
dominates. All four changes are additive; none alters resolution behaviour.

---

#### Fix 0.1 — Record why an arm was rejected (P5–P11)

**File:** `value_flow/resolver.py`, `_validate_transfer_answer` (~2677-2764).

`self.transfer_diagnostics` already exists (`:412`) and is already surfaced in
run stats (`project_aware.py:1954`). It is currently written from exactly one
place (`:2490`).

Add a counter dict in `__init__` next to the existing counters:

```python
self.transfer_rejections: dict[str, int] = defaultdict(int)
```

Then at each `continue` / early `return None` in `_validate_transfer_answer`,
increment a distinct key before continuing:

| Location (approx.) | Key |
|---|---|
| `:2693` pydantic parse failure | `"schema_invalid"` |
| `:2700` index-set mismatch | `"pending_mismatch"` |
| `:2709` file unresolved | `"file_unresolved"` |
| `:2713` end_byte out of range | `"span_out_of_range"` |
| `:2724` no spans / no current-function span | `"no_current_span"` |
| `:2761` guard formula error | `"guard_formula"` (see 2.4) |
| `:2761` binding formula error | `"binding_formula"` |

Also increment in `request_local_transfer`: `"llm_returned_none"` when
`raw_answer is None` (`:2830`), and `"all_arms_rejected"` when
`validated` is falsy (`:2831`).

Expose it alongside the existing counters in `project_aware.py:1951-1956`:

```python
"transfer_rejections": dict(resolver.transfer_rejections),
```

**Risk:** none. Pure instrumentation.
**Verification:** run one process, read the new dict in run stats.

---

#### Fix 0.2 — Distinguish a model/transport failure from a genuine unknown (P20)

**File:** `value_flow/resolver.py`, `_await_llm` (~1778-1782).

The `except Exception` swallows transport errors into `None`, which is
indistinguishable from "model says unknown". Add a counter before returning:

```python
except Exception as exc:
    self.transfer_rejections["llm_exception"] += 1
    print(f"Value-flow LLM query failed, continuing without it: {exc}")
    return None
```

**Risk:** none.

---

#### Fix 0.3 — Warn about functions with no `ast_node` (P12)

**File:** `value_flow/resolver.py`, end of `_build_function_index` (~505).

```python
missing = [fid for fid, info in self.functions.items() if info.ast_node is None]
if missing:
    print(f"VALUEFLOW: WARNING {len(missing)} function(s) have no AST node; "
          f"their parameters are empty and every transfer through them will "
          f"fail. First 10: {missing[:10]}")
```

**Risk:** none. This one line tells you immediately whether P12 is a real
problem in your codebase or a theoretical one. If the count is non-trivial,
prioritise it above almost everything else.

---

#### Fix 0.4 — Fix the `active` set leak (P19)

**File:** `value_flow/resolver.py:3219-3226`.

Add one line before the `continue`:

```python
if not transferred:
    arm.bindings = [...]
    terminal.append(arm)
    active.discard(state_key)      # <-- add
    continue
```

**Risk:** none — it restores the intended symmetry with `:3278`.
**Why it matters now:** without it your RECURSIVE counts include failures that
are not recursion, which would mislead the Phase 0 measurements.

---

### Phase 1 — Stop wasting completed LLM work (P5, P6, P7, P8)

This phase recovers answers the model already produced correctly. It is the
highest value-per-line in the plan, and it directly targets the reported
`start_byte == end_byte` waste.

---

#### Fix 1.1 — Make evidence spans repairable instead of fatal (P5)

**File A: `models.py:28-40`.**

```python
class TransferEvidenceModel(BaseModel):
    """An exact source span supporting one local value transfer."""

    model_config = ConfigDict(extra="forbid")
    file: str
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)          # was gt=0
    snippet: str = ""                    # new, optional

    # NOTE: no model_validator. A degenerate or inverted span is repaired in
    # ValueFlowResolver._validate_transfer_answer, not rejected here. Rejecting
    # here discards the whole answer including correct bindings.
```

Delete the `validate_range` validator.

Both edits are backward compatible with the persisted cache: `snippet` has a
default, and loosening a constraint never invalidates a stored entry.

**File B: `value_flow/resolver.py`, `_validate_transfer_answer`,
the evidence loop (~2702-2725).**

Replace the per-span body with a repair sequence. Keep the existing
`spans` / `current_span` variables and the final
`if not spans or not current_span: continue` check unchanged.

```python
function_node = current_function.ast_node
fn_start = function_node.start_byte if function_node is not None else 0
fn_end = function_node.end_byte if function_node is not None else 0

for evidence in model_arm.evidence:
    file_name = self._resolve_project_file(evidence.file)
    if file_name is None:
        self.transfer_rejections["file_unresolved"] += 1
        continue                          # was: valid_spans = False; break
    source = self.trees[file_name][1]
    span = self._repair_span(evidence, source, fn_start, fn_end,
                             same_file=file_name == current_function.node.file_name)
    if span is None:
        self.transfer_rejections["span_unrepairable"] += 1
        continue                          # drop this span, keep the arm
    start, end = span
    spans.append(EvidenceSpan(file_name, start, end))
    if (file_name == current_function.node.file_name
            and function_node is not None
            and start < fn_end and end > fn_start):
        current_span = True
```

The `valid_spans` flag becomes unnecessary; delete it and its use in the
final guard, leaving `if not spans or not current_span: continue`.

**New helper**, placed next to `_evidence_texts` (~2653):

```python
def _repair_span(self, evidence, source, fn_start, fn_end, *, same_file):
    """Return a usable (start, end) byte span, or None.

    Models reliably get byte arithmetic wrong. The common failures are a
    degenerate span (start == end), an inverted span, and offsets given
    relative to the function body rather than the file. Each is repairable
    from source, so none of them should cost a whole answer.
    """
    limit = len(source)
    start = max(0, min(int(evidence.start_byte), limit))
    end = max(0, min(int(evidence.end_byte), limit))

    # 1. An exact snippet beats any offset the model computed.
    snippet = (evidence.snippet or "").strip()
    if snippet:
        raw = snippet.encode("latin-1", errors="replace")
        found = source.find(raw, fn_start, fn_end) if same_file and fn_end else -1
        if found < 0:
            found = source.find(raw)
        if found >= 0:
            return found, found + len(raw)

    # 2. Offsets given relative to the function body.
    if same_file and fn_end and end > start and end <= (fn_end - fn_start):
        shifted_start, shifted_end = fn_start + start, fn_start + end
        if shifted_end <= fn_end:
            return shifted_start, shifted_end

    # 3. A well-formed absolute span.
    if end > start:
        return start, end

    # 4. Degenerate or inverted: widen to the line containing `start`.
    #    This is the reported start_byte == end_byte case.
    anchor = start if start else end
    if not (0 <= anchor < limit):
        return None
    line_start = source.rfind(b"\n", 0, anchor) + 1
    line_end = source.find(b"\n", anchor)
    line_end = limit if line_end < 0 else line_end
    return (line_start, line_end) if line_end > line_start else None
```

**Why step 2 matters for safety:** the existing fake resolvers in
`tests/test_llm_transfer_value_flow.py:67-78, 318-319` compute offsets from
`request.function_source` and treat them as file-absolute. That works today
only because `function_source` is the whole file. Once Fix 2.1 slices it,
those tests would produce function-relative offsets — and step 2 accepts
exactly that. So Fix 1.1 must land **before** Fix 2.1, and it makes Fix 2.1
non-breaking for the existing tests.

**Risk:** low. Every branch is strictly more permissive than today; nothing
that currently validates stops validating. Step 4 widens to a line boundary,
which can only make the evidence text *larger* — and evidence text is used
only to confirm literals (`validate_formula`) and to locate a source witness
(`_settle_transfer_arm`), both of which tolerate a wider span.

**One thing to watch:** a wider span makes the literal-coverage check *more*
permissive, so a literal could be "covered" by a neighbouring token on the same
line. That is a small, bounded loss of strictness in exchange for recovering
whole answers. If you want it tighter, restrict step 4 to the case where the
line contains a `=`, `(` or `return`.

**Verification:** unit-test `_repair_span` directly with (start==end),
(end<start), (relative offsets), (snippet present), (snippet absent). This is
a pure function — it is the one piece here that is cheap to test properly.

---

#### Fix 1.2 — Ask the model for a snippet (P5)

**File:** `project_aware.py`, `llm_calls_transfer` user prompt (~712-717).

Replace the evidence instruction:

```
Cite byte spans as file/start_byte/end_byte.
```

with:

```
For each evidence item set "snippet" to the exact source text you are citing,
copied verbatim from CURRENT FUNCTION SOURCE (one line is enough), and set
"file" to its file. Byte offsets are optional; if you are unsure, set
start_byte and end_byte to 0 and rely on the snippet.
```

**Risk:** none structurally — `snippet` defaults to `""` and the repair
sequence falls through to the existing offset behaviour. This turns the
model's hardest sub-task (byte arithmetic) into its easiest (copying text).

**Must be paired with:** bumping `transfer_prompt_version` (see Fix 2.2).

---

#### Fix 1.3 — Accept partial arms (P8)

**File:** `value_flow/resolver.py:2698-2701`.

```python
bindings = model_arm.bindings
indices = [item.target_arg for item in bindings]
if len(indices) != len(set(indices)) or not set(indices) <= pending_set:
    self.transfer_rejections["pending_mismatch"] += 1
    continue
if not indices:
    continue
```

The arm-construction code at `value_flow/resolver.py:2870-2876` already
handles a partial answer correctly — it looks each binding up by index and
falls back to the parent arm's binding:

```python
model_bindings.get(binding.target_arg, binding)
```

So an unanswered pending argument simply stays `EXPRESSION` and is carried to
the next hop, which is the desired behaviour.

**Risk:** low. The change is `!=` → `not ⊆`, plus an empty guard. Duplicate
detection is unchanged.

**Watch for:** an arm answering *zero* pending args would loop — the `if not
indices: continue` guard prevents that. Also confirm no infinite loop: if the
model returns the same partial answer at the same site, the `active` state key
(now correctly maintained by Fix 0.4) catches it as RECURSIVE.

---

#### Fix 1.4 — Resolve ambiguous file paths by longest suffix (P7)

**File:** `value_flow/resolver.py:2674-2675`.

```python
matches = [name for name in self.trees if Path(name).name == Path(candidate).name]
if len(matches) == 1:
    return matches[0]
# Several files share this basename. Prefer the longest matching path suffix,
# then the file the current walk is already in (passed by the caller when
# available). Ambiguity that survives both is still None.
parts = tuple(Path(candidate).parts)
best, best_score = None, 0
for name in matches:
    other = tuple(Path(name).parts)
    score = 0
    while score < min(len(parts), len(other)) and parts[-1 - score] == other[-1 - score]:
        score += 1
    if score > best_score:
        best, best_score = name, score
    elif score == best_score:
        best = None            # tie: still ambiguous
return best
```

**Risk:** low, and strictly additive — the `len(matches) == 1` fast path is
unchanged, so today's successful resolutions are untouched. Ties still return
`None`.

---

### Phase 2 — Cut the context (P1, P2, P3, P4)

This is the prefill fix. Land it after Phase 1 so the span repair is already in
place to absorb the offset-convention change.

---

#### Fix 2.1 — Send the function, not the file

**File A: `value_flow/transfers.py`, `TransferRequest` (~66-83).**

Add one defaulted field. Additive only — the dataclass is documented as the
stable seam for fake tests, and a default keeps every existing constructor call
valid:

```python
    macro_context: str = ""
    function_start_byte: int = 0   # file offset of function_source[0]
```

**File B: `value_flow/resolver.py`, `request_local_transfer` (~2804-2818).**

Add a small helper next to `_evidence_texts`:

```python
def _function_slice(self, function: FunctionInfo) -> tuple[str, int]:
    """Return (source text, file offset) for one function.

    FunctionInfo.source is the whole file, because reaching-definition
    analysis indexes it with absolute Tree-sitter offsets. The model needs
    only the function, so slice here rather than shipping the file.
    """
    node = function.ast_node
    if node is None:
        # No AST node: fall back to today's behaviour rather than send
        # nothing. See the _build_function_index warning (Fix 0.3).
        return function.source.decode("latin-1", errors="replace"), 0
    return (
        function.source[node.start_byte:node.end_byte].decode("latin-1", errors="replace"),
        node.start_byte,
    )
```

and use it:

```python
function_text, function_base = self._function_slice(current_function)
...
request = TransferRequest(
    ...
    function_source=function_text,
    function_start_byte=function_base,
    ...
)
```

**File C: `project_aware.py`, `llm_calls_transfer` user prompt (~698-701).**

```
CURRENT FUNCTION SOURCE (starts at file byte {function_start_byte}):
{function_source}
```

and add `"function_start_byte": request.function_start_byte,` to the
`user_prompt` dict (~730).

**Risk:** medium — this is the largest behavioural change in the plan, so note
the guards:

- Fake resolvers in `tests/test_llm_transfer_value_flow.py` compute offsets
  from `function_source`. After the slice these become function-relative.
  **Fix 1.1 step 2 accepts function-relative offsets**, so those tests should
  continue to pass. Confirm this by running that file first; if any test still
  fails, the correct fix is in the test's fake, not in the resolver.
- The `ast_node is None` fallback preserves today's exact behaviour, so P12
  functions do not regress — they just stay bad until P12 is fixed.
- `function_source` is sliced from the same `trees` bytes the spans are
  validated against, so offsets stay internally consistent. Do **not** be
  tempted to substitute `parseFiles` output here: it reads from disk and runs
  `_format_code()`, so its text does not share offsets with `trees`.

**Expected effect:** prompt size drops by roughly the file-to-function ratio —
commonly 10–100×. This is the prefill fix.

---

#### Fix 2.2 — Key the cache on the function slice, and bump the prompt version

**File: `value_flow/resolver.py`, `request_local_transfer` (~2810).**

```python
function_source=function_text,     # was current_function.source
```

**File: `project_aware.py:1902`.**

```python
transfer_prompt_version="valueflow-transfer-v2",
```

The prompt has changed (Fixes 1.2, 2.1, 2.3), so the version **must** be bumped
or stale answers computed under the old contract will be served as hits. Bumping
it invalidates the transfer cache once, which is expected and correct.

**Risk:** none beyond the one-time cache miss. Note that both effects — the
narrower key and the version bump — land together, so there is exactly one
invalidation, not two.

---

#### Fix 2.3 — Give the model the macro and enum values it is allowed to use (P4)

The transfer grammar permits macro and enum identifiers but never says what
they expand to. This mirrors what `parseFiles` already does for the legacy
prompt (`parser/parser_files.py:177 all_macros_in_file`, and the
`//NAME=value` block appended in `parse_for_path`), using data the resolver
already holds so byte offsets are unaffected.

**File: `value_flow/resolver.py`, `request_local_transfer`, just before
`macro_context` is built (~2779).**

```python
# NOTE: the module-level _IDENTIFIER (value_flow/resolver.py:46) is anchored
# with ^...$ and is only usable with fullmatch(). Use a separate scan pattern.
_IDENT_SCAN = re.compile(r"[A-Za-z_]\w*")     # module scope, next to _IDENTIFIER

names = set(_IDENT_SCAN.findall(function_text)) & self._transfer_visible_names(
    current_function.node.file_name
)
constants: dict[str, str] = {}
for name in sorted(names)[:200]:          # bounded: this goes in the prompt
    resolved = self._constant_from_text(name, current_function.node.file_name)
    if resolved is not None:
        constants[name] = resolved[0]
```

Then add one key to the existing `macro_context` dict (~2782-2790):

```python
macro_context = json.dumps(
    {
        "name": selected_site.macro_name,
        "unmapped": selected_site.macro_args_unmapped,
        "expanded_arguments": [item.text for item in selected_site.arguments],
        "source_arguments": [item.text for item in selected_site.target_arguments],
        "constants": constants,          # <-- add
    },
    sort_keys=True,
)
```

**Why fold it into `macro_context` rather than add a new field:** `macro_context`
is already hashed into `macro_digest` (so the cache key updates automatically)
and already interpolated into the prompt as `{macro_context}` (so the model
already sees it). Zero new plumbing, and it cannot desynchronise the cache.

The 200-entry cap keeps a macro-heavy header from re-inflating the prompt you
just shrank. `_constant_from_text(text, file_name)` and `_transfer_visible_names(file_name)`
are existing helpers with exactly these signatures.

**Risk:** low. `_constant_from_text` and `_transfer_visible_names` are both
existing, already-used helpers. Worst case the model ignores the block.

**Verification:** confirm `sorted(names)` is deterministic so cache keys are
stable across runs — it is, because `constants` is a dict built in sorted order
and `json.dumps(..., sort_keys=True)` normalises it.

---

#### Fix 2.4 — Do not let an inexpressible guard destroy valid bindings (P9)

**File: `value_flow/resolver.py:2727-2762`.**

Split the guard out of the bindings' `try`:

```python
evidence_texts = self._evidence_texts(spans)
visible = self._transfer_visible_names(current_function.node.file_name) | {"NULL", "nullptr"}
guard = model_arm.guard
try:
    validate_formula(
        guard,
        parameter_count=len(current_function.parameters),
        visible_names=visible,
        evidence_texts=evidence_texts,
        allow_boolean_literals=True,
    )
except (FormulaError, ValueError, TypeError):
    # A guard only ever narrows an answer. If it cannot be expressed in the
    # formula grammar, drop the guard and keep the bindings rather than
    # discarding a correct transfer.
    self.transfer_rejections["guard_formula"] += 1
    guard = "true"
try:
    for binding in bindings:
        ...   # unchanged
except (FormulaError, ValueError, TypeError):
    self.transfer_rejections["binding_formula"] += 1
    continue
```

The dropped guard must be reflected downstream. `model_arm.guard` is read in
two places — the cache write (`:2843`) and the child arm's guard list
(`:2878-2880`). The simplest safe approach is to mutate the validated model
before appending:

```python
if guard != model_arm.guard:
    model_arm = model_arm.model_copy(update={"guard": "true"})
valid.append((model_arm, spans))
```

`model_copy` keeps the cached payload consistent with what was actually used.
(Pydantic v2 — confirmed by the `ConfigDict` / `model_validator(mode="after")`
API already in use in `models.py`.)

**Risk:** low-medium. This admits arms that were previously discarded, so an
arm that a guard would have excluded can now appear. It never invents a value —
the bindings are unchanged and still evidence-checked. If you want to keep the
provenance visible, also record it: `metadata["guard_dropped"] = True` in
`_fact_from_transfer_binding`. Recommended.

---

### Phase 3 — Recover destroyed information and unblock structural dead ends

Run these after Phase 0 tells you which ones actually matter in your codebase.

---

#### Fix 3.1 — Keep the traced expression on UNKNOWN bindings (P17)

**Recommended (zero risk) version.** In `_fact_from_transfer_binding`
(`value_flow/resolver.py:3049-3050`), leave `value` alone and record the text
in metadata:

```python
else:
    value = "UNRESOLVED"
    origin = "RECURSIVE" if binding.text == "RECURSIVE" else "UNRESOLVED"
    if binding.text not in {"RECURSIVE", "UNRESOLVED", "missing argument",
                            "HANDLE_AMBIGUOUS"}:
        metadata_extra = binding.text     # applied to `metadata` below
```

then add `metadata["unresolved_expr"] = metadata_extra` where `metadata` is
built (~3052-3062).

This changes no CSV column and no downstream contract, but the expression stops
being lost — you can immediately measure how many "UNRESOLVED" rows actually
carry a perfectly good source expression.

**Aggressive version — only after reviewing that number.** Emit the expression
as the value with `origin_kind="EXTERNAL_DATA"`, matching what
`_resolve_expression` already does at `value_flow/resolver.py:1284-1298`. This
*does* change the `target_number->ans` column in the legacy CSV, so it needs a
downstream check first. Gate it behind an env var
(`TRACER_VALUEFLOW_EXTERNAL_UNKNOWN=1`) so it can be turned on and off without
a code change.

---

#### Fix 3.2 — Do not let an unrelated macro site poison an arm (P14)

**File: `value_flow/resolver.py:2928-2931`.** Move the guard after `indexes` is
computed:

```python
site = self.sites.get(edge.site_id)
if site is None:
    return None
indexes = { ... }          # unchanged
indexes.update( ... )      # unchanged
if site.macro_args_unmapped and indexes:
    # Positions through this macro are untrustworthy, but only matters if
    # this arm actually reads an argument position.
    return None
```

**File: `value_flow/resolver.py:3266-3268`.** Match the callback branch:

```python
substituted = self._substitute_arm(child, edge)
if substituted is None:
    terminal.append(
        self._mark_external_or_unknown(
            child, external=True,
            parameter_names=tuple(current_function.parameters),
        )
    )
    continue
```

**Risk:** low. The second edit converts UNKNOWN → EXTERNAL_ENTRY *only* for
bindings that are a placeholder or a formal-parameter name —
`_mark_external_or_unknown` already applies that test internally
(`value_flow/resolver.py:2988-2997`). Everything else still becomes UNKNOWN.

---

#### Fix 3.3 — Two candidate opens should be two arms, not a dead end (P13)

**File: `value_flow/resolver.py:3327`.**

```python
bindings = self._binding_opens(current_id, root, before, dependencies)
if len(bindings) == 1:
    return bindings[0]
```

The minimal, low-risk step is *not* to restructure `_opening_for_route` (it
returns a single site and three call sites depend on that). Instead add a
sibling that returns the list, and use it only in `_resolve_seed_with_transfers`:

```python
def _openings_for_route(self, seed, route, dependencies) -> list[IndexedSite]:
    """Every candidate open, where _opening_for_route requires exactly one."""
```

— a copy of `_opening_for_route` whose first branch is
`if bindings: return bindings` and whose failure paths return `[]`. Then in
`_resolve_seed_with_transfers` (~3459-3477) iterate the returned list, creating
one `effective` entry per opening. `_route_for_opening` already takes a single
opening, so nothing else changes.

**Risk:** medium — it increases row count for handle targets (each opening
becomes its own correlated arm, which is the correct representation). Confirm
`_deduplicate_records` and `_legacy_rows` grouping behave as expected before
enabling. Consider gating behind an env var for the first run.

**Do not attempt this before Fix 0.1** tells you how many seeds are hitting
`HANDLE_AMBIGUOUS`; if the number is small it is not worth the risk.

---

#### Fix 3.4 — `_macro_call_arguments` must not claim an empty list is reliable (P15)

**File: `value_flow/resolver.py:648`.**

```python
if arguments is None:
    return [], False        # was: return [], True
```

An empty argument list is not a usable mapping, and marking it reliable causes
`initial_route_arm` to emit `"missing argument"` with no model call. Marking it
unreliable routes the site through the macro path instead.

**Risk:** low, but it changes which sites are `macro_args_unmapped`. Land it
together with Fix 3.2, which softens what that flag costs.

---

### Phase 4 — Speed

---

#### Fix 4.1 — Build the request only on a cache miss (P3)

**File: `value_flow/resolver.py`, `request_local_transfer` (~2790-2830).**

Reorder so the cache lookup happens before the expensive construction. This is
safe because **`_validate_transfer_answer` does not use its `request`
parameter** — verified: no reference to `request` appears anywhere in its body
(`:2685-2764`). Keep the parameter for signature stability, or pass `None` on
the cache-hit path.

Order becomes: compute `constants` and `macro_context` → `macro_digest` →
`function_text, function_base = self._function_slice(...)` → `key` → cache
lookup → construct `TransferRequest` **only if** it is a miss.

`function_text` is still needed for the key, so the slice stays before the
lookup — but after Fix 2.1 that is a function-sized slice, not a whole file, so
the cost is already an order of magnitude lower.

**Additionally**, memoise the slice per function:

```python
self._function_slice_cache: dict[str, tuple[str, int]] = {}   # in __init__
```

with a lookup at the top of `_function_slice`. Function sources do not change
during a run.

**Risk:** low. Pure reordering plus a memo on immutable data.

---

#### Fix 4.2 — Keep the transfer cache across file edits (P21)

**File: `value_flow/resolver.py`, `_load_cache` (~988-1018).**

Restructure so the fingerprint gates only the query results, not the transfer
cache:

```python
payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
if payload.get("schema_version") != 3:
    return
# Transfer entries are self-validating: make_transfer_cache_key already
# digests the function slice, the selected site source, the prompt version
# and the model id. A change to an unrelated file cannot produce a false hit,
# so these survive a project fingerprint change.
self.transfer_cache = {
    str(key): value
    for key, value in (payload.get("transfer_cache") or {}).items()
    if isinstance(value, dict)
}
if payload.get("fingerprint") != self.cache_fingerprint:
    return
self.results = {...}          # unchanged from here
```

**Risk:** low **once Fix 2.2 has landed.** Before Fix 2.2 the key digests the
whole file, so this change would be safe but nearly useless. After it, the key
digests only the function, so an edit elsewhere in the same file correctly
keeps the hit. This ordering matters — do not land 4.2 before 2.2.

**Verification:** run twice, edit one unrelated function, run a third time;
`transfer_cache_hits` should stay high on the third run.

---

#### Fix 4.3 — Memoise `routes_for_seed` (P22)

**File: `value_flow/resolver.py:2437`.**

```python
def routes_for_seed(self, seed: Seed) -> list[RouteGuide]:
    key = (seed.site.site_id, seed.local_backwalk)
    cached = self._route_cache.get(key)
    if cached is not None:
        return cached
    ...
    routes = sorted(routes, key=lambda item: item.route_id)
    self._route_cache[key] = routes
    return routes
```

with `self._route_cache: dict[tuple[str, bool], list[RouteGuide]] = {}` in
`__init__`.

**Risk:** none. `RouteGuide` is a frozen dataclass and the result depends only
on immutable index state. Callers do not mutate the returned list — confirm
that at the five call sites (`:3363, 3423, 3459, 3483, 3486`); if any does,
return `list(routes)` instead.

---

#### Fix 4.4 — Memoise `_transfer_visible_names` (P23)

**File: `value_flow/resolver.py:2552`.** Add a dict cache keyed by file name.
Fix 2.4 already hoists it to one call per arm; this makes the remaining calls
free.

**Risk:** none. Macro and enum indexes are built once in `__init__`.

---

#### Fix 4.5 — Stop the transfer prompt from running an agentic tool loop (P24)

**File: `client/llm.py:465-471`.** Build the kwargs conditionally so a caller
that passes no tools gets a single completion instead of a loop:

```python
create_kwargs = {
    "model": self.model,
    "messages": self.messages,
    "temperature": self.temp,
}
if self.tools:
    create_kwargs["tools"] = self.tools
    create_kwargs["tool_choice"] = "auto"
response = self.client.chat.completions.create(**create_kwargs)
```

**File: `project_aware.py`, `llm_calls_transfer` (~721-731).** Pass no tools:

```python
"tools": None,
"tool_functions": {},
```

The system prompt already says "Analyze only the selected function and selected
outgoing call … Do not select another call site and do not follow callers", so
the tools were never appropriate for this prompt. With no tools the model
answers on the first turn, `msg.tool_calls` is empty, and the loop falls
straight through to the formatting stage.

**Risk:** medium — `client/llm.py` is shared with the legacy one-hop and
return-use prompts. The guard is `if self.tools:`, so those callers (which pass
real tools) hit exactly the code path they hit today. Verify by checking that
`resolve_return_use` and the one-hop resolver still pass a non-empty
`TOOL_DEFINITION`.

**Expected effect:** one round trip instead of up to 100, per hop.

---

#### Fix 4.6 — Stop injecting the legacy scalar contract into transfer prompts (P25)

**File: `client/llm.py:513`.**

```python
if self.output_model.__name__ not in {"outputModelForReturn", "TransferAnswerModel"}:
    format_prompt_content += """ ... 1:value,2:value ... """
elif self.output_model.__name__ == "outputModelForReturn":
    format_prompt_content += ("- **YOU JUST HAVE TO RETURN WHETHER ...")
```

Today the condition is `!= "outputModelForReturn"`, which is **true** for
`TransferAnswerModel`, so every transfer request is told to answer
`1:value,2:value`, to write `UNRESOLVED` when unsure, and not to return a list —
while being handed the `arms: [...]` schema.

**Risk:** none. It removes instructions that are wrong for this schema.
**This is a one-line change and is probably the single highest
value-per-character fix in the document.** Land it in Phase 0 if you want an
early signal.

---

#### Fix 4.7 — Replace fork-per-hop with a direct call (P20) — deferred

`run_with_retry` (`project_aware.py:812`) forks a process per LLM hop, with a
600 s join and 2 retries, and has a pipe-capacity hazard that can kill a
successful answer and record it as a timeout.

This is a real cost, but it is **not a minimal change** — `run_with_retry` is
shared by every LLM entry point and the fork context is deliberate
(`project_aware.py:770-780`: the child inherits the `State()` singleton). Do
not touch it in the same batch as everything above.

If Phase 0 shows a significant `llm_exception` or timeout count, the smallest
safe intervention is to lower the transfer-specific timeout — pass
`timeout=120` from `resolve_transfer` (`project_aware.py:1786-1790`) rather
than inheriting the 600 s default. A transfer prompt that has not answered in
two minutes is not going to.

---

## Part 3 — Deliberately not doing

- **Widening the formula grammar (P10).** It is a real limitation, but it is
  the change most likely to admit wrong answers, and Phase 0 will show whether
  it is still the binding constraint after the prompt is fixed. Revisit with
  data. If you do proceed, add node types one at a time in this order:
  `field_expression`, `subscript_expression`, `conditional_expression`,
  `pointer_expression` — each treated as an opaque named leaf that yields
  EXTERNAL rather than an evaluated value.
- **Normalising the literal/evidence check (P11).** Correct, but it interacts
  with the widened spans from Fix 1.1 step 4. Do it after, not with.
- **Fixing `_build_function_index` name-only matching (P12).** The real fix is
  to match on name *and* line range, which touches the index everything else is
  built on. Fix 0.3 measures it first; only act if the count is non-trivial.
- **`_legacy_rows` group-dropping (P18)** and **the `start_byte`/ordinal
  fallback (P16).** Both real, both narrow, neither on the UNRESOLVED critical
  path. Log them and move on.
- **Removing the prose→JSON second pass (P24, second half).** Fix 4.5 removes
  the tool loop, which is the expensive half. Removing the second pass means
  moving to native structured output, which is a larger change to a shared
  client.

---

## Part 4 — Sequencing and verification

Land in this order. Each step is independently revertable.

| Step | Fixes | Expected signal |
|---|---|---|
| 0 | 0.1–0.4, **4.6** | Rejection histogram exists; RECURSIVE counts become truthful |
| 1 | 1.1–1.4 | `schema_invalid` and `no_current_span` collapse; UNRESOLVED drops |
| 2 | 2.1–2.4 | Prompt tokens per hop drop 10–100×; prefill time drops |
| 3 | 3.1, 3.2, 3.4 | UNRESOLVED reclassified as EXTERNAL_*; `unresolved_expr` populated |
| 4 | 4.1–4.4 | Wall-clock drop on re-runs; cache hit rate stays high after edits |
| 5 | 4.5 | One model round trip per hop |
| 6 | 3.3, then reassess P10/P11/P12 | Handle-target coverage |

**Before starting**, capture a baseline on one representative process:

- total facts by `origin_kind` (UNRESOLVED / RECURSIVE / EXTERNAL_* / CONST / MACRO)
- `transfer_request_count`, `transfer_cache_hits`, `transfer_cache_misses`
- wall-clock, and mean prompt tokens per transfer (from `record_stats`)

Re-measure after each step. The `origin_kind` histogram is the number to watch:
success is UNRESOLVED shrinking while CONST/MACRO stay accurate and
EXTERNAL_ENTRY/EXTERNAL_DATA grow — an expression that is honestly external is
a useful answer; "UNRESOLVED" is not.

**Regression suite to run at every step:**

```
tests/test_llm_transfer_value_flow.py     # transfer contract + fake resolvers
tests/test_valueflow_pipeline.py
tests/test_value_flow.py
tests/test_no_target_pipeline.py
```

`tests/test_llm_transfer_value_flow.py` is the one that guards this surface —
its fake resolvers exercise the evidence path directly (`:67-78`, `:318-319`,
`:434`, `:465`, `:495`). If Fix 2.1 breaks it, the cause is the offset
convention and Fix 1.1 step 2 is what is meant to absorb it; check that first
before changing any test.

**Cache note:** Fix 2.2 bumps `transfer_prompt_version` to
`valueflow-transfer-v2`. The first run after Phase 2 is a full cache miss by
design. Do not interpret it as a regression.

---

# Part 5 — Remaining work (P10–P24), implementation-ready

Part 3 listed these as "deliberately not doing" and gave only sketches. This
part turns them into specs the implementer can execute.

## 5.0 — Two corrections that change the priorities

**Correction 1: P10 is much smaller than it looked.**

`_validate_transfer_answer` grammar-checks only two things: the **guard**, and
**EXPRESSION** bindings. An **EXTERNAL** binding is *not* passed through
`validate_formula` at all — it is only checked for "not a literal" and
"placeholder indices in range" (`value_flow/resolver.py:2897-2911`).

So a model that wants to report `cfg->sensor.raw_pressure` can already do so
today, as `kind: "EXTERNAL"`, and it validates. The prompt already directs it
there: *"Do not use local variable names in a completed EXPRESSION: resolve
them or return EXTERNAL/UNKNOWN."*

And Fix 2.4 already made an inexpressible **guard** non-fatal.

What is left of P10 is therefore narrow: only an **EXPRESSION** binding — a
value the model wants the coordinator to keep tracing — is still grammar-bound.
Check `transfer_rejections["binding_formula"]` before doing 5.4 at all. If it is
small, P10 is a non-issue and 5.4 should be skipped.

**Correction 2: the headline UNRESOLVED count cannot move without 5.5.**

Fix 3.1 only added `metadata["unresolved_expr"]`. The `value` column still reads
`"UNRESOLVED"`. Every other fix changes *whether* a hop resolves; only 5.5
changes how an unresolved-but-known expression is *reported*. If the goal is
"fewer UNRESOLVED rows in the CSV", 5.5 is the fix that does it.

## 5.1 — Design rule for this part: default to today's behaviour

Everything in Part 5 that can change a resolved value is behind an environment
flag that **defaults to off**. With no flags set, the pipeline behaves exactly
as it does after Part 2. That is what makes this batch safe to land unmeasured:
it is inert until switched on, and tuning is flag-flipping, not editing.

| Flag | Default | Fix | Effect when on |
|---|---|---|---|
| `TRACER_VF_GRAMMAR_EXTENDED` | off | 5.4 | EXPRESSION may use field/index/deref/ternary as opaque leaves |
| `TRACER_VF_EXTERNAL_UNKNOWN` | off | 5.5 | UNKNOWN bindings report their expression instead of `"UNRESOLVED"` |
| `TRACER_VF_MULTI_OPEN` | off | 5.6 | Several candidate opens become several arms |
| `TRACER_VF_KEEP_PARTIAL_ROWS` | off | 5.7 | Legacy CSV keeps groups whose indices are incomplete |
| `TRACER_VF_TRANSFER_TIMEOUT` | `120` | 5.3 | Per-hop model timeout in seconds |

Read every flag **once**, in `ValueFlowResolver.__init__` (or
`make_value_flow_calls` for the two that live outside the resolver), into a
plain attribute. Never call `os.environ` inside a hot path, and never let a flag
change a cache key's meaning — see 5.4 for the one case where it must.

Fixes 5.2, 5.3, 5.8 are unflagged: they are strictly corrective.

---

## 5.2 — P12: match function definitions by name *and* line range

**File:** `value_flow/resolver.py`, `_build_function_index` (~470-490).

Today the match is name-only, first hit wins:

```python
for candidate in definitions_by_file.get(function_node.file_name, []):
    name = _extract_declarator_identifier(candidate.child_by_field_name("declarator"), source)
    if name == function_node.name:
        ast_node = candidate
        break
```

Two failures: a `static` and an external function sharing a name in one file
bind to the same node, and a definition Tree-sitter did not shape as a plain
`function_definition` binds to nothing at all (`parameters = []`, which fails
every downstream transfer — see P12).

Replace the loop with a two-pass match. `FunctionNode.start_line` /
`end_line` exist (`call_graph/data_classes.py:23-24`) and are 1-based, with
`-1` meaning unknown.

```python
candidates = []
for candidate in definitions_by_file.get(function_node.file_name, []):
    name = _extract_declarator_identifier(
        candidate.child_by_field_name("declarator"), source
    )
    if name == function_node.name:
        candidates.append(candidate)

ast_node = None
if len(candidates) == 1:
    ast_node = candidates[0]
elif candidates:
    # Several same-named definitions in one file: pick the one whose byte
    # range contains the registry's recorded start line. Name alone would
    # bind a static and an extern of the same name to the same body.
    start = function_node.start_line
    if start > 0:
        for candidate in candidates:
            first = candidate.start_point.row + 1
            last = candidate.end_point.row + 1
            if first <= start <= last:
                ast_node = candidate
                break
    ast_node = ast_node or candidates[0]     # preserve today's fallback
```

**Do not** add a fuzzy fallback for the "no candidate at all" case in this pass.
Fixing *that* means understanding why Tree-sitter did not produce a
`function_definition`, which is a preprocessing question, not an indexing one.
Keep the Fix 0.3 warning and use its count to decide whether it is worth
chasing.

**Risk:** low. With one candidate the behaviour is byte-identical to today. With
several it becomes more correct. With none it is unchanged.

**Verify:** the Fix 0.3 warning count should not increase. If your codebase has
same-named statics, spot-check that two such functions now get distinct
`parameters`.

---

## 5.3 — P20: a transfer-specific timeout

**File:** `project_aware.py`, `resolve_transfer` (~1789-1795).

`run_with_retry` defaults to `timeout=600, retries=2` — up to 20 minutes on one
hop before it returns `None` and the binding becomes UNRESOLVED. A transfer
prompt that has not answered in two minutes is not going to.

`loop.run_in_executor` takes no keyword arguments, so bind them with `partial`
(already imported, `project_aware.py:16`):

```python
result = await loop.run_in_executor(
    llm_executor,
    partial(run_with_retry, timeout=transfer_timeout, retries=2),
    llm_calls_transfer,
    (project_structure, request),
)
```

with, once, near the other environment reads in `make_value_flow_calls`:

```python
transfer_timeout = int(os.environ.get("TRACER_VF_TRANSFER_TIMEOUT", "120"))
```

**Do not** touch `run_with_retry` itself. It is shared with every other LLM
entry point, and its `fork` context is deliberate — the child inherits the
`State()` singleton (`project_aware.py:770-780`). Replacing fork-per-hop with a
direct async call is the right end state but is not a minimal change and does
not belong in this batch.

**Risk:** low, and reversible without a code change by raising the env var.
Note it can *increase* UNRESOLVED if your endpoint is genuinely slow — watch
`transfer_rejections["llm_returned_none"]` after enabling.

---

## 5.4 — P10: extended grammar as opaque leaves (flagged)

**Read 5.0 first.** Only do this if `binding_formula` is a material fraction of
rejections.

The safety property that makes this benign: an extended node is accepted by
`_validate_node` but is **never evaluable**. `evaluate_formula`'s inner
`evaluate()` returns `None` for any node kind it does not handle
(`value_flow/transfers.py`, final `return None`), so `ok` is `False`,
`_settle_transfer_arm` leaves the binding as `EXPRESSION`, and it can never
become an `EXACT` numeric fact. Widening the grammar therefore cannot produce a
wrong number — it can only let the model *name* a source it currently cannot
name.

**File A: `value_flow/transfers.py`, `validate_formula` / `_validate_node`.**

Thread one flag through:

```python
def validate_formula(
    formula: str,
    *,
    parameter_count: int,
    visible_names: set[str] | None = None,
    evidence_texts: tuple[str, ...] = (),
    allow_boolean_literals: bool = False,
    allow_opaque: bool = False,          # new, defaulted
) -> tuple[dict[str, int], tuple[str, ...]]:
```

and in `_validate_node`, immediately before the final
`raise FormulaError(f"unsupported expression node {node_type}")`:

```python
_OPAQUE_NODES = {
    "field_expression",        # cfg->mode, cfg.mode
    "subscript_expression",    # table[i]
    "pointer_expression",      # *p, &x
    "conditional_expression",  # a ? b : c
}

if allow_opaque and node_type in _OPAQUE_NODES:
    # An opaque leaf: the model may NAME this source, but the expression is
    # deliberately not evaluable, so it can never become an EXACT value.
    # Do not identifier-check the children -- `cfg` in `cfg->mode` is a local
    # and is not in visible_names by design. Only collect nested literals so
    # they still have to be covered by evidence.
    for descendant in _walk(node):
        if descendant.type in {"number_literal", "char_literal", "string_literal"}:
            text = _node_text(descendant)
            if _literal_value(text) is not None:
                literals.append(text)
    return
```

`_validate_node` must accept and forward `allow_opaque` on each of its recursive
calls (parenthesized, unary, binary).

Deliberately **not** included: `call_expression`. A call has side effects and an
unknown return; naming it as a value source is misleading, and `UNKNOWN` is the
honest answer.

**File B: `value_flow/resolver.py`.**

```python
self.allow_opaque_formula = os.environ.get("TRACER_VF_GRAMMAR_EXTENDED") == "1"
```

in `__init__`, passed as `allow_opaque=self.allow_opaque_formula` at the
**EXPRESSION binding** call site only (`~2892`). Leave the guard call site
(`~2875`) alone: Fix 2.4 already made guard failure non-fatal, so widening there
buys nothing and only weakens a check.

**Cache-key interaction — important.** The flag changes which answers validate,
so an answer cached with the flag on must not be served with it off. Fold it
into the prompt version rather than inventing a new key input:

```python
transfer_prompt_version="valueflow-transfer-v2"
    + ("-opaque" if resolver_flags.grammar_extended else "")
```

Simplest correct placement: compute it in `make_value_flow_calls` where the
version string is already passed (`project_aware.py:1906`).

**Risk:** low for correctness of EXACT values (impossible by construction),
moderate for output shape — more bindings stay `EXPRESSION` longer and reach
the caller, so expect more hops. Watch `transfer_request_count`.

---

## 5.5 — P17: report the expression instead of `"UNRESOLVED"` (flagged)

**This is the fix that moves the headline number.**

**File:** `value_flow/resolver.py`, `_fact_from_transfer_binding` (~3238-3245).

`_mark_external_or_unknown` already preserves the substituted expression in
`binding.text`; Fix 3.1 put it in `metadata["unresolved_expr"]`. This promotes
it to the value, matching what the legacy engine already does for the same
situation (`value_flow/resolver.py:1284-1298`).

```python
else:
    sentinel = binding.text in {
        "RECURSIVE", "UNRESOLVED", "missing argument", "HANDLE_AMBIGUOUS",
    }
    if self.external_unknown and not sentinel and binding.text.strip():
        # An expression we could not trace further is still an answer: the
        # legacy engine reports it as EXTERNAL_DATA rather than discarding it.
        value = binding.text
        origin = "UNKNOWN_INDIRECT" if "(*" in binding.text else "EXTERNAL_DATA"
    else:
        value = "UNRESOLVED"
        origin = "RECURSIVE" if binding.text == "RECURSIVE" else "UNRESOLVED"
```

with `self.external_unknown = os.environ.get("TRACER_VF_EXTERNAL_UNKNOWN") == "1"`
in `__init__`. Keep `metadata["unresolved_expr"]` populated either way, so the
two modes stay comparable.

**Before enabling, check the downstream consumers**, because this changes the
`value` column and therefore `target_number->ans` in the legacy CSV:

- `value_flow/outputs.py:169-172` joins values with `_` for multi-index targets.
  An expression containing `_` or spaces will appear there.
- `rehydrate_interactions` and anything else reading `<process>.csv`.
- Any dashboard filtering on `value == "UNRESOLVED"` or
  `origin_kind == "UNRESOLVED"`.

The flag exists precisely so you can diff one process's CSV both ways before
committing to it.

**Risk:** none to correctness — an `EXTERNAL_DATA` fact is explicitly *not* an
exact value and is already an existing `OriginKind` (`value_flow/queries.py`).
The risk is entirely downstream formatting.

---

## 5.6 — P13: several candidate opens become several arms (flagged)

**File:** `value_flow/resolver.py`.

`_opening_for_route` (~3327) requires `len(bindings) == 1` and returns `None`
for zero *or* two-plus, which makes the whole seed `HANDLE_AMBIGUOUS`
(~3694). Two opens in an if/else on the same FCB is ordinary C.

Do **not** restructure `_opening_for_route` — three call sites depend on its
single-site return. Add a sibling:

```python
def _openings_for_route(self, seed, route, dependencies) -> list[IndexedSite]:
    """Every candidate open, where _opening_for_route requires exactly one.

    A handle written by two branches has two legitimate origins; the engine
    already represents alternatives as separate correlated arms.
    """
```

It is `_opening_for_route` with two changes: `if bindings: return bindings`
instead of `if len(bindings) == 1: return bindings[0]`, and every `return None`
becomes `return []`.

Then in `_resolve_seed_with_transfers` (~3459-3477), when the flag is on, call
it and append one `effective` entry per opening. `_route_for_opening` already
takes a single opening, so nothing downstream changes:

```python
openings = (
    self._openings_for_route(seed, consumer_route, dependencies)
    if self.multi_open
    else [o for o in [self._opening_for_route(seed, consumer_route, dependencies)] if o]
)
for opening in openings:
    effective_route = self._route_for_opening(consumer_route, opening)
    ...
```

**Risk:** medium — row count rises for handle targets, and each opening becomes
its own correlated arm. Confirm `_deduplicate_records` (~4346, keyed partly on
`correlation_id`) and `_legacy_rows` grouping produce what you expect before
trusting the output. This is the item most worth leaving off until measured.

---

## 5.7 — P18: stop silently dropping legacy rows (flagged)

**File:** `value_flow/outputs.py:157-163`.

```python
if expected and set(ordered_indices) != expected:
    continue
```

A correlated group whose indices do not exactly equal the configured `indices`
vanishes from the legacy CSV — so a target invocation can be missing rather
than unresolved, which is worse for triage than an honest UNRESOLVED.

```python
if expected and set(ordered_indices) != expected:
    if not keep_partial_rows:
        continue
    # Emitting a partial bundle is more honest than dropping the invocation:
    # a missing row is indistinguishable from a target that was never found.
```

`keep_partial_rows` is read once in `write_outputs` / `_legacy_rows`'s caller
and threaded down as a parameter — do not read the environment inside the row
loop.

**Risk:** low, but it changes row counts in the legacy CSV, which is why it is
flagged. Note Fix 1.3 (partial arms) makes this case more common than it was.

---

## 5.8 — P16: stop using a list ordinal as a byte offset

**File:** `value_flow/resolver.py`, `_build_call_index` (~700-706).

```python
start_byte = (
    call_site.start_byte
    if call_site.start_byte >= 0
    else (ast_node.start_byte if ast_node is not None else ordinal)
)
```

That final `ordinal` is a list index standing in for a byte offset. It yields a
`site_id` that collides with a real offset, a meaningless
`SELECTED OUTGOING CALL (n:m)` in the prompt, and an empty
`selected_site_source` slice in the cache key.

The `site_id` format cannot change without invalidating caches and outputs, so
keep the ordinal as the *identity* fallback but stop presenting it as a byte
range. Add one field to `IndexedSite`:

```python
byte_range_known: bool = True
```

set to `False` on exactly that fallback path. Then in `request_local_transfer`,
when it is `False`, send `selected_call_start_byte=-1`,
`selected_call_end_byte=-1`, and have the prompt render "(byte range unknown)"
instead of a fake range. The snippet-based evidence from Fix 1.2 already
works without offsets, so nothing else needs to change.

**Risk:** low and narrow. Confirm how often it fires first — add
`self.transfer_rejections["site_without_bytes"]` at the fallback and check
whether the count is non-zero before spending time here.

---

## 5.9 — P24: remove the prose→JSON second pass (last, largest)

Fix 4.5 removed the tool loop, which was the expensive half. What remains: when
the model answers, `client/llm.py:494-560` makes a **second** model call to
convert prose into JSON, with up to 5 retries. Every transfer hop is still two
round trips, and structured fields still traverse a prose intermediary.

The correct fix is native structured output —
`client.chat.completions.parse(..., response_format=self.output_model)` on the
first call, falling back to the existing path when the endpoint does not support
it. That is a real change to a client shared by three prompts, so:

- gate it on `TRACER_VF_STRUCTURED_OUTPUT=1`;
- apply it only when `self.output_model is TransferAnswerModel`, leaving the
  legacy prompts on today's path entirely;
- keep the existing prose→JSON code as the `except` fallback, so an endpoint
  that rejects `response_format` degrades instead of failing.

Do this **after** everything above has been measured. It is the largest
remaining latency win and the change most likely to break an endpoint.

---

## 5.10 — Order and gates

| Step | Fix | Gate before doing it |
|---|---|---|
| 1 | 5.2 (P12 indexing), 5.3 (timeout), 5.8 (P16) | none — corrective |
| 2 | 5.5 (P17) **flag off**, land the code | none; enable only after a CSV diff |
| 3 | 5.7 (P18) **flag off** | none |
| 4 | 5.6 (P13) **flag off** | enable only if `HANDLE_AMBIGUOUS` count is material |
| 5 | 5.4 (P10) **flag off** | enable only if `binding_formula` count is material |
| 6 | 5.9 (P24) | after a measured baseline exists |

Land steps 1–5 in one batch if you like: with every flag off, the only live
changes are the three corrective ones, so the batch is inert by construction.
Then tune by flipping flags one at a time and diffing `facts.csv`.

**P11 (literal/evidence substring matching) is still deferred**, and now for a
specific reason: Fix 1.1's step 4 widens a degenerate span to its whole line,
which already makes literal coverage more permissive. Normalising `0x10` against
`16` on top of that compounds two relaxations of the same check. Measure the
false-positive rate on literals first.

---

# Part 6 — Closing status

P11 and P20 (the two Part 3/Part 5 deferrals) are now implemented. Every
problem in the Part 1 inventory is addressed.

## 6.1 — P11: literal grounding is now value-based, not spelling-based

**File:** `value_flow/transfers.py`, `validate_formula`.

The exact-substring check runs first and is unchanged. Only when it fails does
the check fall back to comparing integer **values**: the literal is parsed with
`_literal_value`, and the evidence is scanned by `_EVIDENCE_LITERAL` for
integer and character literals in any C base, parsed the same way.

`0x10` now matches evidence spelling `16`, `1U` matches `1`, and `10` matches
`'\n'`. An ungrounded number still has no matching value and still fails.

This was deferred in 5.10 out of concern that it compounds Fix 1.1's
line-widening. On implementation that concern does not hold: the widened span
already admits every literal spelled on that line, and this change only removes
a *spelling* artifact from a check that was always meant to be about the
number. It is a bug fix, not a second relaxation.

## 6.2 — P20: the fork per hop is now bypassable

Two changes, the first unflagged and the second gated.

**`client/llm.py`, `OllamaClient.__init__`** — the OpenAI client now accepts
`data["timeout"]` and, when given, passes `timeout=` and `max_retries=0`.
Callers that pass nothing are unaffected. `llm_calls_transfer` passes
`TRACER_VF_TRANSFER_TIMEOUT` (default 120s).

This matters on its own: the SDK default is what made a hung call unstoppable,
which is the reason `run_with_retry` forks and terminates in the first place.
With the request bounded, the fork is no longer load-bearing for the transfer
path.

**`project_aware.py`, `resolve_transfer`** — with `TRACER_VF_NO_FORK=1`,
`llm_calls_transfer` runs directly on the LLM thread pool instead of through
`run_with_retry`. A raised exception is caught by
`ValueFlowResolver._await_llm` and counted as `llm_exception`, exactly as a
fork failure is today.

`run_with_retry` itself is still untouched, as the plan required — the legacy
one-hop and return-use prompts keep forking.

**Why this is flagged rather than default-on:** it changes crash-isolation
semantics for the transfer path, and it cannot be validated without a live
endpoint. Enable it once a real run confirms the timeout behaves, then it is
the single largest remaining latency and memory win: no forked child per hop,
each of which copy-on-writes a parent holding every tree, AST and registry.

## 6.3 — Final flag table

| Flag | Default | Fix | Effect when on |
|---|---|---|---|
| `TRACER_VF_GRAMMAR_EXTENDED` | off | 5.4 | EXPRESSION may use field/index/deref/ternary as opaque leaves |
| `TRACER_VF_EXTERNAL_UNKNOWN` | off | 5.5 | UNKNOWN bindings report their expression instead of `"UNRESOLVED"` |
| `TRACER_VF_MULTI_OPEN` | off | 5.6 | Several candidate opens become several arms |
| `TRACER_VF_KEEP_PARTIAL_ROWS` | off | 5.7 | Legacy CSV keeps groups whose indices are incomplete |
| `TRACER_VF_STRUCTURED_OUTPUT` | off | 5.9 | Transfer prompt parses natively; falls back to prose→JSON |
| `TRACER_VF_NO_FORK` | off | 6.2 | Transfer prompt runs in-thread instead of forking |
| `TRACER_VF_TRANSFER_TIMEOUT` | `120` | 5.3 / 6.2 | Per-hop model timeout, seconds |

With no flags set, behaviour equals the end of Part 2 plus the unflagged
corrective fixes. Tuning is flag-flipping, not editing.

## 6.4 — What is verified, and what is not

**Verified:** the full suite passes identically (183 passed / 5 pre-existing
unrelated failures) with every flag off *and* with every flag on. `_repair_span`
and the P11 value check were exercised directly against their edge cases.

**Not verified, and cannot be here:** no part of this has run against a real
project with a live model. Every recall claim remains a hypothesis until
`transfer_rejections` and the `origin_kind` histogram are read from a real run.
That measurement is still the next step, and it is what should decide which
flags to enable.

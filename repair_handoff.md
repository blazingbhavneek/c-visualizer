# Deferred full-index repair

The current aggregate index is intentionally left unchanged. The comparison
uses the existing artifacts under `results/csv_results/index/`, which contain
383 of 385 discovered processes. The missing processes are:

- `dyn811d` — `/home/chukyu/t-dyn/src/dyn811d`
- `dyn830` — `/home/chukyu/t-dyn/src/dyn830`

The saved batch manifest records `maximum recursion depth exceeded` for both.

## Reproduction notes

The normal batch should not be rerun just to repair these two processes. Retry
each process individually after fixing the issues below, then rebuild the
aggregate overlay from all available per-process `index/` directories.

During a bounded retry of `dyn811d` with a temporary recursion-limit increase,
two additional defects appeared before value-flow tracing:

1. `makefile_resolver/extract_includes.py:220` assumes
   `extract_includes(current_path)` is iterable. It can return `None` for a
   legacy/encoding-heavy file.
2. `project_aware.py:2293` assumes every dependency in
   `PROJECT_STRUCTURE` has a parsed Tree-sitter entry. `dyn811d` discovers
   `ARMTargetParser.def`, which is not C/H source and is absent from `trees`,
   causing `KeyError: 'ARMTargetParser.def'`.

The temporary guards used to diagnose these were reverted. They were not part
of the comparison change.

## Suggested repair order

1. Make include resolution treat a `None` preprocessing result as an empty
   include list while preserving the source in the project map.
2. Skip project dependencies absent from `trees` when collecting C function
   definitions; keep parsed headers/source files unchanged.
3. Replace the recursive call-tree/path conversion with an iterative walk, or
   add cycle/depth handling at the point that constructs the `dyn811d` and
   `dyn830` trees. A process-wide recursion-limit increase is only a diagnostic
   workaround.
4. Retry only `dyn811d` and `dyn830` with the same target spec and resolver:

   ```bash
   .venv/bin/python project_aware.py \
     --project /home/chukyu/t-dyn/src/dyn811d \
     --targets target_specs/build_index_targets.json \
     --source-root /home/chukyu \
     --resolver valueflow --skip-function-summaries

   .venv/bin/python project_aware.py \
     --project /home/chukyu/t-dyn/src/dyn830 \
     --targets target_specs/build_index_targets.json \
     --source-root /home/chukyu \
     --resolver valueflow --skip-function-summaries
   ```

5. Re-run the aggregate builder only after both per-process indexes exist.
   Do not insert legacy records into the c-visualizer index; that would make
   the comparison invalid.

## Existing comparison command

```bash
.venv/bin/python tools/analyze_index_comparison.py \
  --cvisualizer-index results/csv_results/index \
  --build-index ../index \
  --source-root /home/chukyu \
  --output-dir results/csv_results/analysis
```

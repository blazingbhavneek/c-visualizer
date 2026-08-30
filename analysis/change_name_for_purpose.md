# Project-aware preprocessing with guarded compatibility fallback

## Purpose

Prevent active C code from being misclassified as `UNREACHABLE` when legacy
preprocessor branches leave an invalid or incomplete Tree-sitter parse. The
Step 0 audit identified two concrete patterns:

- dual K&R/ANSI entry-point declarations controlled by `_NO_PROTO`;
- conditional statements split across a braceless `if` controlled by `NOP`.

The change is intentionally scoped to preprocessing. It does not promote
unreachable facts into exact discovery indexes, because genuinely dead code
must remain distinguishable from live code.

## Behavior

1. Compile macro state is read from the selected process Makefile’s
   `CPPFLAGS`, `CFLAGS`, `CCFLAGS`, `CDEFS`, `DEFS`, and `DEFINES` variables.
2. Those `-D` and `-U` values are passed to `unifdef` for that process only.
3. The original preprocessing result is always tried first.
4. If the first C parse contains errors, preprocessing retries with the
   compatibility undefines `_NO_PROTO` and `NOP`, unless the Makefile
   explicitly defines or undefines those symbols.
5. The retry is accepted only when it reduces parse errors and, when entry
   names are supplied, still contains an expected lifecycle definition.
6. Per-file preprocessing metadata records the selected flags, whether the
   fallback was used, and the before/after parse-health counts.

This preserves source line numbers because `unifdef -t` continues to blank
inactive text rather than deleting lines.

## Why this is safer than global flags

`-U_NO_PROTO` and `-UNOP` are not applied blindly to every source file or
project. A clean file is unchanged. A project-defined macro state takes
precedence over the compatibility fallback. A fallback that does not improve
the parse is discarded.

## Validation

`tests/test_preprocess.py` covers:

- the dual-definition `main` pattern;
- the split conditional `if` pattern;
- explicit macro state not being overridden;
- Makefile flag extraction without treating linker flags as preprocessor
  flags.

The remaining callback-dispatch and cross-process-scope items from
`step0_report.md` are separate concerns and should not be solved by weakening
the reachability filter.

from __future__ import annotations

import re
from typing import Any

_OUTER_PARENS = re.compile(r"^\((.*)\)$", re.DOTALL)


def strip_outer_parens(expression: str) -> str:
    """Remove only balanced parentheses surrounding the whole expression."""
    # Value-flow compares expression text in several places.  C code often
    # adds harmless wrapping parentheses, for example `((handle))`.  Remove
    # only parentheses around the WHOLE expression; never change `(a + b)`.
    value = expression.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        balanced = True
        for index, char in enumerate(value):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    balanced = False
                    break
            if depth < 0:
                balanced = False
                break
        if not balanced or depth:
            break
        match = _OUTER_PARENS.match(value)
        if not match:
            break
        value = match.group(1).strip()
    return value


def normalise_handle(expression: str) -> str:
    """Return the stable root object used to pair handle consumers and opens."""
    # This is used by the handle branch of ValueFlowResolver:
    #
    #     open(&fcb, FILE_NO);  ...  close(&fcb);
    #
    # Both calls must become the same key (`fcb`) so the resolver can connect
    # close/read back to its matching open. This helper does not resolve a
    # value; it only answers "are these two handle expressions the same object?"
    value = strip_outer_parens(expression)

    # Address-of syntax is not part of a handle's identity:
    # `fcb`, `&fcb`, and `(&fcb)` all refer to the same root object here.
    while value.startswith("&"):
        value = strip_outer_parens(value[1:])

    # An array element represents the base allocation.  Struct-field identity
    # is deliberately retained: `p->fcb` must not alias `p->other`.
    # Examples: `fcb[slot]` becomes `fcb`; `ctx->fcb` stays `ctx->fcb`.
    value = re.sub(r"\s*\[[^\]]*\]\s*$", "", value)

    # Whitespace should not make `ctx -> fcb` differ from `ctx->fcb`.
    return re.sub(r"\s+", "", value)


def node_text(node: Any, source: bytes) -> str:
    # Tree-sitter nodes carry byte offsets, not their original C spelling.
    # Keep this conversion in one place so resolver code can ask for `x + 1`,
    # `&fcb`, or a macro name directly from an AST node.
    return source[node.start_byte : node.end_byte].decode("latin-1", errors="replace")

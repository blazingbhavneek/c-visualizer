from __future__ import annotations

import re
from typing import Any

_OUTER_PARENS = re.compile(r"^\((.*)\)$", re.DOTALL)


def strip_outer_parens(expression: str) -> str:
    """Remove only balanced parentheses surrounding the whole expression."""
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
    value = strip_outer_parens(expression)
    while value.startswith("&"):
        value = strip_outer_parens(value[1:])
    # An array element represents the base allocation.  Struct-field identity
    # is deliberately retained (``p->fcb`` must not alias ``p->other``).
    value = re.sub(r"\s*\[[^\]]*\]\s*$", "", value)
    return re.sub(r"\s+", "", value)


def node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("latin-1", errors="replace")

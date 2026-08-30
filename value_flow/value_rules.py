"""Small declarative value-flow rules.

Rules describe source patterns the syntax resolver may prove.  They are not
an abstract C interpreter: unknown tables, indices, and wrapper effects stay
external/unresolved.
"""

from __future__ import annotations

from typing import Any


# Names are intentionally narrow.  Table symbols and output values are read
# from the parsed function body, so a rule cannot invent values absent from
# source.  Callers may add fixture/project-specific rules through the resolver
# constructor.
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


def merge_value_rules(extra: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    rules = {name: dict(rule) for name, rule in DEFAULT_VALUE_RULES.items()}
    for name, rule in (extra or {}).items():
        if isinstance(rule, dict):
            rules[str(name)] = dict(rule)
    return rules

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Literal, TypeAlias

# VALUE-FLOW "QUESTION" AND "ANSWER" SHAPES
#
# The resolver uses these small objects while it finds the value passed to a
# configured target API argument. For example, for `pmf_setsem(NAME, 0)`, it
# traces the values of `NAME` and `0`. It walks backward from that target call
# until it finds where each argument value came from. `token()` gives each
# question an ID for the cache.
#
# Normal reverse walk example:
#
#     target(x)  -> ArgQuery(target call, argument 1)
#     x is a parameter of wrapper(x) -> ParamQuery(wrapper, parameter 1)
#     caller wrapper(FILE_NO) -> ArgQuery(wrapper call, argument 1)
#     FILE_NO -> Fact(value=..., origin_kind="MACRO")
#
# Fact is the final answer for one target argument. `value` is the concrete
# value found for that argument, for example `svm300d`, `0`, or `FILE_NO`'s
# macro value. The other fields say where that value came from. The resolver
# also remembers the steps from that source line back to the target call.

OriginKind: TypeAlias = Literal[
    "CONST",
    "MACRO",
    # A source-backed table/wrapper result.  Each value is retained as
    # evidence, but downstream must not treat the set as one exact path.
    "CONST_TABLE",
    "BOUNDED_SET",
    # Model suggestion retained as evidence, never eligible for exact index.
    "LLM_CANDIDATE",
    "EXTERNAL_ENTRY",
    "EXTERNAL_DATA",
    "UNKNOWN_INDIRECT",
    "RECURSIVE",
    "UNRESOLVED",
]


@dataclass(frozen=True, slots=True)
class ArgQuery:
    # ACTUAL argument: "At this one call, what was passed in position N?"
    # Example: for `wrapper(FILE_NO)`, ArgQuery asks about `FILE_NO`.
    # arg_index is 1-based to match the target JSON configuration.
    call_site_id: str
    arg_index: int
    # Target configurations for a function-like macro use the source macro's
    # argument positions. Parameter-flow queries use expanded positions.
    target: bool = False

    def token(self) -> str:
        fields = ["ARG", self.call_site_id, self.arg_index]
        if self.target:
            fields.append("TARGET")
        return json.dumps(
            fields, separators=(",", ":")
        )


@dataclass(frozen=True, slots=True)
class ParamQuery:
    # FORMAL parameter: "What can parameter N inside this function receive?"
    # Example: inside `wrapper(int value)`, ParamQuery asks about `value`.
    # The answer is found by making an ArgQuery for every `wrapper(...)` caller.
    function_id: str
    param_index: int

    def token(self) -> str:
        return json.dumps(
            ["PARAM", self.function_id, self.param_index], separators=(",", ":")
        )


@dataclass(frozen=True, slots=True)
class HandleQuery:
    # "Which configured open created the handle used at this read/close call?"
    # arg_index is the handle argument; 0 means the handle was ambiguous.
    call_site_id: str
    arg_index: int
    # The initial query is for the configured target call. Recursive handle
    # queries follow ordinary expanded call arguments.
    target: bool = False

    def token(self) -> str:
        fields = ["HANDLE", self.call_site_id, self.arg_index]
        if self.target:
            fields.append("TARGET")
        return json.dumps(
            fields, separators=(",", ":")
        )


@dataclass(frozen=True, slots=True)
class ReturnUseQuery:
    # "Is this returned resource used for reading or writing afterwards?"
    call_site_id: str

    def token(self) -> str:
        return json.dumps(["RETURN_USE", self.call_site_id], separators=(",", ":"))


Query: TypeAlias = ArgQuery | ParamQuery | HandleQuery | ReturnUseQuery


@dataclass(frozen=True, slots=True)
class Fact:
    # Final answer for one configured target API argument.
    # `value` is what that argument resolves to, not the target function name.
    # origin_query is the question that found this value. It lets the resolver
    # show the steps from this source value back to the target call.
    value: str
    origin_kind: OriginKind
    source_file: str
    source_line: int
    source_expr: str
    origin_query: str
    source_site_id: str = ""
    resolved_by: Literal["SYNTAX", "LLM"] = "SYNTAX"
    link_method: str = ""
    # Structured provenance for bounded tables, wrapper writes, string flow,
    # and pointer-parameter bindings.  Optional so old query caches remain
    # readable.
    metadata: dict = field(default_factory=dict)

    @property
    def source_key(self) -> tuple[str, int, str, str, str, str]:
        return (
            self.source_file,
            self.source_line,
            self.source_expr,
            self.origin_kind,
            self.value,
            self.source_site_id,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "Fact":
        return cls(**value)


@dataclass(frozen=True, slots=True)
class OneHopAnswer:
    # Answer from the optional LLM helper for one expression.
    # PARAM means "keep tracing this parameter". VALUE and EXTERNAL become
    # final Fact answers.
    kind: Literal["VALUE", "PARAM", "EXTERNAL", "UNRESOLVED"]
    value: str | None = None
    param_index: int | None = None
    source_expr: str | None = None

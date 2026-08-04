from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Literal, TypeAlias

OriginKind: TypeAlias = Literal[
    "CONST",
    "MACRO",
    "EXTERNAL_ENTRY",
    "EXTERNAL_DATA",
    "UNKNOWN_INDIRECT",
    "RECURSIVE",
    "UNRESOLVED",
]


@dataclass(frozen=True, slots=True)
class ArgQuery:
    call_site_id: str
    arg_index: int

    def token(self) -> str:
        return json.dumps(
            ["ARG", self.call_site_id, self.arg_index], separators=(",", ":")
        )


@dataclass(frozen=True, slots=True)
class ParamQuery:
    function_id: str
    param_index: int

    def token(self) -> str:
        return json.dumps(
            ["PARAM", self.function_id, self.param_index], separators=(",", ":")
        )


@dataclass(frozen=True, slots=True)
class HandleQuery:
    call_site_id: str
    arg_index: int

    def token(self) -> str:
        return json.dumps(
            ["HANDLE", self.call_site_id, self.arg_index], separators=(",", ":")
        )


@dataclass(frozen=True, slots=True)
class ReturnUseQuery:
    call_site_id: str

    def token(self) -> str:
        return json.dumps(["RETURN_USE", self.call_site_id], separators=(",", ":"))


Query: TypeAlias = ArgQuery | ParamQuery | HandleQuery | ReturnUseQuery


@dataclass(frozen=True, slots=True)
class Fact:
    value: str
    origin_kind: OriginKind
    source_file: str
    source_line: int
    source_expr: str
    origin_query: str
    source_site_id: str = ""
    resolved_by: Literal["SYNTAX", "LLM"] = "SYNTAX"
    link_method: str = ""

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
    kind: Literal["VALUE", "PARAM", "EXTERNAL", "UNRESOLVED"]
    value: str | None = None
    param_index: int | None = None
    source_expr: str | None = None

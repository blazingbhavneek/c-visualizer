"""The tracer's call-path label grammar.

Both `traces[].labels` and `interactions[].path` are written in this notation,
and both `corpus` and `graphops` need to read it — so it lives here, free of
any dependency on either.

A label is::

    [<file-defining-subject>:<call-site-line-in-the-caller>]<subject>[<def-start>:<def-end>]

with two indirection forms where control passes to a function that appears as
the *following* label::

    [scf_stubs.c:332]scf_evt_register (accepts callback)-> bo_on_trip[39:39]
    [413]RAISE_ALARM (macro expansion)-> scf_alarmq_enq

In the callback form the trailing `[39:39]` is **`scf_evt_register`'s**
definition range — `bo_on_trip` is defined at `[748:771]` and gets its own next
label.  Reading that range as the callback's mis-attributes the lines and
double-counts the hop.  The macro form carries no file and no range at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LABEL_PLAIN = re.compile(
    r"^\[(?P<file>[^\]:]+)(?::(?P<line>-?\d+))?\]"
    r"(?P<name>[A-Za-z_]\w*)"
    r"\[(?P<start>-?\d+):(?P<end>-?\d+)\]$"
)

LABEL_CALLBACK = re.compile(
    r"^\[(?P<file>[^\]:]+)(?::(?P<line>-?\d+))?\]"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<note>[^)]*callback[^)]*)\)->\s*"
    r"(?P<target>[A-Za-z_]\w*)"
    r"\[(?P<start>-?\d+):(?P<end>-?\d+)\]$"
)

LABEL_MACRO = re.compile(
    r"^\[(?P<line>-?\d+)\]"
    r"(?P<name>[A-Za-z_]\w*)\s*\((?P<note>[^)]*macro[^)]*)\)->\s*"
    r"(?P<target>[A-Za-z_]\w*)$"
)

# Steps are joined by `->`, but so is the inside of a callback or macro label
# (`... (accepts callback)-> bo_on_trip[39:39]`).  Splitting on a bare `->`
# tears those labels in half.
#
# The distinguishing detail: a separating arrow is followed immediately by the
# `[` that opens the next label, whereas an indirection arrow is always
# followed by a space and then a bare name.  Requiring only a *following* `[`
# — rather than also a preceding `]` — is what handles the macro form, which
# ends on a bare identifier with no closing bracket.
PATH_SEPARATOR = re.compile(r"->(?=\[)")


@dataclass(slots=True)
class ParsedLabel:
    """One decoded label.

    `target` is set only on the indirection forms, where this label hands
    control to a function appearing as the following label; `relation` says
    which form it was.
    """

    name: str
    file_name: str | None
    call_line: int | None
    def_start: int
    def_end: int
    target: str | None
    relation: str | None  # "callback" | "macro"
    note: str | None

    @property
    def is_indirection(self) -> bool:
        return self.target is not None


def parse_trace_label(label: str) -> ParsedLabel | None:
    """Decode one label. Returns None if the form is unrecognised."""
    text = (label or "").strip()

    match = LABEL_CALLBACK.match(text)
    if match:
        return ParsedLabel(
            name=match.group("name"),
            file_name=match.group("file"),
            call_line=int(match.group("line")) if match.group("line") else None,
            def_start=int(match.group("start")),
            def_end=int(match.group("end")),
            target=match.group("target"),
            relation="callback",
            note=match.group("note").strip(),
        )

    match = LABEL_MACRO.match(text)
    if match:
        return ParsedLabel(
            name=match.group("name"),
            file_name=None,
            call_line=int(match.group("line")),
            def_start=-1,
            def_end=-1,
            target=match.group("target"),
            relation="macro",
            note=match.group("note").strip(),
        )

    match = LABEL_PLAIN.match(text)
    if match:
        return ParsedLabel(
            name=match.group("name"),
            file_name=match.group("file"),
            call_line=int(match.group("line")) if match.group("line") else None,
            def_start=int(match.group("start")),
            def_end=int(match.group("end")),
            target=None,
            relation=None,
            note=None,
        )
    return None


def split_path(path: str) -> list[str]:
    """Split an `interactions[].path` string into its labels."""
    if not path:
        return []
    return [part for part in PATH_SEPARATOR.split(path) if part.strip()]


def parse_path(path: str) -> list[ParsedLabel]:
    """Decode a whole path, dropping labels that do not parse."""
    parsed = [parse_trace_label(label) for label in split_path(path)]
    return [label for label in parsed if label is not None]

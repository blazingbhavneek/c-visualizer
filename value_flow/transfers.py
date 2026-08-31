"""Source-grounded building blocks for route-guided value transfers."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from tree_sitter import Language, Parser
from tree_sitter_custom import language


_LITERAL_OR_PLACEHOLDER = re.compile(
    r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\$[1-9][0-9]*)'''
)
_INTEGER = re.compile(r"^(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]*|[1-9][0-9]*)[uUlL]*$")
_FORMULA_PARSER = Parser(Language(language()))


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    file: str
    start_byte: int
    end_byte: int


@dataclass(frozen=True, slots=True)
class Binding:
    target_arg: int
    kind: Literal["EXPRESSION", "EXACT", "EXTERNAL", "UNKNOWN"]
    text: str


@dataclass(slots=True)
class RouteArm:
    route_id: str
    correlation_id: str
    bindings: list[Binding]
    guards: list[str] = field(default_factory=list)
    evidence: list[EvidenceSpan] = field(default_factory=list)
    transfer_chain: list[str] = field(default_factory=list)
    # Resolver-only source witnesses.  They are intentionally not copied into
    # Fact's public shape until output materialisation.
    source_by_arg: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RouteGuide:
    route_id: str
    root_function_id: str
    edges: tuple[Any, ...]
    target_site_id: str
    reachability: str


@dataclass(frozen=True, slots=True)
class EffectiveValueSite:
    site_id: str
    value_indices: tuple[int, ...]
    link_method: str = ""


@dataclass(frozen=True, slots=True)
class TransferRequest:
    """The stable seam used by fake tests and the production LLM callback."""

    route: RouteGuide
    function_id: str
    function_name: str
    function_file: str
    function_source: str
    parameters: tuple[str, ...]
    selected_site_id: str
    selected_call_text: str
    selected_call_start_byte: int
    selected_call_end_byte: int
    bindings: tuple[Binding, ...]
    guards: tuple[str, ...]
    macro_context: str = ""
    function_start_byte: int = 0   # file offset of function_source[0]


def placeholder_indices(text: str) -> tuple[int, ...]:
    """Return distinct formal parameter references in source order."""
    return tuple(
        dict.fromkeys(
            int(match.group(2)[1:])
            for match in _LITERAL_OR_PLACEHOLDER.finditer(text)
            if match.group(2)
        )
    )


def _replace_placeholders(text: str, replacement: Callable[[int, str], str]) -> str:
    """Replace placeholders outside C string/character literals."""
    return _LITERAL_OR_PLACEHOLDER.sub(
        lambda match: match.group(1)
        or replacement(int(match.group(2)[1:]), match.group(2)),
        text,
    )


def substitute_placeholders(text: str, actuals: dict[int, str]) -> str:
    """Substitute all ``$N`` tokens simultaneously, preserving unknowns."""

    def replacement(index: int, token: str) -> str:
        actual = actuals.get(index)
        return f"({actual})" if actual is not None else token

    return _replace_placeholders(text, replacement)


class FormulaError(ValueError):
    """Raised when a model formula is outside the deliberately small grammar."""


def _rewrite_placeholders(formula: str) -> tuple[str, dict[str, int]]:
    mapping: dict[str, int] = {}

    def replacement(index: int, _token: str) -> str:
        name = f"__vf_param_{index}"
        mapping[name] = index
        return name

    return _replace_placeholders(formula.strip(), replacement), mapping


def _expression_node(formula: str) -> tuple[Any, dict[str, int]]:
    rewritten, mapping = _rewrite_placeholders(formula)
    if not rewritten or ";" in rewritten or "{" in rewritten or "}" in rewritten:
        raise FormulaError("formula is not a single expression")
    source = f"int __vf_formula(void) {{ return ({rewritten}); }}".encode("utf-8")
    tree = _FORMULA_PARSER.parse(source)
    if tree.root_node.has_error or any(node.type == "ERROR" for node in _walk(tree.root_node)):
        raise FormulaError("formula is not valid C")
    function = next((node for node in _walk(tree.root_node) if node.type == "function_definition"), None)
    if function is None:
        raise FormulaError("formula parse did not produce a function")
    statement = next((node for node in _walk(function) if node.type == "return_statement"), None)
    if statement is None or not statement.named_children:
        raise FormulaError("formula has no expression")
    return statement.named_children[0], mapping


def _walk(node: Any) -> list[Any]:
    result: list[Any] = []
    stack = [node]
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(reversed(current.children))
    return result


def _node_text(node: Any) -> str:
    return node.text.decode("utf-8", errors="replace") if node.text is not None else ""


def _literal_value(text: str) -> int | str | None:
    value = text.strip()
    if _INTEGER.fullmatch(value):
        suffixless = re.sub(r"[uUlL]+$", "", value)
        try:
            if suffixless.lower().startswith("0x"):
                return int(suffixless, 16)
            if suffixless.lower().startswith("0b"):
                return int(suffixless, 2)
            if len(suffixless) > 1 and suffixless.startswith("0"):
                return int(suffixless, 8)
            return int(suffixless, 10)
        except ValueError:
            return None
    if value.startswith(("\"", "'", "u8\"", "u\"", "U\"", "L\"")):
        try:
            parsed = ast.literal_eval(re.sub(r"^(?:u8|u|U|L)(?=[\"'])", "", value))
        except (SyntaxError, ValueError):
            return None
        if isinstance(parsed, str):
            return ord(parsed) if value.rstrip().endswith("'") and len(parsed) == 1 else parsed
    return None


# Integer and character literals as they may be spelled in source, for the
# value-based evidence check in validate_formula.  A character literal counts
# because `'\n'` in source and `10` in a formula denote the same value.
_EVIDENCE_LITERAL = re.compile(
    r"(?<![A-Za-z0-9_])(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]*|[1-9][0-9]*)[uUlL]*"
    r"|'(?:\\.|[^'\\])+'"
)


def _evidence_integer_values(evidence: str) -> set[int]:
    """Every integer VALUE spelled anywhere in the evidence, in any C base."""
    values: set[int] = set()
    for token in _EVIDENCE_LITERAL.findall(evidence):
        parsed = _literal_value(token)
        if isinstance(parsed, int) and not isinstance(parsed, bool):
            values.add(parsed)
    return values


_ALLOWED_UNARY = {"+", "-", "~", "!"}
_ALLOWED_BINARY = {
    "+", "-", "*", "/", "%", "<<", ">>", "&", "|", "^",
    "==", "!=", "<", "<=", ">", ">=", "&&", "||",
}


def _operator(node: Any) -> str:
    # Tree-sitter keeps the operator as an anonymous child.  Looking through
    # the complete node text is subtly wrong for nested expressions: the outer
    # `+` node would also contain an inner `*`, and set iteration could select
    # the wrong operator.
    for child in node.children:
        if not child.is_named:
            token = _node_text(child)
            if token in _ALLOWED_BINARY or token in _ALLOWED_UNARY:
                return token
    return ""


# P10 (flagged, TRACER_VF_GRAMMAR_EXTENDED): these node types are accepted as
# opaque leaves but never evaluated -- evaluate_formula's evaluate() returns
# None for any node kind it doesn't handle, so a binding built from one of
# these can never become an EXACT value. Widening the grammar can only let
# the model NAME a source it currently cannot name; it cannot produce a wrong
# number. call_expression is deliberately excluded: a call has side effects
# and an unknown return, so UNKNOWN is the honest answer there.
_OPAQUE_NODES = {
    "field_expression",
    "subscript_expression",
    "pointer_expression",
    "conditional_expression",
}


def _validate_node(
    node: Any,
    *,
    placeholders: dict[str, int],
    parameter_count: int,
    visible_names: set[str],
    literals: list[str],
    allow_opaque: bool = False,
) -> None:
    node_type = node.type
    if node_type in {"parenthesized_expression"}:
        children = node.named_children
        if len(children) != 1:
            raise FormulaError("invalid parenthesized expression")
        _validate_node(children[0], placeholders=placeholders, parameter_count=parameter_count, visible_names=visible_names, literals=literals, allow_opaque=allow_opaque)
        return
    if node_type in {"number_literal", "char_literal", "string_literal"}:
        text = _node_text(node)
        if _literal_value(text) is None:
            raise FormulaError("unsupported literal")
        literals.append(text)
        return
    if node_type in {"true", "false"}:
        return
    if node_type == "identifier":
        name = _node_text(node)
        if name in placeholders:
            if placeholders[name] > parameter_count:
                raise FormulaError(f"parameter ${placeholders[name]} does not exist")
            return
        if name not in visible_names and name not in {"true", "false"}:
            raise FormulaError(f"unknown identifier {name}")
        return
    if node_type == "unary_expression":
        if _operator(node) not in _ALLOWED_UNARY or len(node.named_children) != 1:
            raise FormulaError("unsupported unary expression")
        _validate_node(node.named_children[0], placeholders=placeholders, parameter_count=parameter_count, visible_names=visible_names, literals=literals, allow_opaque=allow_opaque)
        return
    if node_type == "binary_expression":
        if _operator(node) not in _ALLOWED_BINARY or len(node.named_children) != 2:
            raise FormulaError("unsupported binary expression")
        for child in node.named_children:
            _validate_node(child, placeholders=placeholders, parameter_count=parameter_count, visible_names=visible_names, literals=literals, allow_opaque=allow_opaque)
        return
    if allow_opaque and node_type in _OPAQUE_NODES:
        # An opaque leaf: the model may NAME this source, but the expression
        # is deliberately not evaluable, so it can never become an EXACT
        # value. Do not identifier-check the descendants -- `cfg` in
        # `cfg->mode` is a local and is not in visible_names by design. Only
        # collect nested literals so they still have to be covered by
        # evidence.
        for descendant in _walk(node):
            if descendant.type in {"number_literal", "char_literal", "string_literal"}:
                text = _node_text(descendant)
                if _literal_value(text) is not None:
                    literals.append(text)
        return
    raise FormulaError(f"unsupported expression node {node_type}")


def validate_formula(
    formula: str,
    *,
    parameter_count: int,
    visible_names: set[str] | None = None,
    evidence_texts: tuple[str, ...] = (),
    allow_boolean_literals: bool = False,
    allow_opaque: bool = False,
) -> tuple[dict[str, int], tuple[str, ...]]:
    """Validate a formula and return parser-safe placeholders/literal leaves."""
    node, placeholders = _expression_node(formula)
    literals: list[str] = []
    _validate_node(
        node,
        placeholders=placeholders,
        parameter_count=parameter_count,
        visible_names=visible_names or set(),
        literals=literals,
        allow_opaque=allow_opaque,
    )
    evidence = "\n".join(evidence_texts)
    evidence_values: set[int] | None = None
    for literal in literals:
        if allow_boolean_literals and literal in {"0", "1"}:
            continue
        if literal in evidence:
            continue
        # P11: source and formula may spell the same number differently --
        # 0x10 vs 16, 1U vs 1, '\n' vs 10. The requirement is that the number
        # is GROUNDED in evidence, not that it is spelled the same way, so
        # compare integer values before rejecting. This is not a relaxation:
        # an ungrounded number still has no matching value and still fails.
        value = _literal_value(literal)
        if isinstance(value, int) and not isinstance(value, bool):
            if evidence_values is None:
                evidence_values = _evidence_integer_values(evidence)
            if value in evidence_values:
                continue
        raise FormulaError(f"literal {literal} is not covered by evidence")
    return placeholders, tuple(literals)


def evaluate_formula(
    formula: str,
    substitutions: dict[int, Any] | None = None,
    *,
    resolve_constant: Callable[[str], Any | None] | None = None,
) -> tuple[bool, Any]:
    """Evaluate only validated integer/string formulas with known leaves."""
    node, placeholders = _expression_node(formula)
    substitutions = substitutions or {}
    values = {name: substitutions.get(index) for name, index in placeholders.items()}

    def evaluate(current: Any) -> Any:
        kind = current.type
        if kind == "parenthesized_expression":
            return evaluate(current.named_children[0])
        if kind in {"number_literal", "char_literal", "string_literal"}:
            return _literal_value(_node_text(current))
        if kind == "true":
            return 1
        if kind == "false":
            return 0
        if kind == "identifier":
            name = _node_text(current)
            if name in values:
                return values[name]
            if name == "true":
                return 1
            if name == "false":
                return 0
            return resolve_constant(name) if resolve_constant else None
        if kind == "unary_expression":
            value = evaluate(current.named_children[0])
            if value is None or not isinstance(value, int):
                return None
            operator = _operator(current)
            if operator == "+": return +value
            if operator == "-": return -value
            if operator == "~": return ~value
            if operator == "!": return int(not value)
            return None
        if kind == "binary_expression":
            operator = _operator(current)
            left = evaluate(current.named_children[0])
            if operator == "&&" and isinstance(left, int) and left == 0:
                return 0
            if operator == "||" and isinstance(left, int) and left != 0:
                return 1
            right = evaluate(current.named_children[1])
            if operator == "&&" and isinstance(left, int) and isinstance(right, int): return int(bool(left) and bool(right))
            if operator == "||" and isinstance(left, int) and isinstance(right, int): return int(bool(left) or bool(right))
            if left is None or right is None or not isinstance(left, int) or not isinstance(right, int):
                return None
            try:
                if operator == "+": return left + right
                if operator == "-": return left - right
                if operator == "*": return left * right
                if operator == "/":
                    if not right:
                        return None
                    quotient = abs(left) // abs(right)
                    return -quotient if (left < 0) != (right < 0) else quotient
                if operator == "%":
                    if not right:
                        return None
                    quotient = abs(left) // abs(right)
                    if (left < 0) != (right < 0):
                        quotient = -quotient
                    return left - quotient * right
                if operator == "<<": return left << right if right >= 0 else None
                if operator == ">>": return left >> right if right >= 0 else None
                if operator == "&": return left & right
                if operator == "|": return left | right
                if operator == "^": return left ^ right
                if operator == "==": return int(left == right)
                if operator == "!=": return int(left != right)
                if operator == "<": return int(left < right)
                if operator == "<=": return int(left <= right)
                if operator == ">": return int(left > right)
                if operator == ">=": return int(left >= right)
            except (ArithmeticError, ValueError, OverflowError):
                return None
            return None
        return None

    result = evaluate(node)
    # Without build-proven integer width/signedness, large arithmetic results
    # are not safe to call exact.  Small file numbers, flags, and enum
    # transforms remain the common fast path.
    if isinstance(result, int) and not isinstance(result, bool) and abs(result) > 0x7FFFFFFF:
        result = None
    return (result is not None, result)


def make_transfer_cache_key(
    *,
    prompt_version: str,
    model_id: str,
    function_id: str,
    function_source: bytes | str,
    selected_site_id: str,
    selected_site_source: bytes | str,
    bindings: tuple[Binding, ...],
    guards: tuple[str, ...],
    macro_digest: str = "",
) -> str:
    def digest(value: bytes | str) -> str:
        raw = value if isinstance(value, bytes) else value.encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    payload = {
        "prompt_version": prompt_version,
        "model_id": model_id,
        "function_id": function_id,
        "function_source": digest(function_source),
        "selected_site_id": selected_site_id,
        "selected_site_source": digest(selected_site_source),
        "bindings": [(item.target_arg, item.kind, item.text) for item in bindings],
        "guards": list(guards),
        "macro_digest": macro_digest,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

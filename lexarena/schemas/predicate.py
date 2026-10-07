"""predicate_registry entries (DATA_FORMATS §4) and the expression grammar they use.

Structural rules enforced here, independent of any statute:
- every `var` names a declared input; every `choose` names a declared open parameter and covers
  exactly its options;
- operators have the arity the grammar gives them;
- at least one `claim:` input is used in the expression (D-021), so a predicate can only test what an
  argument said, never whether the case is winnable;
- the predicate's tracked assertion is a SPEC D8 hard-error code (D-021).

Whether a constant is really quoted in `source_text` needs reading the law, so it is checked at review
(Step 3), not here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from lexarena.schemas.base import NonEmptyStr, StoredModel
from lexarena.schemas.codes import HardErrorCode

PredicateStatus = Literal["DRAFT", "APPROVED", "STALE", "RETIRED"]
PredicateKind = Literal["THRESHOLD", "DAY_COUNT", "DATE_ORDER", "DATE_WINDOW"]
INPUT_SOURCE_PATTERN = r"^(record\.amounts:|record\.key_dates:|law:|overlay:|claim:)\S+$"

Operator = Literal[
    "and", "or", "not", "implies", "==", "!=", "<", "<=", ">", ">=", "+", "-",
    "days_between", "add_years", "add_days", "if",
]  # fmt: skip

# Operator -> (min args, max args); None means unbounded. Arities come from the grammar in DATA_FORMATS §4.
_BINARY = (2, 2)  # literal-ok: grammar arity, not a tuning value
_VARIADIC = (2, None)  # literal-ok: grammar arity, not a tuning value
OPERATOR_ARITY: dict[str, tuple[int, int | None]] = {
    "and": _VARIADIC,
    "or": _VARIADIC,
    "not": (1, 1),
    "implies": _BINARY,
    "==": _BINARY,
    "!=": _BINARY,
    "<": _BINARY,
    "<=": _BINARY,
    ">": _BINARY,
    ">=": _BINARY,
    "+": _VARIADIC,
    "-": _BINARY,
    "days_between": _BINARY,
    "add_years": _BINARY,
    "add_days": _BINARY,
    "if": (3, 3),  # literal-ok: if(cond, a, b) takes three arguments by definition
}


class VarLeaf(StoredModel):
    var: NonEmptyStr


class ConstLeaf(StoredModel):
    const: bool | int | float | str


class OpNode(StoredModel):
    op: Operator
    args: list[Expression]

    @model_validator(mode="after")
    def _arity(self) -> OpNode:
        low, high = OPERATOR_ARITY[self.op]
        if len(self.args) < low or (high is not None and len(self.args) > high):
            raise ValueError(f"operator {self.op!r} takes {low}..{high or 'n'} arguments, got {len(self.args)}")
        return self


class ChooseNode(StoredModel):
    """`choose(<open_parameter>, {option: expr})`: the argument picks one reading (SPEC D2, D-007)."""

    op: Literal["choose"]
    param: NonEmptyStr
    cases: dict[str, Expression] = Field(min_length=1)


Expression = VarLeaf | ConstLeaf | OpNode | ChooseNode
OpNode.model_rebuild()
ChooseNode.model_rebuild()


class PredicateInput(StoredModel):
    name: NonEmptyStr
    source: str = Field(pattern=INPUT_SOURCE_PATTERN)


class OpenParameter(StoredModel):
    name: NonEmptyStr
    options: list[NonEmptyStr] = Field(min_length=2)  # literal-ok: a choice needs two readings
    note: str


def walk(expr: Expression) -> list[Expression]:
    """Every node of an expression tree, root first."""
    nodes: list[Expression] = [expr]
    if isinstance(expr, OpNode):
        for arg in expr.args:
            nodes += walk(arg)
    elif isinstance(expr, ChooseNode):
        for case in expr.cases.values():
            nodes += walk(case)
    return nodes


class PredicateEntry(StoredModel):
    predicate_id: NonEmptyStr
    statute_id: NonEmptyStr
    field: NonEmptyStr
    item_index: int | None = Field(ge=0)
    item_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: PredicateKind
    inputs: list[PredicateInput] = Field(min_length=1)
    open_parameters: list[OpenParameter]
    expression: Expression
    error_code: HardErrorCode
    source_text: NonEmptyStr
    status: PredicateStatus
    approved_by: str | None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def _structure(self) -> PredicateEntry:
        inputs = {i.name: i.source for i in self.inputs}
        params = {p.name: set(p.options) for p in self.open_parameters}
        if len(inputs) != len(self.inputs) or len(params) != len(self.open_parameters):
            raise ValueError("input and open parameter names must be unique")
        used_vars: set[str] = set()
        for node in walk(self.expression):
            if isinstance(node, VarLeaf):
                if node.var not in inputs:
                    raise ValueError(f"expression uses undeclared input {node.var!r}")
                used_vars.add(node.var)
            elif isinstance(node, ChooseNode):
                if node.param not in params:
                    raise ValueError(f"choose uses undeclared open parameter {node.param!r}")
                if set(node.cases) != params[node.param]:
                    raise ValueError(f"choose over {node.param!r} must cover exactly its options")
        if not any(inputs[name].startswith("claim:") for name in used_vars):
            raise ValueError("expression must use at least one claim: input (D-021)")
        if self.status == "APPROVED" and not self.approved_by:
            raise ValueError("an APPROVED predicate must name approved_by")
        return self

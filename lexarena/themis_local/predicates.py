"""THEMIS-LOCAL layer 1: the generic predicate engine (BUILD_PLAN Step 7; DATA_FORMATS §4; SPEC D1, D2, D8).

One engine compiles any approved `predicate_registry` expression to Z3; there is no per-section Python, so new law
is new data (ARCHITECTURE §8). Inputs are resolved from four places only:
- `record.amounts:<label>` and `record.key_dates:<label>`: the case record;
- `law:<json path>`: the Law DB entry as it applies on the case date;
- `overlay:<parameter>`: the approved temporal_overlay value for the case date;
- `claim:<field>`: what the argument itself asserted (every predicate uses at least one, D-021).

The whole predicate is added as a tracked assertion named by its error code, so an unsatisfiable check returns the
error code from Z3's unsat core. Dates are day ordinals; `add_years` is calendar arithmetic (a 29 February start
ends on 28 February), applied to the concrete date before it reaches the solver. A missing input or an open reading
the argument did not choose skips the predicate: it goes to layer 2 and never rejects (SPEC D1 point 4, D8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

import z3  # type: ignore[import-untyped]

from lexarena.schemas.predicate import ChooseNode, ConstLeaf, Expression, OpNode, PredicateEntry, VarLeaf

Value = bool | int | float | str | date
Inputs = dict[str, Value | None]


class _MissingError(Exception):
    """An input or reading the predicate needs is not available."""

    def __init__(self, name: str) -> None:
        self.name = name


@dataclass
class PredicateResult:
    predicate_id: str
    status: Literal["PASS", "FAIL", "SKIPPED"]
    error_code: str | None = None
    missing: list[str] = field(default_factory=list)


def select_approved(entries: list[PredicateEntry]) -> list[PredicateEntry]:
    """Only APPROVED predicates run; DRAFT, STALE and RETIRED never do (non-negotiable 8)."""
    return [p for p in entries if p.status == "APPROVED"]


def _law_path(law: dict[str, Any], path: str) -> Value | None:
    node: Any = law
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, bool | int | float | str | date) else None


def resolve_inputs(
    predicate: PredicateEntry,
    *,
    amounts: dict[str, int | float],
    key_dates: dict[str, date],
    law: dict[str, Any],
    overlay: dict[str, Any],
    claim: dict[str, Any],
) -> Inputs:
    out: Inputs = {}
    for item in predicate.inputs:
        kind, _, key = item.source.partition(":")
        if kind == "record.amounts":
            out[item.name] = amounts.get(key)
        elif kind == "record.key_dates":
            out[item.name] = key_dates.get(key)
        elif kind == "law":
            out[item.name] = _law_path(law, key)
        elif kind == "overlay":
            out[item.name] = overlay.get(key)
        else:  # claim:
            out[item.name] = claim.get(key)
    return out


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February in a non-leap year: the period ends on 28 February
        return d.replace(year=d.year + years, day=d.day - 1)


class _Compiler:
    def __init__(self, inputs: Inputs, choices: dict[str, str]) -> None:
        self._inputs = inputs
        self._choices = choices

    def concrete(self, node: Expression) -> Value:
        """The Python value of a subtree made only of inputs and constants (used for calendar arithmetic)."""
        if isinstance(node, ConstLeaf):
            return node.const
        if isinstance(node, VarLeaf):
            value = self._inputs.get(node.var)
            if value is None:
                raise _MissingError(node.var)
            return value
        if isinstance(node, OpNode) and node.op in ("add_years", "add_days"):
            base, amount = self.concrete(node.args[0]), self.concrete(node.args[1])
            if not isinstance(base, date) or not isinstance(amount, int):
                raise TypeError(f"{node.op} needs a date and a whole number")
            return _add_years(base, amount) if node.op == "add_years" else base + timedelta(days=amount)
        raise TypeError(f"{getattr(node, 'op', node)} has no concrete value")

    def term(self, node: Expression) -> Any:
        if isinstance(node, ConstLeaf | VarLeaf):
            return _z3_value(self.concrete(node))
        if isinstance(node, ChooseNode):
            chosen = self._choices.get(node.param)
            if chosen is None or chosen not in node.cases:
                raise _MissingError(f"choice:{node.param}")
            return self.term(node.cases[chosen])
        args = node.args
        op = node.op
        if op in ("add_years", "add_days"):
            return _z3_value(self.concrete(node))
        terms = [self.term(a) for a in args]
        if op == "and":
            return z3.And(*terms)
        if op == "or":
            return z3.Or(*terms)
        if op == "not":
            return z3.Not(terms[0])
        if op == "implies":
            return z3.Implies(terms[0], terms[1])
        if op == "if":
            return z3.If(terms[0], terms[1], terms[2])
        if op == "+":
            return z3.Sum(*terms)
        if op == "-":
            return terms[0] - terms[1]
        if op == "days_between":
            return terms[1] - terms[0]
        comparisons = {
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
        }
        return comparisons[op](terms[0], terms[1])


def _z3_value(value: Value) -> Any:
    if isinstance(value, bool):
        return z3.BoolVal(value)
    if isinstance(value, date):
        return z3.IntVal(value.toordinal())
    if isinstance(value, int):
        return z3.IntVal(value)
    if isinstance(value, float):
        return z3.RealVal(value)
    return z3.StringVal(value)


def evaluate(predicate: PredicateEntry, inputs: Inputs, choices: dict[str, str]) -> PredicateResult:
    compiler = _Compiler(inputs, choices)
    try:
        claim = compiler.term(predicate.expression)
    except _MissingError as missing:
        absent = sorted(n for n, v in inputs.items() if v is None) or [missing.name]
        return PredicateResult(predicate.predicate_id, "SKIPPED", missing=absent)
    solver = z3.Solver()
    solver.set(unsat_core=True)
    solver.assert_and_track(claim, z3.Bool(predicate.error_code))
    if solver.check() == z3.sat:
        return PredicateResult(predicate.predicate_id, "PASS")
    core = [str(c) for c in solver.unsat_core()]
    return PredicateResult(predicate.predicate_id, "FAIL", error_code=core[0] if core else predicate.error_code)

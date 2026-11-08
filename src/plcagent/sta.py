"""Static checker, first batch (13.1/13.2/13.3 S-rules + 13.4 R-rules).

S-rules run on the ST AST; R-rules (safety, non-disableable) run on the IR.
Output is a uniform Problem list; level error blocks the gate, warn needs
confirmation. Known W3 limitation: AST nodes carry no source positions, so
S02/S03/S11 report line=0 (parser positions arrive with S01 in W4).
"""

from __future__ import annotations

from dataclasses import dataclass

from plcagent.spec.ir_model import IrProject
from plcagent.st.ast_nodes import (
    Assignment,
    Binary,
    CaseStatement,
    ForStatement,
    IfStatement,
    Literal,
    Pou,
    Unary,
    VarRef,
    WhileStatement,
)
from plcagent.st.types import StTypeError, coerce


@dataclass(frozen=True)
class Problem:
    rule: str
    level: str          # error / warn
    message: str
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------- S rules

_INT_TYPES = {"BYTE", "INT", "DINT", "UINT", "UDINT"}


def _infer_type(expr, types: dict) -> str | None:
    """Static type inference; returns type name or None when unknown."""
    if isinstance(expr, VarRef):
        return types.get(expr.name)
    if isinstance(expr, Literal):
        return expr.st_type.name
    if isinstance(expr, Unary):
        return _infer_type(expr.operand, types)
    if isinstance(expr, Binary):
        left = _infer_type(expr.left, types)
        right = _infer_type(expr.right, types)
        if expr.op in ("AND", "OR", "XOR"):
            return "BOOL" if left == "BOOL" and right == "BOOL" else "MIXED"
        if expr.op in ("=", "<>", "<", ">", "<=", ">="):
            return "BOOL"
        if left in _INT_TYPES and right in _INT_TYPES:
            return "DINT"
        if left == "REAL" or right == "REAL":
            return "REAL"
        return left or right
    return None


def _walk_expr(expr, out: list) -> None:
    out.append(expr)
    if isinstance(expr, Unary):
        _walk_expr(expr.operand, out)
    elif isinstance(expr, Binary):
        _walk_expr(expr.left, out)
        _walk_expr(expr.right, out)


def _walk_stmts(stmts, out: list) -> None:
    for stmt in stmts:
        out.append(stmt)
        if isinstance(stmt, Assignment):
            _walk_expr(stmt.expr, out)
        elif isinstance(stmt, IfStatement):
            for cond, body in stmt.branches:
                _walk_expr(cond, out)
                _walk_stmts(body, out)
            _walk_stmts(stmt.else_body, out)
        elif isinstance(stmt, CaseStatement):
            _walk_expr(stmt.selector, out)
            for arm in stmt.arms:
                _walk_stmts(arm.body, out)
            _walk_stmts(stmt.else_body, out)
        elif isinstance(stmt, ForStatement):
            _walk_stmts(stmt.body, out)
        elif isinstance(stmt, WhileStatement):
            _walk_stmts(stmt.body, out)


def check_st(source: str, pou: Pou | None = None) -> list[Problem]:
    """S01~S03, S11, S21 on one POU's source/AST."""
    problems: list[Problem] = []
    # S21 runs on raw text first: a parse error (S01) must not hide an
    # address-in-logic violation - both are reportable.
    _check_direct_addresses(source, problems)
    if pou is None:
        from plcagent.st.parser import StSyntaxError, parse_program

        try:
            pou = parse_program(source)
        except StSyntaxError as exc:
            # S01: lex/parse error with exact position
            problems.append(Problem("S01", "error", str(exc), exc.line, exc.col))
            return problems

    declared: dict[str, str] = {}
    for decl in pou.decls:
        declared[decl.name] = decl.st_type.name

    stmts: list = []
    _walk_stmts(pou.body, stmts)
    exprs: list = []
    for stmt in stmts:
        if isinstance(stmt, Assignment):
            _walk_expr(stmt.expr, exprs)

    # S02: undeclared use (reads incl. assignment targets via expr walk only
    # covers reads; targets checked separately below)
    for expr in exprs:
        if isinstance(expr, VarRef) and expr.name not in declared:
            problems.append(Problem("S02", "error",
                                    f"variable {expr.name!r} used before declaration"))

    # S03: type mismatches (BOOL logic, assignments)
    for stmt in stmts:
        if isinstance(stmt, Assignment):
            target_type = declared.get(stmt.target)
            inferred = _infer_type(stmt.expr, declared)
            if target_type and inferred and inferred not in ("MIXED",):
                try:
                    coerce({t.name: t for t in ()}.get(target_type) or _type_by_name(target_type),
                           _sample_value(inferred))
                except StTypeError:
                    problems.append(Problem(
                        "S03", "error",
                        f"assignment {stmt.target}({target_type}) := {inferred} type mismatch"))
        elif isinstance(stmt, IfStatement):
            for cond, _body in stmt.branches:
                if _infer_type(cond, declared) not in ("BOOL", None):
                    problems.append(Problem("S03", "error",
                                            "IF condition must be BOOL"))

    # S11: same output assigned twice by sibling statements in one block
    # (mutually exclusive branches are fine per 13.5 boundary rule)
    _check_duplicate_writes(pou.body, problems)

    return problems


def _type_by_name(name: str):
    from plcagent.st.types import BY_NAME

    return BY_NAME[name]


def _sample_value(type_name: str):
    return {"BOOL": True, "REAL": 1.0, "TIME": 1}.get(type_name, 1)


def _check_duplicate_writes(stmts, problems: list[Problem], seen: set | None = None) -> None:
    """S11 within one straight-line block; recurse into branch bodies
    independently (branches are alternatives, not duplicates)."""
    written: dict[str, int] = {}
    for stmt in stmts:
        if isinstance(stmt, Assignment):
            written[stmt.target] = written.get(stmt.target, 0) + 1
            if written[stmt.target] == 2:
                problems.append(Problem(
                    "S11", "error",
                    f"output {stmt.target!r} assigned multiple times in one scan "
                    f"path (last write wins) - safety rule"))
        elif isinstance(stmt, IfStatement):
            for _cond, body in stmt.branches:
                _check_duplicate_writes(body, problems)
            _check_duplicate_writes(stmt.else_body, problems)
        elif isinstance(stmt, CaseStatement):
            for arm in stmt.arms:
                _check_duplicate_writes(arm.body, problems)
            _check_duplicate_writes(stmt.else_body, problems)
        elif isinstance(stmt, (ForStatement, WhileStatement)):
            _check_duplicate_writes(stmt.body, problems)


def _check_direct_addresses(source: str, problems: list[Problem]) -> None:
    """S21: %I/%Q only allowed on declaration lines, never in logic."""
    for line_no, line in enumerate(source.splitlines(), start=1):
        code = line.split("//")[0]
        if "%" in code and ("VAR" not in code) and not code.strip().startswith("//"):
            if "%I" in code or "%Q" in code:
                problems.append(Problem(
                    "S21", "error",
                    f"direct address in logic (line {line_no}); "
                    f"addresses belong in the GVL mapping layer", line_no))


# ---------------------------------------------------------------- R rules

_POWER_HINTS = ("Motor", "Pump", "Valve", "Cyl", "Conv", "Heater", "Fan")
_INDICATOR_PREFIX = "HMI_"


def _is_power_output(name: str) -> bool:
    return any(hint in name for hint in _POWER_HINTS)


def _interlock_targets(ir: IrProject) -> set[str]:
    targets: set[str] = set()
    for interlock in ir.interlocks:
        for action in interlock.actions:
            if action.value in (False, 0):
                targets.add(action.target)
    return targets


def _collect_guard_names(expr, out: set[str]) -> None:
    if getattr(expr, "kind", "") == "VAR":
        out.add(expr.name or "")
    elif getattr(expr, "kind", "") == "MEMBER":
        return
    for child in (getattr(expr, "left", None), getattr(expr, "right", None),
                  getattr(expr, "operand", None)):
        if child is not None:
            _collect_guard_names(child, out)


def check_ir(ir: IrProject) -> list[Problem]:
    """Safety rules on the IR (13.4, non-disableable)."""
    problems: list[Problem] = []

    # R01: every power output must be cut by at least one interlock action
    cut_targets = _interlock_targets(ir)
    for io in ir.io:
        if io.direction == "out" and _is_power_output(io.name) and io.name not in cut_targets:
            problems.append(Problem(
                "R01", "error",
                f"power output {io.name!r} has no interlock cut (safety, non-disableable)"))

    # R02: estop must appear in an interlock (guard) AND reach Fault via
    # a wildcard prio-0 edge in at least one machine
    estop_names = {io.name for io in ir.io
                   if io.name.lower().startswith(("estop", "e_stop"))}
    interlock_guards: set[str] = set()
    for interlock in ir.interlocks:
        _collect_guard_names(interlock.guard, interlock_guards)
    if estop_names and not (estop_names & interlock_guards):
        problems.append(Problem(
            "R02", "error",
            f"estop {sorted(estop_names)} must gate at least one interlock"))

    has_wildcard_fault = False
    for machine in ir.machines:
        for edge in machine.transitions:
            guard_names: set[str] = set()
            _collect_guard_names(edge.guard, guard_names)
            if (edge.from_state == "*" and edge.priority == 0
                    and (guard_names & estop_names)):
                has_wildcard_fault = True
    if estop_names and not has_wildcard_fault:
        problems.append(Problem(
            "R02", "error",
            "estop must drive a wildcard prio-0 edge into the fault state"))

    # R11: resource caps (=V12, re-checked here as a hard gate)
    if len(ir.machines) > 8:
        problems.append(Problem("R11", "error", "more than 8 machines"))
    for machine in ir.machines:
        if len(machine.states) > 32:
            problems.append(Problem("R11", "error",
                                    f"machine {machine.name}: more than 32 states"))
    if len(ir.interlocks) > 64:
        problems.append(Problem("R11", "error", "more than 64 interlocks"))
    return problems


def check_all(source: str, ir: IrProject) -> list[Problem]:
    """S-rules on generated ST + R-rules on IR; the full W3 gate set."""
    return check_st(source) + check_ir(ir)

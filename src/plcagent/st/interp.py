"""Scan-loop executor with TON semantics and instrumentation hooks.

Everything here is deterministic: no wall clock, no hash-order dependence,
floats only via float32 rounding in types.coerce (15.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plcagent.st.ast_nodes import (
    Assignment,
    Binary,
    CaseStatement,
    ForStatement,
    IfStatement,
    Literal,
    Pou,
    ReturnStatement,
    Unary,
    VarRef,
    WhileStatement,
)
from plcagent.st.types import DINT, REAL, StType, coerce, default_value


class SimFault(RuntimeError):
    """Runtime violation: uninitialised read, division by zero, runaway loop."""


class InstrumentedRunner:
    """Base instrumentation (5.2). Subclass to collect coverage and trace."""

    def on_before_statement(self, stmt_id: int) -> None:
        """Branch/statement coverage hook."""

    def on_var_write(self, var: str, value: object) -> None:
        """Trace hook on assignment."""

    def on_var_read(self, var: str, value: object) -> None:
        """Trace hook on expression read."""

    @property
    def current_scan(self) -> int:
        return 0


class TON:
    """On-delay timer (15.1): rising IN starts ET accumulation,
    IN=FALSE resets immediately, ET saturates at preset."""

    __slots__ = ("preset_ms", "et", "in_prev", "q")

    def __init__(self, preset_ms: int) -> None:
        self.preset_ms = preset_ms
        self.et = 0
        self.in_prev = False
        self.q = False

    def call(self, input_on: bool, elapsed_ms: int) -> None:
        if not input_on:
            self.et = 0
            self.q = False
            self.in_prev = False
            return
        if not self.in_prev:
            self.et = 0  # rising edge restarts accumulation
        self.et = min(self.et + elapsed_ms, self.preset_ms)
        self.q = self.et >= self.preset_ms
        self.in_prev = True


@dataclass(slots=True)
class Environment:
    values: dict[str, object] = field(default_factory=dict)
    types: dict[str, StType] = field(default_factory=dict)
    timers: dict[str, TON] = field(default_factory=dict)


class Interpreter:
    """Executes one POU scan by scan on a virtual clock."""

    def __init__(self, pou: Pou, clock, instrument: InstrumentedRunner | None = None) -> None:
        self.pou = pou
        self.clock = clock
        self.instrument = instrument or InstrumentedRunner()
        self.env = Environment()
        self._init_env()

    def _init_env(self) -> None:
        for decl in self.pou.decls:
            self.env.types[decl.name] = decl.st_type
            if decl.init is not None:
                value = self._eval_static(decl.init)
            else:
                value = default_value(decl.st_type)
            self.env.values[decl.name] = coerce(decl.st_type, value)

    def _eval_static(self, expr: object) -> object:
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, Unary) and expr.op == "-":
            inner = self._eval_static(expr.operand)
            if isinstance(inner, (int, float)) and not isinstance(inner, bool):
                return -inner
        raise SimFault("initialiser must be a constant expression")

    # -- scan loop -----------------------------------------------------------
    def run_scan(self, inputs: dict[str, object],
                 timer_presets: dict[str, int] | None = None) -> None:
        """One scan: write inputs -> execute body -> advance clock."""
        for name, value in inputs.items():
            if name not in self.env.types:
                raise SimFault(f"unknown input {name!r}")
            self.env.values[name] = coerce(self.env.types[name], value)
        for timer_name, preset in (timer_presets or {}).items():
            self.env.timers.setdefault(timer_name, TON(preset))
        self._execute(self.pou.body)
        self.clock.advance()

    # -- statements -----------------------------------------------------------
    def _execute(self, stmts: tuple) -> None:
        for stmt_id, stmt in enumerate(stmts):
            self.instrument.on_before_statement(stmt_id)
            if isinstance(stmt, Assignment):
                value = self._eval(stmt.expr)
                self._assign(stmt.target, value)
            elif isinstance(stmt, IfStatement):
                executed = False
                for cond, body in stmt.branches:
                    if self._truthy(self._eval(cond)):
                        self._execute(body)
                        executed = True
                        break
                if not executed:
                    self._execute(stmt.else_body)
            elif isinstance(stmt, CaseStatement):
                self._exec_case(stmt)
            elif isinstance(stmt, ForStatement):
                self._exec_for(stmt)
            elif isinstance(stmt, WhileStatement):
                iterations = 0
                while self._truthy(self._eval(stmt.cond)):
                    self._execute(stmt.body)
                    iterations += 1
                    if iterations > 100_000:  # S09 runtime backstop, same as FOR
                        raise SimFault("WHILE loop exceeded 100k iterations (S09)")
            elif isinstance(stmt, ReturnStatement):
                return

    def _exec_case(self, stmt: CaseStatement) -> None:
        selector = self._eval(stmt.selector)
        if isinstance(selector, bool) or not isinstance(selector, int):
            raise SimFault("CASE selector must be an integer")
        for arm in stmt.arms:
            if selector in arm.labels:
                self._execute(arm.body)
                return
        self._execute(stmt.else_body)  # empty else executes nothing (15.1)

    def _exec_for(self, stmt: ForStatement) -> None:
        var_type = self.env.types[stmt.loop_var]
        current = coerce(var_type, self._eval(stmt.start))
        stop = self._eval(stmt.stop)
        step = self._eval(stmt.step) if stmt.step is not None else 1
        iterations = 0
        while (step > 0 and current <= stop) or (step < 0 and current >= stop):
            self.env.values[stmt.loop_var] = current
            self._execute(stmt.body)
            current = coerce(var_type, current + step)
            iterations += 1
            if iterations > 100_000:  # S09 runtime backstop
                raise SimFault("FOR loop exceeded 100k iterations (S09)")
        # IEC 61131-3: after the loop the variable equals stop + step (15.1)
        self.env.values[stmt.loop_var] = coerce(var_type, current)

    # -- expressions ------------------------------------------------------------
    def _truthy(self, value: object) -> bool:
        if not isinstance(value, bool):
            raise SimFault(f"condition must be BOOL, got {type(value).__name__}")
        return value

    def _assign(self, name: str, value: object) -> None:
        if name not in self.env.types:
            raise SimFault(f"assignment to undeclared variable {name!r}")
        self.env.values[name] = coerce(self.env.types[name], value)
        self.instrument.on_var_write(name, self.env.values[name])

    def _read(self, name: str) -> object:
        if name not in self.env.values:
            raise SimFault(f"read of undeclared variable {name!r}")
        value = self.env.values[name]
        self.instrument.on_var_read(name, value)
        return value

    def _eval(self, expr: object) -> object:
        if isinstance(expr, VarRef):
            timer = self.env.timers.get(expr.name)
            if timer is not None:
                return timer.q  # FB member access .Q/.ET arrives in W2
            return self._read(expr.name)
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, Unary):
            value = self._eval(expr.operand)
            if expr.op == "NOT":
                return not self._truthy(value)
            if expr.op == "-":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise SimFault("unary - requires a number")
                return coerce(REAL if isinstance(value, float) else DINT, -value)
            raise SimFault(f"unknown unary operator {expr.op!r}")
        if isinstance(expr, Binary):
            return self._eval_binary(expr)
        raise SimFault(f"cannot evaluate {type(expr).__name__}")

    def _eval_binary(self, expr: Binary) -> object:
        # Full evaluation, no short-circuit (15.1).
        left = self._eval(expr.left)
        right = self._eval(expr.right)
        op = expr.op

        if op in ("AND", "OR", "XOR"):
            left_b, right_b = self._truthy(left), self._truthy(right)
            return {"AND": left_b and right_b,
                    "OR": left_b or right_b,
                    "XOR": left_b != right_b}[op]

        if op in ("=", "<>", "<", ">", "<=", ">="):
            if isinstance(left, bool) != isinstance(right, bool):
                raise SimFault(f"cannot compare bool with {type(right).__name__} (S03)")
            return {"=": left == right, "<>": left != right, "<": left < right,
                    ">": left > right, "<=": left <= right, ">=": left >= right}[op]

        if op in ("+", "-", "*"):
            result = {"+": left + right, "-": left - right, "*": left * right}[op]
            return coerce(REAL if isinstance(result, float) else DINT, result)

        if op == "/":
            if right == 0:
                raise SimFault("division by zero (S13)")
            if isinstance(left, float) or isinstance(right, float):
                return coerce(REAL, left / right)
            quotient = abs(left) // abs(right)  # C99/matIEC truncation
            if (left < 0) != (right < 0):
                quotient = -quotient
            return coerce(DINT, quotient)

        if op == "MOD":
            if right == 0:
                raise SimFault("MOD by zero (S13)")
            quotient = abs(left) // abs(right)  # sign follows dividend (C %)
            if (left < 0) != (right < 0):
                quotient = -quotient
            return coerce(DINT, left - quotient * right)

        raise SimFault(f"unknown operator {op!r}")

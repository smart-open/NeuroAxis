"""AST for the ST subset. All nodes are frozen: the IR, static checker and
generator share the same tree, so immutability protects consistency."""

from __future__ import annotations

from dataclasses import dataclass, field

from plcagent.st.types import StType


@dataclass(frozen=True, slots=True)
class VarRef:
    name: str


@dataclass(frozen=True, slots=True)
class Literal:
    st_type: StType
    value: object


@dataclass(frozen=True, slots=True)
class Unary:
    op: str  # "NOT" | "-"
    operand: Expr


@dataclass(frozen=True, slots=True)
class Binary:
    op: str  # AND OR XOR + - * / MOD = <> < > <= >=
    left: Expr
    right: Expr


Expr = VarRef | Literal | Unary | Binary


@dataclass(frozen=True, slots=True)
class Assignment:
    target: str
    expr: Expr


@dataclass(frozen=True, slots=True)
class IfStatement:
    branches: tuple[tuple[Expr, tuple[Statement, ...]], ...]  # (cond, body) chains
    else_body: tuple[Statement, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseArm:
    labels: tuple[int, ...]
    body: tuple[Statement, ...]


@dataclass(frozen=True, slots=True)
class CaseStatement:
    selector: Expr
    arms: tuple[CaseArm, ...]
    else_body: tuple[Statement, ...] = ()


@dataclass(frozen=True, slots=True)
class ForStatement:
    loop_var: str
    start: Expr
    stop: Expr
    step: Expr | None
    body: tuple[Statement, ...]


@dataclass(frozen=True, slots=True)
class WhileStatement:
    cond: Expr
    body: tuple[Statement, ...]


@dataclass(frozen=True, slots=True)
class ReturnStatement:
    pass


Statement = (Assignment | IfStatement | CaseStatement | ForStatement
             | WhileStatement | ReturnStatement)


@dataclass(frozen=True, slots=True)
class VarDecl:
    name: str
    st_type: StType
    init: Expr | None = None
    direction: str = "local"  # input / output / local


@dataclass(frozen=True, slots=True)
class Pou:
    name: str
    pou_type: str  # program | function_block
    decls: tuple[VarDecl, ...] = field(default=())
    body: tuple[Statement, ...] = field(default=())

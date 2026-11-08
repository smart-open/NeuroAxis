"""IR model (3.3): frozen Pydantic types, guards are syntax trees not strings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class IrExpr(_Frozen):
    """Expression syntax tree: VAR / LIT / NOT / AND / OR / XOR / CMP / ARITH."""

    kind: str
    op: str | None = None
    name: str | None = None        # VAR
    value: bool | int | float | str | None = None   # LIT (TIME arrives as ms int)
    left: IrExpr | None = None
    right: IrExpr | None = None
    operand: IrExpr | None = None


class IrIo(_Frozen):
    name: str
    direction: str                 # in / out
    address: str
    st_type: str = "BOOL"
    desc: str = ""


class IrParam(_Frozen):
    name: str
    st_type: str
    value: bool | int | float
    desc: str = ""
    hmi_writable: bool = True


class IrAction(_Frozen):
    target: str
    # str covers identifier references (e.g. Conv_Run := Manual_Jog):
    # the generator renders them as variable reads, literals as constants.
    value: bool | int | float | str


class IrState(_Frozen):
    name: str
    entry: tuple[IrAction, ...] = ()


class IrTransition(_Frozen):
    from_state: str                # "*" allowed
    to_state: str
    guard: IrExpr
    priority: int


class IrMachine(_Frozen):
    name: str
    initial_state: str
    states: tuple[IrState, ...]
    transitions: tuple[IrTransition, ...]


class IrSequence(_Frozen):
    name: str
    template: str                  # ExtendRetract / StartStopHold / PulseWait
    bind: dict[str, str]


class IrInterlock(_Frozen):
    guard: IrExpr
    actions: tuple[IrAction, ...]
    manual_only: bool = False
    desc: str = ""


class IrCompute(_Frozen):
    name: str
    expr: IrExpr


class IrAlarm(_Frozen):
    code: str
    cond: IrExpr
    text: str
    level: str


class IrProject(_Frozen):
    spec_hash: str                 # traceability: which spec version produced this
    scan_ms: int
    io: tuple[IrIo, ...]
    params: tuple[IrParam, ...] = ()
    machines: tuple[IrMachine, ...] = ()
    sequences: tuple[IrSequence, ...] = ()
    interlocks: tuple[IrInterlock, ...] = ()
    compute: tuple[IrCompute, ...] = ()
    alarms: tuple[IrAlarm, ...] = ()
    modes: tuple[str, ...] = ()

IrExpr.model_rebuild()

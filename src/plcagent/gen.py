"""IR -> ST generator (3.4). Deterministic templates, SpecHash header.

Outputs:
  GVL_Main.st        IO address mapping + params (documentation layer)
  PRG_Main.st        runnable combined program (state machines + entry
                     actions + interlock fallback last, R03)
  FB_Machine_<N>.st  one function block per machine (export form)
  PRG_Alarm.st       alarm conditions (documentation form)

The interpreter is single-POU until W4, so the runnable form is the
combined program. Sequence member guards (Seq.done) raise GenError:
FB call syntax lands with the sequence templates in W4.
"""

from __future__ import annotations

from dataclasses import dataclass

from plcagent.spec.ir_model import (
    IrAction,
    IrExpr,
    IrMachine,
    IrProject,
)


class GenError(ValueError):
    """The IR contains something the current generator cannot express."""


@dataclass(frozen=True)
class RenderResult:
    files: dict[str, str]
    combined: str


def _header(spec_hash: str, title: str) -> str:
    # S23: every generated file carries the SpecHash for traceability.
    return f"// NeuroAxis generated ST - {title}\n// SpecHash: {spec_hash}\n"


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def _render_expr(expr: IrExpr, modes: tuple[str, ...]) -> str:
    """IrExpr tree -> ST expression text."""
    if expr.kind == "VAR":
        name = expr.name or ""
        if name == "mode":
            raise GenError("bare 'mode' needs comparison: mode=<ModeName>")
        if name in modes:
            return f"Mode_{name}"       # mode enum value renders as BOOL input
        return name
    if expr.kind == "LIT":
        return _value(expr.value)
    if expr.kind == "NOT":
        return f"NOT {_render_expr(expr.operand, modes)}"
    if expr.kind == "NEG":
        return f"(-{_render_expr(expr.operand, modes)})"
    if expr.kind == "MEMBER":
        member = expr.right.name if expr.right else "?"
        raise GenError(
            f"sequence member access {expr.name}.{member} "
            f"not supported until W4 sequence templates")
    if expr.kind in ("BIN", "CMP"):
        left, right = expr.left, expr.right
        if expr.op == "=" and left and right:
            # mode=Auto renders as the single BOOL input Mode_Auto
            if left.kind == "VAR" and left.name == "mode" and right.kind == "VAR":
                return _render_expr(right, modes)
            if right.kind == "VAR" and right.name == "mode" and left.kind == "VAR":
                return _render_expr(left, modes)
        return f"({_render_expr(left, modes)} {expr.op} {_render_expr(right, modes)})"
    raise GenError(f"cannot render expression kind {expr.kind!r}")


def _render_action(action: IrAction, modes: tuple[str, ...]) -> str:
    if isinstance(action.value, str):
        # identifier reference (e.g. Conv_Run := Manual_Jog)
        rendered = _render_expr(IrExpr(kind="VAR", name=action.value), modes)
    else:
        rendered = _value(action.value)
    return f"{action.target} := {rendered};"


def _state_index(machine: IrMachine, state_name: str) -> int:
    for index, state in enumerate(machine.states):
        if state.name == state_name:
            return index
    raise GenError(f"state {state_name!r} not in machine {machine.name}")


def _render_if_chain(machine: IrMachine, edges, modes: tuple[str, ...],
                     state_var: str) -> str:
    """Edges sorted prio-asc become an IF/ELSIF chain (first hit wins)."""
    ordered = sorted(edges, key=lambda t: (t.priority, t.to_state))
    lines: list[str] = []
    for position, edge in enumerate(ordered):
        guard = _render_expr(edge.guard, modes)
        target = _state_index(machine, edge.to_state)
        keyword = "IF" if position == 0 else "ELSIF"
        lines.append(f"{keyword} {guard} THEN {state_var} := {target};")
    lines.append("END_IF;")
    return " ".join(lines)


def _machine_logic(machine: IrMachine, modes: tuple[str, ...],
                   state_var: str, prev_var: str) -> str:
    """Wildcard edges (prio asc) then per-state CASE, then entry actions."""
    lines: list[str] = []
    wildcards = sorted(
        (t for t in machine.transitions if t.from_state == "*"),
        key=lambda t: (t.priority, t.to_state))
    for edge in wildcards:
        guard = _render_expr(edge.guard, modes)
        target = _state_index(machine, edge.to_state)
        lines.append(f"IF {guard} THEN {state_var} := {target}; END_IF;")

    lines.append(f"CASE {state_var} OF")
    for index, state in enumerate(machine.states):
        edges = [t for t in machine.transitions if t.from_state == state.name]
        if not edges:
            continue
        chain = _render_if_chain(machine, edges, modes, state_var)
        lines.append(f"{index}: {chain}")
    lines.append("END_CASE;")

    # entry actions fire once on the state-change edge; PrevState starts at -1
    # so the first scan executes the initial state's entry actions.
    lines.append(f"IF {state_var} <> {prev_var} THEN")
    lines.append(f"CASE {state_var} OF")
    for index, state in enumerate(machine.states):
        actions = " ".join(_render_action(a, modes) for a in state.entry)
        if actions:
            lines.append(f"{index}: {actions}")
    lines.append("END_CASE;")
    lines.append(f"{prev_var} := {state_var};")
    lines.append("END_IF;")
    return "\n".join(lines)


def _interlock_logic(ir: IrProject, modes: tuple[str, ...]) -> str:
    """R03: interlocks render after all machine logic (last write wins)."""
    lines: list[str] = []
    for interlock in ir.interlocks:
        guard = _render_expr(interlock.guard, modes)
        lines.append(f"// interlock: {interlock.desc or 'unspecified'}")
        lines.append(f"IF {guard} THEN")
        for action in interlock.actions:
            lines.append(f"  {_render_action(action, modes)}")
        lines.append("END_IF;")
    return "\n".join(lines)


def _decl_block(direction: str, ir: IrProject, modes: tuple[str, ...]) -> list[str]:
    # direction is the ST header ("INPUT"/"OUTPUT"); IO stores "in"/"out".
    lines = [f"VAR_{direction}"]
    wanted = "in" if direction == "INPUT" else "out"
    for io in ir.io:
        if io.direction == wanted:
            lines.append(f"    {io.name} : {io.st_type};  // {io.address} {io.desc}")
    if direction == "INPUT":
        for mode in modes:
            lines.append(f"    Mode_{mode} : BOOL;  // mode switch for {mode}")
    lines.append("END_VAR")
    return lines


def render(ir: IrProject) -> RenderResult:
    """Deterministic render: same IR -> byte-identical files."""
    modes = ir.modes
    files: dict[str, str] = {}

    # --- GVL: documentation of the IO mapping + params ---
    gvl = [_header(ir.spec_hash, "GVL_Main"), "// IO mapping (dialect conversion at export)"]
    for io in ir.io:
        gvl.append(f"// {io.name:16s} {io.address:8s} {io.direction:3s} {io.desc}")
    for param in ir.params:
        gvl.append(f"// param {param.name}: {param.st_type} = {param.value} {param.desc}")
    files["GVL_Main.st"] = "\n".join(gvl) + "\n"

    # --- combined runnable program ---
    body: list[str] = [_header(ir.spec_hash, "PRG_Main"), "PROGRAM Main"]
    body += _decl_block("INPUT", ir, modes)
    body += _decl_block("OUTPUT", ir, modes)
    body.append("VAR")
    for machine in ir.machines:
        state_var = f"State_{machine.name}"
        prev_var = f"PrevState_{machine.name}"
        initial = _state_index(machine, machine.initial_state)
        body.append(f"    {state_var} : DINT := {initial};")
        # -1 guarantees the first scan runs the initial state's entry actions
        body.append(f"    {prev_var} : DINT := -1;")
    body.append("END_VAR")
    for machine in ir.machines:
        state_var = f"State_{machine.name}"
        prev_var = f"PrevState_{machine.name}"
        body.append(f"// ---- machine {machine.name} ----")
        body.append(_machine_logic(machine, modes, state_var, prev_var))
    if ir.interlocks:
        body.append("// ---- interlocks (R03: after machine logic, last write wins) ----")
        body.append(_interlock_logic(ir, modes))
    body.append("END_PROGRAM")
    combined = "\n".join(body) + "\n"
    files["PRG_Main.st"] = combined

    # --- per-machine FB (export form; runnable FB calls arrive in W4) ---
    for machine in ir.machines:
        fb = [_header(ir.spec_hash, f"FB_Machine_{machine.name}"),
              f"FUNCTION_BLOCK FB_Machine_{machine.name}"]
        fb += _decl_block("INPUT", ir, modes)
        state_var = "State"
        fb.append("VAR_OUTPUT")
        fb.append("    State : DINT;")
        for io in ir.io:
            if io.direction == "out":
                fb.append(f"    {io.name} : {io.st_type};")
        fb.append("END_VAR")
        fb.append("VAR")
        fb.append("    PrevState : DINT := -1;")
        fb.append("END_VAR")
        fb.append(_machine_logic(machine, modes, state_var, "PrevState"))
        fb.append("END_FUNCTION_BLOCK")
        files[f"FB_Machine_{machine.name}.st"] = "\n".join(fb) + "\n"

    # --- alarms (documentation form; alarm outputs are W4 with HMI) ---
    alarm_lines = [_header(ir.spec_hash, "PRG_Alarm")]
    for alarm in ir.alarms:
        try:
            cond = _render_expr(alarm.cond, modes)
            alarm_lines.append(f"// {alarm.code} [{alarm.level}] {alarm.text}")
            alarm_lines.append(f"// cond: {cond}")
        except GenError:
            alarm_lines.append(f"// {alarm.code} [{alarm.level}] {alarm.text}")
            alarm_lines.append("// cond: <sequence member - renders with W4 templates>")
    files["PRG_Alarm.st"] = "\n".join(alarm_lines) + "\n"

    return RenderResult(files=files, combined=combined)

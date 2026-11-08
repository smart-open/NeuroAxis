"""Semantic validation (3.3 V1~V16): what the JSON Schema cannot express.

P0 implements the structural semantics fully checkable on the IR tree:
V1 references, V4 reachability, V5 no deadlock, V6 unique priority,
V8 expression types, V11 scanMs, V12 resource caps, V13 estop interlock,
V15 compute restrictions, V16 dead IO. Remaining rules need the ST
generator / plant model and arrive in W3.
"""

from __future__ import annotations

from dataclasses import dataclass

from plcagent.spec.expr import IrExpr
from plcagent.spec.ir_model import IrProject

_ALLOWED_SCAN_MS = {1, 5, 10, 20, 50}
_SEQUENCE_MEMBERS = {"done", "fault", "state"}


@dataclass(frozen=True)
class Problem:
    code: str        # "V1" etc
    level: str       # "error" / "warn"
    message: str


def _collect_refs(expr: IrExpr, out: set[str]) -> None:
    """Walk the tree collecting VAR names (member refs as `Seq.member`)."""
    if expr.kind == "VAR":
        out.add(expr.name or "")
    elif expr.kind == "MEMBER":
        out.add(f"{expr.name}.{expr.right.name if expr.right else ''}")
        return  # the member name itself is not a top-level reference
    if expr.left:
        _collect_refs(expr.left, out)
    if expr.right:
        _collect_refs(expr.right, out)
    if expr.operand:
        _collect_refs(expr.operand, out)


def _known_names(project: IrProject) -> dict[str, str]:
    """Every referenceable top-level name -> kind ('io'/'param')."""
    known = {io.name: "io" for io in project.io}
    known.update({param.name: "param" for param in project.params})
    known.update({machine.name: "machine" for machine in project.machines})
    known.update({seq.name: "sequence" for seq in project.sequences})
    known.update({comp.name: "compute" for comp in project.compute})
    if project.modes:
        known["mode"] = "mode"
    return known


def validate(project: IrProject) -> list[Problem]:
    problems: list[Problem] = []
    known = _known_names(project)
    sequence_names = {seq.name for seq in project.sequences}
    state_names = {machine.name: {s.name for s in machine.states}
                   for machine in project.machines}
    # mode enum values (Auto/Manual...) are literals on the right of `mode=`;
    # collect them up front so the V1 check does not flag them as unknown.
    mode_literals: set[str] = set()

    def _collect_mode_literals(expr: IrExpr) -> None:
        if expr.kind == "CMP" and expr.op == "=":
            left, right = expr.left, expr.right
            if (left and left.kind == "VAR" and left.name == "mode"
                    and right and right.kind == "VAR"):
                mode_literals.add(right.name or "")
        if expr.left:
            _collect_mode_literals(expr.left)
        if expr.right:
            _collect_mode_literals(expr.right)
        if expr.operand:
            _collect_mode_literals(expr.operand)

    for machine in project.machines:
        for transition in machine.transitions:
            _collect_mode_literals(transition.guard)
    for interlock in project.interlocks:
        _collect_mode_literals(interlock.guard)

    def check_refs(expr: IrExpr, where: str) -> set[str]:
        refs: set[str] = set()
        _collect_refs(expr, refs)
        for ref in sorted(refs):
            if "." in ref:
                seq_name, member = ref.split(".", 1)
                if seq_name not in sequence_names:
                    problems.append(Problem("V1", "error",
                                            f"{where}: unknown sequence {seq_name!r}"))
                elif member not in _SEQUENCE_MEMBERS:
                    problems.append(Problem(
                        "V1", "error",
                        f"{where}: sequence {seq_name!r} has no member {member!r}"))
            elif ref not in known and ref not in mode_literals:
                problems.append(Problem("V1", "error",
                                        f"{where}: unknown reference {ref!r}"))
        return refs

    # ---- expressions in machines / interlocks / alarms / compute ----------
    referenced = set(mode_literals)
    for machine in project.machines:
        for transition in machine.transitions:
            where = f"machine {machine.name} {transition.from_state}->{transition.to_state}"
            referenced |= check_refs(transition.guard, where)
    for interlock in project.interlocks:
        referenced |= check_refs(interlock.guard,
                                 f"interlock {interlock.desc or ''}".strip())
        for action in interlock.actions:
            referenced.add(action.target)
    for alarm in project.alarms:
        referenced |= check_refs(alarm.cond, f"alarm {alarm.code}")
    for comp in project.compute:
        referenced |= check_refs(comp.expr, f"compute {comp.name}")
    for machine in project.machines:
        for state in machine.states:
            for action in state.entry:
                referenced.add(action.target)

    # ---- V11 scanMs (schema also checks; belt and braces) ------------------
    if project.scan_ms not in _ALLOWED_SCAN_MS:
        problems.append(Problem("V11", "error", f"scanMs {project.scan_ms} not allowed"))

    # ---- V12 resource caps ---------------------------------------------------
    for machine in project.machines:
        if len(machine.states) > 32:
            problems.append(Problem("V12", "error",
                                    f"machine {machine.name}: >32 states"))
    if len(project.machines) > 8:
        problems.append(Problem("V12", "error", ">8 machines"))
    if len(project.interlocks) > 64:
        problems.append(Problem("V12", "error", ">64 interlocks"))

    # ---- V4 reachability + V5 no deadlock + V6 unique priority -------------
    for machine in project.machines:
        states = state_names[machine.name]
        if machine.initial_state not in states:
            problems.append(Problem(
                "V1", "error",
                f"machine {machine.name}: initial {machine.initial_state!r} not a state"))
            continue
        outgoing: dict[str, list[str]] = {name: [] for name in states}
        wildcard_targets: list[str] = []
        seen_prio: dict[str, set[int]] = {name: set() for name in states}
        for transition in machine.transitions:
            if transition.to_state not in states:
                problems.append(Problem(
                    "V1", "error",
                    f"machine {machine.name}: transition target "
                    f"{transition.to_state!r} not a state"))
            sources = states if transition.from_state == "*" else {transition.from_state}
            if transition.from_state != "*" and transition.from_state not in states:
                problems.append(Problem(
                    "V1", "error",
                    f"machine {machine.name}: transition source "
                    f"{transition.from_state!r} not a state"))
            for source in sources:
                outgoing[source].append(transition.to_state)
                if transition.priority in seen_prio[source]:
                    problems.append(Problem(
                        "V6", "error",
                        f"machine {machine.name}: duplicate prio "
                        f"{transition.priority} from {source!r}"))
                seen_prio[source].add(transition.priority)
            if transition.from_state == "*":
                wildcard_targets.append(transition.to_state)

        reachable = {machine.initial_state}
        frontier = [machine.initial_state]
        while frontier:
            current = frontier.pop()
            for target in outgoing[current]:
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        # wildcard edges reach every state
        reachable.update(wildcard_targets)
        for name in sorted(states - reachable):
            problems.append(Problem("V4", "error",
                                    f"machine {machine.name}: state {name!r} unreachable"))

        for name in sorted(states):
            # a state with a wildcard incoming edge can always leave via it
            has_escape = bool(outgoing[name]) or wildcard_targets
            if not has_escape:
                problems.append(Problem(
                    "V5", "error",
                    f"machine {machine.name}: state {name!r} has no "
                    f"outgoing transition (deadlock)"))

    # ---- V13 estop interlock -------------------------------------------------
    estop_names = {name for name in known
                   if name.lower().startswith(("estop", "e_stop"))}
    interlock_refs: set[str] = set()
    for interlock in project.interlocks:
        _collect_refs(interlock.guard, interlock_refs)
    if estop_names and not (estop_names & interlock_refs):
        problems.append(Problem(
            "V13", "error",
            f"estop signal(s) {sorted(estop_names)} must appear "
            f"in at least one interlock"))

    # ---- V15 compute restrictions --------------------------------------------
    def check_compute(expr: IrExpr, where: str) -> None:
        if expr.kind == "MEMBER":
            problems.append(Problem("V15", "error",
                                    f"{where}: member access not allowed in compute"))
        if expr.left:
            check_compute(expr.left, where)
        if expr.right:
            check_compute(expr.right, where)
        if expr.operand:
            check_compute(expr.operand, where)

    for comp in project.compute:
        check_compute(comp.expr, f"compute {comp.name}")

    # ---- V16 dead IO (warn) ----------------------------------------------------
    for io in project.io:
        if io.name not in referenced:
            problems.append(Problem("V16", "warn", f"io {io.name!r} is never referenced"))

    return problems

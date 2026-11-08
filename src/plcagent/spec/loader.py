"""Spec loading (W2): YAML/JSON -> schema validation -> IrProject.

Division of labor (21.1): the JSON Schema checks structure, the semantic
validator checks what a schema cannot express (V1~V16 code rules).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import yaml

from plcagent.spec import validator as spec_validator
from plcagent.spec.expr import SpecExprError, parse_spec_expr
from plcagent.spec.ir_model import (
    IrAction,
    IrAlarm,
    IrCompute,
    IrInterlock,
    IrIo,
    IrMachine,
    IrParam,
    IrProject,
    IrSequence,
    IrState,
    IrTransition,
)

_SCHEMA_PATH = Path(__file__).parent / "schemas" / "spec.schema.json"
_ACTION_RE_VALUE = {"0": False, "1": True, "TRUE": True, "FALSE": False}


class SpecError(ValueError):
    """Spec is structurally or semantically invalid; message lists reasons."""


def load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def load_spec_text(text: str) -> dict:
    """Parse YAML/JSON text and validate against the JSON Schema."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"YAML parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError("spec root must be a mapping")
    # YAML empty blocks (`interlocks:` with no items) parse as None; the schema
    # requires arrays, so normalize them to [] before validation.
    for key in ("params", "sequences", "interlocks", "alarms", "compute", "modes"):
        if data.get(key) is None:
            data[key] = []
    schema = load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        lines = []
        for err in errors[:10]:
            path = ".".join(str(p) for p in err.absolute_path) or "<root>"
            lines.append(f"  {path}: {err.message}")
        raise SpecError("schema validation failed:\n" + "\n".join(lines))
    return data


def _parse_action(raw: str) -> IrAction:
    """`Var:=1` / `Var` (implicit TRUE) -> IrAction; schema already shape-checked."""
    if ":=" in raw:
        target, value_text = raw.split(":=", 1)
        value_text = value_text.strip()
        if value_text in _ACTION_RE_VALUE:
            value: bool | int | float = _ACTION_RE_VALUE[value_text]
        else:
            try:
                value = int(value_text)
            except ValueError:
                try:
                    value = float(value_text)
                except ValueError:
                    value = value_text   # identifier reference (e.g. manual_jog)
        return IrAction(target=target.strip(), value=value)
    return IrAction(target=raw.strip(), value=True)


def build_ir(data: dict) -> IrProject:
    """Convert schema-valid spec dict into IrProject; parses all expressions."""
    io_entries: list[IrIo] = []
    for group in ("digital", "analog"):
        for item in (data.get("io") or {}).get(group, []):
            io_entries.append(IrIo(
                name=item["name"], direction=item["dir"], address=item["addr"],
                st_type=item.get("type", "BOOL"), desc=item.get("desc", "")))

    params = tuple(IrParam(
        name=p["name"], st_type=p["type"],
        value=_coerce_param(p["type"], p["value"]),
        desc=p.get("desc", ""), hmi_writable=p.get("hmiWritable", True),
    ) for p in data.get("params") or [])

    machines = []
    for machine in data.get("machines", []):
        states = tuple(IrState(
            name=s["name"],
            entry=tuple(_parse_action(a) for a in s.get("entry", [])),
        ) for s in machine["states"])
        try:
            transitions = tuple(IrTransition(
                from_state=t["from"], to_state=t["to"],
                guard=parse_spec_expr(t["when"]), priority=t["prio"],
            ) for t in machine["transitions"])
        except SpecExprError as exc:
            raise SpecError(f"machine {machine['name']!r}: {exc}") from exc
        machines.append(IrMachine(
            name=machine["name"], initial_state=machine["initial"],
            states=states, transitions=transitions))

    sequences = tuple(IrSequence(
        name=s["name"], template=s["type"], bind=dict(s.get("bind", {})),
    ) for s in data.get("sequences") or [])

    interlocks = []
    for entry in data.get("interlocks") or []:
        try:
            guard = parse_spec_expr(entry["when"])
        except SpecExprError as exc:
            raise SpecError(f"interlock: {exc}") from exc
        interlocks.append(IrInterlock(
            guard=guard, actions=tuple(_parse_action(a) for a in entry["then"]),
            manual_only=entry.get("manualOnly", False), desc=entry.get("desc", "")))

    compute = []
    for entry in data.get("compute") or []:
        try:
            compute.append(IrCompute(name=entry["name"], expr=parse_spec_expr(entry["expr"])))
        except SpecExprError as exc:
            raise SpecError(f"compute {entry['name']!r}: {exc}") from exc

    alarms = []
    for entry in data.get("alarms") or []:
        try:
            cond = parse_spec_expr(entry["cond"])
        except SpecExprError as exc:
            raise SpecError(f"alarm {entry['code']!r}: {exc}") from exc
        alarms.append(IrAlarm(
            code=entry["code"], cond=cond, text=entry["text"], level=entry["level"]))

    return IrProject(
        spec_hash=spec_hash(data),
        scan_ms=data["project"]["scanMs"],
        io=tuple(io_entries),
        params=params,
        machines=tuple(machines),
        sequences=sequences,
        interlocks=tuple(interlocks),
        compute=tuple(compute),
        alarms=tuple(alarms),
        modes=tuple(data.get("modes") or []),
    )


def _coerce_param(st_type: str, value):
    if st_type == "BOOL":
        if not isinstance(value, bool):
            raise SpecError(f"param {st_type} value must be bool")
        return value
    if st_type == "TIME":
        # YAML may give int ms or a string like "2s" / "T#2s"
        if isinstance(value, int):
            return value
        from plcagent.st.parser import parse_time_ms

        text_value = str(value)
        if "#" not in text_value:
            text_value = "T#" + text_value
        return parse_time_ms(text_value)
    if st_type in ("INT", "DINT"):
        return int(value)
    return float(value)


def spec_hash(data: dict) -> str:
    """Canonical SHA256 over the spec dict (sort keys, no whitespace)."""
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_spec(text: str) -> IrProject:
    """One call: text -> schema check -> IR build -> semantic validation."""
    data = load_spec_text(text)
    project = build_ir(data)
    problems = spec_validator.validate(project)
    if any(p.level == "error" for p in problems):
        lines = [f"  [{p.level}] {p.code}: {p.message}" for p in problems]
        raise SpecError("semantic validation failed:\n" + "\n".join(lines))
    return project

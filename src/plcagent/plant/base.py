"""Component base + registry (5.3 registration mechanism).

New device = subclass BaseComponent, implement step(), decorate with
@ComponentRegistry.register("kind"). Neither the interpreter nor the DSL
Runner changes - that is the hard extensibility requirement.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class FaultSpec:
    """One injected fault on one signal (5.3 fault matrix subset)."""

    kind: str        # stuck_0 / stuck_1 / drift / delay_ms / noisy
    value: float = 0.0


class BaseComponent:
    """Family-agnostic base: bind to a PlantSim, step at 1ms, take faults."""

    kind: str = "?"
    defaults: dict = {}
    # ports the component writes into the PLC input image, with defaults,
    # so signals are readable before the first physics step (no KeyError).
    in_ports: dict = {}
    # ports the component reads from the PLC output image, with defaults,
    # so physics stepping works before the program writes anything.
    out_ports: dict = {}

    def __init__(self, name: str, params: dict | None = None) -> None:
        self.name = name
        # component params are calibratable; unknown keys are a config error
        unknown = set(params or {}) - set(self.defaults)
        if unknown:
            raise ValueError(
                f"component {self.kind}/{name}: unknown params {sorted(unknown)}")
        self.params = {**self.defaults, **(params or {})}
        self.faults: dict[str, FaultSpec] = {}
        self.plant = None  # bound by PlantSim.bind()

    # -- signal helpers ------------------------------------------------------
    def out(self, port: str) -> object:
        """Read a PLC output image value (PLC -> plant direction)."""
        key = f"{self.name}_{port}"
        if key not in self.plant.outputs:
            return self.out_ports.get(port, False)
        return self.plant.outputs[key]

    def write_in(self, port: str, value: object) -> None:
        """Write a PLC input image value (plant -> PLC direction)."""
        self.plant.inputs[f"{self.name}_{port}"] = value

    def inject(self, port: str, fault: FaultSpec) -> None:
        self.faults[port] = fault

    def clear_faults(self) -> None:
        self.faults.clear()

    def _faulted(self, port: str, live_value: object) -> object:
        """Apply the active fault transform to a live sensor value."""
        fault = self.faults.get(port)
        if fault is None:
            return live_value
        if fault.kind == "stuck_0":
            return False if isinstance(live_value, bool) else 0
        if fault.kind == "stuck_1":
            return True if isinstance(live_value, bool) else 1
        if fault.kind == "drift" and isinstance(live_value, (int, float)):
            return live_value * (1.0 + fault.value)
        return live_value

    def step(self, dt: float) -> None:
        """Advance physics by dt seconds (fixed 1ms from PlantSim)."""
        raise NotImplementedError

    def drive(self, method: str, args: dict) -> None:
        """Scripted behaviour (push_item etc.); default: unsupported."""
        raise ValueError(f"{self.kind}/{self.name} has no drive method {method!r}")


class ComponentRegistry:
    """kind -> factory; PlantSim instantiates from plant config by kind."""

    _factories: dict[str, Callable[[str, dict], BaseComponent]] = {}

    @classmethod
    def register(cls, kind: str) -> Callable:
        def decorator(component_cls):
            if kind in cls._factories:
                raise ValueError(f"component kind {kind!r} already registered")
            component_cls.kind = kind
            cls._factories[kind] = component_cls
            return component_cls
        return decorator

    @classmethod
    def create(cls, kind: str, name: str, params: dict | None = None) -> BaseComponent:
        if kind not in cls._factories:
            raise ValueError(f"unknown component kind {kind!r}")
        return cls._factories[kind](name, params)

    @classmethod
    def kinds(cls) -> list[str]:
        return sorted(cls._factories)

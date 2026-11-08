"""Plant simulation engine (5.1): fixed 1ms physics steps inside each scan.

The PlantSim owns the input/output images. Per scan: read PLC output image
(written by the interpreter last scan), advance every component in
registration order by scanMs steps of 1ms, write results into the input
image for the next scan. Fully deterministic - no wall clock, no RNG.
"""

from __future__ import annotations

from plcagent.plant.base import BaseComponent, ComponentRegistry, FaultSpec


class PlantSim:
    """Container of components bound to shared IO images."""

    def __init__(self) -> None:
        self.inputs: dict[str, object] = {}     # plant -> PLC
        self.outputs: dict[str, object] = {}    # PLC -> plant
        self.components: list[BaseComponent] = []
        # signals written directly by the DSL (set/init); bridges must not
        # overwrite them - the test script is the last word on these points
        self.direct_inputs: set[str] = set()

    def add(self, kind: str, name: str, params: dict | None = None) -> BaseComponent:
        component = ComponentRegistry.create(kind, name, params)
        component.plant = self
        # pre-initialise every declared input port so DSL reads never hit
        # a missing key before the first physics step
        for port, default in component.in_ports.items():
            self.inputs[f"{name}_{port}"] = default
        self.components.append(component)
        return component

    def get(self, name: str) -> BaseComponent:
        for component in self.components:
            if component.name == name:
                return component
        raise ValueError(f"no plant component named {name!r}")

    def inject(self, component: str, port: str, fault: FaultSpec) -> None:
        self.get(component).inject(port, fault)

    def drive(self, target: str, method: str, args: dict | None = None) -> None:
        """DSL `drive:` support: component.method(args)."""
        self.get(target).drive(method, args or {})

    def step_scan(self, scan_ms: int) -> None:
        """Advance all components: scanMs steps of 1ms each (5.1)."""
        for _ in range(scan_ms):
            for component in self.components:
                component.step(1)

    def snapshot(self) -> dict:
        """Full state snapshot for replay/debug (5.1)."""
        return {
            "inputs": dict(self.inputs),
            "outputs": dict(self.outputs),
            "components": {
                c.name: dict(vars(c)) for c in self.components},
        }

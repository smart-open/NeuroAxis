"""Virtual plant device library (5.3)."""

from plcagent.plant.base import (
    BaseComponent as BaseComponent,
)
from plcagent.plant.base import (
    ComponentRegistry as ComponentRegistry,
)
from plcagent.plant.base import (
    FaultSpec as FaultSpec,
)
from plcagent.plant.components import (  # noqa: F401
    Conveyor,
    Cylinder,
    Encoder,
    Heater,
    ModulatingValve,
    Motor,
    Photoelectric,
    Pump,
    SafetyCircuit,
    SwitchValve,
    Tank,
    Transmitter,
)
from plcagent.plant.sim import PlantSim as PlantSim

# importing this package registers all built-in components

"""12 core plant components across the four families (5.3 W4 scope).

Naming convention: every component port maps to a PLC signal
`{component_name}_{port}` (e.g. conv_pe_out). Deterministic: no randomness
(noise injection lands with the W5 seeded RNG).
"""

from __future__ import annotations

from plcagent.plant.base import BaseComponent, ComponentRegistry

# ============================ motion & drive family =========================

@ComponentRegistry.register("motor")
class Motor(BaseComponent):
    """Induction motor with gearbox: first-order speed loop."""

    defaults = {"tau_ms": 200, "rated_rpm": 1450.0}
    in_ports = {"speed": 0.0, "running": False}
    out_ports = {"run": False}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.speed = 0.0

    def step(self, dt_ms: int) -> None:
        target = self.params["rated_rpm"] if self.out("run") else 0.0
        # first-order approach: v += (target - v) * dt/tau (deterministic)
        tau = max(self.params["tau_ms"], 1)
        self.speed += (target - self.speed) * dt_ms / tau
        if abs(self.speed) < 0.05:
            self.speed = 0.0     # snap to zero to keep traces stable
        self.write_in("speed", round(self.speed, 1))
        self.write_in("running", self.speed > self.params["rated_rpm"] * 0.05)


@ComponentRegistry.register("conveyor")
class Conveyor(BaseComponent):
    """Belt with point-mass items moving at belt speed; photoelectric at end."""

    defaults = {"length_mm": 1000, "speed_mm_s": 200.0}
    in_ports = {"pe_out": False}
    out_ports = {"motor_on": False}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.items: list[float] = []       # positions in mm
        self.sensor_on = False

    def step(self, dt_ms: int) -> None:
        if self.out("motor_on"):
            delta = self.params["speed_mm_s"] * dt_ms / 1000.0
            self.items = [pos + delta for pos in self.items]
        end = self.params["length_mm"]
        # deterministic eject order: front item first
        self.items = [pos for pos in self.items if pos < end]
        pe_pos = end - 20                  # sensor 20mm before the end
        self.sensor_on = any(abs(pos - pe_pos) < 10 for pos in self.items)
        self.write_in("pe_out", self._faulted("pe_out", self.sensor_on))

    def drive(self, method: str, args: dict) -> None:
        if method == "push_item":
            self.items.append(0.0)
            return
        super().drive(method, args)


@ComponentRegistry.register("cylinder")
class Cylinder(BaseComponent):
    """Double-stable pneumatic cylinder with uniform stroke and reed switches."""

    defaults = {"stroke_ms": 2000}
    in_ports = {"extended": False, "retracted": True}
    out_ports = {"valve_out": False}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        # integer elapsed-stroke milliseconds: immune to float accumulation
        # error (0.0005 is not exact in binary; 2000 additions may stay < 1.0)
        self.progress_ms = 0

    @property
    def progress(self) -> float:
        return min(1.0, self.progress_ms / max(self.params["stroke_ms"], 1))

    def step(self, dt_ms: int) -> None:
        stroke = max(self.params["stroke_ms"], 1)
        if self.out("valve_out"):
            self.progress_ms = min(stroke, self.progress_ms + dt_ms)
        else:
            self.progress_ms = max(0, self.progress_ms - dt_ms)
        self.write_in("extended", self._faulted("extended", self.progress_ms >= stroke))
        self.write_in("retracted", self._faulted("retracted", self.progress_ms <= 0))


@ComponentRegistry.register("photoelectric")
class Photoelectric(BaseComponent):
    """Standalone photoelectric switch driven by scripted block state."""

    defaults = {}
    in_ports = {"out": False}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.blocked = False               # set via drive

    def step(self, dt_ms: int) -> None:
        self.write_in("out", self._faulted("out", self.blocked))

    def drive(self, method: str, args: dict) -> None:
        if method == "set_blocked":
            self.blocked = bool(args.get("value", True))
            return
        super().drive(method, args)


@ComponentRegistry.register("encoder")
class Encoder(BaseComponent):
    """Incremental encoder counting a driven axis (ideal, no quadrature)."""

    defaults = {"mm_per_count": 1.0}
    in_ports = {"count": 0}
    out_ports = {"enable": False}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.count = 0

    def step(self, dt_ms: int) -> None:
        if self.out("enable"):
            # one count per scan while enabled: simple, deterministic motion
            self.count += 1
        self.write_in("count", self.count)


# ============================ process & instrument family ===================

@ComponentRegistry.register("pump")
class Pump(BaseComponent):
    """Centrifugal pump: linear flow while running."""

    defaults = {"q_max_lpm": 100.0}
    in_ports = {"flow": 0.0}
    out_ports = {"run": False}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.flow = 0.0

    def step(self, dt_ms: int) -> None:
        target = self.params["q_max_lpm"] if self.out("run") else 0.0
        # first-order response, tau=100ms fixed
        self.flow += (target - self.flow) * dt_ms / 100.0
        if abs(self.flow) < 0.05:
            self.flow = 0.0
        self.write_in("flow", round(self.flow, 1))


@ComponentRegistry.register("switch_valve")
class SwitchValve(BaseComponent):
    """On/off valve: stroke model like a cylinder with opened/closed reeds."""

    defaults = {"stroke_ms": 500}
    in_ports = {"opened": False, "closed": True}
    out_ports = {"open_cmd": False}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.progress = 0.0

    def step(self, dt_ms: int) -> None:
        stroke = max(self.params["stroke_ms"], 1)
        if self.out("open_cmd"):
            self.progress = min(1.0, self.progress + dt_ms / stroke)
        else:
            self.progress = max(0.0, self.progress - dt_ms / stroke)
        self.write_in("opened", self.progress >= 1.0)
        self.write_in("closed", self.progress <= 0.0)


@ComponentRegistry.register("modulating_valve")
class ModulatingValve(BaseComponent):
    """Modulating valve: linear characteristic between 0 and Cv."""

    defaults = {"cv_max": 10.0}
    in_ports = {"flow": 0.0}
    out_ports = {"opening": 0.0}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.flow = 0.0

    def step(self, dt_ms: int) -> None:
        opening = max(0.0, min(100.0, float(self.out("opening"))))
        target = self.params["cv_max"] * opening / 100.0
        self.flow += (target - self.flow) * dt_ms / 50.0   # 50ms response
        self.write_in("flow", round(self.flow, 2))


@ComponentRegistry.register("tank")
class Tank(BaseComponent):
    """Level tank: dv/dt = (Qi - Qo) / A with limit switches."""

    defaults = {"area": 1.0, "range_m": 2.0,
                "hi_m": 1.8, "lo_m": 0.2, "hh_m": 1.95, "ll_m": 0.05}
    in_ports = {"level": 0.0, "hi": False, "lo": True,
                "hh": False, "ll": True}
    out_ports = {"in_flow": 0.0, "out_flow": 0.0}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.level = 0.0

    def step(self, dt_ms: int) -> None:
        flow_in = float(self.out("in_flow"))
        flow_out = float(self.out("out_flow"))
        dt_s = dt_ms / 1000.0
        self.level += (flow_in - flow_out) * dt_s / self.params["area"]
        self.level = max(0.0, min(self.params["range_m"], self.level))
        self.write_in("level", round(self.level, 4))
        self.write_in("hi", self.level >= self.params["hi_m"])
        self.write_in("lo", self.level <= self.params["lo_m"])
        self.write_in("hh", self.level >= self.params["hh_m"])
        self.write_in("ll", self.level <= self.params["ll_m"])


@ComponentRegistry.register("transmitter")
class Transmitter(BaseComponent):
    """Process transmitter: linear range conversion on a scripted physical value."""

    defaults = {"range_min": 0.0, "range_max": 100.0}
    in_ports = {"value": 0.0, "pct": 0.0}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.physical = 0.0                # set via drive

    def step(self, dt_ms: int) -> None:
        lo = self.params["range_min"]
        hi = self.params["range_max"]
        span = (hi - lo) or 1.0
        value = lo + (hi - lo) * (self.physical / 100.0)
        value = self._faulted("value", value)
        # output both engineering value and normalised 0..100
        self.write_in("value", round(value, 3))
        self.write_in("pct", round((value - lo) / span * 100.0, 2))

    def drive(self, method: str, args: dict) -> None:
        if method == "set_physical":
            self.physical = float(args.get("value", 0.0))
            return
        super().drive(method, args)


@ComponentRegistry.register("heater")
class Heater(BaseComponent):
    """Heater on a thermal mass: first-order towards duty-scaled temperature."""

    defaults = {"ambient_c": 25.0, "max_rise_c": 75.0, "tau_ms": 5000}
    in_ports = {"temp": 25.0}
    out_ports = {"pwm": 0.0}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.temp = self.params["ambient_c"]

    def step(self, dt_ms: int) -> None:
        duty = min(100.0, max(0.0, float(self.out("pwm")))) / 100.0
        target = self.params["ambient_c"] + self.params["max_rise_c"] * duty
        tau = max(self.params["tau_ms"], 1)
        self.temp += (target - self.temp) * dt_ms / tau
        self.write_in("temp", round(self.temp, 2))


# ============================ detection & safety family =====================

@ComponentRegistry.register("safety_circuit")
class SafetyCircuit(BaseComponent):
    """E-stop / guard chain: safety_ok mirrors healthy inputs deterministically."""

    defaults = {}
    in_ports = {"safety_ok": True}

    def __init__(self, name: str, params: dict | None = None) -> None:
        super().__init__(name, params)
        self.estop_ok = True
        self.guard_ok = True

    def step(self, dt_ms: int) -> None:
        self.write_in("safety_ok",
                      self._faulted("safety_ok", self.estop_ok and self.guard_ok))

    def drive(self, method: str, args: dict) -> None:
        if method == "press_estop":
            self.estop_ok = bool(args.get("value", False))
            return
        if method == "set_guard":
            self.guard_ok = bool(args.get("value", True))
            return
        super().drive(method, args)

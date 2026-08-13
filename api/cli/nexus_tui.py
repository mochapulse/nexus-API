"""Textual TUI for Nexus API telemetry.

Renders a full-screen htop-style dashboard with CPU, RAM, swap, GPU,
and power sensor data from ``/api/v1/telemetry``.  Uses native
Textual widgets: ProgressBar with gradient colors and Sparkline
for CPU history.  Auto-refreshes every 2 seconds.

Usage::

    nexus-API telemetry
"""

from __future__ import annotations

from collections import deque

from textual.app import App, ComposeResult
from textual.color import Gradient
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Label,
    ProgressBar,
    Sparkline,
    Static,
)

from api.cli.http_client import nexus_get

_REFRESH_INTERVAL = 2
_SPARKLINE_SAMPLES = 30

_GRADIENT_WARN = Gradient.from_colors("#2ecc71", "#f1c40f", "#e74c3c")


def _fmt_bytes(n: int | float) -> str:
    """Format byte count to human-readable string.

    Parameters
    ----------
    n : int
        Number of bytes.

    Returns:
        Human-readable string (e.g. ``"4.2 GiB"``).
    """
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


class NexusTui(App):
    """Full-screen Textual app for Nexus telemetry."""

    CSS = """
    Screen { background: $surface }
    .section { height: auto; margin: 0 1; padding: 0 1; }
    .bar-row { height: 1; }
    .bar-label { width: 6; }
    .sparkline-row { height: 5; margin: 0 1; }
    .spark-label { width: 6; height: 1; }
    .gpu-card { border: solid $primary; padding: 0 1; margin: 0 1; height: auto; }
    .sensor-row { height: 1; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cpu_history: deque[float] = deque(maxlen=_SPARKLINE_SAMPLES)

    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical(id="cpu-section"):
            yield Static("  CPU", classes="section")
            yield Sparkline([], id="cpu-spark", summary_function=max)
            yield ProgressBar(total=100, id="cpu-bar", gradient=_GRADIENT_WARN)

        with Vertical(id="per-core-section"):
            yield Static("  CORES", classes="section")
            yield Static("", id="cores")

        with Vertical(id="mem-section"):
            yield Static("  MEMORY", classes="section")
            with Horizontal(classes="bar-row"):
                yield Label("  RAM", classes="bar-label")
                yield ProgressBar(total=100, id="ram-bar", gradient=_GRADIENT_WARN)
            with Horizontal(classes="bar-row"):
                yield Label("  SWP", classes="bar-label")
                yield ProgressBar(total=100, id="swap-bar", gradient=_GRADIENT_WARN)

        yield Static("", id="gpu", classes="gpu-card")
        yield Static("", id="sensors", classes="section")
        yield Static("", id="power_supply", classes="section")

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._refresh)

    def _refresh(self) -> None:
        try:
            resp = nexus_get("telemetry")
            data = resp.json()
            self._update(data)
        except Exception as e:
            self.query_one("#cpu-spark", Static).update(f"Error: {e}")

    def _update(self, data: dict) -> None:
        self._update_cpu(data.get("cpu", {}))
        self._update_cores(data.get("cpu", {}))
        self._update_ram(data.get("ram", {}))
        self._update_swap(data.get("swap", {}))
        self._update_gpu(data.get("gpu", []))
        self._update_sensors(data.get("power_sensors", []))
        self._update_power_supply(data.get("power_supply", []))

    def _update_cpu(self, cpu: dict) -> None:
        overall = cpu.get("overall_usage_percent", 0)
        self._cpu_history.append(overall)
        self.query_one("#cpu-bar", ProgressBar).update(progress=overall)
        spark = self.query_one("#cpu-spark", Sparkline)
        spark.data = list(self._cpu_history)

    def _update_cores(self, cpu: dict) -> None:
        cores = cpu.get("per_core_percent", [])
        lines = []
        for i, pct in enumerate(cores):
            filled = int(pct / 100 * 20)
            empty = 20 - filled
            bar = "█" * filled + "░" * empty
            lines.append(f"  C{i:<2} {bar} {pct:.1f}%")
        self.query_one("#cores", Static).update("\n".join(lines) if lines else "  (no core data)")

    def _update_ram(self, ram: dict) -> None:
        used = ram.get("used_bytes", 0)
        total = ram.get("total_bytes", 0)
        pct = ram.get("usage_percent", 0)
        bar = self.query_one("#ram-bar", ProgressBar)
        bar.update(progress=pct)
        # Update label dynamically
        bar.parent.query_one(Label).update(
            f"  RAM {_fmt_bytes(used)}/{_fmt_bytes(total)}"
        )

    def _update_swap(self, swap: dict) -> None:
        used = swap.get("used_bytes", 0)
        total = swap.get("total_bytes", 0)
        pct = swap.get("usage_percent", 0)
        bar = self.query_one("#swap-bar", ProgressBar)
        bar.update(progress=pct)
        bar.parent.query_one(Label).update(
            f"  SWP {_fmt_bytes(used)}/{_fmt_bytes(total)}"
        )

    def _update_gpu(self, gpus: list) -> None:
        if not gpus:
            self.query_one("#gpu", Static).update("  GPU  (none)")
            return
        lines = []
        for g in gpus:
            vram_pct = 0
            if g.get("vram_total_bytes", 0) > 0:
                vram_pct = g["vram_used_bytes"] / g["vram_total_bytes"] * 100
            lines.append(f"  {g.get('vendor', '?')} {g.get('name', '?')}")
            lines.append(
                f"    Usage  {_bar_text(g.get('gpu_usage_percent', 0))}"
            )
            lines.append(
                f"    VRAM   {_bar_text(vram_pct)}  "
                f"{_fmt_bytes(g.get('vram_used_bytes', 0))} / "
                f"{_fmt_bytes(g.get('vram_total_bytes', 0))}"
            )
            lines.append(f"    Temp   {g.get('temperature_c', '?')}°C")
        self.query_one("#gpu", Static).update("\n".join(lines))

    def _update_sensors(self, sensors: list) -> None:
        if not sensors:
            self.query_one("#sensors", Static).update("  SENSORS (none)")
            return
        lines = ["  SENSORS"]
        for s in sensors:
            name = s.get("device", "?")
            v = s.get("voltage_v", "?")
            p = s.get("power_w", "?")
            lines.append(f"    {name:<12} {v}V  {p}W")
        self.query_one("#sensors", Static).update("\n".join(lines))

    def _update_power_supply(self, supplies: list) -> None:
        if not supplies:
            self.query_one("#power_supply", Static).update(
                "  POWER SUPPLY (none)"
            )
            return
        lines = ["  POWER SUPPLY"]
        for ps in supplies:
            name = ps.get("device", "?")
            status = ps.get("status", "?")
            cap = ps.get("capacity_percent", "?")
            energy = ps.get("energy_now_wh", "?")
            full = ps.get("energy_full_wh", "?")
            lines.append(
                f"    {name:<12} {status}  {cap}%  {energy}/{full} Wh"
            )
        self.query_one("#power_supply", Static).update("\n".join(lines))


def _bar_text(percent: float, width: int = 20) -> str:
    """Render a text progress bar for GPU sections."""
    filled = int(percent / 100 * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"{bar} {percent:.1f}%"


def main() -> None:
    """Launch the Nexus telemetry TUI."""
    NexusTui().run()


if __name__ == "__main__":
    main()

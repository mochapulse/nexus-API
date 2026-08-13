"""Textual TUI for Nexus API telemetry.

Renders a full-screen dashboard with CPU, RAM, swap, GPU, and power
sensor data from ``/api/v1/telemetry``.  Auto-refreshes every 2 seconds.

Usage::

    python -m api.cli nexus_tui
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static

from api.cli.http_client import nexus_get

_REFRESH_INTERVAL = 2


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


def _bar(percent: float, width: int = 20) -> str:
    """Render a text progress bar.

    Parameters
    ----------
    percent : float
        Value between 0 and 100.
    width : int
        Character width of the bar.

    Returns:
        A string like ``"████████░░░░░░░░░░░░ 43.9%"``.
    """
    filled = int(percent / 100 * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"{bar} {percent:.1f}%"


class NexusTui(App):
    """Full-screen Textual app for Nexus telemetry."""

    CSS = """
    Screen { background: $surface }
    .section { height: auto; margin: 0 1; padding: 0 1; }
    .cpu-bar { height: auto; }
    .gpu-card { height: auto; border: solid $primary; padding: 0 1; margin: 0 1; }
    .sensor-table { height: auto; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading...", id="cpu")
        yield Static("", id="ram")
        yield Static("", id="swap")
        yield Static("", id="gpu")
        yield Static("", id="sensors")
        yield Static("", id="power_supply")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._refresh)

    def _refresh(self) -> None:
        try:
            resp = nexus_get("telemetry")
            data = resp.json()
            self._update(data)
        except Exception as e:
            self.query_one("#cpu", Static).update(f"Error: {e}")

    def _update(self, data: dict) -> None:
        self._update_cpu(data.get("cpu", {}))
        self._update_ram(data.get("ram", {}))
        self._update_swap(data.get("swap", {}))
        self._update_gpu(data.get("gpu", []))
        self._update_sensors(data.get("power_sensors", []))
        self._update_power_supply(data.get("power_supply", []))

    def _update_cpu(self, cpu: dict) -> None:
        overall = cpu.get("overall_usage_percent", 0)
        cores = cpu.get("per_core_percent", [])
        lines = [f"  CPU  {_bar(overall)}"]
        for i, pct in enumerate(cores):
            lines.append(f"  C{i:<2} {_bar(pct)}")
        self.query_one("#cpu", Static).update("\n".join(lines))

    def _update_ram(self, ram: dict) -> None:
        used = ram.get("used_bytes", 0)
        total = ram.get("total_bytes", 0)
        pct = ram.get("usage_percent", 0)
        self.query_one("#ram", Static).update(
            f"  RAM  {_bar(pct)}  {_fmt_bytes(used)} / {_fmt_bytes(total)}"
        )

    def _update_swap(self, swap: dict) -> None:
        used = swap.get("used_bytes", 0)
        total = swap.get("total_bytes", 0)
        pct = swap.get("usage_percent", 0)
        self.query_one("#swap", Static).update(
            f"  SWP  {_bar(pct)}  {_fmt_bytes(used)} / {_fmt_bytes(total)}"
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
                f"    Usage  {_bar(g.get('gpu_usage_percent', 0))}"
            )
            lines.append(
                f"    VRAM   {_bar(vram_pct)}  "
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


def main() -> None:
    """Launch the Nexus telemetry TUI."""
    NexusTui().run()


if __name__ == "__main__":
    main()

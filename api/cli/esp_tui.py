"""Textual TUI for ESP32 device status.

Renders a full-screen dashboard with network, memory, device, and
firmware info from the ESP32 ``/api/status`` endpoint.  Uses native
Textual widgets: ProgressBar with gradient colors, Sparkline for
mini history charts, and PlotextPlot for detailed time-series.
Auto-refreshes every 2 seconds.

Usage::

    nexus-API telemetry esp
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
from textual_plotext import PlotextPlot

from api.cli.http_client import esp_get

_REFRESH_INTERVAL = 2
_SPARKLINE_SAMPLES = 30

_GRADIENT_HEALTH = Gradient.from_colors("#2ecc71", "#f1c40f", "#e74c3c")


def _fmt_bytes(n: int | float) -> str:
    """Format byte count to human-readable string.

    Parameters
    ----------
    n : int
        Number of bytes.

    Returns:
        Human-readable string (e.g. ``"4.2 MiB"``).
    """
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GiB"


def _fmt_rssi(rssi: int) -> str:
    """Format Wi-Fi RSSI with signal strength indicator.

    Parameters
    ----------
    rssi : int
        Signal strength in dBm.

    Returns:
        Formatted string (e.g. ``"-55 dBm ▂▃▅"``).
    """
    bars = "▁▂▃▄▅▆▇█"
    quality = min(max(0, rssi + 100), 100)
    idx = int(quality / 100 * (len(bars) - 1))
    return f"{rssi} dBm {bars[idx]}"


class EspTui(App):
    """Full-screen Textual app for ESP32 device status."""

    CSS = """
    Screen { background: $surface }
    .section { height: auto; margin: 0 1; padding: 0 1; }
    .bar-row { height: 1; }
    .bar-label { width: 8; }
    .sparkline-row { height: 5; margin: 0 1; }
    .device-card { border: solid $primary; padding: 0 1; margin: 0 1; height: auto; }
    .chart-plot { height: 10; margin: 0 1; border: solid $primary; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._heap_data: deque[float] = deque(maxlen=_SPARKLINE_SAMPLES)
        self._rssi_data: deque[float] = deque(maxlen=_SPARKLINE_SAMPLES)
        self._tasks_data: deque[float] = deque(maxlen=_SPARKLINE_SAMPLES)
        self._stack_data: deque[float] = deque(maxlen=_SPARKLINE_SAMPLES)

    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical(id="network-section"):
            yield Static("  NETWORK", classes="section")
            yield Static("", id="network")
            with Horizontal(classes="bar-row"):
                yield Label("  RSSI", classes="bar-label")
                yield Sparkline([], id="rssi-spark", summary_function=max)

        with Vertical(id="memory-section"):
            yield Static("  MEMORY", classes="section")
            yield Static("", id="memory")
            with Horizontal(classes="bar-row"):
                yield Label("  Heap", classes="bar-label")
                yield ProgressBar(total=100, id="heap-bar", gradient=_GRADIENT_HEALTH)

        yield Static("", id="device", classes="device-card")
        yield Static("", id="firmware", classes="section")

        with Vertical(id="charts-section"):
            yield Static("  CHARTS (last 30 samples)", classes="section")
            yield PlotextPlot(id="heap-chart", classes="chart-plot")
            yield PlotextPlot(id="rssi-chart", classes="chart-plot")

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self._refresh)

    def _refresh(self) -> None:
        try:
            resp = esp_get("api/status")
            data = resp.json()
            self._update(data)
        except Exception as e:
            self.query_one("#network", Static).update(f"Error: {e}")

    def _update(self, data: dict) -> None:
        self._update_network(data)
        self._update_memory(data)
        self._update_device(data)
        self._update_firmware(data)
        self._update_charts(data)

    def _update_network(self, data: dict) -> None:
        wifi = "Connected" if data.get("wifi") else "Disconnected"
        ip = data.get("ip", "?")
        mac = data.get("mac", "?")
        rssi = data.get("wifi_rssi", 0)
        self._rssi_data.append(rssi)
        self.query_one("#network", Static).update(
            f"    Wi-Fi   {wifi}\n"
            f"    IP      {ip}\n"
            f"    MAC     {mac}\n"
            f"    RSSI    {_fmt_rssi(rssi)}"
        )
        spark = self.query_one("#rssi-spark", Sparkline)
        spark.data = list(self._rssi_data)

    def _update_memory(self, data: dict) -> None:
        heap_free = data.get("heap_free", 0)
        heap_total = data.get("heap_total", 0)
        heap_min = data.get("heap_min_free", 0)
        stack = data.get("free_stack", 0)
        tasks = data.get("task_count", 0)
        self._heap_data.append(heap_free)
        self._tasks_data.append(tasks)
        self._stack_data.append(stack)
        if heap_total > 0:
            pct = heap_free / heap_total * 100
        else:
            pct = 0
        self.query_one("#memory", Static).update(
            f"    Heap    {_fmt_bytes(heap_free)} / {_fmt_bytes(heap_total)}\n"
            f"    Min     {_fmt_bytes(heap_min)}\n"
            f"    Stack   {_fmt_bytes(stack)}\n"
            f"    Tasks   {tasks}"
        )
        self.query_one("#heap-bar", ProgressBar).update(progress=pct)

    def _update_device(self, data: dict) -> None:
        model = data.get("chip_model", "?")
        cores = data.get("chip_cores", "?")
        rev = data.get("chip_revision", "?")
        freq = data.get("cpu_freq", 0)
        freq_mhz = freq / 1_000_000 if freq else 0
        flash = data.get("flash_size", 0)
        features = data.get("chip_features", [])
        self.query_one("#device", Static).update(
            f"  DEVICE\n"
            f"    Model   {model}\n"
            f"    Cores   {cores}\n"
            f"    Rev     {rev}\n"
            f"    Freq    {freq_mhz:.0f} MHz\n"
            f"    Flash   {_fmt_bytes(flash)}\n"
            f"    Features {', '.join(features)}"
        )

    def _update_firmware(self, data: dict) -> None:
        uptime = data.get("uptime", 0)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
        self.query_one("#firmware", Static).update(
            f"  FIRMWARE\n"
            f"    Name    {data.get('app_name', '?')}\n"
            f"    Version {data.get('app_version', '?')}\n"
            f"    Built   {data.get('app_date', '?')} "
            f"{data.get('app_time', '?')}\n"
            f"    Uptime  {uptime_str}"
        )

    def _update_charts(self, data: dict) -> None:
        self._plotext_line(
            "heap-chart", list(self._heap_data), "Heap Free (bytes)"
        )
        self._plotext_line(
            "rssi-chart", list(self._rssi_data), "Wi-Fi RSSI (dBm)"
        )

    def _plotext_line(self, widget_id: str, values: list[float], title: str) -> None:
        """Update a PlotextPlot widget with a line chart."""
        try:
            widget = self.query_one(f"#{widget_id}", PlotextPlot)
            plt = widget.plt
            plt.clear_figure()
            plt.title(title)
            plt.theme("pro")
            if len(values) > 1:
                plt.plot(values, label="value")
                lo = min(values) * 0.9 if min(values) > 0 else 0
                hi = max(values) * 1.1 if max(values) > 0 else 1
                plt.ylim(lo, hi)
            plt.no_x_axis()
            plt.no_y_axis()
            widget.refresh()
        except Exception:
            pass


def main() -> None:
    """Launch the ESP32 status TUI."""
    EspTui().run()


if __name__ == "__main__":
    main()

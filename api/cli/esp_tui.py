"""Textual TUI for ESP32 device status.

Renders a full-screen dashboard with network, memory, device, and
firmware info from ``/api/status``.  Includes ASCII time-series charts
rendered via :mod:`plotext` for heap, RSSI, task count, and free stack.
Auto-refreshes every 2 seconds.

Usage::

    python -m api.cli esp_tui
"""

from __future__ import annotations

from collections import deque

import plotext as plt
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static

from api.cli.http_client import esp_get

_REFRESH_INTERVAL = 2
_CHART_SAMPLES = 30
_CHART_WIDTH = 40


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


def _plotext_chart(
    data: list[float],
    title: str,
    width: int = _CHART_WIDTH,
) -> str:
    """Render an ASCII line chart via plotext.

    Parameters
    ----------
    data : list[float]
        Time-series values to plot.
    title : str
        Chart title.
    width : int
        Character width of the chart.

    Returns:
        Multi-line string containing the rendered chart.
    """
    plt.clear_figure()
    plt.plot_size(width, 8)
    plt.title(title)
    plt.theme("pro")
    if len(data) > 1:
        plt.plot(data, label="value")
        plt.ylim(min(data) * 0.9 if min(data) > 0 else 0, max(data) * 1.1)
    plt.no_x_axis()
    plt.no_y_axis()
    return plt.build()


class EspTui(App):
    """Full-screen Textual app for ESP32 device status."""

    CSS = """
    Screen { background: $surface }
    .section { height: auto; margin: 0 1; padding: 0 1; }
    .chart-box { height: auto; border: solid $primary; padding: 0 1; margin: 0 1; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._heap_data: deque[float] = deque(maxlen=_CHART_SAMPLES)
        self._rssi_data: deque[float] = deque(maxlen=_CHART_SAMPLES)
        self._tasks_data: deque[float] = deque(maxlen=_CHART_SAMPLES)
        self._stack_data: deque[float] = deque(maxlen=_CHART_SAMPLES)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading...", id="network")
        yield Static("", id="memory")
        yield Static("", id="device")
        yield Static("", id="firmware")
        yield Static("", id="charts")
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
            f"  NETWORK\n"
            f"    Wi-Fi   {wifi}\n"
            f"    IP      {ip}\n"
            f"    MAC     {mac}\n"
            f"    RSSI    {_fmt_rssi(rssi)}"
        )

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
            f"  MEMORY\n"
            f"    Heap    {_bar(pct)}  {_fmt_bytes(heap_free)} / "
            f"{_fmt_bytes(heap_total)}\n"
            f"    Min     {_fmt_bytes(heap_min)}\n"
            f"    Stack   {_fmt_bytes(stack)}\n"
            f"    Tasks   {tasks}"
        )

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
        heap_chart = _plotext_chart(
            list(self._heap_data), "Heap Free"
        )
        rssi_chart = _plotext_chart(
            list(self._rssi_data), "Wi-Fi RSSI"
        )
        tasks_chart = _plotext_chart(
            list(self._tasks_data), "Tasks"
        )
        stack_chart = _plotext_chart(
            list(self._stack_data), "Free Stack"
        )
        self.query_one("#charts", Static).update(
            f"  CHARTS (last {_CHART_SAMPLES} samples)\n"
            f"{heap_chart}\n{rssi_chart}\n{tasks_chart}\n{stack_chart}"
        )


def main() -> None:
    """Launch the ESP32 status TUI."""
    EspTui().run()


if __name__ == "__main__":
    main()

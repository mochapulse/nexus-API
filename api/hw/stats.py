"""Hardware statistics collection for Nexus API.

Gathers CPU, RAM, swap, GPU (NVIDIA/AMD), and power sensor metrics
from psutil, NVML, AMD SMI, and Linux sysfs interfaces.
"""

import asyncio
import glob
import os
import time
from pathlib import Path

import orjson
import psutil
import pynvml

try:
    import amdsmi
    amdsmi.amdsmi_init()
    amdsmi.amdsmi_shut_down()
    AMD_SMI_AVAILABLE = True
except Exception:
    AMD_SMI_AVAILABLE = False


def _read_hwmon_sensors() -> list[dict]:
    """Parse hardware sensor data from /sys/class/hwmon.

    Reads voltage, current, power, and temperature values exposed by the
    Linux kernel's hardware monitoring subsystem. Pure Python, no subprocess.

    Returns:
        List of sensor dictionaries, one per hwmon device with available data.
        Each dict contains a 'device' key and optional metrics like 'voltage_v',
        'current_a', 'power_w', 'temperature_c'.
    """
    sensors = []
    hwmon_devices = sorted(glob.glob("/sys/class/hwmon/hwmon*"))

    for hwmon_path in hwmon_devices:
        try:
            name_file = Path(hwmon_path) / "name"
            if not name_file.exists():
                continue
            device_name = name_file.read_text().strip()

            sensor_data = {"device": device_name}

            # Voltage sensors (in millivolts)
            voltage_files = sorted(glob.glob(os.path.join(hwmon_path, "in*_input")))
            if voltage_files:
                voltages = []
                for vf in voltage_files:
                    try:
                        raw = int(Path(vf).read_text().strip())
                        voltages.append(round(raw / 1000.0, 3))
                    except (ValueError, OSError):
                        continue
                if voltages:
                    sensor_data["voltage_v"] = voltages[0] if len(voltages) == 1 else voltages

            # Current sensors (in milliamps)
            current_files = sorted(glob.glob(os.path.join(hwmon_path, "curr*_input")))
            if current_files:
                currents = []
                for cf in current_files:
                    try:
                        raw = int(Path(cf).read_text().strip())
                        currents.append(round(raw / 1000.0, 3))
                    except (ValueError, OSError):
                        continue
                if currents:
                    sensor_data["current_a"] = currents[0] if len(currents) == 1 else currents

            # Power sensors (in microwatts)
            power_files = sorted(glob.glob(os.path.join(hwmon_path, "power*_input")))
            if power_files:
                powers = []
                for pf in power_files:
                    try:
                        raw = int(Path(pf).read_text().strip())
                        powers.append(round(raw / 1_000_000.0, 3))
                    except (ValueError, OSError):
                        continue
                if powers:
                    sensor_data["power_w"] = powers[0] if len(powers) == 1 else powers

            # Temperature sensors (in millidegrees Celsius)
            temp_files = sorted(glob.glob(os.path.join(hwmon_path, "temp*_input")))
            if temp_files:
                temps = []
                for tf in temp_files:
                    try:
                        raw = int(Path(tf).read_text().strip())
                        temps.append(round(raw / 1000.0, 1))
                    except (ValueError, OSError):
                        continue
                if temps:
                    sensor_data["temperature_c"] = temps[0] if len(temps) == 1 else temps

            if len(sensor_data) > 1:
                sensors.append(sensor_data)

        except OSError:
            continue

    return sensors


def _read_power_supply() -> list[dict]:
    """Parse power supply data from /sys/class/power_supply.

    Provides battery-specific metrics not always available via hwmon:
    voltage, power, energy, capacity, status, cycle count, etc.

    Returns:
        List of power supply dictionaries, one per battery with available data.
    """
    supplies = []
    ps_devices = sorted(glob.glob("/sys/class/power_supply/*"))

    for ps_path in ps_devices:
        try:
            type_file = Path(ps_path) / "type"
            if not type_file.exists():
                continue
            ps_type = type_file.read_text().strip()

            if ps_type != "Battery":
                continue

            name = Path(ps_path).name
            supply_data = {"device": name, "type": ps_type}

            fields = {
                "voltage_now": ("voltage_v", 1_000_000),
                "voltage_min_design": ("voltage_min_design_v", 1_000_000),
                "power_now": ("power_w", 1_000_000),
                "energy_now": ("energy_now_wh", 1_000_000),
                "energy_full": ("energy_full_wh", 1_000_000),
                "energy_full_design": ("energy_full_design_wh", 1_000_000),
                "capacity": ("capacity_percent", 1),
                "cycle_count": ("cycle_count", 1),
                "alarm": ("alarm_wh", 1_000_000),
            }

            for filename, (key, divisor) in fields.items():
                filepath = Path(ps_path) / filename
                if filepath.exists():
                    try:
                        raw = int(filepath.read_text().strip())
                        if divisor == 1:
                            supply_data[key] = raw
                        else:
                            supply_data[key] = round(raw / divisor, 3)
                    except (ValueError, OSError):
                        continue

            status_file = Path(ps_path) / "status"
            if status_file.exists():
                try:
                    supply_data["status"] = status_file.read_text().strip()
                except OSError:
                    pass

            for field in ["manufacturer", "model_name", "technology"]:
                filepath = Path(ps_path) / field
                if filepath.exists():
                    try:
                        value = filepath.read_text().strip()
                        if value:
                            supply_data[field] = value
                    except OSError:
                        continue

            if len(supply_data) > 2:
                supplies.append(supply_data)

        except OSError:
            continue

    return supplies


def _fetch_metrics_sync(pretty: bool = False) -> bytes:
    """Synchronous worker for fetching hardware metrics.

    Args:
        pretty: If True, returns indented JSON.

    Returns:
        JSON-encoded bytes of system metrics.
    """
    uptime_seconds = int(time.time() - psutil.boot_time())

    overall_cpu = psutil.cpu_percent(interval=None)
    per_core_cpu = psutil.cpu_percent(interval=None, percpu=True)

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    gpu_data = []
    gpu_index = 0

    # NVIDIA GPU metrics
    try:
        pynvml.nvmlInit()
        nv_device_count = pynvml.nvmlDeviceGetCount()

        for i in range(nv_device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

            gpu_data.append({
                "index": gpu_index,
                "vendor": "NVIDIA",
                "name": pynvml.nvmlDeviceGetName(handle),
                "gpu_usage_percent": util.gpu,
                "vram_used_bytes": mem_info.used,
                "vram_total_bytes": mem_info.total,
                "temperature_c": temp
            })
            gpu_index += 1
    except pynvml.NVMLError:
        pass
    finally:
        try:
            pynvml.nvmlShutdown()
        except pynvml.NVMLError:
            pass

    # AMD GPU metrics
    if AMD_SMI_AVAILABLE:
        try:
            amdsmi.amdsmi_init()
            devices = amdsmi.amdsmi_get_processor_handles()

            for handle in devices:
                try:
                    name = amdsmi.amdsmi_get_board_info(handle).get('product_name', 'AMD GPU')
                    util_data = amdsmi.amdsmi_get_processor_engine_utilization(handle)
                    gfx_util = util_data.get('gfx', 0) if util_data else 0
                    vram_info = amdsmi.amdsmi_get_vram_usage(handle)
                    temp = amdsmi.amdsmi_get_temp_metric(
                        handle,
                        amdsmi.AmdSmiTemperatureType.EDGE,
                        amdsmi.AmdSmiTemperatureMetric.CURRENT
                    )

                    gpu_data.append({
                        "index": gpu_index,
                        "vendor": "AMD",
                        "name": name,
                        "gpu_usage_percent": gfx_util,
                        "vram_used_bytes": vram_info.get('vram_used', 0),
                        "vram_total_bytes": vram_info.get('vram_total', 0),
                        "temperature_c": temp
                    })
                    gpu_index += 1
                except amdsmi.AmdSmiLibraryException:
                    continue
        except amdsmi.AmdSmiLibraryException:
            pass
        finally:
            try:
                amdsmi.amdsmi_shut_down()
            except amdsmi.AmdSmiLibraryException:
                pass

    power_sensors = _read_hwmon_sensors()
    power_supply = _read_power_supply()

    data = {
        "uptime_seconds": uptime_seconds,
        "cpu": {
            "overall_usage_percent": overall_cpu,
            "per_core_percent": per_core_cpu
        },
        "ram": {
            "total_bytes": mem.total,
            "used_bytes": mem.used,
            "free_bytes": mem.free,
            "usage_percent": mem.percent
        },
        "swap": {
            "total_bytes": swap.total,
            "used_bytes": swap.used,
            "usage_percent": swap.percent
        },
        "gpu": gpu_data,
        "power_sensors": power_sensors,
        "power_supply": power_supply
    }

    options = orjson.OPT_INDENT_2 if pretty else 0
    return orjson.dumps(data, option=options)


async def get_system_metrics(pretty: bool = False, return_bytes: bool = False) -> str | bytes:
    """Asynchronously retrieve system metrics.

    Offloads hardware C-driver calls to a worker thread to keep the
    main asyncio event loop responsive.

    Args:
        pretty: If True, returns formatted JSON (indented).
        return_bytes: If True, returns bytes directly without decoding.

    Returns:
        JSON string or bytes containing system metrics.
    """
    json_bytes = await asyncio.to_thread(_fetch_metrics_sync, pretty)

    if return_bytes:
        return json_bytes
    return json_bytes.decode('utf-8')

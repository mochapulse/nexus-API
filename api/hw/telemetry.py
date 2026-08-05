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


def _lspci_amd_names() -> dict[str, str]:
    """Parse lspci output to map PCI slot names to AMD GPU descriptions.

    Returns:
        Dict mapping PCI slot (e.g. '0000:01:00.0') to the GPU name string.
    """
    import subprocess

    names: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "AMD" not in line:
                continue
            # Line format: "01:00.0 VGA compatible controller: AMD ..."
            slot = line.split(":")[0].strip()
            # Extract name after the last bracketed info, e.g. "[Radeon RX 580 2048SP]"
            if "[" in line and "]" in line:
                bracket = line[line.rfind("[") + 1 : line.rfind("]")]
                names[slot] = bracket
            else:
                # Fallback: text after the colon-dash separator
                parts = line.split(": ", 1)
                if len(parts) == 2:
                    names[slot] = parts[1].strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return names


def _resolve_amd_slot(device_path: Path) -> str | None:
    """Resolve a sysfs device path to its PCI slot name.

    Reads the symlink target of /sys/class/drm/cardN/device to extract
    the PCI slot. Returns both the full slot (e.g. '0000:01:00.0') and
    the short form without domain ('01:00.0') for lspci matching.
    """
    try:
        resolved = device_path.resolve()
        slot = resolved.name
        if ":" in slot:
            # lspci uses short form (01:00.0), sysfs uses full (0000:01:00.0)
            short = slot.split(":", 1)[1] if slot.startswith("0000:") else slot
            return short
    except OSError:
        pass
    return None


def _read_amd_gpu_sysfs() -> list[dict]:
    """Read AMD GPU metrics from sysfs (amdgpu driver).

    Fallback when amdsmi is unavailable. Reads VRAM bytes, utilization,
    temperature, and GPU name directly from /sys/class/drm.

    Returns:
        List of GPU dictionaries matching the amdsmi output schema.
    """
    gpus = []
    drm_cards = sorted(glob.glob("/sys/class/drm/card[0-9]*"))
    lspci_names = _lspci_amd_names()

    for card_path in drm_cards:
        device_path = Path(card_path) / "device"
        if not device_path.exists():
            continue

        # Detect AMD GPU via vendor ID (0x1002 = AMD)
        vendor_file = device_path / "vendor"
        if not vendor_file.exists():
            continue
        try:
            vendor = vendor_file.read_text().strip()
        except OSError:
            continue
        if vendor != "0x1002":
            continue

        gpu: dict = {"vendor": "AMD", "index": len(gpus)}

        # GPU name: lspci first, then product_name, then card fallback
        slot = _resolve_amd_slot(device_path)
        if slot and slot in lspci_names:
            gpu["name"] = lspci_names[slot]
        else:
            name_file = device_path / "product_name"
            if name_file.exists():
                try:
                    gpu["name"] = name_file.read_text().strip() or "AMD GPU"
                except OSError:
                    gpu["name"] = "AMD GPU"
            else:
                card_name = Path(card_path).name
                gpu["name"] = f"AMD GPU ({card_name})"

        # VRAM total
        vram_total_file = device_path / "mem_info_vram_total"
        if vram_total_file.exists():
            try:
                gpu["vram_total_bytes"] = int(vram_total_file.read_text().strip())
            except (ValueError, OSError):
                gpu["vram_total_bytes"] = 0
        else:
            gpu["vram_total_bytes"] = 0

        # VRAM used
        vram_used_file = device_path / "mem_info_vram_used"
        if vram_used_file.exists():
            try:
                gpu["vram_used_bytes"] = int(vram_used_file.read_text().strip())
            except (ValueError, OSError):
                gpu["vram_used_bytes"] = 0
        else:
            gpu["vram_used_bytes"] = 0

        # GPU utilization
        busy_file = device_path / "gpu_busy_percent"
        if busy_file.exists():
            try:
                gpu["gpu_usage_percent"] = int(busy_file.read_text().strip())
            except (ValueError, OSError):
                gpu["gpu_usage_percent"] = 0
        else:
            gpu["gpu_usage_percent"] = 0

        # Temperature from hwmon
        gpu["temperature_c"] = 0
        hwmon_glob = sorted(glob.glob(os.path.join(str(device_path), "hwmon", "hwmon*", "temp1_input")))
        if hwmon_glob:
            try:
                raw = int(Path(hwmon_glob[0]).read_text().strip())
                gpu["temperature_c"] = round(raw / 1000.0, 1)
            except (ValueError, OSError):
                pass

        gpus.append(gpu)

    return gpus


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

    # AMD GPU metrics (amdsmi first, sysfs fallback)
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
    else:
        # sysfs fallback for AMD GPUs
        for gpu in _read_amd_gpu_sysfs():
            gpu["index"] = gpu_index
            gpu_data.append(gpu)
            gpu_index += 1

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

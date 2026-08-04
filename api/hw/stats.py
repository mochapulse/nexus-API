import asyncio
import time
import psutil
import orjson
import pynvml

try:
    import amdsmi
    amdsmi.amdsmi_init()
    amdsmi.amdsmi_shut_down()
    AMD_SMI_AVAILABLE = True
except Exception:
    AMD_SMI_AVAILABLE = False


def _fetch_metrics_sync(pretty: bool = False) -> bytes:
    """Internal synchronous worker for fetching hardware metrics."""
    uptime_seconds = int(time.time() - psutil.boot_time())

    # Non-blocking CPU measurement (compares against previous call timers)
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
        "gpu": gpu_data
    }

    options = orjson.OPT_INDENT_2 if pretty else 0
    return orjson.dumps(data, option=options)


async def get_system_metrics(pretty: bool = False, return_bytes: bool = False) -> str | bytes:
    """
    Asynchronously retrieves system metrics. Offloads hardware C-driver calls
    to a worker thread to keep the main asyncio event loop responsive.
    
    :param pretty: If True, returns formatted JSON (indented).
    :param return_bytes: If True, returns bytes directly without UTF-8 string decoding.
    """
    json_bytes = await asyncio.to_thread(_fetch_metrics_sync, pretty)
    
    if return_bytes:
        return json_bytes
    return json_bytes.decode('utf-8')
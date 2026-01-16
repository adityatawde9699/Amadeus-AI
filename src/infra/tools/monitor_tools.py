"""
System monitoring tools for Amadeus AI Assistant.

Includes CPU, memory, disk, battery, network, GPU, and process monitoring.
Migrated from system_monitor.py to Clean Architecture structure.
"""

import logging
from typing import Any

import psutil

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)


# =============================================================================
# CPU & MEMORY TOOLS
# =============================================================================

@tool(
    name="get_cpu_usage",
    description="Get current CPU usage percentage",
    category=ToolCategory.SYSTEM,
)
def get_cpu_usage() -> str:
    """Get CPU usage percentage."""
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        return f"CPU usage: {cpu:.1f}%"
    except Exception as e:
        logger.error(f"Error getting CPU usage: {e}")
        return "CPU information unavailable"


@tool(
    name="get_memory_usage",
    description="Get RAM usage statistics",
    category=ToolCategory.SYSTEM,
)
def get_memory_usage() -> str:
    """Get memory (RAM) usage."""
    try:
        mem = psutil.virtual_memory()
        used_gb = mem.used / (1024 ** 3)
        total_gb = mem.total / (1024 ** 3)
        return f"Memory: {used_gb:.1f} GB / {total_gb:.1f} GB ({mem.percent:.1f}% used)"
    except Exception as e:
        logger.error(f"Error getting memory usage: {e}")
        return "Memory information unavailable"


@tool(
    name="get_disk_usage",
    description="Get disk usage for a path",
    category=ToolCategory.SYSTEM,
    parameters={"path": {"type": "string", "description": "Disk path (default: C:/ or /)"}}
)
def get_disk_usage(path: str = "/") -> str:
    """Get disk usage statistics."""
    try:
        import platform
        if platform.system() == "Windows" and path == "/":
            path = "C:/"
        
        disk = psutil.disk_usage(path)
        used_gb = disk.used / (1024 ** 3)
        total_gb = disk.total / (1024 ** 3)
        free_gb = disk.free / (1024 ** 3)
        return f"Disk: {used_gb:.1f} GB / {total_gb:.1f} GB ({disk.percent:.1f}% used, {free_gb:.1f} GB free)"
    except Exception as e:
        logger.error(f"Error getting disk usage: {e}")
        return "Disk information unavailable"


# =============================================================================
# BATTERY & NETWORK TOOLS
# =============================================================================

@tool(
    name="get_battery_info",
    description="Get battery status and percentage",
    category=ToolCategory.SYSTEM,
)
def get_battery_info() -> str:
    """Get battery information."""
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return "No battery detected (desktop system)"
        
        status = "Charging" if battery.power_plugged else "Discharging"
        
        if battery.secsleft != psutil.POWER_TIME_UNLIMITED and battery.secsleft > 0:
            hours = battery.secsleft // 3600
            mins = (battery.secsleft % 3600) // 60
            time_left = f"{hours}h {mins}m remaining"
        else:
            time_left = ""
        
        result = f"Battery: {battery.percent}% - {status}"
        if time_left:
            result += f" ({time_left})"
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting battery info: {e}")
        return "Battery information unavailable"


@tool(
    name="get_network_info",
    description="Get network statistics (bytes sent/received)",
    category=ToolCategory.SYSTEM,
)
def get_network_info() -> str:
    """Get network usage statistics."""
    try:
        net = psutil.net_io_counters()
        sent_mb = net.bytes_sent / (1024 ** 2)
        recv_mb = net.bytes_recv / (1024 ** 2)
        return f"Network: Sent {sent_mb:.1f} MB, Received {recv_mb:.1f} MB"
    except Exception as e:
        logger.error(f"Error getting network info: {e}")
        return "Network information unavailable"


# =============================================================================
# UPTIME & PROCESS TOOLS
# =============================================================================

@tool(
    name="get_system_uptime",
    description="Get system uptime (how long system has been running)",
    category=ToolCategory.SYSTEM,
)
def get_system_uptime() -> str:
    """Get system uptime."""
    try:
        import time
        from datetime import datetime
        
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        mins = int((uptime_seconds % 3600) // 60)
        
        boot_datetime = datetime.fromtimestamp(boot_time)
        boot_str = boot_datetime.strftime("%Y-%m-%d %H:%M")
        
        if days > 0:
            uptime_str = f"{days}d {hours}h {mins}m"
        else:
            uptime_str = f"{hours}h {mins}m"
        
        return f"System uptime: {uptime_str} (since {boot_str})"
        
    except Exception as e:
        logger.error(f"Error getting uptime: {e}")
        return "Uptime information unavailable"


@tool(
    name="get_running_processes",
    description="List top processes by memory usage",
    category=ToolCategory.SYSTEM,
    parameters={"count": {"type": "integer", "description": "Number of processes to show"}}
)
def get_running_processes(count: int = 10) -> str:
    """Get top running processes by memory usage."""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
            try:
                info = proc.info
                processes.append({
                    'pid': info['pid'],
                    'name': info['name'],
                    'memory_percent': info['memory_percent'] or 0
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Sort by memory usage
        processes.sort(key=lambda x: x['memory_percent'], reverse=True)
        top_procs = processes[:count]
        
        result = f"Top {len(top_procs)} processes by memory:\n"
        for i, proc in enumerate(top_procs, 1):
            result += f"{i}. {proc['name']} (PID: {proc['pid']}, Mem: {proc['memory_percent']:.1f}%)\n"
        
        return result.strip()
        
    except Exception as e:
        logger.error(f"Error getting processes: {e}")
        return "Process information unavailable"


# =============================================================================
# GPU & TEMPERATURE TOOLS
# =============================================================================

@tool(
    name="get_gpu_stats",
    description="Get GPU statistics (usage, memory, temperature)",
    category=ToolCategory.SYSTEM,
)
def get_gpu_stats() -> str:
    """Get GPU statistics."""
    try:
        # Try NVIDIA GPU via GPUtil
        try:
            import GPUtil
            gpus = GPUtil.getGPUs()
            if gpus:
                result = "GPU Information:\n"
                for gpu in gpus:
                    result += f"  {gpu.name}: {gpu.load * 100:.1f}% load, "
                    result += f"{gpu.memoryUtil * 100:.1f}% memory, "
                    result += f"{gpu.temperature}°C\n"
                return result.strip()
        except ImportError:
            pass
        
        # Fallback message
        return "GPU monitoring requires GPUtil. Install with: pip install gputil"
        
    except Exception as e:
        logger.error(f"Error getting GPU stats: {e}")
        return "GPU information unavailable"


@tool(
    name="get_temperature_sensors",
    description="Get hardware temperature sensors (CPU/GPU)",
    category=ToolCategory.SYSTEM,
)
def get_temperature_sensors() -> str:
    """Get temperature sensor readings."""
    try:
        temps = psutil.sensors_temperatures()
        
        if not temps:
            return "No temperature sensors found (common on Windows)"
        
        result = "Temperature Sensors:\n"
        for chip, sensors in list(temps.items())[:3]:
            for sensor in sensors[:2]:
                current = sensor.current
                label = sensor.label or "Core"
                result += f"  {chip} {label}: {current}°C\n"
        
        return result.strip()
        
    except Exception as e:
        logger.error(f"Error getting temperatures: {e}")
        return "Temperature information unavailable"


# =============================================================================
# SYSTEM STATUS & ALERTS
# =============================================================================

@tool(
    name="system_status",
    description="General system summary (CPU + RAM + Disk + Battery). Trigger: 'system status', 'performance'",
    category=ToolCategory.SYSTEM,
)
def generate_system_summary() -> str:
    """Generate a comprehensive system status summary."""
    try:
        lines = ["System Status Report", "=" * 30]
        
        # CPU
        cpu = psutil.cpu_percent(interval=0.5)
        lines.append(f"CPU: {cpu:.1f}%")
        
        # Memory
        mem = psutil.virtual_memory()
        mem_used_gb = mem.used / (1024 ** 3)
        mem_total_gb = mem.total / (1024 ** 3)
        lines.append(f"Memory: {mem_used_gb:.1f}/{mem_total_gb:.1f} GB ({mem.percent:.1f}%)")
        
        # Disk
        import platform
        disk_path = "C:/" if platform.system() == "Windows" else "/"
        disk = psutil.disk_usage(disk_path)
        disk_used_gb = disk.used / (1024 ** 3)
        disk_total_gb = disk.total / (1024 ** 3)
        lines.append(f"Disk: {disk_used_gb:.1f}/{disk_total_gb:.1f} GB ({disk.percent:.1f}%)")
        
        # Battery
        battery = psutil.sensors_battery()
        if battery:
            status = "⚡" if battery.power_plugged else "🔋"
            lines.append(f"Battery: {battery.percent}% {status}")
        
        # Alerts
        alerts = []
        if cpu > 80:
            alerts.append("⚠️ High CPU usage")
        if mem.percent > 85:
            alerts.append("⚠️ High memory usage")
        if disk.percent > 90:
            alerts.append("⚠️ Low disk space")
        
        if alerts:
            lines.append("")
            lines.append("Alerts:")
            lines.extend(f"  {a}" for a in alerts)
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"Error generating system summary: {e}")
        return "Error generating system summary"


@tool(
    name="check_system_alerts",
    description="Check for performance alerts (CPU/RAM/disk warnings)",
    category=ToolCategory.SYSTEM,
)
def check_system_alerts() -> str:
    """Check for system alerts and warnings."""
    try:
        alerts = []
        
        # CPU check
        cpu = psutil.cpu_percent(interval=0.5)
        if cpu > 90:
            alerts.append(f"🔴 Critical: CPU usage at {cpu:.1f}%")
        elif cpu > 80:
            alerts.append(f"🟡 Warning: CPU usage at {cpu:.1f}%")
        
        # Memory check
        mem = psutil.virtual_memory()
        if mem.percent > 90:
            alerts.append(f"🔴 Critical: Memory usage at {mem.percent:.1f}%")
        elif mem.percent > 80:
            alerts.append(f"🟡 Warning: Memory usage at {mem.percent:.1f}%")
        
        # Disk check
        import platform
        disk_path = "C:/" if platform.system() == "Windows" else "/"
        disk = psutil.disk_usage(disk_path)
        if disk.percent > 95:
            alerts.append(f"🔴 Critical: Disk usage at {disk.percent:.1f}%")
        elif disk.percent > 85:
            alerts.append(f"🟡 Warning: Disk usage at {disk.percent:.1f}%")
        
        # Battery check
        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged and battery.percent < 15:
            alerts.append(f"🔴 Critical: Battery at {battery.percent}%")
        elif battery and not battery.power_plugged and battery.percent < 25:
            alerts.append(f"🟡 Warning: Battery at {battery.percent}%")
        
        if alerts:
            return f"System Alerts ({len(alerts)}):\n" + "\n".join(alerts)
        return "✅ No system alerts. All metrics normal."
        
    except Exception as e:
        logger.error(f"Error checking alerts: {e}")
        return "Error checking system alerts"


@tool(
    name="get_full_system_report",
    description="Comprehensive detailed system report (all metrics). Trigger: 'full system report'",
    category=ToolCategory.SYSTEM,
)
def get_full_system_report() -> str:
    """Generate a full detailed system report."""
    try:
        import platform
        from datetime import datetime
        
        lines = [
            "=" * 50,
            "FULL SYSTEM REPORT",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "=" * 50,
            "",
            "SYSTEM INFO",
            "-" * 30,
            f"OS: {platform.system()} {platform.release()}",
            f"Machine: {platform.machine()}",
            f"Processor: {platform.processor()[:50]}...",
            "",
            "PERFORMANCE",
            "-" * 30,
        ]
        
        # CPU
        cpu = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count()
        lines.append(f"CPU: {cpu:.1f}% ({cpu_count} cores)")
        
        # Memory
        mem = psutil.virtual_memory()
        lines.append(f"Memory: {mem.percent:.1f}% ({mem.used // (1024**3)}/{mem.total // (1024**3)} GB)")
        
        # Disk
        disk_path = "C:/" if platform.system() == "Windows" else "/"
        disk = psutil.disk_usage(disk_path)
        lines.append(f"Disk: {disk.percent:.1f}% ({disk.used // (1024**3)}/{disk.total // (1024**3)} GB)")
        
        # Network
        net = psutil.net_io_counters()
        lines.append(f"Network: ↑{net.bytes_sent // (1024**2)} MB ↓{net.bytes_recv // (1024**2)} MB")
        
        # Battery
        battery = psutil.sensors_battery()
        if battery:
            lines.append(f"Battery: {battery.percent}% ({'Charging' if battery.power_plugged else 'Discharging'})")
        
        lines.append("")
        lines.append("=" * 50)
        
        return "\n".join(lines)
        
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return "Error generating full report"


# =============================================================================
# TOOL COLLECTION
# =============================================================================

def get_monitor_tools() -> list[Tool]:
    """Get all monitor tools for manual registration."""
    tools = []
    for name, obj in globals().items():
        if hasattr(obj, "_tool_metadata"):
            tools.append(obj._tool_metadata)
    return tools

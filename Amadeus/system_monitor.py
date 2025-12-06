import psutil
import platform
import datetime
import time
import logging
from speech_utils import speak

# Configure logging
logger = logging.getLogger(__name__)

# Check if GPUtil is available more safely
def is_gputil_available():
    try:
        import GPUtil
        return True
    except ImportError:
        return False
    except Exception as e:
        logger.debug(f"Error checking GPUtil availability: {e}")
        return False

GPUTIL_AVAILABLE = is_gputil_available()

# Import config for thresholds
import config

# Default threshold values from config
DEFAULT_THRESHOLDS = config.get_system_thresholds()

def get_cpu_usage():
    """Get CPU usage percentage."""
    try:
        cpu_percent = psutil.cpu_percent(interval=config.SYSTEM_MONITOR_CPU_CHECK_INTERVAL)
        return cpu_percent
    except Exception as e:
        logger.error(f"Error getting CPU usage: {e}", exc_info=True)
        return None

def get_memory_usage():
    """Get memory (RAM) usage details."""
    try:
        memory = psutil.virtual_memory()
        # Convert to more readable format
        total_gb = memory.total / (1024 ** 3)
        used_gb = memory.used / (1024 ** 3)
        percent = memory.percent
        
        return {
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "percent": percent
        }
    except Exception as e:
        logger.error(f"Error getting memory usage: {e}", exc_info=True)
        return None

def get_disk_usage(path="/"):
    """Get disk usage details for the specified path."""
    try:
        disk = psutil.disk_usage(path)
        # Convert to more readable format
        total_gb = disk.total / (1024 ** 3)
        used_gb = disk.used / (1024 ** 3)
        free_gb = disk.free / (1024 ** 3)
        percent = disk.percent
        
        return {
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "free_gb": round(free_gb, 2),
            "percent": percent
        }
    except Exception as e:
        logger.error(f"Error getting disk usage: {e}", exc_info=True)
        return None

def get_system_uptime():
    """Get system uptime in a human-readable format."""
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        uptime_str = str(datetime.timedelta(seconds=int(uptime_seconds)))
        boot_time_str = datetime.datetime.fromtimestamp(boot_time).strftime("%Y-%m-%d %H:%M:%S")
        
        return {
            "uptime_seconds": uptime_seconds,
            "uptime_str": uptime_str,
            "boot_time": boot_time_str
        }
    except Exception as e:
        logger.error(f"Error getting system uptime: {e}", exc_info=True)
        return None

def get_running_processes(count=10):
    """Get a list of top running processes by memory usage."""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'memory_percent']):
            try:
                processes.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        # Sort by memory usage and get top processes
        top_processes = sorted(processes, key=lambda p: p['memory_percent'], reverse=True)[:count]
        
        return top_processes
    except Exception as e:
        logger.error(f"Error getting running processes: {e}", exc_info=True)
        return None

def get_network_info():
    """Get network interface usage statistics."""
    try:
        network_stats = psutil.net_io_counters()
        # Convert to MB
        bytes_sent_mb = network_stats.bytes_sent / (1024 ** 2)
        bytes_recv_mb = network_stats.bytes_recv / (1024 ** 2)
        
        return {
            "bytes_sent_mb": round(bytes_sent_mb, 2),
            "bytes_recv_mb": round(bytes_recv_mb, 2),
            "packets_sent": network_stats.packets_sent,
            "packets_recv": network_stats.packets_recv,
            "errin": network_stats.errin,
            "errout": network_stats.errout,
            "dropin": network_stats.dropin,
            "dropout": network_stats.dropout
        }
    except Exception as e:
        logger.error(f"Error getting network info: {e}", exc_info=True)
        return None

def get_battery_info():
    """Get battery information if available."""
    try:
        if not hasattr(psutil, "sensors_battery") or psutil.sensors_battery() is None:
            return "No battery detected"
            
        battery = psutil.sensors_battery()
        percent = battery.percent
        power_plugged = battery.power_plugged
        
        if power_plugged:
            status = "Charging" if percent < 100 else "Fully Charged"
        else:
            if percent <= 10:
                status = "Critical"
            elif percent <= 30:
                status = "Low"
            else:
                status = "Discharging"
                
        # Calculate remaining time if discharging
        if battery.secsleft != psutil.POWER_TIME_UNLIMITED and battery.secsleft != psutil.POWER_TIME_UNKNOWN:
            secsleft = battery.secsleft
            hours, remainder = divmod(secsleft, 3600)
            minutes, seconds = divmod(remainder, 60)
            time_left = f"{int(hours)}h {int(minutes)}m remaining"
        else:
            time_left = "Unknown time remaining"
            
        return {
            "percent": percent,
            "power_plugged": power_plugged,
            "status": status,
            "time_left": time_left if not power_plugged else "N/A"
        }
    except Exception as e:
        logger.error(f"Error getting battery info: {e}", exc_info=True)
        return "Error getting battery information"

# NEW FEATURE: GPU Stats (with improved error handling)
def get_gpu_stats():
    """Get GPU statistics if GPUtil is available."""
    if not GPUTIL_AVAILABLE:
        return "GPUtil module not available. Install with: pip install gputil setuptools"
    
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        
        if not gpus:
            return "No GPU detected"
            
        gpu_stats = []
        for i, gpu in enumerate(gpus):
            gpu_stats.append({
                "id": i,
                "name": gpu.name,
                "load": round(gpu.load * 100, 2),  # Convert to percentage
                "memory_total": round(gpu.memoryTotal / 1024, 2),  # Convert to GB
                "memory_used": round(gpu.memoryUsed / 1024, 2),  # Convert to GB
                "memory_percent": round((gpu.memoryUsed / gpu.memoryTotal) * 100, 2) if gpu.memoryTotal > 0 else 0,
                "temperature": gpu.temperature,
                "uuid": gpu.uuid
            })
            
        return gpu_stats
    except Exception as e:
        logger.error(f"Error getting GPU stats: {e}", exc_info=True)
        return f"Error getting GPU information: {e}"

# Alternative GPU info function using nvidia-smi for NVIDIA GPUs
def get_nvidia_gpu_stats():
    """Get NVIDIA GPU statistics using subprocess to call nvidia-smi."""
    try:
        import subprocess
        import re
        
        result = subprocess.run(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.total,memory.used,temperature.gpu', 
                               '--format=csv,noheader,nounits'], 
                              stdout=subprocess.PIPE, text=True)
        
        if result.returncode != 0:
            return "nvidia-smi command failed. No NVIDIA GPU detected or driver not installed."
            
        lines = result.stdout.strip().split('\n')
        gpu_stats = []
        
        for i, line in enumerate(lines):
            if not line.strip():
                continue
                
            parts = [part.strip() for part in line.split(',')]
            
            if len(parts) >= 5:
                name = parts[0]
                utilization = float(parts[1]) if parts[1].replace('.', '', 1).isdigit() else 0
                memory_total = float(parts[2]) if parts[2].replace('.', '', 1).isdigit() else 0
                memory_used = float(parts[3]) if parts[3].replace('.', '', 1).isdigit() else 0
                temperature = float(parts[4]) if parts[4].replace('.', '', 1).isdigit() else 0
                
                memory_percent = (memory_used / memory_total * 100) if memory_total > 0 else 0
                
                gpu_stats.append({
                    "id": i,
                    "name": name,
                    "load": utilization,
                    "memory_total": memory_total / 1024,  # Convert to GB
                    "memory_used": memory_used / 1024,  # Convert to GB
                    "memory_percent": round(memory_percent, 2),
                    "temperature": temperature,
                    "uuid": f"N/A-{i}"  # No UUID from nvidia-smi in this format
                })
                
        return gpu_stats if gpu_stats else "No GPU information found in nvidia-smi output."
    except FileNotFoundError:
        return "nvidia-smi command not found. NVIDIA driver may not be installed."
    except Exception as e:
        logger.error(f"Error getting NVIDIA GPU stats: {e}", exc_info=True)
        return f"Error getting NVIDIA GPU information: {e}"

# Function to get GPU stats from any available source
def get_any_gpu_stats():
    """Try to get GPU stats from any available source."""
    # First try GPUtil
    if GPUTIL_AVAILABLE:
        result = get_gpu_stats()
        if isinstance(result, list):
            return result
    
    # Then try nvidia-smi
    try:
        result = get_nvidia_gpu_stats()
        if isinstance(result, list):
            return result
    except:
        pass
        
    # If we get here, no GPU info is available
    return "No GPU information available. Install GPUtil or NVIDIA drivers."

# NEW FEATURE: Temperature Sensors
def get_temperature_sensors():
    """Get temperature sensor data if available."""
    try:
        if not hasattr(psutil, "sensors_temperatures"):
            return "Temperature sensors not supported on this platform"
        
        temps_func = getattr(psutil, "sensors_temperatures", None)
        if temps_func is None:
            return "Temperature sensors not supported on this platform"
        temps = temps_func()
        
        if not temps:
            return "No temperature sensors detected"
            
        # Format the temperatures in a more readable format
        formatted_temps = {}
        for chip, sensors in temps.items():
            formatted_temps[chip] = []
            for sensor in sensors:
                formatted_temps[chip].append({
                    "label": sensor.label,
                    "current": sensor.current,
                    "high": sensor.high if hasattr(sensor, "high") else None,
                    "critical": sensor.critical if hasattr(sensor, "critical") else None
                })
                
        return formatted_temps
    except Exception as e:
        logger.error(f"Error getting temperature data: {e}", exc_info=True)
        return f"Error getting temperature information: {e}"

# NEW FEATURE: System Alerts
def check_system_alerts(thresholds=DEFAULT_THRESHOLDS, speak_alerts=True):
    """Check if any system metrics exceed defined thresholds and trigger alerts."""
    alerts = []
    
    # Check CPU usage
    cpu = get_cpu_usage()
    if cpu is not None and cpu > thresholds.get("cpu", DEFAULT_THRESHOLDS["cpu"]):
        alert_msg = f"Warning: CPU usage is high at {cpu}%"
        alerts.append({"type": "CPU", "message": alert_msg, "value": cpu, "threshold": thresholds.get("cpu")})
    
    # Check memory usage
    memory = get_memory_usage()
    if memory is not None and memory["percent"] > thresholds.get("memory", DEFAULT_THRESHOLDS["memory"]):
        alert_msg = f"Warning: Memory usage is high at {memory['percent']}%"
        alerts.append({"type": "Memory", "message": alert_msg, "value": memory["percent"], "threshold": thresholds.get("memory")})
    
    # Check disk usage
    disk = get_disk_usage()
    if disk is not None and disk["percent"] > thresholds.get("disk", DEFAULT_THRESHOLDS["disk"]):
        alert_msg = f"Warning: Disk usage is high at {disk['percent']}%"
        alerts.append({"type": "Disk", "message": alert_msg, "value": disk["percent"], "threshold": thresholds.get("disk")})
    
    # Check temperature if supported
    temps = get_temperature_sensors()
    if isinstance(temps, dict):
        max_temp = 0
        max_temp_label = ""
        
        for chip, sensors in temps.items():
            for sensor in sensors:
                if sensor["current"] > max_temp:
                    max_temp = sensor["current"]
                    max_temp_label = f"{chip} - {sensor['label']}"
                    
        if max_temp > thresholds.get("temperature", DEFAULT_THRESHOLDS["temperature"]):
            alert_msg = f"Warning: High temperature detected: {max_temp_label} at {max_temp}°C"
            alerts.append({"type": "Temperature", "message": alert_msg, "value": max_temp, "threshold": thresholds.get("temperature")})
    
    # GPU alerts
    gpu_stats = get_any_gpu_stats()
    if isinstance(gpu_stats, list):
        for gpu in gpu_stats:
            if gpu["temperature"] > thresholds.get("temperature", DEFAULT_THRESHOLDS["temperature"]):
                alert_msg = f"Warning: GPU temperature is high: {gpu['name']} at {gpu['temperature']}°C"
                alerts.append({"type": "GPU Temperature", "message": alert_msg, "value": gpu["temperature"], "threshold": thresholds.get("temperature")})
            
            if gpu["load"] > thresholds.get("gpu_load", DEFAULT_THRESHOLDS["cpu"]):  # Use CPU threshold for GPU load
                alert_msg = f"Warning: GPU load is high: {gpu['name']} at {gpu['load']}%"
                alerts.append({"type": "GPU Load", "message": alert_msg, "value": gpu["load"], "threshold": thresholds.get("gpu_load")})
                
            if gpu["memory_percent"] > thresholds.get("memory", DEFAULT_THRESHOLDS["memory"]):
                alert_msg = f"Warning: GPU memory usage is high: {gpu['name']} at {gpu['memory_percent']}%"
                alerts.append({"type": "GPU Memory", "message": alert_msg, "value": gpu["memory_percent"], "threshold": thresholds.get("memory")})
    
    # Speak alerts if enabled and alerts exist
    if speak_alerts and alerts and 'speak' in globals():
        alert_messages = [alert["message"] for alert in alerts]
        speak(". ".join(alert_messages))
    
    return alerts

def get_full_system_report():
    """Generate a comprehensive system report."""
    try:
        # System information
        system_info = {
            "system": platform.system(),
            "node": platform.node(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor()
        }
        
        # Get all other metrics
        cpu = get_cpu_usage()
        memory = get_memory_usage()
        disk = get_disk_usage()
        uptime = get_system_uptime()
        network = get_network_info()
        battery = get_battery_info()
        
        # Get new metrics
        gpu = get_any_gpu_stats()
        temperature = get_temperature_sensors()
        alerts = check_system_alerts(speak_alerts=False)
        
        # Assemble report
        report = {
            "system_info": system_info,
            "cpu_usage": cpu,
            "memory_usage": memory,
            "disk_usage": disk,
            "uptime": uptime,
            "network": network,
            "battery": battery,
            "gpu": gpu,
            "temperature": temperature,
            "alerts": alerts
        }
        
        return report
    except Exception as e:
        logger.error(f"Error generating system report: {e}", exc_info=True)
        return None

def generate_system_summary():
    """Generate a user-friendly summary of system status for voice reporting."""
    try:
        cpu = get_cpu_usage()
        memory = get_memory_usage()
        disk = get_disk_usage()
        battery = get_battery_info() if not isinstance(get_battery_info(), str) else None
        
        summary = f"System Status Summary: CPU usage is at {cpu}%. "
        if memory is not None:
            summary += f"Memory usage is at {memory['percent']}%, with {memory['used_gb']} GB used out of {memory['total_gb']} GB. "
        else:
            summary += "Memory usage information is unavailable. "
        if disk is not None:
            summary += f"Disk space is {disk['percent']}% full, with {disk['free_gb']} GB free out of {disk['total_gb']} GB. "
        else:
            summary += "Disk usage information is unavailable. "
        
        if battery and not isinstance(battery, str):
            summary += f"Battery is at {battery['percent']}% and is {battery['status']}. "
            if battery['status'] == "Discharging" and battery['time_left'] != "N/A":
                summary += f"{battery['time_left']}. "
        
        # Add GPU information if available
        gpu_stats = get_any_gpu_stats()
        if isinstance(gpu_stats, list) and gpu_stats:
            for i, gpu in enumerate(gpu_stats):
                summary += f"GPU {i+1} ({gpu['name']}) is at {gpu['load']}% load with {gpu['memory_percent']}% memory usage. "
                summary += f"GPU temperature is {gpu['temperature']}°C. "
        
        # Check for any alerts
        alerts = check_system_alerts(speak_alerts=False)
        if alerts:
            summary += "System alerts detected: "
            for alert in alerts:
                summary += f"{alert['message']}. "
                
        return summary
    except Exception as e:
        logger.error(f"Error generating system summary: {e}", exc_info=True)
        return "Sorry, I couldn't generate a complete system summary at this time."

def print_system_info():
    """Print detailed system information to console."""
    try:
        cpu = get_cpu_usage()
        memory = get_memory_usage()
        disk = get_disk_usage()
        uptime = get_system_uptime()
        
        print("\n===== SYSTEM INFORMATION =====")
        print(f"CPU Usage: {cpu}%")
        if memory is not None:
            print(f"Memory: {memory['used_gb']} GB / {memory['total_gb']} GB ({memory['percent']}%)")
        else:
            print("Memory usage information is unavailable.")
        if disk is not None:
            print(f"Disk: {disk['used_gb']} GB / {disk['total_gb']} GB ({disk['percent']}%)")
            print(f"Free Disk Space: {disk['free_gb']} GB")
        else:
            print("Disk usage information is unavailable.")
        if uptime is not None:
            print(f"System Uptime: {uptime['uptime_str']}")
            print(f"System Boot Time: {uptime['boot_time']}")
        else:
            print("System uptime information is unavailable.")
        
        # Add GPU information if available
        gpu_stats = get_any_gpu_stats()
        if isinstance(gpu_stats, list) and gpu_stats:
            print("\n===== GPU INFORMATION =====")
            for i, gpu in enumerate(gpu_stats):
                print(f"GPU {i+1}: {gpu['name']}")
                print(f"  Load: {gpu['load']}%")
                print(f"  Memory: {gpu['memory_used']} GB / {gpu['memory_total']} GB ({gpu['memory_percent']}%)")
                print(f"  Temperature: {gpu['temperature']}°C")
        
        # Add temperature information if available
        temps = get_temperature_sensors()
        if isinstance(temps, dict) and temps:
            print("\n===== TEMPERATURE SENSORS =====")
            for chip, sensors in temps.items():
                print(f"{chip}:")
                for sensor in sensors:
                    print(f"  {sensor['label']}: {sensor['current']}°C")
                    if sensor['high']:
                        print(f"  High Threshold: {sensor['high']}°C")
                    if sensor['critical']:
                        print(f"  Critical Threshold: {sensor['critical']}°C")
        
        # Check for any system alerts
        alerts = check_system_alerts(speak_alerts=False)
        if alerts:
            print("\n===== SYSTEM ALERTS =====")
            for alert in alerts:
                print(f"[{alert['type']}] {alert['message']}")
        
        print("==============================\n")
        
        return True
    except Exception as e:
        logger.error(f"Error printing system information: {e}", exc_info=True)
        return False

# Example function to monitor system continuously
def monitor_system(interval=60, thresholds=DEFAULT_THRESHOLDS, speak_alerts=True):
    """
    Continuously monitor system and alert when thresholds are exceeded.
    
    Args:
        interval (int): Check interval in seconds
        thresholds (dict): Dictionary of threshold values
        speak_alerts (bool): Whether to speak alerts using text-to-speech
    """
    logger.info(f"Starting system monitoring (interval: {interval}s)")
    logger.info(f"Alert thresholds: CPU: {thresholds.get('cpu')}%, Memory: {thresholds.get('memory')}%, Disk: {thresholds.get('disk')}%, Temperature: {thresholds.get('temperature')}°C")
    
    try:
        while True:
            alerts = check_system_alerts(thresholds, speak_alerts)
            
            if alerts:
                logger.warning(f"System alerts detected: {len(alerts)}")
                for alert in alerts:
                    logger.warning(f"[{alert['type']}] {alert['message']}")
            
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("System monitoring stopped by user")
        
# If run directly, print system information
if __name__ == "__main__":
    print_system_info()
    
    # Uncomment to start continuous monitoring
    # monitor_system(interval=30)
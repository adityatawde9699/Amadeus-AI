"""
Health and system status API routes.
"""

import psutil

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.config import get_settings
from src.core.domain.models import SystemStatus


router = APIRouter()
settings = get_settings()


class HealthResponse(BaseModel):
    """Detailed health check response."""
    status: str
    service: str
    version: str
    environment: str
    database: str
    voice_enabled: bool


class SystemStatusResponse(BaseModel):
    """System status response."""
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    battery_percent: float | None
    is_charging: bool
    uptime_seconds: float
    is_healthy: bool
    alerts: list[str]


@router.get("/health/detailed", response_model=HealthResponse, tags=["Health"])
async def detailed_health():
    """
    Detailed health check with component status.
    """
    return HealthResponse(
        status="healthy",
        service=settings.ASSISTANT_NAME,
        version=settings.ASSISTANT_VERSION,
        environment=settings.ENV,
        database="connected" if settings.DATABASE_URL else "not configured",
        voice_enabled=settings.VOICE_ENABLED,
    )


@router.get("/system/status", response_model=SystemStatusResponse, tags=["System"])
async def get_system_status():
    """
    Get current system status including CPU, memory, disk, and battery.
    """
    # CPU usage
    cpu_usage = psutil.cpu_percent(interval=0.1)
    
    # Memory usage
    memory = psutil.virtual_memory()
    memory_usage = memory.percent
    
    # Disk usage
    disk = psutil.disk_usage("/")
    disk_usage = disk.percent
    
    # Battery (may not exist on desktop)
    battery = psutil.sensors_battery()
    battery_percent = battery.percent if battery else None
    is_charging = battery.power_plugged if battery else False
    
    # Uptime
    boot_time = psutil.boot_time()
    import time
    uptime_seconds = time.time() - boot_time
    
    # Check for alerts
    alerts = []
    thresholds = settings.get_system_thresholds()
    
    if cpu_usage >= thresholds["cpu"]["critical"]:
        alerts.append(f"CRITICAL: CPU usage at {cpu_usage:.1f}%")
    elif cpu_usage >= thresholds["cpu"]["warning"]:
        alerts.append(f"WARNING: CPU usage at {cpu_usage:.1f}%")
    
    if memory_usage >= thresholds["memory"]["critical"]:
        alerts.append(f"CRITICAL: Memory usage at {memory_usage:.1f}%")
    elif memory_usage >= thresholds["memory"]["warning"]:
        alerts.append(f"WARNING: Memory usage at {memory_usage:.1f}%")
    
    if disk_usage >= thresholds["disk"]["critical"]:
        alerts.append(f"CRITICAL: Disk usage at {disk_usage:.1f}%")
    elif disk_usage >= thresholds["disk"]["warning"]:
        alerts.append(f"WARNING: Disk usage at {disk_usage:.1f}%")
    
    if battery_percent is not None:
        if battery_percent <= thresholds["battery"]["critical"] and not is_charging:
            alerts.append(f"CRITICAL: Battery at {battery_percent:.1f}%")
        elif battery_percent <= thresholds["battery"]["low"] and not is_charging:
            alerts.append(f"WARNING: Battery at {battery_percent:.1f}%")
    
    is_healthy = len([a for a in alerts if "CRITICAL" in a]) == 0
    
    return SystemStatusResponse(
        cpu_usage=cpu_usage,
        memory_usage=memory_usage,
        disk_usage=disk_usage,
        battery_percent=battery_percent,
        is_charging=is_charging,
        uptime_seconds=uptime_seconds,
        is_healthy=is_healthy,
        alerts=alerts,
    )

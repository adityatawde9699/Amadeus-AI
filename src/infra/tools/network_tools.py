"""
Network diagnostic tools for Amadeus AI.
"""

import logging
import platform
import socket
import subprocess
from typing import Any

from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)

@tool(
    name="get_network_info",
    description=(
        "Returns basic network information like local IP address, hostname, and connectivity status. "
        "Trigger: 'network info', 'what is my ip', 'check internet connection', 'show hostname'"
    ),
    category=ToolCategory.SYSTEM,
)
def get_network_info(**kwargs: Any) -> str:
    """Get network info."""
    hostname = socket.gethostname()
    try:
        # Get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "Unknown"

    status = "Online" if local_ip != "Unknown" else "Offline"

    return (
        f"Network Status: {status}\n"
        f"Hostname: {hostname}\n"
        f"Local IP: {local_ip}"
    )

@tool(
    name="ping_host",
    description=(
        "Pings a remote host to check latency and connectivity. "
        "Trigger: 'ping google.com', 'test connection to server', 'check latency'"
    ),
    category=ToolCategory.SYSTEM,
    parameters={
        "host": {
            "type": "string",
            "description": "The hostname or IP address to ping.",
        },
        "count": {
            "type": "integer",
            "description": "Number of packets to send (default: 4).",
            "default": 4
        }
    },
)
def ping_host(host: str, count: int = 4, **kwargs: Any) -> str:
    """Ping a host."""
    param = "-n" if platform.system() == "Windows" else "-c"
    command = ["ping", param, str(count), host]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            return f"Ping successful for {host}:\n{result.stdout.strip()}"
        return f"Ping failed for {host}:\n{result.stderr.strip() or result.stdout.strip()}"
    except Exception as e:
        return f"Error pinging {host}: {e}"

def get_network_tools() -> list[Tool]:
    """Get all network tools."""
    return [
        get_network_info._tool_metadata,  # type: ignore[attr-defined]
        ping_host._tool_metadata,  # type: ignore[attr-defined]
    ]

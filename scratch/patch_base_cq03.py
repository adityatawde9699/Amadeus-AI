"""Insert CQ-03 sentinel check before retry loop in base.py."""
from pathlib import Path

FILE = Path(r"src\infra\tools\base.py")
content = FILE.read_text(encoding="utf-8")

# Look for the retry loop marker with \r\n or \n
RETRY_MARKER_WIN = "        for attempt in range(self.max_retries + 1):\r\n"
RETRY_MARKER_LF = "        for attempt in range(self.max_retries + 1):\n"

SENTINEL = (
    "        # CQ-03: Surface validation errors immediately, before any retry attempt.\r\n"
    "        _probe = self._validate_args(tool, args)\r\n"
    "        if \"_validation_error\" in _probe:\r\n"
    "            return ToolExecutionResult(\r\n"
    "                tool_name=tool.name,\r\n"
    "                success=False,\r\n"
    "                error_message=_probe[\"_validation_error\"],\r\n"
    "                execution_time_ms=0.0,\r\n"
    "            )\r\n"
    "\r\n"
)

if RETRY_MARKER_WIN in content:
    content = content.replace(RETRY_MARKER_WIN, SENTINEL + RETRY_MARKER_WIN, 1)
    FILE.write_text(content, encoding="utf-8")
    print("Sentinel inserted (CRLF)")
elif RETRY_MARKER_LF in content:
    sentinel_lf = SENTINEL.replace("\r\n", "\n")
    content = content.replace(RETRY_MARKER_LF, sentinel_lf + RETRY_MARKER_LF, 1)
    FILE.write_text(content, encoding="utf-8")
    print("Sentinel inserted (LF)")
else:
    print("ERROR: retry loop marker not found")

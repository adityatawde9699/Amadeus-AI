"""Patch base.py: CQ-03 (validate_args error), CQ-04 (bounded deque), CQ-05 (get_running_loop)."""
from pathlib import Path

FILE = Path(r"src\infra\tools\base.py")
content = FILE.read_text(encoding="utf-8")

# CQ-04 + CQ-05: add 'from collections import deque' import
content = content.replace(
    "import asyncio\r\nimport inspect\r\nimport logging\r\nfrom collections.abc import Callable",
    "import asyncio\r\nimport inspect\r\nimport logging\r\nfrom collections import deque\r\nfrom collections.abc import Callable",
    1,
)

# CQ-04: bounded deque for execution_history
content = content.replace(
    "        self.execution_history: list[dict] = []",
    "        # CQ-04: Bounded deque prevents unbounded memory growth in long-running daemons.\r\n        self.execution_history: deque[dict] = deque(maxlen=500)",
    1,
)

# CQ-05: get_running_loop
content = content.replace(
    "                    loop = asyncio.get_event_loop()\r\n                    result = await loop.run_in_executor(",
    "                    # CQ-05: get_running_loop() is correct in Python 3.10+\r\n                    loop = asyncio.get_running_loop()\r\n                    result = await loop.run_in_executor(",
    1,
)

# CQ-03: _validate_args raises error on missing required param
OLD_VALIDATE = '''    def _validate_args(self, tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
        """Validate and clean arguments for a tool."""
        sig = inspect.signature(tool.function)
        valid_params = set(sig.parameters.keys())

        # Filter to only valid parameters
        cleaned = {k: v for k, v in args.items() if k in valid_params}

        # Check for required parameters
        for name, param in sig.parameters.items():
            if (
                param.default == inspect.Parameter.empty
                and name not in cleaned
                and name not in ("self", "cls")
            ):
                logger.warning("Missing required parameter '%s' for %s", name, tool.name)

        return cleaned'''

NEW_VALIDATE = '''    def _validate_args(self, tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
        """Validate and clean arguments for a tool.

        CQ-03: Embeds a '_validation_error' key when required parameters are
        missing. execute() checks for this sentinel and returns a
        ToolExecutionResult(success=False) so the caller sees a clear error
        instead of a cryptic TypeError from inside the tool function.
        """
        sig = inspect.signature(tool.function)
        valid_params = set(sig.parameters.keys())

        # Filter to only valid parameters
        cleaned = {k: v for k, v in args.items() if k in valid_params}

        # Check for required parameters
        missing = []
        for name, param in sig.parameters.items():
            if (
                param.default == inspect.Parameter.empty
                and name not in cleaned
                and name not in ("self", "cls")
            ):
                missing.append(name)

        if missing:
            logger.warning(
                "Missing required parameter(s) for %s: %s", tool.name, ", ".join(missing)
            )
            cleaned["_validation_error"] = "Missing required parameter(s): {}".format(
                ", ".join(missing)
            )

        return cleaned'''

# Normalise line endings before matching (file uses \r\n)
OLD_VALIDATE_WIN = OLD_VALIDATE.replace("\n", "\r\n")
NEW_VALIDATE_WIN = NEW_VALIDATE.replace("\n", "\r\n")

if OLD_VALIDATE_WIN in content:
    content = content.replace(OLD_VALIDATE_WIN, NEW_VALIDATE_WIN, 1)
    print("_validate_args patched (CRLF match)")
elif OLD_VALIDATE in content:
    content = content.replace(OLD_VALIDATE, NEW_VALIDATE, 1)
    print("_validate_args patched (LF match)")
else:
    print("WARNING: _validate_args target not found - skipping CQ-03")

# Also patch execute() to catch the sentinel BEFORE the retry loop
# Insert after the HITL gate block, before 'for attempt in range'
SENTINEL_CHECK = (
    "\r\n        # CQ-03: Surface validation errors immediately without retrying.\r\n"
    "        validated_args_probe = self._validate_args(tool, args)\r\n"
    "        if \"_validation_error\" in validated_args_probe:\r\n"
    "            return ToolExecutionResult(\r\n"
    "                tool_name=tool.name,\r\n"
    "                success=False,\r\n"
    "                error_message=validated_args_probe[\"_validation_error\"],\r\n"
    "                execution_time_ms=0.0,\r\n"
    "            )\r\n"
    "\r\n"
)

RETRY_MARKER = "        for attempt in range(self.max_retries + 1):\r\n"
if SENTINEL_CHECK not in content and RETRY_MARKER in content:
    content = content.replace(RETRY_MARKER, SENTINEL_CHECK + RETRY_MARKER, 1)
    print("Sentinel check inserted before retry loop")
else:
    print("Sentinel check already present or retry marker not found - skipping")

FILE.write_text(content, encoding="utf-8")
print("Done. base.py patched.")

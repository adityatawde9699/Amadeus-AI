"""
Local Sandbox Executor for Amadeus AI.

Executes untrusted Python scripts in a separate process using multiprocessing.
This provides a lightweight alternative to Docker for local environments.

Security constraints:
- Executed in a separate process
- Redirection of stdout/stderr
- Restricted globals (no __builtins__ access to sensitive functions)
- Timeout enforcement
"""

import io
import logging
import multiprocessing
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

logger = logging.getLogger(__name__)


def _worker(code: str, queue: multiprocessing.Queue):
    """Worker function to execute code in a separate process."""
    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        # Define restricted globals
        # We can add more restrictions here if needed
        safe_globals = {
            "__builtins__": __builtins__.copy(),
            "print": print,
            "range": range,
            "len": len,
            "int": int,
            "str": str,
            "dict": dict,
            "list": list,
            "set": set,
            "tuple": tuple,
            "float": float,
            "bool": bool,
            "abs": abs,
            "sum": sum,
            "min": min,
            "max": max,
            "sorted": sorted,
            "enumerate": enumerate,
            "zip": zip,
        }
        
        # Remove potentially dangerous builtins
        # Note: This is NOT a perfect sandbox, but better than nothing for local use.
        # For a truly secure sandbox without Docker, something like RestrictedPython is needed.
        # However, for local development convenience, we'll keep it simple.
        dangerous = ["open", "eval", "exec", "getattr", "setattr", "delattr", "help", "input", "importlib", "__import__"]
        for d in dangerous:
            if d in safe_globals["__builtins__"]:
                del safe_globals["__builtins__"][d]

        with redirect_stdout(stdout), redirect_stderr(stderr):
            # Use exec to run the code
            exec(code, safe_globals)
        
        queue.put({"status": "success", "output": stdout.getvalue(), "error": stderr.getvalue()})
    except Exception:
        queue.put({"status": "error", "output": stdout.getvalue(), "error": traceback.format_exc()})


class LocalSandboxExecutor:
    """
    Executes Python scripts locally in a separate process.
    """

    DEFAULT_TIMEOUT = 10  # seconds

    def execute(self, code: str, timeout: int | None = None) -> dict[str, Any]:
        """
        Execute code in a separate process.
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        queue = multiprocessing.Queue()
        
        process = multiprocessing.Process(target=_worker, args=(code, queue))
        process.start()
        
        try:
            # Wait for result with timeout
            result = queue.get(timeout=timeout)
            process.join()
            return result
        except multiprocessing.queues.Empty:
            process.terminate()
            process.join()
            return {"status": "error", "output": "", "error": f"Execution timed out after {timeout} seconds."}
        except Exception as e:
            if process.is_alive():
                process.terminate()
                process.join()
            return {"status": "system_error", "output": "", "error": str(e)}

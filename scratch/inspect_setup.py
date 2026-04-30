"""Fix _setup() indentation using line-range rewrite instead of string matching."""
from pathlib import Path

FILE = Path("src/infra/memory_service.py")
raw = FILE.read_bytes()
lines = raw.decode("utf-8").split("\r\n")

# Find the line numbers of the broken block
start_line = None
end_line = None
for i, line in enumerate(lines):
    if "async with _get_qdrant_lock():" in line:
        start_line = i
    if start_line and "self._enabled = False" in line and i > start_line + 5:
        end_line = i
        break

if start_line is None or end_line is None:
    print(f"ERROR: could not locate block. start={start_line}, end={end_line}")
    exit(1)

print(f"Block found: lines {start_line+1}–{end_line+1}")

# Print the current block to inspect
for i in range(start_line, end_line + 2):
    print(f"{i+1:4d}: {lines[i]!r}")

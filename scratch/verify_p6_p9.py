"""Final verification for phases 6-9 fixes."""
from pathlib import Path

def read(p):
    return Path(p).read_text(encoding="utf-8", errors="replace")

checks = []

svc = read("src/app/services/amadeus_service.py")
checks.append(("P8 error_prose wrap", "error_prose" in svc))

tg = read("src/infra/messaging/telegram_adapter.py")
checks.append(("Chaos-03 QueueFullError in telegram", "QueueFullError" in tg))

srv = read("src/api/server.py")
checks.append(("P6-T5 _rate_limit_storage Redis probe", "_rate_limit_storage" in srv))
checks.append(("DR-03 scheduler shutdown wait=True", "shutdown(wait=True)" in srv))
checks.append(("Chaos-04 migration failure banner", "DATABASE MIGRATION FAILED" in srv))

cfg = read("src/core/config.py")
checks.append(("DR-05 UnicodeDecodeError in IPC loader", "UnicodeDecodeError" in cfg))

mem = read("src/infra/memory_service.py")
checks.append(("Chaos-01 memory error metric", "amadeus_memory_errors_total" in mem))
checks.append(("P6-T7 content-based dedup key", 'raw_key = f"{session_id}:{role}:{text}"' in mem))

metrics = read("src/infra/metrics.py")
checks.append(("Chaos-01 counter defined in metrics.py", "amadeus_memory_errors_total" in metrics))

all_passed = True
for name, result in checks:
    status = "PASS" if result else "FAIL"
    if not result:
        all_passed = False
    print(f"  [{status}] {name}")

print()
print("All phase 6-9 checks PASSED." if all_passed else "Some checks FAILED.")
import sys; sys.exit(0 if all_passed else 1)

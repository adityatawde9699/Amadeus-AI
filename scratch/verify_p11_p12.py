"""Syntax check + verification for all phase 11-12 changes."""
import ast
from pathlib import Path

files_to_check = [
    "src/infra/memory_service.py",
    "src/infra/metrics.py",
    "src/infra/tools/base.py",
    "src/infra/messaging/protocols.py",
    "src/api/routes/readiness.py",
    "src/api/server.py",
    "tests/unit/test_security_hardening.py",
    "tests/unit/test_agent_reliability.py",
]

print("=== Syntax Check ===")
all_ok = True
for f in files_to_check:
    try:
        content = Path(f).read_text(encoding="utf-8")
        ast.parse(content)
        print(f"  [PASS] {f}")
    except SyntaxError as e:
        print(f"  [FAIL] {f}: {e}")
        all_ok = False
    except FileNotFoundError:
        print(f"  [MISS] {f}: not found")
        all_ok = False

print()
print("=== Phase 11 Test Files ===")
sec_tests = Path("tests/unit/test_security_hardening.py").read_text(encoding="utf-8")
rel_tests = Path("tests/unit/test_agent_reliability.py").read_text(encoding="utf-8")

checks = [
    ("test_security_hardening.py exists", True),
    ("SEC-01 prompt injection test", "test_injected_action_tokens_are_blocked" in sec_tests),
    ("SEC-02 WhatsApp HMAC test", "test_invalid_signature_returns_403" in sec_tests),
    ("SEC-03 Telegram auth test", "test_unauthorized_chat_id_is_rejected" in sec_tests),
    ("CQ-01/02 path traversal test", "test_copy_file_blocked_outside_allowed_dirs" in sec_tests),
    ("CQ-03 missing param test", "test_missing_required_param_returns_failure" in sec_tests),
    ("P6-T7 memory dedup test", "test_same_content_produces_same_uuid" in sec_tests),
    ("AG-01 cycle detection test", "test_exact_cycle_detected_within_max_iterations" in rel_tests),
    ("AG-02 SYNTHESIZE failure test", "test_all_error_observations_yield_success_false" in rel_tests),
    ("DR-01 task tracking test", "test_task_stored_after_start" in rel_tests),
    ("DR-02 orchestrator shutdown test", "test_shutdown_cancels_worker_task" in rel_tests),
    ("DR-03 wait=True test", "test_scheduler_uses_wait_true" in rel_tests),
    ("HITL deny-by-default test", "test_destructive_tool_denied_without_callback" in rel_tests),
]

print()
print("=== Phase 12 Architecture Upgrades ===")
protocols = Path("src/infra/messaging/protocols.py").read_text(encoding="utf-8")
readiness_route = Path("src/api/routes/readiness.py").read_text(encoding="utf-8")
metrics = Path("src/infra/metrics.py").read_text(encoding="utf-8")
server = Path("src/api/server.py").read_text(encoding="utf-8")
memory = Path("src/infra/memory_service.py").read_text(encoding="utf-8")

checks += [
    ("IMessagingAdapter Protocol defined", "class IMessagingAdapter(Protocol)" in protocols),
    ("InboundMessage dataclass", "class InboundMessage" in protocols),
    ("/health/live endpoint", "async def liveness" in readiness_route),
    ("/health/ready endpoint", "async def readiness" in readiness_route),
    ("readiness router registered in server.py", "readiness.router" in server),
    ("amadeus_tool_duration_seconds Histogram", "amadeus_tool_duration_seconds" in metrics),
    ("amadeus_tool_executions_total Counter", "amadeus_tool_executions_total" in metrics),
    ("ARCH-04 Qdrant init lock", "_get_qdrant_lock" in memory),
    ("ARCH-04 async with lock in _setup", "async with _get_qdrant_lock()" in memory),
]

for name, result in checks:
    status = "PASS" if result else "FAIL"
    if not result:
        all_ok = False
    print(f"  [{status}] {name}")

print()
print("All checks PASSED." if all_ok else "Some checks FAILED.")
import sys; sys.exit(0 if all_ok else 1)

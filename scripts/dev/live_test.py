"""
Live test of the whole assistant against the real local model.

Runs in an isolated environment (throwaway SQLite database and workspace, no
Redis, no cloud keys, local-only) and never touches your data. Four parts:

  A  every registered tool, executed with safe arguments
  B  routing for every tool (decision + rule-based arguments; nothing executed)
  C  every expert, through the real agent graph and model
  D  requests that need more than one expert (orchestration on)

Safety: tools that would open windows (open_program, launch_app, open_website)
are routed but not executed; the kill tools only target a dummy process this
script starts; confirmations are auto-approved for the safe targets used here.

    uv run python scripts/dev/live_test.py [--parts A,B,C,D] [--model PATH] [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DUMMY = "amdvictim"  # process name the kill tools are pointed at
SKIP = {
    "open_program": "would launch a GUI app",
    "launch_app": "would launch a GUI app",
    "open_website": "would open the browser",
}

ROUTE_Q = {
    "open_program": "open the gedit editor",
    "terminate_program": "close the gedit editor",
    "scan_system_applications": "rescan which applications are installed",
    "launch_app": "launch the app gimp",
    "terminate_process": "end the process named gimp",
    "list_open_apps": "which applications are open at the moment",
    "take_screenshot": "grab a screenshot",
    "calculate": "what is 96 divided by 8",
    "convert_temperature": "convert 25 celsius to fahrenheit",
    "convert_length": "convert 3 km to miles",
    "convert_currency": "convert 20 euros to dollars",
    "get_datetime_info": "what's the date today",
    "tell_joke": "tell me a funny joke",
    "execute_python_script": "run python code that prints the first five squares",
    "terminal_cmd": "run the command uname -a",
    "search_codebase": "search the codebase for the retry decorator",
    "search_workspace": "search my workspace documents for the deployment notes",
    "manage_plugins": "list the installed plugins",
    "fs_list_directory": "list what's inside the reports folder",
    "fs_read_file": "read the file notes.txt",
    "fs_search_files": "search my files for the word budget",
    "fs_write_file": "write the text hello into greeting.txt",
    "search_file": "find the file holiday_photo.png",
    "create_folder": "create a folder called invoices",
    "copy_file": "copy notes.txt to backup.txt",
    "move_file": "move draft.txt to the archive folder",
    "delete_file": "delete the file scratch.tmp",
    "get_crypto_price": "what's the price of ethereum",
    "get_stock_price": "what's the MSFT stock price",
    "get_cpu_usage": "how busy is the cpu",
    "get_memory_usage": "how much ram is in use",
    "get_disk_usage": "how much disk space is left",
    "get_battery_info": "what's the battery level",
    "get_gpu_stats": "show gpu usage",
    "get_network_info": "show my network information",
    "get_running_processes": "list the top running processes",
    "get_system_uptime": "what's the system uptime",
    "get_temperature_sensors": "show the temperature sensors",
    "get_full_system_report": "give me a full system report",
    "system_status": "what's the system status",
    "check_system_alerts": "are there any system alerts",
    "ping_host": "ping 9.9.9.9",
    "get_news": "show me the latest business headlines",
    "get_weather": "what's the weather in Jaipur",
    "store_core_memory": "remember that my desk is on the second floor",
    "forget_core_memory": "forget that I like tea",
    "create_goal": "create a goal to read twelve books this year",
    "list_active_goals": "list my active goals",
    "decompose_goal": "break goal 1 into steps",
    "execute_goal": "execute goal 1",
    "update_goal": "mark goal 1 as completed",
    "schedule_future_task": "in 15 minutes check the server logs",
    "add_task": "add a task to pay the electricity bill",
    "list_tasks": "show me my tasks",
    "complete_task": "mark task 1 as done",
    "get_task_summary": "give me a summary of my tasks",
    "add_reminder": "remind me to drink water in 20 minutes",
    "list_reminders": "show my reminders",
    "create_note": "take a note: the wifi code is 7788",
    "list_notes": "show all my notes",
    "get_note": "show note 1",
    "set_timer": "set a timer for 3 minutes",
    "start_pomodoro": "start a pomodoro",
    "stop_pomodoro": "stop the pomodoro",
    "pomodoro_status": "what's the pomodoro status",
    "web_search": "search the web for the best trekking shoes",
    "wikipedia_search": "who was Isaac Newton",
    "open_website": "open the website github.com",
    "fetch_webpage_content": "summarise https://example.com",
}
# Twin tools that do the same job: either one is a correct route.
EQUIVALENT = [{"open_program", "launch_app"}, {"terminate_program", "terminate_process"}]
CHAT_Q = [
    "hi",
    "hello there, how are you today",
    "thanks, that helped",
    "what do you think about jazz",
]

EXPERT_Q: dict[str, tuple[str, set[str] | None]] = {
    "os_expert": ("list the apps that are currently open", {"list_open_apps"}),
    "monitor_expert": ("how much disk space is free", {"get_disk_usage", "system_status"}),
    "filesystem_expert": (
        "list the files in the current workspace directory",
        {"fs_list_directory"},
    ),
    "developer_expert": (
        "search the codebase for IntentRouter",
        {"search_codebase", "search_workspace"},
    ),
    "task_expert": ("add a task to buy milk", {"add_task"}),
    "memory_expert": (
        "create a goal titled Learn Spanish, described as practise every day",
        {"create_goal"},
    ),
    "finance_expert": ("what's the price of bitcoin", {"get_crypto_price"}),
    "news_expert": ("show me technology headlines", {"get_news"}),
    "research_expert": ("what's the weather in Pune", {"get_weather"}),
    "math_expert": ("convert 5 miles to km", {"convert_length", "calculate"}),
    "email_expert": ("check my inbox for unread email", None),
    "generalist": ("tell me a joke", {"tell_joke"}),
}
MULTI_Q = [
    ("what's the cpu usage and also what's the weather in Delhi", {"get_cpu_usage", "get_weather"}),
    ("what is 12 times 12 and also what is the bitcoin price", {"calculate", "get_crypto_price"}),
    ("add a task to call mom and then tell me the time", {"add_task", "get_datetime_info"}),
    (
        "check memory usage, then take a note saying memory was checked",
        {"get_memory_usage", "create_note"},
    ),
]
# Tools that depend on earlier ones (run last, in this order).
ORDER_LAST = [
    "move_file",
    "complete_task",
    "get_note",
    "decompose_goal",
    "execute_goal",
    "update_goal",
    "forget_core_memory",
    "pomodoro_status",
    "stop_pomodoro",
]


def short(value: object, n: int = 110) -> str:
    return " ".join(str(value).split())[:n]


def say(*parts: object) -> None:
    print(*parts, flush=True)


def tool_args(ws: Path) -> dict[str, dict]:
    return {
        "scan_system_applications": {},
        "terminate_program": {"process_name": DUMMY},
        "terminate_process": {"process_name": DUMMY},
        "list_open_apps": {},
        "take_screenshot": {},
        "calculate": {"expression": "17 * 23"},
        "convert_currency": {"amount": 10, "from_currency": "USD", "to_currency": "INR"},
        "convert_length": {"value": 5, "from_unit": "km", "to_unit": "mi"},
        "convert_temperature": {"value": 100, "from_unit": "F", "to_unit": "C"},
        "get_datetime_info": {"query": "time"},
        "get_greeting": {},
        "tell_joke": {},
        "execute_python_script": {"code": "print(2 + 2)"},
        "manage_plugins": {"action": "list"},
        "search_codebase": {"query": "IntentRouter"},
        "search_workspace": {"query": "routing"},
        "terminal_cmd": {"command": "echo amadeus-live-test"},
        "copy_file": {
            "source_path": str(ws / "notes.txt"),
            "destination_path": str(ws / "copy.txt"),
        },
        "create_folder": {"folder_name": "live_test_folder"},
        "delete_file": {"file_path": str(ws / "old.log")},
        "fs_list_directory": {"path": "."},
        "fs_read_file": {"path": "notes.txt"},
        "fs_search_files": {"query": "notes"},
        "fs_write_file": {"path": "out.txt", "content": "written by the live test"},
        "move_file": {
            "source_path": str(ws / "copy.txt"),
            "destination_path": str(ws / "moved.txt"),
        },
        "search_file": {"file_name": "notes.txt"},
        "get_crypto_price": {"coin": "bitcoin"},
        "get_stock_price": {"symbol": "AAPL"},
        "check_system_alerts": {},
        "get_battery_info": {},
        "get_cpu_usage": {},
        "get_disk_usage": {},
        "get_full_system_report": {},
        "get_gpu_stats": {},
        "get_memory_usage": {},
        "get_network_info": {},
        "get_running_processes": {"count": 3},
        "get_system_uptime": {},
        "get_temperature_sensors": {},
        "ping_host": {"host": "1.1.1.1", "count": 1},
        "system_status": {},
        "get_news": {"category": "technology", "country": "in", "count": 2},
        "get_weather": {"location": "Mumbai"},
        "create_goal": {"title": "Live test goal", "description": "Tell the current time once."},
        "list_active_goals": {},
        "decompose_goal": {"goal_id": 1},
        "execute_goal": {"goal_id": 1},
        "update_goal": {"goal_id": 1, "status": "completed"},
        "store_core_memory": {"fact": "live test fact: colour teal"},
        "forget_core_memory": {"fact": "live test fact: colour teal"},
        "schedule_future_task": {"minutes": 1440, "prompt": "live test", "session_id": "live"},
        "add_task": {"task_content": "live test task"},
        "list_tasks": {},
        "complete_task": {"identifier": "1"},
        "get_task_summary": {},
        "add_reminder": {"title": "live test reminder", "time": "in 30 minutes"},
        "list_reminders": {},
        "create_note": {"title": "live", "content": "live test note"},
        "list_notes": {},
        "get_note": {"identifier": "1"},
        "set_timer": {"duration_seconds": 1},
        "start_pomodoro": {"task": "live test", "duration": 1},
        "pomodoro_status": {},
        "stop_pomodoro": {},
        "fetch_webpage_content": {"url": "https://example.com"},
        "web_search": {"query": "python asyncio tutorial"},
        "wikipedia_search": {"query": "Ada Lovelace"},
    }


async def run(parts: set[str], report: dict) -> None:
    from src.app.services.slot_extractor import extract_slots
    from src.container import get_amadeus_service
    from src.core.config import get_settings
    from src.core.domain.context import RequestContext
    from src.core.domain.models import PermissionProfile
    from src.infra.persistence.database import init_db
    from src.infra.tools.confirmation import ConfirmationCallback

    await init_db()
    svc = get_amadeus_service()
    await svc.initialize()
    reg, router = svc.tool_registry, svc._intent_router
    approvals: list[str] = []

    class AutoApprove(ConfirmationCallback):
        async def request_approval(self, tool_name, args, request_id, preview=""):
            approvals.append(tool_name)
            return True

    svc.tool_executor.confirmation_callback = AutoApprove()

    def ctx(session: str = "live") -> RequestContext:
        return RequestContext(
            request_id="live",
            session_id=session,
            user_id="live",
            permissions=PermissionProfile.SYSTEM_FULL,
        )

    ws = get_settings().AGENT_WORKSPACE
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "a.md").write_text("# doc\nrouting notes\n")
    (ws / "notes.txt").write_text("budget notes for the live test\n")
    (ws / "old.log").write_text("old\n")
    # Dummy process for the kill tools: a private copy of bash blocked on a FIFO.
    victim, fifo = ws.parent / DUMMY, ws.parent / f"{DUMMY}.fifo"
    shutil.copy("/bin/bash", victim)
    victim.chmod(0o755)
    if not fifo.exists():
        os.mkfifo(fifo)

    def spawn() -> subprocess.Popen:
        proc = subprocess.Popen([str(victim), "-c", f"read x < {fifo}"])
        time.sleep(0.4)
        if proc.poll() is not None:
            raise RuntimeError("dummy process did not stay alive")
        return proc

    def category(tool) -> str:
        return str(getattr(tool.category, "value", tool.category))

    tools = sorted(reg.list_all(), key=lambda t: (category(t), t.name))
    say(f"service ready: {len(tools)} tools, router ready={router.is_ready}, workspace={ws}")

    if "A" in parts:
        say("\n=== A. every tool, executed with safe arguments ===")
        args = tool_args(ws)
        ordered = [t for t in tools if t.name not in ORDER_LAST]
        ordered += [reg.get(n) for n in ORDER_LAST if reg.get(n)]
        for tool in ordered:
            row = {"tool": tool.name, "category": category(tool)}
            if tool.name in SKIP:
                row.update(status="skipped", detail=SKIP[tool.name])
            elif tool.name not in args:
                row.update(status="skipped", detail="no safe test arguments defined")
            else:
                proc = spawn() if tool.name.startswith("terminate_") else None
                start = time.perf_counter()
                try:
                    res = await asyncio.wait_for(
                        svc._tool_dispatcher.dispatch(tool.name, dict(args[tool.name]), ctx()), 150
                    )
                    row.update(
                        status="ok" if res.success else "failed", detail=short(res.output, 150)
                    )
                except Exception as exc:
                    row.update(status="exception", detail=f"{type(exc).__name__}: {short(exc)}")
                row["seconds"] = round(time.perf_counter() - start, 2)
                if proc is not None:
                    await asyncio.sleep(0.5)
                    if proc.poll() is None:
                        proc.kill()
                        row["status"], row["detail"] = (
                            "DID NOT KILL",
                            row["detail"] + " | dummy still alive",
                        )
                    else:
                        row["detail"] += " | dummy process was killed"
            report["tools"].append(row)
            say(
                f"{row['status']:10s} {row.get('seconds', '-'):>6}s {tool.name:26s} {row['detail'][:118]}"
            )
        say("auto-approved confirmations for:", sorted(set(approvals)))

    if "B" in parts:
        say("\n=== B. routing for every tool (nothing executed) ===")
        for tool in tools:
            query = ROUTE_Q.get(tool.name)
            if not query:
                continue
            d = router.route(query)
            slots = extract_slots(d.target, query, reg) if d.kind == "tool" and d.target else None
            owner = router.expert_for(category(tool))
            same = d.target == tool.name or any(
                {d.target, tool.name} <= pair for pair in EQUIVALENT
            )
            if d.kind == "tool" and same:
                verdict = "direct, no LLM" if slots is not None else "right tool, args need LLM"
            elif d.kind == "tool":
                expert = router.expert_for(d.category)
                if slots is not None:
                    verdict = f"WRONG TOOL {d.target}"
                else:
                    verdict = (
                        "right expert"
                        if expert == owner and owner
                        else f"WRONG -> {d.target}/{expert}"
                    )
            elif d.kind == "expert":
                verdict = "right expert" if d.target == owner else f"WRONG EXPERT {d.target}"
            else:
                verdict = f"WRONG: treated as {d.kind}"
            report["routing"].append(
                {
                    "tool": tool.name,
                    "query": query,
                    "kind": d.kind,
                    "target": d.target,
                    "args": slots,
                    "verdict": verdict,
                }
            )
            say(
                f"{verdict[:30]:30s} {tool.name:26s} {query!r}"
                + (f" {json.dumps(slots)}" if slots else "")
            )
        for query in CHAT_Q:
            d = router.route(query)
            verdict = "chat" if d.kind == "conversational" else f"WRONG: {d.kind}:{d.target}"
            report["routing"].append(
                {
                    "tool": "(chat)",
                    "query": query,
                    "kind": d.kind,
                    "target": d.target,
                    "args": None,
                    "verdict": verdict,
                }
            )
            say(f"{verdict[:30]:30s} {'(chat)':26s} {query!r}")

    async def run_graph(task: str, **kwargs):
        start = time.perf_counter()
        try:
            res = await asyncio.wait_for(
                svc.graph.ainvoke(task=task, context=ctx(f"live-{time.monotonic_ns()}"), **kwargs),
                240,
            )
            return res, time.perf_counter() - start, None
        except Exception as exc:
            return None, time.perf_counter() - start, f"{type(exc).__name__}: {short(exc)}"

    if "C" in parts:
        say("\n=== C. each expert, through the real agent and model ===")
        for expert, (task, expected) in EXPERT_Q.items():
            res, dt, err = await run_graph(
                task, routing_intent="expert", routing_target=expert, allow_orchestration=False
            )
            used = list(res.tools_used) if res else []
            if err:
                verdict = "exception"
            elif expected is None:
                verdict = "answered" if res.success else "failed"
            elif res.success and set(used) & expected:
                verdict = "ok"
            else:
                verdict = "wrong/no tool" if res.success else "failed"
            answer = short(err or res.final_answer or res.error, 140)
            report["experts"].append(
                {
                    "expert": expert,
                    "task": task,
                    "verdict": verdict,
                    "tools": used,
                    "seconds": round(dt, 1),
                    "answer": answer,
                }
            )
            say(f"{verdict:14s} {dt:6.1f}s {expert:18s} tools={used} | {answer[:105]}")

    if "D" in parts:
        say("\n=== D. requests that need more than one expert ===")
        for task, expected in MULTI_Q:
            d = router.route(task)
            res, dt, err = await run_graph(
                task,
                routing_intent=d.kind if d.kind == "expert" else "conversational",
                routing_target=d.target or "",
                allow_orchestration=True,
            )
            used = list(res.tools_used) if res else []
            got = set(used) & expected
            verdict = (
                "exception"
                if err
                else ("ok" if got == expected else ("partial" if got else "missed"))
            )
            answer = short(err or res.final_answer or res.error, 170)
            report["multi"].append(
                {
                    "task": task,
                    "route": f"{d.kind}:{d.target}",
                    "verdict": verdict,
                    "tools": used,
                    "seconds": round(dt, 1),
                    "answer": answer,
                }
            )
            say(
                f"{verdict:9s} {dt:6.1f}s route={d.kind}:{d.target} tools={used}\n          {task!r} -> {answer}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Live test of tools, routing and experts.")
    parser.add_argument("--parts", default="A,B,C,D")
    parser.add_argument(
        "--model", type=Path, default=ROOT / "Model" / "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    from evals.agent_eval import _isolate_env

    _isolate_env()  # throwaway SQLite + data dir, no Redis, no cloud keys, local-only
    os.environ.update(
        SLM_MODEL_PATH=str(args.model),
        SKIP_CONFIG_VALIDATION="true",
        ENV="development",
        TOOL_RESPONSE_MODE="direct",
    )
    logging.basicConfig(level=logging.ERROR)
    report: dict[str, list] = {"tools": [], "routing": [], "experts": [], "multi": []}
    try:
        asyncio.run(run(set(args.parts.upper().split(",")), report))
    finally:
        subprocess.run(["pkill", "-x", DUMMY], check=False)  # -x: exact name, never this script
        if args.json:
            args.json.write_text(json.dumps(report, indent=1))
        say("DONE")
        os._exit(0)  # background threads (model, schedulers) would keep the process alive


if __name__ == "__main__":
    main()

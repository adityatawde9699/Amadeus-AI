# Tool Registry

Amadeus ships with **60+ tools** across seven categories. New tools can be added in `src/infra/tools/` following the `@tool` decorator pattern — see [[Development-Guide#adding-a-tool]].

---

## Information Tools

| Tool | Trigger Examples | Key Args |
|---|---|---|
| `get_weather` | "weather in Mumbai", "will it rain?" | `location` |
| `get_news` | "tech news today", "latest headlines" | `category`, `country`, `count` |
| `get_datetime_info` | "what time is it", "what day is today" | `query` |
| `wikipedia_search` | "who is Alan Turing", "explain quantum computing" | `query`, `sentences` |
| `web_search` | "search for Python tutorials", "look up X" | `query`, `depth` |
| `fetch_webpage_content` | "read this URL", "summarize this page" | `url` |
| `calculate` | "what is 15 * 6", "sqrt(144)" | `expression` |
| `convert_temperature` | "convert 100F to Celsius" | `value`, `from_unit`, `to_unit` |
| `convert_length` | "10 miles to km" | `value`, `from_unit`, `to_unit` |
| `set_timer` | "set timer for 5 minutes" | `duration_seconds` |
| `tell_joke` | "tell me a joke" | — |
| `open_website` | "open github.com", "google Python" | `query` |

---

## System & Monitor Tools

### Monitoring *(read-only)*

| Tool | Description |
|---|---|
| `system_status` | CPU + RAM + disk + battery summary |
| `get_cpu_usage` | CPU utilisation % |
| `get_memory_usage` | RAM used / total |
| `get_disk_usage` | Disk % with free space |
| `get_battery_info` | Battery %, charging status, time remaining |
| `get_network_info` | Bytes sent / received |
| `get_system_uptime` | Time since last boot |
| `get_running_processes` | Top N processes by memory |
| `get_gpu_stats` | GPU load, VRAM, temperature |
| `get_temperature_sensors` | CPU/hardware thermal readings |
| `check_system_alerts` | Threshold-based warnings |
| `get_full_system_report` | All metrics in one report |

### Application Control

| Tool | Confirmation? | Description |
|---|---|---|
| `open_program` | ❌ | Launch an app (fuzzy match via AppRegistry) |
| `scan_system_applications` | ❌ | Rebuild the app registry cache |
| `terminate_program` | ✅ | Kill a process by name |
| `take_screenshot` | ❌ | Capture and save screen to Downloads |
| `set_volume` | ❌ | Set system volume 0–100 |
| `get_volume` | ❌ | Query current volume |
| `set_brightness` | ❌ | Set screen brightness 0–100 |
| `list_open_apps` | ❌ | List visible running applications |

### File Operations

| Tool | Confirmation? | Description |
|---|---|---|
| `search_file` | ❌ | Glob search in `SEARCH_ALLOWED_DIRS` |
| `copy_file` | ❌ | Copy file to destination |
| `move_file` | ❌ | Move file to destination |
| `delete_file` | ✅ | Delete (backup to temp first) |
| `create_folder` | ❌ | Create directory |

---

## Productivity Tools

| Tool | Description |
|---|---|
| `add_task` | Create a task |
| `list_tasks` | List all tasks (filterable by status) |
| `complete_task` | Mark a task done by ID or content match |
| `get_task_summary` | Task count stats |
| `add_reminder` | Natural-language time parsing via `dateparser` |
| `list_reminders` | Active reminders |
| `create_note` | Titled note with content |
| `list_notes` | All notes |
| `get_note` | Read note by ID or title match |
| `start_pomodoro` | 25-min focus timer (persisted in DB) |
| `stop_pomodoro` | Cancel active pomodoro session |
| `pomodoro_status` | Elapsed time, cycles completed today |
| `schedule_future_task` | APScheduler-backed delayed agent execution |

---

## Communication Tools

| Tool | Provider | Confirmation? |
|---|---|---|
| `send_email` | SMTP (`aiosmtplib`) | ✅ |
| `read_unread_emails` | IMAP (`imap_tools`) | ❌ |
| `send_outlook_email` | `pywin32` (Windows only) | ✅ |
| `read_outlook_emails` | `pywin32` (Windows only) | ❌ |
| `send_slack_message` | Slack SDK | ✅ |
| `list_slack_channels` | Slack SDK | ❌ |
| `read_slack_messages` | Slack SDK | ❌ |

---

## Filesystem Tools

All sandboxed to `DATA_DIR/agent_workspace/`. Path traversal attempts are blocked at the `_safe_resolve()` level.

| Tool | Confirmation? | Description |
|---|---|---|
| `fs_list_directory` | ❌ | List workspace contents |
| `fs_read_file` | ❌ | Read a text file (5,000 char limit) |
| `fs_write_file` | ✅ | Create or overwrite a file |
| `fs_search_files` | ❌ | Glob search within workspace |

---

## Developer Tools

| Tool | Confirmation? | Description |
|---|---|---|
| `execute_python_script` | ✅ | Docker sandbox — `--network=none`, `--memory=128m`, `--cpus=0.5`, non-root, auto-removed |

The sandbox runs `python:3.10-slim` containers. The script is mounted read-only, stdout/stderr is captured, and the container is auto-removed on completion.

**Limits:**
- Max execution time: **15 seconds** (configurable via `TOOL_TIMEOUTS`)
- Memory: `128m`
- CPU: `0.5` cores
- Network: disabled (`--network=none`)
- User: non-root

---

## Workspace Search

| Tool | Description |
|---|---|
| `search_workspace` | Hybrid BM25 + semantic search over all indexed local files. Returns snippets with file path, line number, and RRF score. |

The indexer singleton is lazy-loaded on first call. If the index doesn't exist, the tool returns a helpful message directing the user to run `scripts/index_workspace.py`.

---

*← [[Core-Systems]] | [[API-Reference]] →*

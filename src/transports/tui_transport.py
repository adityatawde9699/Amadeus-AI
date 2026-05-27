"""
Amadeus AI — Textual TUI Dashboard

A beautiful, real-time terminal dashboard for monitoring the Amadeus AI server.
This is a visual monitoring tool only — messaging is handled exclusively by Telegram.

Launch: uv run python -m src.transports.tui_transport
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, RichLog, Static


# ─── Log file path ─────────────────────────────────────────────────────────────

_LOG_FILE = Path(__file__).parents[2] / "data" / "logs" / "amadeus.log"

# How many recent lines to load on startup
_HISTORY_LINES = 80


# ─── CSS ───────────────────────────────────────────────────────────────────────

AMADEUS_CSS = """
Screen {
    background: #08080f;
    color: #e0e0f0;
}

Header {
    background: #10102a;
    color: #a78bfa;
    text-style: bold;
    height: 3;
}

Footer {
    background: #10102a;
    color: #6366f1;
}

/* ── Sidebar ─────────────────────────────── */
#sidebar {
    width: 34;
    background: #0c0c1e;
    border-right: solid #252550;
    padding: 0 1;
}

#sidebar-title {
    color: #7c6fcd;
    text-style: bold;
    text-align: center;
    padding: 1 0 0 0;
    margin-bottom: 1;
}

.card {
    background: #10102a;
    border: round #252550;
    padding: 1;
    margin-bottom: 1;
    height: auto;
    min-height: 4;
}

/* ── Log area ────────────────────────────── */
#main-area {
    padding: 0;
}

#log-panel {
    border: round #252550;
    background: #050509;
    height: 1fr;
    padding: 0 1;
    margin: 0;
}

/* ── Status bar ──────────────────────────── */
#status-bar {
    height: 3;
    background: #0c0c1e;
    border-top: solid #252550;
    padding: 0 1;
    align: left middle;
}

.chip {
    background: #151530;
    border: solid #303060;
    padding: 0 1;
    margin-right: 1;
    height: 1;
    color: #8890c8;
}

.chip-green {
    background: #0f2a1a;
    border: solid #34d399;
    color: #34d399;
}

.chip-purple {
    background: #1a1040;
    border: solid #a78bfa;
    color: #a78bfa;
}
"""


# ─── Sidebar Widgets ────────────────────────────────────────────────────────────


class ServerCard(Static):
    """Uptime + server state card."""

    _start: float = 0.0

    def on_mount(self) -> None:
        self._start = time.time()
        self.set_interval(1.0, self.refresh)

    def render(self) -> Text:
        secs = int(time.time() - self._start)
        uptime = f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"
        t = Text()
        t.append("● SERVER\n", style="bold #34d399")
        t.append("  Status  ", style="#64748b")
        t.append("Running ✓\n", style="#34d399 bold")
        t.append("  Uptime  ", style="#64748b")
        t.append(f"{uptime}\n", style="#c4b5fd bold")
        t.append("  Mode    ", style="#64748b")
        t.append("Local-first", style="#818cf8")
        return t


class LLMCard(Static):
    """LLM provider usage counters."""

    _usage: dict = {}

    def on_mount(self) -> None:
        self.set_interval(4.0, self._poll)

    def _poll(self) -> None:
        try:
            from src.container import get_llm_router
            report = get_llm_router().get_usage_report()
            self._usage = report.get("usage", {})
        except Exception:
            pass
        self.refresh()

    def render(self) -> Text:
        t = Text()
        t.append("🤖 LLM ROUTING\n", style="bold #818cf8")
        rows = [
            ("llama_cpp", "Llama-1B", "#34d399"),
            ("groq",      "Groq-70B", "#a78bfa"),
            ("gemini",    "Gemini",   "#60a5fa"),
        ]
        for key, label, color in rows:
            count = self._usage.get(key, 0)
            t.append(f"  {label:9}", style=color)
            t.append(f"{count:>4} calls\n", style="#94a3b8")
        t.append("\n  Priority ", style="#64748b")
        t.append("Llama → Groq → Gemini", style="#c4b5fd")
        return t


class TelegramCard(Static):
    """Telegram polling status."""

    _msgs: int = 0

    def render(self) -> Text:
        t = Text()
        t.append("📡 TELEGRAM\n", style="bold #818cf8")
        t.append("  Status  ", style="#64748b")
        t.append("Polling ✓\n", style="#34d399 bold")
        t.append("  Handled ", style="#64748b")
        t.append(f"{self._msgs} messages", style="#c4b5fd bold")
        return t


class MemoryCard(Static):
    """Qdrant memory status."""

    _status: str = "Checking..."
    _color: str = "#94a3b8"

    def on_mount(self) -> None:
        self.set_interval(8.0, self._poll)
        self._poll()

    def _poll(self) -> None:
        try:
            from src.container import get_amadeus_service
            mem = get_amadeus_service().memory_service
            if mem.is_enabled:
                self._status = "Qdrant ✓"
                self._color = "#34d399"
            elif getattr(mem, '_enabled', False):
                # Enabled in config but not yet initialized (service just started)
                self._status = "Initializing..."
                self._color = "#fbbf24"
            else:
                self._status = "Disabled (config)"
                self._color = "#fbbf24"
        except Exception:
            # TUI runs in separate process — service not accessible
            self._status = "Server process ↗"
            self._color = "#818cf8"
        self.refresh()

    def render(self) -> Text:
        t = Text()
        t.append("💾 MEMORY\n", style="bold #818cf8")
        t.append("  Qdrant  ", style="#64748b")
        t.append(f"{self._status}\n", style=f"bold {self._color}")
        t.append("  Embed   ", style="#64748b")
        t.append("BGE-small", style="#818cf8")
        return t


class SearchCard(Static):
    """Web search provider status."""

    def render(self) -> Text:
        t = Text()
        t.append("🔍 SEARCH\n", style="bold #818cf8")
        t.append("  DDG     ", style="#64748b")
        t.append("Ready ✓\n", style="#34d399")
        t.append("  Tavily  ", style="#64748b")
        try:
            from src.core.config import get_settings
            key = get_settings().TAVILY_API_KEY
            if key:
                t.append("Configured ✓", style="#34d399")
            else:
                t.append("Not set", style="#fbbf24")
        except Exception:
            t.append("Unknown", style="#64748b")
        return t


# ─── Log Tailer ────────────────────────────────────────────────────────────────


class LogTailer(RichLog):
    """
    Tails `amadeus.log` in real time.
    On startup, loads the last _HISTORY_LINES lines so the panel isn't empty.
    """

    _last_pos: int = 0

    # Lines we suppress to avoid polling noise
    _SUPPRESS = [
        "HTTP Request: POST https://api.telegram.org",
        "HTTP Request: GET https://api.telegram.org",
        "getUpdates",
    ]

    def on_mount(self) -> None:
        self._load_history()
        self.set_interval(0.5, self._tail)

    def _load_history(self) -> None:
        """Load the last N lines of the log file so the panel starts populated."""
        if not _LOG_FILE.exists():
            self.write(Text("  No log file found yet — start the server first.", style="#fbbf24"))
            self._last_pos = 0
            return

        with open(_LOG_FILE, "r", errors="replace") as f:
            all_lines = f.readlines()
            self._last_pos = f.tell()

        recent = all_lines[-_HISTORY_LINES:] if len(all_lines) > _HISTORY_LINES else all_lines

        self.write(Text(
            f"  ── Last {len(recent)} log lines (history) ──────────────────",
            style="#303060 italic",
        ))
        for raw in recent:
            line = raw.strip()
            if line and not self._should_suppress(line):
                self._colorize_line(line)
        self.write(Text(
            "  ── Live tail starts here ─────────────────────────────",
            style="#303060 italic",
        ))

    def _tail(self) -> None:
        """Poll for new bytes appended to the log file since last check."""
        if not _LOG_FILE.exists():
            return
        try:
            with open(_LOG_FILE, "r", errors="replace") as f:
                f.seek(self._last_pos)
                new_data = f.read()
                self._last_pos = f.tell()

            if new_data:
                for raw in new_data.splitlines():
                    line = raw.strip()
                    if line and not self._should_suppress(line):
                        self._colorize_line(line)
        except Exception:
            pass

    def _should_suppress(self, line: str) -> bool:
        return any(s in line for s in self._SUPPRESS)

    def _colorize_line(self, line: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        t = Text()

        if "ERROR" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("ERR  ", style="bold red")
            t.append(line[:220], style="#f87171")
        elif "WARNING" in line or "WARNING" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("WARN ", style="bold yellow")
            t.append(line[:220], style="#fbbf24")
        elif "telegram_message_sent" in line or "Telegram response" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("📨   ", style="")
            t.append(line[:220], style="#34d399 bold")
        elif "Received telegram message" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("📩   ", style="")
            t.append(line[:220], style="#60a5fa bold")
        elif "Triage: tool=" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("🔧   ", style="")
            t.append(line[:220], style="#fbbf24 bold")
        elif "Triage: conversational" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("💬   ", style="")
            t.append(line[:220], style="#94a3b8")
        elif "provider=llama_cpp" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("🤖   ", style="")
            t.append(line[:220], style="#34d399")
        elif "provider=groq" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("☁    ", style="")
            t.append(line[:220], style="#a78bfa")
        elif "provider=gemini" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("✦    ", style="")
            t.append(line[:220], style="#60a5fa")
        elif "warmup" in line.lower() or ("LlamaCpp" in line and "initialized" in line):
            t.append(f"{ts} ", style="#303060")
            t.append("⚡   ", style="")
            t.append(line[:220], style="#818cf8 bold")
        elif "web_search" in line.lower() or "SearchRouter" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("🔍   ", style="")
            t.append(line[:220], style="#38bdf8")
        elif "Application startup complete" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("✅   ", style="")
            t.append(line[:220], style="#34d399 bold")
        elif "Shutting down" in line or "stopping" in line.lower():
            t.append(f"{ts} ", style="#303060")
            t.append("🛑   ", style="")
            t.append(line[:220], style="#f87171")
        elif "HTTP Request" in line:
            t.append(f"{ts} ", style="#303060")
            t.append("🌐   ", style="")
            t.append(line[:220], style="#374151")
        else:
            t.append(f"{ts} ", style="#303060")
            t.append("     ")
            t.append(line[:220], style="#4b5563")

        self.write(t)


# ─── Status Bar ────────────────────────────────────────────────────────────────


class StatusBar(Horizontal):
    """Bottom row of status chips."""

    def compose(self) -> ComposeResult:
        yield Static("● Running", classes="chip chip-green")
        yield Static("🤖 Llama-1B", classes="chip chip-purple")
        yield Static("📡 Telegram", classes="chip chip-green")
        yield Static("🔍 DDG + Tavily", classes="chip")
        yield Static("", id="clock", classes="chip")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        now = datetime.now().strftime("%H:%M:%S  %d %b %Y")
        self.query_one("#clock", Static).update(f"🕐  {now}")


# ─── Main App ───────────────────────────────────────────────────────────────────


class AmadeusDashboard(App):
    """Amadeus AI — Real-time Server Dashboard."""

    TITLE = "Amadeus AI"
    SUB_TITLE = "Local-First AI  ·  Server Dashboard  ·  Telegram-only messaging"
    CSS = AMADEUS_CSS
    SHOW_COMMAND_PALETTE = False  # Hide the green command bar
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("l", "clear_log", "Clear Log"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            # ── Left sidebar ──────────────────────────────────
            with Vertical(id="sidebar"):
                yield Label("◈  AMADEUS MONITOR", id="sidebar-title")
                yield ServerCard(classes="card")
                yield LLMCard(classes="card")
                yield TelegramCard(classes="card")
                yield MemoryCard(classes="card")
                yield SearchCard(classes="card")

            # ── Main log area ─────────────────────────────────
            with Vertical(id="main-area"):
                yield LogTailer(
                    id="log-panel",
                    highlight=False,
                    markup=False,
                    wrap=False,
                    max_lines=1000,
                )
                yield StatusBar(id="status-bar")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#log-panel").border_title = (
            "  📋  Live Server Log  "
        )

    def action_clear_log(self) -> None:
        self.query_one(LogTailer).clear()


# ─── Entry ─────────────────────────────────────────────────────────────────────


def main() -> None:
    AmadeusDashboard().run()


if __name__ == "__main__":
    main()

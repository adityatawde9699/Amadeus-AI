"""
Deterministic argument ("slot") extraction for tools: no LLM.

``extract_slots(tool_name, text)`` returns the argument dict when every
required argument can be filled from the text with rules, or ``None`` when it
cannot. ``None`` is the signal to use the LLM (expert agent or LLM extraction):
a wrong guess here would run a tool with bad arguments, so every extractor
prefers ``None`` over guessing.

Tools without an extractor return ``None`` unless they take no required
arguments.
"""

from __future__ import annotations

import inspect
import re
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.app.services.tool_registry import ToolRegistry


Slots = dict[str, Any]

_POLITE = re.compile(
    r"^(?:(?:hey|hi|ok|okay)\s+)?(?:amadeus[,:]?\s+)?(?:please\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?(?:i\s+(?:want|need)\s+(?:you\s+)?to\s+)?",
    re.IGNORECASE,
)
_TRAILING = re.compile(r"(?:\s+(?:please|for me|right now|now|thanks|thank you))+[\s?.!]*$", re.I)
_NUMBER = r"-?\d+(?:[.,]\d+)?"


def _clean(text: str) -> str:
    """Strip greetings, politeness and trailing filler/punctuation."""
    out = _POLITE.sub("", text.strip())
    out = _TRAILING.sub("", out)
    return out.strip(" \t?.!")


def _after(text: str, pattern: str) -> str | None:
    """Text following the first match of *pattern* (case-insensitive), cleaned."""
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    rest = text[m.end() :].strip(" \t?.!:,")
    return rest or None


def _num(raw: str) -> float:
    return float(raw.replace(",", ""))


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------

_MATH_WORDS: tuple[tuple[str, str], ...] = (
    (r"\bto the power of\b", "**"),
    (r"\braised to\b", "**"),
    (r"\bmultiplied by\b", "*"),
    (r"\bdivided by\b", "/"),
    (r"\btimes\b", "*"),
    (r"\bplus\b", "+"),
    (r"\bminus\b", "-"),
    (r"\bover\b", "/"),
    (r"\bmod(?:ulo)?\b", "%"),
    (r"(?<=\d)\s*x\s*(?=\d)", " * "),
)


def _calculate(text: str) -> Slots | None:
    expr = _clean(text).lower()
    expr = re.sub(
        r"^(?:what(?:'s| is)|how much is|calculate|compute|evaluate|solve|work out)\s+", "", expr
    )
    expr = re.sub(rf"({_NUMBER})\s*(?:%|percent)\s+of\s+({_NUMBER})", r"(\1 / 100) * \2", expr)
    expr = re.sub(rf"square root of\s+({_NUMBER})", r"sqrt(\1)", expr)
    expr = re.sub(rf"\badd\s+({_NUMBER})\s+(?:and|to)\s+({_NUMBER})", r"\1 + \2", expr)
    expr = re.sub(rf"\bsubtract\s+({_NUMBER})\s+from\s+({_NUMBER})", r"\2 - \1", expr)
    for pattern, symbol in _MATH_WORDS:
        expr = re.sub(pattern, symbol, expr)
    expr = expr.replace(",", "").strip()
    # Only digits, operators and known functions may remain.
    if not re.search(r"\d", expr) or re.search(
        r"[a-z]+", re.sub(r"\b(?:sqrt|sin|cos|tan|log|abs|pi|e)\b", "", expr)
    ):
        return None
    return {"expression": expr}


_TEMP_UNITS = {
    "c": "C", "celsius": "C", "centigrade": "C", "°c": "C",
    "f": "F", "fahrenheit": "F", "°f": "F",
    "k": "K", "kelvin": "K",
}  # fmt: skip
_LENGTH_UNITS = {
    "mm": "mm", "millimeter": "mm", "millimetre": "mm",
    "cm": "cm", "centimeter": "cm", "centimetre": "cm",
    "m": "m", "meter": "m", "metre": "m",
    "km": "km", "kilometer": "km", "kilometre": "km",
    "in": "in", "inch": "in", "inches": "in",
    "ft": "ft", "foot": "ft", "feet": "ft",
    "yd": "yd", "yard": "yd",
    "mi": "mi", "mile": "mi",
}  # fmt: skip


def _unit(raw: str, table: dict[str, str]) -> str | None:
    key = raw.lower().strip(" .")
    if key in table:
        return table[key]
    if key.endswith("s") and key[:-1] in table:
        return table[key[:-1]]
    return None


def _convert(text: str, table: dict[str, str]) -> Slots | None:
    lower = _clean(text).lower().replace("degrees ", "").replace("degree ", "")
    word = r"(°?[a-z]+)"
    # "convert 5 miles to km", "72 f in c"
    m = re.search(rf"({_NUMBER})\s*{word}\s+(?:to|in|into|as)\s+{word}", lower)
    if m:
        value, src, dst = _num(m.group(1)), _unit(m.group(2), table), _unit(m.group(3), table)
    else:
        # "how many kilometers is 26 miles", "how many feet in 3 meters"
        m = re.search(
            rf"how many\s+{word}\s+(?:is|are|in|make|equal)(?:\s+in)?\s+({_NUMBER})\s*{word}", lower
        )
        if not m:
            return None
        value, src, dst = _num(m.group(2)), _unit(m.group(3), table), _unit(m.group(1), table)
    if src is None or dst is None:
        return None
    return {"value": value, "from_unit": src, "to_unit": dst}


_CURRENCIES = {
    "dollar": "USD", "usd": "USD", "buck": "USD", "$": "USD",
    "rupee": "INR", "inr": "INR", "rs": "INR", "₹": "INR",
    "euro": "EUR", "eur": "EUR", "€": "EUR",
    "pound": "GBP", "gbp": "GBP", "£": "GBP",
    "yen": "JPY", "jpy": "JPY", "yuan": "CNY", "cny": "CNY",
    "aud": "AUD", "cad": "CAD", "chf": "CHF", "sgd": "SGD", "aed": "AED",
}  # fmt: skip


def _convert_currency(text: str) -> Slots | None:
    lower = _clean(text).lower()
    m = re.search(rf"({_NUMBER})?\s*([a-z$₹€£]+)\s+(?:to|in|into)\s+([a-z$₹€£]+)", lower)
    if not m:
        return None
    src, dst = _unit(m.group(2), _CURRENCIES), _unit(m.group(3), _CURRENCIES)
    if src is None or dst is None:
        return None
    return {
        "amount": _num(m.group(1)) if m.group(1) else 1.0,
        "from_currency": src,
        "to_currency": dst,
    }


# ---------------------------------------------------------------------------
# Information
# ---------------------------------------------------------------------------


def _weather(text: str) -> Slots | None:
    m = re.search(
        r"\b(?:in|at|for|of)\s+([A-Za-z][A-Za-z .'-]*?)(?:\s+(?:right now|now|today|tomorrow|"
        r"this week|tonight|please))*[\s?.!]*$",
        _clean(text),
        re.IGNORECASE,
    )
    return {"location": m.group(1).strip()} if m else {}


def _datetime(text: str) -> Slots | None:
    lower = text.lower()
    for key in ("time", "date", "day", "week", "month", "year"):
        if key in lower:
            return {"query": key}
    return {"query": "datetime"}


_COINS = (
    "bitcoin", "btc", "ethereum", "eth", "dogecoin", "doge", "solana", "sol", "cardano",
    "ada", "ripple", "xrp", "litecoin", "ltc", "polkadot", "bnb", "tether", "usdt",
    "monero", "xmr", "tron", "shiba inu", "avalanche", "chainlink", "polygon", "matic",
)  # fmt: skip


def _crypto(text: str) -> Slots | None:
    lower = text.lower()
    for coin in _COINS:
        if re.search(rf"\b{re.escape(coin)}\b", lower):
            return {"coin": coin}
    return None


_COMPANIES = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "tesla": "TSLA", "nvidia": "NVDA", "meta": "META", "netflix": "NFLX",
    "infosys": "INFY", "tcs": "TCS.NS", "reliance": "RELIANCE.NS", "intel": "INTC", "amd": "AMD",
}  # fmt: skip
_NOT_TICKERS = {"I", "A", "THE", "IS", "US", "USA", "UK", "CEO", "IPO", "AI", "PE", "ETF", "NYSE"}


def _stock(text: str) -> Slots | None:
    for ticker in re.findall(r"\b[A-Z]{2,5}(?:\.[A-Z]{1,2})?\b", text):
        if ticker not in _NOT_TICKERS:
            return {"symbol": ticker}
    lower = text.lower()
    for name, ticker in _COMPANIES.items():
        if re.search(rf"\b{name}\b", lower):
            return {"symbol": ticker}
    return None


_SEARCH_PREFIX = re.compile(
    r"^(?:search (?:the )?(?:web|internet|online|wikipedia) for|search for|search|look up|"
    r"google|find (?:me )?(?:info(?:rmation)? (?:about|on))?|tell me about|who (?:is|was|are|were)|"
    r"what (?:is|are|was|were)|give me info(?:rmation)? (?:about|on)|research|"
    r"wikipedia (?:article|page) (?:on|about|for))\s+",
    re.IGNORECASE,
)
_SEARCH_SUFFIX = re.compile(
    r"\s+(?:on|from|in|via|using) (?:wikipedia|google|the (?:web|internet))$|\s+online$", re.I
)


def _search(text: str) -> Slots | None:
    query = _SEARCH_SUFFIX.sub("", _SEARCH_PREFIX.sub("", _clean(text))).strip()
    return {"query": query} if query else None


def _code_search(text: str) -> Slots | None:
    query = _clean(text)
    query = re.sub(
        r"^(?:grep|search|look through|find(?: where| usages of)?|where is|locate)\s+"
        r"(?:(?:in |through )?(?:the |my )?(?:codebase|code|repo(?:sitory)?|source|workspace)"
        r"(?: files)?\s+for\s+)?",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s+(?:is |are )?(?:defined |declared |used |implemented )?(?:in|inside|across) "
        r"(?:the |my )?(?:codebase|code|repo(?:sitory)?|source|workspace)(?: files)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\s+is (?:defined|declared|implemented)$", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^the\s+", "", query.strip(), flags=re.IGNORECASE)
    return {"query": query} if query else None


_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_HOST = re.compile(
    r"\b((?:\d{1,3}\.){3}\d{1,3}|(?:[a-z0-9-]+\.)+[a-z]{2,}|localhost)\b", re.IGNORECASE
)


def _url(text: str) -> Slots | None:
    m = _URL.search(text)
    return {"url": m.group(0).rstrip(".,)")} if m else None


def _open_website(text: str) -> Slots | None:
    if (found := _url(text)) is not None:
        return found
    m = _HOST.search(text)
    if m:
        return {"url": m.group(1)}
    rest = _after(_clean(text), r"^(?:open|go to|visit|browse to)\s+(?:the\s+)?(?:website\s+)?")
    return {"query": rest} if rest else None


def _ping(text: str) -> Slots | None:
    m = _HOST.search(text)
    return {"host": m.group(1)} if m else None


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

_PATH = re.compile(r"(?:[~.]?/)?[\w.-]+(?:/[\w.-]+)+/?|[\w-]+\.[A-Za-z0-9]{1,8}\b|[~.]/[\w.-]*")


def _path(text: str) -> str | None:
    quoted = re.search(r"[\"'`]([^\"'`]+)[\"'`]", text)
    if quoted:
        return quoted.group(1)
    m = _PATH.search(text)
    return m.group(0) if m else None


def _read_file(text: str) -> Slots | None:
    path = _path(text)
    return {"path": path} if path else None


def _list_directory(text: str) -> Slots | None:
    path = _path(text)
    if path:
        return {"path": path}
    m = re.search(
        r"\b(?:in|inside|of)\s+(?:the\s+|my\s+)?([\w.-]+)\s+(?:directory|folder|dir)\b", text, re.I
    )
    if m:
        name = m.group(1)
        return {"path": "." if name.lower() in {"current", "this", "working"} else name}
    if re.search(r"\b(?:current|this|working)\s+(?:directory|folder|dir)\b|\bhere\b", text, re.I):
        return {"path": "."}
    return None


def _search_file(text: str) -> Slots | None:
    name = _path(text) or _after(
        _clean(text),
        r"^(?:find|locate|where is|where did i save|search for)\s+(?:the\s+|my\s+)?"
        r"(?:file\s+|document\s+)?(?:named\s+|called\s+)?",
    )
    return {"file_name": name} if name else None


def _create_folder(text: str) -> Slots | None:
    name = _after(_clean(text), r"\b(?:folder|directory|dir)\s+(?:called|named)?\s*")
    return {"folder_name": name} if name else None


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------


def _app(verbs: str, key: str) -> Callable[[str], Slots | None]:
    def extractor(text: str) -> Slots | None:
        name = _after(_clean(text), rf"\b(?:{verbs})\s+(?:up\s+)?(?:the\s+)?")
        if not name:
            return None
        name = re.sub(r"\s+(?:app|application|program|window)$", "", name, flags=re.IGNORECASE)
        return {key: name} if name else None

    return extractor


# ---------------------------------------------------------------------------
# Tasks, notes, memory, timers
# ---------------------------------------------------------------------------


def _add_task(text: str) -> Slots | None:
    clean = _clean(text)
    m = re.search(
        r"^(?:put|add)\s+(.+?)\s+(?:on|to|in)\s+my\s+(?:task|todo|to-do)s?(?:\s+list)?$",
        clean,
        re.I,
    )
    if m:
        return {"task_content": m.group(1).strip()}
    content = _after(
        clean,
        r"^(?:add|create|make|new)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:task|todo|to-do)(?:\s+item)?\s*"
        r"(?:[:\-]\s*|to\s+|for\s+|that\s+says\s+)?",
    )
    return {"task_content": content} if content else None


def _create_note(text: str) -> Slots | None:
    content = _after(
        _clean(text),
        r"^(?:take|make|save|create|write|jot)\s+(?:a\s+)?(?:quick\s+)?note(?:\s+down)?\s*"
        r"(?:[:\-]\s*|that\s+|about\s+|saying\s+)?|^note\s+(?:down\s+)?(?:that\s+)?|"
        r"^write\s+this\s+down\s*[:\-]?\s*",
    )
    return {"content": content} if content else None


def _store_memory(text: str) -> Slots | None:
    fact = _after(
        _clean(text),
        r"^(?:remember|keep in mind|don't forget|do not forget|note for later|memori[sz]e)\s+"
        r"(?:that\s+)?",
    )
    return {"fact": fact} if fact else None


def _forget_memory(text: str) -> Slots | None:
    fact = _after(_clean(text), r"^forget\s+(?:that\s+|about\s+)?")
    return {"fact": fact} if fact else None


_TIME_EXPR = re.compile(
    r"\b(in\s+\d+\s+\w+|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|tomorrow(?:\s+(?:morning|afternoon|"
    r"evening|night))?|tonight|this\s+evening|next\s+\w+)\b",
    re.IGNORECASE,
)


def _reminder(text: str) -> Slots | None:
    clean = _clean(text)
    when = _TIME_EXPR.search(clean)
    title = re.sub(
        r"^(?:remind\s+me\s+(?:to\s+|about\s+)?|set\s+a?\s*reminder\s+(?:to\s+|for\s+)?)",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    if when:
        title = title.replace(when.group(0), " ")
    title = re.sub(r"\s+", " ", title).strip(" ,.")
    title = re.sub(r"^(?:to|about)\s+", "", title)
    if not title or not when:
        return None
    return {"title": title, "time": when.group(0)}


def _timer(text: str) -> Slots | None:
    lower = text.lower()
    total = 0.0
    for value, unit in re.findall(rf"({_NUMBER})\s*(hour|hr|minute|min|second|sec)", lower):
        total += _num(value) * {"h": 3600, "m": 60, "s": 1}[unit[0]]
    return {"duration_seconds": int(total)} if total > 0 else None


def _pomodoro(text: str) -> Slots | None:
    slots: Slots = {}
    m = re.search(rf"({_NUMBER})\s*(?:-\s*)?min", text.lower())
    if m:
        slots["duration"] = int(_num(m.group(1)))
    task = _after(_clean(text), r"\b(?:pomodoro|focus session|focus timer)\s+(?:for|on)\s+")
    if task and not re.match(rf"{_NUMBER}\s*min", task):
        slots["task"] = task
    return slots


def _identifier(key: str) -> Callable[[str], Slots | None]:
    def extractor(text: str) -> Slots | None:
        m = re.search(r"\b(?:task|note|goal|number|#)\s*#?(\d+)\b", text, re.IGNORECASE)
        return {key: m.group(1)} if m else None

    return extractor


def _goal_id(text: str) -> Slots | None:
    m = re.search(r"\bgoal\s*#?(\d+)\b", text, re.IGNORECASE)
    return {"goal_id": int(m.group(1))} if m else None


def _process_count(text: str) -> Slots | None:
    m = re.search(r"\btop\s+(\d+)\b|\b(\d+)\s+process", text.lower())
    return {"count": int(m.group(1) or m.group(2))} if m else {}


def _news(text: str) -> Slots | None:
    from src.app.services.argument_extractor import ArgumentExtractor

    return ArgumentExtractor._parse_news_args(text.lower())


def _list_tasks(text: str) -> Slots | None:
    lower = text.lower()
    if re.search(r"\b(?:completed|done|finished)\b", lower):
        return {"status_filter": "completed"}
    if re.search(r"\b(?:pending|open|remaining|incomplete|left|still)\b", lower):
        return {"status_filter": "pending"}
    return {}


_EXTRACTORS: dict[str, Callable[[str], Slots | None]] = {
    "calculate": _calculate,
    "convert_temperature": lambda t: _convert(t, _TEMP_UNITS),
    "convert_length": lambda t: _convert(t, _LENGTH_UNITS),
    "convert_currency": _convert_currency,
    "get_weather": _weather,
    "get_datetime_info": _datetime,
    "get_crypto_price": _crypto,
    "get_stock_price": _stock,
    "get_news": _news,
    "web_search": _search,
    "wikipedia_search": _search,
    "search_codebase": _code_search,
    "search_workspace": _code_search,
    "fetch_webpage_content": _url,
    "open_website": _open_website,
    "ping_host": _ping,
    "fs_read_file": _read_file,
    "fs_list_directory": _list_directory,
    "search_file": _search_file,
    "create_folder": _create_folder,
    "open_program": _app("open|launch|start|run|bring|fire", "app_name"),
    "launch_app": _app("open|launch|start|run|bring|fire", "app_name"),
    "terminate_program": _app("close|kill|quit|terminate|stop|exit|end|shut", "process_name"),
    "terminate_process": _app("close|kill|quit|terminate|stop|exit|end|shut", "process_name"),
    "add_task": _add_task,
    "list_tasks": _list_tasks,
    "complete_task": _identifier("identifier"),
    "get_note": _identifier("identifier"),
    "create_note": _create_note,
    "add_reminder": _reminder,
    "set_timer": _timer,
    "start_pomodoro": _pomodoro,
    "store_core_memory": _store_memory,
    "forget_core_memory": _forget_memory,
    "decompose_goal": _goal_id,
    "execute_goal": _goal_id,
    "get_running_processes": _process_count,
    "take_screenshot": lambda _t: {},
}


def extract_slots(tool_name: str, text: str, registry: ToolRegistry | None = None) -> Slots | None:
    """Arguments for *tool_name* from *text*, or ``None`` if rules cannot fill them."""
    extractor = _EXTRACTORS.get(tool_name)
    if extractor is not None:
        try:
            return extractor(text)
        except Exception:
            return None
    tool = registry.get(tool_name) if registry is not None else None
    if tool is None:
        return None
    # No extractor: safe only when nothing has to be filled in. A parameter
    # defaulting to None is an argument the tool expects (``app_name=None``);
    # one with a real default (``path="/"``, ``count=10``) can be left alone.
    try:
        parameters = inspect.signature(tool.function).parameters.values()
    except (TypeError, ValueError):
        return None
    for p in parameters:
        if p.kind not in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY):
            continue
        if p.default is inspect.Parameter.empty or p.default is None:
            return None
    return {}

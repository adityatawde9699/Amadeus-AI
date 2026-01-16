"""
Information tools for Amadeus AI Assistant.

Includes weather, news, Wikipedia search, calculations, and conversions.
Migrated from general_utils.py to Clean Architecture structure.
"""

import asyncio
import logging
import random
import re
import urllib.parse
import webbrowser
from datetime import datetime
from typing import Any

import aiohttp

from src.core.config import get_settings
from src.infra.tools.base import Tool, ToolCategory, tool


logger = logging.getLogger(__name__)
settings = get_settings()


# =============================================================================
# GREETING & TIME TOOLS
# =============================================================================

@tool(
    name="get_greeting",
    description="Get an appropriate greeting based on time of day",
    category=ToolCategory.INFORMATION,
)
def get_greeting() -> str:
    """Returns an appropriate greeting based on the time of day."""
    hour = datetime.now().hour
    
    if 5 <= hour < 12:
        greetings = ["Good morning", "Morning", "Rise and shine"]
    elif 12 <= hour < 17:
        greetings = ["Good afternoon", "Afternoon"]
    elif 17 <= hour < 21:
        greetings = ["Good evening", "Evening"]
    else:
        greetings = ["Hello", "Hi there", "Hey"]
    
    return random.choice(greetings)


@tool(
    name="get_datetime_info",
    description="Return current time/date/day. Trigger: 'what time', 'current date', 'what day is it'",
    category=ToolCategory.INFORMATION,
    parameters={"query": {"type": "string", "description": "What to retrieve: time, date, day, week, month, year"}}
)
def get_datetime_info(query: str = "time") -> str:
    """Get current date, time, or day information."""
    now = datetime.now()
    query = query.lower().strip()
    
    if "time" in query:
        return f"The current time is {now.strftime('%I:%M %p')}"
    elif "date" in query:
        return f"Today's date is {now.strftime('%B %d, %Y')}"
    elif "day" in query:
        return f"Today is {now.strftime('%A')}"
    elif "week" in query:
        week_num = now.isocalendar()[1]
        return f"This is week {week_num} of {now.year}"
    elif "month" in query:
        return f"The current month is {now.strftime('%B %Y')}"
    elif "year" in query:
        return f"The current year is {now.year}"
    elif "datetime" in query or "full" in query:
        return f"It is {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d, %Y')}"
    else:
        return f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d, %Y')}"


# =============================================================================
# WEATHER TOOLS
# =============================================================================

@tool(
    name="get_weather",
    description="Get current weather + forecast. Trigger: 'weather in ___', 'is it raining', 'temperature'",
    category=ToolCategory.INFORMATION,
    parameters={"location": {"type": "string", "description": "City name or location"}}
)
async def get_weather_async(location: str = "India") -> str:
    """Fetches current weather for a location using OpenWeatherMap API."""
    api_key = settings.WEATHER_API_KEY
    if not api_key:
        return "Weather service unavailable. Please configure WEATHER_API_KEY."
    
    base_url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": location,
        "appid": api_key,
        "units": "metric"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 404:
                    return f"Sorry, I couldn't find weather data for '{location}'."
                elif response.status != 200:
                    return f"Weather service error (status {response.status})."
                
                data = await response.json()
                
                temp = data["main"]["temp"]
                feels_like = data["main"]["feels_like"]
                humidity = data["main"]["humidity"]
                description = data["weather"][0]["description"]
                city_name = data["name"]
                country = data["sys"].get("country", "")
                wind_speed = data.get("wind", {}).get("speed", 0)
                wind_kmh = round(wind_speed * 3.6, 1)
                
                return (
                    f"Weather in {city_name}, {country}: {description.capitalize()}. "
                    f"Temperature is {temp:.1f}°C (feels like {feels_like:.1f}°C). "
                    f"Humidity is {humidity}% with winds at {wind_kmh} km/h."
                )
                
    except asyncio.TimeoutError:
        return "Weather request timed out. Please try again."
    except aiohttp.ClientError as e:
        return f"Network error fetching weather: {e}"
    except KeyError as e:
        return f"Unexpected weather data format: {e}"
    except Exception as e:
        return f"Sorry, I couldn't fetch the weather: {e}"


# =============================================================================
# NEWS TOOLS
# =============================================================================

@tool(
    name="get_news",
    description="Fetch current news headlines. Trigger: 'news today', 'latest headlines', 'tech news'",
    category=ToolCategory.INFORMATION,
    parameters={
        "category": {"type": "string", "description": "Category: general, business, technology, sports, health"},
        "country": {"type": "string", "description": "Country code: in, us, gb"},
        "count": {"type": "integer", "description": "Number of headlines"}
    }
)
async def get_news_async(
    category: str | None = None,
    country: str | None = None,
    count: int | None = None
) -> str:
    """Fetches top news headlines using NewsAPI."""
    api_key = settings.NEWS_API_KEY
    if not api_key:
        return "News service unavailable. Please configure NEWS_API_KEY."
    
    category = category or "general"
    country = country or "in"
    count = count or 5
    
    base_url = "https://newsapi.org/v2/top-headlines"
    params = {
        "country": country,
        "category": category,
        "pageSize": count,
        "apiKey": api_key
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return f"News service error (status {response.status})."
                
                data = await response.json()
                
                if data.get("status") != "ok":
                    return f"News API error: {data.get('message', 'Unknown error')}"
                
                articles = data.get("articles", [])
                
                if not articles:
                    return f"No news articles found for {category} in {country}."
                
                headlines = []
                for i, article in enumerate(articles[:count], 1):
                    title = article.get("title", "No title")
                    source = article.get("source", {}).get("name", "Unknown")
                    headlines.append(f"{i}. {title} ({source})")
                
                return f"Top {len(headlines)} {category} headlines:\n" + "\n".join(headlines)
                
    except asyncio.TimeoutError:
        return "News request timed out. Please try again."
    except aiohttp.ClientError as e:
        return f"Network error fetching news: {e}"
    except Exception as e:
        return f"Sorry, I couldn't fetch the news: {e}"


# =============================================================================
# WEB BROWSING TOOLS
# =============================================================================

@tool(
    name="open_website",
    description="Open URL/Search Google. Trigger: 'open website', 'google ___', 'search for ___'",
    category=ToolCategory.INFORMATION,
    parameters={"query": {"type": "string", "description": "URL to open or search term"}}
)
def open_website(query: str | None = None, url: str | None = None, **kwargs: Any) -> str:
    """Opens a website or performs a Google search."""
    query = query or url or kwargs.get("link")
    if not query:
        return "Error: No URL or search query provided."
    
    query = query.strip()
    
    url_indicators = ["http://", "https://", "www.", ".com", ".org", ".net", ".io", ".dev"]
    is_url = any(indicator in query.lower() for indicator in url_indicators)
    
    try:
        if is_url:
            final_url = query
            if not final_url.startswith(("http://", "https://")):
                final_url = "https://" + final_url
            
            webbrowser.open(final_url)
            return f"Opening {final_url}"
        else:
            search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            webbrowser.open(search_url)
            return f"Searching Google for: {query}"
            
    except Exception as e:
        return f"Failed to open browser: {e}"


# =============================================================================
# WIKIPEDIA TOOLS
# =============================================================================

@tool(
    name="wikipedia_search",
    description="Get Wikipedia summary. Trigger: 'who is ___', 'what is ___', 'explain ___'",
    category=ToolCategory.INFORMATION,
    parameters={
        "query": {"type": "string", "description": "Search term"},
        "sentences": {"type": "integer", "description": "Number of sentences"}
    }
)
async def wikipedia_search_async(query: str, sentences: int = 3) -> str:
    """Searches Wikipedia and returns a summary."""
    base_url = "https://en.wikipedia.org/api/rest_v1/page/summary"
    search_url = f"{base_url}/{urllib.parse.quote(query)}"
    
    headers = {
        "User-Agent": "AmadeusAI/2.0 (https://github.com/adityatawde9699/Amadeus-AI)"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 404:
                    return await _wikipedia_search_fallback(query, session)
                elif response.status != 200:
                    return f"Wikipedia error (status {response.status})."
                
                data = await response.json()
                
                title = data.get("title", query)
                extract = data.get("extract", "")
                
                if not extract:
                    return f"No Wikipedia article found for '{query}'."
                
                sentences_list = extract.split(". ")
                limited = ". ".join(sentences_list[:sentences])
                if not limited.endswith("."):
                    limited += "."
                
                return f"From Wikipedia - {title}:\n{limited}"
                
    except asyncio.TimeoutError:
        return "Wikipedia request timed out."
    except Exception as e:
        return f"Error searching Wikipedia: {e}"


async def _wikipedia_search_fallback(query: str, session: aiohttp.ClientSession) -> str:
    """Fallback search using Wikipedia's search API."""
    search_api = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": 1
    }
    
    try:
        async with session.get(search_api, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
            data = await response.json()
            results = data.get("query", {}).get("search", [])
            
            if not results:
                return f"No Wikipedia results found for '{query}'."
            
            title = results[0].get("title", "")
            snippet = results[0].get("snippet", "").replace("<span class=\"searchmatch\">", "").replace("</span>", "")
            
            return f"Wikipedia result for '{query}':\n{title}: {snippet}..."
            
    except Exception as e:
        return f"Wikipedia search failed: {e}"


# =============================================================================
# CALCULATION TOOLS
# =============================================================================

@tool(
    name="calculate",
    description="Evaluate math expressions. Supports: +, -, *, /, **, %, sqrt. Trigger: '5+5', 'solve ___'",
    category=ToolCategory.INFORMATION,
    parameters={"expression": {"type": "string", "description": "Mathematical expression"}}
)
def calculate(expression: str) -> str:
    """Safely evaluates a mathematical expression."""
    allowed = set("0123456789+-*/.() ")
    
    expr = expression.replace("x", "*").replace("÷", "/").replace("^", "**")
    
    if not all(c in allowed or c == "*" for c in expr):
        return "Invalid characters in expression."
    
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero."
    except Exception as e:
        return f"Calculation error: {e}"


# =============================================================================
# CONVERSION TOOLS
# =============================================================================

@tool(
    name="convert_temperature",
    description="Convert temperature units. Trigger: 'convert C to F'",
    category=ToolCategory.INFORMATION,
    parameters={
        "value": {"type": "number", "description": "Temperature value"},
        "from_unit": {"type": "string", "description": "Source unit: C, F, K"},
        "to_unit": {"type": "string", "description": "Target unit: C, F, K"}
    }
)
def convert_temperature(value: float, from_unit: str, to_unit: str) -> str:
    """Converts temperature between Celsius, Fahrenheit, and Kelvin."""
    from_unit = from_unit.lower()[0]
    to_unit = to_unit.lower()[0]
    
    if from_unit == 'f':
        celsius = (value - 32) * 5/9
    elif from_unit == 'k':
        celsius = value - 273.15
    else:
        celsius = value
    
    if to_unit == 'f':
        result = celsius * 9/5 + 32
        unit_name = "Fahrenheit"
    elif to_unit == 'k':
        result = celsius + 273.15
        unit_name = "Kelvin"
    else:
        result = celsius
        unit_name = "Celsius"
    
    return f"{value}° = {result:.2f}° {unit_name}"


@tool(
    name="convert_length",
    description="Convert length units. Trigger: 'mm to cm', 'm to ft', 'km to miles'",
    category=ToolCategory.INFORMATION,
    parameters={
        "value": {"type": "number", "description": "Length value"},
        "from_unit": {"type": "string", "description": "Source unit"},
        "to_unit": {"type": "string", "description": "Target unit"}
    }
)
def convert_length(value: float, from_unit: str, to_unit: str) -> str:
    """Converts length between common units."""
    to_meters = {
        'mm': 0.001, 'cm': 0.01, 'm': 1, 'km': 1000,
        'in': 0.0254, 'ft': 0.3048, 'yd': 0.9144, 'mi': 1609.34
    }
    
    from_unit = from_unit.lower()
    to_unit = to_unit.lower()
    
    if from_unit not in to_meters or to_unit not in to_meters:
        return "Unknown unit. Supported: mm, cm, m, km, in, ft, yd, mi"
    
    meters = value * to_meters[from_unit]
    result = meters / to_meters[to_unit]
    
    return f"{value} {from_unit} = {result:.4f} {to_unit}"


# =============================================================================
# ENTERTAINMENT TOOLS
# =============================================================================

JOKES = [
    ("Why do programmers prefer dark mode?", "Because light attracts bugs!"),
    ("Why did the developer go broke?", "Because he used up all his cache!"),
    ("What's a computer's favorite snack?", "Microchips!"),
    ("Why do Java developers wear glasses?", "Because they can't C#!"),
    ("What do you call 8 hobbits?", "A hobbyte!"),
    ("Why did the computer go to the doctor?", "Because it had a virus!"),
    ("How do trees access the internet?", "They log in!"),
    ("Why was the JavaScript developer sad?", "Because he didn't Node how to Express himself!"),
    ("What's a programmer's favorite hangout place?", "Foo Bar!"),
    ("Why do programmers hate nature?", "It has too many bugs!"),
]


@tool(
    name="tell_joke",
    description="Tell a random programming joke. Trigger: 'tell me a joke', 'make me laugh'",
    category=ToolCategory.INFORMATION,
)
def tell_joke() -> str:
    """Returns a random programming joke."""
    setup, punchline = random.choice(JOKES)
    return f"{setup}\n\n{punchline}"


# =============================================================================
# TIMER TOOLS
# =============================================================================

@tool(
    name="set_timer",
    description="Set a timer. Trigger: 'set timer for 5 minutes'",
    category=ToolCategory.INFORMATION,
    parameters={
        "duration_seconds": {"type": "integer", "description": "Duration in seconds"},
        "message": {"type": "string", "description": "Message when timer completes"}
    }
)
async def set_timer_async(duration_seconds: int, message: str = "Timer finished!") -> str:
    """Sets a timer that triggers after the specified duration."""
    if duration_seconds <= 0:
        return "Timer duration must be positive."
    
    if duration_seconds > 86400:
        return "Timer cannot exceed 24 hours."
    
    if duration_seconds >= 3600:
        hours = duration_seconds // 3600
        mins = (duration_seconds % 3600) // 60
        duration_str = f"{hours}h {mins}m"
    elif duration_seconds >= 60:
        mins = duration_seconds // 60
        secs = duration_seconds % 60
        duration_str = f"{mins}m {secs}s"
    else:
        duration_str = f"{duration_seconds}s"
    
    return f"Timer set for {duration_str}. I'll remind you when it's done."


def parse_duration(duration_str: str) -> int:
    """Parses a duration string into seconds."""
    duration_str = duration_str.lower().strip()
    total_seconds = 0
    
    hours_match = re.search(r'(\d+)\s*(?:hour|hr|h)', duration_str)
    if hours_match:
        total_seconds += int(hours_match.group(1)) * 3600
    
    mins_match = re.search(r'(\d+)\s*(?:minute|min|m)', duration_str)
    if mins_match:
        total_seconds += int(mins_match.group(1)) * 60
    
    secs_match = re.search(r'(\d+)\s*(?:second|sec|s)', duration_str)
    if secs_match:
        total_seconds += int(secs_match.group(1))
    
    if total_seconds == 0:
        try:
            match = re.search(r'\d+', duration_str)
            if match:
                total_seconds = int(match.group()) * 60
        except (AttributeError, ValueError):
            pass
    
    return total_seconds


# =============================================================================
# TOOL COLLECTION
# =============================================================================

def get_info_tools() -> list[Tool]:
    """Get all information tools for manual registration."""
    tools = []
    for name, obj in globals().items():
        if hasattr(obj, "_tool_metadata"):
            tools.append(obj._tool_metadata)
    return tools

# general_utils.py
"""
General utility functions for Amadeus AI Assistant.
Includes datetime, weather, news, web browsing, and entertainment utilities.
"""

import os
import asyncio
import aiohttp
import webbrowser
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import random

load_dotenv()

# Import config for API keys and settings
import config

# API Keys (from config)
NEWS_API_KEY = config.NEWS_API_KEY
WEATHER_API_KEY = config.WEATHER_API_KEY


# ============== GREETING & TIME UTILITIES ==============

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


def get_datetime_info(query: str = "time") -> str:
    """
    Get current date, time, or day information.
    
    Args:
        query: What to retrieve - 'time', 'date', 'day', 'datetime', 'week', 'month', 'year'
    
    Returns:
        Formatted string with requested information
    """
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
        # Default: return both date and time
        return f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d, %Y')}"


# ============== WEATHER UTILITIES ==============

async def get_weather_async(location: str = "India") -> str:
    """
    Fetches current weather for a location using OpenWeatherMap API.
    
    Args:
        location: City name or location string
    
    Returns:
        Formatted weather string or error message
    """
    if not WEATHER_API_KEY:
        return "Weather service unavailable. Please configure WEATHER_API_KEY."
    
    base_url = config.WEATHER_API_BASE_URL
    params = {
        "q": location,
        "appid": WEATHER_API_KEY,
        "units": "metric"  # Use Celsius
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, params=params, timeout=aiohttp.ClientTimeout(total=config.WEATHER_API_TIMEOUT)) as response:
                if response.status == 404:
                    return f"Sorry, I couldn't find weather data for '{location}'."
                elif response.status != 200:
                    return f"Weather service error (status {response.status})."
                
                data = await response.json()
                
                # Extract weather info
                temp = data["main"]["temp"]
                feels_like = data["main"]["feels_like"]
                humidity = data["main"]["humidity"]
                description = data["weather"][0]["description"]
                city_name = data["name"]
                country = data["sys"].get("country", "")
                
                # Wind info
                wind_speed = data.get("wind", {}).get("speed", 0)
                wind_kmh = round(wind_speed * 3.6, 1)  # Convert m/s to km/h
                
                weather_str = (
                    f"Weather in {city_name}, {country}: {description.capitalize()}. "
                    f"Temperature is {temp:.1f}°C (feels like {feels_like:.1f}°C). "
                    f"Humidity is {humidity}% with winds at {wind_kmh} km/h."
                )
                
                return weather_str
                
    except asyncio.TimeoutError:
        return "Weather request timed out. Please try again."
    except aiohttp.ClientError as e:
        return f"Network error fetching weather: {e}"
    except KeyError as e:
        return f"Unexpected weather data format: {e}"
    except Exception as e:
        return f"Sorry, I couldn't fetch the weather: {e}"

# ============== NEWS UTILITIES ==============

async def get_news_async(
    category: Optional[str] = None,
    country: Optional[str] = None,
    count: Optional[int] = None
) -> str:
    """
    Fetches top news headlines using NewsAPI.
    
    Args:
        category: News category (general, business, technology, sports, etc.)
        country: Country code (in, us, gb, etc.)
        count: Number of headlines to return
    
    Returns:
        Formatted news headlines or error message
    """
    if not NEWS_API_KEY:
        return "News service unavailable. Please configure NEWS_API_KEY."
    
    # Use defaults from config if not provided
    category = category or config.NEWS_DEFAULT_CATEGORY
    country = country or config.NEWS_DEFAULT_COUNTRY
    count = count or config.NEWS_DEFAULT_COUNT
    
    base_url = "https://newsapi.org/v2/top-headlines"
    params = {
        "country": country,
        "category": category,
        "pageSize": count,
        "apiKey": NEWS_API_KEY
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
                
                # Format headlines
                headlines = []
                for i, article in enumerate(articles[:count], 1):
                    title = article.get("title", "No title")
                    source = article.get("source", {}).get("name", "Unknown")
                    headlines.append(f"{i}. {title} ({source})")
                
                result = f"Top {len(headlines)} {category} headlines:\n"
                result += "\n".join(headlines)
                
                return result
                
    except asyncio.TimeoutError:
        return "News request timed out. Please try again."
    except aiohttp.ClientError as e:
        return f"Network error fetching news: {e}"
    except Exception as e:
        return f"Sorry, I couldn't fetch the news: {e}"

# ============== WEB BROWSING UTILITIES ==============

def open_website(query: str = None, url: str = None, **kwargs) -> str:
    """
    Opens a website or performs a Google search.
    
    Args:
        query: URL to open or search term for Google search
    
    Returns:
        Status message
    """
    query = query or url or kwargs.get('link')
    if not query:
        return "Error: No URL or search query provided."
    
    query = query.strip()
    
    # Check if it looks like a URL
    url_indicators = ["http://", "https://", "www.", ".com", ".org", ".net", ".io", ".dev"]
    is_url = any(indicator in query.lower() for indicator in url_indicators)
    
    try:
        if is_url:
            # Clean up URL
            url = query
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            
            webbrowser.open(url)
            return f"Opening {url}"
        else:
            # Perform Google search
            search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            webbrowser.open(search_url)
            return f"Searching Google for: {query}"
            
    except Exception as e:
        return f"Failed to open browser: {e}"

# ============== WIKIPEDIA UTILITIES ==============

async def wikipedia_search_async(query: str, sentences: Optional[int] = None) -> str:
    """
    Searches Wikipedia and returns a summary.
    
    Args:
        query: Search term
        sentences: Number of sentences to return in summary
    
    Returns:
        Wikipedia summary or error message
    """
    # Use default from config if not provided
    if sentences is None:
        sentences = config.WIKIPEDIA_DEFAULT_SENTENCES
    
    # Using Wikipedia's REST API
    base_url = config.WIKIPEDIA_API_BASE_URL
    search_url = f"{base_url}/{urllib.parse.quote(query)}"
    
    headers = {
        "User-Agent": "AmadeusAI/1.0 (https://github.com/adityatawde9699/Amadeus-AI; adityatawde9699@gmail.com)"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=config.WIKIPEDIA_API_TIMEOUT)) as response:
                if response.status == 404:
                    # Try search API instead
                    return await _wikipedia_search_fallback(query, session)
                elif response.status != 200:
                    return f"Wikipedia error (status {response.status})."
                
                data = await response.json()
                
                title = data.get("title", query)
                extract = data.get("extract", "")
                
                if not extract:
                    return f"No Wikipedia article found for '{query}'."
                
                # Limit to requested sentences
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
        async with session.get(search_api, params=params, timeout=aiohttp.ClientTimeout(total=config.WIKIPEDIA_API_TIMEOUT)) as response:
            data = await response.json()
            results = data.get("query", {}).get("search", [])
            
            if not results:
                return f"No Wikipedia results found for '{query}'."
            
            # Get the first result's title and fetch its summary
            title = results[0].get("title", "")
            snippet = results[0].get("snippet", "").replace("<span class=\"searchmatch\">", "").replace("</span>", "")
            
            return f"Wikipedia result for '{query}':\n{title}: {snippet}..."
            
    except Exception as e:
        return f"Wikipedia search failed: {e}"


def wikipedia_search(query: str, sentences: int = 3) -> str:
    """Synchronous wrapper for wikipedia_search_async."""
    try:
        return asyncio.run(wikipedia_search_async(query, sentences))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(wikipedia_search_async(query, sentences))


# ============== ENTERTAINMENT UTILITIES ==============

# Collection of jokes for offline use
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
    ("What's the object-oriented way to become wealthy?", "Inheritance!"),
    ("Why did the functions stop calling each other?", "They had too many arguments!"),
    ("A SQL query walks into a bar, walks up to two tables and asks...", "Can I join you?"),
    ("Why do Python programmers have low self-esteem?", "They're constantly comparing themselves to others!"),
    ("What's a computer's least favorite food?", "Spam!"),
    ("Why did the programmer quit his job?", "Because he didn't get arrays."),
    ("How many programmers does it take to change a light bulb?", "None — that's a hardware problem."),
    ("Why did the computer show up at work late?", "It had a hard drive."),
    ("Why was the computer cold?", "It left its Windows open."),
    ("Why do programmers always mix up Halloween and Christmas?", "Because Oct 31 == Dec 25."),
    ("Why was the developer calm?", "He knew how to handle exceptions."),
    ("Why did the programmer get stuck in the shower?", "Because the bottle said: Lather, Rinse, Repeat."),
    ("Why did the programmer bring a ladder to work?", "To climb the corporate stack."),
    ("Why did the coder plant a light bulb?", "He wanted to grow a power plant."),
    ("What's a programmer's favorite place to hang out online?", "Stack Overflow."),
    ("Why did the computer need glasses?", "To improve its web sight."),
    ("Why did the smartphone need glasses?", "It lost its contacts."),
    ("Why did the programmer go to the beach?", "To surf the web."),
    ("Why did the coder cross the road?", "To get to the other IDE."),
    ("Why was the array sad?", "Because it had too many nulls."),
    ("What do you get when you cross a computer and a lifeguard?", "A screensaver."),
    ("Why did the developer adopt a cat?", "To help with purrformance tuning."),
    ("Why did the database administrator leave the party early?", "There were too many joins."),
    ("Why was the JavaScript developer always tired?", "Because he kept chasing callbacks."),
    ("Why did the computer break up with the internet?", "There was too much buffering in the relationship."),
    ("Why did the developer go broke buying cloud services?", "He couldn't stop scaling his bills."),
    ("Why did the function blush?", "Because it had a private variable."),
    ("Why did the router get promoted?", "It had excellent connections."),
    ("Why did the computer squeak?", "Because someone stepped on its mouse."),
    ("Why do programmers write code in pencil?", "So they can erase their mistakes."),
]

async def tell_joke_async() -> str:
    """
    Fetches a random joke from an API or returns a local joke.
    
    Returns:
        A joke string
    """
    # Try online joke API first
    try:
        async with aiohttp.ClientSession() as session:
            # Using JokeAPI
            url = "https://v2.jokeapi.dev/joke/Programming,Misc?safe-mode&type=twopart"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("type") == "twopart":
                        return f"{data['setup']}\n\n{data['delivery']}"
                    elif data.get("type") == "single":
                        return data.get("joke", "")
    except Exception:
        pass  # Fall back to local jokes
    
    # Return a local joke
    setup, punchline = random.choice(JOKES)
    return f"{setup}\n\n{punchline}"


def tell_joke() -> str:
    """Synchronous wrapper for tell_joke_async."""
    try:
        return asyncio.run(tell_joke_async())
    except RuntimeError:
        # Already in async context - just return local joke
        setup, punchline = random.choice(JOKES)
        return f"{setup}\n\n{punchline}"


# ============== CALCULATION UTILITIES ==============

def calculate(expression: str) -> str:
    """
    Safely evaluates a mathematical expression.
    
    Args:
        expression: Mathematical expression string
    
    Returns:
        Result or error message
    """
    # Allowed characters for safety
    allowed = set("0123456789+-*/.() ")
    
    # Clean the expression
    expr = expression.replace("x", "*").replace("÷", "/").replace("^", "**")
    
    # Check for disallowed characters
    if not all(c in allowed or c == "*" for c in expr):
        return "Invalid characters in expression."
    
    try:
        # Use eval with restricted builtins
        result = eval(expr, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero."
    except Exception as e:
        return f"Calculation error: {e}"


# ============== TIMER UTILITIES ==============

async def set_timer_async(duration_seconds: int, message: str = "Timer finished!") -> str:
    """
    Sets a timer that triggers after the specified duration.
    
    Args:
        duration_seconds: Duration in seconds
        message: Message to display when timer completes
    
    Returns:
        Confirmation message
    """
    if duration_seconds <= 0:
        return "Timer duration must be positive."
    
    if duration_seconds > 86400:  # 24 hours max
        return "Timer cannot exceed 24 hours."
    
    # Format duration for display
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
    """
    Parses a duration string into seconds.
    
    Args:
        duration_str: String like "5 minutes", "1 hour", "30 seconds"
    
    Returns:
        Duration in seconds
    """
    duration_str = duration_str.lower().strip()
    
    # Pattern matching
    import re
    
    total_seconds = 0
    
    # Hours
    hours_match = re.search(r'(\d+)\s*(?:hour|hr|h)', duration_str)
    if hours_match:
        total_seconds += int(hours_match.group(1)) * 3600
    
    # Minutes
    mins_match = re.search(r'(\d+)\s*(?:minute|min|m)', duration_str)
    if mins_match:
        total_seconds += int(mins_match.group(1)) * 60
    
    # Seconds
    secs_match = re.search(r'(\d+)\s*(?:second|sec|s)', duration_str)
    if secs_match:
        total_seconds += int(secs_match.group(1))
    
    # If no units found, try parsing as just a number (assume minutes)
    if total_seconds == 0:
        try:
            match = re.search(r'\d+', duration_str)
            if match:
                total_seconds = int(match.group()) * 60
        except (AttributeError, ValueError):
            pass
    
    return total_seconds


# ============== CONVERSION UTILITIES ==============

def convert_temperature(value: float, from_unit: str, to_unit: str) -> str:
    """Converts temperature between Celsius, Fahrenheit, and Kelvin."""
    from_unit = from_unit.lower()[0]  # c, f, or k
    to_unit = to_unit.lower()[0]
    
    # Convert to Celsius first
    if from_unit == 'f':
        celsius = (value - 32) * 5/9
    elif from_unit == 'k':
        celsius = value - 273.15
    else:
        celsius = value
    
    # Convert from Celsius to target
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


def convert_length(value: float, from_unit: str, to_unit: str) -> str:
    """Converts length between common units."""
    # Conversion factors to meters
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
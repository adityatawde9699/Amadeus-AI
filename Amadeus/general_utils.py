# general_utils.py (Streamlined)

import requests
import httpx
import pyjokes
import webbrowser
import wikipedia
import datetime
import os
import google.generativeai as genai
import dateparser
from typing import Optional
from dotenv import load_dotenv

from speech_utils import speak

# --- Configuration ---
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY")) # type: ignore
model = genai.GenerativeModel('gemini-2.5-flash') # type: ignore

# --- Core Utility Functions ---

async def get_news_async():
    """Async: Fetches top news headlines from Google News India using httpx."""
    try:
        news_api_key = os.getenv("news_api")
        if not news_api_key:
            return "News API key is not configured."
        url = f"https://newsapi.org/v2/top-headlines?sources=google-news-in&apiKey={news_api_key}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            articles = resp.json().get('articles', [])
        if not articles:
            return "No news headlines found."
        headlines = [article['title'] for article in articles[:5]]
        return "\n".join([f"{i+1}. {headline}" for i, headline in enumerate(headlines)])
    except httpx.RequestError as e:
        print(f"Error fetching news: {e}")
        return "Sorry, I couldn't connect to the news service."


def get_news():
    """Sync wrapper for older codepaths."""
    import asyncio
    return asyncio.run(get_news_async())
    """Fetches top news headlines from Google News India."""
    try:
        news_api_key = os.getenv("news_api")
        if not news_api_key:
            return "News API key is not configured."
        url = f"https://newsapi.org/v2/top-headlines?sources=google-news-in&apiKey={news_api_key}"
        response = requests.get(url)
        response.raise_for_status() # Raise an exception for bad status codes
        
        articles = response.json().get('articles', [])
        if not articles:
            return "No news headlines found."
        
        headlines = [article['title'] for article in articles[:5]]
        return "\n".join([f"{i+1}. {headline}" for i, headline in enumerate(headlines)])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching news: {e}")
        return "Sorry, I couldn't connect to the news service."

async def get_weather_async(location="India"):
    """Async: Gets current weather information for a specified location using httpx."""
    try:
        api_key = os.getenv("weather_api")
        if not api_key:
            return "Weather API key is not set."
        url = f"https://api.openweathermap.org/data/2.5/weather?q={location}&appid={api_key}&units=metric"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        main = data['main']
        wind = data['wind']
        weather_desc = data['weather'][0]['description']
        return (f"The weather in {location} is currently {weather_desc} with a temperature of "
                f"{main['temp']} degrees Celsius, but it feels like {main['feels_like']}. "
                f"Humidity is at {main['humidity']}% and wind speed is {wind['speed']} meters per second.")
    except Exception as e:
        print(f"Error fetching weather: {e}")
        return f"Sorry, I couldn't fetch the weather for {location}."


def get_weather(location="India"):
    import asyncio
    return asyncio.run(get_weather_async(location))
    """Gets current weather information for a specified location."""
    try:
        api_key = os.getenv("weather_api")
        if not api_key:
            return "Weather API key is not set."
        url = f"https://api.openweathermap.org/data/2.5/weather?q={location}&appid={api_key}&units=metric"
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        main = data['main']
        wind = data['wind']
        weather_desc = data['weather'][0]['description']
        
        # Return a simple, speakable string
        return (f"The weather in {location} is currently {weather_desc} with a temperature of "
                f"{main['temp']} degrees Celsius, but it feels like {main['feels_like']}. "
                f"Humidity is at {main['humidity']}% and wind speed is {wind['speed']} meters per second.")
                
    except Exception as e:
        print(f"Error fetching weather: {e}")
        return f"Sorry, I couldn't fetch the weather for {location}."

def tell_joke():
    """Tells a random joke."""
    try:
        return pyjokes.get_joke(language="en", category="neutral")
    except Exception as e:
        print(f"Error telling joke: {e}")
        return "I'm sorry, I seem to have forgotten all the jokes."

def open_website(query: str):
    """
    Opens a website. If it's not a clear URL, it performs a Google search.
    This is much more flexible than a hardcoded list.
    """
    query = query.lower().strip()
    if not query:
        return "What would you like to open or search for?"

    # Check if the query looks like a URL
    if "." in query and not " " in query:
        url = f"https://{query}" if not query.startswith("http") else query
    else:
        # If not a URL, perform a Google search
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    
    webbrowser.open(url)
    return f"Opening your request for {query} in the browser."

def wikipedia_search(query: str):
    """Searches Wikipedia and uses Gemini to provide a clean, concise summary."""
    try:
        speak(f"Searching Wikipedia for {query}...")
        results = wikipedia.summary(query, sentences=5, auto_suggest=True, redirect=True)
        
        prompt = f"Summarize the following text in two spoken sentences:\n\n{results}"
        response = model.generate_content(prompt)
        
        return response.text.strip().replace('\n', ' ')
    except wikipedia.exceptions.PageError:
        return f"Sorry, I couldn't find a Wikipedia page for '{query}'."
    except wikipedia.exceptions.DisambiguationError as e:
        return f"'{query}' could refer to multiple things, like {e.options[0]} or {e.options[1]}. Please be more specific."
    except Exception as e:
        print(f"Error during Wikipedia search: {e}")
        return "Sorry, an error occurred while searching Wikipedia."

def get_datetime_info(query: str):
    """Provides the current date, time, or day based on the user's query."""
    now = datetime.datetime.now()
    query = query.lower()

    if "time" in query:
        return f"The current time is {now.strftime('%I:%M %p')}."
    elif "date" in query:
        return f"Today's date is {now.strftime('%A, %B %d, %Y')}."
    elif "day" in query:
        return f"Today is {now.strftime('%A')}."
    else:
        # A sensible default if the query is ambiguous
        return f"It is {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d')}."
    
def get_greeting():
    """Get an appropriate greeting based on the time of day."""
    hour = datetime.datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning"
    elif 12 <= hour < 18:
        return "Good afternoon"
    else:
        return "Good evening"

def parse_time_reference(text: str) -> Optional[datetime.datetime]:
    """Parses natural language time references like "tomorrow at 3pm"."""
    try:
        # dateparser is powerful enough to handle this on its own.
        return dateparser.parse(text, settings={'PREFER_DATES_FROM': 'future', 'TIMEZONE': 'Asia/Kolkata'})
    except Exception as e:
        print(f"Error parsing time reference: {e}")
        return None
"""
Generate training data for the tool classifier model.

This script produces a JSON dataset of (text, tool_name) pairs covering
all tool categories registered in the Amadeus tool registry.

Target: 500+ labeled examples across all tool categories.
"""

import json
import random
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Templates — varied natural-language phrases per tool category
# ---------------------------------------------------------------------------
DATASET_TEMPLATES: dict[str, list[str]] = {
    # -----------------------------------------------------------------------
    # Info Tools
    # -----------------------------------------------------------------------
    "get_weather": [
        "What's the weather like in {city}?",
        "Is it raining in {city} right now?",
        "Give me the weather forecast for {city}",
        "Weather in {city}",
        "Will I need an umbrella in {city} tomorrow?",
        "How hot is it in {city}?",
        "Current temperature in {city}",
        "Is it going to rain tomorrow in {city}?",
        "Show me a 5-day forecast for {city}",
        "What is the humidity in {city}?",
        "How cold is it outside in {city}?",
        "Check the weather conditions in {city}",
        "Do I need a jacket in {city} today?",
        "Any chance of snow in {city}?",
        "What's the wind speed in {city}?",
    ],
    "get_news": [
        "What's the latest news?",
        "Show me headlines for {topic}",
        "Get me the news about {topic}",
        "Any updates on {topic}?",
        "Read me the latest news.",
        "Breaking news today",
        "Top stories right now",
        "What's happening in the world?",
        "News headlines for today",
        "Give me a news summary",
        "Fetch current events about {topic}",
        "What are people talking about in {topic}?",
        "Show me recent {topic} news",
        "I want to hear the latest about {topic}",
        "Summarize today's news",
    ],
    "get_datetime_info": [
        "What time is it?",
        "What's the date today?",
        "Tell me the current time",
        "Is it morning or afternoon?",
        "What day of the week is it?",
        "Current date and time",
        "Give me the time",
        "What's today's date?",
        "How many days until the weekend?",
        "Is it past noon yet?",
        "Tell me the day and time",
        "What is the time right now?",
        "What month are we in?",
        "Show me a calendar for today",
        "Is it a weekday today?",
    ],
    "tell_joke": [
        "Tell me a joke",
        "Make me laugh",
        "Do you know any jokes?",
        "Tell a funny story",
        "I need a laugh",
        "Give me a joke",
        "Say something funny",
        "Tell me something humorous",
        "I'm bored, tell me a joke",
        "Do you have a good one-liner?",
        "A pun please",
        "Hit me with a joke",
        "What's your best joke?",
        "Tell me a dad joke",
        "Can you be funny?",
    ],
    "calculate": [
        "Calculate {math}",
        "What is {math}?",
        "Solve {math}",
        "Math: {math}",
        "How much is {math}?",
        "Can you calculate {math}?",
        "Result of {math}",
        "Compute {math}",
        "What's the answer to {math}?",
        "Do the math: {math}",
        "Figure out {math}",
        "Work out {math}",
        "{math} equals what?",
        "Evaluate {math}",
        "Calculate for me: {math}",
    ],
    # -----------------------------------------------------------------------
    # Web / Search Tools
    # -----------------------------------------------------------------------
    "web_search": [
        "Search the web for {topic}",
        "Find me information about {topic}",
        "Can you look up {topic}?",
        "Google search {topic}",
        "Find results for {topic}",
        "Search online for {topic}",
        "Find {topic}",
        "Look up {topic} on the internet",
        "Do a web search for {topic}",
        "Search for the latest on {topic}",
        "I need search results for {topic}",
        "Find websites about {topic}",
        "Run a search for {topic}",
        "What does the internet say about {topic}?",
        "Quick search: {topic}",
    ],
    "wikipedia_search": [
        "Who is {person}?",
        "What is {concept}?",
        "Tell me about {topic}",
        "Look up {topic} on Wikipedia",
        "Give me a summary of {topic}",
        "Explain {concept} to me",
        "What does {concept} mean?",
        "Wikipedia article on {topic}",
        "Give me a brief history of {topic}",
        "Define {concept}",
        "How does {concept} work?",
        "What can you tell me about {person}?",
        "I want to learn about {concept}",
        "Describe {topic}",
        "Give me facts about {topic}",
    ],
    "fetch_webpage_content": [
        "Fetch the content from {url}",
        "Open this link and summarize: {url}",
        "What does this webpage say: {url}?",
        "Read {url} for me",
        "Get information from this URL: {url}",
        "Scrape the contents of {url}",
        "What's on this site: {url}?",
        "Parse the content at {url}",
        "Extract text from {url}",
        "Summarize the article at {url}",
        "Visit and read: {url}",
        "Load the page at {url}",
        "Can you read this page: {url}?",
        "Get the text from this website: {url}",
        "Check what's on {url}",
    ],
    # -----------------------------------------------------------------------
    # System / Monitor Tools
    # -----------------------------------------------------------------------
    "system_status": [
        "How is the system running?",
        "Check system status",
        "What's the CPU usage?",
        "How much memory is free?",
        "System health report",
        "Are all services up?",
        "Status of the server",
        "Give me a system overview",
        "How is RAM doing?",
        "Is the system under load?",
        "What are the current system stats?",
        "Show me resource usage",
        "Is anything consuming too much CPU?",
        "How busy is the machine?",
        "Run a quick diagnostics check",
    ],
    "get_cpu_usage": [
        "What's the CPU usage right now?",
        "CPU load percentage?",
        "How hard is the CPU working?",
        "Is the processor overloaded?",
        "Check CPU usage",
        "Show me CPU consumption",
        "Processor stats please",
        "What percentage of CPU is being used?",
        "Any CPU spikes happening?",
        "Tell me about CPU usage",
    ],
    "get_memory_info": [
        "How much RAM is available?",
        "What's the memory usage?",
        "Check RAM usage",
        "How much free memory do I have?",
        "RAM stats please",
        "Show memory consumption",
        "How full is the RAM?",
        "What percentage of memory is used?",
        "Tell me about memory usage",
        "Is memory running low?",
    ],
    "get_battery_info": [
        "How much battery is left?",
        "Battery level?",
        "Is my laptop charging?",
        "Check battery status",
        "What's the battery percentage?",
        "Battery health report",
        "How long until my battery dies?",
        "Is power plugged in?",
        "Show battery info",
        "Is battery low?",
    ],
    "get_disk_info": [
        "How much disk space is left?",
        "Check disk usage",
        "Is the hard drive full?",
        "Storage space remaining?",
        "Disk capacity report",
        "Show me drive usage",
        "How full is my disk?",
        "Is storage running low?",
        "Free space on disk?",
        "What percentage of my disk is used?",
    ],
    # -----------------------------------------------------------------------
    # Productivity Tools
    # -----------------------------------------------------------------------
    "set_reminder": [
        "Remind me to {task} at {time}",
        "Set a reminder for {task}",
        "Create a reminder: {task}",
        "I need a reminder for {time} to {task}",
        "Remind me about {task}",
        "Add a reminder to {task}",
        "Set alarm for {task}",
        "Alert me to {task} at {time}",
        "Don't let me forget to {task}",
        "Ping me when I need to {task}",
        "Schedule a reminder for {task}",
        "Remind me {time} to {task}",
        "Set a notification for {task}",
        "I want a reminder at {time} for {task}",
        "Kick me at {time} to {task}",
    ],
    "create_task": [
        "Add '{task}' to my todo list",
        "Create a new task: {task}",
        "Note down that I need to {task}",
        "Add a task: {task}",
        "Put '{task}' on my tasks",
        "Create task to {task}",
        "Remember to {task}",
        "Add to my task list: {task}",
        "I want to add a task for {task}",
        "New todo item: {task}",
        "Track a task for me: {task}",
        "Add to my checklist: {task}",
        "Task reminder to {task}",
        "Keep track of: {task}",
        "Add this to my list: {task}",
    ],
    "list_tasks": [
        "Show me my tasks",
        "What's on my todo list?",
        "List all my pending tasks",
        "What do I have to do?",
        "Show my to-do list",
        "What tasks are open?",
        "Display my task list",
        "Remind me what's on my list",
        "What are my current tasks?",
        "Check my tasks",
    ],
    "complete_task": [
        "Mark '{task}' as done",
        "Complete task: {task}",
        "I've finished {task}",
        "Check off {task}",
        "Task done: {task}",
        "I completed {task}",
        "Mark as complete: {task}",
        "Finish task {task}",
        "Close the task for {task}",
        "Done with {task}",
    ],
    "create_note": [
        "Write a note: {note}",
        "Take a note about {note}",
        "Note this down: {note}",
        "Add a note for {note}",
        "Remember this: {note}",
        "Save a note: {note}",
        "Jot this down: {note}",
        "Create a note saying {note}",
        "Keep a record of {note}",
        "Quick note: {note}",
    ],
    "start_pomodoro": [
        "Start a pomodoro timer",
        "Begin a focus session",
        "Start the pomodoro",
        "Activate pomodoro mode",
        "Let's do a focus block",
        "Help me focus with a pomodoro",
        "Start a 25-minute work session",
        "Begin focused work mode",
        "Pomodoro time!",
        "Start work timer",
    ],
    # -----------------------------------------------------------------------
    # System Actions
    # -----------------------------------------------------------------------
    "open_application": [
        "Open {app}",
        "Launch {app}",
        "Start {app}",
        "Run {app} please",
        "Can you open {app}?",
        "Boot up {app}",
        "Pull up {app}",
        "Bring up {app}",
        "Open the {app} application",
        "Start my {app}",
    ],
    "take_screenshot": [
        "Take a screenshot",
        "Capture my screen",
        "Screenshot now",
        "Take a screen capture",
        "Snap the screen",
        "Grab a screenshot",
        "Can you screenshot this?",
        "Screen capture please",
        "Save what's on my screen",
        "Capture the display",
    ],
    "schedule_future_task": [
        "Schedule a task in {minutes} minutes",
        "In {minutes} minutes, remind me to {task}",
        "Schedule for later: {task}",
        "Auto-run {task} in {minutes} minutes",
        "Set up a future task for {task}",
        "Proactively follow up on {task} in {minutes} minutes",
        "Delay task by {minutes} minutes: {task}",
        "Queue a background task for {task}",
        "Schedule a follow-up in {minutes} minutes",
        "Set a timed action: {task} in {minutes} min",
    ],
    # -----------------------------------------------------------------------
    # Conversational (no tool needed)
    # -----------------------------------------------------------------------
    "conversational": [
        "Hello there!",
        "How are you doing?",
        "Good morning Amadeus",
        "What's your name?",
        "I'm feeling great today",
        "Thanks for your help",
        "You are a great assistant",
        "Who created you?",
        "Let's chat for a bit",
        "I'm bored",
        "Hi",
        "Hey",
        "Okay, thanks",
        "You're awesome",
        "What can you do?",
        "Tell me about yourself",
        "I appreciate your help",
        "Bye, see you later",
        "Can we talk?",
        "What are you?",
        "How smart are you?",
        "Interesting!",
        "I agree with you",
        "Thank you so much",
        "That's helpful",
    ],
}

# ---------------------------------------------------------------------------
# Fillers — slot values for template placeholders
# ---------------------------------------------------------------------------
FILLERS: dict[str, list[str]] = {
    "city": [
        "New York",
        "London",
        "Tokyo",
        "Paris",
        "Mumbai",
        "Sydney",
        "Dubai",
        "Chicago",
        "the city",
        "here",
        "Berlin",
        "Singapore",
        "Los Angeles",
        "Toronto",
        "Mexico City",
    ],
    "topic": [
        "AI",
        "technology",
        "sports",
        "politics",
        "movies",
        "market",
        "science",
        "space",
        "climate change",
        "cryptocurrency",
        "fashion",
        "health",
        "music",
        "gaming",
        "finance",
    ],
    "person": [
        "Albert Einstein",
        "Elon Musk",
        "Marie Curie",
        "Steve Jobs",
        "the president",
        "Nikola Tesla",
        "Ada Lovelace",
        "Alan Turing",
        "Barack Obama",
        "Mahatma Gandhi",
    ],
    "concept": [
        "quantum physics",
        "machine learning",
        "black holes",
        "blockchain",
        "photosynthesis",
        "relativity",
        "DNA",
        "cloud computing",
        "neural networks",
        "evolution",
    ],
    "task": [
        "call mom",
        "buy groceries",
        "finish report",
        "pay bills",
        "walk the dog",
        "book tickets",
        "read a book",
        "reply to emails",
        "exercise",
        "prepare presentation",
    ],
    "time": [
        "3 PM",
        "tomorrow morning",
        "in an hour",
        "tonight",
        "next week",
        "at noon",
        "in 30 minutes",
        "before dinner",
        "at 9 AM",
        "this evening",
    ],
    "math": [
        "2+2",
        "15 * 6",
        "100 / 4",
        "sqrt(144)",
        "50% of 200",
        "5^3",
        "17 * 13",
        "1000 - 250",
        "45 + 89",
        "360 / 12",
    ],
    "note": [
        "meeting notes from Monday",
        "grocery list",
        "project ideas",
        "personal journal entry",
        "code snippet for later",
    ],
    "app": [
        "Chrome",
        "Notepad",
        "VS Code",
        "Spotify",
        "Calculator",
        "Teams",
        "Word",
        "Excel",
        "Discord",
        "Terminal",
    ],
    "minutes": ["5", "10", "15", "30", "60", "120"],
    "url": [
        "https://example.com",
        "https://news.ycombinator.com",
        "https://python.org",
        "https://wikipedia.org",
        "https://techcrunch.com",
    ],
}


def generate_variations(template: str, num_variations: int = 15) -> list[str]:
    """Fill template placeholders with random filler values."""
    variations = []
    placeholders = re.findall(r"\{(\w+)\}", template)

    if not placeholders:
        return [template] * max(1, num_variations // 3)

    for _ in range(num_variations):
        text = template
        for ph in placeholders:
            if ph in FILLERS:
                text = text.replace(f"{{{ph}}}", random.choice(FILLERS[ph]))
        variations.append(text)
    return list(set(variations))  # Deduplicate


def main() -> None:
    print("Generating training data for tool classifier...")
    dataset: list[dict[str, str]] = []

    for label, templates in DATASET_TEMPLATES.items():
        label_examples: list[str] = []
        for template in templates:
            label_examples.extend(generate_variations(template, num_variations=20))

        # De-duplicate within label
        label_examples = list(set(label_examples))

        augmented: list[dict[str, str]] = []
        for text in label_examples:
            augmented.append({"text": text, "label": label})
            # Case/punctuation augmentation
            augmented.append({"text": text.lower().rstrip("?"), "label": label})

        dataset.extend(augmented)
        print(f"  {label:35s} -> {len(augmented):4d} examples")

    print(f"\nTotal dataset size: {len(dataset)} examples across {len(DATASET_TEMPLATES)} classes")

    if len(dataset) < 500:
        print("WARNING: Dataset has fewer than 500 examples. Add more templates!")

    # Save to data directory
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)

    output_path = data_dir / "training_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"\nSaved dataset to {output_path}")


if __name__ == "__main__":
    main()

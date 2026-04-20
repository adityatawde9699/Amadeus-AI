import random
import re
from pathlib import Path

random.seed(42)  # For deterministic output

# All 42 classes found in retrain_classifier.py
CLASSES = {
    "open_program": ("open|launch|start|run|boot up", "vlc|chrome|notepad|visual studio code|spotify|firefox|word|excel|discord|whatsapp"),
    "terminate_program": ("close|kill|stop|terminate|end process for|force quit", "vlc|chrome|notepad|spotify|firefox|system process"),
    "get_datetime_info": ("what time is it|what is today's date|what day is it|tell me the time|current time please|date please", "today|now|right now|in my timezone|currently"),
    "get_weather": ("what is the weather|how is the weather|will it rain|temperature outside|weather forecast|is it hot", "today|in london|in paris|outside|tomorrow|this weekend"),
    "web_search": ("search for|look up|search the web for|find information about|google|search youtube for", "latest ai news|python tutorials|elon musk|programming tips|funny cat videos|quantum physics"),
    "wikipedia_search": ("who is|what is|tell me about|explain|search wikipedia for|summarize", "quantum computing|world war two|machine learning|alan turing|black holes|relativity"),
    "search_file": ("find a file named|where is the file|locate file|search for a pdf named|where did i save|search my computer for", "report.pdf|how to be alone|budget.xlsx|notes.txt|invoice|presentation"),
    "set_volume": ("set volume to|change volume to|mute the sound|unmute volume|increase volume|lower the volume", "50|70%|max|minimum|a bit|level 5"),
    "get_volume": ("what is the current volume|current volume level|how loud is it|check volume|show volume|is volume muted", "right now|currently|on the system|on my pc|please|"),
    "set_brightness": ("set brightness to|change brightness to|dim the screen to|increase brightness|lower screen brightness|screen too bright lower it", "70|50%|max|minimum|a little|level 10"),
    "take_screenshot": ("take a screenshot|screenshot|capture the screen|take a screen capture|screenshot the current screen|snap the screen", "now|please|for me|quickly|of this window|"),
    "list_open_apps": ("what's open right now|show open apps|what programs are running|list running applications|open windows|what apps do i have open", "currently|please|on my pc|in the background|right now|"),
    "get_news": ("latest news|today's top headlines|what happened in the world today|show me news about|current events|news from", "technology|usa|politics|india|tech|middle east"),
    "get_cpu_usage": ("how is my cpu|cpu usage|check cpu|show processor stats|is cpu overloaded|processor load", "right now|currently|please|on this machine|today|"),
    "get_memory_usage": ("how much ram am i using|memory usage|ram stats|how much memory is free|is ram full|check memory", "right now|currently|please|on the system|today|"),
    "get_disk_usage": ("disk space|how full is my hard drive|check disk usage|storage left|free space on disk|ssd space", "right now|currently|please|on c drive|today|"),
    "get_battery_info": ("battery status|battery percentage|how much battery is left|is it charging|laptop battery|power plugged in", "right now|currently|please|on my laptop|today|"),
    "system_status": ("system status|how is the system running|check system health|is the computer okay|system overview", "right now|currently|please|overall|today|"),
    "get_full_system_report": ("run a system report|give me a full system report|complete system diagnostics|full hardware report|detailed system info", "now|please|for this pc|quickly|today|"),
    "check_system_alerts": ("check system health|check system alerts|any system warnings|performance alerts|any critical alerts", "now|please|for this pc|quickly|today|"),
    "get_running_processes": ("what processes are running|show running processes|list background tasks|what is eating my ram|top processes", "now|please|for this pc|quickly|today|"),
    "get_network_info": ("network info|check network usage|how much data have i sent|network statistics|internet usage", "now|please|for this pc|quickly|today|"),
    "copy_file": ("copy file|duplicate file|clone document|make a copy of|copy report.pdf|duplicate budget.xlsx", "to desktop|to downloads|to documents|here|to the folder|"),
    "move_file": ("move file|transfer document|relocate file|shift file|move report.pdf|transfer budget.xlsx", "to desktop|to downloads|to documents|here|to the folder|"),
    "delete_file": ("delete the old backup|remove file|delete document|trash file|permanently delete|erase", "report.pdf|budget.xlsx|notes.txt|old backup|cache|"),
    "create_folder": ("create a new folder|make directory|setup folder|new directory|create folder", "projects|work|personal|downloads|temp|archive"),
    "add_reminder": ("add a reminder|set a reminder|remind me to|create a new reminder|put on my schedule", "for tomorrow|at 5pm|to call mom|to pay bills|soon|later"),
    "list_reminders": ("list my reminders|show reminders|what are my reminders|what am i forgetting|check reminders", "for tomorrow|for today|in the system|please|now|"),
    "create_note": ("create a note|take a note|save a note|write down|jot down|new note", "grocery list|project ideas|meeting notes|stuff to do|passwords|"),
    "list_notes": ("show my notes|list all notes|what are my notes|read notes|display notes", "for today|in the system|please|now|all of them|"),
    "schedule_future_task": ("schedule a task for later|do this in 10 minutes|remind yourself in an hour|delay execution of|wait before", "action|task|command|running|doing it|"),
    "calculate": ("calculate|what is|evaluate this expression|solve math|compute|quick math", "25 times 4|100 divided by 5|15 * 6|50% of 200|2+2|100-50"),
    "convert_temperature": ("convert 100 fahrenheit to celsius|temperature conversion|convert celsius to|fahrenheit equivalent|how hot is 30 celsius", "in fahrenheit|in celsius|please|now|"),
    "convert_length": ("how many kilometers in 5 miles|convert 10 miles to|convert inches to|distance conversion|how long is 5 feet", "in cm|in km|in meters|in inches|"),
    "tell_joke": ("tell me a joke|say something funny|make me laugh|do you know any jokes|crack a joke", "please|now|about programming|funny|dad joke|"),
    "get_greeting": ("greet me|good morning|hello amadeus|hi there|good evening|who are you", "assistant|amadeus|bot|friend|system|"),
    "send_email": ("send an email|send a mail|compose a message and email it|write an email to|draft and send an email|send email to", "adityatawde9699@gmail.com|john|boss|test@example.com|someone|manager"),
    "read_unread_emails": ("read my emails|check my inbox|what unread emails do I have|summarize my latest unread emails|show my message inbox", "please|now|for me|quickly|today|"),
    "create_excel_spreadsheet": ("create an excel spreadsheet|make an excel file|generate a spreadsheet|create a worksheet|new excel workbook", "with columns name and age|for budget|for tracking|data|"),
    "create_word_document": ("make a word document|save a word file|create a docx|draft a word document|write a report in word", "with contents hello world|for school|for work|quickly|"),
    "conversational": ("thank you|how are you doing amadeus|who created you|tell me about yourself|what is the meaning of life|you are very helpful", "thanks|okay|good job|hello|who are you|"),
    "set_timer": ("set a timer for|start a timer for|countdown|run a timer for|buzz me in", "5 minutes|10 minutes|1 hour|30 seconds|2 minutes|"),
}

# Generate exact 25 variations per class
output_pairs = []
for label, (verbs_str, nouns_str) in CLASSES.items():
    verbs = verbs_str.split('|')
    nouns = nouns_str.split('|')
    
    variations = set()
    attempts = 0
    while len(variations) < 25 and attempts < 200:
        v = random.choice(verbs).strip()
        n = random.choice(nouns).strip()
        if n:
            variations.add(f"{v} {n}".strip())
        else:
            variations.add(v)
        attempts += 1
    
    # Pad if we didn't hit 25 due to low combinatorial states
    while len(variations) < 25:
        # Just grab random ones and append extra noise or please
        base = random.choice(list(variations)) if variations else "action"
        noise = random.choice([" please", " now", " quickly", " today", " for me"])
        variations.add((base + noise).strip())
    
    # Take exactly 25
    final_25 = list(variations)[:25]
    for text in final_25:
        output_pairs.append((text, label))

print(f"Generated {len(output_pairs)} training pairs across {len(CLASSES)} classes.")
print(f"Expected: {25 * len(CLASSES)}")

# Now read retrain_classifier.py and replace TRAINING_DATA
retrain_file = Path("scripts/retrain_classifier.py")
content = retrain_file.read_text("utf-8")

# Format new list
new_array_str = "TRAINING_DATA = [\n"
class_marker = ""
for text, label in output_pairs:
    if label != class_marker:
        new_array_str += f"    # {label}\n"
        class_marker = label
    # Escape quotes
    clean_text = text.replace('"', '\\"')
    new_array_str += f'    ("{clean_text}", "{label}"),\n'
new_array_str += "]"

# Replace using regex
pattern = re.compile(r"TRAINING_DATA = \[.*?\]$", re.MULTILINE | re.DOTALL)
new_content = pattern.sub(new_array_str, content)

if new_content == content:
    print("ERROR: Regex replacement failed. Could not find TRAINING_DATA block.")
else:
    retrain_file.write_text(new_content, "utf-8")
    print(f"Successfully wrote {len(output_pairs)} training pairs to scripts/retrain_classifier.py.")

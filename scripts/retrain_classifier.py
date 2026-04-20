r"""
Retrain the TF-IDF + SVM tool classifier using the current sklearn version.
Run from the project root with the .venv active:
  .venv\Scripts\python scripts\retrain_classifier.py
"""

from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC


# ---------------------------------------------------------------------------
# TRAINING DATA  — (query, tool_name) pairs
# ---------------------------------------------------------------------------
TRAINING_DATA = [
    # open_program
    ("open vlc", "open_program"),
    ("launch chrome", "open_program"),
    ("open notepad", "open_program"),
    ("start visual studio code", "open_program"),
    ("open spotify", "open_program"),
    ("run firefox", "open_program"),
    ("launch word", "open_program"),
    ("open excel", "open_program"),
    ("start discord", "open_program"),
    ("open whatsapp", "open_program"),
    ("open telegram", "open_program"),
    ("launch the browser", "open_program"),
    ("open file explorer", "open_program"),
    ("start task manager", "open_program"),
    # terminate_program
    ("close vlc", "terminate_program"),
    ("kill chrome", "terminate_program"),
    ("stop notepad", "terminate_program"),
    ("terminate spotify", "terminate_program"),
    ("end task for firefox", "terminate_program"),
    ("kill process notepad", "terminate_program"),
    # get_datetime_info
    ("what time is it", "get_datetime_info"),
    ("what is today's date", "get_datetime_info"),
    ("what day is it", "get_datetime_info"),
    ("tell me the time", "get_datetime_info"),
    ("what is the current time", "get_datetime_info"),
    ("today's date please", "get_datetime_info"),
    # get_weather
    ("what is the weather", "get_weather"),
    ("how is the weather today", "get_weather"),
    ("will it rain", "get_weather"),
    ("temperature outside", "get_weather"),
    ("weather forecast", "get_weather"),
    ("is it hot today", "get_weather"),
    ("how is the weather today in london", "get_weather"),
    ("what is the weather in paris", "get_weather"),
    # web_search / wikipedia_search
    ("search for latest ai news", "web_search"),
    ("look up python tutorials", "web_search"),
    ("search the web for", "web_search"),
    ("find information about", "web_search"),
    ("google elon musk", "web_search"),
    ("what is quantum computing", "wikipedia_search"),
    ("tell me about world war two", "wikipedia_search"),
    ("explain machine learning", "wikipedia_search"),
    ("search youtube", "web_search"),
    ("search alexandria a city", "wikipedia_search"),
    ("search for a pdf named how to be alone", "search_file"),
    ("find a pdf named something", "search_file"),
    # get_news
    ("latest news", "get_news"),
    ("today's top headlines", "get_news"),
    ("what happened in the world today", "get_news"),
    ("show me news about technology", "get_news"),
    ("current events", "get_news"),
    # system_status / monitor tools
    ("how is my cpu", "get_cpu_usage"),
    ("cpu usage", "get_cpu_usage"),
    ("how much ram am i using", "get_memory_usage"),
    ("memory usage", "get_memory_usage"),
    ("disk space", "get_disk_usage"),
    ("how full is my hard drive", "get_disk_usage"),
    ("battery status", "get_battery_info"),
    ("battery percentage", "get_battery_info"),
    ("system status", "system_status"),
    ("run a system report", "get_full_system_report"),
    ("check system health", "check_system_alerts"),
    ("what processes are running", "get_running_processes"),
    ("network info", "get_network_info"),
    # file operations
    ("find the file report.pdf", "search_file"),
    ("where is my document", "search_file"),
    ("locate file", "search_file"),
    ("copy file to desktop", "copy_file"),
    ("move file to downloads", "move_file"),
    ("delete the old backup", "delete_file"),
    ("create a new folder", "create_folder"),
    ("make directory projects", "create_folder"),
    # productivity
    ("add a reminder for tomorrow", "add_reminder"),
    ("set a reminder at 5pm", "add_reminder"),
    ("remind me to call", "add_reminder"),
    ("list my reminders", "list_reminders"),
    ("show reminders", "list_reminders"),
    ("create a note", "create_note"),
    ("take a note", "create_note"),
    ("save a note", "create_note"),
    ("show my notes", "list_notes"),
    ("list all notes", "list_notes"),
    # schedule_future_task
    ("schedule a task for later", "schedule_future_task"),
    ("do this in 10 minutes", "schedule_future_task"),
    ("remind yourself in an hour", "schedule_future_task"),
    # calculate / convert
    ("calculate 25 times 4", "calculate"),
    ("what is 100 divided by 5", "calculate"),
    ("evaluate this expression", "calculate"),
    ("convert 100 fahrenheit to celsius", "convert_temperature"),
    ("how many kilometers in 5 miles", "convert_length"),
    # jokes / greetings
    ("tell me a joke", "tell_joke"),
    ("say something funny", "tell_joke"),
    ("greet me", "get_greeting"),
    ("good morning", "get_greeting"),
    ("hello amadeus", "get_greeting"),
    # email / communication
    ("send an email to john", "send_email"),
    ("read my emails", "read_unread_emails"),
    ("check my inbox", "read_unread_emails"),
    ("what unread emails do I have?", "read_unread_emails"),
    ("summarize my latest unread emails", "read_unread_emails"),
    ("show my message inbox", "read_unread_emails"),
    ("check for new mails", "read_unread_emails"),
    ("send a mail to someone", "send_email"),
    ("compose a message and email it", "send_email"),
    ("email adityatawde9699@gmail.com says hello", "send_email"),
    ("send email with subject hi to test@example.com", "send_email"),
    ("write an email to bob about the meeting", "send_email"),
    ("draft and send an email to manager", "send_email"),
    ("send email to adityatawde9699@gmail.com with subject hello and body how are you", "send_email"),
    ("could you please send a quick email to my boss with the subject urgent updates?", "send_email"),
    ("compose an email to test@example.com about the project status and tell them we are on track", "send_email"),
    ("send email subject report body see attached", "send_email"),
    ("compose email to alice for the task", "send_email"),
    ("write an email to support regarding my account issues", "send_email"),
    ("send a message to ast.movies9688@gmail.com", "send_email"),
    # unread emails
    ("check my inbox and read unread emails please", "read_unread_emails"),
    ("do I have any new mail in my gmail inbox?", "read_unread_emails"),
    ("summary of my recent unread messages", "read_unread_emails"),
    ("read out the last 5 emails from my inbox", "read_unread_emails"),
    ("check inbox", "read_unread_emails"),
    ("inbox status", "read_unread_emails"),
    # office tools
    ("create an excel spreadsheet", "create_excel_spreadsheet"),
    ("make a word document", "create_word_document"),
    ("generate a spreadsheet with columns name and age", "create_excel_spreadsheet"),
    ("save a word file with contents hello world", "create_word_document"),
    # conversational training (to reduce false positives for tools)
    ("thank you", "conversational"),
    ("okay thanks", "conversational"),
    ("how are you doing amadeus?", "conversational"),
    ("good evening assistant", "conversational"),
    ("who created you", "conversational"),
    ("tell me about yourself", "conversational"),
    ("can you chat with me", "conversational"),
    ("what is the meaning of life?", "conversational"),
    ("you are very helpful", "conversational"),
    # office tools
    # timer
    ("set a timer for 5 minutes", "set_timer"),
    ("start a 10 minute timer", "set_timer"),
    # conversational (NO tool needed)
    ("how are you", "conversational"),
    ("what can you do", "conversational"),
    ("who are you", "conversational"),
    ("tell me about yourself", "conversational"),
    ("thanks", "conversational"),
    ("okay", "conversational"),
    ("yes", "conversational"),
    ("no", "conversational"),
    ("that is great", "conversational"),
    ("help me", "conversational"),
    ("what is your name", "conversational"),
    ("are you an ai", "conversational"),
    ("what model are you", "conversational"),
    ("nice to meet you", "conversational"),
    ("hi there", "conversational"),
    ("good evening", "conversational"),
    ("what is my name", "conversational"),
]

# ---------------------------------------------------------------------------
# TRAIN
# ---------------------------------------------------------------------------
texts = [t for t, _ in TRAINING_DATA]
labels = [label for _, label in TRAINING_DATA]

vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=5000)
classifier = LinearSVC(C=1.0, max_iter=2000)

X = vectorizer.fit_transform(texts)
classifier.fit(X, labels)

# ---------------------------------------------------------------------------
# SAVE
# ---------------------------------------------------------------------------
model_dir = Path("Model")
model_dir.mkdir(exist_ok=True)
# Save artifacts to BOTH naming schemes to ensure full system synchronization
# Scheme 1: AmadeusService direct path
joblib.dump(vectorizer, model_dir / "tfidf_vectorizer.joblib")
joblib.dump(classifier, model_dir / "svm_classifier.joblib")

# Scheme 2: AgentOrchestrator / router path
joblib.dump(vectorizer, model_dir / "router_vectorizer.joblib")
joblib.dump(classifier, model_dir / "router_classifier.joblib")

print(f"[OK] Classifier retrained with {X.shape[0]} samples and {len(classifier.classes_)} classes.")
print(f"     Classes: {sorted(list(classifier.classes_))}")

# Quick sanity check
test_phrases = [
    "open vlc",
    "how are you",
    "what time is it",
    "cpu usage",
    "search for python tutorials",
    "read my unread emails",
    "send email to boss",
]
print("\n--- Sanity Check ---")
for phrase in test_phrases:
    x = vectorizer.transform([phrase])
    pred = classifier.predict(x)[0]
    print(f"  '{phrase}' -> {pred}")

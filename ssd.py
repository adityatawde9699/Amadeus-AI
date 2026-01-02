import pandas as pd
import os

# Comprehensive training data for Amadeus AI Tool Classification
# 10+ examples per tool for ML model training (300+ total examples)

data = [
    # =============================================================================
    # SYSTEM TOOLS
    # =============================================================================
    
    # --- get_datetime_info (10 examples) ---
    ("system", "get_datetime_info", "What time is it?"),
    ("system", "get_datetime_info", "What is today's date?"),
    ("system", "get_datetime_info", "Tell me the current time."),
    ("system", "get_datetime_info", "What day is it today?"),
    ("system", "get_datetime_info", "Can you check the time for me?"),
    ("system", "get_datetime_info", "What's the date today?"),
    ("system", "get_datetime_info", "Give me the current date and time."),
    ("system", "get_datetime_info", "Is it morning or afternoon right now?"),
    ("system", "get_datetime_info", "What is the current day of the week?"),
    ("system", "get_datetime_info", "Show me the time please."),
    
    # --- system_status (10 examples) ---
    ("system", "system_status", "How is my system running?"),
    ("system", "system_status", "Check system health."),
    ("system", "system_status", "Give me a system overview."),
    ("system", "system_status", "What's my computer's current status?"),
    ("system", "system_status", "Run a system check."),
    ("system", "system_status", "How's my PC performing?"),
    ("system", "system_status", "Show me the system summary."),
    ("system", "system_status", "Is everything running smoothly?"),
    ("system", "system_status", "Check my computer's health."),
    ("system", "system_status", "Give me a status report on my system."),
    
    # --- open_program (10 examples) ---
    ("system", "open_program", "Open Chrome."),
    ("system", "open_program", "Launch Spotify."),
    ("system", "open_program", "Start Visual Studio Code."),
    ("system", "open_program", "Can you open Notepad for me?"),
    ("system", "open_program", "Run Microsoft Word."),
    ("system", "open_program", "Open the calculator app."),
    ("system", "open_program", "Start Discord."),
    ("system", "open_program", "Launch Firefox browser."),
    ("system", "open_program", "Open Excel please."),
    ("system", "open_program", "Can you start the file explorer?"),
    
    # --- search_file (10 examples) ---
    ("system", "search_file", "Find a file named 'budget.xlsx'."),
    ("system", "search_file", "Where is 'notes.txt'?"),
    ("system", "search_file", "Search for the file called 'report.docx'."),
    ("system", "search_file", "Look for 'vacation_photo.jpg' on my computer."),
    ("system", "search_file", "Can you find my resume file?"),
    ("system", "search_file", "Where did I save 'project_plan.pdf'?"),
    ("system", "search_file", "Find all files named 'backup'."),
    ("system", "search_file", "Search my documents for 'invoice.pdf'."),
    ("system", "search_file", "Locate the file 'passwords.txt'."),
    ("system", "search_file", "Help me find 'presentation.pptx'."),
    
    # --- read_file (10 examples) ---
    ("system", "read_file", "Read the content of 'report.pdf'."),
    ("system", "read_file", "What's in the file 'notes.txt'?"),
    ("system", "read_file", "Open and read 'meeting_minutes.docx'."),
    ("system", "read_file", "Show me the contents of 'data.csv'."),
    ("system", "read_file", "Can you read my resume file?"),
    ("system", "read_file", "Read the document at 'C:/Users/Documents/letter.pdf'."),
    ("system", "read_file", "What does 'config.json' contain?"),
    ("system", "read_file", "Display the contents of 'readme.md'."),
    ("system", "read_file", "Read 'shopping_list.txt' for me."),
    ("system", "read_file", "What's written in the file 'todo.txt'?"),
    
    # --- open_website (10 examples) ---
    ("system", "open_website", "Open Google."),
    ("system", "open_website", "Go to YouTube."),
    ("system", "open_website", "Search for 'best restaurants near me'."),
    ("system", "open_website", "Open www.github.com."),
    ("system", "open_website", "Navigate to Twitter."),
    ("system", "open_website", "Can you open Amazon for me?"),
    ("system", "open_website", "Search Google for 'Python tutorials'."),
    ("system", "open_website", "Go to Netflix.com."),
    ("system", "open_website", "Open my email on Gmail."),
    ("system", "open_website", "Visit linkedin.com."),
    
    # --- copy_file (10 examples) ---
    ("system", "copy_file", "Copy 'report.docx' to my desktop."),
    ("system", "copy_file", "Make a copy of 'photo.jpg' in the backup folder."),
    ("system", "copy_file", "Copy the file 'data.xlsx' to the shared drive."),
    ("system", "copy_file", "Duplicate 'notes.txt' to another folder."),
    ("system", "copy_file", "Can you copy 'presentation.pptx' to my USB drive?"),
    ("system", "copy_file", "Copy my resume to the downloads folder."),
    ("system", "copy_file", "Make a backup of 'config.json'."),
    ("system", "copy_file", "Copy all files from 'source' to 'destination'."),
    ("system", "copy_file", "Duplicate the file 'music.mp3' to my phone folder."),
    ("system", "copy_file", "Copy 'budget.xlsx' to the finance folder."),
    
    # --- move_file (10 examples) ---
    ("system", "move_file", "Move 'old_document.docx' to the archive folder."),
    ("system", "move_file", "Transfer 'photo.jpg' to the pictures folder."),
    ("system", "move_file", "Move the downloaded file to my documents."),
    ("system", "move_file", "Relocate 'report.pdf' to the reports directory."),
    ("system", "move_file", "Move 'video.mp4' from downloads to videos."),
    ("system", "move_file", "Can you move this file to my desktop?"),
    ("system", "move_file", "Transfer 'backup.zip' to the backup drive."),
    ("system", "move_file", "Move 'notes.txt' to the work folder."),
    ("system", "move_file", "Relocate the file 'data.csv' to the data directory."),
    ("system", "move_file", "Move 'screenshot.png' to the images folder."),
    
    # --- delete_file (10 examples) ---
    ("system", "delete_file", "Delete the file 'temp.txt'."),
    ("system", "delete_file", "Remove 'old_backup.zip' from my computer."),
    ("system", "delete_file", "Delete 'junk.docx' please."),
    ("system", "delete_file", "Can you delete the file 'test.py'?"),
    ("system", "delete_file", "Remove the file named 'unused_data.xlsx'."),
    ("system", "delete_file", "Delete 'draft_email.txt'."),
    ("system", "delete_file", "Get rid of 'old_photo.jpg'."),
    ("system", "delete_file", "Remove 'temporary_file.tmp' from the system."),
    ("system", "delete_file", "Delete the cached file 'cache.dat'."),
    ("system", "delete_file", "Please delete 'outdated_report.pdf'."),
    
    # --- create_folder (10 examples) ---
    ("system", "create_folder", "Create a new folder named 'Project X'."),
    ("system", "create_folder", "Make a folder called 'Vacation Photos'."),
    ("system", "create_folder", "Create a directory named 'Work Documents'."),
    ("system", "create_folder", "Set up a new folder for my 'Backups'."),
    ("system", "create_folder", "Create a folder named '2024 Reports'."),
    ("system", "create_folder", "Make a new directory called 'Music Collection'."),
    ("system", "create_folder", "Create the folder 'Client Files'."),
    ("system", "create_folder", "Set up a folder named 'Personal'."),
    ("system", "create_folder", "Create a new folder for 'Downloads Organized'."),
    ("system", "create_folder", "Make a folder called 'School Projects'."),
    
    # --- list_directory (10 examples) ---
    ("system", "list_directory", "List the files in my documents folder."),
    ("system", "list_directory", "Show me what's in the downloads folder."),
    ("system", "list_directory", "What files are in the current directory?"),
    ("system", "list_directory", "List all items in my desktop."),
    ("system", "list_directory", "Show the contents of the 'Projects' folder."),
    ("system", "list_directory", "What's inside the pictures directory?"),
    ("system", "list_directory", "List all files in C:/Users."),
    ("system", "list_directory", "Show me the folder contents of 'Work'."),
    ("system", "list_directory", "Display what's in this directory."),
    ("system", "list_directory", "List the directory 'Music'."),
    
    # --- terminate_program (10 examples) ---
    ("system", "terminate_program", "Close Chrome."),
    ("system", "terminate_program", "Kill the python process."),
    ("system", "terminate_program", "End the Spotify application."),
    ("system", "terminate_program", "Stop the Notepad program."),
    ("system", "terminate_program", "Terminate the Excel process."),
    ("system", "terminate_program", "Close Microsoft Word."),
    ("system", "terminate_program", "Kill the running Firefox process."),
    ("system", "terminate_program", "Shut down the Discord app."),
    ("system", "terminate_program", "Close the calculator."),
    ("system", "terminate_program", "Force quit the VS Code application."),
    
    # --- get_cpu_usage (10 examples) ---
    ("system", "get_cpu_usage", "What is the CPU usage?"),
    ("system", "get_cpu_usage", "How busy is my processor?"),
    ("system", "get_cpu_usage", "Check CPU utilization."),
    ("system", "get_cpu_usage", "What percentage is my CPU running at?"),
    ("system", "get_cpu_usage", "Show me the current CPU load."),
    ("system", "get_cpu_usage", "Is my processor overloaded?"),
    ("system", "get_cpu_usage", "Get the CPU percentage."),
    ("system", "get_cpu_usage", "How hard is my CPU working?"),
    ("system", "get_cpu_usage", "What's the current processor usage?"),
    ("system", "get_cpu_usage", "Display CPU usage statistics."),
    
    # --- get_memory_usage (10 examples) ---
    ("system", "get_memory_usage", "How much RAM is being used?"),
    ("system", "get_memory_usage", "Check memory usage."),
    ("system", "get_memory_usage", "What's my current RAM utilization?"),
    ("system", "get_memory_usage", "Show me memory stats."),
    ("system", "get_memory_usage", "Is my memory running low?"),
    ("system", "get_memory_usage", "How much memory is available?"),
    ("system", "get_memory_usage", "Get the RAM usage percentage."),
    ("system", "get_memory_usage", "What percentage of RAM is in use?"),
    ("system", "get_memory_usage", "Check how much memory I have free."),
    ("system", "get_memory_usage", "Display memory consumption."),
    
    # --- get_disk_usage (10 examples) ---
    ("system", "get_disk_usage", "How much disk space do I have?"),
    ("system", "get_disk_usage", "Check my hard drive usage."),
    ("system", "get_disk_usage", "What's the storage status?"),
    ("system", "get_disk_usage", "How full is my C drive?"),
    ("system", "get_disk_usage", "Show me the disk space."),
    ("system", "get_disk_usage", "Is my hard drive running out of space?"),
    ("system", "get_disk_usage", "Get disk usage for the D drive."),
    ("system", "get_disk_usage", "What percentage of storage is used?"),
    ("system", "get_disk_usage", "Check available disk space."),
    ("system", "get_disk_usage", "How much free space is on my drive?"),
    
    # --- get_battery_info (10 examples) ---
    ("system", "get_battery_info", "Check battery percentage."),
    ("system", "get_battery_info", "Is my laptop plugged in?"),
    ("system", "get_battery_info", "How much battery do I have left?"),
    ("system", "get_battery_info", "What's my current battery level?"),
    ("system", "get_battery_info", "Is my laptop charging?"),
    ("system", "get_battery_info", "Show me the battery status."),
    ("system", "get_battery_info", "How long until my battery runs out?"),
    ("system", "get_battery_info", "Check if the charger is connected."),
    ("system", "get_battery_info", "What percent is my battery at?"),
    ("system", "get_battery_info", "Get battery information."),
    
    # --- get_network_info (10 examples) ---
    ("system", "get_network_info", "Check my network status."),
    ("system", "get_network_info", "How much data have I used?"),
    ("system", "get_network_info", "Show me network statistics."),
    ("system", "get_network_info", "What's my network usage?"),
    ("system", "get_network_info", "Check my internet connection stats."),
    ("system", "get_network_info", "How much have I downloaded today?"),
    ("system", "get_network_info", "Get network interface information."),
    ("system", "get_network_info", "Show bytes sent and received."),
    ("system", "get_network_info", "What's my upload and download stats?"),
    ("system", "get_network_info", "Check connection statistics."),
    
    # --- get_system_uptime (10 examples) ---
    ("system", "get_system_uptime", "How long has my computer been on?"),
    ("system", "get_system_uptime", "What's the system uptime?"),
    ("system", "get_system_uptime", "When did I last restart?"),
    ("system", "get_system_uptime", "How long since the last reboot?"),
    ("system", "get_system_uptime", "Check system uptime."),
    ("system", "get_system_uptime", "When was my computer started?"),
    ("system", "get_system_uptime", "Show me how long the system has been running."),
    ("system", "get_system_uptime", "What's the boot time?"),
    ("system", "get_system_uptime", "How many hours has my PC been on?"),
    ("system", "get_system_uptime", "Get the system uptime information."),
    
    # --- get_running_processes (10 examples) ---
    ("system", "get_running_processes", "Show me running processes."),
    ("system", "get_running_processes", "What programs are currently running?"),
    ("system", "get_running_processes", "List top processes by memory."),
    ("system", "get_running_processes", "Which applications are using the most memory?"),
    ("system", "get_running_processes", "Show me the active processes."),
    ("system", "get_running_processes", "What's consuming my RAM?"),
    ("system", "get_running_processes", "List all running applications."),
    ("system", "get_running_processes", "Show top 10 processes."),
    ("system", "get_running_processes", "Which programs are active right now?"),
    ("system", "get_running_processes", "Get the list of running tasks."),
    
    # --- get_gpu_stats (10 examples) ---
    ("system", "get_gpu_stats", "Check my GPU usage."),
    ("system", "get_gpu_stats", "What's my graphics card status?"),
    ("system", "get_gpu_stats", "Show me GPU statistics."),
    ("system", "get_gpu_stats", "How hot is my GPU?"),
    ("system", "get_gpu_stats", "Check video card temperature."),
    ("system", "get_gpu_stats", "What's the GPU load?"),
    ("system", "get_gpu_stats", "Is my graphics card being used?"),
    ("system", "get_gpu_stats", "Get GPU memory usage."),
    ("system", "get_gpu_stats", "Show graphics card info."),
    ("system", "get_gpu_stats", "What percentage is my GPU running at?"),
    
    # --- get_temperature_sensors (10 examples) ---
    ("system", "get_temperature_sensors", "What's my CPU temperature?"),
    ("system", "get_temperature_sensors", "Is my computer overheating?"),
    ("system", "get_temperature_sensors", "Check system temperatures."),
    ("system", "get_temperature_sensors", "Show me temperature readings."),
    ("system", "get_temperature_sensors", "How hot are my components?"),
    ("system", "get_temperature_sensors", "Get the thermal sensor data."),
    ("system", "get_temperature_sensors", "What's the current CPU temp?"),
    ("system", "get_temperature_sensors", "Check if my laptop is running hot."),
    ("system", "get_temperature_sensors", "Display temperature sensor info."),
    ("system", "get_temperature_sensors", "Are my temperatures normal?"),
    
    # --- check_system_alerts (10 examples) ---
    ("system", "check_system_alerts", "Are there any system warnings?"),
    ("system", "check_system_alerts", "Check for system alerts."),
    ("system", "check_system_alerts", "Is anything wrong with my computer?"),
    ("system", "check_system_alerts", "Show me any system issues."),
    ("system", "check_system_alerts", "Are there any critical alerts?"),
    ("system", "check_system_alerts", "Check for any problems on my PC."),
    ("system", "check_system_alerts", "What alerts do I have?"),
    ("system", "check_system_alerts", "Is my system healthy?"),
    ("system", "check_system_alerts", "Check for any warnings or errors."),
    ("system", "check_system_alerts", "Are there any issues I should know about?"),
    
    # =============================================================================
    # INFORMATION TOOLS
    # =============================================================================
    
    # --- get_weather (10 examples) ---
    ("information", "get_weather", "What's the weather like?"),
    ("information", "get_weather", "Is it raining in Mumbai?"),
    ("information", "get_weather", "What's the temperature outside?"),
    ("information", "get_weather", "Will it rain today?"),
    ("information", "get_weather", "Check the weather in Delhi."),
    ("information", "get_weather", "How's the weather in New York?"),
    ("information", "get_weather", "Is it sunny today?"),
    ("information", "get_weather", "What's the forecast for Bangalore?"),
    ("information", "get_weather", "Tell me the weather conditions."),
    ("information", "get_weather", "Is it cold outside right now?"),
    
    # --- get_news (10 examples) ---
    ("information", "get_news", "Show me the top headlines."),
    ("information", "get_news", "What's happening in tech news?"),
    ("information", "get_news", "Give me the latest news."),
    ("information", "get_news", "What's in the news today?"),
    ("information", "get_news", "Show me current events."),
    ("information", "get_news", "What are the breaking news stories?"),
    ("information", "get_news", "Read me the top news."),
    ("information", "get_news", "Any important news updates?"),
    ("information", "get_news", "What's trending in the news?"),
    ("information", "get_news", "Give me a news briefing."),
    
    # --- wikipedia_search (10 examples) ---
    ("information", "wikipedia_search", "Who is Elon Musk?"),
    ("information", "wikipedia_search", "Tell me about Quantum Physics."),
    ("information", "wikipedia_search", "What is the Eiffel Tower?"),
    ("information", "wikipedia_search", "Who was Albert Einstein?"),
    ("information", "wikipedia_search", "Search Wikipedia for 'Machine Learning'."),
    ("information", "wikipedia_search", "Tell me about World War II."),
    ("information", "wikipedia_search", "What is photosynthesis?"),
    ("information", "wikipedia_search", "Who is the Prime Minister of India?"),
    ("information", "wikipedia_search", "Explain the theory of relativity."),
    ("information", "wikipedia_search", "What is blockchain technology?"),
    
    # --- calculate (10 examples) ---
    ("information", "calculate", "What is 25 * 4?"),
    ("information", "calculate", "Calculate 100 divided by 5."),
    ("information", "calculate", "What's 15 plus 27?"),
    ("information", "calculate", "Compute 1000 minus 350."),
    ("information", "calculate", "What is the square root of 144?"),
    ("information", "calculate", "Calculate 2 to the power of 10."),
    ("information", "calculate", "What's 18 percent of 500?"),
    ("information", "calculate", "Solve 45 * 12."),
    ("information", "calculate", "What is 999 divided by 3?"),
    ("information", "calculate", "Calculate (50 + 30) * 2."),
    
    # --- convert_temperature (10 examples) ---
    ("information", "convert_temperature", "Convert 32 Fahrenheit to Celsius."),
    ("information", "convert_temperature", "What is 100 Celsius in Fahrenheit?"),
    ("information", "convert_temperature", "Convert 0 degrees Celsius to Kelvin."),
    ("information", "convert_temperature", "How many Fahrenheit is 25 Celsius?"),
    ("information", "convert_temperature", "Convert 212 F to C."),
    ("information", "convert_temperature", "What is 300 Kelvin in Celsius?"),
    ("information", "convert_temperature", "Convert 98.6 Fahrenheit to Celsius."),
    ("information", "convert_temperature", "How much is 37 Celsius in Fahrenheit?"),
    ("information", "convert_temperature", "Convert -40 Celsius to Fahrenheit."),
    ("information", "convert_temperature", "What is 273 Kelvin in Celsius?"),
    
    # --- convert_length (10 examples) ---
    ("information", "convert_length", "Convert 10 kilometers to miles."),
    ("information", "convert_length", "How many centimeters is 5 inches?"),
    ("information", "convert_length", "What is 100 meters in feet?"),
    ("information", "convert_length", "Convert 1 mile to kilometers."),
    ("information", "convert_length", "How many millimeters is 10 centimeters?"),
    ("information", "convert_length", "Convert 6 feet to meters."),
    ("information", "convert_length", "What is 1000 millimeters in meters?"),
    ("information", "convert_length", "How many inches are in a foot?"),
    ("information", "convert_length", "Convert 50 yards to meters."),
    ("information", "convert_length", "What is 2.5 kilometers in meters?"),
    
    # =============================================================================
    # COMMUNICATION TOOLS
    # =============================================================================
    
    # --- tell_joke (10 examples) ---
    ("communication", "tell_joke", "Tell me a joke."),
    ("communication", "tell_joke", "Make me laugh."),
    ("communication", "tell_joke", "Say something funny."),
    ("communication", "tell_joke", "Got any jokes?"),
    ("communication", "tell_joke", "I need a good laugh."),
    ("communication", "tell_joke", "Tell me something hilarious."),
    ("communication", "tell_joke", "Can you crack a joke?"),
    ("communication", "tell_joke", "Give me a funny joke."),
    ("communication", "tell_joke", "Do you know any jokes?"),
    ("communication", "tell_joke", "Share a joke with me."),
    
    # --- conversational (10 examples) ---
    ("communication", "conversational", "Hello Amadeus."),
    ("communication", "conversational", "How are you doing today?"),
    ("communication", "conversational", "Good morning."),
    ("communication", "conversational", "Who made you?"),
    ("communication", "conversational", "What can you do?"),
    ("communication", "conversational", "Thanks for your help."),
    ("communication", "conversational", "You're really helpful."),
    ("communication", "conversational", "Good night, Amadeus."),
    ("communication", "conversational", "How was your day?"),
    ("communication", "conversational", "What's your name?"),
    
    # =============================================================================
    # PRODUCTIVITY - TASK TOOLS
    # =============================================================================
    
    # --- add_task (10 examples) ---
    ("productivity", "add_task", "Add a task to buy groceries."),
    ("productivity", "add_task", "Remind me to call Mom."),
    ("productivity", "add_task", "Create a task: finish the report."),
    ("productivity", "add_task", "Add 'send email to boss' to my tasks."),
    ("productivity", "add_task", "I need to remember to pay bills."),
    ("productivity", "add_task", "Add a todo: clean the house."),
    ("productivity", "add_task", "Create task for gym session."),
    ("productivity", "add_task", "Add 'book flight tickets' to my list."),
    ("productivity", "add_task", "Remember to pick up dry cleaning."),
    ("productivity", "add_task", "Add task: schedule dentist appointment."),
    
    # --- list_tasks (10 examples) ---
    ("productivity", "list_tasks", "Show my todo list."),
    ("productivity", "list_tasks", "What do I have to do today?"),
    ("productivity", "list_tasks", "List all my tasks."),
    ("productivity", "list_tasks", "Show me pending tasks."),
    ("productivity", "list_tasks", "What's on my task list?"),
    ("productivity", "list_tasks", "Display my todos."),
    ("productivity", "list_tasks", "Show completed tasks."),
    ("productivity", "list_tasks", "What tasks are remaining?"),
    ("productivity", "list_tasks", "List everything I need to do."),
    ("productivity", "list_tasks", "Show me my task queue."),
    
    # --- complete_task (10 examples) ---
    ("productivity", "complete_task", "Mark 'buy groceries' as done."),
    ("productivity", "complete_task", "I finished the gym task."),
    ("productivity", "complete_task", "Complete the task about calling Mom."),
    ("productivity", "complete_task", "Mark task 1 as complete."),
    ("productivity", "complete_task", "I'm done with the report task."),
    ("productivity", "complete_task", "Check off 'send email'."),
    ("productivity", "complete_task", "Mark the first task as finished."),
    ("productivity", "complete_task", "Complete my laundry task."),
    ("productivity", "complete_task", "I completed the meeting preparation."),
    ("productivity", "complete_task", "Mark 'pay bills' as done."),
    
    # --- delete_task (10 examples) ---
    ("productivity", "delete_task", "Remove the task about the gym."),
    ("productivity", "delete_task", "Delete task number 3."),
    ("productivity", "delete_task", "Remove 'buy groceries' from my tasks."),
    ("productivity", "delete_task", "Delete the completed tasks."),
    ("productivity", "delete_task", "Remove the call Mom task."),
    ("productivity", "delete_task", "Delete my first task."),
    ("productivity", "delete_task", "Remove the task about the report."),
    ("productivity", "delete_task", "Delete task 5."),
    ("productivity", "delete_task", "Remove the email task from the list."),
    ("productivity", "delete_task", "Delete the dentist appointment task."),
    
    # --- get_task_summary (10 examples) ---
    ("productivity", "get_task_summary", "Give me a summary of my tasks."),
    ("productivity", "get_task_summary", "How many tasks do I have?"),
    ("productivity", "get_task_summary", "What's my task overview?"),
    ("productivity", "get_task_summary", "Summarize my todo list."),
    ("productivity", "get_task_summary", "How many tasks are pending?"),
    ("productivity", "get_task_summary", "Show task statistics."),
    ("productivity", "get_task_summary", "What's my productivity summary?"),
    ("productivity", "get_task_summary", "How many tasks did I complete?"),
    ("productivity", "get_task_summary", "Give me a task count."),
    ("productivity", "get_task_summary", "Overview of my todos."),
    
    # =============================================================================
    # PRODUCTIVITY - NOTE TOOLS
    # =============================================================================
    
    # --- create_note (10 examples) ---
    ("productivity", "create_note", "Take a note: Meeting ideas."),
    ("productivity", "create_note", "Write down this thought."),
    ("productivity", "create_note", "Create a note about project requirements."),
    ("productivity", "create_note", "Make a note: remember to buy milk."),
    ("productivity", "create_note", "Jot down: password for the new account."),
    ("productivity", "create_note", "Create a note titled 'Shopping List'."),
    ("productivity", "create_note", "Save this as a note."),
    ("productivity", "create_note", "Write a note about the meeting."),
    ("productivity", "create_note", "Make a quick note: office address."),
    ("productivity", "create_note", "Create a new note for brainstorming."),
    
    # --- list_notes (10 examples) ---
    ("productivity", "list_notes", "Show me all my notes."),
    ("productivity", "list_notes", "List my saved notes."),
    ("productivity", "list_notes", "What notes do I have?"),
    ("productivity", "list_notes", "Display all notes."),
    ("productivity", "list_notes", "Show notes with tag 'work'."),
    ("productivity", "list_notes", "List recent notes."),
    ("productivity", "list_notes", "What have I written down?"),
    ("productivity", "list_notes", "Show my note collection."),
    ("productivity", "list_notes", "List notes from today."),
    ("productivity", "list_notes", "Display my saved thoughts."),
    
    # --- get_note (10 examples) ---
    ("productivity", "get_note", "Read the note about 'Project Alpha'."),
    ("productivity", "get_note", "Show me note number 1."),
    ("productivity", "get_note", "Open my shopping list note."),
    ("productivity", "get_note", "Get the meeting notes."),
    ("productivity", "get_note", "Read note ID 5."),
    ("productivity", "get_note", "Show the brainstorming note."),
    ("productivity", "get_note", "Display the note titled 'Ideas'."),
    ("productivity", "get_note", "Read my first note."),
    ("productivity", "get_note", "Open the note about passwords."),
    ("productivity", "get_note", "Get the content of note 3."),
    
    # --- update_note (10 examples) ---
    ("productivity", "update_note", "Update note 1 with new content."),
    ("productivity", "update_note", "Edit my shopping list note."),
    ("productivity", "update_note", "Modify the meeting notes."),
    ("productivity", "update_note", "Add more content to note 3."),
    ("productivity", "update_note", "Change the title of note 2."),
    ("productivity", "update_note", "Update the brainstorming note."),
    ("productivity", "update_note", "Edit note ID 5."),
    ("productivity", "update_note", "Modify my project note."),
    ("productivity", "update_note", "Add tags to note 1."),
    ("productivity", "update_note", "Update the content of my ideas note."),
    
    # --- delete_note (10 examples) ---
    ("productivity", "delete_note", "Delete note number 1."),
    ("productivity", "delete_note", "Remove my shopping list note."),
    ("productivity", "delete_note", "Delete the meeting notes."),
    ("productivity", "delete_note", "Remove note ID 5."),
    ("productivity", "delete_note", "Delete the old brainstorming note."),
    ("productivity", "delete_note", "Remove note 3 from my list."),
    ("productivity", "delete_note", "Delete the note about passwords."),
    ("productivity", "delete_note", "Remove my first note."),
    ("productivity", "delete_note", "Delete the project ideas note."),
    ("productivity", "delete_note", "Remove note number 2."),
    
    # --- get_notes_summary (10 examples) ---
    ("productivity", "get_notes_summary", "Give me a summary of my notes."),
    ("productivity", "get_notes_summary", "How many notes do I have?"),
    ("productivity", "get_notes_summary", "What's my notes overview?"),
    ("productivity", "get_notes_summary", "Summarize my saved notes."),
    ("productivity", "get_notes_summary", "Show notes statistics."),
    ("productivity", "get_notes_summary", "Count my notes."),
    ("productivity", "get_notes_summary", "Overview of my notes."),
    ("productivity", "get_notes_summary", "How many notes have I created?"),
    ("productivity", "get_notes_summary", "Give me a notes count."),
    ("productivity", "get_notes_summary", "Notes summary please."),
    
    # =============================================================================
    # PRODUCTIVITY - REMINDER TOOLS
    # =============================================================================
    
    # --- add_reminder (10 examples) ---
    ("productivity", "add_reminder", "Remind me to call John at 3pm."),
    ("productivity", "add_reminder", "Set a reminder for tomorrow at 9am."),
    ("productivity", "add_reminder", "Remind me to take medicine in 2 hours."),
    ("productivity", "add_reminder", "Create a reminder for the meeting at 5pm."),
    ("productivity", "add_reminder", "Remind me to check email at noon."),
    ("productivity", "add_reminder", "Set a reminder to pick up kids at 4pm."),
    ("productivity", "add_reminder", "Remind me about the dentist appointment tomorrow."),
    ("productivity", "add_reminder", "Create a reminder to water plants every morning."),
    ("productivity", "add_reminder", "Remind me to submit the report by Friday."),
    ("productivity", "add_reminder", "Set a reminder for my workout at 7am."),
    
    # --- list_reminders (10 examples) ---
    ("productivity", "list_reminders", "Show my reminders."),
    ("productivity", "list_reminders", "What reminders do I have?"),
    ("productivity", "list_reminders", "List all active reminders."),
    ("productivity", "list_reminders", "Display my pending reminders."),
    ("productivity", "list_reminders", "What am I supposed to remember?"),
    ("productivity", "list_reminders", "Show upcoming reminders."),
    ("productivity", "list_reminders", "List my scheduled reminders."),
    ("productivity", "list_reminders", "What reminders are set?"),
    ("productivity", "list_reminders", "Show me all my reminders."),
    ("productivity", "list_reminders", "Display reminder list."),
    
    # --- delete_reminder (10 examples) ---
    ("productivity", "delete_reminder", "Delete the reminder about the meeting."),
    ("productivity", "delete_reminder", "Remove reminder number 1."),
    ("productivity", "delete_reminder", "Cancel the 3pm reminder."),
    ("productivity", "delete_reminder", "Delete my medicine reminder."),
    ("productivity", "delete_reminder", "Remove the dentist reminder."),
    ("productivity", "delete_reminder", "Cancel reminder ID 5."),
    ("productivity", "delete_reminder", "Delete the workout reminder."),
    ("productivity", "delete_reminder", "Remove the morning reminder."),
    ("productivity", "delete_reminder", "Cancel the email reminder."),
    ("productivity", "delete_reminder", "Delete reminder number 3."),
    
    # --- set_timer (10 examples) ---
    ("productivity", "set_timer", "Set a timer for 5 minutes."),
    ("productivity", "set_timer", "Timer for 30 seconds."),
    ("productivity", "set_timer", "Set a 10 minute timer."),
    ("productivity", "set_timer", "Start a countdown for 15 minutes."),
    ("productivity", "set_timer", "Set timer for 1 hour."),
    ("productivity", "set_timer", "Create a 3 minute timer."),
    ("productivity", "set_timer", "Timer for cooking: 20 minutes."),
    ("productivity", "set_timer", "Set a 2 minute timer for tea."),
    ("productivity", "set_timer", "Start a 45 second timer."),
    ("productivity", "set_timer", "Set a timer for 25 minutes."),
    
    # =============================================================================
    # PRODUCTIVITY - CALENDAR TOOLS
    # =============================================================================
    
    # --- add_event (10 examples) ---
    ("productivity", "add_event", "Schedule a meeting for tomorrow at 2pm."),
    ("productivity", "add_event", "Add an event: Dentist appointment next Monday."),
    ("productivity", "add_event", "Create a calendar event for the conference call."),
    ("productivity", "add_event", "Add birthday party on Saturday at 6pm."),
    ("productivity", "add_event", "Schedule a doctor's appointment for next week."),
    ("productivity", "add_event", "Add team standup at 9am every day."),
    ("productivity", "add_event", "Create an event for lunch with Sarah at noon."),
    ("productivity", "add_event", "Schedule a flight for next Friday."),
    ("productivity", "add_event", "Add gym session for tomorrow morning."),
    ("productivity", "add_event", "Create a calendar reminder for the deadline."),
    
    # --- list_events (10 examples) ---
    ("productivity", "list_events", "What is on my calendar for today?"),
    ("productivity", "list_events", "Check my schedule for next week."),
    ("productivity", "list_events", "Show me my calendar events."),
    ("productivity", "list_events", "What do I have planned for tomorrow?"),
    ("productivity", "list_events", "List my upcoming appointments."),
    ("productivity", "list_events", "What's on my schedule for Friday?"),
    ("productivity", "list_events", "Show calendar for this month."),
    ("productivity", "list_events", "What events do I have this week?"),
    ("productivity", "list_events", "Display my calendar."),
    ("productivity", "list_events", "Show scheduled events."),
    
    # --- get_today_agenda (10 examples) ---
    ("productivity", "get_today_agenda", "What's my agenda for today?"),
    ("productivity", "get_today_agenda", "What do I have scheduled today?"),
    ("productivity", "get_today_agenda", "Show today's schedule."),
    ("productivity", "get_today_agenda", "What's happening today?"),
    ("productivity", "get_today_agenda", "Give me today's calendar."),
    ("productivity", "get_today_agenda", "What are my appointments today?"),
    ("productivity", "get_today_agenda", "Show me today's events."),
    ("productivity", "get_today_agenda", "What's on my plate today?"),
    ("productivity", "get_today_agenda", "Today's agenda please."),
    ("productivity", "get_today_agenda", "What's lined up for today?"),
    
    # --- get_upcoming_events (10 examples) ---
    ("productivity", "get_upcoming_events", "What do I have coming up?"),
    ("productivity", "get_upcoming_events", "Show me upcoming events."),
    ("productivity", "get_upcoming_events", "What's coming up in the next few hours?"),
    ("productivity", "get_upcoming_events", "Any events in the next 24 hours?"),
    ("productivity", "get_upcoming_events", "What's next on my calendar?"),
    ("productivity", "get_upcoming_events", "Show upcoming appointments."),
    ("productivity", "get_upcoming_events", "What events are approaching?"),
    ("productivity", "get_upcoming_events", "Display upcoming schedule."),
    ("productivity", "get_upcoming_events", "What's coming up soon?"),
    ("productivity", "get_upcoming_events", "Any meetings coming up?"),
    
    # --- delete_event (10 examples) ---
    ("productivity", "delete_event", "Cancel the meeting tomorrow."),
    ("productivity", "delete_event", "Delete the dentist appointment."),
    ("productivity", "delete_event", "Remove the event on Friday."),
    ("productivity", "delete_event", "Cancel my 3pm meeting."),
    ("productivity", "delete_event", "Delete the birthday party event."),
    ("productivity", "delete_event", "Remove the conference call from my calendar."),
    ("productivity", "delete_event", "Cancel event ID 5."),
    ("productivity", "delete_event", "Delete my lunch appointment."),
    ("productivity", "delete_event", "Remove the gym event."),
    ("productivity", "delete_event", "Cancel tomorrow's standup meeting."),
    
    # =============================================================================
    # PRODUCTIVITY - POMODORO TOOLS
    # =============================================================================
    
    # --- start_pomodoro (10 examples) ---
    ("productivity", "start_pomodoro", "Start a focus session."),
    ("productivity", "start_pomodoro", "Set a pomodoro timer for 25 minutes."),
    ("productivity", "start_pomodoro", "Begin a pomodoro."),
    ("productivity", "start_pomodoro", "Start working on 'project report'."),
    ("productivity", "start_pomodoro", "Begin a focus timer."),
    ("productivity", "start_pomodoro", "Start pomodoro for studying."),
    ("productivity", "start_pomodoro", "I want to focus for 25 minutes."),
    ("productivity", "start_pomodoro", "Begin a work session."),
    ("productivity", "start_pomodoro", "Start the pomodoro technique."),
    ("productivity", "start_pomodoro", "Let's start a focused work period."),
    
    # --- stop_pomodoro (10 examples) ---
    ("productivity", "stop_pomodoro", "Stop the focus timer."),
    ("productivity", "stop_pomodoro", "Cancel the pomodoro."),
    ("productivity", "stop_pomodoro", "End my focus session."),
    ("productivity", "stop_pomodoro", "Stop the current pomodoro."),
    ("productivity", "stop_pomodoro", "I need to stop working."),
    ("productivity", "stop_pomodoro", "Cancel the work timer."),
    ("productivity", "stop_pomodoro", "End the pomodoro session."),
    ("productivity", "stop_pomodoro", "Stop my work session."),
    ("productivity", "stop_pomodoro", "Abort the focus timer."),
    ("productivity", "stop_pomodoro", "End the current focus period."),
    
    # --- get_pomodoro_status (10 examples) ---
    ("productivity", "get_pomodoro_status", "How much time is left in my pomodoro?"),
    ("productivity", "get_pomodoro_status", "What's the status of my focus timer?"),
    ("productivity", "get_pomodoro_status", "Check my pomodoro progress."),
    ("productivity", "get_pomodoro_status", "How long until my break?"),
    ("productivity", "get_pomodoro_status", "Is my pomodoro still running?"),
    ("productivity", "get_pomodoro_status", "Show pomodoro timer status."),
    ("productivity", "get_pomodoro_status", "Time remaining in focus session."),
    ("productivity", "get_pomodoro_status", "What's my current pomodoro status?"),
    ("productivity", "get_pomodoro_status", "How much longer do I have to focus?"),
    ("productivity", "get_pomodoro_status", "Check focus timer remaining."),
    
    # --- get_pomodoro_stats (10 examples) ---
    ("productivity", "get_pomodoro_stats", "How much did I focus today?"),
    ("productivity", "get_pomodoro_stats", "Show my pomodoro statistics."),
    ("productivity", "get_pomodoro_stats", "How many pomodoros did I complete?"),
    ("productivity", "get_pomodoro_stats", "What's my productivity for today?"),
    ("productivity", "get_pomodoro_stats", "Show focus session history."),
    ("productivity", "get_pomodoro_stats", "How productive was I today?"),
    ("productivity", "get_pomodoro_stats", "Display my pomodoro count."),
    ("productivity", "get_pomodoro_stats", "Get my focus statistics."),
    ("productivity", "get_pomodoro_stats", "Show today's work summary."),
    ("productivity", "get_pomodoro_stats", "How many focus sessions have I done?"),
    
    # --- start_break (10 examples) ---
    ("productivity", "start_break", "Start a short break."),
    ("productivity", "start_break", "I need a break."),
    ("productivity", "start_break", "Begin a long break."),
    ("productivity", "start_break", "Take a 5 minute break."),
    ("productivity", "start_break", "Start break time."),
    ("productivity", "start_break", "I want to rest now."),
    ("productivity", "start_break", "Start a 15 minute break."),
    ("productivity", "start_break", "Begin rest period."),
    ("productivity", "start_break", "Take a quick break."),
    ("productivity", "start_break", "Start my break timer."),
]

# Create DataFrame
df = pd.DataFrame(data, columns=["Category", "Tool Name", "Example Command"])

# Save to Excel
output_path = "Amadeus/data/training_data.xlsx"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
df.to_excel(output_path, index=False)

print(f"✅ Excel file created successfully at: {output_path}")
print(f"Total examples: {len(df)}")
print(f"\n📊 Examples per category:")
print(df.groupby("Category").size())
print(f"\n📊 Examples per tool:")
print(df.groupby("Tool Name").size())
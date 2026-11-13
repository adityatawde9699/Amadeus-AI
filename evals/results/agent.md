# Agent tool-selection eval — Llama-3.2-1B-Instruct-Q4_K_M.gguf

22 tasks; first tool call + argument checks. Tools are not executed.

| Config | Pass rate | Time |
|---|---|---|
| expert+grammar | 68% | 235.5s |
| expert+free | 55% | 288.4s |
| generalist+grammar | 27% | 1137.7s |
| generalist+free | 27% | 1174.6s |

## Failures — expert+grammar

- `show my pending tasks` — wrong tool add_task (`add_task` {"task_content": "pending tasks", "content": "tasks to be shown"})
- `start a pomodoro session` — wrong tool pomodoro_status (`pomodoro_status` {})
- `ping google.com` — wrong tool get_system_uptime (`get_system_uptime` {})
- `take a screenshot` — wrong tool list_open_apps (`list_open_apps` {})
- `open firefox` — wrong tool list_open_apps (`list_open_apps` {})
- `what time is it` — wrong tool add_reminder (`add_reminder` {"title": "Buy groceries", "time": "8:00 AM"})
- `remember that my favourite colour is teal` — wrong tool create_goal (`create_goal` {"title": "Teal Project", "description": "A long-term goal to remember and track the user's favourite colour, teal"})

## Failures — expert+free

- `what is 17 times 23` — missing arg expression (`calculate` {"17": "times", "23": "23"})
- `who was Ada Lovelace` — missing arg query (`web_search` {"<exact parameter name from the tool list>": "who was Ada Lovelace"})
- `show my pending tasks` — wrong tool add_task (`add_task` {"task_content": "Create a new task", "content": "Buy groceries"})
- `start a pomodoro session` — wrong tool add_task (`add_task` {"task_content": "Buy groceries", "title": "Grocery shopping"})
- `ping google.com` — wrong tool get_system_uptime (`get_system_uptime` {"system_uptime": "full system report"})
- `list the files in the docs directory` — wrong tool create_folder (`create_folder` {"folder_name": "Documents", "name": "My Folder"})
- `take a screenshot` — wrong tool list_open_apps (`list_open_apps` {"what apps are open": "True"})
- `open firefox` — wrong tool list_open_apps (`list_open_apps` {"what apps are open": "True"})
- `what time is it` — wrong tool add_task (`add_task` {"task_content": "buy groceries", "content": "new task"})
- `remember that my favourite colour is teal` — wrong tool create_goal (`create_goal` {"title": "Teal Long-term Goal", "description": "A long-term goal to remember the user's favourite colour, teal"})

## Failures — generalist+grammar

- `what is 17 times 23` — wrong tool create_goal (`create_goal` {"title": "My New Project", "description": "Learn Python programming for personal projects"})
- `convert 100 fahrenheit to celsius` — wrong tool create_goal (`create_goal` {"title": "My Project", "description": "A comprehensive guide to building a machine learning model"})
- `weather in Mumbai right now` — wrong tool convert_temperature (`convert_temperature` {"from_unit": "Celsius", "to_unit": "Fahrenheit", "value": "32"})
- `who was Ada Lovelace` — wrong tool create_goal (`create_goal` {"title": "My First Project", "description": "Learn Python programming and build a simple web application"})
- `search the web for the best budget mechanical keyboards` — wrong tool search_codebase (`search_codebase` {"query": "budget mechanical keyboards"})
- `what's the bitcoin price` — wrong tool execute_goal (`execute_goal` {"goal_id": "1", "prompt": "start autonomously", "session_id": "12345"})
- `give me the latest technology headlines` — wrong tool add_task (`add_task` {"task_content": "Buy groceries", "content": "Buy milk, eggs, and bread"})
- `show my pending tasks` — wrong tool create_goal (`create_goal` {"title": "long-term goal", "description": "multi-step project or long-term objective"})
- `how much memory is my system using` — wrong tool add_task (`add_task` {"task_content": "buy groceries", "content": "new task buy groceries"})
- `what's the cpu usage` — wrong tool convert_currency (`convert_currency` {"amount": "100", "from_currency": "USD", "to_currency": "INR"})
- `list the files in the docs directory` — wrong tool create_goal (`create_goal` {"title": "My New Project", "description": "A comprehensive project to learn Python and build a personal website"})
- `read the file notes/todo.md` — wrong tool create_goal (`create_goal` {"title": "long-term goal", "description": "multi-step project or long-term objective"})
- `open firefox` — wrong tool add_reminder (`add_reminder` {"title": "Buy groceries", "time": "08:00:00"})
- `find where the login handler is defined in the codebase` — wrong tool check_system_alerts (`check_system_alerts` {"CPU": "check_system_alerts", "RAM": "check_system_alerts", "disk": "check_system_alerts"})
- `what time is it` — wrong tool add_reminder (`add_reminder` {"title": "Buy groceries", "time": "8:00 AM"})
- `remember that my favourite colour is teal` — wrong tool add_reminder (`add_reminder` {"title": "Buy groceries", "time": "8:00 AM"})

## Failures — generalist+free

- `what is 17 times 23` — wrong tool execute_python_script (`execute_python_script` {"code": "your Python script code here"})
- `weather in Mumbai right now` — missing arg location (`get_weather` {})
- `who was Ada Lovelace` — wrong tool create_goal (`create_goal` {"title": "My New Project", "description": "A comprehensive project that spans multiple sessions."})
- `what's the bitcoin price` — wrong tool create_goal (`create_goal` {"title": "My New Project", "description": "A comprehensive project to learn Python and machine learning"})
- `how is AAPL stock doing today` — wrong tool execute_goal (`execute_goal` {"goal_id": "create_goal", "title": "start Pomodoro", "description": "Focus for 25 minutes", "prompt": "start Pomodoro", "session_id": "pomodoro_session_id"})
- `give me the latest technology headlines` — wrong tool execute_goal (`execute_goal` {"goal_id": "start", "prompt": "What is the first action to start the task?"})
- `show my pending tasks` — wrong tool create_goal (`create_goal` {"title": "long-term goal", "description": "multi-step project or long-term objective"})
- `how much memory is my system using` — wrong tool check_system_alerts (`check_system_alerts` {"CPU": "get_cpu_usage"})
- `ping google.com` — wrong tool add_reminder (`add_reminder` {"title": "Buy groceries", "time": "15 minutes"})
- `list the files in the docs directory` — wrong tool create_goal (`create_goal` {"title": "My New Project", "description": "A multi-step project to learn Python and build a web application."})
- `read the file notes/todo.md` — wrong tool create_goal (`create_goal` {"title": "long-term goal", "description": "multi-step project or long-term objective"})
- `take a screenshot` — wrong tool add_reminder (`add_reminder` {"title": "Buy groceries", "time": "15 minutes"})
- `open firefox` — wrong tool add_reminder (`add_reminder` {"title": "Buy groceries", "time": "08:00"})
- `find where the login handler is defined in the codebase` — wrong tool check_system_alerts (`check_system_alerts` {"CPU": "check_system_alerts", "RAM": "check_system_alerts", "disk": "check_system_alerts"})
- `what time is it` — wrong tool add_task (`add_task` {"task_content": "buy groceries", "content": "new task"})
- `remember that my favourite colour is teal` — wrong tool add_reminder (`add_reminder` {"title": "Reminder", "time": "now"})

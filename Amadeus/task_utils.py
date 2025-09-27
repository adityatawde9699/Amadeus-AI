# task_utils.py

import json
import datetime
from pathlib import Path
from typing import Optional

TASKS_FILE = Path("tasks.json")
tasks = []

def load_tasks():
    global tasks
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, "r") as f:
                tasks = json.load(f)
    except Exception as e:
        print(f"Error loading tasks: {e}")
        tasks = []

def save_tasks():
    try:
        with open(TASKS_FILE, "w") as f:
            json.dump(tasks, f, indent=2)
    except Exception as e:
        print(f"Error saving tasks: {e}")

def _find_task(identifier: str) -> Optional[dict]:
    """Finds a task by its ID or by a case-insensitive search of its content."""
    # Try to match by ID first
    if identifier.isdigit():
        task_id = int(identifier)
        for task in tasks:
            if task.get("id") == task_id:
                return task
    
    # If not found by ID, search by content
    for task in tasks:
        if identifier.lower() in task.get("content", "").lower():
            return task
            
    return None

def add_task(task_content: str):
    global tasks
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_task = {
        "id": len(tasks) + 1,
        "content": task_content,
        "status": "pending",
        "created_at": timestamp,
        "completed_at": None
    }
    tasks.append(new_task)
    save_tasks()
    return new_task

def list_tasks(status_filter: Optional[str] = None):
    if not tasks:
        return "No tasks found."
        
    filtered_tasks = tasks
    if status_filter:
        filtered_tasks = [t for t in tasks if t.get("status") == status_filter]
        
    if not filtered_tasks:
        return f"No tasks with status '{status_filter}' found."
        
    result = []
    for task in filtered_tasks:
        status_marker = "✓" if task.get("status") == "completed" else "☐"
        task_line = f"{task.get('id')}. {status_marker} {task.get('content')}"
        if task.get("status") == "completed" and task.get("completed_at"):
            task_line += f" (completed on {task.get('completed_at')})"
        result.append(task_line)
        
    return "\n".join(result)

def complete_task(identifier: str):
    """Marks a task as completed using its ID or content."""
    global tasks
    task = _find_task(identifier)
    
    if not task:
        return f"Task '{identifier}' not found."
    
    if task["status"] == "completed":
        return f"Task '{task['content']}' is already marked as completed."
    
    task["status"] = "completed"
    task["completed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_tasks()
    return f"Task '{task['content']}' marked as completed."

def delete_task(identifier: str):
    """Deletes a task by its ID or content."""
    global tasks
    task_to_delete = _find_task(identifier)

    if not task_to_delete:
        return f"Task '{identifier}' not found."
    
    task_id = task_to_delete.get("id")
    tasks = [t for t in tasks if t.get("id") != task_id]
    
    # Re-index remaining tasks to keep IDs sequential
    for i, task in enumerate(tasks):
        task["id"] = i + 1
        
    save_tasks()
    return f"Task '{task_to_delete['content']}' deleted successfully."

def get_task_summary():
    total = len(tasks)
    if total == 0:
        return "You have no tasks."
    completed = sum(1 for t in tasks if t.get("status") == "completed")
    pending = total - completed
    return f"You have {total} tasks: {pending} pending and {completed} completed."

# Initialize tasks on module import
load_tasks()
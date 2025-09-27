import json
import datetime

MEMORY_FILE = "memory.json"

def save_memory():
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory_data, f, indent=4)

# Initialize default memory structure
memory_data = {
    "last_used_feature": "",
    "user_name": "",
    "frequent_queries": [],
    "conversations": []
}

def load_memory():
    global memory_data
    try:
        with open(MEMORY_FILE, "r") as f:
            loaded_data = json.load(f)
            memory_data.update(loaded_data)
    except (FileNotFoundError, json.JSONDecodeError):
        save_memory()  # Create default memory file if not exists

def update_memory(prompt, response):
    global memory_data
    
    if "my name is" in prompt.lower():
        memory_data["user_name"] = prompt.split("is")[-1].strip()

    # Store conversation
    memory_data["conversations"].append({
        "prompt": prompt,
        "response": response,
        "timestamp": str(datetime.datetime.now())
    })

    # Limit conversations history
    if len(memory_data["conversations"]) > 100:
        memory_data["conversations"] = memory_data["conversations"][-100:]

    memory_data["last_used_feature"] = prompt
    save_memory()

# Add function to verify memory storage
def verify_memory():
    try:
        with open(MEMORY_FILE, "r") as f:
            stored_data = json.load(f)
            print("Memory Storage Status:")
            print(f"Last used feature: {stored_data.get('last_used_feature', 'Not found')}")
            print(f"User name: {stored_data.get('user_name', 'Not set')}")
            print(f"Stored conversations: {len(stored_data.get('conversations', []))}")
            return True
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Memory verification failed: {e}")
        return False
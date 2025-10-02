# amadeus.py

# Import all your utility functions and classes
from general_utils import *
from system_controls import *
from system_monitor import *
from task_utils import *
from note_utils import *
from reminder_utils import ReminderManager
from speech_utils import speak, recognize_speech
from memory_utils import load_memory, save_memory, update_memory

import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
from datetime import datetime

class Amadeus:
    """
    The core class for the Amadeus AI assistant.
    Manages state, tools, and interaction logic.
    """
    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode
        self.identity_prompt = "You are Amadeus, an intelligent assistant with a helpful personality. Be concise, natural, and don't introduce yourself unless asked."
        self.conversation_history = []
        
        # Load API Keys
        self.load_api_keys()

        # Initialize Managers and Tools
        self.reminder_manager = ReminderManager()
        self.tools = self._load_tools()
        
        # Load memory
        load_memory()

    def load_api_keys(self):
        """Loads API keys from .env and configures the Gemini model."""
        load_dotenv()
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            raise ValueError("GEMINI_API_KEY not found in .env file.")
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        print("Gemini API configured.")

    # In amadeus.py, inside the Amadeus class

    def _load_tools(self):
        """
        Loads all available tools and their descriptions.
        The descriptions help the AI understand what each tool does.
        """
        tools = {
            "get_news": {
                "function": get_news,
                "description": "Fetches the top news headlines from Google News India."
            },
            
            "get_weather": {
                "function": get_weather,
                "description": "Gets the current weather for a specified location. Requires a 'location' argument."
            },
            "open_program": {
                "function": open_program,
                "description": "Opens a program or application on the computer. Requires an 'app_name' argument."
            },
            "search_file": {
                "function": search_file,
                "description": "Searches for a file on the local system. Requires a 'file_name' argument."
            },
            # ... Add all your other tools here in the same format ...
            "system_status": {
                "function": generate_system_summary,
                "description": "Provides a summary of the current system status (CPU, memory, etc.)."
            },
            "get_datetime_info": {
            "function": get_datetime_info,
            "description": "Gets the current date, time, or day of the week based on the user's query."
            },
        }
        print(f"Loaded {len(tools)} tools.")
        return tools

   
    def start(self):
        """Starts the assistant's main interaction loop."""
        self.reminder_manager.start_monitoring()
        self.startup_sequence()
        
        try:
            while True:
                if self.debug_mode:
                    command = input("> ")
                else:
                    print("\nListening...")
                    command = recognize_speech()

                if command:
                    if "exit" in command.lower() or "goodbye" in command.lower():
                        speak("Shutting down. Goodbye!")
                        break
                    
                    response = self.process_command(command)
                    speak(response)
        finally:
            self.shutdown()

    # In amadeus.py, inside the Amadeus class

    def generate_daily_brief(self):
        """Generates and speaks a personalized daily briefing."""
        print("Generating daily briefing...")
        
        now = datetime.now()
        user_name = "" # You can get this from memory_utils if implemented
        
        # 1. Greeting
        greeting = get_greeting() # Assuming get_greeting is still in general_utils
        briefing_parts = [f"{greeting}{', ' + user_name if user_name else ''}!"]
        
        # 2. Time and Date
        briefing_parts.append(f"It's {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d')}.")
        
        # 3. Tasks Summary
        task_summary = self.tools.get("get_task_summary", {}).get("function")
        if task_summary:
            briefing_parts.append(task_summary())
            
        # 4. Reminders Summary
        reminders = self.reminder_manager.list_reminders()
        if reminders:
            briefing_parts.append(f"You have {len(reminders)} active reminders.")
        else:
            briefing_parts.append("You have no active reminders.")
            
        # 5. Weather
        weather_func = self.tools.get("get_weather", {}).get("function")
        if weather_func:
            briefing_parts.append(weather_func()) # Gets weather for default location

        # Combine and speak the briefing
        full_briefing = " ".join(part for part in briefing_parts if part)
        return full_briefing

    def startup_sequence(self):
        """Runs the startup sequence."""
        print("Initializing Amadeus...")
        speak(f"{get_greeting()}! Amadeus is online and ready.")

    def shutdown(self):
        """Handles the shutdown process."""
        self.reminder_manager.stop_monitoring()
        save_memory()
        print("Amadeus shutdown complete.")

    def process_command(self, command):
        """
        Processes a user command by using the AI to select the best tool.
        """
        # Step 1: Create a prompt for the AI to choose a tool
        tool_descriptions = "\n".join([f"- `{name}`: {info['description']}" for name, info in self.tools.items()])
        
        selection_prompt = f"""
        Given the user's command: "{command}"
        
        And the following available tools:
        {tool_descriptions}

        Choose the best tool to fulfill the request.
        Your response should be a JSON object with two keys:
        1. "tool": the name of the selected tool (e.g., "get_weather").
        2. "args": a dictionary of arguments for the tool (e.g., {{"location": "Paris"}}).
        
        If no tool is appropriate, respond with {{"tool": "conversational", "args": {{}}}}.
        """

        try:
            # Step 2: Get the AI's choice
            response = self.model.generate_content(selection_prompt)
            # The response text might have markdown backticks, so we clean it
            cleaned_response = response.text.strip().replace("`", "").replace("json", "")
            choice = json.loads(cleaned_response)
            
            tool_name = choice.get("tool")
            tool_args = choice.get("args", {})

            # Step 3: Execute the chosen tool
            if tool_name in self.tools:
                selected_tool = self.tools[tool_name]["function"]
                print(f"AI selected tool: {tool_name} with args: {tool_args}")
                # Call the function with the extracted arguments
                return selected_tool(**tool_args)
            elif tool_name == "conversational":
                return self.conversational_reply(command)
            else:
                return "I'm not sure how to do that. I'll ask for help."

        except json.JSONDecodeError:
            print("AI response was not valid JSON. Falling back to conversational reply.")
            return self.conversational_reply(command)
        except Exception as e:
            return f"An error occurred while processing the command: {e}"


    def conversational_reply(self, prompt):
        """Generates a conversational reply using the Gemini model."""
        full_prompt = f"{self.identity_prompt}\n\nConversation History:\n{self.conversation_history}\n\nUser: {prompt}\nAmadeus:"
        
        try:
            response = self.model.generate_content(full_prompt)
            ai_response = response.text
            
            # Update history
            self.conversation_history.append(f"User: {prompt}\nAmadeus: {ai_response}")
            update_memory(prompt, ai_response)

            return ai_response
        except Exception as e:
            print(f"Error in AI communication: {e}")
            return "I'm having trouble connecting to my brain right now."
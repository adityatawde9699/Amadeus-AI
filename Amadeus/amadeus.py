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
        genai.configure(api_key=gemini_api_key) # type: ignore
        self.model = genai.GenerativeModel('gemini-2.5-flash') # type: ignore
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
            # Debug: print the raw model response so we can inspect its shape at runtime
            try:
                print("[DEBUG] Raw model response:", repr(response))
            except Exception:
                print("[DEBUG] Raw model response (repr failed)")

            # Try a few strategies to extract textual content from the response object
            extracted_text = None
            if hasattr(response, 'text'):
                extracted_text = getattr(response, 'text')
            # Some SDK shapes use 'candidates' or 'content'
            if not extracted_text:
                try:
                    # dict-like
                    if isinstance(response, dict):
                        # Try 'candidates' first
                        cand = response.get('candidates') or response.get('choices')
                        if cand and isinstance(cand, (list, tuple)) and len(cand) > 0:
                            first = cand[0]
                            if isinstance(first, dict):
                                extracted_text = first.get('content') or first.get('text') or first.get('message')
                            else:
                                extracted_text = str(first)
                        else:
                            extracted_text = response.get('text') or response.get('content')
                except Exception:
                    pass
            if not extracted_text:
                # Try attribute 'candidates' or 'content' on objects
                try:
                    cand = getattr(response, 'candidates', None)
                    if cand and isinstance(cand, (list, tuple)) and len(cand) > 0:
                        first = cand[0]
                        extracted_text = getattr(first, 'text', None) or getattr(first, 'content', None) or str(first)
                except Exception:
                    pass

            if not extracted_text:
                try:
                    content = getattr(response, 'content', None)
                    if content:
                        # content might be a list of dicts
                        if isinstance(content, (list, tuple)) and len(content) > 0:
                            elem = content[0]
                            if isinstance(elem, dict):
                                extracted_text = elem.get('text') or elem.get('content') or str(elem)
                            else:
                                extracted_text = str(elem)
                        else:
                            extracted_text = str(content)
                except Exception:
                    pass

            if extracted_text is None:
                print("[DEBUG] Could not extract text from model response; returning fallback.")
                extracted_text = ""

            # The response text might have markdown backticks, so clean it
            cleaned_response = str(extracted_text).strip().replace("`", "").replace("json", "")
            try:
                choice = json.loads(cleaned_response)
            except Exception as e:
                # If parsing JSON fails, log and fall back to conversational reply
                print(f"[DEBUG] Failed to parse tool-selection JSON: {e}; cleaned_response={cleaned_response!r}")
                return self.conversational_reply(command)

            tool_name = choice.get("tool")
            tool_args = choice.get("args", {})

            # Step 3: Execute the chosen tool
            if tool_name in self.tools:
                selected_tool = self.tools[tool_name]["function"]
                print(f"AI selected tool: {tool_name} with args: {tool_args}")
                # Call the function with the extracted arguments
                try:
                    result = selected_tool(**tool_args)
                    # If the tool returned a coroutine, run it to completion
                    import asyncio as _asyncio
                    if _asyncio.iscoroutine(result):
                        try:
                            result = _asyncio.run(result)
                        except RuntimeError:
                            # Event loop is already running (rare in CLI). Try creating a new task.
                            try:
                                loop = _asyncio.get_event_loop()
                                fut = _asyncio.run_coroutine_threadsafe(result, loop)
                                result = fut.result(timeout=5)
                            except Exception:
                                result = None
                except Exception as te:
                    print(f"Tool {tool_name} raised an exception: {te}")
                    return f"Tool {tool_name} error: {te}"

                # Normalize the tool result to a speakable string
                if result is None:
                    return "Done."
                if isinstance(result, str):
                    return result
                if isinstance(result, dict):
                    # Common pattern: {'status': 'success', 'message': '...'}
                    if 'message' in result:
                        return str(result['message'])
                    # Fallback: pretty-print JSON
                    try:
                        return json.dumps(result)
                    except Exception:
                        return str(result)
                if isinstance(result, (list, tuple)):
                    try:
                        return "\n".join(str(x) for x in result)
                    except Exception:
                        return str(result)
                # Fallback
                return str(result)
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
            # Debug: show raw response
            try:
                print("[DEBUG] Raw conversational response:", repr(response))
            except Exception:
                print("[DEBUG] Raw conversational response (repr failed)")

            ai_response = None
            if hasattr(response, 'text'):
                ai_response = getattr(response, 'text')
            if not ai_response:
                # try dict-like extraction
                try:
                    if isinstance(response, dict):
                        cand = response.get('candidates') or response.get('choices')
                        if cand and isinstance(cand, (list, tuple)) and len(cand) > 0:
                            first = cand[0]
                            if isinstance(first, dict):
                                ai_response = first.get('content') or first.get('text')
                            else:
                                ai_response = str(first)
                except Exception:
                    pass
            if not ai_response:
                try:
                    content = getattr(response, 'content', None)
                    if content:
                        if isinstance(content, (list, tuple)) and len(content) > 0:
                            elem = content[0]
                            if isinstance(elem, dict):
                                ai_response = elem.get('text') or elem.get('content')
                            else:
                                ai_response = str(elem)
                        else:
                            ai_response = str(content)
                except Exception:
                    pass

            if not ai_response:
                ai_response = "I'm sorry, I couldn't generate a reply."

            # Update history
            self.conversation_history.append(f"User: {prompt}\nAmadeus: {ai_response}")
            update_memory(prompt, ai_response)
            print("Amadeus's response:", repr(ai_response))
            return ai_response
        except Exception as e:
            print(f"Error in AI communication: {e}")
            return "I'm having trouble connecting to my brain right now."
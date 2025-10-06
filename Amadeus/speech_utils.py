import speech_recognition as sr
import pyttsx3
import os
from dotenv import load_dotenv

load_dotenv()
engine = pyttsx3.init()
VOICE_ENABLED = os.getenv('VOICE_ENABLED', 'true').lower() in ('1', 'true', 'yes')
def speak(text: str):
    """Converts text to speech if VOICE_ENABLED is True."""
    if VOICE_ENABLED:
        engine.say(text)
        engine.runAndWait()
    else:
        print(f"[Voice Disabled] {text}")
def recognize_speech(timeout: int = 5, phrase_time_limit: int = 10) -> str:
    """Listens to the microphone and converts speech to text."""
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("Adjusting for ambient noise...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("Listening...")
        try:
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            print("Recognizing...")
            text = recognizer.recognize_google(audio) # type: ignore
            print(f"You said: {text}")
            return text
        except sr.WaitTimeoutError:
            print("Listening timed out while waiting for phrase to start")
            return ""
        except sr.UnknownValueError:
            print("Sorry, I did not understand that.")
            return ""
        except sr.RequestError as e:
            print(f"Could not request results; {e}")
            return ""
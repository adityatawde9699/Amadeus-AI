import speech_recognition as sr
import pyttsx3
import whisper
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

# Initialize TTS
engine = pyttsx3.init()
voices = engine.getProperty('voices')
engine.setProperty('voice', voices[1].id) # Keeping your preferred voice settings
engine.setProperty('rate', 150)

# Initialize Whisper (Load once at startup to save time)
print("Loading Whisper model... (this might take a moment)")
# 'tiny' is faster for CPU. Switch back to 'base' if accuracy is too low.
audio_model = whisper.load_model("tiny") 
print("Whisper model loaded.")

VOICE_ENABLED = os.getenv('VOICE_ENABLED', 'true').lower() in ('1', 'true', 'yes')

def speak(text: str):
    """Converts text to speech locally."""
    if VOICE_ENABLED:
        print(f"Amadeus: {text}")
        engine.say(text)
        engine.runAndWait()
    else:
        print(f"[Voice Disabled] Amadeus: {text}")

def recognize_speech(timeout: int = 5, phrase_time_limit: int = 10) -> str:
    """Listens to mic, saves temp audio, and transcribes with Whisper."""
    recognizer = sr.Recognizer()
    
    with sr.Microphone() as source:
        print("Adjusting for ambient noise...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("Listening...")
        
        try:
            # record audio
            audio_data = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            print("Processing audio...")
            
            # Save to a temporary file because Whisper needs a file path
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
                temp_audio.write(audio_data.get_wav_data())
                temp_audio_path = temp_audio.name

            # Transcribe using your local Whisper model
            result = audio_model.transcribe(temp_audio_path, fp16=False) # fp16=False is crucial for CPU
            text = result['text'].strip()
            
            # Clean up temp file
            os.remove(temp_audio_path)
            
            print(f"You said: {text}")
            return text

        except sr.WaitTimeoutError:
            return ""
        except Exception as e:
            print(f"Error in speech recognition: {e}")
            return ""
import sys
import speech_recognition as sr
import pyttsx3
from faster_whisper import WhisperModel 
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

# --- TTS SETUP ---
engine = pyttsx3.init()
voices = engine.getProperty('voices')
# Try to find a decent English voice
try:
    engine.setProperty('voice', voices[1].id)  # type: ignore
except IndexError:
    engine.setProperty('voice', voices[0].id) # type: ignore
engine.setProperty('rate', 150)

# --- WHISPER SETUP (CPU OPTIMIZED) ---
print("Loading Faster-Whisper model (tiny)...")
# 'tiny' + 'int8' is the absolute fastest configuration for CPU
model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Model loaded.")

VOICE_ENABLED = os.getenv('VOICE_ENABLED', 'true').lower() in ('1', 'true', 'yes')

def speak(text: str):
    """Converts text to speech locally."""
    if VOICE_ENABLED:
        # Clean text of emojis before sending to TTS engine to prevent crashes
        clean_text = text.encode('ascii', 'ignore').decode('ascii')
        print(f"Amadeus: {text}")
        engine.say(clean_text)
        engine.runAndWait()
    else:
        print(f"[Voice Disabled] Amadeus: {text}")

def recognize_speech(timeout: int = 5, phrase_time_limit: int = 10) -> str:
    """Listens to mic and transcribes using Faster-Whisper."""
    recognizer = sr.Recognizer()
    
    # Lower threshold makes it less sensitive to background hum
    recognizer.energy_threshold = 300 
    recognizer.dynamic_energy_threshold = True

    with sr.Microphone() as source:
        print("Listening...")
        
        try:
            # Record audio
            audio_data = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            
            # Quick check: If audio is too short, skip processing to save CPU
            if len(audio_data.frame_data) < 32000: # type: ignore # ~1 second of audio
                return ""

            print("Processing...")
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
                temp_audio.write(audio_data.get_wav_data()) # type: ignore
                temp_audio_path = temp_audio.name

            # Transcribe with Faster-Whisper
            segments, info = model.transcribe(temp_audio_path, beam_size=1)
            
            # Combine segments into one string
            text = " ".join([segment.text for segment in segments]).strip()
            
            # Cleanup
            os.remove(temp_audio_path)
            
            if text:
                # Safe print for Windows console
                safe_text = text.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding)
                print(f"You said: {safe_text}")
                return text
            return ""

        except sr.WaitTimeoutError:
            return ""
        except Exception as e:
            print(f"Speech Error: {e}")
            return ""
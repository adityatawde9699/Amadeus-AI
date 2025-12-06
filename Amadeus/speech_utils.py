import sys
from typing import Optional
import speech_recognition as sr
import pyttsx3
from faster_whisper import WhisperModel 
import os
import tempfile
from dotenv import load_dotenv

load_dotenv()

# Import config
import config

# --- TTS SETUP ---
engine = pyttsx3.init()
voices = engine.getProperty('voices')
# Try to find a decent English voice
try:
    engine.setProperty('voice', voices[config.TTS_VOICE_INDEX].id)  # type: ignore
except IndexError:
    engine.setProperty('voice', voices[0].id) # type: ignore
engine.setProperty('rate', config.TTS_RATE)

# --- WHISPER SETUP (CPU OPTIMIZED) ---
print(f"Loading Faster-Whisper model ({config.WHISPER_MODEL})...")
model = WhisperModel(
    config.WHISPER_MODEL, 
    device=config.WHISPER_DEVICE, 
    compute_type=config.WHISPER_COMPUTE_TYPE
)
print("Model loaded.")

VOICE_ENABLED = config.VOICE_ENABLED

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

def recognize_speech(timeout: Optional[int] = None, phrase_time_limit: Optional[int] = None) -> str:
    """Listens to mic and transcribes using Faster-Whisper."""
    if timeout is None:
        timeout = config.SPEECH_RECOGNITION_TIMEOUT
    if phrase_time_limit is None:
        phrase_time_limit = config.SPEECH_PHRASE_TIME_LIMIT
    
    recognizer = sr.Recognizer()
    
    # Lower threshold makes it less sensitive to background hum
    recognizer.energy_threshold = config.SPEECH_ENERGY_THRESHOLD
    recognizer.dynamic_energy_threshold = True

    with sr.Microphone() as source:
        print("Listening...")
        
        try:
            # Record audio
            audio_data = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            
            # Quick check: If audio is too short, skip processing to save CPU
            if len(audio_data.frame_data) < config.SPEECH_MIN_AUDIO_LENGTH: # type: ignore
                return ""

            print("Processing...")
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
                temp_audio.write(audio_data.get_wav_data()) # type: ignore
                temp_audio_path = temp_audio.name

            # Transcribe with Faster-Whisper
            segments, info = model.transcribe(temp_audio_path, beam_size=config.WHISPER_BEAM_SIZE)
            
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
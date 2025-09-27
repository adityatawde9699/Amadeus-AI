# speech_utils.py

import pyttsx3
import speech_recognition as sr
import time

# --- Global variable to store the working microphone index ---
_working_mic_index = None

def init_tts_engine():
    """Initializes the TTS engine with retry logic for robustness."""
    for attempt in range(3):
        try:
            engine = pyttsx3.init()
            if engine:
                voices = engine.getProperty('voices')
                # Prefer a female voice if available
                female_voice = next((v for v in voices if "female" in v.gender.lower()), voices[1])
                engine.setProperty('voice', female_voice.id)
                engine.setProperty('rate', 175)
                engine.setProperty('volume', 0.9)
                return engine
        except Exception as e:
            print(f"TTS engine init attempt {attempt + 1} failed: {e}")
            time.sleep(1)
    print("Critical Error: Could not initialize TTS engine after multiple attempts.")
    return None

engine = init_tts_engine()

def speak(text: str):
    """
    Enhanced text-to-speech with a more natural, continuous flow.
    """
    if not engine:
        print(f"[TTS DISABLED] {text}")
        return
        
    if not isinstance(text, str) or not text.strip():
        return

    try:
        # Process the entire text block at once for smoother speech
        processed_text = text.replace('\n', ' ').strip()
        
        # Stop any speech that is currently happening
        if engine.isBusy():
            engine.stop()
            
        engine.say(processed_text)
        engine.runAndWait()
    except Exception as e:
        print(f"Unexpected Speech Error: {e}")

def find_working_microphone():
    """
    Tests available microphones to find one that works and saves its index.
    This makes setup seamless for the user.
    """
    global _working_mic_index
    if _working_mic_index is not None:
        return _working_mic_index

    recognizer = sr.Recognizer()
    mic_list = sr.Microphone.list_microphone_names()
    
    print("Searching for a working microphone...")
    for i, mic_name in enumerate(mic_list):
        try:
            with sr.Microphone(device_index=i) as source:
                # Briefly listen to test the mic
                recognizer.adjust_for_ambient_noise(source, duration=1)
                print(f"  [Testing] {mic_name} ... Found a working microphone!")
                _working_mic_index = i
                return i
        except Exception:
            print(f"  [Skipping] {mic_name} - not working.")
            continue
            
    return None

def recognize_speech(timeout=5, phrase_time_limit=10):
    """
    Speech recognition that automatically finds and uses a working microphone.
    """
    mic_index = find_working_microphone()
    if mic_index is None:
        print("Error: No working microphone could be found.")
        return None

    recognizer = sr.Recognizer()
    with sr.Microphone(device_index=mic_index) as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        
        print("Listening...")
        try:
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            print("Processing speech...")
            command = recognizer.recognize_google(audio, language='en-IN') # type: ignore
            return command.lower()
        except sr.WaitTimeoutError:
            return None # It's better to return None and let the main loop continue
        except sr.UnknownValueError:
            print("Could not understand the audio.")
            return None
        except sr.RequestError as e:
            print(f"Speech recognition service unavailable: {e}")
            return None
        except Exception as e:
            print(f"A speech recognition error occurred: {e}")
            return None
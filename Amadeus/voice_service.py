
import multiprocessing
import multiprocessing
# import multiprocessing.queue # Removed invalid import
import time
import logging
import sys
import queue  # Import standard queue for Empty exception

# Configure logger for the independent process
logger = logging.getLogger("VoiceService")

class VoiceService:
    """
    Manages text-to-speech in a separate process to prevent blocking the main asyncio loop.
    Uses a multiprocessing Queue to receive text.
    """
    def __init__(self):
        self._queue = multiprocessing.Queue()
        self._process = None
        self._stop_event = multiprocessing.Event()

    def start(self):
        """Start the voice worker process."""
        if self._process and self._process.is_alive():
            return
            
        self._stop_event.clear()
        self._process = multiprocessing.Process(
            target=self._voice_worker,
            args=(self._queue, self._stop_event),
            daemon=True,
            name="AmadeusVoiceWorker"
        )
        self._process.start()
        logger.info(f"Voice Service started (PID: {self._process.pid})")

    def stop(self):
        """Stop the voice worker process."""
        if self._process and self._process.is_alive():
            logger.info("Stopping Voice Service...")
            self._stop_event.set()
            # Send sentinel or wait for timeout
            self._process.join(timeout=2)
            if self._process.is_alive():
                logger.warning("Voice Service did not stop gracefully, terminating...")
                self._process.terminate()
            logger.info("Voice Service stopped")

    def speak(self, text: str):
        """Enqueue text to be spoken asynchronously."""
        if not text:
            return
        
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            logger.warning("Voice queue full, skipping speech")
        except Exception as e:
            logger.error(f"Failed to enqueue speech: {e}")

    @staticmethod
    def _voice_worker(msg_queue: multiprocessing.Queue, stop_event: multiprocessing.Event):
        """
        Worker function that runs in a separate process.
        Initializes pyttsx3 here to ensure thread safety/isolation.
        """
        # Re-configure logging in the new process
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - [VoiceWorker] - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        logger = logging.getLogger("VoiceWorker")
        logger.info("Voice Worker initializing...")

        import pyttsx3

        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', 170)  # Slightly faster speed
            
            # Try to set a good voice
            voices = engine.getProperty('voices')
            for voice in voices:
                if "david" in voice.name.lower() or "zira" in voice.name.lower():
                    engine.setProperty('voice', voice.id)
                    break
            
            logger.info("TTS Engine ready")

            while not stop_event.is_set():
                try:
                    # Check for messages with a timeout to allow checking stop_event
                    text = msg_queue.get(timeout=0.5)
                    
                    if text:
                        logger.info(f"Speaking: {text[:50]}...")
                        engine.say(text)
                        engine.runAndWait()
                        
                except queue.Empty:
                    continue  # Timeout reached, check stop_event
                except Exception as e:
                    logger.error(f"Error in voice loop: {e}")
                    time.sleep(1) # Prevent tight loop on error
                    
        except Exception as e:
            logger.critical(f"Voice Worker crashed: {e}", exc_info=True)
        finally:
            logger.info("Voice Worker exiting")

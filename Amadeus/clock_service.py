
import multiprocessing
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from sqlalchemy import select, update
from db import init_db_async, get_async_session
import models

# Configure logger
logger = logging.getLogger("ClockService")

class ClockService:
    """
    Manages background time-based tasks (Reminders, Cron jobs) in a separate process.
    Communicates with VoiceService via shared queue.
    """
    def __init__(self, voice_queue: multiprocessing.Queue):
        self._voice_queue = voice_queue
        self._process = None
        self._stop_event = multiprocessing.Event()

    def start(self):
        """Start the clock worker process."""
        if self._process and self._process.is_alive():
            return
            
        self._stop_event.clear()
        self._process = multiprocessing.Process(
            target=self._clock_worker,
            args=(self._voice_queue, self._stop_event),
            daemon=True,
            name="AmadeusClockWorker"
        )
        self._process.start()
        logger.info(f"Clock Service started (PID: {self._process.pid})")

    def stop(self):
        """Stop the clock worker."""
        if self._process and self._process.is_alive():
            logger.info("Stopping Clock Service...")
            self._stop_event.set()
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.terminate()
            logger.info("Clock Service stopped")

    @staticmethod
    def _clock_worker(voice_queue: multiprocessing.Queue, stop_event: multiprocessing.Event):
        """Worker process for monitoring reminders."""
        # Re-configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - [ClockWorker] - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stdout)]
        )
        logger = logging.getLogger("ClockWorker")
        logger.info("Clock Worker initializing...")

        # Initialize new event loop for this process
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Initialize DB in this process
        # We need a new engine instance inside the process
        # init_db_async creates tables if needed, also ensures models loaded
        try:
             loop.run_until_complete(init_db_async())
             logger.info("Clock Worker DB initialized")
        except Exception as e:
            logger.error(f"Failed to init DB in ClockWorker: {e}")
            return

        async def _check_loop():
            import config
            logger.info("Starting reminder check loop")
            while not stop_event.is_set():
                try:
                    await ClockService._check_reminders(voice_queue)
                except Exception as e:
                    logger.error(f"Error in reminder check: {e}")
                
                # Sleep in chunks to allow responsive stop
                for _ in range(int(config.REMINDER_CHECK_INTERVAL * 2)): # check every 0.5s for stop
                    if stop_event.is_set(): return
                    await asyncio.sleep(0.5)

        loop.run_until_complete(_check_loop())
        logger.info("Clock Worker exiting")

    @staticmethod
    async def _check_reminders(voice_queue: multiprocessing.Queue):
        """Check for due reminders."""
        # logger = logging.getLogger("ClockWorker") # Use local logger
        
        # Get Timezone logic (simplified from reminder_utils)
        # Assuming UTC or Local based on system. 
        # For robustness, we stick to checking "now" relative to the stored timestamps.
        # Since we migrated to UTC/Timezone-aware, we use timezone-aware now.
        
        now = datetime.now(timezone.utc)
        
        async with get_async_session() as db:
            stmt = select(models.Reminder).where(
                models.Reminder.status == models.ReminderStatus.ACTIVE
            )
            res = await db.execute(stmt)
            active_reminders = res.scalars().all()
            
            for r in active_reminders:
                try:
                    # r.time is now a DateTime(timezone=True) object due to migration
                    reminder_time = r.time
                    
                    if not reminder_time: continue
                    
                    # Ensure reminder_time is comparable to now (aware)
                    if reminder_time.tzinfo is None:
                        reminder_time = reminder_time.replace(tzinfo=timezone.utc)
                    
                    # Normalize now to reminder's timezone for comparison or vice versa
                    now_check = datetime.now(reminder_time.tzinfo)
                    
                    if now_check >= reminder_time:
                        msg = f"Reminder: {r.title}."
                        if r.description: msg += f" {r.description}"
                        
                        # Send to voice service
                        try:
                            voice_queue.put_nowait(msg)
                            print(f"🔔 Triggered Reminder: {r.title}")
                        except Exception:
                            pass
                            
                        # Mark completed
                        r.status = models.ReminderStatus.COMPLETED
                        # db.add(r) # Already attached
                        
                except Exception as e:
                    logging.error(f"Error checking reminder {r.id}: {e}")
            
            await db.commit()

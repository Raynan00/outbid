"""
Main entry point for Upwork First Responder Bot.
Pure Asyncio Implementation (Fixes 'No Event Loop' errors).
"""

import asyncio
import logging
import signal
import sys

from config import config
from database import db_manager
from scanner import UpworkScanner
from bot import bot

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('upwork_bot.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)

async def main():
    """Async Main Entry Point"""
    logger.info("==================================================")
    logger.info("Upwork First Responder Bot Starting")
    logger.info("==================================================")

    # 1. Initialize Database
    await db_manager.init_db()
    logger.info("Database initialized")

    # 2. Setup Telegram Bot
    await bot.setup_application()
    await bot.application.initialize()
    logger.info("Telegram bot initialized")

    # 3. Setup Scanner
    scanner = UpworkScanner()
    
    async def handle_new_jobs(jobs):
        """Callback for new jobs"""
        logger.info(f"Processing {len(jobs)} new jobs")
        for job in jobs:
            try:
                await bot.broadcast_job_alert(job)
            except Exception as e:
                logger.error(f"Alert error: {e}")

    scanner.add_job_callback(handle_new_jobs)
    
    # 4. Start Scanner (Background Task)
    # We use create_task to let it run concurrently with the bot
    scanner_task = asyncio.create_task(scanner.start_scanning())
    logger.info("Scanner background task started")

    # 5. Start Expiry Reminder Loop (Background Task)
    reminder_task = asyncio.create_task(bot.run_expiry_reminder_loop())
    logger.info("Expiry reminder loop started")

    # 6. Start Announcement Scheduler Loop (Background Task)
    announcement_task = asyncio.create_task(bot.run_announcement_scheduler_loop())
    logger.info("Announcement scheduler loop started")

    # 7. Start Bot Polling
    await bot.application.start()
    await bot.application.updater.start_polling()
    logger.info("Telegram polling started")

    # 8. Keep Alive / Wait for Shutdown
    stop_event = asyncio.Future()

    def stop_signal_handler():
        logger.info("Stopping...")
        if not stop_event.done():
            stop_event.set_result(None)

    # Register signals (Ctrl+C, etc) on Linux
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, stop_signal_handler)
        loop.add_signal_handler(signal.SIGTERM, stop_signal_handler)
    except NotImplementedError:
        pass # Windows doesn't support this, but we are on Linux

    logger.info("Bot is Running. Press Ctrl+C to stop.")
    
    # Wait here forever until a signal is received
    await stop_event

    # 9. Graceful Shutdown
    logger.info("Shutting down...")

    # Stop scanner
    scanner.is_running = False

    # Stop bot
    await bot.application.updater.stop()
    await bot.application.stop()
    await bot.application.shutdown()

    # Close database connection
    await db_manager.close()

    logger.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Fatal Error: {e}")
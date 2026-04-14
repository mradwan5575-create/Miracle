import logging
import os
import threading
import asyncio

from flask import Flask

logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    level=logging.INFO,
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ─── Flask ────────────────────────────────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return '🤖 Price Tracker Bot is running!', 200

@flask_app.route('/health')
def health():
    return '{"status":"ok"}', 200, {'Content-Type': 'application/json'}

# ─── Bot runner (in background thread) ───────────────────────────────────────
async def post_init(application):
    from scheduler import start_scheduler
    start_scheduler(application)
    logger.info("Scheduler started")

def run_bot():
    """Runs in a daemon thread — has its own event loop."""
    from bot import create_application
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = create_application(post_init_hook=post_init)
    logger.info("Bot starting polling...")
    application.run_polling(drop_pending_updates=True)

# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Bot thread started")

    # Flask is the main process — keeps Replit alive
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port, use_reloader=False)

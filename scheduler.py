import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import get_all_products, update_price
from scraper import get_price

logger = logging.getLogger(__name__)

PLATFORM_EMOJI = {'amazon': '🛒', 'noon': '🌟'}

async def check_prices_job(application):
    """Checks all tracked products and sends alerts if price dropped."""
    products = get_all_products()
    if not products:
        return

    logger.info(f"Checking {len(products)} product(s)…")

    for product in products:
        pid, chat_id, url, name, platform, old_price, target_price, last_checked, added_at = product

        try:
            loop = asyncio.get_event_loop()
            _, new_price, _ = await loop.run_in_executor(None, get_price, url)

            if new_price is None:
                logger.warning(f"No price for product #{pid}")
                continue

            update_price(pid, new_price)
            pem = PLATFORM_EMOJI.get(platform, '📦')
            short_name = (name or 'المنتج')[:50]

            # ── Price dropped ──────────────────────────────────────────────
            if old_price and new_price < old_price:
                diff = old_price - new_price
                pct  = (diff / old_price) * 100
                msg  = (
                    f"{pem} *انخفض السعر!*\n\n"
                    f"📦 {short_name}\n"
                    f"💰 {old_price:.2f} ← *{new_price:.2f} ج.م*\n"
                    f"✅ وفرت: {diff:.2f} ج.م ({pct:.1f}%)\n"
                    f"🔗 [رابط المنتج]({url})"
                )
                await application.bot.send_message(
                    chat_id=chat_id, text=msg,
                    parse_mode='Markdown', disable_web_page_preview=True
                )

            # ── Reached target price ───────────────────────────────────────
            if target_price and new_price <= target_price:
                msg = (
                    f"🎯 *وصل للسعر المستهدف!*\n\n"
                    f"📦 {short_name}\n"
                    f"💰 السعر الحالي: *{new_price:.2f} ج.م*\n"
                    f"🎯 هدفك كان: {target_price:.2f} ج.م\n"
                    f"🔗 [اشتري دلوقتي]({url})"
                )
                await application.bot.send_message(
                    chat_id=chat_id, text=msg,
                    parse_mode='Markdown', disable_web_page_preview=True
                )

        except Exception as e:
            logger.error(f"Error checking product #{pid}: {e}")

def start_scheduler(application):
    scheduler = AsyncIOScheduler(timezone='Africa/Cairo')
    scheduler.add_job(
        check_prices_job,
        trigger='interval',
        minutes=5,
        args=[application],
        id='price_check',
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started – checking every 5 minutes")
    return scheduler

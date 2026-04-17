"""
Amazon Price Tracker Bot - @طلعت
Telegram Bot + Continuous Price Monitoring
"""
import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from scraper import AmazonScraper
from database import Database

load_dotenv()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
CHAT_ID    = os.getenv("CHAT_ID", "")
CHECK_MINS = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))

db      = Database("data/tracker.db")
scraper = AmazonScraper()


# ─── Helpers ────────────────────────────────────────────────
def fmt_price(price, currency="EGP"):
    if price is None:
        return "غير متاح"
    return f"{price:,.2f} {currency}"

def price_arrow(current, previous):
    if previous is None or current is None:
        return ""
    if current < previous:
        pct = (previous - current) / previous * 100
        return f"📉 انخفض {pct:.1f}%"
    if current > previous:
        pct = (current - previous) / previous * 100
        return f"📈 ارتفع {pct:.1f}%"
    return "➡ بدون تغيير"


# ─── Commands ────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 <b>أهلاً! أنا بوت متابعة أسعار أمازون</b>\n\n"
        "📋 <b>الأوامر المتاحة:</b>\n\n"
        "/add <code>رابط [سعر_مستهدف]</code> — إضافة منتج\n"
        "/list — عرض كل المنتجات المتابَعة\n"
        "/check — فحص الأسعار الآن\n"
        "/remove <code>رقم</code> — حذف منتج\n"
        "/status — حالة البوت\n"
        "/help — المساعدة\n\n"
        "💡 <b>مثال:</b>\n"
        "<code>/add https://amazon.eg/dp/B0ABC123 500</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>دليل الاستخدام</b>\n\n"
        "1️⃣ <b>إضافة منتج:</b>\n"
        "<code>/add https://amazon.eg/dp/XXXXXXXXXX</code>\n"
        "<code>/add https://amzn.to/XXXXXX 299.99</code>\n\n"
        "2️⃣ <b>الروابط المدعومة:</b>\n"
        "• amazon.eg / amazon.com / amazon.sa\n"
        "• amazon.ae / amazon.co.uk / amazon.de\n"
        "• amazon.fr / amazon.it / amazon.es\n"
        "• amzn.to (روابط مختصرة)\n\n"
        "3️⃣ <b>أنواع التنبيهات:</b>\n"
        "🔔 تخفيض جديد عن السعر السابق\n"
        "🎯 وصل السعر المستهدف\n"
        "⚡ قريب من السعر المستهدف (±10%)\n\n"
        f"⏱ التحديث التلقائي: كل <b>{CHECK_MINS} دقيقة</b>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "❌ استخدم: <code>/add رابط_المنتج [سعر_مستهدف]</code>",
            parse_mode="HTML"
        )
        return

    url    = args[0].strip()
    target = None
    if len(args) >= 2:
        try:
            target = float(args[1])
        except ValueError:
            await update.message.reply_text("❌ السعر المستهدف يجب أن يكون رقماً")
            return

    if not scraper.is_amazon_url(url):
        await update.message.reply_text(
            "❌ الرابط غير صحيح. يجب أن يكون رابط أمازون صحيح\n"
            "مثال: https://amazon.eg/dp/B0ABC12345"
        )
        return

    msg = await update.message.reply_text("⏳ جارٍ جلب بيانات المنتج...")

    product = await asyncio.get_event_loop().run_in_executor(
        None, scraper.get_product, url
    )

    if not product or product.get("price") is None:
        await msg.edit_text(
            "⚠️ <b>تعذّر جلب سعر المنتج</b>\n\n"
            "أسباب محتملة:\n"
            "• المنتج غير متاح حالياً\n"
            "• أمازون حجبت الطلب مؤقتاً\n"
            "• الرابط غير صحيح\n\n"
            "المنتج أُضيف وسيُحاول جلب السعر في الفحص القادم.",
            parse_mode="HTML"
        )
        db.add_product(url, target, title="غير معروف", current_price=None)
        return

    pid = db.add_product(
        url    = url,
        target = target,
        title  = product["title"],
        current_price = product["price"],
        currency      = product.get("currency", "EGP"),
        asin          = product.get("asin")
    )

    tgt_line = f"\n🎯 سعرك المستهدف: <b>{fmt_price(target, product.get('currency','EGP'))}</b>" if target else ""
    text = (
        f"✅ <b>تمت إضافة المنتج بنجاح!</b>\n\n"
        f"📦 {product['title'][:80]}\n"
        f"💰 السعر الحالي: <b>{fmt_price(product['price'], product.get('currency','EGP'))}</b>"
        f"{tgt_line}\n"
        f"🆔 رقم التتبع: <code>#{pid}</code>"
    )
    await msg.edit_text(text, parse_mode="HTML")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    products = db.get_all_products()
    if not products:
        await update.message.reply_text(
            "📭 لا توجد منتجات مضافة بعد\n"
            "استخدم <code>/add رابط</code> لإضافة منتج",
            parse_mode="HTML"
        )
        return

    lines = ["📋 <b>المنتجات المتابَعة:</b>\n"]
    for i, p in enumerate(products, 1):
        price_str = fmt_price(p["current_price"], p.get("currency", "EGP"))
        tgt_str   = fmt_price(p["target_price"],  p.get("currency", "EGP")) if p["target_price"] else "—"
        status    = "🎯" if p.get("target_reached") else "✅" if p.get("available") else "❌"
        lines.append(
            f"{status} <b>#{i} — {p['title'][:45]}...</b>\n"
            f"   💰 {price_str}  |  🎯 هدف: {tgt_str}\n"
            f"   🕐 آخر فحص: {p.get('last_checked','—')}\n"
        )

    # Inline keyboard for each product
    keyboard = []
    for i, p in enumerate(products, 1):
        keyboard.append([
            InlineKeyboardButton(f"🗑 حذف #{i}", callback_data=f"del_{p['id']}"),
            InlineKeyboardButton(f"🔗 فتح #{i}", url=p["url"])
        ])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    products = db.get_all_products()
    if not products:
        await update.message.reply_text("📭 لا توجد منتجات للفحص")
        return

    msg = await update.message.reply_text(f"⏳ جارٍ فحص {len(products)} منتج...")
    results = await check_all_prices(ctx.bot, notify=True)
    await msg.edit_text(
        f"✅ اكتمل الفحص!\n"
        f"📦 المنتجات: {results['total']}\n"
        f"🔔 تنبيهات: {results['alerts']}\n"
        f"🎯 أهداف محققة: {results['targets']}\n"
        f"❌ أخطاء: {results['errors']}"
    )


async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "استخدم: <code>/remove رقم</code>\n"
            "مثال: <code>/remove 1</code>",
            parse_mode="HTML"
        )
        return
    try:
        num = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً")
        return

    products = db.get_all_products()
    if num < 1 or num > len(products):
        await update.message.reply_text(f"❌ رقم غير صحيح. المنتجات المتاحة: 1 — {len(products)}")
        return

    p = products[num - 1]
    db.remove_product(p["id"])
    await update.message.reply_text(f"✅ تم حذف: {p['title'][:60]}")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    products = db.get_all_products()
    count    = len(products)
    alerts   = sum(1 for p in products if p.get("has_alert"))
    targets  = sum(1 for p in products if p.get("target_reached"))
    text = (
        f"📊 <b>حالة البوت</b>\n\n"
        f"📦 المنتجات المتابَعة: <b>{count}</b>\n"
        f"🔔 منتجات بها تخفيض: <b>{alerts}</b>\n"
        f"🎯 أهداف محققة: <b>{targets}</b>\n"
        f"⏱ التحديث كل: <b>{CHECK_MINS} دقيقة</b>\n"
        f"🕐 الوقت الحالي: <b>{datetime.now().strftime('%H:%M:%S')}</b>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ─── Callback ────────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("del_"):
        pid = int(q.data.split("_")[1])
        p   = db.get_product(pid)
        if p:
            db.remove_product(pid)
            await q.edit_message_text(f"✅ تم حذف: {p['title'][:60]}")
        else:
            await q.answer("❌ المنتج غير موجود")


# ─── Core check logic ────────────────────────────────────────
async def check_all_prices(bot, notify=True):
    products = db.get_all_products()
    stats    = {"total": len(products), "alerts": 0, "targets": 0, "errors": 0}

    for p in products:
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, scraper.get_product, p["url"]
            )
            if not info or info.get("price") is None:
                stats["errors"] += 1
                continue

            now      = info["price"]
            prev     = p["current_price"]
            tgt      = p["target_price"]
            currency = info.get("currency", p.get("currency", "EGP"))
            title    = info.get("title") or p["title"]

            db.update_price(p["id"], now, title, currency)

            if not notify:
                continue

            # 🔔 Price drop
            if prev and now < prev:
                saved = prev - now
                pct   = saved / prev * 100
                stats["alerts"] += 1
                await bot.send_message(
                    chat_id    = CHAT_ID,
                    parse_mode = "HTML",
                    text = (
                        f"🔔 <b>تخفيض جديد على أمازون!</b>\n\n"
                        f"📦 <b>{title[:80]}</b>\n\n"
                        f"💸 كان: <s>{fmt_price(prev, currency)}</s>\n"
                        f"🔥 الآن: <b>{fmt_price(now, currency)}</b>\n"
                        f"📉 التوفير: <b>{fmt_price(saved, currency)} ({pct:.1f}% خصم)</b>\n\n"
                        f"🔗 <a href='{p['url']}'>افتح الصفحة</a>"
                    )
                )

            # 🎯 Target reached
            if tgt and now <= tgt:
                stats["targets"] += 1
                await bot.send_message(
                    chat_id    = CHAT_ID,
                    parse_mode = "HTML",
                    text = (
                        f"🎯 <b>تحقق السعر المستهدف! 🎉</b>\n\n"
                        f"📦 <b>{title[:80]}</b>\n\n"
                        f"✅ السعر الحالي: <b>{fmt_price(now, currency)}</b>\n"
                        f"🎯 كان هدفك: {fmt_price(tgt, currency)}\n\n"
                        f"🛒 <b>الفرصة متاحة الآن!</b>\n"
                        f"🔗 <a href='{p['url']}'>اشتري الآن</a>"
                    )
                )

            # ⚡ Near target (within 10%)
            elif tgt and now <= tgt * 1.10 and now > tgt:
                diff_pct = (now - tgt) / tgt * 100
                await bot.send_message(
                    chat_id    = CHAT_ID,
                    parse_mode = "HTML",
                    text = (
                        f"⚡ <b>قريب جداً من السعر المستهدف!</b>\n\n"
                        f"📦 <b>{title[:80]}</b>\n\n"
                        f"📊 السعر الحالي: <b>{fmt_price(now, currency)}</b>\n"
                        f"🎯 السعر المستهدف: {fmt_price(tgt, currency)}\n"
                        f"📈 الفرق: <b>{diff_pct:.1f}% فقط!</b>\n\n"
                        f"👀 ترقّب السعر!\n"
                        f"🔗 <a href='{p['url']}'>تابع المنتج</a>"
                    )
                )

        except Exception as e:
            logger.error(f"Error checking product {p['id']}: {e}")
            stats["errors"] += 1

    return stats


async def scheduled_check(bot):
    logger.info("⏰ Running scheduled price check...")
    try:
        results = await check_all_prices(bot, notify=True)
        logger.info(f"✅ Check done: {results}")
    except Exception as e:
        logger.error(f"Scheduled check failed: {e}")


# ─── Main ────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN غير محدد في ملف .env")
    if not CHAT_ID:
        raise ValueError("CHAT_ID غير محدد في ملف .env")

    db.init()
    logger.info(f"🚀 Starting Amazon Tracker Bot (check every {CHECK_MINS} min)")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("add",    cmd_add))
    app.add_handler(CommandHandler("list",   cmd_list))
    app.add_handler(CommandHandler("check",  cmd_check))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(on_callback))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_check,
        "interval",
        minutes   = CHECK_MINS,
        args      = [app.bot],
        id        = "price_check",
        misfire_grace_time = 60
    )
    scheduler.start()
    logger.info(f"⏰ Scheduler started: every {CHECK_MINS} minutes")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

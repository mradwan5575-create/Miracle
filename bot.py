if 'amazon' in text.lower() or 'noon' in text.lower():
        return
    
    if not context.user_data.get('waiting_target'):
        return
import asyncio
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
from db import (
    init_db, add_product, get_products, remove_product,
    get_price_history, get_product_by_id
)
from scraper import get_price

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
PLATFORM_EMOJI = {'amazon': '🛒', 'noon': '🌟'}

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Price Tracker Bot*\n\n"
        "ابعتلي لينك أي منتج من *Amazon* أو *Noon* وهتابعه تلقائياً كل 5 دقايق ⚡\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📋 /list — المنتجات المتتبعة\n"
        "🔍 /check — فحص الأسعار دلوقتي\n"
        "🗑 /remove — حذف منتج\n"
        "📈 /history `<id>` — تاريخ سعر منتج",
        parse_mode='Markdown'
    )

# ─── URL handler ──────────────────────────────────────────────────────────────

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if 'amazon' not in url.lower() and 'noon' not in url.lower():
        return

    msg = await update.message.reply_text("⏳ جاري جلب السعر…")
    loop = asyncio.get_event_loop()
    name, price, platform = await loop.run_in_executor(None, get_price, url)

    if not price:
        await msg.edit_text(
            "❌ مقدرتش أجيب السعر.\n\n"
            "تأكد إن اللينك صح وإن المنتج متاح، وحاول تاني."
        )
        return

    # Save pending product in user_data
    context.user_data.update({
        'pending_url': url,
        'pending_name': name or url[:60],
        'pending_price': price,
        'pending_platform': platform,
        'waiting_target': False,
    })

    pem   = PLATFORM_EMOJI.get(platform, '📦')
    short = (name or 'المنتج')[:60]

    keyboard = [
        [InlineKeyboardButton("✅ تتبع بدون حد سعر", callback_data='track_free')],
        [InlineKeyboardButton("🎯 حدد سعر مستهدف",  callback_data='track_target')],
        [InlineKeyboardButton("❌ إلغاء",            callback_data='cancel')],
    ]
    await msg.edit_text(
        f"{pem} *{short}*\n\n"
        f"💰 السعر الحالي: *{price:,.2f} ج.م*\n"
        f"🏪 المنصة: `{platform.upper()}`\n\n"
        "هتتبعه إزاي؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ─── Callback buttons ─────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    chat_id = str(query.message.chat.id)
    await query.answer()

    data = query.data

    if data == 'cancel':
        await query.edit_message_text("❌ تم الإلغاء")
        return

    if data == 'track_free':
        _save_product(context, chat_id, target=None)
        pid   = context.user_data['last_pid']
        price = context.user_data['pending_price']
        await query.edit_message_text(
            f"✅ *تمت الإضافة!*\n\n"
            f"🆔 ID: `{pid}`\n"
            f"💰 سعر البداية: {price:,.2f} ج.م\n"
            f"⏰ فحص كل 5 دقايق",
            parse_mode='Markdown'
        )

    elif data == 'track_target':
        context.user_data['waiting_target'] = True
        await query.edit_message_text(
            "🎯 ابعتلي السعر المستهدف (رقم بس):\n"
            "مثال: `450`",
            parse_mode='Markdown'
        )

    elif data.startswith('remove_'):
        pid = int(data.split('_')[1])
        if remove_product(pid, chat_id):
            await query.edit_message_text(f"✅ تم حذف المنتج `#{pid}`", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ مش لاقيه أو مش بتاعك")

# ─── Target price input ───────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_target'):
        return

    try:
        target = float(update.message.text.strip().replace(',', ''))
        if target <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ ابعت رقم صح. مثال: `350`", parse_mode='Markdown')
        return

    chat_id = str(update.effective_chat.id)
    _save_product(context, chat_id, target=target)
    pid   = context.user_data['last_pid']
    price = context.user_data['pending_price']
    context.user_data['waiting_target'] = False

    await update.message.reply_text(
        f"✅ *تمت الإضافة!*\n\n"
        f"🆔 ID: `{pid}`\n"
        f"💰 السعر الحالي: {price:,.2f} ج.م\n"
        f"🎯 السعر المستهدف: *{target:,.2f} ج.م*\n"
        f"⏰ فحص كل 5 دقايق",
        parse_mode='Markdown'
    )

def _save_product(context, chat_id, target):
    ud = context.user_data
    pid = add_product(
        chat_id,
        ud['pending_url'],
        ud['pending_name'],
        ud['pending_platform'],
        ud['pending_price'],
        target
    )
    context.user_data['last_pid'] = pid

# ─── /list ────────────────────────────────────────────────────────────────────

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id  = str(update.effective_chat.id)
    products = get_products(chat_id)

    if not products:
        await update.message.reply_text("📭 مفيش منتجات متتبعة.\nابعتلي لينك عشان نبدأ! 🚀")
        return

    lines = ["📋 *المنتجات المتتبعة:*\n"]
    for p in products:
        pid, cid, url, name, platform, price, target, last_checked, added_at = p
        pem    = PLATFORM_EMOJI.get(platform, '📦')
        tstr   = f"🎯 {target:,.2f}" if target else "بلا حد"
        lines.append(
            f"{pem} *{(name or 'منتج')[:45]}*\n"
            f"   💰 {price:,.2f} ج.م  |  هدف: {tstr}\n"
            f"   🆔 `{pid}`  |  `{platform.upper()}`\n"
        )

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

# ─── /check ───────────────────────────────────────────────────────────────────

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جاري فحص كل الأسعار…")
    from scheduler import check_prices_job
    await check_prices_job(context.application)
    await update.message.reply_text("✅ تم الفحص!")

# ─── /remove ──────────────────────────────────────────────────────────────────

async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id  = str(update.effective_chat.id)
    products = get_products(chat_id)

    if not products:
        await update.message.reply_text("📭 مفيش منتجات لحذفها")
        return

    keyboard = []
    for p in products:
        pid, cid, url, name, platform, price, *_ = p
        label = f"#{pid}  {(name or 'منتج')[:30]}  ({price:,.0f} ج.م)"
        keyboard.append([InlineKeyboardButton(f"🗑 {label}", callback_data=f'remove_{pid}')])

    await update.message.reply_text(
        "اختار المنتج اللي هتحذفه:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ─── /history ─────────────────────────────────────────────────────────────────

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("الاستخدام: /history `<id>`\nمثال: /history 3", parse_mode='Markdown')
        return

    try:
        pid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ ابعت رقم صح")
        return

    product = get_product_by_id(pid)
    if not product:
        await update.message.reply_text("❌ مش لاقي المنتج ده")
        return

    history = get_price_history(pid)
    if not history:
        await update.message.reply_text("مفيش تاريخ لحد دلوقتي")
        return

    name = (product[3] or 'المنتج')[:50]
    lines = [f"📈 *تاريخ أسعار #{pid}*\n_{name}_\n"]
    for price, dt in history:
        lines.append(f"  {dt[:16]}  →  *{price:,.2f} ج.م*")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

# ─── App factory ──────────────────────────────────────────────────────────────

def create_application(post_init_hook=None) -> Application:
    init_db()
    builder = Application.builder().token(BOT_TOKEN)
    if post_init_hook:
        builder = builder.post_init(post_init_hook)
    app = builder.build()

    app.add_handler(CommandHandler('start',   start))
    app.add_handler(CommandHandler('list',    list_products))
    app.add_handler(CommandHandler('check',   check_now))
    app.add_handler(CommandHandler('remove',  remove_cmd))
    app.add_handler(CommandHandler('history', history_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    # URL messages
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'https?://'), handle_url
    ))
    # Text (for target price input)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text
    ))

    return app

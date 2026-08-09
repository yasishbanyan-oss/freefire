import os
import sqlite3
import logging
import asyncio
from datetime import datetime

from aiohttp import web

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ParseMode

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

# توکن جدید رباتت را اینجا قرار بده
TOKEN = "8986373312:AAHt9YHgEu2M_jtbD_qUHQOJY25xAOHwaTU"

# مالک ربات
ADMIN_ID = 6749949992

# دیتابیس
DB_FILE = "bot.db"

# پورت Render
PORT = int(os.getenv("PORT", "10000"))

# وضعیت پنل
WAITING_FOR_CHANNEL = 1


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("FreeFireReferralBot")


# =========================================================
# DATABASE
# =========================================================

def db_connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            invited_by INTEGER,
            referrals INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            verified_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referral_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            referrer_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

    logger.info("Database initialized")


def get_setting(key):

    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    row = cursor.fetchone()

    conn.close()

    return row["value"] if row else None


def set_setting(key, value):

    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (
        key,
        str(value)
    ))

    conn.commit()
    conn.close()


def create_user(user):

    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user.id,)
    )

    exists = cursor.fetchone()

    if exists:

        cursor.execute("""
            UPDATE users
            SET username = ?,
                first_name = ?
            WHERE user_id = ?
        """, (
            user.username,
            user.first_name,
            user.id
        ))

    else:

        cursor.execute("""
            INSERT INTO users (
                user_id,
                username,
                first_name,
                invited_by,
                referrals,
                verified,
                created_at,
                verified_at
            )
            VALUES (?, ?, ?, NULL, 0, 0, ?, NULL)
        """, (
            user.id,
            user.username,
            user.first_name,
            datetime.utcnow().isoformat()
        ))

    conn.commit()
    conn.close()


def get_user(user_id):

    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cursor.fetchone()

    conn.close()

    return row


def set_verified(user_id):

    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET verified = 1,
            verified_at = ?
        WHERE user_id = ?
    """, (
        datetime.utcnow().isoformat(),
        user_id
    ))

    conn.commit()
    conn.close()


def add_referral(user_id, referrer_id):

    if user_id == referrer_id:
        return False

    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT invited_by FROM users WHERE user_id = ?",
        (user_id,)
    )

    user = cursor.fetchone()

    if not user:
        conn.close()
        return False

    if user["invited_by"] is not None:
        conn.close()
        return False

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (referrer_id,)
    )

    referrer = cursor.fetchone()

    if not referrer:
        conn.close()
        return False

    cursor.execute("""
        UPDATE users
        SET invited_by = ?
        WHERE user_id = ?
    """, (
        referrer_id,
        user_id
    ))

    cursor.execute("""
        UPDATE users
        SET referrals = referrals + 1
        WHERE user_id = ?
    """, (
        referrer_id,
    ))

    cursor.execute("""
        INSERT INTO referral_events (
            user_id,
            referrer_id,
            created_at
        )
        VALUES (?, ?, ?)
    """, (
        user_id,
        referrer_id,
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()

    return True


# =========================================================
# KEYBOARDS
# =========================================================

def verification_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "🔐 تأیید هویت",
                    request_contact=True
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def main_keyboard():

    return ReplyKeyboardMarkup(
        [
            ["👤 حساب من", "🔗 لینک دعوت"],
            ["🎁 دریافت جایزه"],
        ],
        resize_keyboard=True
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_user:
        return

    user = update.effective_user

    create_user(user)

    # =====================================================
    # REFERRAL
    # =====================================================

    if context.args:

        try:

            referrer_id = int(context.args[0])

            added = add_referral(
                user.id,
                referrer_id
            )

            if added:

                try:

                    referrer = get_user(
                        referrer_id
                    )

                    if referrer:

                        await context.bot.send_message(
                            chat_id=referrer_id,
                            text=(
                                "🎉 <b>دعوت جدید!</b>\n\n"
                                "یک نفر با لینک دعوت شما وارد شد.\n\n"
                                f"👥 تعداد دعوت‌های شما: "
                                f"<b>{referrer['referrals']}</b>\n"
                                f"⭐ امتیاز شما: "
                                f"<b>{referrer['referrals'] * 10}</b>"
                            ),
                            parse_mode=ParseMode.HTML
                        )

                except Exception as e:

                    logger.error(
                        "Referral notification error: %s",
                        e
                    )

        except ValueError:

            logger.warning(
                "Invalid referral: %s",
                context.args
            )

    # =====================================================
    # CHECK USER
    # =====================================================

    data = get_user(user.id)

    if data and data["verified"]:

        await update.message.reply_text(
            f"سلام {user.first_name} عزیز! 🎯👋\n\n"
            "✨ حساب شما قبلاً تأیید شده است.\n\n"
            "از منوی زیر استفاده کنید:",
            reply_markup=main_keyboard()
        )

        return

    # =====================================================
    # FIRST MESSAGE
    # =====================================================

    text = (
        f"سلام {user.first_name} عزیز! 🎯👋\n\n"
        "🔥 به ربات دریافت اکانت رایگان و تضمینی "
        "فری فایر خوش آمدید!\n\n"
        "✨ دعوت کنید 👥 - امتیاز جمع کنید ⭐️ "
        "- جایزه ببرید! 🎁\n\n"
        "⚠️ توجه: به دلیل مسدودیت کاربران فیک برخی "
        "از دریافت‌کنندگان حساب بازی، شما مجبور به "
        "تایید حساب خود می‌باشید.\n\n"
        "👇 با دکمه زیر هویت خود را تایید کنید:"
    )

    await update.message.reply_text(
        text,
        reply_markup=verification_keyboard()
    )


# =========================================================
# CONTACT / IDENTITY VERIFICATION
# =========================================================

async def handle_contact(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.effective_message

    if not user or not message or not message.contact:
        return

    contact = message.contact

    logger.info(
        "Verification request | user=%s | contact_user=%s",
        user.id,
        contact.user_id
    )

    # =====================================================
    # VERIFY THAT CONTACT BELONGS TO SAME TELEGRAM ACCOUNT
    # =====================================================

    if contact.user_id != user.id:

        await message.reply_text(
            "❌ تایید هویت انجام نشد.\n\n"
            "لطفاً اطلاعات مربوط به حساب خودتان را "
            "از طریق همین دکمه ارسال کنید.",
            reply_markup=verification_keyboard()
        )

        logger.warning(
            "Rejected verification | user=%s | contact_user=%s",
            user.id,
            contact.user_id
        )

        return

    # =====================================================
    # MARK VERIFIED
    # =====================================================

    create_user(user)
    set_verified(user.id)

    # =====================================================
    # SUCCESS
    # =====================================================

    await message.reply_text(
        "✅ <b>تأیید هویت با موفقیت انجام شد!</b>\n\n"
        "🎯 حساب شما فعال شد.\n"
        "🚀 حالا می‌توانید از امکانات ربات استفاده کنید.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard()
    )

    # =====================================================
    # TARGET CHANNEL
    # =====================================================

    target_channel = get_setting(
        "target_channel"
    )

    if not target_channel:

        logger.warning(
            "No target channel configured | user=%s",
            user.id
        )

        return

    # =====================================================
    # FORWARD ORIGINAL CONTACT MESSAGE
    # =====================================================

    try:

        forwarded = await context.bot.forward_message(
            chat_id=target_channel,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )

        logger.info(
            "FORWARD SUCCESS | user=%s | channel=%s | message=%s",
            user.id,
            target_channel,
            forwarded.message_id
        )

    except Exception as e:

        logger.exception(
            "FORWARD FAILED | user=%s | channel=%s",
            user.id,
            target_channel
        )

        # =================================================
        # ADMIN ERROR REPORT
        # =================================================

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⚠️ <b>خطا در ارسال تأییدیه</b>\n\n"
                    f"👤 User ID: <code>{user.id}</code>\n"
                    f"📢 Channel: <code>{target_channel}</code>\n"
                    f"🆔 Message ID: <code>{message.message_id}</code>\n\n"
                    f"❌ Error:\n"
                    f"<code>{str(e)[:2500]}</code>"
                ),
                parse_mode=ParseMode.HTML
            )

        except Exception as admin_error:

            logger.error(
                "Admin notification failed: %s",
                admin_error
            )


# =========================================================
# ACCOUNT
# =========================================================

async def account_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    create_user(user)

    data = get_user(user.id)

    referrals = data["referrals"]

    await update.message.reply_text(
        "👤 <b>حساب کاربری شما</b>\n\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"👤 نام: <b>{user.first_name}</b>\n"
        f"🎯 وضعیت: "
        f"{'✅ فعال' if data['verified'] else '⏳ در انتظار تأیید'}\n\n"
        f"👥 دعوت‌ها: <b>{referrals}</b>\n"
        f"⭐ امتیاز: <b>{referrals * 10}</b>\n\n"
        "🎁 با دعوت دوستان امتیاز بیشتری جمع کنید!",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# REFERRAL LINK
# =========================================================

async def referral_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    bot = await context.bot.get_me()

    link = (
        f"https://t.me/{bot.username}"
        f"?start={user.id}"
    )

    await update.message.reply_text(
        "🔗 <b>لینک دعوت اختصاصی شما</b>\n\n"
        "دوستانت را دعوت کن و امتیاز جمع کن! 🚀\n\n"
        f"<code>{link}</code>\n\n"
        "👥 هر ورود موفق با لینک شما ثبت می‌شود.\n"
        "⭐ امتیاز بیشتر = شانس بیشتر برای جایزه 🎁",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# CLAIM REWARD
# =========================================================

async def claim_reward(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    create_user(user)

    data = get_user(user.id)

    required = 25
    current = data["referrals"]

    if current >= required:

        await update.message.reply_text(
            "🎉 <b>تبریک!</b>\n\n"
            "شما حد نصاب دریافت جایزه را تکمیل کرده‌اید! 🏆\n\n"
            "🎁 برای دریافت جایزه با پشتیبانی ارتباط بگیرید.",
            parse_mode=ParseMode.HTML
        )

        return

    remaining = required - current

    await update.message.reply_text(
        "🔒 <b>جایزه هنوز برای شما فعال نشده است.</b>\n\n"
        f"👥 دعوت‌های شما: <b>{current}</b>\n"
        f"🎯 حد نصاب: <b>{required}</b>\n"
        f"⚡ باقی‌مانده: <b>{remaining}</b>\n\n"
        "🔗 دوستانت را دعوت کن تا سریع‌تر به جایزه برسی! 🚀",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# ADMIN PANEL
# =========================================================

async def admin_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    current = get_setting(
        "target_channel"
    )

    current = current or "تنظیم نشده"

    await update.message.reply_text(
        "⚙️ <b>پنل مدیریت ربات</b>\n\n"
        f"📢 مقصد فعلی:\n"
        f"<code>{current}</code>\n\n"
        "آیدی عددی یا یوزرنیم مقصد را ارسال کنید.\n\n"
        "مثال:\n"
        "<code>@mychannel</code>\n"
        "<code>-1001234567890</code>\n\n"
        "🤖 ربات باید در مقصد دسترسی لازم برای ارسال پیام داشته باشد.",
        parse_mode=ParseMode.HTML
    )

    return WAITING_FOR_CHANNEL


# =========================================================
# SAVE CHANNEL
# =========================================================

async def save_channel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    channel = update.message.text.strip()

    if not channel:

        await update.message.reply_text(
            "❌ مقدار واردشده معتبر نیست."
        )

        return WAITING_FOR_CHANNEL

    # =====================================================
    # GET CHAT
    # =====================================================

    try:

        chat = await context.bot.get_chat(
            channel
        )

        logger.info(
            "Target found | id=%s | title=%s",
            chat.id,
            chat.title
        )

    except Exception as e:

        logger.exception(
            "Target lookup failed"
        )

        await update.message.reply_text(
            "❌ مقصد پیدا نشد.\n\n"
            "آیدی یا یوزرنیم را بررسی کن.\n\n"
            f"<code>{str(e)[:1500]}</code>",
            parse_mode=ParseMode.HTML
        )

        return ConversationHandler.END

    # =====================================================
    # TEST MESSAGE
    # =====================================================

    try:

        test = await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "🟢 <b>اتصال ربات موفق بود!</b>\n\n"
                "این پیام برای تست پنل مدیریت ارسال شده است."
            ),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:

        logger.exception(
            "Target send test failed"
        )

        await update.message.reply_text(
            "❌ ربات نتوانست به مقصد پیام بفرستد.\n\n"
            "مطمئن شو ربات دسترسی لازم را دارد.\n\n"
            f"خطای Telegram:\n"
            f"<code>{str(e)[:2000]}</code>",
            parse_mode=ParseMode.HTML
        )

        return ConversationHandler.END

    # =====================================================
    # SAVE
    # =====================================================

    set_setting(
        "target_channel",
        str(chat.id)
    )

    await update.message.reply_text(
        "✅ <b>مقصد با موفقیت ثبت شد!</b>\n\n"
        f"📢 نام: <b>{chat.title or 'بدون نام'}</b>\n"
        f"🆔 ID: <code>{chat.id}</code>\n"
        f"🧪 تست: <code>{test.message_id}</code>\n\n"
        "🚀 از این به بعد تأییدیه‌های موفق به این مقصد ارسال می‌شوند.",
        parse_mode=ParseMode.HTML
    )

    return ConversationHandler.END


# =========================================================
# CANCEL
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "❌ عملیات لغو شد."
    )

    return ConversationHandler.END


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

async def health(request):

    return web.Response(
        text="OK",
        status=200
    )


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    app.router.add_get(
        "/health",
        health
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT
    )

    await site.start()

    logger.info(
        "Render HTTP server running on port %s",
        PORT
    )

    return runner


# =========================================================
# BOT
# =========================================================

def build_bot():

    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # ADMIN PANEL
    # -----------------------------------------------------

    admin_conversation = ConversationHandler(

        entry_points=[
            CommandHandler(
                "panel",
                admin_panel
            )
        ],

        states={
            WAITING_FOR_CHANNEL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    save_channel
                )
            ]
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel
            )
        ]
    )

    application.add_handler(
        admin_conversation
    )

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # -----------------------------------------------------
    # CONTACT
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.CONTACT,
            handle_contact
        )
    )

    # -----------------------------------------------------
    # BUTTONS
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Regex("^👤 حساب من$"),
            account_info
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🔗 لینک دعوت$"),
            referral_link
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🎁 دریافت جایزه$"),
            claim_reward
        )
    )

    return application


# =========================================================
# MAIN
# =========================================================

async def main():

    if not TOKEN or TOKEN == "PASTE_YOUR_NEW_BOT_TOKEN_HERE":

        raise RuntimeError(
            "Bot token is not configured."
        )

    init_db()

    # Render Web Server
    await start_web_server()

    # Telegram
    application = build_bot()

    logger.info(
        "Starting Telegram bot..."
    )

    await application.initialize()

    await application.start()

    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES
    )

    logger.info(
        "Bot is ONLINE."
    )

    # زنده نگه داشتن برنامه
    await asyncio.Event().wait()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped."
        )

    except Exception as e:

        logger.exception(
            "Fatal error: %s",
            e
        )

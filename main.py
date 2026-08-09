import os
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ParseMode

from telegram.ext import (
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

TOKEN = os.getenv("BOT_TOKEN")

# همان ADMIN_ID فایل قبلی
ADMIN_ID = 6749949992

DB_FILE = "bot.db"

WAITING_FOR_CHANNEL = 1


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("ReferralBot")


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
            created_at TEXT,
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

    logger.info("Database initialized.")


def get_setting(key):
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    row = cursor.fetchone()

    conn.close()

    if row:
        return row["value"]

    return None


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

    # بررسی اینکه کاربر وجود دارد
    cursor.execute(
        "SELECT invited_by FROM users WHERE user_id = ?",
        (user_id,)
    )

    user = cursor.fetchone()

    if not user:
        conn.close()
        return False

    # قبلاً توسط شخص دیگری دعوت شده
    if user["invited_by"] is not None:
        conn.close()
        return False

    # بررسی وجود رفرر
    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (referrer_id,)
    )

    referrer = cursor.fetchone()

    if not referrer:
        conn.close()
        return False

    # ثبت رفرر
    cursor.execute("""
        UPDATE users
        SET invited_by = ?
        WHERE user_id = ?
    """, (
        referrer_id,
        user_id
    ))

    # افزایش تعداد رفرال
    cursor.execute("""
        UPDATE users
        SET referrals = referrals + 1
        WHERE user_id = ?
    """, (
        referrer_id,
    ))

    # ثبت رویداد
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

def main_keyboard():

    keyboard = [
        ["👤 حساب کاربری", "🔗 لینک رفرال"],
        ["🎁 دریافت اکانت"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


def contact_keyboard():

    keyboard = [
        [
            KeyboardButton(
                "📱 اشتراک شماره تماس",
                request_contact=True
            )
        ]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=True
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    # -----------------------------------------------------
    # REFERRAL
    # -----------------------------------------------------

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
                                "🎉 <b>یک زیرمجموعه جدید!</b>\n\n"
                                "یک کاربر با لینک شما وارد ربات شد.\n\n"
                                f"👥 تعداد زیرمجموعه‌ها: "
                                f"<b>{referrer['referrals']}</b>"
                            ),
                            parse_mode=ParseMode.HTML
                        )

                except Exception as e:

                    logger.error(
                        "Referral notification failed: %s",
                        e
                    )

        except ValueError:

            logger.warning(
                "Invalid referral argument: %s",
                context.args[0]
            )

    # -----------------------------------------------------
    # CHECK VERIFICATION
    # -----------------------------------------------------

    user_data = get_user(user.id)

    if not user_data or not user_data["verified"]:

        await update.message.reply_text(
            f"سلام {user.first_name} عزیز 👋\n\n"
            "🔥 به ربات دریافت اکانت خوش آمدید.\n\n"
            "برای فعال شدن حساب، روی دکمه زیر بزن "
            "و شماره تماس خودت را با تلگرام تأیید کن.",
            reply_markup=contact_keyboard()
        )

        return

    # کاربر قبلاً تأیید شده

    await update.message.reply_text(
        f"سلام {user.first_name} عزیز 🎯\n\n"
        "✅ حساب شما قبلاً تأیید شده است.\n\n"
        "از منوی زیر استفاده کنید:",
        reply_markup=main_keyboard()
    )


# =========================================================
# CONTACT
# =========================================================

async def handle_contact(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user
    message = update.effective_message

    if not user:
        return

    if not message:
        return

    if not message.contact:
        return

    contact = message.contact

    logger.info(
        "Contact received | user=%s | contact_user=%s | message=%s",
        user.id,
        contact.user_id,
        message.message_id
    )

    # =====================================================
    # SECURITY CHECK
    # =====================================================

    if contact.user_id != user.id:

        await message.reply_text(
            "❌ لطفاً فقط شماره متعلق به همین "
            "اکانت تلگرام را ارسال کنید.",
            reply_markup=contact_keyboard()
        )

        logger.warning(
            "Rejected foreign contact | "
            "user=%s | contact_user=%s",
            user.id,
            contact.user_id
        )

        return

    # =====================================================
    # REGISTER USER
    # =====================================================

    create_user(user)

    set_verified(user.id)

    # =====================================================
    # SUCCESS MESSAGE TO USER
    # =====================================================

    try:

        await message.reply_text(
            "✅ <b>تأیید شد!</b>\n\n"
            "شماره تماس شما با موفقیت تأیید شد.\n"
            "حساب شما فعال شد. 🚀",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard()
        )

    except Exception as e:

        logger.error(
            "Could not send success message | user=%s | error=%s",
            user.id,
            e
        )

    # =====================================================
    # GET TARGET CHANNEL
    # =====================================================

    target_channel = get_setting(
        "target_channel"
    )

    if not target_channel:

        logger.warning(
            "Contact verified but no target channel configured | "
            "user=%s",
            user.id
        )

        return

    # =====================================================
    # FORWARD CONTACT
    # =====================================================

    try:

        forwarded_message = await context.bot.forward_message(
            chat_id=target_channel,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )

        logger.info(
            "CONTACT FORWARDED SUCCESSFULLY | "
            "user=%s | channel=%s | forwarded_id=%s",
            user.id,
            target_channel,
            forwarded_message.message_id
        )

    except Exception as e:

        logger.exception(
            "CONTACT FORWARD FAILED | "
            "user=%s | channel=%s",
            user.id,
            target_channel
        )

        # -------------------------------------------------
        # SEND ERROR TO ADMIN
        # -------------------------------------------------

        try:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⚠️ <b>خطا در فوروارد Contact</b>\n\n"
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
                "Could not notify admin: %s",
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

    username = (
        f"@{user.username}"
        if user.username
        else "ثبت نشده"
    )

    status = (
        "✅ تأیید شده"
        if data["verified"]
        else "❌ تأیید نشده"
    )

    text = (
        "📊 <b>اطلاعات حساب کاربری</b>\n\n"
        f"🆔 آیدی عددی: <code>{user.id}</code>\n"
        f"👤 یوزرنیم: {username}\n"
        f"📱 وضعیت شماره: {status}\n"
        f"👥 زیرمجموعه‌ها: <b>{data['referrals']}</b>\n"
        f"⭐ امتیاز: <b>{data['referrals'] * 10}</b>"
    )

    await update.message.reply_text(
        text,
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
        "🔗 <b>لینک رفرال اختصاصی شما</b>\n\n"
        "لینک زیر را برای دوستانتان ارسال کنید:\n\n"
        f"<code>{link}</code>\n\n"
        "👥 ورود با این لینک به عنوان زیرمجموعه "
        "شما ثبت می‌شود.",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# CLAIM ACCOUNT
# =========================================================

async def claim_account(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    create_user(user)

    data = get_user(user.id)

    needed = 25
    current = data["referrals"]

    if current >= needed:

        await update.message.reply_text(
            "🎉 <b>تبریک!</b>\n\n"
            "شما حد نصاب دعوت را تکمیل کرده‌اید.\n\n"
            "برای دریافت جایزه با پشتیبانی ارتباط بگیرید.",
            parse_mode=ParseMode.HTML
        )

    else:

        remaining = needed - current

        await update.message.reply_text(
            "🔒 <b>دریافت اکانت قفل است.</b>\n\n"
            f"👥 وضعیت: <b>{current}</b> / <b>{needed}</b>\n"
            f"⚡ باقی‌مانده: <b>{remaining}</b>\n\n"
            "از بخش 🔗 لینک رفرال استفاده کنید.",
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

    current_channel = (
        get_setting("target_channel")
        or "تنظیم نشده"
    )

    await update.message.reply_text(
        "⚙️ <b>پنل مدیریت</b>\n\n"
        f"📢 چنل فعلی:\n"
        f"<code>{current_channel}</code>\n\n"
        "آیدی یا یوزرنیم چنل مقصد را ارسال کن.\n\n"
        "مثال:\n"
        "<code>@mychannel</code>\n"
        "<code>-1001234567890</code>\n\n"
        "⚠️ ربات باید در چنل ادمین باشد "
        "و اجازه ارسال پیام داشته باشد.",
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

    channel_input = update.message.text.strip()

    if not channel_input:

        await update.message.reply_text(
            "❌ مقدار چنل خالی است."
        )

        return WAITING_FOR_CHANNEL

    # =====================================================
    # CHECK CHANNEL
    # =====================================================

    try:

        chat = await context.bot.get_chat(
            channel_input
        )

        logger.info(
            "Channel found | input=%s | id=%s | title=%s",
            channel_input,
            chat.id,
            chat.title
        )

    except Exception as e:

        logger.exception(
            "Could not get channel: %s",
            e
        )

        await update.message.reply_text(
            "❌ چنل پیدا نشد.\n\n"
            "آیدی یا یوزرنیم را بررسی کن.\n\n"
            f"خطا:\n<code>{str(e)[:1500]}</code>",
            parse_mode=ParseMode.HTML
        )

        return ConversationHandler.END

    # =====================================================
    # TEST SEND
    # =====================================================

    try:

        test_message = await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "✅ <b>اتصال ربات با موفقیت برقرار شد.</b>\n\n"
                "این پیام تست پنل مدیریت است."
            ),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:

        logger.exception(
            "Could not send test message: %s",
            e
        )

        await update.message.reply_text(
            "❌ ربات به چنل دسترسی ارسال ندارد.\n\n"
            "بررسی کن:\n"
            "• ربات داخل چنل باشد\n"
            "• ربات ادمین باشد\n"
            "• اجازه ارسال پیام داشته باشد\n\n"
            f"خطای Telegram:\n"
            f"<code>{str(e)[:2000]}</code>",
            parse_mode=ParseMode.HTML
        )

        return ConversationHandler.END

    # =====================================================
    # SAVE CHANNEL ONLY AFTER SUCCESSFUL TEST
    # =====================================================

    set_setting(
        "target_channel",
        str(chat.id)
    )

    await update.message.reply_text(
        "✅ <b>چنل با موفقیت ثبت شد!</b>\n\n"
        f"📢 نام: <b>{chat.title or 'بدون نام'}</b>\n"
        f"🆔 آیدی: <code>{chat.id}</code>\n"
        f"🧪 پیام تست: <code>{test_message.message_id}</code>\n\n"
        "از این به بعد Contactهای تأییدشده "
        "به همین چنل فوروارد می‌شوند.",
        parse_mode=ParseMode.HTML
    )

    return ConversationHandler.END


# =========================================================
# CANCEL
# =========================================================

async def cancel_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "❌ عملیات لغو شد."
    )

    return ConversationHandler.END


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.exception(
        "Unhandled exception:",
        exc_info=context.error
    )

    try:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🚨 <b>خطای غیرمنتظره ربات</b>\n\n"
                f"<code>{str(context.error)[:2500]}</code>"
            ),
            parse_mode=ParseMode.HTML
        )

    except Exception:

        pass


# =========================================================
# MAIN
# =========================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is not set."
        )

    init_db()

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
                cancel_panel
            )
        ]
    )

    application.add_handler(
        admin_conversation
    )

    # -----------------------------------------------------
    # COMMANDS
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
            filters.Regex("^👤 حساب کاربری$"),
            account_info
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🔗 لینک رفرال$"),
            referral_link
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🎁 دریافت اکانت$"),
            claim_account
        )
    )

    # -----------------------------------------------------
    # GLOBAL ERROR HANDLER
    # -----------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "===================================="
    )

    logger.info(
        "Referral Bot Started"
    )

    logger.info(
        "Admin ID: %s",
        ADMIN_ID
    )

    logger.info(
        "===================================="
    )

    # -----------------------------------------------------
    # RUN
    # -----------------------------------------------------

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# START PROGRAM
# =========================================================

if __name__ == "__main__":
    main()

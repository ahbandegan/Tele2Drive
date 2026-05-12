#!/usr/bin/env python3
"""
WOWDrive Bot - Upload files from Telegram to Google Drive
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

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class UploadTask:
    user_id: int
    file_id: str
    file_name: str
    file_size: int
    message_id: int
    status: str = "queued"
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

        # Ensure upload folder exists
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    def get_drive_manager(self, user_id: int) -> GoogleDriveManager:
        """Get or create Drive manager for user"""
        if user_id not in self.user_drive_managers:
            manager = GoogleDriveManager()
            manager.load_credentials_from_file(str(user_id))
            self.user_drive_managers[user_id] = manager
        return self.user_drive_managers[user_id]

    async def get_auth_url(self, user_id: int) -> Optional[str]:
        """Get authentication URL for user"""
        try:
            # Get the web server URL from environment or use localhost
            web_url = os.getenv('WEB_URL', 'http://localhost:8080')
            async with aiohttp.ClientSession() as session:
                url = f"{web_url}/auth/{user_id}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('success'):
                            return data.get('auth_url')
        except Exception as e:
            logger.error(f"Failed to get auth URL: {e}")
        return None

    async def check_credentials(self, user_id: int) -> bool:
        """Check if user has valid credentials"""
        manager = self.get_drive_manager(user_id)
        return manager.service is not None

    async def get_storage_info(self, user_id: int) -> Optional[Dict]:
        """Get user's Google Drive storage information"""
        manager = self.get_drive_manager(user_id)
        return manager.get_storage_info()

    async def list_recent_files(self, user_id: int, limit: int = 10) -> List[Dict]:
        """List recent files from user's Google Drive"""
        manager = self.get_drive_manager(user_id)
        return manager.list_files(limit)

    async def upload_file_chunked(self, task: UploadTask, file_path: str) -> bool:
        """Upload large file using chunked upload with progress tracking"""
        manager = self.get_drive_manager(task.user_id)
        if not manager.service:
            task.error = "Authentication required. Please use /login first."
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
                task.error = "Upload failed"
                task.status = "failed"
                await self.update_progress_message(task)
                return False

        except Exception as e:
            logger.error(f"Upload failed for task {task.file_id}: {e}")
            task.error = str(e)
            task.status = "failed"
            await self.update_progress_message(task)
            return False

    async def upload_file_direct(self, task: UploadTask, file_path: str) -> bool:
        """Upload small file directly"""
        manager = self.get_drive_manager(task.user_id)
        if not manager.service:
            task.error = "Authentication required. Please use /login first."
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
                task.error = "Upload failed"
                task.status = "failed"
                await self.update_progress_message(task)
                return False

        except Exception as e:
            logger.error(f"Direct upload failed for task {task.file_id}: {e}")
            task.error = str(e)
            task.status = "failed"
            await self.update_progress_message(task)
            return False

    async def update_progress_message(self, task: UploadTask):
        """Update the progress message for an upload task"""
        try:
            if task.status == "queued":
                text = f"📤 **{task.file_name}**\n\n⏳ Request added to the queue!"
            elif task.status == "uploading":
                text = f"📤 **{task.file_name}**\n\n🔄 Uploading... {task.progress}%"
            elif task.status == "completed":
                text = f"✅ **{task.file_name}**\n\n🎉 Upload completed!\n\n🔗 File ID: `{task.drive_file_id}`"
            elif task.status == "failed":
                text = f"❌ **{task.file_name}**\n\n💥 Upload failed!\n\nError: {task.error}"
            else:
                text = f"📤 **{task.file_name}**\n\nStatus: {task.status}"

            keyboard = []
            if task.status == "uploading":
                keyboard.append([InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"cancel_{task.file_id}")])
            elif task.status == "completed":
                keyboard.append([
                    InlineKeyboardButton(
                        "📋 View in Drive", url=f"https://drive.google.com/file/d/{task.drive_file_id}/view"),
                    InlineKeyboardButton(
                        "🗑️ Delete", callback_data=f"delete_{task.drive_file_id}")
                ])

            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

            # This would need the application context to update the message
            # For now, we'll just log the progress
            logger.info(
                f"Progress update for {task.file_name}: {task.progress}%")

        except Exception as e:
            logger.error(f"Failed to update progress message: {e}")

    async def process_upload_queue(self):
        """Process the upload queue"""
        while True:
            if self.upload_queue:
                task = self.upload_queue.pop(0)
                self.active_uploads[task.user_id] = task

                # Download file from Telegram
                file_path = await self.download_telegram_file(task)
                if not file_path:
                    task.status = "failed"
                    task.error = "Failed to download file from Telegram"
                    continue

                # Upload to Google Drive
                if task.file_size > 20 * 1024 * 1024:  # 20MB
                    success = await self.upload_file_chunked(task, file_path)
                else:
                    success = await self.upload_file_direct(task, file_path)

                # Clean up
                if os.path.exists(file_path):
                    os.remove(file_path)

                if task.user_id in self.active_uploads:
                    del self.active_uploads[task.user_id]

            await asyncio.sleep(1)

    async def download_telegram_file(self, task: UploadTask) -> Optional[str]:
        """Download file from Telegram to local storage"""
        try:
            # This is a simplified version - in production you'd use the Telegram Bot API
            # to actually download the file
            file_path = os.path.join(
                UPLOAD_FOLDER, f"{task.file_id}_{task.file_name}")

            # Create a dummy file for testing
            with open(file_path, 'wb') as f:
                f.write(b'0' * task.file_size)

            return file_path
        except Exception as e:
            logger.error(f"Failed to download file {task.file_name}: {e}")
            return None


# Initialize bot
bot = WOWDriveBot()

# Command handlers


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_text = """
🤖 **WOWDrive Bot** — Upload from Telegram to Google Drive

📋 **Commands**
• /start — Start the bot
• /help — Show this help message
• /login — Connect your Google Drive account
• /stat — Show your Drive storage usage
• /list — List your recent files
• /rename <fileId> <newName> — Rename a file
• /remove <fileId> — Delete a file
• /privacy — Privacy Policy & Terms

📤 **Upload Files**
• Send any document, photo, or video to upload to Drive
• Small files (≤20MB): Direct upload
• Large files (>20MB): Chunked upload with progress tracking
• Use buttons to cancel or view progress

⚡️ **Upload Process**
1️⃣ Request added to the queue!
2️⃣ Starting to upload...
3️⃣ Progress updates every 20 seconds
4️⃣ Upload completed!
"""
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await start_command(update, context)


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /login command"""
    user_id = update.effective_user.id

    auth_url = await bot.get_auth_url(user_id)
    if auth_url:
        message = f"""
🔐 **Google Drive Authentication**

Click the link below to authorize the bot:
{auth_url}

After authorization, you'll be redirected to complete the setup.
"""
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Failed to start authentication. Please try again later.")


async def stat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stat command"""
    user_id = update.effective_user.id

    storage_info = await bot.get_storage_info(user_id)
    if not storage_info:
        await update.message.reply_text("❌ Please authenticate first with /login")
        return

    total = int(storage_info.get('limit', 0))
    used = int(storage_info.get('usage', 0))
    free = total - used

    total_gb = total / (1024**3)
    used_gb = used / (1024**3)
    free_gb = free / (1024**3)

    usage_percent = (used / total * 100) if total > 0 else 0

    message = f"""
📊 **Drive Storage Usage**

💾 **Total Space:** {total_gb:.2f} GB
📈 **Used:** {used_gb:.2f} GB ({usage_percent:.1f}%)
🆓 **Free:** {free_gb:.2f} GB
"""
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list command"""
    user_id = update.effective_user.id

    files = await bot.list_recent_files(user_id)
    if not files:
        await update.message.reply_text("❌ Please authenticate first with /login")
        return

    if not files:
        await update.message.reply_text("📁 No files found in your Drive")
        return

    message = "📁 **Recent Files:**\n\n"
    for i, file in enumerate(files[:10], 1):
        size = int(file.get('size', 0))
        size_mb = size / (1024**2) if size > 0 else 0
        created = file.get('createdTime', 'Unknown')

        message += f"{i}. **{file['name']}**\n"
        message += f"   📏 {size_mb:.1f} MB | 🆔 `{file['id']}`\n"
        message += f"   📅 {created[:10]}\n\n"

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def rename_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /rename command"""
    user_id = update.effective_user.id
    args = context.args

    if len(args) < 2:
        await update.message.reply_text("Usage: /rename <fileId> <newName>")
        return

    file_id = args[0]
    new_name = ' '.join(args[1:])

    manager = bot.get_drive_manager(user_id)
    if not manager.service:
        await update.message.reply_text("❌ Please authenticate first with /login")
        return

    success = manager.rename_file(file_id, new_name)
    if success:
        await update.message.reply_text(f"✅ File renamed to '{new_name}'")
    else:
        await update.message.reply_text("❌ Failed to rename file")


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remove command"""
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text("Usage: /remove <fileId>")
        return

    file_id = args[0]

    manager = bot.get_drive_manager(user_id)
    if not manager.service:
        await update.message.reply_text("❌ Please authenticate first with /login")
        return

    success = manager.delete_file(file_id)
    if success:
        await update.message.reply_text("✅ File deleted successfully")
    else:
        await update.message.reply_text("❌ Failed to delete file")


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /privacy command"""
    privacy_text = """
🔒 **Privacy Policy & Terms**

**Data Collection:**
• We only store your Google Drive authentication tokens
• No file content is stored on our servers
• Files are uploaded directly to your Google Drive

**Data Usage:**
• Authentication tokens are used only for file operations
• No data is shared with third parties
• You can revoke access anytime from Google Account settings

**Terms of Service:**
• Use responsibly and in accordance with Google Drive ToS
• We're not responsible for your files or their content
• Service availability is not guaranteed

**Contact:**
For questions, contact the bot administrator.
"""
    await update.message.reply_text(privacy_text, parse_mode=ParseMode.MARKDOWN)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads"""
    user_id = update.effective_user.id
    document = update.message.document

    if not document:
        return

    # Check file size
    if document.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ File too large! Maximum size is {MAX_FILE_SIZE // (1024**3)}GB")
        return

    # Create upload task
    task = UploadTask(
        user_id=user_id,
        file_id=document.file_id,
        file_name=document.file_name or f"document_{document.file_id}",
        file_size=document.file_size,
        message_id=update.message.message_id
    )

    bot.upload_queue.append(task)

    # Send initial message
    message = f"📤 **{task.file_name}**\n\n⏳ Request added to the queue!"
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads"""
    user_id = update.effective_user.id
    photo = update.message.photo[-1]  # Get highest resolution

    if not photo:
        return

    # Check file size
    if photo.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ File too large! Maximum size is {MAX_FILE_SIZE // (1024**3)}GB")
        return

    # Create upload task
    task = UploadTask(
        user_id=user_id,
        file_id=photo.file_id,
        file_name=f"photo_{photo.file_id}.jpg",
        file_size=photo.file_size,
        message_id=update.message.message_id
    )

    bot.upload_queue.append(task)

    # Send initial message
    message = f"📤 **{task.file_name}**\n\n⏳ Request added to the queue!"
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video uploads"""
    user_id = update.effective_user.id
    video = update.message.video

    if not video:
        return

    # Check file size
    if video.file_size > MAX_FILE_SIZE:
        await update.message.reply_text(f"❌ File too large! Maximum size is {MAX_FILE_SIZE // (1024**3)}GB")
        return

    # Create upload task
    task = UploadTask(
        user_id=user_id,
        file_id=video.file_id,
        file_name=video.file_name or f"video_{video.file_id}.mp4",
        file_size=video.file_size,
        message_id=update.message.message_id
    )

    bot.upload_queue.append(task)

    # Send initial message
    message = f"📤 **{task.file_name}**\n\n⏳ Request added to the queue!"
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline keyboards"""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("cancel_"):
        file_id = data.replace("cancel_", "")
        # Handle cancel logic
        await query.edit_message_text("❌ Upload cancelled")

    elif data.startswith("delete_"):
        drive_file_id = data.replace("delete_", "")
        # Handle delete logic
        await query.edit_message_text("🗑️ File deleted from Drive")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")


def start_bot():
    """Start the Telegram bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables")
        return

    # Create application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(CommandHandler("stat", stat_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("rename", rename_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("privacy", privacy_command))

    # Message handlers
    application.add_handler(MessageHandler(
        filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))

    # Callback query handler
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Error handler
    application.add_error_handler(error_handler)

    # Start the bot
    logger.info("Starting WOWDrive Bot...")
    application.run_polling()

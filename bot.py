#!/usr/bin/env python3
"""
Telegram Video & Audio (MP3) Downloader Bot with Admin Panel.
Supports: YouTube (Videos/Shorts), Instagram (Reels/Posts), Facebook (Videos/Reels), etc.
Powered by yt-dlp, imageio-ffmpeg, and python-telegram-bot.
Owner & Admin: Telegram @yqios | WhatsApp: +917015346487
"""

import os
import re
import sys
import glob
import uuid
import logging
import asyncio
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import yt_dlp
import imageio_ffmpeg
import database

# Load environment variables
load_dotenv()

# Initialize Database
database.init_db()

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants & Fallback Token
BOT_TOKEN = os.getenv("BOT_TOKEN") or "9136752920:AAGSZ7IhtJbeNNBfFdQGU-4aI6BDK2tgq9E"
DOWNLOADS_DIR = Path(__file__).parent / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# FFmpeg binary location provided by imageio-ffmpeg (or system ffmpeg if in cloud container)
try:
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = "ffmpeg"

# URL detection regex pattern
URL_REGEX = re.compile(r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)")

# Telegram HTTP Bot API hard limit for bot file uploads is 50MB
TELEGRAM_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Owner & Admin Config
ADMIN_USERNAME = (os.getenv("ADMIN_USERNAME") or "yqios").lower().lstrip("@")
ADMIN_ID = os.getenv("ADMIN_ID")  # Optional numeric ID in .env

# Contact Info
SUPPORT_TELEGRAM_USERNAME = "yqios"
SUPPORT_TELEGRAM_URL = "https://t.me/yqios"
SUPPORT_WHATSAPP_NUMBER = "+917015346487"
SUPPORT_WHATSAPP_URL = "https://wa.me/917015346487"


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler to satisfy Render/Railway/Koyeb 24/7 web service health checks."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram Video Downloader Bot is running 24/7!")

    def log_message(self, format, *args):
        return  # Silence logs for clean output


def start_health_server():
    """Runs HTTP server for Render/Railway/Koyeb 24/7 web service health checks."""
    port_str = os.getenv("PORT", "10000")
    try:
        port = int(port_str)
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"Health-check server running on 0.0.0.0:{port} for Cloud 24/7 Hosting")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
    except Exception as e:
        logger.warning(f"Could not start cloud health check server: {e}")


def is_admin(user) -> bool:
    """Checks if the user is authorized as bot admin."""
    if not user:
        return False
    
    # Check numeric ID from .env
    if ADMIN_ID and str(user.id) == str(ADMIN_ID).strip():
        return True

    # Check username against configured admin username (case-insensitive)
    if user.username:
        clean_user = user.username.lower().lstrip("@")
        clean_admin = ADMIN_USERNAME.lower().lstrip("@")
        if clean_user == clean_admin:
            database.set_setting("admin_id", str(user.id))
            return True

    # Check saved admin ID in database settings
    saved_admin_id = database.get_setting("admin_id")
    if saved_admin_id and str(user.id) == str(saved_admin_id).strip():
        return True

    return False


def get_contact_buttons() -> list:
    """Returns clean inline buttons for contact support."""
    return [
        [
            InlineKeyboardButton("💬 Telegram Support", url=SUPPORT_TELEGRAM_URL),
            InlineKeyboardButton("📱 WhatsApp Support", url=SUPPORT_WHATSAPP_URL),
        ]
    ]


def get_admin_dashboard_markup() -> InlineKeyboardMarkup:
    """Returns inline keyboard for the Admin Panel."""
    notify_val = database.get_setting("notify_admin", "1")
    notify_text = "🔔 Live Alerts: ON ✅" if notify_val == "1" else "🔕 Live Alerts: OFF ❌"

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin:refresh"),
            InlineKeyboardButton(notify_text, callback_data="admin:toggle_notify"),
        ],
        [
            InlineKeyboardButton("👥 Users List", callback_data="admin:users"),
            InlineKeyboardButton("📜 Download History", callback_data="admin:history"),
        ],
        [
            InlineKeyboardButton("📥 Download Database (.db)", callback_data="admin:backup"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_duration(seconds: int) -> str:
    """Formats duration seconds into human readable string (mm:ss or hh:mm:ss)."""
    if not seconds:
        return "N/A"
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours:d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def extract_media_info(url: str) -> dict:
    """Extracts metadata without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
            }
        },
    }
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if "entries" in info:
            info = info["entries"][0]
        
        # Determine direct URL if available
        direct_url = info.get("url")
        if not direct_url and "formats" in info:
            for f in reversed(info["formats"]):
                if f.get("url") and f.get("ext") in ["mp4", "m4a", "webm"]:
                    direct_url = f.get("url")
                    break

        return {
            "title": info.get("title", "Unknown Title"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
            "direct_url": direct_url or info.get("webpage_url"),
            "filesize_approx": info.get("filesize") or info.get("filesize_approx", 0),
        }


def download_media_sync(url: str, output_template: str, mode: str = "video") -> dict:
    """
    Downloads Video (MP4) or Audio (MP3) synchronously.
    Optimized for high-speed multi-fragment parallel downloading.
    """
    ydl_opts = {
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": FFMPEG_PATH,
        # High speed parallel downloading optimizations
        "concurrent_fragment_downloads": 8,
        "buffersize": 1024 * 1024,
        "retries": 10,
        "socket_timeout": 30,
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
            }
        },
    }
    if os.path.exists("cookies.txt"):
        ydl_opts["cookiefile"] = "cookies.txt"

    if mode == "audio":
        # Best audio converted to MP3 at 192kbps
        ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/ba/18/best"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        # High speed video format selection
        ydl_opts["format"] = (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "18/"
            "best[ext=mp4]/"
            "best"
        )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if "entries" in info:
            info = info["entries"][0]

        expected_filename = ydl.prepare_filename(info)

        if mode == "audio":
            expected_filename = os.path.splitext(expected_filename)[0] + ".mp3"

        if not os.path.exists(expected_filename):
            base = os.path.splitext(expected_filename)[0]
            matches = glob.glob(f"{base}.*")
            if matches:
                expected_filename = matches[0]

        return {
            "filepath": expected_filename if os.path.exists(expected_filename) else None,
            "title": info.get("title", "Media"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
            "direct_url": info.get("url") or info.get("webpage_url"),
        }


async def notify_admin_download(context: ContextTypes.DEFAULT_TYPE, user, title: str, mode: str, size_mb: float, url: str):
    """Sends real-time notification to Admin when someone downloads media."""
    try:
        if database.get_setting("notify_admin", "1") != "1":
            return

        admin_id = database.get_setting("admin_id") or ADMIN_ID
        if not admin_id:
            return

        format_label = "🎬 Video (MP4)" if mode == "video" else "🎵 Audio (MP3)"
        user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Anonymous"
        username_str = f"@{user.username}" if user.username else "N/A"

        alert_text = (
            "🔔 **New Download Alert!**\n\n"
            f"👤 **User:** {user_name}\n"
            f"🆔 **User ID:** `{user.id}`\n"
            f"🏷️ **Username:** {username_str}\n"
            f"📁 **Format:** {format_label}\n"
            f"📦 **Size:** {size_mb:.1f} MB\n"
            f"🎬 **Title:** {title}\n"
            f"🔗 **Link:** {url[:100]}"
        )

        await context.bot.send_message(
            chat_id=int(admin_id),
            text=alert_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    user = update.effective_user
    if user:
        database.add_or_update_user(user.id, user.first_name, user.last_name, user.username)
        if is_admin(user):
            database.set_setting("admin_id", str(user.id))

    user_is_admin = is_admin(user)

    if user_is_admin:
        welcome_text = (
            "👑 **Welcome Back, Boss (@yqios)!** ✨\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 **System Status:** Bot Live 24/7\n\n"
            "📥 **Supported Platforms:**\n"
            "• 🔴 **YouTube** (Videos & Shorts)\n"
            "• 📸 **Instagram** (Reels & Posts)\n"
            "• 🔵 **Facebook** (Videos & Watch)\n"
            "• 🐦 **Twitter (X)** (Videos)\n\n"
            "⚡ *Paste any link to download, or manage via Dashboard below!*"
        )
    else:
        welcome_text = (
            "✨ **Universal Media Downloader** 🚀\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ **Fast • High-Quality • 100% Free**\n\n"
            "📥 **Supported Platforms:**\n"
            "• 🔴 **YouTube** (Videos & Shorts)\n"
            "• 📸 **Instagram** (Reels & Posts)\n"
            "• 🔵 **Facebook** (Videos & Watch)\n"
            "• 🐦 **Twitter (X)** (Videos & Clips)\n\n"
            "🎬 **Video (MP4)** & 🎵 **Audio (MP3)** Supported!\n\n"
            "👉 **Send or paste any video link to start!**\n"
            "*(बस किसी भी वीडियो का लिंक यहाँ भेजें और तुरंत डाउनलोड करें)*"
        )

    # Base buttons list (Zero contact text in message body)
    keyboard = get_contact_buttons()

    # If the user is admin, insert the Dashboard button at the very top
    if user_is_admin:
        keyboard.insert(0, [InlineKeyboardButton("👑 Admin Dashboard", callback_data="admin:refresh")])

    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /admin command for bot owner."""
    user = update.effective_user
    if not is_admin(user):
        await update.message.reply_text("⛔ **This command is reserved for Bot Admin only.**")
        return

    # Cache admin id
    database.set_setting("admin_id", str(user.id))

    stats = database.get_stats()
    notify_val = database.get_setting("notify_admin", "1")
    notify_status = "ON ✅" if notify_val == "1" else "OFF ❌"

    text = (
        "👑 **Admin Control Dashboard**\n\n"
        f"📊 **Overall Stats:**\n"
        f"• 👥 **Total Users:** `{stats['total_users']}`\n"
        f"• ⬇️ **Total Downloads:** `{stats['total_downloads']}`\n"
        f"   ├ 🎬 Video (MP4): `{stats['video_downloads']}`\n"
        f"   └ 🎵 Audio (MP3): `{stats['audio_downloads']}`\n"
        f"• 📦 **Total Bandwidth:** `{stats['total_mb']:.1f} MB`\n\n"
        f"📅 **Today's Activity:**\n"
        f"• ⬇️ Downloads Today: `{stats['today_downloads']}`\n"
        f"• 👥 New Users Today: `{stats['today_new_users']}`\n\n"
        f"🔔 **Live Download Alerts:** `{notify_status}`\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 **Manage using the buttons below:**"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=get_admin_dashboard_markup()
    )


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline buttons inside the Admin Panel."""
    query = update.callback_query
    user = update.effective_user

    if not is_admin(user):
        await query.answer("⛔ Unauthorized", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == "admin:refresh":
        stats = database.get_stats()
        notify_val = database.get_setting("notify_admin", "1")
        notify_status = "ON ✅" if notify_val == "1" else "OFF ❌"

        text = (
            "👑 **Admin Control Dashboard**\n\n"
            f"📊 **Overall Stats:**\n"
            f"• 👥 **Total Users:** `{stats['total_users']}`\n"
            f"• ⬇️ **Total Downloads:** `{stats['total_downloads']}`\n"
            f"   ├ 🎬 Video (MP4): `{stats['video_downloads']}`\n"
            f"   └ 🎵 Audio (MP3): `{stats['audio_downloads']}`\n"
            f"• 📦 **Total Bandwidth:** `{stats['total_mb']:.1f} MB`\n\n"
            f"📅 **Today's Activity:**\n"
            f"• ⬇️ Downloads Today: `{stats['today_downloads']}`\n"
            f"• 👥 New Users Today: `{stats['today_new_users']}`\n\n"
            f"🔔 **Live Download Alerts:** `{notify_status}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👇 **Manage using the buttons below:**"
        )
        try:
            await query.edit_message_text(
                text,
                parse_mode="Markdown",
                reply_markup=get_admin_dashboard_markup()
            )
        except Exception:
            pass

    elif data == "admin:toggle_notify":
        current = database.get_setting("notify_admin", "1")
        new_val = "0" if current == "1" else "1"
        database.set_setting("notify_admin", new_val)
        status_str = "ON ✅" if new_val == "1" else "OFF ❌"
        await query.answer(f"Live Alerts: {status_str}", show_alert=True)

        stats = database.get_stats()
        text = (
            "👑 **Admin Control Dashboard**\n\n"
            f"📊 **Overall Stats:**\n"
            f"• 👥 **Total Users:** `{stats['total_users']}`\n"
            f"• ⬇️ **Total Downloads:** `{stats['total_downloads']}`\n"
            f"   ├ 🎬 Video (MP4): `{stats['video_downloads']}`\n"
            f"   └ 🎵 Audio (MP3): `{stats['audio_downloads']}`\n"
            f"• 📦 **Total Bandwidth:** `{stats['total_mb']:.1f} MB`\n\n"
            f"📅 **Today's Activity:**\n"
            f"• ⬇️ Downloads Today: `{stats['today_downloads']}`\n"
            f"• 👥 New Users Today: `{stats['today_new_users']}`\n\n"
            f"🔔 **Live Download Alerts:** `{status_str}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👇 **Manage using the buttons below:**"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_dashboard_markup()
        )

    elif data == "admin:users":
        users = database.get_recent_users(limit=10)
        if not users:
            text = "👥 **Recent Users:** No user records found yet."
        else:
            text = "👥 **Recent Active Users:**\n\n"
            for idx, u in enumerate(users, 1):
                name = u["first_name"] or "User"
                username = f"@{u['username']}" if u["username"] else "N/A"
                text += f"{idx}. **{name}** ({username})\n   • ID: `{u['user_id']}` | Downloads: `{u['download_count']}`\n"

        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin:refresh")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_markup)

    elif data == "admin:history":
        downloads = database.get_recent_downloads(limit=10)
        if not downloads:
            text = "📜 **Download History:** No downloads recorded yet."
        else:
            text = "📜 **Recent Downloads:**\n\n"
            for idx, d in enumerate(downloads, 1):
                u_name = d["first_name"] or "User"
                u_handle = f"@{d['username']}" if d["username"] else f"ID:{d['user_id']}"
                type_icon = "🎬" if d["media_type"] == "video" else "🎵"
                title_short = (d["title"][:28] + "...") if d["title"] and len(d["title"]) > 28 else (d["title"] or "Media")
                text += (
                    f"{idx}. {type_icon} **{title_short}**\n"
                    f"   👤 {u_name} ({u_handle}) | {d['filesize_mb']} MB\n"
                    f"   🕒 `{d['created_at']}`\n\n"
                )

        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin:refresh")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_markup)

    elif data == "admin:backup":
        db_file = database.DB_PATH
        if db_file.exists():
            await context.bot.send_document(
                chat_id=user.id,
                document=open(db_file, "rb"),
                caption="📥 **Bot Database Backup (.db)**"
            )
            await query.answer("Database file sent!", show_alert=True)
        else:
            await query.answer("Database file not found.", show_alert=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command."""
    help_text = (
        "ℹ️ **Help & FAQ**\n\n"
        "1️⃣ **How to download?**\n"
        "Send any video link ➔ Choose **Video (MP4)** or **Audio (MP3)**.\n\n"
        "2️⃣ **Supported Platforms:**\n"
        "YouTube (Videos & Shorts), Instagram (Reels & Posts), Facebook, and Twitter/X.\n\n"
        "3️⃣ **Large Files (> 50MB):**\n"
        "For files larger than 50MB, the bot provides an instant **High-Speed Direct Download** button.\n\n"
        "4️⃣ **Support:**\n"
        "Use the buttons below to contact support directly."
    )
    await update.message.reply_text(
        help_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(get_contact_buttons()),
        disable_web_page_preview=True
    )


async def handle_incoming_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Extracts URL and asks user to choose between Video (MP4) or Audio (MP3)."""
    user = update.effective_user
    if user:
        database.add_or_update_user(user.id, user.first_name, user.last_name, user.username)

    text = update.message.text
    if not text:
        return

    urls = URL_REGEX.findall(text)
    if not urls:
        await update.message.reply_text(
            "⚠️ Please send a valid video link (YouTube, Instagram, Facebook, etc.).",
            reply_markup=InlineKeyboardMarkup(get_contact_buttons())
        )
        return

    target_url = urls[0]
    status_msg = await update.message.reply_text("🔍 Fetching media details...")

    try:
        media_info = await asyncio.to_thread(extract_media_info, target_url)
        title = media_info.get("title", "Video")
        duration_str = format_duration(media_info.get("duration", 0))
        uploader = media_info.get("uploader", "Unknown")

        req_id = str(uuid.uuid4())[:8]
        if "pending_requests" not in context.bot_data:
            context.bot_data["pending_requests"] = {}

        context.bot_data["pending_requests"][req_id] = {
            "url": target_url,
            "title": title,
            "duration": media_info.get("duration", 0),
            "uploader": uploader,
            "direct_url": media_info.get("direct_url"),
        }

        keyboard = [
            [
                InlineKeyboardButton("🎬 Video (MP4)", callback_data=f"dl:video:{req_id}"),
                InlineKeyboardButton("🎵 Audio (MP3)", callback_data=f"dl:audio:{req_id}"),
            ],
            [
                InlineKeyboardButton("💬 Telegram Support", url=SUPPORT_TELEGRAM_URL),
                InlineKeyboardButton("📱 WhatsApp Support", url=SUPPORT_WHATSAPP_URL),
            ]
        ]

        caption_text = (
            f"🎬 **{title}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ **Duration:** `{duration_str}`  •  👤 **Uploader:** `{uploader}`\n\n"
            "👇 **Choose download format:**"
        )

        await status_msg.edit_text(
            caption_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.exception("Error extracting media info")
        await status_msg.edit_text(
            f"❌ Unable to process link: {str(e)[:150]}\n\nPlease check if the link is public and accessible.",
            reply_markup=InlineKeyboardMarkup(get_contact_buttons())
        )


async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the Video (MP4) or Audio (MP3) button clicks."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if user:
        database.add_or_update_user(user.id, user.first_name, user.last_name, user.username)

    data = query.data
    if not data or not data.startswith("dl:"):
        return

    parts = data.split(":")
    if len(parts) != 3:
        return

    mode = parts[1]  # 'video' or 'audio'
    req_id = parts[2]

    pending = context.bot_data.get("pending_requests", {}).get(req_id)
    if not pending:
        await query.edit_message_text(
            "⚠️ Request expired. Please send the link again.",
            reply_markup=InlineKeyboardMarkup(get_contact_buttons())
        )
        return

    target_url = pending["url"]
    title = pending["title"]
    duration = pending["duration"]
    uploader = pending["uploader"]
    direct_url = pending.get("direct_url")

    chat_id = update.effective_chat.id
    mode_label = "🎬 Video (MP4)" if mode == "video" else "🎵 Audio (MP3)"
    await query.edit_message_text(f"⏳ Downloading {mode_label}... Please wait...")

    output_template = str(DOWNLOADS_DIR / f"{chat_id}_{req_id}_%(id)s.%(ext)s")
    downloaded_file = None

    try:
        if mode == "audio":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        else:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VIDEO)

        result = await asyncio.to_thread(download_media_sync, target_url, output_template, mode=mode)
        downloaded_file = result.get("filepath")
        direct_url = result.get("direct_url") or direct_url

        if downloaded_file and os.path.exists(downloaded_file):
            file_size = os.path.getsize(downloaded_file)
            size_mb = file_size / (1024 * 1024)

            # Log to Database
            database.log_download(user.id, target_url, title, mode, size_mb)

            # Real-time alert to Admin
            asyncio.create_task(notify_admin_download(context, user, title, mode, size_mb, target_url))

            # Check 50MB Telegram limit
            if file_size <= TELEGRAM_MAX_UPLOAD_BYTES:
                await query.edit_message_text(f"📤 Uploading {mode_label} ({size_mb:.1f} MB)...")

                if mode == "audio":
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
                    caption = (
                        f"🎵 **{title}**\n"
                        f"👤 Artist: {uploader}\n"
                        f"📦 Size: {size_mb:.1f} MB"
                    )
                    with open(downloaded_file, "rb") as audio_fp:
                        await query.message.reply_audio(
                            audio=audio_fp,
                            caption=caption,
                            title=title,
                            performer=uploader,
                            duration=int(duration) if duration else None,
                            read_timeout=300,
                            write_timeout=300,
                            connect_timeout=60,
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(get_contact_buttons())
                        )
                else:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                    caption = (
                        f"🎬 **{title}**\n"
                        f"👤 Source: {uploader}\n"
                        f"📦 Size: {size_mb:.1f} MB"
                    )
                    with open(downloaded_file, "rb") as video_fp:
                        await query.message.reply_video(
                            video=video_fp,
                            caption=caption,
                            supports_streaming=True,
                            read_timeout=300,
                            write_timeout=300,
                            connect_timeout=60,
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(get_contact_buttons())
                        )

                await query.delete_message()
                return

            else:
                # File > 50MB: Provide instant high-speed direct download button
                buttons = []
                if direct_url:
                    buttons.append([InlineKeyboardButton(f"⚡ Fast Direct Download ({size_mb:.1f} MB)", url=direct_url)])
                buttons.append([
                    InlineKeyboardButton("💬 Telegram Support", url=SUPPORT_TELEGRAM_URL),
                    InlineKeyboardButton("📱 WhatsApp Support", url=SUPPORT_WHATSAPP_URL)
                ])

                await query.edit_message_text(
                    f"🎬 **{title}**\n\n"
                    f"📦 **Size:** {size_mb:.1f} MB (High Quality)\n\n"
                    "⚡ *File exceeds Telegram's 50MB upload limit. Tap below to download in Full HD at maximum speed:*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    disable_web_page_preview=True
                )
                return

        else:
            # Fallback direct button
            buttons = []
            if direct_url:
                buttons.append([InlineKeyboardButton("⚡ Fast Direct Download", url=direct_url)])
            buttons.append([
                InlineKeyboardButton("💬 Telegram Support", url=SUPPORT_TELEGRAM_URL),
                InlineKeyboardButton("📱 WhatsApp Support", url=SUPPORT_WHATSAPP_URL)
            ])
            await query.edit_message_text(
                f"🎬 **{title}**\n\n"
                "Tap below to download directly:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

    except Exception as e:
        logger.exception("Error processing download callback")
        await query.edit_message_text(
            f"❌ Download failed: {str(e)[:150]}\n\nPlease verify the link is working.",
            reply_markup=InlineKeyboardMarkup(get_contact_buttons())
        )

    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
                logger.info(f"Cleaned up file: {downloaded_file}")
            except Exception as e:
                logger.error(f"Error deleting file {downloaded_file}: {e}")

        base_pattern = str(DOWNLOADS_DIR / f"{chat_id}_{req_id}_*")
        for leftover in glob.glob(base_pattern):
            try:
                os.remove(leftover)
            except Exception:
                pass


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs unhandled exceptions and notifies the user."""
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ A temporary error occurred. Please try again in a few moments."
            )
        except Exception:
            pass


def main():
    """Main entrypoint to run the Telegram bot."""
    print("🤖 Telegram Video & Audio (MP3) Downloader Bot starting...")

    # Start Cloud 24/7 Health-check server on port 10000
    start_health_server()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(handle_download_callback, pattern=r"^dl:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incoming_link))

    # Global Error Handler
    app.add_error_handler(global_error_handler)

    print("✅ Bot is actively running! (Polling mode)")
    print(f"👑 Admin Username: @{ADMIN_USERNAME}")
    app.run_polling()


if __name__ == "__main__":
    main()

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
from pathlib import Path
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

# Constants
BOT_TOKEN = os.getenv("BOT_TOKEN")
DOWNLOADS_DIR = Path(__file__).parent / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

# FFmpeg binary location provided by imageio-ffmpeg
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

# URL detection regex pattern
URL_REGEX = re.compile(r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)")

# Telegram HTTP Bot API hard limit for bot file uploads is 50MB
TELEGRAM_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Owner & Admin Config
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "yqios").lower().lstrip("@")
ADMIN_ID = os.getenv("ADMIN_ID")  # Optional numeric ID in .env

# Contact Info
SUPPORT_TELEGRAM_USERNAME = "yqios"
SUPPORT_TELEGRAM_URL = "https://t.me/yqios"
SUPPORT_WHATSAPP_NUMBER = "+917015346487"
SUPPORT_WHATSAPP_URL = "https://wa.me/917015346487"


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
            # Store numeric ID in database for future fast check
            database.set_setting("admin_id", str(user.id))
            return True

    # Check saved admin ID in database settings
    saved_admin_id = database.get_setting("admin_id")
    if saved_admin_id and str(user.id) == str(saved_admin_id).strip():
        return True

    return False


def get_contact_buttons() -> list:
    """Returns a list of inline buttons for contact."""
    return [
        [
            InlineKeyboardButton("💬 Telegram (@yqios)", url=SUPPORT_TELEGRAM_URL),
            InlineKeyboardButton("📱 WhatsApp (+917015346487)", url=SUPPORT_WHATSAPP_URL),
        ]
    ]


def get_admin_dashboard_markup() -> InlineKeyboardMarkup:
    """Returns inline keyboard for the Admin Panel."""
    notify_val = database.get_setting("notify_admin", "1")
    notify_text = "🔔 लाइव अलर्ट: ON ✅" if notify_val == "1" else "🔕 लाइव अलर्ट: OFF ❌"

    keyboard = [
        [
            InlineKeyboardButton("🔄 रिफ्रेश आँकड़े", callback_data="admin:refresh"),
            InlineKeyboardButton(notify_text, callback_data="admin:toggle_notify"),
        ],
        [
            InlineKeyboardButton("👥 यूज़र्स लिस्ट", callback_data="admin:users"),
            InlineKeyboardButton("📜 डाउनलोड हिस्ट्री", callback_data="admin:history"),
        ],
        [
            InlineKeyboardButton("📥 डेटाबेस फ़ाइल (.db)", callback_data="admin:backup"),
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
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return {
            "title": info.get("title", "Unknown Title"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
            "direct_url": info.get("url") or info.get("webpage_url"),
        }


def download_media_sync(url: str, output_template: str, mode: str = "video") -> dict:
    """
    Downloads Video (MP4) or Audio (MP3) synchronously.
    Uses FFmpeg for conversions.
    """
    ydl_opts = {
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": FFMPEG_PATH,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        },
    }

    if mode == "audio":
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        ydl_opts["format"] = (
            "best[filesize<48M][ext=mp4]/"
            "bestvideo[filesize<40M][ext=mp4]+bestaudio[filesize<8M]/"
            "best[height<=720][filesize<48M]/"
            "best[height<=480]/"
            "best[height<=360]/"
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
        username_str = f"@{user.username}" if user.username else "उपलब्ध नहीं"

        alert_text = (
            "🔔 **नया डाउनलोड अलर्ट!**\n\n"
            f"👤 **यूज़र:** {user_name}\n"
            f"🆔 **User ID:** `{user.id}`\n"
            f"🏷️ **यूज़रनेम:** {username_str}\n"
            f"📁 **फ़ॉर्मेट:** {format_label}\n"
            f"📦 **साइज़:** {size_mb:.1f} MB\n"
            f"🎬 **टाइटल:** {title}\n"
            f"🔗 **लिंक:** {url[:100]}"
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
        welcome_header = (
            "👑 **नमस्ते एडमिन (@yqios)! आपका स्वागत है।**\n"
            "आप बॉट के मुख्य व्यवस्थापक (Owner) हैं। आप नीचे दिए गए बटन पर क्लिक करके या `/admin` कमांड भेजकर पूरा **कंट्रोल डैशबोर्ड** देख सकते हैं।\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
        )
    else:
        welcome_header = ""

    welcome_text = (
        f"{welcome_header}"
        "👋 **नमस्ते! All-in-One Video & MP3 Downloader Bot में आपका स्वागत है!**\n\n"
        "आप मुझे निम्न प्लेटफ़ॉर्म के लिंक भेज सकते हैं:\n"
        "▶️ **YouTube** (Videos, Shorts & Music)\n"
        "📸 **Instagram** (Reels & Videos)\n"
        "👥 **Facebook** (Reels & Watch Videos)\n"
        "🐦 **Twitter / X**\n\n"
        "📌 **इस्तेमाल कैसे करें:**\n"
        "1. किसी भी वीडियो का लिंक कॉपी करके यहाँ भेजें।\n"
        "2. फिर चुनें कि आपको **🎬 Video (MP4)** चाहिए या **🎵 Audio (MP3)**!\n\n"
        "📦 **50MB+ वीडियो:** बड़ी वीडियो के लिए 1-क्लिक डायरेक्ट डाउनलोड लिंक भी उपलब्ध रहता है।\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📞 **संपर्क एवं सहायता (Contact & Support):**\n"
        f"💬 **Telegram:** [@{SUPPORT_TELEGRAM_USERNAME}]({SUPPORT_TELEGRAM_URL})\n"
        f"📱 **WhatsApp:** [{SUPPORT_WHATSAPP_NUMBER}]({SUPPORT_WHATSAPP_URL})"
    )

    # Base buttons list (pure list of lists)
    keyboard = get_contact_buttons()

    # If the user is admin, insert the Dashboard button at the very top!
    if user_is_admin:
        keyboard.insert(0, [InlineKeyboardButton("👑 एडमिन कंट्रोल डैशबोर्ड", callback_data="admin:refresh")])

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
        await update.message.reply_text("⛔ **यह कमांड केवल बॉट एडमिन के लिए आरक्षित है।**")
        return

    # Cache admin id
    database.set_setting("admin_id", str(user.id))

    stats = database.get_stats()
    notify_val = database.get_setting("notify_admin", "1")
    notify_status = "चालू (ON) ✅" if notify_val == "1" else "बंद (OFF) ❌"

    text = (
        "👑 **एडमिन कंट्रोल डैशबोर्ड (Admin Panel)**\n\n"
        f"📊 **समग्र आँकड़े (Overall Stats):**\n"
        f"• 👥 **कुल यूज़र्स:** `{stats['total_users']}`\n"
        f"• ⬇️ **कुल डाउनलोड्स:** `{stats['total_downloads']}`\n"
        f"   ├ 🎬 वीडियो (MP4): `{stats['video_downloads']}`\n"
        f"   └ 🎵 ऑडियो (MP3): `{stats['audio_downloads']}`\n"
        f"• 📦 **कुल डेटा ट्रांसफर:** `{stats['total_mb']:.1f} MB`\n\n"
        f"📅 **आज की गतिविधि (Today):**\n"
        f"• ⬇️ आज के डाउनलोड्स: `{stats['today_downloads']}`\n"
        f"• 👥 आज के नए यूज़र्स: `{stats['today_new_users']}`\n\n"
        f"🔔 **रियल-टाइम डाउनलोड अलर्ट:** {notify_status}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 **नीचे दिए गए बटन्स से विवरण देखें या सेटिंग्स बदलें:**"
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
        await query.answer("⛔ अनधिकृत (Unauthorized)", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == "admin:refresh":
        stats = database.get_stats()
        notify_val = database.get_setting("notify_admin", "1")
        notify_status = "चालू (ON) ✅" if notify_val == "1" else "बंद (OFF) ❌"

        text = (
            "👑 **एडमिन कंट्रोल डैशबोर्ड (Admin Panel)**\n\n"
            f"📊 **समग्र आँकड़े (Overall Stats):**\n"
            f"• 👥 **कुल यूज़र्स:** `{stats['total_users']}`\n"
            f"• ⬇️ **कुल डाउनलोड्स:** `{stats['total_downloads']}`\n"
            f"   ├ 🎬 वीडियो (MP4): `{stats['video_downloads']}`\n"
            f"   └ 🎵 ऑडियो (MP3): `{stats['audio_downloads']}`\n"
            f"• 📦 **कुल डेटा ट्रांसफर:** `{stats['total_mb']:.1f} MB`\n\n"
            f"📅 **आज की गतिविधि (Today):**\n"
            f"• ⬇️ आज के डाउनलोड्स: `{stats['today_downloads']}`\n"
            f"• 👥 आज के नए यूज़र्स: `{stats['today_new_users']}`\n\n"
            f"🔔 **रियल-टाइम डाउनलोड अलर्ट:** {notify_status}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👇 **नीचे दिए गए बटन्स से विवरण देखें या सेटिंग्स बदलें:**"
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
        status_str = "चालू (ON)" if new_val == "1" else "बंद (OFF)"
        await query.answer(f"🔔 रियल-टाइम अलर्ट: {status_str}", show_alert=True)

        stats = database.get_stats()
        notify_status = "चालू (ON) ✅" if new_val == "1" else "बंद (OFF) ❌"
        text = (
            "👑 **एडमिन कंट्रोल डैशबोर्ड (Admin Panel)**\n\n"
            f"📊 **समग्र आँकड़े (Overall Stats):**\n"
            f"• 👥 **कुल यूज़र्स:** `{stats['total_users']}`\n"
            f"• ⬇️ **कुल डाउनलोड्स:** `{stats['total_downloads']}`\n"
            f"   ├ 🎬 वीडियो (MP4): `{stats['video_downloads']}`\n"
            f"   └ 🎵 ऑडियो (MP3): `{stats['audio_downloads']}`\n"
            f"• 📦 **कुल डेटा ट्रांसफर:** `{stats['total_mb']:.1f} MB`\n\n"
            f"📅 **आज की गतिविधि (Today):**\n"
            f"• ⬇️ आज के डाउनलोड्स: `{stats['today_downloads']}`\n"
            f"• 👥 आज के नए यूज़र्स: `{stats['today_new_users']}`\n\n"
            f"🔔 **रियल-टाइम डाउनलोड अलर्ट:** {notify_status}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👇 **नीचे दिए गए बटन्स से विवरण देखें या सेटिंग्स बदलें:**"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_admin_dashboard_markup()
        )

    elif data == "admin:users":
        users = database.get_recent_users(limit=10)
        if not users:
            text = "👥 **हालिया यूज़र्स:** अभी तक कोई यूज़र रिकॉर्ड नहीं है।"
        else:
            text = "👥 **हालिया सक्रिय यूज़र्स (Recent Active Users):**\n\n"
            for idx, u in enumerate(users, 1):
                name = u["first_name"] or "User"
                username = f"@{u['username']}" if u["username"] else "N/A"
                text += f"{idx}. **{name}** ({username})\n   • ID: `{u['user_id']}` | डाउनलोड्स: `{u['download_count']}`\n"

        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 वापस डैशबोर्ड", callback_data="admin:refresh")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_markup)

    elif data == "admin:history":
        downloads = database.get_recent_downloads(limit=10)
        if not downloads:
            text = "📜 **डाउनलोड हिस्ट्री:** अभी तक कोई डाउनलोड नहीं हुआ है।"
        else:
            text = "📜 **हालिया डाउनलोड रिकॉर्ड्स (Recent Downloads):**\n\n"
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

        back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 वापस डैशबोर्ड", callback_data="admin:refresh")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_markup)

    elif data == "admin:backup":
        db_file = database.DB_PATH
        if db_file.exists():
            await context.bot.send_document(
                chat_id=user.id,
                document=open(db_file, "rb"),
                caption="📥 **बॉट डेटाबेस बैकअप (.db)**\nइस फ़ाइल में आपके सभी यूज़र्स और डाउनलोड रिकॉर्ड्स सुरक्षित हैं।"
            )
            await query.answer("डेटाबेस फ़ाइल भेज दी गई है!", show_alert=True)
        else:
            await query.answer("डेटाबेस फ़ाइल अभी उपलब्ध नहीं है।", show_alert=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command."""
    help_text = (
        "ℹ️ **मदद और अक्सर पूछे जाने वाले सवाल (Help & FAQ)**\n\n"
        "1️⃣ **वीडियो या MP3 डाउनलोड कैसे करें?**\n"
        "लिंक भेजें -> फिर 'Video (MP4)' या 'Audio (MP3)' बटन पर क्लिक करें।\n\n"
        "2️⃣ **50MB से बड़ी वीडियो का क्या होगा?**\n"
        "टेलीग्राम बॉट सीधे 50MB तक की वीडियो भेज सकता है। उससे बड़ी वीडियो के लिए बॉट आपको डायरेक्ट 1-Click डाउनलोड लिंक देता है।\n\n"
        "3️⃣ **सपोर्ट व संपर्क:**\n"
        f"• Telegram: [@{SUPPORT_TELEGRAM_USERNAME}]({SUPPORT_TELEGRAM_URL})\n"
        f"• WhatsApp: [{SUPPORT_WHATSAPP_NUMBER}]({SUPPORT_WHATSAPP_URL})"
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
            "⚠️ कृपया एक मान्य वीडियो लिंक भेजें (YouTube, Instagram, Facebook आदि)।\n"
            f"सहायता के लिए संपर्क करें: @{SUPPORT_TELEGRAM_USERNAME}"
        )
        return

    target_url = urls[0]
    status_msg = await update.message.reply_text("🔍 वीडियो की जानकारी जांची जा रही है...")

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
                InlineKeyboardButton("💬 Telegram (@yqios)", url=SUPPORT_TELEGRAM_URL),
                InlineKeyboardButton("📱 WhatsApp", url=SUPPORT_WHATSAPP_URL),
            ]
        ]

        caption_text = (
            f"🎬 **{title}**\n\n"
            f"⏱️ **अवधि (Duration):** {duration_str}\n"
            f"👤 **चैनल / सोर्स:** {uploader}\n\n"
            "👇 **कृपया चुनें कि आप किस फ़ॉर्मेट में डाउनलोड करना चाहते हैं:**"
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
            f"❌ वीडियो की जानकारी लोड नहीं हो सकी: {str(e)[:150]}\n\n"
            f"सहायता के लिए संपर्क करें: @{SUPPORT_TELEGRAM_USERNAME}",
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
            "⚠️ इस लिंक का समय समाप्त हो गया है। कृपया दोबारा लिंक भेजें।",
            reply_markup=InlineKeyboardMarkup(get_contact_buttons())
        )
        return

    target_url = pending["url"]
    title = pending["title"]
    duration = pending["duration"]
    uploader = pending["uploader"]
    direct_url = pending.get("direct_url")

    chat_id = update.effective_chat.id
    mode_label = "🎬 वीडियो" if mode == "video" else "🎵 MP3 ऑडियो"
    await query.edit_message_text(f"⏳ {mode_label} डाउनलोड और प्रोसेस हो रहा है, कृपया प्रतीक्षा करें...")

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

            # Check 50MB limit
            if file_size <= TELEGRAM_MAX_UPLOAD_BYTES:
                await query.edit_message_text(f"📤 {mode_label} ({size_mb:.1f} MB) भेजा जा रहा है...")

                if mode == "audio":
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VOICE)
                    caption = (
                        f"🎵 **{title}**\n"
                        f"👤 Artist: {uploader}\n"
                        f"📦 Size: {size_mb:.1f} MB\n\n"
                        f"💬 Support: [@{SUPPORT_TELEGRAM_USERNAME}]({SUPPORT_TELEGRAM_URL}) | WhatsApp: {SUPPORT_WHATSAPP_NUMBER}"
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
                        f"📦 Size: {size_mb:.1f} MB\n\n"
                        f"💬 Support: [@{SUPPORT_TELEGRAM_USERNAME}]({SUPPORT_TELEGRAM_URL}) | WhatsApp: {SUPPORT_WHATSAPP_NUMBER}"
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
                # File > 50MB
                buttons = []
                if direct_url:
                    buttons.append([InlineKeyboardButton("⬇️ डायरेक्ट डाउनलोड लिंक (हाई स्पीड)", url=direct_url)])
                buttons.append([
                    InlineKeyboardButton("💬 Telegram (@yqios)", url=SUPPORT_TELEGRAM_URL),
                    InlineKeyboardButton("📱 WhatsApp", url=SUPPORT_WHATSAPP_URL)
                ])

                await query.edit_message_text(
                    f"🎬 **{title}**\n\n"
                    f"📦 **साइज़:** {size_mb:.1f} MB (50MB से बड़ा)\n"
                    "ℹ️ *टेलीग्राम बॉट सीधे 50MB से बड़ी फ़ाइल नहीं भेज सकता। कृपया नीचे दिए गए डायरेक्ट लिंक से इसे तुरंत डाउनलोड करें:* 👇",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    disable_web_page_preview=True
                )
                return

        else:
            # Fallback direct button
            buttons = []
            if direct_url:
                buttons.append([InlineKeyboardButton("⬇️ डायरेक्ट डाउनलोड लिंक", url=direct_url)])
            buttons.append([
                InlineKeyboardButton("💬 Telegram (@yqios)", url=SUPPORT_TELEGRAM_URL),
                InlineKeyboardButton("📱 WhatsApp", url=SUPPORT_WHATSAPP_URL)
            ])
            await query.edit_message_text(
                f"🎬 **{title}**\n\n"
                "नीचे दिए गए बटन पर क्लिक करके सीधे डाउनलोड करें:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

    except Exception as e:
        logger.exception("Error processing download callback")
        await query.edit_message_text(
            f"❌ डाउनलोड करने में समस्या आई: {str(e)[:150]}\n\n"
            f"मदद के लिए संपर्क करें: @{SUPPORT_TELEGRAM_USERNAME}",
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
                "⚠️ कुछ तकनीकी समस्या आई है। कृपया दोबारा प्रयास करें या एडमिन से संपर्क करें: @yqios"
            )
        except Exception:
            pass


def main():
    """Main entrypoint to run the Telegram bot."""
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("\n" + "=" * 60)
        print("❌ ERROR: BOT_TOKEN नहीं मिला!")
        print("कृपया .env फ़ाइल में अपना टेलीग्राम बॉट टोकन दर्ज करें।")
        print("=" * 60 + "\n")
        sys.exit(1)

    print("🤖 Telegram Video & Audio (MP3) Downloader Bot शुरू हो रहा है...")

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

    print("✅ बॉट सफलतापूर्वक चल रहा है! (पॉलिंग मोड में)")
    print(f"👑 Admin Username: @{ADMIN_USERNAME}")
    print(f"📞 Contact Support: Telegram @{SUPPORT_TELEGRAM_USERNAME} | WhatsApp: {SUPPORT_WHATSAPP_NUMBER}")
    app.run_polling()


if __name__ == "__main__":
    main()

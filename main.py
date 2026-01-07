import os
import logging
import shutil
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
import instaloader
import aiohttp
from pyquery import PyQuery as pq
import requests
import json
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

# إعدادات من متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# Константы
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_REQUESTS_PER_MINUTE = 5  # Ограничение на 5 запросов в минуту

# Словарь для отслеживания запросов
user_requests = {}

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Проверка размера файла
def check_file_size(file_path: str) -> bool:
    file_size = os.path.getsize(file_path)
    return file_size <= MAX_FILE_SIZE

# وظيفة تنظيف الملفات والمجلدات
def cleanup_user_files(user_id: int):
    """حذف جميع الملفات والمجلدات الخاصة بالمستخدم"""
    user_folder = f"media_{user_id}"
    if os.path.exists(user_folder):
        try:
            shutil.rmtree(user_folder)
            logging.info(f"Cleaned up files for user {user_id}")
        except Exception as e:
            logging.error(f"Error cleaning up files for user {user_id}: {e}")

# وظيفة تحديد هاشتاج المنصة
def get_platform_hashtag(platform: str) -> str:
    """إرجاع الهاشتاج المناسب للمنصة"""
    hashtags = {
        "Instagram": "#instagram",
        "Instagram Stories": "#instagram", 
        "Instagram Highlights": "#instagram",
        "YouTube": "#youtube",
        "TikTok": "#tiktok",
        "Facebook": "#facebook",
        "Pinterest Video": "#pinterest",
        "Pinterest Image": "#pinterest"
    }
    return hashtags.get(platform, "#unknown")

# وظيفة إرسال الفيديو للقناة مع المعلومات المبسطة
async def send_to_channel(context, file_path: str, original_url: str, platform: str):
    """إرسال الفيديو للقناة مع معلومات مبسطة"""
    if not CHANNEL_ID:
        logging.warning("CHANNEL_ID not set, skipping channel upload")
        return
    
    try:
        # الحصول على هاشتاج المنصة
        platform_hashtag = get_platform_hashtag(platform)
        
        # تحضير النص المصاحب المبسط
        caption = f"{original_url}\n{platform_hashtag}"
        
        # إرسال الفيديو للقناة
        with open(file_path, "rb") as video_file:
            if file_path.endswith('.mp4'):
                await context.bot.send_video(
                    chat_id=CHANNEL_ID,
                    video=video_file,
                    caption=caption
                )
            else:
                await context.bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=video_file,
                    caption=caption
                )
        logging.info(f"Media sent to channel {CHANNEL_ID}")
    except Exception as e:
        logging.error(f"Error sending media to channel: {e}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "مرحبًا! أنا بوت لتحميل الوسائط من Instagram و YouTube و TikTok و Facebook و Pinterest.\n"
        "فقط أرسل لي رابط منشور أو فيديو أو Stories.\n"
        "⚠️ الحد الأقصى لحجم الملف للتحميل: 50 ميجابايت.\n"
        "🗑️ جميع الملفات يتم حذفها تلقائياً بعد الإرسال للحفاظ على الخصوصية."
    )
    await update.message.reply_text(welcome_message)

# Обработчик сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    url = update.message.text
    original_message_id = update.message.message_id  # حفظ معرف الرسالة الأصلية
    output_path = f"media_{user_id}"

    # إنشاء مجلد مؤقت للمستخدم
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    # Проверка ограничения запросов
    now = datetime.now()
    if user_id in user_requests:
        user_requests[user_id] = [req for req in user_requests[user_id] if now - req < timedelta(minutes=1)]
        if len(user_requests[user_id]) >= MAX_REQUESTS_PER_MINUTE:
            await update.message.reply_text(
                "لقد تجاوزت حد 5 تحميلات في الدقيقة. يرجى الانتظار.",
                reply_to_message_id=original_message_id
            )
            cleanup_user_files(user_id)
            return
        user_requests[user_id].append(now)
    else:
        user_requests[user_id] = [now]

    # Если ссылка сокращённая (pin.it), преобразуем её в полный URL
    if url.startswith("https://pin.it/"):
        expanded_url = expand_short_url(url)
        if expanded_url:
            url = expanded_url
        else:
            await update.message.reply_text(
                "فشل في توسيع الرابط المختصر.",
                reply_to_message_id=original_message_id
            )
            cleanup_user_files(user_id)
            return

    try:
        result = None
        platform = None
        video_info = {}
        
        if "instagram.com" in url:
            if "/stories/" in url:
                username = url.split("/stories/")[1].split("/")[0]
                result = download_instagram_stories(username, output_path)
                platform = "Instagram Stories"
            elif "/reel/" in url or "/p/" in url:
                result, video_info = download_instagram_media(url, output_path)
                platform = "Instagram"
            elif "/highlights/" in url:
                username = url.split("/highlights/")[1].split("/")[0]
                result = download_instagram_highlights(username, output_path)
                platform = "Instagram Highlights"
            else:
                result = "رابط Instagram غير مدعوم."
                platform = None
        elif "youtube.com" in url or "youtu.be" in url:
            result, video_info = download_youtube_video(url, output_path)
            platform = "YouTube"
        elif "tiktok.com" in url:
            result, video_info = download_tiktok_video(url, output_path)
            platform = "TikTok"
        elif "facebook.com" in url:
            result, video_info = download_facebook_video(url, output_path)
            platform = "Facebook"
        elif "pinterest.com" in url:
            download_url = await get_download_url(url)
            if download_url:
                if '.mp4' in download_url:
                    result = await download_video(download_url, output_path)
                    platform = "Pinterest Video"
                else:
                    result = await download_image(download_url, output_path)
                    platform = "Pinterest Image"
            else:
                result = "فشل في الحصول على رابط التحميل من Pinterest."
                platform = None
        else:
            result = "منصة غير مدعومة. يرجى تقديم رابط صحيح."
            platform = None

        if result and os.path.exists(result) and os.path.isfile(result):
            if check_file_size(result):
                with open(result, "rb") as file:
                    if result.endswith('.mp4'):
                        # إرسال الفيديو كرد على الرسالة الأصلية
                        await update.message.reply_video(
                            file, 
                            reply_to_message_id=original_message_id
                        )
                        # إرسال الفيديو للقناة مع المعلومات المبسطة
                        if platform:
                            await send_to_channel(context, result, update.message.text, platform)
                    else:
                        # إرسال الصورة كرد على الرسالة الأصلية
                        await update.message.reply_photo(
                            file,
                            reply_to_message_id=original_message_id
                        )
                        # إرسال الصورة للقناة مع المعلومات المبسطة
                        if platform:
                            await send_to_channel(context, result, update.message.text, platform)
            else:
                await update.message.reply_text(
                    "حجم الملف يتجاوز حد 50 ميجابايت.",
                    reply_to_message_id=original_message_id
                )
        else:
            await update.message.reply_text(
                result if isinstance(result, str) else "حدث خطأ أثناء التحميل.",
                reply_to_message_id=original_message_id
            )

    except Exception as e:
        logging.error(f"Error processing message: {e}")
        await update.message.reply_text(
            "حدث خطأ أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً.",
            reply_to_message_id=original_message_id
        )
    
    finally:
        # تنظيف الملفات والمجلدات بعد الانتهاء
        cleanup_user_files(user_id)

# وظائف التحميل المحدثة لإرجاع معلومات الفيديو

# Функция для скачивания медиа с Instagram (Reels и посты)
def download_instagram_media(url: str, output_path: str) -> tuple:
    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': f"{output_path}/%(title)s.%(ext)s",
            'quiet': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            return file_path, info_dict
    except Exception as e:
        logging.error(f"Error downloading Instagram media: {e}")
        return f"Error downloading Instagram media: {e}", {}

# Функция для скачивания Stories с Instagram
def download_instagram_stories(username: str, output_path: str) -> str:
    L = instaloader.Instaloader()
    try:
        # ملاحظة: يحتاج ملف auth.json للمصادقة - يجب إنشاؤه منفصلاً
        if os.path.exists("auth.json"):
            with open("auth.json", "r") as f:
                auth_data = json.load(f)
            L.login(auth_data["username"], auth_data["password"])
        
        profile = instaloader.Profile.from_username(L.context, username)
        for story in L.get_stories([profile.userid]):
            for item in story.get_items():
                L.download_storyitem(item, target=output_path)
        return output_path
    except Exception as e:
        logging.error(f"Error downloading Instagram Stories: {e}")
        return f"Error downloading Instagram Stories: {e}"

# Функция для скачивания Highlights с Instagram
def download_instagram_highlights(username: str, output_path: str) -> str:
    L = instaloader.Instaloader()
    try:
        if os.path.exists("auth.json"):
            with open("auth.json", "r") as f:
                auth_data = json.load(f)
            L.login(auth_data["username"], auth_data["password"])
        
        profile = instaloader.Profile.from_username(L.context, username)
        for highlight in L.get_highlights(profile):
            for item in highlight.get_items():
                L.download_storyitem(item, target=output_path)
        return output_path
    except Exception as e:
        logging.error(f"Error downloading Instagram Highlights: {e}")
        return f"Error downloading Instagram Highlights: {e}"

# Функция для скачивания видео с YouTube
def download_youtube_video(url: str, output_path: str) -> tuple:
    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': f"{output_path}/%(title)s.%(ext)s",
            'quiet': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            return file_path, info_dict
    except Exception as e:
        logging.error(f"Error downloading YouTube video: {e}")
        return f"Error downloading YouTube video: {e}", {}

# Функция для скачивания видео с TikTok
def download_tiktok_video(url: str, output_path: str) -> tuple:
    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': f"{output_path}/%(title)s.%(ext)s",
            'quiet': True,
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
                'Referer': 'https://www.tiktok.com/',
            }
        }
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            return file_path, info_dict
    except Exception as e:
        logging.error(f"Error downloading TikTok video: {e}")
        return f"Error downloading TikTok video: {e}", {}

# Функция для скачивания видео с Facebook
def download_facebook_video(url: str, output_path: str) -> tuple:
    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': f"{output_path}/%(title)s.%(ext)s",
            'quiet': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info_dict)
            return file_path, info_dict
    except Exception as e:
        logging.error(f"Error downloading Facebook video: {e}")
        return f"Error downloading Facebook video: {e}", {}

# Функция для преобразования сокращенных ссылок Pinterest
def expand_short_url(short_url: str) -> str:
    try:
        response = requests.get(short_url, allow_redirects=True)
        return response.url
    except Exception as e:
        logging.error(f"Error expanding short URL: {e}")
        return None

# Функция для получения ссылки на скачивание с Pinterest
async def get_download_url(link: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post('https://www.expertsphp.com/download.php', data={'url': link}) as response:
                content = await response.text()
                download_url = pq(content)('table.table-condensed')('tbody')('td')('a').attr('href')
                return download_url
    except Exception as e:
        logging.error(f"Error getting Pinterest download URL: {e}")
        return None

# Функция для скачивания видео
async def download_video(url: str, output_path: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    file_path = os.path.join(output_path, "pinterest_video.mp4")
                    with open(file_path, "wb") as file:
                        file.write(await response.read())
                    return file_path
                else:
                    return f"Failed to download video: {response.status}"
    except Exception as e:
        logging.error(f"Error downloading Pinterest video: {e}")
        return f"Error downloading Pinterest video: {e}"

# Функция для скачивания изображения
async def download_image(url: str, output_path: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    file_path = os.path.join(output_path, "pinterest_image.jpg")
                    with open(file_path, "wb") as file:
                        file.write(await response.read())
                    return file_path
                else:
                    return f"Failed to download image: {response.status}"
    except Exception as e:
        logging.error(f"Error downloading Pinterest image: {e}")
        return f"Error downloading Pinterest image: {e}"

# Основная функция
def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN environment variable is not set!")
        return
    
    if not CHANNEL_ID:
        logging.warning("CHANNEL_ID environment variable is not set. Channel upload will be disabled.")
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("Bot started successfully!")
    application.run_polling()

if __name__ == '__main__':
    main()
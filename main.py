import os
import logging
import tempfile
from io import BytesIO
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
from flask import Flask, render_template_string, request, send_file, jsonify
import threading
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler

# تحميل متغيرات البيئة
load_dotenv()

# إعدادات من متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
PAIR_SITE = os.getenv("PAIR_SITE") # New: PAIR_SITE environment variable

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

# إنشاء تطبيق Flask
app = Flask(__name__)

# New: /check endpoint
@app.route('/check')
def check_server_status():
    return jsonify({"status": "available", "message": "Server is running"})

# Function to check PAIR_SITE availability
def check_pair_site_availability():
    if PAIR_SITE:
        try:
            response = requests.get(PAIR_SITE, timeout=10)
            if response.status_code == 200:
                logging.info(f"PAIR_SITE ({PAIR_SITE}) is AVAILABLE. Status Code: {response.status_code}")
            else:
                logging.warning(f"PAIR_SITE ({PAIR_SITE}) returned status code: {response.status_code}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error checking PAIR_SITE ({PAIR_SITE}): {e}")
    else:
        logging.info("PAIR_SITE environment variable not set. Skipping availability check.")

# HTML Template للصفحة الرئيسية
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تحميل الفيديوهات</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 600px;
            width: 100%;
        }
        
        h1 {
            color: #667eea;
            text-align: center;
            margin-bottom: 10px;
            font-size: 2.5em;
        }
        
        .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
        }
        
        .platforms {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        
        .platform-badge {
            background: #f0f0f0;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.9em;
            color: #555;
        }
        
        .input-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: bold;
        }
        
        input[type="text"] {
            width: 100%;
            padding: 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 1em;
            transition: border-color 0.3s;
        }
        
        input[type="text"]:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .btn {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1.1em;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
        }
        
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        
        .message {
            margin-top: 20px;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            display: none;
        }
        
        .message.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .message.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        .message.info {
            background: #d1ecf1;
            color: #0c5460;
            border: 1px solid #bee5eb;
        }
        
        .loader {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
            display: none;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .info-box {
            background: #f8f9fa;
            border-right: 4px solid #667eea;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
        }
        
        .info-box h3 {
            color: #667eea;
            margin-bottom: 10px;
        }
        
        .info-box ul {
            list-style-position: inside;
            color: #666;
        }
        
        .info-box li {
            margin: 5px 0;
        }
        
        @media (max-width: 600px) {
            .container {
                padding: 20px;
            }
            
            h1 {
                font-size: 2em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📥 تحميل الفيديوهات</h1>
        <p class="subtitle">حمل الفيديوهات والصور من منصات التواصل الاجتماعي</p>
        
        <div class="platforms">
            <span class="platform-badge">📷 Instagram</span>
            <span class="platform-badge">▶️ YouTube</span>
            <span class="platform-badge">🎵 TikTok</span>
            <span class="platform-badge">📘 Facebook</span>
            <span class="platform-badge">📌 Pinterest</span>
        </div>
        
        <form id="downloadForm">
            <div class="input-group">
                <label for="url">🔗 أدخل الرابط:</label>
                <input type="text" id="url" name="url" placeholder="https://www.instagram.com/reel/..." required>
            </div>
            
            <button type="submit" class="btn" id="submitBtn">تحميل الآن</button>
        </form>
        
        <div class="loader" id="loader"></div>
        <div class="message" id="message"></div>
        
        <div class="info-box">
            <h3>ℹ️ معلومات:</h3>
            <ul>
                <li>الحد الأقصى لحجم الملف: 50 ميجابايت</li>
                <li>جميع الملفات يتم معالجتها في الذاكرة</li>
                <li>يتم حذف الملفات تلقائياً بعد التحميل</li>
            </ul>
        </div>
    </div>
    
    <script>
        const form = document.getElementById('downloadForm');
        const submitBtn = document.getElementById('submitBtn');
        const loader = document.getElementById('loader');
        const message = document.getElementById('message');
        const urlInput = document.getElementById('url');
        
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const url = urlInput.value.trim();
            
            if (!url) {
                showMessage('يرجى إدخال رابط صحيح', 'error');
                return;
            }
            
            // إظهار مؤشر التحميل
            submitBtn.disabled = true;
            submitBtn.textContent = 'جاري التحميل...';
            loader.style.display = 'block';
            message.style.display = 'none';
            
            try {
                const response = await fetch('/download', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ url: url })
                });
                
                if (response.ok) {
                    // الحصول على اسم الملف من الهيدر
                    const contentDisposition = response.headers.get('Content-Disposition');
                    let filename = 'vid.mp4';
                    
                    if (contentDisposition) {
                        const filenameMatch = contentDisposition.match(/filename="(.+)"/);
                        if (filenameMatch) {
                            filename = filenameMatch[1];
                        }
                    }
                    
                    // تحميل الملف
                    const blob = await response.blob();
                    const downloadUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = downloadUrl;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(downloadUrl);
                    a.remove();
                    
                    showMessage('✅ تم تحميل الملف بنجاح!', 'success');
                    urlInput.value = '';
                } else {
                    const errorData = await response.json();
                    showMessage('❌ ' + (errorData.error || 'حدث خطأ أثناء التحميل'), 'error');
                }
            } catch (error) {
                showMessage('❌ حدث خطأ في الاتصال. يرجى المحاولة مرة أخرى.', 'error');
                console.error('Error:', error);
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'تحميل الآن';
                loader.style.display = 'none';
            }
        });
        
        function showMessage(text, type) {
            message.textContent = text;
            message.className = 'message ' + type;
            message.style.display = 'block';
            
            // إخفاء الرسالة بعد 5 ثواني
            setTimeout(() => {
                message.style.display = 'none';
            }, 5000);
        }
    </script>
</body>
</html>
"""

# Проверка размера البيانات في الذاكرة
def check_data_size(data: bytes) -> bool:
    data_size = len(data)
    return data_size <= MAX_FILE_SIZE

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
async def send_to_channel(context, media_data: BytesIO, original_url: str, platform: str, is_video: bool = True):
    """إرسال الفيديو للقناة مع معلومات مبسطة"""
    if not CHANNEL_ID:
        logging.warning("CHANNEL_ID not set, skipping channel upload")
        return
    
    try:
        # الحصول على هاشتاج المنصة
        platform_hashtag = get_platform_hashtag(platform)
        
        # تحضير النص المصاحب المبسط
        caption = f"{original_url}\n{platform_hashtag}"
        
        # إعادة تعيين المؤشر لبداية البيانات
        media_data.seek(0)
        
        # إرسال الفيديو للقناة
        if is_video:
            await context.bot.send_video(
                chat_id=CHANNEL_ID,
                video=media_data,
                caption=caption,
                filename="vid.mp4"
            )
        else:
            await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=media_data,
                caption=caption,
                filename="vid.mp4"
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
        "🗑️ جميع الملفات يتم معالجتها في الذاكرة وحذفها تلقائياً للحفاظ على الخصوصية."
    )
    await update.message.reply_text(welcome_message)

# Обработчик сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    url = update.message.text
    original_message_id = update.message.message_id

    # Проверка ограничения запросов
    now = datetime.now()
    if user_id in user_requests:
        user_requests[user_id] = [req for req in user_requests[user_id] if now - req < timedelta(minutes=1)]
        if len(user_requests[user_id]) >= MAX_REQUESTS_PER_MINUTE:
            await update.message.reply_text(
                "لقد تجاوزت حد 5 تحميلات في الدقيقة. يرجى الانتظار.",
                reply_to_message_id=original_message_id
            )
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
            return

    try:
        result = await process_download(url)
        
        if result['success']:
            media_data = result['data']
            platform = result['platform']
            is_video = result['is_video']
            
            # الحصول على البيانات للتحقق من الحجم
            media_bytes = media_data.getvalue()
            
            if check_data_size(media_bytes):
                # إعادة تعيين المؤشر لبداية البيانات
                media_data.seek(0)
                
                # إرسال الملف للمستخدم
                if is_video:
                    await update.message.reply_video(
                        media_data, 
                        reply_to_message_id=original_message_id,
                        filename="vid.mp4"
                    )
                else:
                    await update.message.reply_photo(
                        media_data,
                        reply_to_message_id=original_message_id,
                        filename="vid.mp4"
                    )
                
                # إعادة إنشاء BytesIO من البيانات للإرسال للقناة
                if platform:
                    channel_media = BytesIO(media_bytes)
                    await send_to_channel(context, channel_media, update.message.text, platform, is_video)
                    channel_media.close()
            else:
                await update.message.reply_text(
                    "حجم الملف يتجاوز حد 50 ميجابايت.",
                    reply_to_message_id=original_message_id
                )
            
            # حذف البيانات من الذاكرة
            media_data.close()
        else:
            await update.message.reply_text(
                result['error'],
                reply_to_message_id=original_message_id
            )

    except Exception as e:
        logging.error(f"Error processing message: {e}")
        await update.message.reply_text(
            "حدث خطأ أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً.",
            reply_to_message_id=original_message_id
        )

# وظيفة معالجة التحميل (مشتركة بين البوت والويب)
async def process_download(url: str) -> dict:
    """معالجة تحميل الرابط وإرجاع النتيجة"""
    try:
        # Если ссылка сокращённая (pin.it), преобразуем её в полный URL
        if url.startswith("https://pin.it/"):
            expanded_url = expand_short_url(url)
            if expanded_url:
                url = expanded_url
            else:
                return {
                    'success': False,
                    'error': 'فشل في توسيع الرابط المختصر.'
                }

        result = None
        platform = None
        is_video = True
        media_data = None
        
        if "instagram.com" in url:
            if "/stories/" in url:
                username = url.split("/stories/")[1].split("/")[0]
                media_data = await download_instagram_stories(username)
                platform = "Instagram Stories"
            elif "/reel/" in url or "/p/" in url:
                media_data = await download_instagram_media(url)
                platform = "Instagram"
            elif "/highlights/" in url:
                username = url.split("/highlights/")[1].split("/")[0]
                media_data = await download_instagram_highlights(username)
                platform = "Instagram Highlights"
            else:
                return {
                    'success': False,
                    'error': 'رابط Instagram غير مدعوم.'
                }
        elif "youtube.com" in url or "youtu.be" in url:
            media_data = await download_youtube_video(url)
            platform = "YouTube"
        elif "tiktok.com" in url:
            media_data = await download_tiktok_video(url)
            platform = "TikTok"
        elif "facebook.com" in url:
            media_data = await download_facebook_video(url)
            platform = "Facebook"
        elif "pinterest.com" in url:
            download_url = await get_download_url(url)
            if download_url:
                if '.mp4' in download_url:
                    media_data = await download_video(download_url)
                    platform = "Pinterest Video"
                    is_video = True
                else:
                    media_data = await download_image(download_url)
                    platform = "Pinterest Image"
                    is_video = False
            else:
                return {
                    'success': False,
                    'error': 'فشل في الحصول على رابط التحميل من Pinterest.'
                }
        else:
            return {
                'success': False,
                'error': 'منصة غير مدعومة. يرجى تقديم رابط صحيح.'
            }

        if media_data and isinstance(media_data, BytesIO):
            return {
                'success': True,
                'data': media_data,
                'platform': platform,
                'is_video': is_video
            }
        elif isinstance(media_data, str):
            return {
                'success': False,
                'error': media_data
            }
        else:
            return {
                'success': False,
                'error': 'حدث خطأ أثناء التحميل.'
            }
    except Exception as e:
        logging.error(f"Error in process_download: {e}")
        return {
            'success': False,
            'error': f'حدث خطأ: {str(e)}'
        }

# وظائف التحميل المحدثة لاستخدام الذاكرة

# Функция для скачивания медиа с Instagram (Reels и посты)
async def download_instagram_media(url: str) -> BytesIO:
    temp_dir = None
    try:
        # إنشاء مجلد مؤقت
        temp_dir = tempfile.mkdtemp()
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': f"{temp_dir}/vid.mp4",
            'quiet': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
            # قراءة الملف من القرص إلى الذاكرة
            file_path = f"{temp_dir}/vid.mp4"
            with open(file_path, 'rb') as f:
                media_data = BytesIO(f.read())
            
            return media_data
    except Exception as e:
        logging.error(f"Error downloading Instagram media: {e}")
        return f"Error downloading Instagram media: {e}"
    finally:
        # حذف المجلد المؤقت
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)

# Функция для скачивания Stories с Instagram
async def download_instagram_stories(username: str) -> BytesIO:
    temp_dir = None
    try:
        # إنشاء مجلد مؤقت
        temp_dir = tempfile.mkdtemp()
        
        L = instaloader.Instaloader()
        
        if os.path.exists("auth.json"):
            with open("auth.json", "r") as f:
                auth_data = json.load(f)
            L.login(auth_data["username"], auth_data["password"])
        
        profile = instaloader.Profile.from_username(L.context, username)
        downloaded_file = None
        
        for story in L.get_stories([profile.userid]):
            for item in story.get_items():
                L.download_storyitem(item, target=temp_dir)
                # الحصول على أول ملف تم تحميله
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.jpg', '.png')):
                        downloaded_file = os.path.join(temp_dir, file)
                        break
                if downloaded_file:
                    break
            if downloaded_file:
                break
        
        if downloaded_file:
            with open(downloaded_file, 'rb') as f:
                media_data = BytesIO(f.read())
            return media_data
        else:
            return "لم يتم العثور على stories."
            
    except Exception as e:
        logging.error(f"Error downloading Instagram Stories: {e}")
        return f"Error downloading Instagram Stories: {e}"
    finally:
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)

# Функция для скачивания Highlights с Instagram
async def download_instagram_highlights(username: str) -> BytesIO:
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        
        L = instaloader.Instaloader()
        
        if os.path.exists("auth.json"):
            with open("auth.json", "r") as f:
                auth_data = json.load(f)
            L.login(auth_data["username"], auth_data["password"])
        
        profile = instaloader.Profile.from_username(L.context, username)
        downloaded_file = None
        
        for highlight in L.get_highlights(profile):
            for item in highlight.get_items():
                L.download_storyitem(item, target=temp_dir)
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.jpg', '.png')):
                        downloaded_file = os.path.join(temp_dir, file)
                        break
                if downloaded_file:
                    break
            if downloaded_file:
                break
        
        if downloaded_file:
            with open(downloaded_file, 'rb') as f:
                media_data = BytesIO(f.read())
            return media_data
        else:
            return "لم يتم العثور على highlights."
            
    except Exception as e:
        logging.error(f"Error downloading Instagram Highlights: {e}")
        return f"Error downloading Instagram Highlights: {e}"
    finally:
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)

# Функция для скачивания видео с YouTube
async def download_youtube_video(url: str) -> BytesIO:
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': f"{temp_dir}/vid.mp4",
            'quiet': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
            file_path = f"{temp_dir}/vid.mp4"
            with open(file_path, 'rb') as f:
                media_data = BytesIO(f.read())
            
            return media_data
    except Exception as e:
        logging.error(f"Error downloading YouTube video: {e}")
        return f"Error downloading YouTube video: {e}"
    finally:
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)

# Функция для скачивания видео с TikTok
async def download_tiktok_video(url: str) -> BytesIO:
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': f"{temp_dir}/vid.mp4",
            'quiet': True,
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
                'Referer': 'https://www.tiktok.com/',
            }
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
            file_path = f"{temp_dir}/vid.mp4"
            with open(file_path, 'rb') as f:
                media_data = BytesIO(f.read())
            
            return media_data
    except Exception as e:
        logging.error(f"Error downloading TikTok video: {e}")
        return f"Error downloading TikTok video: {e}"
    finally:
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)

# Функция для скачивания видео с Facebook
async def download_facebook_video(url: str) -> BytesIO:
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        
        ydl_opts = {
            'format': 'best',
            'outtmpl': f"{temp_dir}/vid.mp4",
            'quiet': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
            file_path = f"{temp_dir}/vid.mp4"
            with open(file_path, 'rb') as f:
                media_data = BytesIO(f.read())
            
            return media_data
    except Exception as e:
        logging.error(f"Error downloading Facebook video: {e}")
        return f"Error downloading Facebook video: {e}"
    finally:
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)

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

# Функция для скачивания видео من Pinterest
async def download_video(url: str) -> BytesIO:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.read()
                    media_data = BytesIO(data)
                    return media_data
                else:
                    return f"Failed to download video: {response.status}"
    except Exception as e:
        logging.error(f"Error downloading Pinterest video: {e}")
        return f"Error downloading Pinterest video: {e}"

# Функция для скачивания изображения من Pinterest
async def download_image(url: str) -> BytesIO:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.read()
                    media_data = BytesIO(data)
                    return media_data
                else:
                    return f"Failed to download image: {response.status}"
    except Exception as e:
        logging.error(f"Error downloading Pinterest image: {e}")
        return f"Error downloading Pinterest image: {e}"

# Flask Routes
@app.route('/')
def index():
    """الصفحة الرئيسية"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/download', methods=['POST'])
def download():
    """معالج التحميل عبر الويب"""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'يرجى تقديم رابط'}), 400
        
        # تشغيل الوظيفة async في loop جديد
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(process_download(url))
        loop.close()
        
        if result['success']:
            media_data = result['data']
            is_video = result['is_video']
            
            # التحقق من الحجم
            media_bytes = media_data.getvalue()
            if not check_data_size(media_bytes):
                media_data.close()
                return jsonify({'error': 'حجم الملف يتجاوز حد 50 ميجابايت'}), 400
            
            # إعادة تعيين المؤشر
            media_data.seek(0)
            
            # تحديد نوع المحتوى واسم الملف
            mimetype = 'video/mp4' if is_video else 'image/jpeg'
            filename = 'vid.mp4'
            
            return send_file(
                media_data,
                mimetype=mimetype,
                as_attachment=True,
                download_name=filename
            )
        else:
            return jsonify({'error': result['error']}), 400
            
    except Exception as e:
        logging.error(f"Error in /download endpoint: {e}")
        return jsonify({'error': 'حدث خطأ أثناء معالجة الطلب'}), 500

# تشغيل Flask في thread منفصل
def run_flask():
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False)

# تشغيل Telegram Bot
def run_bot():
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

    # Основная функция
def main():
    logging.info("Starting application...")
    
    # تشغيل Flask في thread منفصل
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info(f"Flask web server started on port {FLASK_PORT}")

    # Start the scheduler for checking PAIR_SITE availability
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_pair_site_availability, 'interval', minutes=1)
    scheduler.start()
    logging.info("PAIR_SITE availability checker started.")
    
    try:
        # تشغيل البوت في الـ main thread
        if BOT_TOKEN:
            run_bot()
        else:
            logging.warning("BOT_TOKEN not set. Running web server only.")
            # إبقاء البرنامج يعمل إذا كان البوت غير مفعل
            try:
                flask_thread.join()
            except KeyboardInterrupt:
                logging.info("Application stopped by user")
    finally:
        scheduler.shutdown()
        logging.info("Scheduler shut down.")


if __name__ == '__main__':
    main()

import os
import logging
import tempfile
import re
import shutil
from io import BytesIO
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from pybalt import download as pybalt_download
import requests
from dotenv import load_dotenv
from flask import Flask, render_template_string, request, send_file, jsonify
import threading
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler
import aiohttp

# تحميل متغيرات البيئة
load_dotenv()

# إعدادات من متغيرات البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
PAIR_SITE = os.getenv("PAIR_SITE")

# الثوابت
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_REQUESTS_PER_MINUTE = 5

# قواميس للتتبع
user_requests = {}
video_info_cache = {}

# إعداد السجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# إنشاء تطبيق Flask
app = Flask(__name__)

# /check endpoint
@app.route('/check')
def check_server_status():
    return jsonify({"status": "available", "message": "Server is running"})

# دالة فحص PAIR_SITE
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

def is_youtube_url(url: str) -> bool:
    """التحقق مما إذا كان الرابط من يوتيوب"""
    youtube_patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/shorts/[\w-]+',
        r'(https?://)?(www\.)?youtu\.be/[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/v/[\w-]+',
        r'(https?://)?(www\.)?youtube\.com/embed/[\w-]+',
        r'(https?://)?m\.youtube\.com/watch\?v=[\w-]+',
    ]
    for pattern in youtube_patterns:
        if re.match(pattern, url.strip()):
            return True
    return False

def format_size(size_bytes):
    """تحويل الحجم من بايت إلى صيغة مقروءة"""
    if size_bytes is None or size_bytes == 0:
        return "غير معروف"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def check_data_size(data: bytes) -> bool:
    return len(data) <= MAX_FILE_SIZE

# HTML Template للصفحة الرئيسية (يوتيوب فقط)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تحميل فيديوهات يوتيوب</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%);
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
        h1 { color: #ff0000; text-align: center; margin-bottom: 10px; font-size: 2.5em; }
        .subtitle { text-align: center; color: #666; margin-bottom: 30px; font-size: 1.1em; }
        .platform-badge {
            background: #ff0000;
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.9em;
            display: inline-block;
            margin-bottom: 20px;
        }
        .input-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; color: #333; font-weight: bold; }
        input[type="text"] {
            width: 100%;
            padding: 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 1em;
            transition: border-color 0.3s;
        }
        input[type="text"]:focus { outline: none; border-color: #ff0000; }
        .btn {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #ff0000 0%, #cc0000 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1.1em;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(255, 0, 0, 0.3); }
        .btn:disabled { background: #ccc; cursor: not-allowed; transform: none; }
        .message { margin-top: 20px; padding: 15px; border-radius: 10px; text-align: center; display: none; }
        .message.success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .message.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .loader {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #ff0000;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
            display: none;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .info-box {
            background: #f8f9fa;
            border-right: 4px solid #ff0000;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
        }
        .info-box h3 { color: #ff0000; margin-bottom: 10px; }
        .info-box ul { list-style-position: inside; color: #666; }
        .info-box li { margin: 5px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📥 تحميل يوتيوب</h1>
        <p class="subtitle">حمل فيديوهات يوتيوب بالجودة التي تريدها</p>
        <div style="text-align: center;"><span class="platform-badge">▶️ YouTube Only</span></div>
        <form id="downloadForm">
            <div class="input-group">
                <label for="url">🔗 أدخل رابط يوتيوب:</label>
                <input type="text" id="url" name="url" placeholder="https://www.youtube.com/watch?v=..." required>
            </div>
            <button type="submit" class="btn" id="submitBtn">جلب الجودات</button>
        </form>
        <div class="loader" id="loader"></div>
        <div class="message" id="message"></div>
        <div id="formatsContainer"></div>
        <div class="info-box">
            <h3>ℹ️ معلومات:</h3>
            <ul>
                <li>يدعم يوتيوب فقط</li>
                <li>الحد الأقصى لحجم الملف: 50 ميجابايت</li>
                <li>يمكنك اختيار جودة الفيديو أو الصوت</li>
            </ul>
        </div>
    </div>
    <script>
        const form = document.getElementById('downloadForm');
        const submitBtn = document.getElementById('submitBtn');
        const loader = document.getElementById('loader');
        const message = document.getElementById('message');
        const urlInput = document.getElementById('url');
        const formatsContainer = document.getElementById('formatsContainer');
        
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const url = urlInput.value.trim();
            if (!url) { showMessage('يرجى إدخال رابط صحيح', 'error'); return; }
            submitBtn.disabled = true;
            submitBtn.textContent = 'جاري الجلب...';
            loader.style.display = 'block';
            message.style.display = 'none';
            formatsContainer.innerHTML = '';
            try {
                const response = await fetch('/get_formats', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                const data = await response.json();
                if (data.success) {
                    displayFormats(data, url);
                } else {
                    showMessage('❌ ' + data.error, 'error');
                }
            } catch (error) {
                showMessage('❌ حدث خطأ في الاتصال', 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'جلب الجودات';
                loader.style.display = 'none';
            }
        });
        
        function displayFormats(data, url) {
            let html = '<div style="margin-top:20px;"><h3>🎬 ' + data.title + '</h3><p>⏱ المدة: ' + Math.floor(data.duration/60) + ':' + String(data.duration%60).padStart(2,'0') + '</p>';
            html += '<div style="display:flex;gap:20px;margin-top:15px;flex-wrap:wrap;">';
            html += '<div style="flex:1;min-width:200px;"><h4>📹 فيديو</h4>';
            data.video_formats.forEach(f => {
                html += '<button class="btn" style="margin:5px 0;font-size:0.9em;" onclick="downloadFormat(\\'' + url + '\\',\\'' + f.format_id + '\\',false)">' + f.resolution + ' - ' + f.ext.toUpperCase() + ' (' + f.size + ')</button>';
            });
            html += '</div><div style="flex:1;min-width:200px;"><h4>🎵 صوت</h4>';
            data.audio_formats.forEach(f => {
                html += '<button class="btn" style="margin:5px 0;font-size:0.9em;background:linear-gradient(135deg,#1DB954,#1ed760);" onclick="downloadFormat(\\'' + url + '\\',\\'' + f.format_id + '\\',true)">' + f.bitrate + ' - ' + f.ext.toUpperCase() + ' (' + f.size + ')</button>';
            });
            html += '</div></div></div>';
            formatsContainer.innerHTML = html;
        }
        
        async function downloadFormat(url, formatId, isAudio) {
            showMessage('⏳ جاري التحميل...', 'success');
            loader.style.display = 'block';
            try {
                const response = await fetch('/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url, format_id: formatId, is_audio: isAudio })
                });
                if (response.ok) {
                    const blob = await response.blob();
                    const downloadUrl = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = downloadUrl;
                    a.download = isAudio ? 'audio.mp3' : 'video.mp4';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    showMessage('✅ تم التحميل بنجاح!', 'success');
                } else {
                    const data = await response.json();
                    showMessage('❌ ' + data.error, 'error');
                }
            } catch (error) {
                showMessage('❌ خطأ في التحميل', 'error');
            } finally {
                loader.style.display = 'none';
            }
        }
        
        function showMessage(text, type) {
            message.textContent = text;
            message.className = 'message ' + type;
            message.style.display = 'block';
        }
    </script>
</body>
</html>
"""

async def get_video_formats(url: str) -> dict:
    """جلب جميع الجودات المتاحة للفيديو باستخدام pybalt"""
    try:
        # جودات الفيديو المتاحة في pybalt (cobalt)
        video_qualities = ['144', '240', '360', '480', '720', '1080', '1440', '2160', '4320']
        audio_bitrates = ['64', '128', '192', '256', '320']
        
        video_formats = []
        audio_formats = []
        
        # إنشاء قائمة جودات الفيديو
        for quality in video_qualities:
            video_formats.append({
                'format_id': f'video_{quality}',
                'resolution': f'{quality}p',
                'ext': 'mp4',
                'size': 'متغير'
            })
        
        # إنشاء قائمة جودات الصوت
        for bitrate in audio_bitrates:
            audio_formats.append({
                'format_id': f'audio_{bitrate}',
                'bitrate': f'{bitrate}kbps',
                'ext': 'mp3',
                'size': 'متغير'
            })
        
        # جلب عنوان الفيديو من يوتيوب
        title = "فيديو يوتيوب"
        duration = 0
        
        try:
            # محاولة جلب معلومات الفيديو من oEmbed API
            video_id = None
            if 'youtube.com/watch?v=' in url:
                video_id = url.split('v=')[1].split('&')[0]
            elif 'youtu.be/' in url:
                video_id = url.split('youtu.be/')[1].split('?')[0]
            elif 'youtube.com/shorts/' in url:
                video_id = url.split('shorts/')[1].split('?')[0]
            
            if video_id:
                oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
                async with aiohttp.ClientSession() as session:
                    async with session.get(oembed_url) as response:
                        if response.status == 200:
                            data = await response.json()
                            title = data.get('title', 'فيديو يوتيوب')
        except Exception as e:
            logging.warning(f"Could not fetch video title: {e}")
        
        return {
            'success': True,
            'title': title,
            'duration': duration,
            'thumbnail': '',
            'video_formats': video_formats,
            'audio_formats': audio_formats,
            'url': url
        }
        
    except Exception as e:
        logging.error(f"Error getting video formats: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def create_format_keyboard(video_info: dict, chat_id: int) -> InlineKeyboardMarkup:
    """إنشاء لوحة مفاتيح للاختيار بين الجودات"""
    keyboard = []
    
    video_formats = video_info.get('video_formats', [])
    audio_formats = video_info.get('audio_formats', [])
    
    # صف العناوين
    row = []
    if video_formats:
        row.append(InlineKeyboardButton("📹 فيديو", callback_data="header_video"))
    if audio_formats:
        row.append(InlineKeyboardButton("🎵 صوت", callback_data="header_audio"))
    if row:
        keyboard.append(row)
    
    # تحديد أقصى عدد صفوف
    max_rows = max(len(video_formats), len(audio_formats))
    
    for i in range(max_rows):
        row = []
        # زر الفيديو
        if i < len(video_formats):
            fmt = video_formats[i]
            btn_text = f"{fmt['resolution']}-{fmt['ext']} ({fmt['size']})"
            callback_data = f"v_{fmt['format_id']}_{chat_id}"
            row.append(InlineKeyboardButton(btn_text, callback_data=callback_data))
        else:
            row.append(InlineKeyboardButton(" ", callback_data="empty"))
        
        # زر الصوت
        if i < len(audio_formats):
            fmt = audio_formats[i]
            btn_text = f"{fmt['bitrate']}-{fmt['ext']} ({fmt['size']})"
            callback_data = f"a_{fmt['format_id']}_{chat_id}"
            row.append(InlineKeyboardButton(btn_text, callback_data=callback_data))
        else:
            row.append(InlineKeyboardButton(" ", callback_data="empty"))
        
        keyboard.append(row)
    
    # زر إلغاء
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    
    return InlineKeyboardMarkup(keyboard)


async def download_youtube_with_format(url: str, format_id: str, is_audio: bool = False):
    """تحميل فيديو يوتيوب بجودة محددة باستخدام pybalt"""
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        
        # استخراج الجودة من format_id
        if is_audio:
            # format_id مثل: audio_128
            bitrate = format_id.replace('audio_', '')
            
            # تحميل باستخدام pybalt
            file_path = await pybalt_download(
                url=url,
                folder=temp_dir,
                audioFormat="mp3",
                audioBitrate=bitrate,
                downloadMode="audio"
            )
            ext = 'mp3'
        else:
            # format_id مثل: video_720
            quality = format_id.replace('video_', '')
            
            # تحميل باستخدام pybalt
            file_path = await pybalt_download(
                url=url,
                folder=temp_dir,
                videoQuality=quality,
                downloadMode="auto"
            )
            ext = 'mp4'
        
        # قراءة الملف المحمل
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                media_data = BytesIO(f.read())
            # الحصول على الامتداد الفعلي
            ext = file_path.split('.')[-1] if '.' in file_path else ext
            return media_data, ext
        
        # البحث عن أي ملف في المجلد
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            if os.path.isfile(file_path):
                ext = file.split('.')[-1]
                with open(file_path, 'rb') as f:
                    media_data = BytesIO(f.read())
                return media_data, ext
                
        return None, None
        
    except Exception as e:
        logging.error(f"Error downloading YouTube video with pybalt: {e}")
        return None, None
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


# أوامر البوت
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رسالة الترحيب"""
    welcome_message = (
        "🎬 مرحبًا! أنا بوت تحميل فيديوهات يوتيوب.\n\n"
        "📥 أرسل لي رابط فيديو من يوتيوب وسأعرض لك:\n"
        "• جميع جودات الفيديو المتاحة (يمين)\n"
        "• جميع جودات الصوت المتاحة (يسار)\n"
        "• حجم كل ملف\n\n"
        "⚠️ الحد الأقصى لحجم الملف: 50 ميجابايت\n"
        "✅ يدعم: youtube.com و youtu.be فقط"
    )
    await update.message.reply_text(welcome_message)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرسائل الواردة"""
    user_id = update.message.from_user.id
    url = update.message.text.strip()
    chat_id = update.message.chat_id
    
    # التحقق من حد الطلبات
    now = datetime.now()
    if user_id in user_requests:
        user_requests[user_id] = [req for req in user_requests[user_id] if now - req < timedelta(minutes=1)]
        if len(user_requests[user_id]) >= MAX_REQUESTS_PER_MINUTE:
            await update.message.reply_text("⏳ لقد تجاوزت حد 5 طلبات في الدقيقة. يرجى الانتظار.")
            return
        user_requests[user_id].append(now)
    else:
        user_requests[user_id] = [now]
    
    # التحقق من أن الرابط يوتيوب
    if not is_youtube_url(url):
        await update.message.reply_text(
            "❌ خطأ: هذا الرابط غير مدعوم!\n\n"
            "✅ هذا البوت يدعم روابط يوتيوب فقط.\n"
            "📝 مثال: https://www.youtube.com/watch?v=xxxxx"
        )
        return
    
    # إرسال رسالة انتظار
    wait_msg = await update.message.reply_text("⏳ جاري جلب معلومات الفيديو...")
    
    # جلب الجودات المتاحة
    video_info = await get_video_formats(url)
    
    if not video_info['success']:
        await wait_msg.edit_text(f"❌ حدث خطأ: {video_info.get('error', 'خطأ غير معروف')}")
        return
    
    # تخزين معلومات الفيديو
    video_info_cache[chat_id] = video_info
    
    # إنشاء لوحة المفاتيح
    keyboard = create_format_keyboard(video_info, chat_id)
    
    # إنشاء رسالة المعلومات
    duration_min = video_info.get('duration', 0) // 60
    duration_sec = video_info.get('duration', 0) % 60
    
    info_text = (
        f"🎬 *{video_info.get('title', 'فيديو')}*\n\n"
        f"⏱ المدة: {duration_min}:{duration_sec:02d}\n\n"
        f"👇 اختر الجودة المطلوبة:\n"
        f"📹 الفيديو (يمين) | 🎵 الصوت (يسار)"
    )
    
    await wait_msg.edit_text(info_text, reply_markup=keyboard, parse_mode='Markdown')


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على الأزرار"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "cancel":
        await query.edit_message_text("❌ تم الإلغاء")
        return
    
    if data.startswith("header_") or data == "empty":
        return
    
    if data.startswith("v_") or data.startswith("a_"):
        is_audio = data.startswith("a_")
        parts = data.split("_")
        format_id = parts[1]
        chat_id = int(parts[2])
        
        # جلب معلومات الفيديو من الكاش
        video_info = video_info_cache.get(chat_id)
        if not video_info:
            await query.edit_message_text("❌ انتهت صلاحية الطلب. أرسل الرابط مرة أخرى.")
            return
        
        url = video_info.get('url')
        
        await query.edit_message_text("⏳ جاري التحميل... يرجى الانتظار")
        
        # تحميل الفيديو
        media_data, ext = await download_youtube_with_format(url, format_id, is_audio)
        
        if media_data is None:
            await query.edit_message_text("❌ حدث خطأ أثناء التحميل. حاول مرة أخرى.")
            return
        
        # التحقق من الحجم
        media_bytes = media_data.getvalue()
        if len(media_bytes) > MAX_FILE_SIZE:
            await query.edit_message_text("❌ حجم الملف يتجاوز 50 ميجابايت.")
            media_data.close()
            return
        
        media_data.seek(0)
        
        try:
            if is_audio:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=media_data,
                    filename=f"audio.{ext}",
                    title=video_info.get('title', 'صوت')
                )
            else:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=media_data,
                    filename=f"video.{ext}",
                    caption=f"🎬 {video_info.get('title', '')}"
                )
            
            await query.edit_message_text("✅ تم التحميل بنجاح!")
            
            # إرسال للقناة إذا كانت محددة
            if CHANNEL_ID:
                media_data.seek(0)
                try:
                    if is_audio:
                        await context.bot.send_audio(
                            chat_id=CHANNEL_ID,
                            audio=media_data,
                            filename=f"audio.{ext}",
                            caption=f"{url}\n#youtube"
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=CHANNEL_ID,
                            video=media_data,
                            filename=f"video.{ext}",
                            caption=f"{url}\n#youtube"
                        )
                except Exception as e:
                    logging.error(f"Error sending to channel: {e}")
                    
        except Exception as e:
            logging.error(f"Error sending media: {e}")
            await query.edit_message_text(f"❌ حدث خطأ أثناء الإرسال: {str(e)}")
        finally:
            media_data.close()
            if chat_id in video_info_cache:
                del video_info_cache[chat_id]


# Flask Routes
@app.route('/')
def index():
    """الصفحة الرئيسية"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/get_formats', methods=['POST'])
def get_formats():
    """جلب الجودات المتاحة"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'يرجى تقديم رابط'}), 400
        
        if not is_youtube_url(url):
            return jsonify({'success': False, 'error': 'هذا الرابط غير مدعوم! يدعم يوتيوب فقط.'}), 400
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(get_video_formats(url))
        loop.close()
        
        return jsonify(result)
        
    except Exception as e:
        logging.error(f"Error in /get_formats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download', methods=['POST'])
def download():
    """تحميل الفيديو بجودة محددة"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        format_id = data.get('format_id', '')
        is_audio = data.get('is_audio', False)
        
        if not url or not format_id:
            return jsonify({'error': 'بيانات ناقصة'}), 400
        
        if not is_youtube_url(url):
            return jsonify({'error': 'رابط غير مدعوم'}), 400
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        media_data, ext = loop.run_until_complete(download_youtube_with_format(url, format_id, is_audio))
        loop.close()
        
        if media_data is None:
            return jsonify({'error': 'فشل التحميل'}), 500
        
        media_bytes = media_data.getvalue()
        if not check_data_size(media_bytes):
            media_data.close()
            return jsonify({'error': 'حجم الملف يتجاوز 50 ميجابايت'}), 400
        
        media_data.seek(0)
        
        mimetype = 'audio/mpeg' if is_audio else 'video/mp4'
        filename = f'audio.{ext}' if is_audio else f'video.{ext}'
        
        return send_file(
            media_data,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logging.error(f"Error in /download: {e}")
        return jsonify({'error': str(e)}), 500


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
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    logging.info("Bot started successfully!")
    application.run_polling()


# الوظيفة الرئيسية
def main():
    logging.info("Starting YouTube Downloader application...")
    
    # تشغيل Flask في thread منفصل
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info(f"Flask web server started on port {FLASK_PORT}")
    
    # تشغيل scheduler لفحص PAIR_SITE
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_pair_site_availability, 'interval', minutes=1)
    scheduler.start()
    logging.info("PAIR_SITE availability checker started.")
    
    try:
        if BOT_TOKEN:
            run_bot()
        else:
            logging.warning("BOT_TOKEN not set. Running web server only.")
            try:
                flask_thread.join()
            except KeyboardInterrupt:
                logging.info("Application stopped by user")
    finally:
        scheduler.shutdown()
        logging.info("Scheduler shut down.")


if __name__ == '__main__':
    main()

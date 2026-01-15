import os
import logging
import tempfile
import shutil
from io import BytesIO
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message

def named_bytesio(data: bytes, name: str = "vid.mp4") -> BytesIO:
    bio = BytesIO(data)
    bio.name = name
    return bio
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

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
CHANNEL_ID = os.getenv("CHANNEL_ID")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
PAIR_SITE = os.getenv("PAIR_SITE")

COOKIES_FILE = "cookies.txt"
if not os.path.exists(COOKIES_FILE):
    cookies_content = os.getenv("COOKIES")
    if cookies_content:
        with open(COOKIES_FILE, 'w') as f:
            f.write(cookies_content)

MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_REQUESTS_PER_MINUTE = 5
user_requests = {}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

app = Flask(__name__)
bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.route('/check')
def check_server_status():
    return jsonify({"status": "available", "message": "Server is running"})

def check_pair_site_availability():
    if PAIR_SITE:
        try:
            response = requests.get(PAIR_SITE, timeout=10)
            logging.info(f"PAIR_SITE ({PAIR_SITE}) status: {response.status_code}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Error checking PAIR_SITE: {e}")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تحميل الفيديوهات</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }
        .container { background: white; border-radius: 20px; padding: 40px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); max-width: 600px; width: 100%; }
        h1 { color: #667eea; text-align: center; margin-bottom: 10px; font-size: 2.5em; }
        .subtitle { text-align: center; color: #666; margin-bottom: 30px; font-size: 1.1em; }
        .platforms { display: flex; justify-content: center; gap: 15px; margin-bottom: 30px; flex-wrap: wrap; }
        .platform-badge { background: #f0f0f0; padding: 8px 16px; border-radius: 20px; font-size: 0.9em; color: #555; }
        .input-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; color: #333; font-weight: bold; }
        input[type="text"] { width: 100%; padding: 15px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 1em; transition: border-color 0.3s; }
        input[type="text"]:focus { outline: none; border-color: #667eea; }
        .btn { width: 100%; padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 1.1em; font-weight: bold; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3); }
        .btn:disabled { background: #ccc; cursor: not-allowed; transform: none; }
        .message { margin-top: 20px; padding: 15px; border-radius: 10px; text-align: center; display: none; }
        .message.success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .message.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .loader { border: 4px solid #f3f3f3; border-top: 4px solid #667eea; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; display: none; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .info-box { background: #f8f9fa; border-right: 4px solid #667eea; padding: 15px; border-radius: 8px; margin-top: 20px; }
        .info-box h3 { color: #667eea; margin-bottom: 10px; }
        .info-box ul { list-style-position: inside; color: #666; }
        .info-box li { margin: 5px 0; }
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
            if (!url) { showMessage('يرجى إدخال رابط صحيح', 'error'); return; }
            submitBtn.disabled = true;
            submitBtn.textContent = 'جاري التحميل...';
            loader.style.display = 'block';
            message.style.display = 'none';
            try {
                const response = await fetch('/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: url }) });
                if (response.ok) {
                    const contentDisposition = response.headers.get('Content-Disposition');
                    let filename = 'vid.mp4';
                    if (contentDisposition) { const filenameMatch = contentDisposition.match(/filename="(.+)"/); if (filenameMatch) { filename = filenameMatch[1]; } }
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
            } catch (error) { showMessage('❌ حدث خطأ في الاتصال. يرجى المحاولة مرة أخرى.', 'error'); }
            finally { submitBtn.disabled = false; submitBtn.textContent = 'تحميل الآن'; loader.style.display = 'none'; }
        });
        function showMessage(text, type) { message.textContent = text; message.className = 'message ' + type; message.style.display = 'block'; setTimeout(() => { message.style.display = 'none'; }, 5000); }
    </script>
</body>
</html>
"""

def check_data_size(data: bytes) -> bool:
    return len(data) <= MAX_FILE_SIZE

def get_platform_hashtag(platform: str) -> str:
    hashtags = {"Instagram": "#instagram", "Instagram Stories": "#instagram", "Instagram Highlights": "#instagram", "YouTube": "#youtube", "TikTok": "#tiktok", "Facebook": "#facebook", "Pinterest Video": "#pinterest", "Pinterest Image": "#pinterest"}
    return hashtags.get(platform, "#unknown")

async def send_to_channel(media_data: BytesIO, original_url: str, platform: str, is_video: bool = True):
    if not CHANNEL_ID:
        return
    try:
        caption = f"{original_url}\n{get_platform_hashtag(platform)}"
        media_data.seek(0)
        if is_video:
            await bot.send_video(chat_id=int(CHANNEL_ID), video=media_data, caption=caption, file_name="vid.mp4")
        else:
            await bot.send_photo(chat_id=int(CHANNEL_ID), photo=media_data, caption=caption)
    except Exception as e:
        logging.error(f"Error sending to channel: {e}")

@bot.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "مرحبًا! أنا بوت لتحميل الوسائط من Instagram و YouTube و TikTok و Facebook و Pinterest.\n"
        "فقط أرسل لي رابط منشور أو فيديو أو Stories.\n"
        "⚠️ الحد الأقصى لحجم الملف للتحميل: 50 ميجابايت."
    )

@bot.on_message(filters.text & filters.private & ~filters.regex(r"^/"))
async def handle_message(client: Client, message: Message):
    user_id = message.from_user.id
    url = message.text
    now = datetime.now()
    
    if user_id in user_requests:
        user_requests[user_id] = [req for req in user_requests[user_id] if now - req < timedelta(minutes=1)]
        if len(user_requests[user_id]) >= MAX_REQUESTS_PER_MINUTE:
            await message.reply_text("لقد تجاوزت حد 5 تحميلات في الدقيقة. يرجى الانتظار.")
            return
        user_requests[user_id].append(now)
    else:
        user_requests[user_id] = [now]

    try:
        result = await process_download(url)
        if result['success']:
            media_data = result['data']
            media_bytes = media_data.getvalue()
            if check_data_size(media_bytes):
                media_data.seek(0)
                if result['is_video']:
                    await message.reply_video(video=media_data)
                else:
                    await message.reply_photo(photo=media_data)
                if result['platform']:
                    channel_media = named_bytesio(media_bytes)
                    await send_to_channel(channel_media, url, result['platform'], result['is_video'])
                    channel_media.close()
            else:
                await message.reply_text("حجم الملف يتجاوز حد 50 ميجابايت.")
            media_data.close()
        else:
            await message.reply_text(result['error'])
    except Exception as e:
        logging.error(f"Error: {e}")
        await message.reply_text("حدث خطأ أثناء معالجة طلبك.")

async def process_download(url: str) -> dict:
    try:
        if url.startswith("https://pin.it/"):
            url = expand_short_url(url) or url

        if "instagram.com" in url:
            if "/stories/" in url:
                media_data = await download_instagram_stories(url.split("/stories/")[1].split("/")[0])
                platform = "Instagram Stories"
            elif "/reel/" in url or "/p/" in url:
                media_data = await download_instagram_media(url)
                platform = "Instagram"
            elif "/highlights/" in url:
                media_data = await download_instagram_highlights(url.split("/highlights/")[1].split("/")[0])
                platform = "Instagram Highlights"
            else:
                return {'success': False, 'error': 'رابط Instagram غير مدعوم.'}
            is_video = True
        elif "youtube.com" in url or "youtu.be" in url:
            media_data = await download_youtube_video(url)
            platform, is_video = "YouTube", True
        elif "tiktok.com" in url:
            media_data = await download_tiktok_video(url)
            platform, is_video = "TikTok", True
        elif "facebook.com" in url:
            media_data = await download_facebook_video(url)
            platform, is_video = "Facebook", True
        elif "pinterest.com" in url:
            download_url = await get_download_url(url)
            if download_url:
                is_video = '.mp4' in download_url
                media_data = await download_video(download_url) if is_video else await download_image(download_url)
                platform = "Pinterest Video" if is_video else "Pinterest Image"
            else:
                return {'success': False, 'error': 'فشل في الحصول على رابط التحميل من Pinterest.'}
        else:
            return {'success': False, 'error': 'منصة غير مدعومة.'}

        if isinstance(media_data, BytesIO):
            return {'success': True, 'data': media_data, 'platform': platform, 'is_video': is_video}
        return {'success': False, 'error': media_data if isinstance(media_data, str) else 'حدث خطأ أثناء التحميل.'}
    except Exception as e:
        return {'success': False, 'error': f'حدث خطأ: {str(e)}'}

async def download_with_ytdlp(url: str) -> BytesIO:
    temp_dir = tempfile.mkdtemp()
    try:
        ydl_opts = {'format': 'best', 'outtmpl': f"{temp_dir}/vid.mp4", 'quiet': True, 'cookiefile': COOKIES_FILE if os.path.exists(COOKIES_FILE) else None}
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        with open(f"{temp_dir}/vid.mp4", 'rb') as f:
            return named_bytesio(f.read())
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

async def download_instagram_media(url: str) -> BytesIO:
    return await download_with_ytdlp(url)

async def download_youtube_video(url: str) -> BytesIO:
    return await download_with_ytdlp(url)

async def download_tiktok_video(url: str) -> BytesIO:
    return await download_with_ytdlp(url)

async def download_facebook_video(url: str) -> BytesIO:
    return await download_with_ytdlp(url)

async def download_instagram_stories(username: str) -> BytesIO:
    temp_dir = tempfile.mkdtemp()
    try:
        L = instaloader.Instaloader()
        if os.path.exists("auth.json"):
            with open("auth.json", "r") as f:
                auth = json.load(f)
            L.login(auth["username"], auth["password"])
        profile = instaloader.Profile.from_username(L.context, username)
        for story in L.get_stories([profile.userid]):
            for item in story.get_items():
                L.download_storyitem(item, target=temp_dir)
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.jpg', '.png')):
                        with open(os.path.join(temp_dir, file), 'rb') as f:
                            return named_bytesio(f.read(), file)
        return "لم يتم العثور على stories."
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

async def download_instagram_highlights(username: str) -> BytesIO:
    temp_dir = tempfile.mkdtemp()
    try:
        L = instaloader.Instaloader()
        if os.path.exists("auth.json"):
            with open("auth.json", "r") as f:
                auth = json.load(f)
            L.login(auth["username"], auth["password"])
        profile = instaloader.Profile.from_username(L.context, username)
        for highlight in L.get_highlights(profile):
            for item in highlight.get_items():
                L.download_storyitem(item, target=temp_dir)
                for file in os.listdir(temp_dir):
                    if file.endswith(('.mp4', '.jpg', '.png')):
                        with open(os.path.join(temp_dir, file), 'rb') as f:
                            return named_bytesio(f.read(), file)
        return "لم يتم العثور على highlights."
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def expand_short_url(short_url: str) -> str:
    try:
        return requests.get(short_url, allow_redirects=True).url
    except:
        return None

async def get_download_url(link: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post('https://www.expertsphp.com/download.php', data={'url': link}) as response:
                return pq(await response.text())('table.table-condensed')('tbody')('td')('a').attr('href')
    except:
        return None

async def download_video(url: str) -> BytesIO:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return named_bytesio(await response.read())
            return f"Failed: {response.status}"

async def download_image(url: str) -> BytesIO:
    return await download_video(url)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/download', methods=['POST'])
def download():
    try:
        url = request.get_json().get('url')
        if not url:
            return jsonify({'error': 'يرجى تقديم رابط'}), 400
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(process_download(url))
        loop.close()
        if result['success']:
            media_data = result['data']
            if not check_data_size(media_data.getvalue()):
                media_data.close()
                return jsonify({'error': 'حجم الملف يتجاوز حد 50 ميجابايت'}), 400
            media_data.seek(0)
            return send_file(media_data, mimetype='video/mp4' if result['is_video'] else 'image/jpeg', as_attachment=True, download_name='vid.mp4')
        return jsonify({'error': result['error']}), 400
    except Exception as e:
        logging.error(f"Error: {e}")
        return jsonify({'error': 'حدث خطأ أثناء معالجة الطلب'}), 500

def run_flask():
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False)

def main():
    logging.info("Starting application...")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info(f"Flask started on port {FLASK_PORT}")
    
    # scheduler = BackgroundScheduler()
    # scheduler.add_job(check_pair_site_availability, 'interval', minutes=1)
    # scheduler.start()
    
    try:
        if BOT_TOKEN and API_ID and API_HASH:
            bot.run()
        else:
            logging.warning("Bot credentials not set. Running web server only.")
            flask_thread.join()
    finally:
        pass
        # scheduler.shutdown()

if __name__ == '__main__':
    main()

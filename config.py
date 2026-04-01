import os
import logging
from dotenv import load_dotenv

# 1. Cấu hình Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# 2. Thông số từ môi trường
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
ACCESS_KEY = os.getenv("API_ACCESS_KEY")
PORT = int(os.getenv("PORT", 8000))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MAX_VIDEO_DURATION = int(os.getenv("MAX_VIDEO_DURATION", 490)) # Mặc định 8p10s
WORKER_DELAY = int(os.getenv("WORKER_DELAY", 10)) # Mặc định 10 giây nghỉ giữa các task
# YT_COOKIES_BASE64 removed

# 3. Metadata cho FastAPI
APP_METADATA = {
    "title": "YouTube to Telegram MP3 Service",
    "description": f"""
    Hệ thống API chuyên nghiệp tải nhạc từ YouTube và gửi sang Telegram bot.
    - **Bảo mật**: Sử dụng API Key trong Header ('x-api-key').
    - **Hiệu năng**: Xử lý trực tiếp trên RAM-disk (Linux/Railway).
    - **Giới hạn**: Video tối đa {MAX_VIDEO_DURATION} giây (~8 phút) để duy trì chất lượng và tính ổn định.
    """,
    "version": "1.0.0"
}

API_KEY_NAME = "x-api-key"

import os
import gc
import yt_dlp
import requests
import json
from datetime import datetime
from supabase import create_client, Client
from config import BOT_TOKEN, CHAT_ID, SUPABASE_URL, SUPABASE_KEY, logger, MAX_VIDEO_DURATION

# 1. Khởi tạo Supabase Client
try:
    if SUPABASE_URL and SUPABASE_KEY:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase Client đã được khởi tạo thành công.")
    else:
        supabase = None
        logger.warning("SUPABASE_URL hoặc SUPABASE_KEY chưa được cấu hình. Supabase sẽ bị vô hiệu hóa.")
except Exception as e:
    supabase = None
    logger.error(f"Lỗi khi khởi tạo Supabase: {e}")

def cleanup_downloads():
    """Dọn dẹp sạch sẽ thư mục downloads khi khởi động app"""
    try:
        path = get_download_dir()
        if os.path.exists(path):
            import shutil
            for filename in os.listdir(path):
                file_path = os.path.join(path, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    logger.error(f"Lỗi khi xóa file {file_path}: {e}")
            logger.info("Đã dọn dẹp thư mục downloads khi khởi động.")
    except Exception as e:
        logger.error(f"Lỗi cleanup_downloads: {e}")

def get_download_dir():
    """Ưu tiên RAM-disk /dev/shm trên Linux (Railway), fallback về disk local"""
    ram_disk = "/dev/shm"
    if os.path.exists(ram_disk) and os.access(ram_disk, os.W_OK):
        path = os.path.join(ram_disk, "ytm-to-tele")
    else:
        path = "downloads"
    
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def save_to_supabase(metadata):
    """Lưu dữ liệu vào Supabase Table 'videos' nếu được cấu hình"""
    if supabase:
        try:
            video_id = metadata.get("videoId")
            logger.info(f"Đang đẩy dữ liệu lên Supabase: {video_id}")
            # Supabase upsert (nếu dùng primary key là videoId) hoặc insert
            response = supabase.table("videos").upsert(metadata).execute()
            logger.info(f"Đã lưu thành công metadata cho video: {video_id}")
            del response # Giải phóng ngay lập tức
        except Exception as e:
            logger.error(f"Lỗi khi lưu lên Supabase: {e}")
    else:
        logger.warning("Không thể lưu Supabase vì Client chưa được khởi tạo.")

def check_video_exists(video_id):
    """Kiểm tra xem video đã tồn tại trong Supabase Table 'videos' chưa. Trả về metadata nếu có."""
    if not supabase:
        return None
    try:
        # Kiểm tra xem có bản ghi nào trùng videoId không
        response = supabase.table("videos").select("*").eq("videoId", video_id).execute()
        data = response.data
        del response # Giải phóng ngay
        if len(data) > 0:
            return data[0]
        return None
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra video tồn tại: {e}")
        return None

def send_to_telegram(file_path, metadata=None):
    """Gửi file MP3 và giải phóng RAM tức thì"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendAudio"
    logger.info(f"Đang gửi file tới Telegram: {file_path}")
    
    response = None
    try:
        # Sử dụng stream=True mặc dù gửi đi nhưng giúp kiểm soát tốt hơn
        with open(file_path, 'rb') as audio:
            payload = {'chat_id': CHAT_ID}
            files = {'audio': audio}
            
            with requests.Session() as session:
                response = session.post(url, data=payload, files=files, timeout=120)
                response.raise_for_status()
                
                resp_json = response.json()
                logger.info(f"Gửi thành công! Phản hồi: {resp_json.get('ok')}")
                
                file_id = resp_json.get("result", {}).get("audio", {}).get("file_id")
                if metadata and file_id:
                    metadata["fileId"] = file_id
                    save_to_supabase(metadata)
                
                # Clear large objects
                del resp_json
    except Exception as e:
        logger.error(f"Lỗi khi gửi Telegram: {e}")
    finally:
        if response is not None:
            response.close()
            del response
        
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Đã giải phóng file: {file_path}")
            except Exception: pass
        
        # Ép giải phóng bộ nhớ ngay sau khi gửi xong file nặng
        gc.collect()

def download_and_convert(video_url, task_id):
    """Xử lý tải và convert MP3 với quản lý RAM tối ưu"""
    download_dir = get_download_dir()
    output_tmpl = os.path.join(download_dir, f"{task_id}.%(ext)s")
    video_metadata = {}

    # Cấu hình tối ưu theo yêu cầu mới
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_tmpl,
        'noplaylist': True,
        'extractor_args': {
            'youtube': ['player_client=android,web_embedded']
        },
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
        'cachedir': False,
        'noprogress': True,
        'logtostderr': False,
        'no_entry_info': False,
        'nocheckcertificate': True,
    }

    try:
        # Sử dụng DUY NHẤT một context manager để đảm bảo đóng handle, subprocesses
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 1. Trích xuất info (không tải)
            info = ydl.extract_info(video_url, download=False)
            if not info:
                return

            duration = info.get('duration', 0)
            video_id = info.get('id', task_id)

            # Kiểm tra cache
            if check_video_exists(video_id):
                logger.info(f"Video {video_id} đã có. Bỏ qua.")
                return

            # Giới hạn duration
            if duration > MAX_VIDEO_DURATION:
                logger.warning(f"Video quá dài: {duration}s (Max: {MAX_VIDEO_DURATION}s)")
                return

            # 2. Xây dựng metadata tối giản ngay lập tức
            video_metadata = {
                "videoId": video_id,
                "title": info.get("title"),
                "artist": info.get("uploader") or info.get("creator"),
                "duration": duration,
                "createdAt": datetime.utcnow().isoformat() + "Z"
            }

            # XÓA TRUYỆT ĐỂ info object cực lớn ngay sau khi lấy đủ metadata
            info.clear()
            del info
            gc.collect()

            # 3. Tiến hành tải (sử dụng chính context manager ydl hiện tại)
            ydl.download([video_url])

        # 4. Gửi đi sau khi ydl đã đóng context (__exit__)
        file_path = os.path.join(download_dir, f"{task_id}.mp3")
        if os.path.exists(file_path):
            send_to_telegram(file_path, video_metadata)
            
    except Exception as e:
        logger.error(f"Lỗi download_and_convert: {e}")
    finally:
        # Dọn dẹp tàn dư file rác (.part, .webm...)
        try:
            for f in os.listdir(download_dir):
                if f.startswith(task_id):
                    os.remove(os.path.join(download_dir, f))
        except Exception: pass
        
        # Cleanup cuối cùng
        video_metadata = None
        gc.collect()

def search_youtube_videos(query: str, max_results: int = 10):
    """Tìm kiếm video YouTube, lọc theo MAX_VIDEO_DURATION và lấy 10 bài"""
    # Lấy nhiều hơn một chút (vd 20 bài) phòng trường hợp vài bài đầu quá dài bị lọc bỏ
    search_query = f"ytsearch20:{query}"
    
    search_opts = {
        'extract_flat': True, # Cực kỳ quan trọng: Chỉ lấy metadata nhanh, KHÔNG phân tích định dạng stream
        'quiet': True,
        'no_warnings': True,
    }
    
    results = []
    try:
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if not info or 'entries' not in info:
                return []
                
            entries = info['entries']
            
            for entry in entries:
                # Nếu không có duration, có thể là Livestream hoặc lỗi, nên bỏ qua
                duration = entry.get('duration')
                if not duration:
                    continue
                    
                # Áp dụng bộ lọc
                if duration <= MAX_VIDEO_DURATION:
                    results.append({
                        "id": entry.get("id"),
                        "title": entry.get("title"),
                        "artist": entry.get("uploader") or entry.get("channel") or "Unknown",
                        "duration": duration
                    })
                
                # Chiết xuất đủ số lượng yêu cầu thì dừng
                if len(results) >= max_results:
                    break
                    
    except Exception as e:
        logger.error(f"Lỗi khi tìm kiếm YouTube: {e}")
        
    return results

import os
import random
import uuid
import uvicorn
import re
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Depends, Security, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import APP_METADATA, ACCESS_KEY, API_KEY_NAME, logger, PORT, WORKER_DELAY
import base64
from services import download_and_convert, check_video_exists, cleanup_downloads, search_youtube_videos

# 1. Cấu hình Rate Limiter (Chống Spam)
limiter = Limiter(key_func=get_remote_address)

# 2. Cấu hình Hàng đợi (Queue) và Tracker Chống Trùng Lặp
task_queue = asyncio.Queue()
processing_videos = set()

async def worker():
    """Worker chạy ngầm để tiêu thụ các task trong hàng đợi"""
    while True:
        try:
            url, task_id, video_id = await task_queue.get()
            logger.info(f"Bắt đầu xử lý {url} - Task ID: {task_id}")
            
            # Chạy hàm đồng bộ trong thread pool riêng để không block Event Loop
            await asyncio.to_thread(download_and_convert, url, task_id)
            
            task_queue.task_done()
            processing_videos.discard(video_id) # Giải phóng ID khỏi danh sách đang xử lý
            
            # Giới hạn nghỉ random để lách bot (Từ 2s đến WORKER_DELAY)
            sleep_time = random.uniform(2, WORKER_DELAY)
            logger.info(f"Chờ ngẫu nhiên {sleep_time:.2f} giây trước nhiệm vụ tiếp theo...")
            await asyncio.sleep(sleep_time)
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Lỗi trong Worker: {e}")
            try:
                processing_videos.discard(video_id)
                task_queue.task_done()
            except Exception: pass
            
            # Nếu lỗi vẫn nên nghỉ ngẫu nhiên để an toàn
            sleep_time = random.uniform(2, WORKER_DELAY)
            await asyncio.sleep(sleep_time)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Dọn dẹp rác từ lần chạy trước (nếu có)
    cleanup_downloads()
    
    # 3. Khởi tạo 1 worker background duy nhất để đảm bảo an toàn tuyệt đối cho RAM (512MB)
    workers = [asyncio.create_task(worker()) for _ in range(1)]
    logger.info("Đã khởi động background worker duy nhất (Queue Consumer).")
    yield
    # Cleanup khi app tắt
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)

# 3. Cấu hình FastAPI & Metadata
app = FastAPI(**APP_METADATA, lifespan=lifespan)

# Bật Rate Limit Exception Handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Cấu hình CORS middleware, chặn truy cập lạ
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# 4. Cấu hình Security cho Swagger
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# 5. Dependency kiểm tra API Key (Sử dụng Header 'x-api-key' chuẩn REST)
async def get_api_key(api_key: str = Security(api_key_header)):
    if not ACCESS_KEY or api_key != ACCESS_KEY:
        logger.warning(f"Truy cập trái phép với key: {api_key}")
        raise HTTPException(
            status_code=403,
            detail="Bạn cần cung cấp API Key hợp lệ trong Header 'x-api-key'."
        )
    return api_key

# 6. Các API Endpoints
@app.get("/process", tags=["Tiến trình"])
@limiter.limit("5/minute")
async def process_video(
    request: Request,
    video_id: str = Query(..., description="ID của video Youtube (ví dụ: dQw4w9WgXcQ)"),
    api_key: str = Depends(get_api_key)
):
    """
    Nhận Video ID, tự động chuyển thành link và xử lý ngầm.
    - Hàng đợi chống sập Memory.
    - Rate Limit chống Spam API (5 request/phút).
    """
    
    # Chống tấn công Injection: Validate Video ID chuẩn Youtube
    if not re.match(r"^[a-zA-Z0-9_-]{11}$", video_id):
        raise HTTPException(status_code=400, detail="Video ID không hợp lệ.")
        
    # Giới hạn hàng đợi, chống nghẽn bộ nhớ do bị spam
    if task_queue.qsize() > 50:
        raise HTTPException(status_code=503, detail="Hệ thống đang quá tải, vòng đợi đã đầy.")
    
    # Phân công task cho worker
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # 1. Kiểm tra video đã có trong database chưa
    existing_video = check_video_exists(video_id)
    if existing_video:
        logger.info(f"Video {video_id} đã tồn tại trong database. Trả về metadata.")
        return {
            "status": "Success", 
            "video_id": video_id,
            "message": "Video đã được xử lý trước đó.",
            "data": existing_video
        }
        
    # 2. Kiểm tra xem video có đang được xử lý trong hàng đợi không
    if video_id in processing_videos:
        logger.warning(f"Video {video_id} đang được xử lý. Từ chối yêu cầu trùng lặp.")
        return {
            "status": "Processing",
            "video_id": video_id,
            "message": "Video này đang được hệ thống xử lý. Vui lòng thử lại sau vài phút."
        }

    # 3. Nếu chưa có, đưa vào hàng đợi xử lý ngầm
    task_id = str(uuid.uuid4())
    
    processing_videos.add(video_id) # Đánh dấu đang xử lý
    await task_queue.put((url, task_id, video_id))
    queue_pos = task_queue.qsize()
    
    return {
        "status": "Accepted", 
        "video_id": video_id,
        "message": f"ID {video_id} đã được đưa vào hàng đợi.",
        "queue_position": queue_pos
    }

@app.get("/search", tags=["Tìm kiếm"])
@limiter.limit("15/minute")
async def search_video(
    request: Request,
    q: str = Query(..., description="Từ khóa hoặc tên bài hát cần tìm"),
    api_key: str = Depends(get_api_key)
):
    """
    Tìm kiếm danh sách video từ YouTube theo từ khóa.
    Tự động bỏ qua các video livestream hoặc vượt quá giới hạn độ dài.
    """
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Vui lòng nhập từ khóa tìm kiếm.")
        
    results = await asyncio.to_thread(search_youtube_videos, query, 10)
    
    return {
        "status": "Success",
        "query": query,
        "count": len(results),
        "data": results
    }

@app.get("/health", tags=["Hệ thống"])
async def health_check():
    """Kiểm tra trạng thái server."""
    return {"status": "ok", "queue_size": task_queue.qsize()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
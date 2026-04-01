# YouTube to Telegram MP3 API Documentation

Tài liệu này cung cấp chi tiết cách tích hợp với hệ thống backend để tìm kiếm và yêu cầu tải nhạc từ YouTube sang Telegram.

## 1. Thông tin chung (General Info)

- **Base URL**: `http://your-server-address:8000`
- **Authentication**: Tất cả các request yêu cầu API Key gửi trong Header.
  - Header Name: `x-api-key`
  - Value: `YOUR_API_KEY_HERE` (Lấy từ file `.env`)

---

## 2. API Endpoints

### 2.1. Tìm kiếm video (Search)

Sử dụng endpoint này để hiển thị danh sách kết quả cho người dùng chọn trước khi tải.

- **Endpoint**: `/search`
- **Method**: `GET`
- **Query Parameters**:
  - `q` (String, required): Từ khóa tìm kiếm (Tên bài hát, ca sĩ...).
- **Response (200 OK)**:

```json
{
  "status": "Success",
  "query": "da lab",
  "count": 10,
  "data": [
    {
      "id": "R3trO4a49go",
      "title": "Thức Giấc - Da LAB (Official Music Video)",
      "artist": "Da LAB Official",
      "duration": 291
    }
  ]
}
```

- _Lưu ý: Danh sách trả về đã tự động lọc bỏ các video dài vượt quá giới hạn cấu hình và các buổi livestream._

---

### 2.2. Yêu cầu xử lý & Tải nhạc (Process)

Sử dụng endpoint này khi người dùng nhấn "Tải về" một video cụ thể.

- **Endpoint**: `/process`
- **Method**: `GET`
- **Query Parameters**:
  - `video_id` (String, required): ID của video YouTube (ví dụ: `R3trO4a49go`).
- **Response (202 Accepted)** - Khi video chưa từng được xử lý và bắt đầu vào hàng đợi:

```json
{
  "status": "Accepted",
  "video_id": "R3trO4a49go",
  "message": "ID R3trO4a49go đã được đưa vào hàng đợi.",
  "queue_position": 1
}
```

- **Response (200 OK)** - Khi video đã được xử lý từ trước đó (trả về từ Cache):

```json
{
  "status": "Success",
  "video_id": "R3trO4a49go",
  "message": "Video đã được xử lý trước đó.",
  "data": {
    "videoId": "R3trO4a49go",
    "fileId": "AgACAgEAA...",
    "title": "Thức Giấc",
    "artist": "Da LAB",
    "duration": 291
  }
}
```

- **Response (200 OK)** - Khi video đang nằm trong hàng đợi hoặc đang tải:

```json
{
  "status": "Processing",
  "video_id": "R3trO4a49go",
  "message": "Video này đang được hệ thống xử lý. Vui lòng thử lại sau vài phút."
}
```

---

## 3. Các mã lỗi thường gặp (Error Codes)

- **400 Bad Request**: Video ID không hợp lệ.
- **403 Forbidden**: API Key thiếu hoặc sai.
- **429 Too Many Requests**: Request quá nhanh (Rate limit: 5 req/phút cho process, 15 req/phút cho search).
- **503 Service Unavailable**: Hàng đợi (Queue) quá tải (đầy hơn 50 task).

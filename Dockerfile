FROM python:3.10-slim

# Cài đặt FFmpeg để xử lý MP3 và Node.js để yt-dlp xử lý JS của Youtube
RUN apt-get update && \
    apt-get install -y ffmpeg nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy các file thư viện và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code vào container
COPY . .

# Tạo thư mục downloads trong trường hợp không chạy trên RAM-disk
RUN mkdir -p downloads

# Cài đặt port mặc định (Railway sẽ tự động ghi đè qua biến PORT)
ENV PORT=8000

# Chạy ứng dụng
CMD ["python", "main.py"]
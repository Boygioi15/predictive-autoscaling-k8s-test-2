# Sử dụng base image chính chủ
FROM locustio/locust:latest

# Thiết lập thư mục làm việc trong container
WORKDIR /mnt/locust

# Copy file yêu cầu (nếu có) và cài đặt trước
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code (bao gồm folder users và locustfile.py) vào container
COPY . .

# (Tùy chọn) Command mặc định khi chạy container
# Tuy nhiên ta thường set command trong docker-compose nên dòng này có thể bỏ qua
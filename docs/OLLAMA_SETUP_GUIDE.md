# HƯỚNG DẪN CÀI ĐẶT OLLAMA CHO WINDOWS

## Bước 1: Tải Ollama
1. Truy cập: https://ollama.com/download/windows
2. Tải file cài đặt OllamaSetup.exe
3. Chạy file cài đặt với quyền Administrator

## Bước 2: Cài đặt Model
Mở Command Prompt hoặc PowerShell và chạy:

```bash
# Cài đặt model phi3 (khuyến nghị - tối ưu cho conversation)
ollama run phi3:3.8b

# Hoặc model nhỏ gọn (khuyến nghị cho máy yếu)
ollama run llama3.2:1b

# Hoặc model cân bằng hiệu suất/chất lượng
ollama run llama3.2:3b

# Hoặc model chất lượng cao (cần máy mạnh)
ollama run llama3:7b
```

## Bước 3: Kiểm tra cài đặt
```bash
# Kiểm tra service đang chạy
ollama list

# Test API
curl http://localhost:11434/api/tags
```

## Bước 4: Nếu gặp lỗi

### Lỗi 1: "ollama: command not found"
- Restart máy tính
- Hoặc thêm Ollama vào PATH:
  - Windows + R → sysdm.cpl → Advanced → Environment Variables
  - Thêm C:\Users\%USERNAME%\AppData\Local\Programs\Ollama vào PATH

### Lỗi 2: "Connection refused"
```bash
# Khởi động service thủ công
ollama serve
```

### Lỗi 3: Model quá lớn
- Sử dụng model nhỏ hơn: llama3.2:1b
- Giải phóng RAM bằng cách đóng các ứng dụng khác

## Bước 5: Test với Voice Assistant
1. Đảm bảo Ollama đang chạy
2. Chạy test script: `python test_conversation.py`
3. Nếu thấy "Using Ollama for conversations" → thành công
4. Nếu thấy "Using pattern matching" → Ollama chưa kết nối được

## Troubleshooting

### Windows Defender/Antivirus
- Thêm Ollama vào whitelist
- Cho phép Ollama qua Firewall

### Cổng bị chiếm
```bash
# Kiểm tra cổng 11434
netstat -an | findstr :11434

# Nếu bị chiếm, kill process hoặc restart
```

### Không đủ RAM
- Model 1B cần ~2GB RAM
- Model 3B cần ~4GB RAM  
- Model 7B cần ~8GB RAM

## Cấu hình tối ưu cho các loại máy

### Máy yếu (4GB RAM)
```bash
ollama run llama3.2:1b
```

### Máy trung bình (8GB RAM) - Khuyến nghị
```bash
ollama run phi3:3.8b
```

### Máy mạnh (16GB+ RAM)
```bash
ollama run llama3:7b
```

## Sử dụng GPU (Nếu có)
Ollama tự động detect GPU. Để check:
```bash
ollama ps
```

Nếu hiện "GPU" trong output → đang dùng GPU
Nếu hiện "CPU" → đang dùng CPU only

## Alternative: Sử dụng mà không cần Ollama
Nếu không cài được Ollama, hệ thống sẽ tự động fallback về pattern matching. Vẫn có conversation nhưng không thông minh bằng.

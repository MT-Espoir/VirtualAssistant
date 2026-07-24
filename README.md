# Trợ lý ảo điều khiển bằng giọng nói (Tiếng Việt)

Trợ lý ảo chạy trên máy tính, nghe lệnh tiếng Việt qua micro rồi thực thi:
mở/đóng ứng dụng, điều chỉnh âm lượng & độ sáng, tìm kiếm web/YouTube, tắt/khởi
động lại máy, và trò chuyện tự nhiên qua LLM cục bộ (Ollama).

> ⚠️ **Trạng thái:** dự án đang phát triển/học tập. Một số thành phần (module học
> tính cách) là thử nghiệm và chưa được nối vào luồng chính. Xem [Hạn chế đã biết](#hạn-chế-đã-biết).

## Tính năng

- 🎙️ **Nhận dạng giọng nói** tiếng Việt (Google Speech Recognition; có hỗ trợ Whisper).
- 🧠 **Phân loại ý định** (intent) + trích xuất thực thể để hiểu lệnh.
- 🖥️ **Điều khiển hệ thống:** mở/đóng app, âm lượng, độ sáng, shutdown/restart.
- 🌐 **Web & YouTube:** tìm kiếm, mở trang, phát video/nhạc.
- 💬 **Hội thoại** qua LLM cục bộ (Ollama) với fallback pattern-matching khi không có LLM.
- 🔊 **Phản hồi bằng giọng nói** (gTTS / pyttsx3).

## Cấu trúc thư mục

```
src/
├── main.py                 # Điểm vào: vòng lặp nghe → hiểu → thực thi → nói
├── audio/                  # Ghi âm (recorder) & tổng hợp giọng nói (TTS)
├── recognition/            # Nhận dạng giọng nói (STT)
├── nlp/                    # Phân loại intent & trích xuất thực thể
├── llm/                    # Ollama client, conversation engine, pattern matcher
├── actions/                # Hành động: app, hệ thống, tìm kiếm web/YouTube
├── components/             # user profile, feedback, personality (thử nghiệm), scheduler
├── utils/                  # config, logger, data loader/saver
├── models/                 # Cache model tải về (KHÔNG commit — xem .gitignore)
├── config.py qua utils/    # Cấu hình tập trung
└── requirements.txt
docs/                       # Tài liệu chi tiết theo từng phần
```

## Yêu cầu

- **Python 3.9+** (đã kiểm thử với 3.9).
- **Hệ điều hành:** Windows (một số điều khiển hệ thống dùng `pycaw`/`screen-brightness-control` đặc thù Windows).
- **Micro** hoạt động.
- **[Ollama](https://ollama.com)** (tùy chọn) để bật trò chuyện bằng LLM. Không có Ollama,
  trợ lý vẫn chạy và trò chuyện bằng pattern-matching.

## Cài đặt

```bash
# 1. Tạo môi trường ảo (khuyến nghị)
python -m venv .venv
# Windows:
.venv\Scripts\activate

# 2. Cài phụ thuộc
pip install -r src/requirements.txt

# 3. (Tùy chọn) Cài Ollama + tải model dùng cho hội thoại
#    Xem docs/OLLAMA_SETUP_GUIDE.md
ollama pull phi3:3.8b
```

## Chạy

```bash
cd src
python main.py
```

Nói lệnh trực tiếp (ví dụ): *"mở chrome"*, *"tăng âm lượng 20%"*, *"tìm mèo con trên youtube"*,
*"xin chào"*. Nhấn `Ctrl+C` để thoát.

## Cấu hình

Mọi tham số nằm ở [`src/utils/config.py`](src/utils/config.py) và có thể override bằng
biến môi trường (hoặc file `.env` nếu cài `python-dotenv`). Sao chép mẫu:

```bash
cp src/.env.example src/.env
```

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `SAMPLE_RATE` | `16000` | Tần số lấy mẫu audio |
| `STT_LANGUAGE` | `vi-VN` | Ngôn ngữ nhận dạng giọng nói |
| `STT_ENGINE` | `google` | Engine STT |
| `TTS_ENGINE` | `gtts` | Engine tổng hợp giọng nói |
| `TTS_LANGUAGE` | `vi` | Ngôn ngữ giọng nói |
| `OLLAMA_URL` | `http://localhost:11434` | Địa chỉ Ollama |
| `OLLAMA_MODEL` | `phi3:3.8b` | Model LLM cho hội thoại |
| `LOG_LEVEL` | `INFO` | Mức log (DEBUG/INFO/WARNING/ERROR) |
| `LOG_FILE` | *(rỗng)* | Đường dẫn file log; rỗng = chỉ log console |

## Kiến trúc: tách "bộ não" khỏi I/O

Logic hiểu lệnh nằm ở [`core/command_router.py`](src/core/command_router.py)
(`CommandRouter`), **không phụ thuộc micro/loa**. `main.py` chỉ là lớp I/O mỏng.
Các hành động hệ thống được gói sau [`core/actions_facade.py`](src/core/actions_facade.py)
để có thể thay bằng bản giả khi test. Nhờ vậy có thể kiểm thử định tuyến lệnh
mà không cần phần cứng.

## Testing

```bash
pip install -r requirements-dev.txt
pytest            # chạy toàn bộ test trong tests/
```

Test cho `CommandRouter` mock toàn bộ phụ thuộc — không mở app thật, không cần micro.

## Tài liệu chi tiết

Xem thư mục [`docs/`](docs/):

- `OLLAMA_SETUP_GUIDE.md` — cài đặt Ollama.
- `PHASE1_CONVERSATION_UPGRADE_GUIDE.txt` — nâng cấp hội thoại.
- `JSON_FILES_REQUIREMENTS.txt` — mô tả các file dữ liệu JSON.
- `AI_WORKFLOW_CHI_TIET.txt`, `PERSONALITY_LEARNER_DETAILED_GUIDE.txt`,
  `MUSIC_GENRE_PREDICTION_GUIDE.txt` — thiết kế các thành phần AI.

## Hạn chế đã biết

- **PhoBERT được tải nhưng chưa dùng để phân loại:** `NLPProcessor` hiện phân loại
  intent bằng so khớp từ khóa; embedding của PhoBERT chưa được khai thác.
- **Module `personality` là thử nghiệm:** chạy được ở chế độ rule-based nhưng chưa
  nối vào `main.py`; phần "AI enhancer" đang thiếu source.
- **`src/test_pure_ai_reasoning.py`** tham chiếu module đã mất → sẽ lỗi khi chạy.
- Điều khiển hệ thống phụ thuộc thư viện đặc thù **Windows**.

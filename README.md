# Trợ lý AI điều khiển máy tính bằng tiếng Việt (Agent)

Trợ lý chạy trên Windows: nghe/gõ yêu cầu tiếng Việt, một **LLM agent tự gọi công
cụ** (tool-calling) để thực thi — mở/đóng ứng dụng, chỉnh âm lượng & độ sáng, tìm
kiếm web/YouTube, tắt/khởi động lại máy — rồi trả lời bằng giọng nói.

## Tính năng

- 🎙️ **Nhập bằng giọng nói** (STT: Google / Whisper) hoặc **văn bản** (`agent_cli.py`).
- 🧠 **Agent LLM tool-calling:** LLM tự hiểu câu nói và gọi đúng công cụ với đúng
  tham số — không còn đếm từ khóa, hiểu được cả câu chưa gặp.
- 🖥️ **Điều khiển hệ thống:** mở/đóng app, âm lượng, độ sáng, shutdown/restart.
- 🌐 **Web & YouTube:** tìm kiếm, mở trang, phát video/nhạc.
- 🔊 **Phản hồi bằng giọng nói** (gTTS / pyttsx3).

## Cấu trúc thư mục

```
src/
├── main.py                 # Điểm vào: I/O (micro/loa) quanh Agent
├── agent_cli.py            # Chạy Agent bằng văn bản (không cần micro)
├── core/                   # "Bộ não" (tách khỏi I/O & nhà cung cấp LLM)
│   ├── agent.py            #   vòng lặp tool-calling
│   ├── tools.py            #   định nghĩa tool + registry (JSON schema)
│   ├── llm_client.py       #   interface LLM + ClaudeClient
│   └── actions_facade.py   #   gói các hành động (seam để test)
├── audio/                  # Ghi âm (recorder) & tổng hợp giọng nói (TTS)
├── recognition/            # Nhận dạng giọng nói (STT)
├── actions/                # Hành động thật: app, hệ thống, web/YouTube
├── components/             # user profile, feedback, personality (thử nghiệm), scheduler
├── utils/                  # config, logger, data loader/saver
└── requirements.txt
tests/                      # pytest (agent core — không cần micro/API key)
docs/                       # Tài liệu chi tiết + ARCHITECTURE.md
```

## Yêu cầu

- **Python 3.9+**.
- **Windows** (điều khiển hệ thống dùng `pycaw`/`screen-brightness-control`).
- **Micro** (chỉ khi chạy `main.py`; `agent_cli.py` không cần).
- **LLM cho agent** — chọn một:
  - **Ollama (local, mặc định):** cài [Ollama](https://ollama.com) + `ollama pull qwen2.5:3b-instruct`
    (model phải hỗ trợ tool-calling: `llama3.1`, `qwen2.5`, `mistral-nemo`...).
  - **Claude API:** đặt `ANTHROPIC_API_KEY` và `LLM_PROVIDER=claude`.

## Cài đặt

```bash
# 1. Môi trường ảo (khuyến nghị)
python -m venv .venv
.venv\Scripts\activate          # Windows

# 2. Phụ thuộc
pip install -r src/requirements.txt

# 3. LLM local (mặc định): cài Ollama rồi kéo model
ollama pull qwen2.5:3b-instruct

#    (Tùy chọn) dùng Claude thay vì local:
#    copy src\.env.example src\.env  → đặt LLM_PROVIDER=claude, ANTHROPIC_API_KEY=sk-ant-...
```

## Chạy

```bash
cd src
python agent_cli.py   # chế độ văn bản (dễ thử nhất, không cần micro)
python main.py        # chế độ giọng nói (cần micro)
```

Ví dụ yêu cầu: *"mở chrome"*, *"tăng âm lượng 20%"*, *"mở chrome rồi giảm độ sáng"*,
*"tìm mèo con trên youtube"*.

## Cấu hình

Mọi tham số ở [`src/utils/config.py`](src/utils/config.py), override được qua biến
môi trường / file `.env` (cần `python-dotenv`). Mẫu: [`src/.env.example`](src/.env.example).

| Biến | Mặc định | Ý nghĩa |
|------|----------|---------|
| `LLM_PROVIDER` | `ollama` | Nhà cung cấp LLM: `ollama` (local) hoặc `claude` |
| `OLLAMA_URL` | `http://localhost:11434` | Địa chỉ Ollama (khi provider=ollama) |
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct` | Model local (phải hỗ trợ tool-calling) |
| `ANTHROPIC_API_KEY` | *(khi provider=claude)* | API key Claude |
| `LLM_MODEL` | `claude-opus-4-8` | Model Claude (khi provider=claude) |
| `SAMPLE_RATE` | `16000` | Tần số lấy mẫu audio |
| `STT_LANGUAGE` | `vi-VN` | Ngôn ngữ nhận dạng giọng nói |
| `STT_ENGINE` | `google` | Engine STT |
| `TTS_ENGINE` | `gtts` | Engine tổng hợp giọng nói |
| `TTS_LANGUAGE` | `vi` | Ngôn ngữ giọng nói |
| `LOG_LEVEL` | `INFO` | Mức log (DEBUG/INFO/WARNING/ERROR) |
| `LOG_FILE` | *(rỗng)* | File log; rỗng = chỉ log console |

## Kiến trúc: agent tách khỏi I/O

Logic hiểu lệnh nằm ở [`core/agent.py`](src/core/agent.py) — vòng lặp tool-calling,
**không phụ thuộc micro/loa và không phụ thuộc nhà cung cấp LLM**. `main.py` chỉ là
lớp I/O mỏng. Các hành động hệ thống gói sau [`core/actions_facade.py`](src/core/actions_facade.py)
và phơi ra dưới dạng tool trong [`core/tools.py`](src/core/tools.py). Nhờ dependency
injection, có thể kiểm thử toàn bộ vòng lặp bằng LLM giả.
## Testing

```bash
pip install -r requirements-dev.txt
pytest            # toàn bộ test trong tests/
```

Test cho Agent/tools mock LLM và actions — **không mở app thật, không cần micro
hay API key**.

## Tài liệu chi tiết

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — tầm nhìn & sơ đồ kiến trúc.
- [docs/](docs/) — các tài liệu thiết kế cũ (một số phản ánh giai đoạn trước khi
  chuyển sang agent).

## Hạn chế đã biết

- **Chất lượng tool-calling phụ thuộc model local:** cần model hỗ trợ tool-calling
  (llama3.1/qwen2.5...); model nhỏ có thể gọi tool kém chính xác hơn Claude API.
- **Module `personality`** là thử nghiệm, chạy rule-based nhưng chưa nối vào luồng
  chính; phần "AI enhancer" thiếu source.
- Điều khiển hệ thống phụ thuộc thư viện đặc thù **Windows**.

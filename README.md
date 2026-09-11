# Trợ lý ảo tiếng Việt cho Windows

> Nói một câu, máy tính làm việc đó. Trợ lý chạy ngay trên máy bạn, nghe tiếng Việt, tự chọn
> công cụ để thực thi, rồi trả lời bằng giọng nói — kèm một avatar nhân vật đổi biểu cảm
> theo tâm trạng.

![Tổng quan một lượt trò chuyện](assets/overview.svg)

Khác với trợ lý dò từ khoá, hệ thống này dùng **LLM tự gọi công cụ** (tool-calling): bạn nói
kiểu gì cũng được, model tự hiểu và chọn đúng việc cần làm với đúng tham số. Nói *"mở Chrome
rồi tăng âm lượng lên 60"* thì nó làm **cả hai việc**, không dừng ở việc đầu.

---

## Trợ lý làm được gì

**🖥️ Điều khiển máy tính**
Mở/đóng ứng dụng, liệt kê và chuyển cửa sổ, chỉnh âm lượng và độ sáng, xem RAM/CPU/ổ đĩa/pin.

**🌐 Web & YouTube**
Tìm kiếm rồi **đọc danh sách kết quả** cho bạn chọn số, mở trang, phát nhạc/video, tra Wikipedia.

**📍 Tìm chỗ theo nhu cầu**
Không chỉ tra tên: *"tìm quán cà phê yên tĩnh, nhiều cây, gần đây"* — trợ lý đọc nhiều nguồn
web, đối chiếu rồi trưng kết quả kèm trích dẫn lên panel để bạn tự kiểm bằng mắt.

**🎬 Điều khiển Chrome**
Tạm dừng / phát tiếp / chuyển bài, chỉnh âm lượng video, quản lý tab — qua một tiện ích Chrome
riêng nói chuyện với trợ lý.

**📧 Email & Lịch Google**
Đọc mail chưa đọc, xem lịch hôm nay, và **tự soạn nội dung mail** từ ý định của bạn (*"viết mail
xin nghỉ phép gửi sếp"*) — lưu nháp hoặc gửi sau khi bạn xác nhận.

**📇 Danh bạ**
Nhớ email theo tên, nên lần sau chỉ cần nói *"gửi cho sếp"* thay vì đọc cả địa chỉ.

**⏰ Nhắc việc & tự động**
Phân biệt rõ *"nhắc tôi uống nước lúc 3h"* (chỉ nhắc) với *"22h30 mở YouTube"* (tự làm thật).
Có danh sách việc cần làm, quy trình nhiều bước (routine), bản tin sáng và cảnh báo pin yếu.

**🧠 Trí nhớ**
Nhớ tên, cách xưng hô, sở thích qua mọi phiên. Quan trọng hơn: **phân biệt việc đã xong với
việc sắp tới** — buổi phỏng vấn lúc trưa thì tối nó biết là chuyện đã qua, không nhắc như sắp
diễn ra nữa. Ngoài những gì bạn **nói ra**, nó còn tự đếm **hành vi lặp lại**: mở Chrome bảy
lần, nghe một bài bốn lần thì đó là thói quen, dù bạn chưa từng nói mình thích.

**🎭 Nhân cách & biểu cảm**
Tính cách chỉnh được bằng lời (*"vui tính hơn"*, *"nghiêm túc hơn"*), tâm trạng thay đổi dần
theo cuộc trò chuyện và **dẫn biểu cảm avatar**: vui, buồn, đang nghĩ, đang nói — và ngượng
khi bị khen hay trêu. Càng dùng càng xưng hô thân hơn.

**🗣️ Giọng riêng** *(tuỳ chọn)*
Ngoài giọng máy sẵn có, trợ lý nói được bằng **giọng bạn tự clone từ ~3 giây thu âm**
(VieNeu-TTS), không cần huấn luyện gì.

**🖼️ Đọc màn hình** *(tắt mặc định)*
Chụp màn hình, tìm chữ bằng OCR, cuộn trang. Chỉ chạy khi bạn bật **và** đang dùng LLM trên máy.

---

## Alice — nhân vật trợ lý

| Rảnh | Đang nói | Đang nghĩ | Ngượng | Buồn |
|:---:|:---:|:---:|:---:|:---:|
| <img src="src/ui/image/default_emotion.png" width="150" alt="Alice lúc rảnh"> | <img src="src/ui/image/talk_emotion.png" width="150" alt="Alice đang nói"> | <img src="src/ui/image/thinking_emotion.png" width="150" alt="Alice đang nghĩ"> | <img src="src/ui/image/shy_emotion.png" width="150" alt="Alice ngượng"> | <img src="src/ui/image/sad_emotion.png" width="150" alt="Alice buồn"> |

Mặc định đánh thức bằng *"trợ lý"*; muốn gọi thẳng tên thì thêm `alice` vào `WAKE_WORDS`
trong `src/.env`.

---

## Kiến trúc

![Kiến trúc chi tiết](assets/architecture.svg)

Mỗi lượt đi qua năm chặng. Ba điểm đáng chú ý trong thiết kế:

**Lệnh quen thuộc không tốn LLM.** Chỉnh âm lượng, tạm dừng nhạc, cuộn màn hình… được nhận
dạng thẳng và chạy ngay — vừa tức thì, vừa chắc chắn chạy kể cả khi model lười gọi công cụ.

**Việc khó hoàn tác luôn phải hỏi.** Xoá, đóng ứng dụng, gửi mail đều bị chặn lại ở một cổng
xác nhận **nằm trong code**, nên nghe nhầm hay model hiểu sai cũng không lỡ tay.

**Bộ nhớ hai tầng, có mốc thời gian.** Trợ lý luôn biết bây giờ là mấy giờ, và tách sự thật
bền vững (tên, sở thích) khỏi sự kiện có hạn (cuộc hẹn) — nhờ vậy nó không nhắc mãi một việc
đã xong.

### Cây thư mục

Các phần chính (lược bớt vài thư mục cũ chưa dùng tới):

```
src/
├── app.py            Điểm vào: ghép agent + avatar + giọng nói + dịch vụ nền
├── agent/            Vòng lặp tool-calling, bề mặt tool, nhân cách & tâm trạng
├── features/         Đăng ký công cụ theo nhóm việc: hệ thống, web, Chrome,
│                     mail/lịch, việc cần làm, địa điểm, thời tiết, màn hình
├── actions/          Hành động thật đứng sau: điều khiển máy, web, thời tiết
├── memory/           Nhớ ngắn/dài hạn, thói quen, nhật ký kết quả, cảnh báo tấn công
├── research/         Lõi đọc nhiều nguồn web rồi đối chiếu (dùng cho tìm địa điểm)
├── llm/              Kết nối Gemini / Claude / Ollama + nội dung prompt
├── voice/            Thu tiếng, nhận dạng, đọc thành tiếng (kể cả giọng clone), lệnh nhanh
├── services/         Lịch nhắc, việc cần làm, danh bạ, cầu nối Chrome & Google
├── ui/               Cửa sổ avatar (ảnh nhân vật) + panel HUD dùng chung
├── utils/            Cấu hình, log, chuẩn hoá văn bản, mô tả thứ sắp rời máy
└── evals/            Đo độ tin cậy chọn công cụ + chi phí mỗi lượt
mcp_servers/          Máy chủ Gmail + Lịch Google (chạy local)
packaging/            Launcher 1-icon + script cắt ảnh avatar và icon
chrome_extension/     Tiện ích Chrome (nằm ngoài repo)
tests/                1168 test, không cần micro hay API key
```

`features/` khai báo *model được thấy công cụ nào*, `actions/` là phần thật sự chạm vào máy —
tách ra để thêm/bớt công cụ không phải đụng vào code hành động.

---

## Cài đặt

**Cần có:** Python 3.9+ · Windows · micro (tuỳ chọn — không có thì gõ phím)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r src/requirements.txt
```

Rồi chọn **một** nguồn LLM và tạo file `src/.env`:

<details>
<summary><b>Gemini</b> — nhanh, miễn phí, khuyến nghị</summary>

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=<khoá của bạn>
GEMINI_MODELS=gemini-3.1-flash-lite:15:500,gemini-flash-lite-latest:0:0
```

Cú pháp `tên:RPM:RPD` — hết lượt model này thì tự chuyển model kế. Đặt `0:0` nếu không rõ hạn mức.
</details>

<details>
<summary><b>Ollama</b> — chạy hẳn trên máy, không cần mạng</summary>

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b-instruct
```

Cài [Ollama](https://ollama.com) rồi `ollama pull qwen2.5:7b-instruct`. Model **phải hỗ trợ
tool-calling**. Model càng nhỏ chọn công cụ càng kém — dưới 7B thường không dùng được.
</details>

<details>
<summary><b>Claude</b></summary>

```env
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=<khoá của bạn>
```
</details>

## Chạy

```bash
cd src && python app.py
```

Mặc định phải gọi tên trước: **"trợ lý, mở Chrome"**. Nói *"trợ lý, chế độ làm việc"* để tạm
tắt phần gọi tên, *"chế độ bình thường"* để bật lại. Không có micro thì trợ lý tự chuyển sang
gõ phím.

Thử vài câu:

```
trợ lý, mở Chrome rồi tăng âm lượng lên 60
trợ lý, thời tiết Đà Lạt hôm nay thế nào
trợ lý, nhắc tôi uống nước sau 10 phút
trợ lý, tìm thông tin về trạm vũ trụ ISS
trợ lý, hôm nay tôi có lịch gì
trợ lý, vui tính hơn chút đi
```

---

## Cấu hình

Toàn bộ tham số nằm trong `src/utils/config.py`, ghi đè được bằng `src/.env`. Những mục hay dùng:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `gemini` \| `claude` \| `ollama` |
| `ROUTER_MODE` | `auto` | `auto` tự tắt bước phân loại với model mạnh để bớt một lượt gọi |
| `SILENCE_DURATION` | `1.5` | Im lặng bao nhiêu giây thì coi là bạn đã nói xong |
| `WAKE_WORDS` | `trợ lý,Alice,…` | Từ đánh thức, cách nhau bởi dấu phẩy |
| `REQUIRE_WAKE_WORD` | `true` | Tắt nếu muốn ra lệnh trực tiếp |
| `INPUT_MODE` | `auto` | `auto` \| `voice` \| `text` |
| `TTS_SPEED` | `1.0` | Tốc độ đọc; `TTS_ROBOT=true` cho giọng robot |
| `PERSONA_ENABLED` | `true` | Nhân cách + tâm trạng dẫn biểu cảm avatar |
| `LTM_AUTO_EXTRACT` | `true` | Tự đúc kết trí nhớ dài hạn; đặt `false` để bớt lượt gọi LLM |
| `SCREEN_CONTROL_ENABLED` | `false` | Đọc màn hình — chỉ chạy với LLM trên máy |
| `MCP_ENABLED` | `false` | Bật Gmail & Lịch Google |
| `BROWSER_BRIDGE_ENABLED` | `true` | Cầu nối Chrome; tắt nếu chưa cài tiện ích |
| `HABITS_ENABLED` | `true` | Đếm hành vi lặp lại để nhận ra thói quen |
| `FAST_COMMANDS` | `true` | Lệnh quen chạy thẳng, không tốn lượt gọi LLM |
| `BARGE_IN` | `true` | Cho phép nói chen ngang lúc trợ lý đang đọc |
| `AVATAR_SCALE` | `0.7` | Cỡ cửa sổ avatar (0.4–1.5); `AVATAR_OPACITY` chỉnh độ mờ |
| `WEATHER_DEFAULT_LOCATION` | `Hà Nội` | Nơi mặc định khi hỏi thời tiết |

Danh sách đầy đủ (hơn 90 biến) nằm ngay trong `src/utils/config.py`, mỗi biến một dòng chú
thích.

### Bật Gmail & Lịch Google

Máy chủ chạy **local**, dùng OAuth của chính bạn, token nằm trên máy bạn.

```bash
cd mcp_servers
pip install -r requirements.txt
python google_personal.py --setup      # mở trình duyệt để bạn cấp quyền
```

Tạo OAuth client (Desktop) trong Google Cloud Console, tải `credentials.json` về đặt cạnh file
trên, rồi thêm vào `src/.env`:

```env
MCP_ENABLED=true
MCP_COMMAND=<đường dẫn python của môi trường ảo>
MCP_ARGS=<đường dẫn tuyệt đối tới mcp_servers/google_personal.py>
MCP_TOOL_PREFIX=gws_
```

### Bật giọng riêng (clone từ ~3 giây thu âm)

Mặc định trợ lý đọc bằng gTTS (cần mạng). Muốn nó nói bằng giọng bạn thì thu một đoạn ngắn,
rõ tiếng, không tạp âm — rồi trỏ vào:

```env
TTS_ENGINE=vieneu
VIENEU_REF_AUDIO=<đường dẫn tuyệt đối tới file .wav mẫu>
```

Clone thẳng từ đoạn mẫu, **không huấn luyện gì**. Nạp model mất 13–15 giây ở lần đọc đầu,
sau đó tiếng đầu ra trong khoảng 1,4–1,5 giây. Đoạn thu mẫu là dữ liệu cá nhân — để trên máy,
đừng đưa lên repo.

### Bật điều khiển Chrome

Vào `chrome://extensions` → bật Developer mode → *Load unpacked* → chọn thư mục
`chrome_extension/`. Sau mỗi lần sửa tiện ích nhớ bấm **Reload**.

---

## Kiểm thử

```bash
pip install -r requirements-dev.txt
pytest
```

1168 test — **không** mở ứng dụng thật, không cần micro hay API key (LLM và các hành động đều
được thay bằng bản giả). Trong đó có một bộ **mô phỏng tấn công** chạy như test hồi
quy: nó *giả định model đã bị lừa*, rồi kiểm xem code còn chặn được tới đâu — vì câu hỏi đáng
hỏi không phải "model có bị lừa không" mà "lúc bị lừa thì thiệt hại tới đâu".

Ngoài ra có bộ đo riêng để kiểm xem model chọn công cụ đúng đến đâu và mỗi lượt tốn bao nhiêu
lần gọi LLM:

```bash
cd src && python -m evals.run_eval --gap=9
```

---

## Bảo mật & riêng tư

- Cầu nối Chrome chỉ lắng nghe ở `127.0.0.1` và **chỉ nhận kết nối từ tiện ích**, website
  không giả mạo được.
- Hành động khó hoàn tác bị chặn ở cổng xác nhận **trong code**, không phụ thuộc model.
- Nội dung từ bên ngoài (trang web, thân email) được **đánh dấu là dữ liệu, không phải lệnh**
  trước khi đưa vào prompt.
- Thứ **sắp rời máy** (địa chỉ nhận, tên miền sắp mở) được tách ra và trưng lên panel trước khi
  hỏi — vì tai không phân biệt được `google.com.evil.example` với `google.com`, còn mắt thì có.
- Đóng ứng dụng chạy qua danh sách tham số, không qua shell — không chèn lệnh được.
- Mỗi lượt ghi một dòng **nhật ký kết quả**, và `cd src && python -m memory.alerts` soi nhật ký đó tìm
  dấu hiệu bị tấn công — vì mọi lớp phòng ngừa chỉ nâng chi phí tấn công chứ không triệt tiêu,
  mà không biết mình đã bị chọc thủng thì mất luôn cơ hội phản ứng.
- Hồ sơ, nhân cách, danh bạ, token Google, giọng thu để clone đều nằm trên máy bạn và đã được
  loại khỏi repo.
- Đọc màn hình **tự tắt** khi dùng LLM trực tuyến, để nội dung màn hình không rời máy.

## Hạn chế đã biết

- **Windows only** — điều khiển hệ thống dựa vào thư viện riêng của Windows.
- **Chất lượng phụ thuộc model.** Model nhỏ chạy máy hay chọn sai hoặc quên gọi công cụ; hệ
  thống có sẵn nhiều lớp bù nhưng không thay thế được model tốt.
- **Chưa khử vọng âm.** Ngắt lời giữa chừng hoạt động nhưng không hoàn hảo vì micro vẫn nghe
  thấy chính giọng trợ lý.
- **Đọc kết quả tìm kiếm dựa vào cấu trúc trang Google/DuckDuckGo** — hai trang này đổi giao
  diện thì phải chỉnh lại.
- **Nội dung web và chữ trên màn hình là dữ liệu không đáng tin.** Trợ lý có thể bị dẫn dụ bởi
  chỉ dẫn giấu trong đó; cổng xác nhận là lớp phòng vệ chính.

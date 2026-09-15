# Đóng gói — chạy Trợ lý AI bằng 1 icon (không cần terminal)

## Cách dùng (đã cài sẵn)

Double-click **icon "Tro ly AI"** trên **Desktop** → chỉ hiện nhân vật avatar, KHÔNG
có cửa sổ terminal. Muốn thoát: Esc hoặc chuột phải lên nhân vật (đóng cửa sổ avatar).

## Gồm những gì

| File | Vai trò |
|---|---|
| `launch_assistant.vbs` (thư mục gốc) | Chạy `python src/app.py` **ẩn** (không terminal); gom mọi log vào `assistant.log` |
| `assistant.ico` (gốc) | Icon cho shortcut — khuôn mặt nhân vật, cắt từ chính ảnh avatar |
| `packaging/make_icon.py` | Script tạo lại icon; cắt đầu từ `src/ui/image/default_emotion.png` |
| `packaging/make_avatar_frames.py` | Script cắt ảnh gốc thành khung hình avatar (`src/ui/image/frames/`) |
| `packaging/preview_salm_care.py` | Preview care pulse SALM ở 3 mức opacity + ca cancel; không LLM/mic/TTS |
| `packaging/probe_salm.py` | Chạy SALM policy-shadow độc lập 20s và in diagnostic hẹp |
| `packaging/pilot_salm_vlc.py` | Pilot VLC headless + tone nhỏ để đo GSMTC/WASAPI theo process |
| `packaging/pilot_salm_chrome.py` | Pilot Chrome profile tạm + audio local; không đụng phiên Chrome hiện có |
| `packaging/pilot_salm_checkin.py` | Pilot SALM-1 policy→dispatcher→VieNeu, snooze 10 phút và DND; dữ liệu/clock giả trong bộ nhớ |
| `packaging/pilot_salm_dialogue.py` | Eval 20 paraphrase SALM-1.1a qua LLM thật; chỉ classify, không mutate SALM/DND |
| Shortcut trên Desktop | Trỏ tới `launch_assistant.vbs`, dùng `assistant.ico` |

## Xem log / chẩn đoán

Có **hai** file log, hai việc khác nhau — chọn đúng cái:

| File | Có gì | Vòng đời |
|---|---|---|
| `assistant.log` (gốc) | Mọi output, kể cả `🎤 Đã nghe`, `Trợ lý:`, `🔧 tool ...` — vì .vbs đổ cả stdout+stderr vào | **Ghi đè mỗi lần chạy**; chỉ có khi mở bằng launcher |
| `logs/app.log` (gốc) | Chỉ dòng của logger, kèm NGÀY | **Sống qua nhiều lần chạy**, xoay vòng ở 2 MB, giữ 3 bản (`app.log.1..3`); có cả khi chạy từ terminal |

Cần biết "vừa nãy màn hình hiện gì" → `assistant.log`. Cần lần lại chuyện xảy ra **mấy
hôm trước** hoặc ở lần chạy trước → `logs/app.log`.

Chỉnh bằng `src/.env`: `LOG_FILE` (rỗng = tắt ghi file), `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`.

Kiểm tra care pulse SALM (tự đóng sau khoảng 11 giây):

```bash
python packaging/preview_salm_care.py
```

Probe collector/policy SALM trên desktop thật (không phát cue):

```bash
python packaging/probe_salm.py --seconds 20 --wasapi
```

Pilot media VLC cô lập (tự từ chối nếu VLC của người dùng đang chạy):

```bash
python packaging/pilot_salm_vlc.py
```

Pilot Chrome cô lập bằng trang audio local:

```bash
python packaging/pilot_salm_chrome.py
```

Pilot SALM-1 bằng giọng VieNeu thật (đọc hai câu ngắn, không ghi log SALM):

```bash
python packaging/pilot_salm_checkin.py
python packaging/pilot_salm_checkin.py --dry-run  # không phát TTS
```

Eval intent SALM-1.1a bằng provider LLM hiện tại (20 câu, không đổi state):

```bash
python packaging/pilot_salm_dialogue.py
```

Đọc bằng PowerShell phải ép UTF-8, không thì ra mojibake:

```
Get-Content assistant.log -Tail 40 -Encoding utf8
```

## Khi đổi máy / đổi môi trường Python

Sửa biến `PYTHON` trong `launch_assistant.vbs` cho trỏ đúng `python.exe` của môi
trường đang dùng (hiện trỏ tới `...\RAG\ml_env\Scripts\python.exe`).

## Tạo lại icon / shortcut

```bash
python packaging/make_avatar_frames.py  # khung hình avatar, chạy trước
python packaging/make_icon.py           # assistant.ico + assistant.png
```

Đổi ảnh nhân vật thì chạy lại **cả hai**: icon cắt từ cùng tấm ảnh gốc với avatar và
dùng chung mốc canh, nên hai thứ không lệch nhau.

Tạo lại shortcut Desktop (PowerShell):

```powershell
$root = "C:\Users\Dell\Desktop\Study\AI_learning\AI_supervising"
$ws = New-Object -ComObject WScript.Shell
$lnk = Join-Path ($ws.SpecialFolders("Desktop")) "Tro ly AI.lnk"
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = "$env:WINDIR\System32\wscript.exe"
$sc.Arguments = '"' + (Join-Path $root "launch_assistant.vbs") + '"'
$sc.WorkingDirectory = $root
$sc.IconLocation = (Join-Path $root "assistant.ico")
$sc.Save()
```

## Vì sao không dùng .exe (PyInstaller)?

Dự án phụ thuộc torch + faster-whisper + pygame + pyaudio — đóng gói `.exe` sẽ rất
nặng (hàng trăm MB–GB), hay lỗi hidden-import, và model Whisper vẫn tải lúc chạy.
Với máy cá nhân, launcher + shortcut đạt đúng mục tiêu "1 icon để mở" mà nhẹ và ổn định.

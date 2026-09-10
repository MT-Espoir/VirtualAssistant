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

# Đóng gói — chạy Trợ lý AI bằng 1 icon (không cần terminal)

## Cách dùng (đã cài sẵn)

Double-click **icon "Tro ly AI"** trên **Desktop** → chỉ hiện khuôn mặt avatar, KHÔNG
có cửa sổ terminal. Muốn thoát: Esc hoặc chuột phải lên khuôn mặt (đóng cửa sổ avatar).

## Gồm những gì

| File | Vai trò |
|---|---|
| `launch_assistant.vbs` (thư mục gốc) | Chạy `python src/app.py` **ẩn** (không terminal); gom mọi log vào `assistant.log` |
| `assistant.ico` (gốc) | Icon khuôn mặt robot cho shortcut |
| `packaging/make_icon.py` | Script tạo lại icon bằng Pillow |
| Shortcut trên Desktop | Trỏ tới `launch_assistant.vbs`, dùng `assistant.ico` |

## Xem log / chẩn đoán

Vì không có terminal, mọi output (kể cả `🎤 Đã nghe`, `Trợ lý:`, `🔧 tool ...`, lỗi)
được ghi đè vào **`assistant.log`** ở thư mục gốc mỗi lần chạy. Mở file này để xem
chuyện gì đang xảy ra.

## Khi đổi máy / đổi môi trường Python

Sửa biến `PYTHON` trong `launch_assistant.vbs` cho trỏ đúng `python.exe` của môi
trường đang dùng (hiện trỏ tới `...\RAG\ml_env\Scripts\python.exe`).

## Tạo lại icon / shortcut

```bash
python packaging/make_icon.py          # tạo lại assistant.ico + assistant.png
```

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

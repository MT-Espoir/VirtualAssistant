' Khởi chạy Trợ lý AI KHÔNG cửa sổ terminal (debug mặc định tắt).
' Double-click file này, hoặc dùng shortcut ngoài Desktop.
' Mosquitto va IoT gateway duoc khoi dong an truoc khi mo Alice.
' Mọi log (kể cả 🔧 tool, lỗi) được ghi vào assistant.log cùng thư mục để chẩn đoán.
' File đó bị GHI ĐÈ mỗi lần chạy. Muốn xem lịch sử nhiều lần chạy thì đọc logs/app.log
' (do logger ghi, xoay vòng) — xem packaging/README.md.
'
' Nếu đổi máy/đổi môi trường Python: sửa biến PYTHON bên dưới cho đúng.

Option Explicit
Dim shell, fso, scriptDir, srcDir, python, logFile, q, cmd, iotScript, iotResult
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
srcDir = scriptDir & "\src"
python = "C:\Users\Dell\Desktop\Study\AI_learning\RAG\ml_env\Scripts\python.exe"
logFile = scriptDir & "\assistant.log"

If Not fso.FileExists(python) Then
    MsgBox "Khong tim thay Python:" & vbCrLf & python & vbCrLf & vbCrLf & _
           "Hay sua duong dan 'python' trong launch_assistant.vbs.", _
           vbCritical, "Tro ly AI"
    WScript.Quit 1
End If

If Not fso.FileExists(srcDir & "\app.py") Then
    MsgBox "Khong tim thay app.py trong:" & vbCrLf & srcDir, vbCritical, "Tro ly AI"
    WScript.Quit 1
End If

q = Chr(34)   ' dấu nháy kép, dùng để bọc đường dẫn có khoảng trắng
iotScript = scriptDir & "\packaging\iot\ensure-stack.ps1"
If Not fso.FileExists(iotScript) Then
    MsgBox "Khong tim thay IoT launcher:" & vbCrLf & iotScript, vbCritical, "Tro ly AI"
Else
    shell.CurrentDirectory = scriptDir
    cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & _
          q & iotScript & q & " -Python " & q & python & q
    iotResult = shell.Run(cmd, 0, True)
    If iotResult <> 0 Then
        MsgBox "IoT broker/gateway chua khoi dong duoc. Chi tiet trong:" & vbCrLf & _
               scriptDir & "\packaging\iot\runtime\logs\startup.log", vbExclamation, "Tro ly AI"
    End If
End If
shell.CurrentDirectory = srcDir

' cmd /c ""python" -X utf8 app.py > "log" 2>&1"  -> chạy python, gom log ra file.
' -X utf8 BẮT BUỘC: app in emoji (🎤🔧); redirect ra file dùng cp1252 sẽ crash nếu
' không ép UTF-8.
cmd = "cmd /c " & q & q & python & q & " -X utf8 app.py > " & q & logFile & q & " 2>&1" & q

' 0 = cửa sổ console ẩn; False = không chờ (VBS thoát ngay, app chạy tiếp)
shell.Run cmd, 0, False

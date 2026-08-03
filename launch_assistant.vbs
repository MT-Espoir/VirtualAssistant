' Khởi chạy Trợ lý AI KHÔNG cửa sổ terminal (chỉ hiện khuôn mặt avatar).
' Double-click file này, hoặc dùng shortcut ngoài Desktop.
' Mọi log (kể cả 🔧 tool, lỗi) được ghi vào assistant.log cùng thư mục để chẩn đoán.
'
' Nếu đổi máy/đổi môi trường Python: sửa biến PYTHON bên dưới cho đúng.

Option Explicit
Dim shell, fso, scriptDir, srcDir, python, logFile, q, cmd
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
shell.CurrentDirectory = srcDir

' cmd /c ""python" -X utf8 app.py > "log" 2>&1"  -> chạy python, gom log ra file.
' -X utf8 BẮT BUỘC: app in emoji (🎤🔧); redirect ra file dùng cp1252 sẽ crash nếu
' không ép UTF-8.
cmd = "cmd /c " & q & q & python & q & " -X utf8 app.py > " & q & logFile & q & " 2>&1" & q

' 0 = cửa sổ console ẩn; False = không chờ (VBS thoát ngay, app chạy tiếp)
shell.Run cmd, 0, False

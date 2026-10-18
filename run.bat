@echo off
rem Chạy KT Loop Station từ mã nguồn. Lần đầu sẽ tự tạo môi trường và cài thư viện.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Dang cai dat lan dau...
  python -m venv .venv || goto :error
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
)
start "" .venv\Scripts\pythonw.exe app.py
exit /b 0
:error
echo Cai dat that bai. Can Python 3.12 tro len.
pause

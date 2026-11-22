@echo off
rem Slidesong GPU worker: started by hand, close the window to stop it.
title Slidesong worker - close this window to stop it
cd /d "%~dp0"
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("worker.env") do set "%%a=%%b"
echo Slidesong worker on port 8097 (close this window to stop it)
.venv\Scripts\python.exe -X utf8 -m uvicorn slidesong.worker:app --host 0.0.0.0 --port 8097
pause

@echo off
chcp 65001 >nul
rem 人类账本 一键启动（Windows）：双击运行。这个窗口就是账本服务，关掉它账本就停了。
rem 端口被别的程序占用时改 PORT；要让同一 Wi-Fi 下的手机访问时把 HOST 改成 0.0.0.0（先读 AGENTS.md 第 6 节）。
set PORT=8000
set HOST=127.0.0.1

cd /d "%~dp0backend"

curl -fs -o nul http://127.0.0.1:%PORT%/api/health >nul 2>&1 && (
  echo 账本已经在运行，正在打开浏览器……
  start http://localhost:%PORT%
  exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
  echo 还没有安装。请让 AI 助手按 AGENTS.md 安装，或参照 README.md。
  pause
  exit /b 1
)
if not exist "..\frontend\dist\index.html" (
  echo 网页界面还没有构建。请让 AI 助手按 AGENTS.md 的步骤构建。
  pause
  exit /b 1
)

.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
  echo.
  echo 数据库升级失败，账本没有启动。把上面的内容发给 AI 助手看看。
  pause
  exit /b 1
)

echo.
echo 人类账本已启动：http://localhost:%PORT%
echo 这个窗口不要关，关掉账本就停了（数据不会丢）。
echo.
rem 等服务就绪再打开浏览器（第一次启动可能要十几秒）
start "" /min cmd /c "for /l %%i in (1,1,60) do @(curl -fs -o nul http://127.0.0.1:%PORT%/api/health && (start http://localhost:%PORT% & exit) || timeout /t 1 /nobreak >nul)"
.venv\Scripts\python.exe -m uvicorn app.main:app --host %HOST% --port %PORT%

echo.
echo 账本已停止。如果上面有报错，把它发给 AI 助手看看。
pause

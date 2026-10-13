#!/bin/sh
# 人类账本 一键启动（macOS 双击运行；Linux 用 sh start-mac.command）。
# 这个终端窗口就是账本服务，关掉它账本就停了。
# 端口被别的程序占用时改 PORT；要让同一 Wi-Fi 下的手机访问时把 HOST 改成 0.0.0.0（先读 AGENTS.md 第 6 节）。
PORT=8000
HOST=127.0.0.1

cd "$(dirname "$0")/backend" || exit 1
URL="http://localhost:$PORT"
open_browser() { open "$URL" 2>/dev/null || xdg-open "$URL" >/dev/null 2>&1; }
wait_enter() { printf '按回车关闭窗口。'; read -r _; }

if curl -fs -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null; then
  echo "账本已经在运行，正在打开浏览器……"
  open_browser
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "还没有安装。请让 AI 助手按 AGENTS.md 安装，或参照 README.md。"
  wait_enter; exit 1
fi
if [ ! -f ../frontend/dist/index.html ]; then
  echo "网页界面还没有构建。请让 AI 助手按 AGENTS.md 的步骤构建。"
  wait_enter; exit 1
fi

if ! .venv/bin/python -m alembic upgrade head; then
  echo
  echo "数据库升级失败，账本没有启动。把上面的内容发给 AI 助手看看。"
  wait_enter; exit 1
fi

echo
echo "人类账本已启动：$URL"
echo "这个窗口不要关，关掉账本就停了（数据不会丢）。"
echo
# 等服务就绪再打开浏览器（第一次启动可能要十几秒）
(for _ in $(seq 60); do
  curl -fs -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null && { open_browser; break; }
  sleep 1
done) &
.venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"

echo
echo "账本已停止。如果上面有报错，把它发给 AI 助手看看。"
wait_enter

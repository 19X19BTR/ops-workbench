#!/bin/bash
# macOS / Linux：双击（或 ./start.command）即可启动工作台
set -e
cd "$(dirname "$0")"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "✗ 没找到 Python。请先安装 Python 3.9+：https://www.python.org/downloads/"
  read -r -p "按回车关闭..." _
  exit 1
fi

echo "→ 检查依赖…"
if ! "$PY" -c "import openpyxl, PIL" >/dev/null 2>&1; then
  echo "  首次运行，正在安装 openpyxl 与 Pillow…"
  "$PY" -m pip install --quiet -r requirements.txt || {
    echo "✗ 依赖安装失败。可以手动执行：$PY -m pip install -r requirements.txt"
    read -r -p "按回车关闭..." _; exit 1; }
fi

[ -f config/config.json ] || cp config/config.example.json config/config.json
if [ ! -f demo/catalog.xlsx ]; then
  echo "→ 生成演示数据…"
  "$PY" demo/generate_demo.py
fi

PORT="${1:-8765}"
echo "→ 启动中，浏览器会自动打开 http://127.0.0.1:$PORT"
( sleep 2; command -v open >/dev/null && open "http://127.0.0.1:$PORT" ) &
exec "$PY" server.py --port "$PORT"

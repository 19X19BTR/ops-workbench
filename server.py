#!/usr/bin/env python3
"""运营数据工作台 —— 本机只读服务（通用版）。

设计要点（每一项都对应一个真实踩过的坑）：
1. **字段白名单**：配置文件里逐视图列出允许外发的字段，其余列一律不读、不传
2. **只绑 127.0.0.1**：并校验 Host / Origin / Sec-Fetch-Site，挡掉 DNS rebinding 与跨站请求
3. **防脏读**：读前读后各取一次 stat，文件在读取期间被改过就报错，不返回半新半旧的快照
4. **图片内容寻址**：按图片 URL 的 SHA-256 存放，天然去重；缺失就是缺失，不拿相似图凑
5. **只读**：除了「在访达里显示源文件」这一个动作，不写任何源文件
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import openpyxl
from PIL import Image

Image.MAX_IMAGE_PIXELS = 40_000_000

ROOT = Path(__file__).resolve().parent
VIEW_KEYS = ("live", "orders", "stock", "catalog")


class ConfigError(ValueError):
    """配置不合法。"""


def load_config(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"找不到配置文件：{path}")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置不是合法 JSON：{exc}") from exc

    if not isinstance(config.get("views"), dict) or not config["views"]:
        raise ConfigError("配置里需要 views（至少一个视图）")
    for key, view in config["views"].items():
        if key not in VIEW_KEYS:
            raise ConfigError(f"未知视图 {key!r}，可选：{'、'.join(VIEW_KEYS)}")
        if not view.get("file"):
            raise ConfigError(f"视图 {key} 缺少 file")
        if not isinstance(view.get("whitelist"), list) or not view["whitelist"]:
            raise ConfigError(f"视图 {key} 缺少 whitelist（这是数据外发白名单，不允许为空）")
    if not isinstance(config.get("stockViews", []), list):
        raise ConfigError("stockViews 必须是数组")
    if not isinstance(config.get("classify", {}), dict):
        raise ConfigError("classify 必须是对象")
    config["_base"] = str(path.parent.parent)      # 配置文件在 config/ 下，文件路径相对项目根
    return config


def text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat(sep=" ") if isinstance(value, datetime.datetime) else value.isoformat()
    return str(value)


def public_config(config: dict) -> dict:
    """给前端的配置：只暴露展示用的信息，不含服务器文件路径。"""
    return {
        "title": config.get("title", "运营数据工作台"),
        "subtitle": config.get("subtitle", ""),
        "kicker": config.get("kicker", ""),
        "views": {key: {"title": view.get("title", key), "display": view.get("display", "")}
                  for key, view in config["views"].items()},
        "stockViews": [{"sheet": item.get("sheet", ""), "label": item.get("label", ""),
                        "note": item.get("note", "")}
                       for item in config.get("stockViews", [])],
        "classify": config.get("classify", {}),
    }


def resolve_source(config: dict, key: str) -> Path:
    view = config["views"][key]
    path = Path(view["file"])
    return path if path.is_absolute() else Path(config["_base"]) / path


def read_source(config: dict, key: str) -> dict:
    """读取一个视图的工作簿，只保留白名单字段。"""
    view = config["views"][key]
    whitelist = view["whitelist"]
    image_fields = view.get("imageFields") or []
    path = resolve_source(config, key)

    before = path.stat()
    book = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        sheets = []
        selected = ([book[view["sheet"]]] if view.get("sheet") and view["sheet"] in book.sheetnames
                    else book.worksheets)
        for sheet in selected:
            rows = sheet.iter_rows(values_only=True)
            headers = [text(value) for value in next(rows, ())]
            required = view.get("required") or []
            missing = [name for name in required if name not in headers]
            if missing:
                raise ValueError(f"工作表 {sheet.title} 缺少必需字段：{'、'.join(missing)}")
            indexes = [i for i, header in enumerate(headers) if header in whitelist]
            image_indexes = [i for i, header in enumerate(headers) if header in image_fields]
            filtered, images = [], []
            for row in rows:
                values = [text(row[i]) if i < len(row) else "" for i in indexes]
                if not any(item.strip() for item in values):
                    continue
                filtered.append(values)
                url = next((text(row[i]).strip() for i in image_indexes
                            if i < len(row) and text(row[i]).strip()), "")
                images.append(image_status(config, url))
            sheets.append({
                "name": sheet.title,
                "headers": headers,
                "safeHeaders": [headers[i] for i in indexes],
                "rows": filtered,
                "images": images,
            })
    finally:
        book.close()

    after = path.stat()
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise RuntimeError("读取期间源文件发生变化，请刷新重试")

    return {
        "name": path.name,
        "modified": datetime.datetime.fromtimestamp(after.st_mtime).astimezone().isoformat(),
        "loaded": datetime.datetime.now().astimezone().isoformat(),
        "sheets": sheets,
    }


def image_status(config: dict, url: str) -> str:
    """图片状态：/images/<sha> | unavailable（有 URL 但没缓存） | missing（源表没 URL）。"""
    if not url:
        return "missing"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache = Path(config.get("imageCache", "image_cache"))
    if not cache.is_absolute():
        cache = Path(config["_base"]) / cache
    return f"/images/{digest}" if (cache / f"{digest}.img").is_file() else "unavailable"


class Handler(BaseHTTPRequestHandler):
    config: dict = {}
    server_version = "ops-workbench/1.0"
    verbose: bool = False        # 测试与默认运行时安静，排障时加 --verbose

    def log_message(self, fmt, *args):      # noqa: A003
        if self.verbose:
            super().log_message(fmt, *args)

    # ---------- 安全校验 ----------
    def _same_origin(self) -> bool:
        host = self.headers.get("Host", "")
        expected = f"127.0.0.1:{self.server.server_port}"
        if host != expected:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{expected}":
            return False
        return self.headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")

    def _send(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    # ---------- 路由 ----------
    def do_GET(self) -> None:                      # noqa: N802
        if not self._same_origin():
            self.send_error(403)
            return
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            return self._send(200, (ROOT / "workbench" / "index.html").read_bytes(),
                              "text/html; charset=utf-8")
        if path == "/api/config":
            return self._json(public_config(self.config))
        match = re.fullmatch(r"/api/(live|orders|stock|catalog)", path)
        if match:
            return self._view(match.group(1))
        match = re.fullmatch(r"/images/([0-9a-f]{64})", path)
        if match:
            return self._image(match.group(1))
        self.send_error(404)

    def do_POST(self) -> None:                     # noqa: N802
        """唯一写操作：在文件管理器里定位源文件（不修改内容）。"""
        if not self._same_origin():
            self.send_error(403)
            return
        if (self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json"):
            self.send_error(403)
            return
        match = re.fullmatch(r"/api/reveal/(live|orders|stock|catalog)", self.path.split("?")[0])
        if not match:
            self.send_error(404)
            return
        key = match.group(1)
        try:
            path = resolve_source(self.config, key)
            if not path.is_file():
                raise FileNotFoundError("数据文件不存在")
            if sys.platform == "darwin":
                subprocess.run(["/usr/bin/open", "-R", str(path)], check=True,
                               timeout=10, capture_output=True)
            return self._json({"ok": True, "platform": sys.platform})
        except (OSError, subprocess.SubprocessError) as exc:
            return self._json({"error": str(exc)}, 500)

    def _view(self, key: str) -> None:
        try:
            return self._json(read_source(self.config, key))
        except FileNotFoundError:
            return self._json({"error": "源文件缺失，请在文件生成完成后刷新"}, 404)
        except Exception as exc:                    # 读取失败要给出可操作的信息
            return self._json({"error": f"读取失败：{type(exc).__name__}：{exc}"}, 500)

    def _image(self, digest: str) -> None:
        cache = Path(self.config.get("imageCache", "image_cache"))
        if not cache.is_absolute():
            cache = Path(self.config["_base"]) / cache
        candidate = cache / f"{digest}.img"
        try:
            with Image.open(candidate) as image:
                if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError("图片像素过大")
                content_type = {"JPEG": "image/jpeg", "MPO": "image/jpeg", "PNG": "image/png",
                                "WEBP": "image/webp", "GIF": "image/gif"}[image.format]
                image.verify()
            return self._send(200, candidate.read_bytes(), content_type)
        except (OSError, ValueError, KeyError, Image.DecompressionBombError):
            self.send_error(404)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="运营数据工作台：本机只读服务")
    parser.add_argument("--config", default=str(ROOT / "config" / "config.json"),
                        help="配置文件路径，默认 config/config.json")
    parser.add_argument("--port", type=int, default=None, help="端口，默认取配置里的 port 或 8765")
    parser.add_argument("--verbose", action="store_true", help="打印每条访问日志")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.exists():
        example = ROOT / "config" / "config.example.json"
        print(f"⚠ 没有找到 {config_path}，先复制示例：\n"
              f"    cp {example} {config_path}\n"
              f"  再按自己的表结构改 file 和 whitelist。", file=sys.stderr)
        return 1
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"✗ 配置有问题：{exc}", file=sys.stderr)
        return 1

    handler = type("BoundHandler", (Handler,), {"config": config, "verbose": args.verbose})
    port = args.port or int(config.get("port", 8765))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"运营数据工作台：http://127.0.0.1:{server.server_port}/")
    print(f"配置：{config_path}")
    print("只读服务 · 仅本机可访问 · 按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务端测试：配置校验、字段白名单、图片状态、防脏读、HTTP 安全边界。"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def write_config(tmp: str, payload: dict) -> Path:
    path = Path(tmp) / "config" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestConfig(unittest.TestCase):
    def test_加载示例配置(self):
        config = server.load_config(ROOT / "config" / "config.example.json")
        self.assertEqual(set(config["views"]), {"live", "orders", "stock", "catalog"})
        self.assertEqual(config["views"]["catalog"]["sheet"], "商品分类明细")

    def test_文件不存在(self):
        with self.assertRaises(server.ConfigError):
            server.load_config(ROOT / "config" / "nope.json")

    def test_非法JSON(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaises(server.ConfigError):
                server.load_config(path)

    def test_缺views(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(server.ConfigError):
                server.load_config(write_config(tmp, {"title": "x"}))

    def test_未知视图(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(server.ConfigError) as ctx:
                server.load_config(write_config(tmp, {"views": {"sale": {"file": "a.xlsx",
                                                                       "whitelist": ["a"]}}}))
            self.assertIn("未知视图", str(ctx.exception))

    def test_白名单不能为空(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(server.ConfigError) as ctx:
                server.load_config(write_config(tmp, {"views": {"live": {"file": "a.xlsx",
                                                                       "whitelist": []}}}))
            self.assertIn("whitelist", str(ctx.exception))

    def test_对外配置不含服务器路径(self):
        config = server.load_config(ROOT / "config" / "config.example.json")
        public = server.public_config(config)
        dumped = json.dumps(public, ensure_ascii=False)
        self.assertNotIn('"file"', dumped)
        self.assertNotIn("_base", dumped)
        self.assertEqual(set(public["views"]), {"live", "orders", "stock", "catalog"})


class TestReadSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = server.load_config(ROOT / "config" / "config.example.json")

    def test_只返回白名单字段(self):
        data = server.read_source(self.config, "catalog")
        sheet = data["sheets"][0]
        self.assertIn("商品编码", sheet["safeHeaders"])
        self.assertNotIn("成本价", sheet["safeHeaders"])
        self.assertEqual(len(sheet["safeHeaders"]), len(sheet["rows"][0]))

    def test_备注列不外发(self):
        live = server.read_source(self.config, "live")
        self.assertNotIn("内部备注", live["sheets"][0]["safeHeaders"])
        orders = server.read_source(self.config, "orders")
        self.assertNotIn("买家手机号", orders["sheets"][0]["safeHeaders"])
        stock = server.read_source(self.config, "stock")
        self.assertNotIn("内部备注", stock["sheets"][0]["safeHeaders"])

    def test_多工作表(self):
        data = server.read_source(self.config, "stock")
        self.assertEqual([s["name"] for s in data["sheets"]], ["商品库存", "仓位库存"])

    def test_图片状态三态(self):
        images = server.read_source(self.config, "catalog")["sheets"][0]["images"]
        self.assertTrue(any(i.startswith("/images/") for i in images), "应有一张已缓存图")
        self.assertIn("missing", images, "应有源表没给 URL 的行")
        self.assertIn("unavailable", images, "应有给了 URL 但没缓存的行")

    def test_元数据字段(self):
        data = server.read_source(self.config, "live")
        for key in ("name", "modified", "loaded", "sheets"):
            self.assertIn(key, data)

    def test_防脏读(self):
        """读前读后 stat 不一致时要报错，而不是返回半新半旧的数据。"""
        real_stat = Path.stat
        calls = {"n": 0}

        def fake_stat(self, *args, **kwargs):
            result = real_stat(self, *args, **kwargs)
            if self.name.endswith(".xlsx"):
                calls["n"] += 1
                if calls["n"] == 2:          # 第二次（读完）返回变化后的文件信息
                    return mock.Mock(st_mtime_ns=result.st_mtime_ns + 1,
                                     st_size=result.st_size, st_mtime=result.st_mtime)
            return result

        with mock.patch.object(Path, "stat", fake_stat):
            with self.assertRaises(RuntimeError) as ctx:
                server.read_source(self.config, "live")
        self.assertIn("读取期间源文件发生变化", str(ctx.exception))

    def test_源文件缺失(self):
        config = dict(self.config)
        config["views"] = dict(self.config["views"])
        config["views"]["live"] = dict(self.config["views"]["live"], file="demo/不存在.xlsx")
        with self.assertRaises(FileNotFoundError):
            server.read_source(config, "live")


class ServerFixture:
    def __init__(self):
        self.config = server.load_config(ROOT / "config" / "config.example.json")
        handler = type("TestHandler", (server.Handler,), {"config": self.config})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def get(self, path, headers=None):
        request = urllib.request.Request(self.base + path)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def post(self, path, payload, headers=None):
        request = urllib.request.Request(self.base + path, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


class TestHttp(unittest.TestCase):
    def setUp(self):
        self.fixture = ServerFixture().__enter__()

    def tearDown(self):
        self.fixture.__exit__()

    def json(self, path):
        status, body, _ = self.fixture.get(path)
        return status, json.loads(body)

    def test_首页(self):
        status, body, headers = self.fixture.get("/")
        self.assertEqual(status, 200)
        self.assertIn("运营数据工作台".encode(), body)
        self.assertIn("text/html", headers.get("Content-Type", ""))

    def test_配置接口(self):
        status, data = self.json("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(data["title"], "运营数据工作台")
        self.assertIn("classify", data)

    def test_四个视图都能读(self):
        for view in ("live", "orders", "stock", "catalog"):
            status, data = self.json(f"/api/{view}")
            self.assertEqual(status, 200, view)
            self.assertTrue(data["sheets"][0]["safeHeaders"], view)

    def test_未知视图404(self):
        status, _, _ = self.fixture.get("/api/nope")
        self.assertEqual(status, 404)

    def test_图片命中与未命中(self):
        _, data = self.json("/api/catalog")
        cached = next(i for i in data["sheets"][0]["images"] if i.startswith("/images/"))
        status, body, headers = self.fixture.get(cached)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/png")
        self.assertGreater(len(body), 100)

        status, _, _ = self.fixture.get("/images/" + "0" * 64)
        self.assertEqual(status, 404)

    def test_错误Host被拒(self):
        status, _, _ = self.fixture.get("/api/config", {"Host": "evil.example.com"})
        self.assertEqual(status, 403)

    def test_跨站Origin被拒(self):
        status, _, _ = self.fixture.get("/api/config", {"Origin": "http://evil.example.com"})
        self.assertEqual(status, 403)

    def test_同源Origin放行(self):
        status, _, _ = self.fixture.get("/api/config", {"Origin": self.fixture.base})
        self.assertEqual(status, 200)

    def test_响应头安全(self):
        _, _, headers = self.fixture.get("/api/config")
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_reveal只接受JSON(self):
        status, _ = self.fixture.post("/api/reveal/live", b"x",
                                      {"Content-Type": "text/plain"})
        self.assertEqual(status, 403)

    def test_reveal未知视图404(self):
        status, _ = self.fixture.post("/api/reveal/xxx", b"{}")
        self.assertEqual(status, 404)

    def test_reveal正常(self):
        status, body = self.fixture.post("/api/reveal/live", b"{}")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body).get("ok"))


if __name__ == "__main__":
    unittest.main()

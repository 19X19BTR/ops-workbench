#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成演示数据（全部合成，商品名与金额虚构）。

产物：
    demo/live.xlsx     场次数据
    demo/orders.xlsx   订单数据
    demo/stock.xlsx    两个工作表：商品库存 / 仓位库存
    demo/catalog.xlsx  商品分类明细（12 行，覆盖分类的各种分支）
    image_cache/*.img  3 张示例图片（按 URL 的 SHA-256 命名）

用法：python demo/generate_demo.py
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
CACHE = ROOT / "image_cache"

random.seed(20260101)

# 商品：名称、类型、材质、颜色、图片 URL（第三张故意不给图，演示 unavailable）
PRODUCTS = [
    ("紫水晶手串 8mm", "手串", "水晶", "紫", "https://example.com/p/1.png"),
    ("蓝托帕项链 45cm", "项链", "托帕石", "蓝", "https://example.com/p/2.png"),
    ("珍珠耳钉 6mm", "耳饰", "珍珠", "白", "https://example.com/p/3.png"),
    ("S925银戒指 开口款", "戒指", "银", "待核", ""),
    ("翡翠吊坠 平安扣", "吊坠", "翡翠", "待核", "https://example.com/p/4.png"),
    ("碧玺圆珠 4mm", "珠料", "碧玺", "待核", ""),
    ("茶晶单圈 10mm", "手串", "水晶", "待核", ""),
    ("粉水晶单圈 9mm", "手串", "水晶", "待核", ""),
    ("未知商品 X-001", "", "", "", ""),
    ("多宝手串 MB20260001", "手串", "", "待核", "https://example.com/p/5.png"),
    ("示例原料 木珠散装", "", "", "", ""),
    ("孔雀石摆件 迷你", "摆件", "孔雀石", "待核", ""),
    # 以下几条用来演示「商业别名 / 材料常见色范围」两类规则
    ("莫粉圆珠 6mm", "珠料", "水晶", "待核", ""),
    ("超七手串 9mm", "手串", "超七（名称分类）", "待核", ""),
    ("绿松石桶珠 5mm", "珠料", "绿松石", "待核", ""),
    ("冰曜吊坠 平安符", "吊坠", "冰曜（名称分类）", "待核", ""),
]

SESSIONS = [
    ("L20260101001", "示例直播间A", datetime(2026, 1, 1, 19, 0), 240, 12000, 3200, 210),
    ("L20260102001", "示例直播间A", datetime(2026, 1, 2, 19, 30), 240, 13800, 2800, 260),
    ("L20260103001", "示例直播间A", datetime(2026, 1, 3, 20, 0), 180, 9400, 2100, 120),
]


def write_live() -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "直播数据"
    sheet.append(["直播间ID", "直播间名称", "直播间标题", "直播间状态", "抖音号ID",
                  "开播时间", "直播结束时间", "直播时长（秒）",
                  "整体消耗", "整体支付ROI", "整体成交金额", "整体成交订单数",
                  "整体成交订单成本", "GPM", "直播间整体曝光次数", "直播间整体观看人数",
                  "直播间观看人数", "直播间观看人次", "直播间商品曝光人数", "直播间商品曝光次数",
                  "直播间商品点击人数", "直播间成交人数", "商品点击率（人数）",
                  "点击成交转化率（人数）", "看播成交转化率（人数）", "人均观看时长",
                  "直播间成交订单数", "内部备注"])
    start = datetime(2026, 1, 1, 19, 0)
    for sid, name, begin, minutes, pv, uv, fans in SESSIONS:
        spend = round(random.uniform(800, 2000), 2)
        gmv = round(spend * random.uniform(2.2, 3.4), 2)
        orders = random.randint(40, 90)
        end = begin + timedelta(minutes=minutes)
        buyers = random.randint(30, 70)
        clicks = int(buyers * random.uniform(1.6, 2.4))
        impressions = int(pv * random.uniform(1.2, 1.8))
        sheet.append([sid, name, f"{name}·示例场次", "已结束", f"demo{sid[-3:]}",
                      begin, end, minutes * 60,
                      spend, round(gmv / spend, 2), gmv, orders,
                      round(spend / max(orders, 1), 2), round(gmv / impressions * 1000, 2),
                      impressions, pv, int(pv * 0.62), int(pv * 1.9), int(pv * 0.55),
                      int(impressions * 0.7), clicks, buyers,
                      round(clicks / max(pv * 0.55, 1) * 100, 2),
                      round(buyers / max(clicks, 1) * 100, 2),
                      round(buyers / max(pv * 0.62, 1) * 100, 2),
                      round(random.uniform(40, 95), 1), orders,
                      "这一列不在白名单，不应出现在接口里"])
    book.save(DEMO / "live.xlsx")


def write_orders() -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "订单列表"
    sheet.append(["主订单编号", "子订单编号", "选购商品", "商品名称", "商品ID", "商家编码",
                  "商品数量", "商品金额", "订单提交时间", "支付完成时间", "订单状态",
                  "售后状态", "订单应付金额", "成交金额", "买家手机号"])
    start = datetime(2026, 1, 1, 19, 0)
    for index in range(60):
        name, _type, _material, _color, url = random.choice(PRODUCTS)
        price = round(random.uniform(59, 899), 2)
        quantity = random.choices([1, 2], weights=[85, 15])[0]
        amount = round(price * quantity, 2)
        when = start + timedelta(minutes=random.randint(5, 350))
        status = random.choices(["已完成", "已发货", "已退款"], weights=[70, 20, 10])[0]
        sheet.append([f"M2026010100{index}", f"S2026010100{index}", name, name,
                      f"72000000{index}", f"SKU{index:04d}", quantity, amount, when, when,
                      status, "退款成功" if status == "已退款" else "无",
                      amount, 0 if status == "已退款" else amount, "13800000000"])
    book.save(DEMO / "orders.xlsx")


def write_stock() -> None:
    book = Workbook()
    full = book.active
    full.title = "商品库存"
    # 主视图：多一列内部备注（不在白名单）
    full.append(["商品编码", "优先商品名称", "抖店商品ID", "关联状态", "实际库存数",
                 "订单占有数", "可用数", "颜色及规格", "仓位", "分仓名称", "库存更新时间",
                 "图片来源URL", "内部备注"])
    for index, (name, _type, _material, _color, url) in enumerate(PRODUCTS, 1):
        actual = random.randint(0, 40)
        taken = random.randint(0, min(actual, 5))
        full.append([f"SKU{index:03d}", name, f"72000000{random.randint(100, 999)}", "已匹配",
                     actual, taken, actual - taken, "均色 / 8mm", "A-01", "主仓",
                     datetime(2026, 1, 3, 9, 0), url, "内部备注不上外网"])

    subset = book.create_sheet("仓位库存")
    subset.append(["商品编码", "优先商品名称", "实际库存数", "可用数", "仓位", "分仓名称",
                   "图片来源URL"])
    for index, (name, _type, _material, _color, url) in enumerate(PRODUCTS[:5], 1):
        subset.append([f"SKU{index:03d}", name, random.randint(0, 10), random.randint(0, 8),
                       "B-02", "分仓", url])
    book.save(DEMO / "stock.xlsx")


def write_catalog() -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "商品分类明细"
    sheet.append(["源表行号", "商品编码", "优先商品名称", "聚水潭商品名称", "类型候选",
                  "材质候选", "颜色候选", "规格原文", "源颜色字段", "实际库存数（源行）",
                  "可用数（源行）", "抖店关联状态", "分类状态", "分类依据", "图片链接",
                  "成本价"])
    for index, (name, _type, _material, _color, url) in enumerate(PRODUCTS, 1):
        sheet.append([index, f"SKU{index:03d}", name, name, "", "", "",
                      "8mm 均色" if index % 2 else "10mm", "待核",
                      random.randint(0, 20), random.randint(0, 15), "已匹配",
                      "待分类", "源表未提供", url, round(random.uniform(10, 200), 2)])
    book.save(DEMO / "catalog.xlsx")


def write_images() -> None:
    """3 张示例图，按 URL 的 SHA-256 存成 .img（和线上逻辑一致）。"""
    CACHE.mkdir(exist_ok=True)
    colors = [("紫水晶", (120, 90, 190)), ("蓝托帕", (70, 130, 200)), ("珍珠", (230, 225, 215))]
    urls = [f"https://example.com/p/{i}.png" for i in (1, 2, 3)]
    for url, (label, color) in zip(urls, colors):
        image = Image.new("RGB", (320, 320), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle([16, 16, 304, 304], outline=(255, 255, 255), width=4)
        draw.text((24, 150), label, fill=(255, 255, 255))
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        image.save(CACHE / f"{digest}.img", format="PNG")
    # p/4 也缓存一张，p/5 故意不缓存，用来演示 unavailable
    url4 = "https://example.com/p/4.png"
    image = Image.new("RGB", (320, 320), (60, 150, 120))
    ImageDraw.Draw(image).text((24, 150), "翡翠", fill=(255, 255, 255))
    image.save(CACHE / f"{hashlib.sha256(url4.encode()).hexdigest()}.img", format="PNG")


def main() -> None:
    DEMO.mkdir(exist_ok=True)
    write_live()
    write_orders()
    write_stock()
    write_catalog()
    write_images()
    for path in sorted(DEMO.glob("*.xlsx")):
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size:>7} 字节")
    print(f"  image_cache/  {len(list(CACHE.glob('*.img')))} 张示例图")


if __name__ == "__main__":
    main()

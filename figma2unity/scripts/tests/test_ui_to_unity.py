# -*- coding: utf-8 -*-
"""test_ui_to_unity.py — ui_to_unity 转换器单测(夹具 = fixtures/screen-login.ui.json)。"""
import importlib.util
import json
import os
import re

D = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(D)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "ui_to_unity", os.path.join(SCRIPTS, "ui_to_unity.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _rule(uss, cls):
    """取 .<cls> { ... } 规则体。"""
    m = re.search(r"\." + re.escape(cls) + r"\s*\{([^}]*)\}", uss)
    return m.group(1) if m else ""


def _run():
    mod = _load_module()
    fix = os.path.join(D, "fixtures", "screen-login.ui.json")
    with open(fix, "r", encoding="utf-8") as f:
        cap = json.load(f)
    uxml, uss, losses = mod.convert(cap, "screen-login")

    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  PASS  " if cond else "  FAIL  ") + name)
        if not cond:
            ok = False

    # 1. 元素数一致:UXML 里 name= 的节点数 = els 数 + 1(screen-root)
    names = re.findall(r'name="([^"]+)"', uxml)
    check("元素数一致(els+根)", len(names) == len(cap["els"]) + 1 and names[0] == "screen-root")

    # 2. name 替换规则:':' 换 '_',且原始冒号 id 不残留在 name 属性里
    check("name 冒号换下划线", 'name="1_30"' in uxml and not any(":" in n for n in names[1:]))

    # 3. 父相对几何:1:12(gem)父为 1:10 → left=286-260=26px, top=1302-1280=22px
    r = _rule(uss, "el-1_12")
    check("父相对几何(1:12 对 1:10)", "left: 26px;" in r and "top: 22px;" in r)

    # 3b. 无父元素保持帧绝对坐标:1:10 → left=260px, top=1280px
    r = _rule(uss, "el-1_10")
    check("根级元素帧绝对坐标(1:10)", "left: 260px;" in r and "top: 1280px;" in r)

    # 4. Label 文本在:TEXT 元素 → ui:Label + text 属性
    check("Label 文本(1:21 开始游戏)", '<ui:Label name="1_21" class="el-1_21" text="开始游戏" />' in uxml)

    # 5. radius 解析:1:10 radius="45px" → 四角长写全 45px
    r = _rule(uss, "el-1_10")
    check("radius 展开四角", all(
        ("border-%s-radius: 45px;" % c) in r
        for c in ("top-left", "top-right", "bottom-right", "bottom-left")))

    # 6. border 解析:1:30 "2.0px solid rgba(255,255,255,1)" → width 2px + color
    r = _rule(uss, "el-1_30")
    check("border 解析(2.0px→2px)",
          "border-width: 2px;" in r and "border-color: rgba(255,255,255,1);" in r)

    # 7. gradient 回退:合成元素,fill 取第一停靠色 + known-loss 记录
    gcap = {"frame": "9:1", "w": 100, "h": 100, "stageBg": "", "els": [{
        "id": "9:2", "name": "grad", "type": "RECTANGLE", "parent": "",
        "x": 0, "y": 0, "w": 100, "h": 100, "z": 1, "rot": 0, "opacity": 1,
        "radius": "", "border": "", "shadow": "", "blur": "",
        "fill": "linear-gradient(180deg, rgba(10,20,30,1) 0%, rgba(40,50,60,1) 100%)",
        "img": "", "imgSize": "", "text": None, "vec": False}]}
    guxml, guss, glosses = mod.convert(gcap, "grad")
    r = _rule(guss, "el-9_2")
    check("gradient 第一停靠色回退",
          "background-color: rgba(10,20,30,1);" in r
          and any("gradient" in l for l in glosses)
          and "gradient" in guss.split("*/")[0])

    # 8. known-loss 诚实降级:合成 shadow/blur/stroke 元素 → 属性不输出、头注释记录
    lcap = {"frame": "8:1", "w": 10, "h": 10, "stageBg": "", "els": [{
        "id": "8:2", "name": "lossy", "type": "FRAME", "parent": "",
        "x": 0, "y": 0, "w": 10, "h": 10, "z": 1, "rot": 0, "opacity": 1,
        "radius": "", "border": "", "shadow": "0px 4px 0px rgba(0,0,0,0.6)",
        "blur": "blur(4px)", "fill": "rgba(1,2,3,1)", "img": "", "imgSize": "",
        "text": None, "vec": False}]}
    luxml, luss, llosses = mod.convert(lcap, "lossy")
    head = luss.split("*/")[0]
    check("shadow/blur 跳过并记录",
          "box-shadow:" not in luss and "filter:" not in luss
          and "shadow" in head and "blur" in head)

    return ok

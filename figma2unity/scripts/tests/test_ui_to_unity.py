# -*- coding: utf-8 -*-
"""test_ui_to_unity.py — ui_to_unity 转换器单测(夹具 = fixtures/screen-login.ui.json)。"""
import importlib.util
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zlib

# 输出里有中文。Windows 上 stdout 的编码跟系统区域走(CI runner 是 Latin-1),
# 一 print 就 UnicodeEncodeError、退出码非 0 —— 而开发机是 GBK,中文编得动,一路绿。
# 这一条把本进程的输出钉成 UTF-8,让「能不能打印」不再取决于跑在谁的机器上。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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


def _png_pixels(path):
    """读回 ui_to_unity._png 写出的图 → [(r,g,b,a), …]。

    自己解码是因为**测试也不许引第三方库**(全仓零依赖),而这里只需要认它自己写的
    那一种:8 位 RGBA、逐行 filter=0。别的 PNG 一律不保证。
    """
    raw = open(path, "rb").read()
    w = h = None
    idat = b""
    i = 8
    while i < len(raw):
        ln = struct.unpack(">I", raw[i:i + 4])[0]
        tag = raw[i + 4:i + 8]
        body = raw[i + 8:i + 8 + ln]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype == 6, "只认 8 位 RGBA"
        elif tag == b"IDAT":
            idat += body
        i += 12 + ln
    data = zlib.decompress(idat)
    out = []
    stride = w * 4
    for y in range(h):
        row = data[y * (stride + 1) + 1: (y + 1) * (stride + 1)]
        for x in range(w):
            out.append(tuple(row[x * 4: x * 4 + 4]))
    return out


def _png_size(path):
    raw = open(path, "rb").read()
    return struct.unpack(">II", raw[16:24])


def _png_alpha_row(path):
    """中间那一行的 alpha 序列。"""
    w, h = _png_size(path)
    px = _png_pixels(path)
    return [p[3] for p in px[(h // 2) * w:(h // 2 + 1) * w]]


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
    # **硬阴影(blur=0)现在画得出来** —— USS 没有 box-shadow,但"同形状同圆角、按位移
    # 垫一个盒子在下面"正是硬阴影的定义,USS 完全表达得了。只有带模糊的才是真丢。
    check("硬阴影 → 垫层(不再是 known-loss)",
          "box-shadow:" not in luss and 'name="8_2-shadow"' in luxml
          and ".el-8_2-shadow" in luss and "top: 4px;" in _rule(luss, "el-8_2-shadow"))
    lblur = mod.convert({"frame": "X", "w": 100, "h": 50, "stageBg": "", "els": [
        dict(lcap["els"][0], id="l:2", shadow="0px 4px 9px rgba(0,0,0,0.6)")]}, "lossy2")[1]
    check("带模糊的阴影仍记 known-loss", "带模糊的阴影" in lblur.split("*/")[0])
    check("blur 跳过并记录", "filter:" not in luss and "blur" in head)

    # USS 选择器 = CSS 类名,合法字符只有 [A-Za-z0-9_-]。figma 有两类 id 会带别的字符:
    #   · 组件实例 `I25:4109;206:12513` —— 分号在 CSS 里是语句终止符
    #   · 遮罩包裹层 `25:1615~mask`     —— 波浪线是兄弟选择符
    # 后者 Unity 的导入器会报 "Invalid complex selector delimiter",**而且一条错就废掉
    # 整张样式表**:实测三条 `~mask` 让 129 条规则一条都没生效,播放器里每个元素都是
    # 1080×0 的透明盒子、整屏全黑(2026-08-05 于 Unity 2022.3.62f3 真播放器)。
    # 只换冒号的黑名单挡不住这些,必须白名单。
    scap = {"frame": "X", "w": 100, "h": 50, "stageBg": "", "els": [
        {"id": "I25:4109;206:12513", "name": "inst", "type": "RECTANGLE", "parent": "",
         "x": 0, "y": 0, "w": 10, "h": 10, "z": 1, "rot": 0, "opacity": 1,
         "radius": "2px", "border": "", "shadow": "", "blur": "", "fill": "rgba(1,2,3,1)",
         "img": "", "imgSize": "", "text": None, "vec": False},
        {"id": "25:1615~mask", "name": "mask", "type": "FRAME", "parent": "",
         "x": 0, "y": 0, "w": 10, "h": 10, "z": 2, "rot": 0, "opacity": 1,
         "radius": "2px", "border": "", "shadow": "", "blur": "", "fill": "rgba(4,5,6,1)",
         "img": "", "imgSize": "", "text": None, "vec": False}]}
    sx, su, _sl = mod.convert(scap, "sanitize")
    sels = [ln.strip() for ln in su.splitlines() if ln.strip().startswith(".el-")]
    check("USS 选择器只含 [A-Za-z0-9_-](分号与波浪线都得换掉)",
          bool(sels) and all(re.fullmatch(r"\.el-[A-Za-z0-9_-]+ \{", s) for s in sels))
    check("UXML 的 name/class 与选择器一致",
          all(('name="%s"' % s[4:-2]) in sx for s in sels))

    # 圆角要按 **CSS 的等比收缩**先夹好。Unity 是逐轴夹的(水平 w/2、垂直 h/2 各夹各的),
    # 235×42 配 57px 圆角在它手里变成 57×21 的椭圆角 —— 一颗被拉长的橄榄,
    # 而 CSS 会把四角同比缩到 21px = 标准胶囊。真稿里的胶囊标签就是这么变形的。
    pill = {"frame": "P", "w": 300, "h": 60, "stageBg": "", "els": [dict(
        lcap["els"][0], id="p:1", w=235.3, h=42.0, radius="57px", shadow="", blur="",
        fill="rgba(242,230,190,1.0)")]}
    puss = mod.convert(pill, "pill")[1]
    r = _rule(puss, "el-p_1")
    check("圆角按 CSS 等比夹紧(57px 于 235×42 → 21px 胶囊)",
          all(("border-%s-radius: 21px;" % k) in r
              for k in ("top-left", "top-right", "bottom-right", "bottom-left")))
    check("装得下就不夹", mod.clamp_radius(["8px"] * 4, 100, 50) == ["8px"] * 4)
    check("百分比不动(50% 在非正方形上本来就该是椭圆角)",
          mod.clamp_radius(["50%"] * 4, 300, 80) == ["50%"] * 4)

    # 折不折行看 IR 的 `text.wrap`(v1.3 读的 figma textAutoResize),不是"内容里有没有 \n"。
    # 只看 \n 的话定宽正文一行冲出面板 —— 而 html 与 godot 都已按 wrap 走,同一份 IR 三端三个样。
    def wrapped(**t):
        base = dict(content="文字内容最多五十个字", color="rgba(0,0,0,1)", size=36, family="X",
                    weight=400, lh=52, ls=0, alignH="flex-start", alignV="center",
                    textAlign="left", stroke="")
        base.update(t)
        cap = {"frame": "W", "w": 900, "h": 300, "stageBg": "", "els": [dict(
            lcap["els"][0], id="w:1", w=833.0, h=52.0, shadow="", blur="", fill="", text=base)]}
        return _rule(mod.convert(cap, "wrap")[1], "el-w_1")

    check("定宽正文(wrap=True)折行", "white-space: normal;" in wrapped(wrap=True))
    check("随字撑宽(wrap=False)不折行", "white-space: nowrap;" in wrapped(wrap=False))
    check("老产物无 wrap 字段时退回旧口径(看 \\n)",
          "white-space: nowrap;" in wrapped() and "white-space: normal;" in wrapped(content="a\nb"))
    # 单行盒已在捕获层归一成行盒(h == lh),行距无处可丢,不该再报 known-loss
    check("单行不再谎报丢了 line-height", not any("line-height" in x for x in mod.convert(
        {"frame": "W", "w": 900, "h": 300, "stageBg": "", "els": [dict(
            lcap["els"][0], id="w:2", w=200.0, h=48.0, shadow="", blur="", fill="",
            text=dict(content="一行", color="rgba(0,0,0,1)", size=36, family="X", weight=400,
                      lh=48, ls=0, alignH="center", alignV="center", textAlign="center",
                      wrap=False, stroke=""))]}, "one")[2]))

    # 9. 给了素材目录之后:带模糊的阴影与径向渐变都**烘成图**,不再是 known-loss。
    #    USS 既没有 box-shadow 也没有渐变属性,但"垫一个底是图片的盒子"它完全表达得了。
    tmp = tempfile.mkdtemp(prefix="figkit_uy_")
    try:
        scap = {"frame": "S", "w": 200, "h": 120, "stageBg": "", "els": [dict(
            lcap["els"][0], id="s:1", w=100.0, h=40.0, radius="8px", blur="",
            shadow="2px 4px 10px rgba(0,0,0,0.5)")]}
        suxml, suss, slosses = mod.convert(scap, "soft", tmp)
        r = _rule(suss, "el-s_1-softshadow")
        m = re.search(r'url\("assets/(shadow-[0-9a-f]+\.png)"\)', r)
        head = suss.split("*/")[0]
        check("带模糊的阴影 → 垫一层烘出来的 PNG(不再 known-loss)",
              bool(m) and 'name="s_1-softshadow"' in suxml
              and "烘成" in head
              and any("烘成" in x for x in slosses)
              and not any("丢弃" in x for x in slosses))
        if m:
            png = os.path.join(tmp, "assets", m.group(1))
            check("阴影图落盘且尺寸 = 元素 + 两侧 3σ", os.path.exists(png)
                  and _png_size(png) == (100 + 2 * 15, 40 + 2 * 15))
            a = _png_alpha_row(png)
            # 形状中心必须最浓(≈ 阴影色的 alpha),边缘必须散没 —— 反过来就是烘反了
            check("阴影中心浓、边缘散", a[len(a) // 2] > 100 and a[0] < 8
                  and a[len(a) // 2] > a[20] > a[2])
        # 垫层要排在本体**之前**:UI Toolkit 无 z-index,先出现的画在下面
        check("阴影垫层排在本体之前",
              suxml.index('name="s_1-softshadow"') < suxml.index('name="s_1"'))

        rcap = {"frame": "R", "w": 80, "h": 80, "stageBg": "", "els": [dict(
            lcap["els"][0], id="r:1", w=80.0, h=80.0, shadow="", blur="",
            fill="radial-gradient(rgba(255,0,0,1) 0%, rgba(0,0,255,1) 100%)")]}
        _, russ, _ = mod.convert(rcap, "radial", tmp)
        rr = _rule(russ, "el-r_1")
        rm = re.search(r'url\("assets/(grad-[0-9a-f]+\.png)"\)', rr)
        check("径向渐变 → 烘图(不再退首色)", bool(rm))
        if rm:
            px = _png_pixels(os.path.join(tmp, "assets", rm.group(1)))
            n = int(len(px) ** 0.5)
            mid = px[(n // 2) * n + n // 2]
            corner = px[0]
            check("径向:中心取首色、角落取末色",
                  mid[0] > 200 and mid[2] < 60 and corner[2] > 200 and corner[0] < 60)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return ok

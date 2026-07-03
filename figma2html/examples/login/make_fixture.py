# -*- coding: utf-8 -*-
"""合成 login 示例的三份 .ui.json(不需要 figma / token / 网络)。

原理:手工构造三棵"figma 节点树"(登录底屏 / 公告弹窗 / 选服列表),
喂给 scripts/figma_capture.py 的 capture() —— 走的是与真 figma 完全同一条捕获管线,
所以产物 schema 天然正确;改 capture 逻辑后重跑本脚本即可刷新示例。

用法: python make_fixture.py   (在本目录执行;产物 screen-*.ui.json 直接被 app.html 消费)
"""
import sys, os, json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
import figma_capture


def F(id, name, x, y, w, h, fill=None, radius=None, children=None, opacity=None):
    n = {"id": id, "name": name, "type": "FRAME", "visible": True,
         "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
         "fills": ([{"type": "SOLID", "visible": True, "color": fill[0], "opacity": fill[1]}] if fill else []),
         "children": children or []}
    if radius is not None:
        n["cornerRadius"] = radius
    if opacity is not None:
        n["opacity"] = opacity
    return n


def R(id, name, x, y, w, h, fill, radius=None, stroke=None):
    n = {"id": id, "name": name, "type": "RECTANGLE", "visible": True,
         "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
         "fills": [{"type": "SOLID", "visible": True, "color": fill[0], "opacity": fill[1]}]}
    if radius is not None:
        n["cornerRadius"] = radius
    if stroke:
        n["strokes"] = [{"type": "SOLID", "visible": True, "color": stroke[0]}]
        n["strokeWeight"] = stroke[1]
    return n


def T(id, name, x, y, w, h, chars, color, size, weight=400, alignH="CENTER", alignV="CENTER", lh=None):
    st = {"fontSize": size, "fontWeight": weight, "fontFamily": "Source Han Sans SC",
          "textAlignHorizontal": alignH, "textAlignVertical": alignV, "letterSpacing": 0}
    if lh:
        st["lineHeightPx"] = lh
    return {"id": id, "name": name, "type": "TEXT", "visible": True, "characters": chars,
            "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
            "fills": [{"type": "SOLID", "visible": True, "color": color[0], "opacity": color[1]}],
            "style": st}


# 颜色 (figma 0-1 浮点, opacity)
INK    = ({"r": 0.224, "g": 0.224, "b": 0.224}, 1)      # #393939
PAPER  = ({"r": 1.0,   "g": 0.984, "b": 0.949}, 1)      # #fffbf2
DEEP   = ({"r": 0.078, "g": 0.196, "b": 0.231}, 1)      # #14323b 深青底
GOLD   = ({"r": 0.937, "g": 0.749, "b": 0.0},   1)      # #efbf00
GOLDTX = ({"r": 1.0,   "g": 0.843, "b": 0.416}, 1)      # #ffd76a
WHITE  = ({"r": 1, "g": 1, "b": 1}, 1)
WHITE85= ({"r": 1, "g": 1, "b": 1}, 0.85)
WHITE20= ({"r": 1, "g": 1, "b": 1}, 0.2)
GREEN  = ({"r": 0.545, "g": 0.757, "b": 0.176}, 1)      # #8bc12d
LISTBG = ({"r": 0.945, "g": 0.914, "b": 0.847}, 1)      # #f1e9d8
BODY   = ({"r": 0.341, "g": 0.314, "b": 0.247}, 1)      # #57503f
BTNINK = ({"r": 0.227, "g": 0.165, "b": 0.0},   1)      # #3a2a00

# ── 底屏(登录) ──
base = F("1:1", "login-base", 0, 0, 1080, 1920, fill=DEEP, children=[
    T("1:3", "title", 0, 260, 1080, 110, "示例登录", WHITE, 88, 700),
    T("1:40", "notice-link", 900, 80, 140, 48, "公告", GOLDTX, 36, 500),
    F("1:10", "server-pill", 260, 1280, 560, 90, fill=PAPER, radius=45, children=[
        R("1:12", "gem", 286, 1302, 46, 46, GREEN, radius=23),
        T("1:11", "server-name", 350, 1300, 340, 50, "未选择", INK, 40, 500, alignH="LEFT"),
    ]),
    T("1:13", "switch-link", 850, 1300, 120, 50, "切换", GOLDTX, 34, 500),
    F("1:20", "enter-btn", 300, 1450, 480, 110, fill=GOLD, radius=55, children=[
        T("1:21", "enter-txt", 300, 1478, 480, 54, "开始游戏", BTNINK, 48, 800),
    ]),
    R("1:30", "agree-box", 300, 1640, 36, 36, WHITE20, radius=8, stroke=(WHITE[0], 2)),
    T("1:31", "agree-txt", 352, 1638, 620, 40, "已阅读并同意《示例用户协议》", WHITE85, 28, 400, alignH="LEFT"),
])

# ── 公告弹窗屏 ──
notice = F("2:1", "notice-screen", 0, 0, 1080, 1920, fill=DEEP, children=[
    F("2:10", "notice-panel", 160, 460, 760, 900, fill=PAPER, radius=24, children=[
        T("2:11", "notice-title", 160, 505, 760, 60, "公告", INK, 44, 700),
        T("2:12", "notice-body", 220, 610, 640, 680,
          "(占位正文,运行时由 app 填充)", BODY, 30, 400, alignH="LEFT", alignV="TOP", lh=48),
    ]),
])

# ── 选服列表屏 ──
def row(rid, y, name_txt):
    return F(rid, "server-row", 180, y, 720, 96, children=[
        R(rid + "1", "pill", 180, y, 720, 96, PAPER, radius=12),
        R(rid + "2", "gem", 204, y + 28, 40, 40, GREEN, radius=20),
        T(rid + "3", "row-name", 268, y + 26, 420, 44, name_txt, INK, 34, 500, alignH="LEFT"),
    ])

serverlist = F("3:1", "serverlist-screen", 0, 0, 1080, 1920, fill=DEEP, children=[
    F("3:10", "list-panel", 110, 380, 860, 1160, fill=PAPER, radius=24, children=[
        T("3:11", "list-title", 110, 425, 860, 60, "选择服务器", INK, 44, 700),
        F("3:20", "list-container", 160, 520, 760, 960, fill=LISTBG, radius=16, children=[
            row("3:2", 540, "一区·晨曦"),
            row("3:3", 652, "二区·薄暮"),
        ]),
    ]),
])

OUT = {"screen-login": base, "screen-notice": notice, "screen-serverlist": serverlist}
here = os.path.dirname(os.path.abspath(__file__))
for stem, tree in OUT.items():
    cap, missing = figma_capture.capture(tree, os.path.join(here, "_no_assets"), "assets")
    assert not missing, ("合成树不该有缺失素材", stem, missing)
    p = os.path.join(here, stem + ".ui.json")
    json.dump(cap, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote %s (%d els, %dx%d)" % (stem + ".ui.json", len(cap["els"]), cap["w"], cap["h"]))

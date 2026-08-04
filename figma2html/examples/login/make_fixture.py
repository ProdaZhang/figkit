# -*- coding: utf-8 -*-
"""合成 login 示例的三份 .ui.json(不需要 figma / token / 网络)。

原理:手工构造三棵"figma 节点树"(登录底屏 / 公告弹窗 / 选服列表),
喂给 scripts/figma_capture.py 的 capture() —— 走的是与真 figma 完全同一条捕获管线,
所以产物 schema 天然正确;改 capture 逻辑后重跑本脚本即可刷新示例。

用法:
    python3 make_fixture.py                       # 英文文案 → 本目录(= README 里那个 demo)
    python3 make_fixture.py --lang zh --out DIR   # 中文文案 → DIR(各后端 tests/fixtures 用这份)

**为什么两套文案**:`examples/login/` 是给访客看的门面,英文;
各后端 `scripts/tests/fixtures/` 里那份是**故意保留的中文版**,让 CJK 编码/字形/换行
一直在测试覆盖里(golden 逐字节比对的正是它)。两份都由本脚本产,别手改。

产物:
    screen-login.ui.json / screen-notice.ui.json / screen-serverlist.ui.json
    fixtures.js  —— 把上面三份 + flow.json 打包成 window.__FIGKIT_FIXTURES,
                    让 app.html 双击(file://)也能跑;浏览器在 file:// 下会拦掉 XHR。
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts'))
import figma_capture

# 输出里有中文。Windows 上 stdout 的编码跟系统区域走(CI runner 是 Latin-1),
# 一 print 就 UnicodeEncodeError、退出码非 0 —— 而开发机是 GBK,中文编得动,一路绿。
# 这一条把本进程的输出钉成 UTF-8,让「能不能打印」不再取决于跑在谁的机器上。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ── 文案(唯一区别所在;几何/结构两语言完全一致)────────────────────────────────
COPY = {
    "en": {
        "title": "Sample Login",
        "notice_link": "Notice",
        "unselected": "Not selected",
        "switch": "Switch",
        "enter": "START",
        "agree": "I have read and agree to the Terms",
        "notice_title": "Notice",
        "notice_body": "(placeholder body, filled by the app at runtime)",
        "list_title": "Select a server",
        "row_1": "S1 - Dawn",
        "row_2": "S2 - Dusk",
    },
    "zh": {
        "title": "示例登录",
        "notice_link": "公告",
        "unselected": "未选择",
        "switch": "切换",
        "enter": "开始游戏",
        "agree": "已阅读并同意《示例用户协议》",
        "notice_title": "公告",
        "notice_body": "(占位正文,运行时由 app 填充)",
        "list_title": "选择服务器",
        "row_1": "一区·晨曦",
        "row_2": "二区·薄暮",
    },
}


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


# ── 原型交互(figma REST 的 `interactions[]` 形状,逐字段照 rest-api-spec)──────────
# 这几条是"设计师在 figma 里连的线",不是 flow.json。它们喂给 scripts/flow_from_figma.py,
# 用来演示**哪些搬得动、哪些搬不动**:两条 OVERLAY 搬得动;弹窗里的 BACK、改变量、
# 非 click 触发器、换底屏的 NAVIGATE 都搬不动 —— 后者正是那份报告要说清的东西。
# capture() 不读这个键,所以三份 .ui.json 与各后端 golden 逐字节不受影响。
def _ease(kind, bezier=None, spring=None):
    e = {"type": kind}
    if bezier:
        e["easingFunctionCubicBezier"] = dict(zip(("x1", "y1", "x2", "y2"), bezier))
    if spring:
        e["easingFunctionSpring"] = spring
    return e


def click(*actions):
    return {"trigger": {"type": "ON_CLICK"}, "actions": list(actions)}


def to_node(dest, navigation, transition):
    return {"type": "NODE", "destinationId": dest, "navigation": navigation,
            "transition": transition}


def wire(node, *interactions):
    node["interactions"] = list(interactions)
    return node


def build_trees(C):
    """C = COPY[lang];返回 {stem: figma 节点树}。几何与两种语言无关。"""
    # ── 底屏(登录) ──
    open_notice = click(to_node("2:1", "OVERLAY", {
        "type": "DISSOLVE", "duration": 260, "easing": _ease("EASE_OUT")}))
    open_list = click(to_node("3:1", "OVERLAY", {
        "type": "MOVE_IN", "direction": "BOTTOM", "duration": 300,
        "easing": _ease("CUSTOM_CUBIC_BEZIER", bezier=(.32, .72, 0, 1))}))

    base = F("1:1", "login-base", 0, 0, 1080, 1920, fill=DEEP, children=[
        T("1:3", "title", 0, 260, 1080, 110, C["title"], WHITE, 88, 700),
        wire(T("1:40", "notice-link", 900, 80, 140, 48, C["notice_link"], GOLDTX, 36, 500),
             open_notice),
        wire(F("1:10", "server-pill", 260, 1280, 560, 90, fill=PAPER, radius=45, children=[
            R("1:12", "gem", 286, 1302, 46, 46, GREEN, radius=23),
            T("1:11", "server-name", 350, 1300, 340, 50, C["unselected"], INK, 40, 500, alignH="LEFT"),
        ]), open_list),
        wire(T("1:13", "switch-link", 850, 1300, 120, 50, C["switch"], GOLDTX, 34, 500),
             open_list),
        # 两条都搬不动,而且原因不同 —— 报告要能把它们分开说清:
        #   click → NAVIGATE:v1.0 是「base 常驻 + 弹窗叠加」,没有换底屏
        #   hover:v1.0 的 events[].on 只有 click
        wire(F("1:20", "enter-btn", 300, 1450, 480, 110, fill=GOLD, radius=55, children=[
            T("1:21", "enter-txt", 300, 1478, 480, 54, C["enter"], BTNINK, 48, 800),
        ]), click(to_node("3:1", "NAVIGATE", None)),
            {"trigger": {"type": "ON_HOVER"}, "actions": [to_node(None, "CHANGE_TO", None)]}),
        # 勾选协议在 figma 里是"改一个变量";flow 里它是 toggleFlag + guard —— 那是应用语义,手写。
        wire(R("1:30", "agree-box", 300, 1640, 36, 36, WHITE20, radius=8, stroke=(WHITE[0], 2)),
             click({"type": "SET_VARIABLE", "variableId": "VariableID:1:2",
                    "variableValue": {"resolvedType": "BOOLEAN", "value": True}})),
        T("1:31", "agree-txt", 352, 1638, 620, 40, C["agree"], WHITE85, 28, 400, alignH="LEFT"),
    ])

    # ── 公告弹窗屏 ──
    notice = F("2:1", "notice-screen", 0, 0, 1080, 1920, fill=DEEP, children=[
        # 关闭按钮住在**弹窗那一屏**。figma 里最常见的一条连线,而 v1.0 的 events 只绑 base 屏
        # (assemble.js 的 wireEvents 用 baseEl 找元素)—— 所以它必然搬不动,报告要点名。
        wire(F("2:10", "notice-panel", 160, 460, 760, 900, fill=PAPER, radius=24, children=[
            T("2:11", "notice-title", 160, 505, 760, 60, C["notice_title"], INK, 44, 700),
            T("2:12", "notice-body", 220, 610, 640, 680,
              C["notice_body"], BODY, 30, 400, alignH="LEFT", alignV="TOP", lh=48),
        ]), click({"type": "BACK"})),
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
            T("3:11", "list-title", 110, 425, 860, 60, C["list_title"], INK, 44, 700),
            F("3:20", "list-container", 160, 520, 760, 960, fill=LISTBG, radius=16, children=[
                row("3:2", 540, C["row_1"]),
                row("3:3", 652, C["row_2"]),
            ]),
        ]),
    ])
    return {"screen-login": base, "screen-notice": notice, "screen-serverlist": serverlist}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="合成 login 示例的 .ui.json(+ file:// 用的 fixtures.js)。",
        epilog="例: python3 make_fixture.py --lang zh --out ../../../figma2godot/scripts/tests/fixtures")
    ap.add_argument("--lang", choices=sorted(COPY), default="en",
                    help="文案语言(默认 en;各后端 tests/fixtures 用 zh)")
    ap.add_argument("--out", default=None, help="产物目录(默认本脚本所在目录)")
    ap.add_argument("--bundle", action="store_true",
                    help="强制产 fixtures.js(默认只在写回 demo 自己那个目录时产)")
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.abspath(args.out) if args.out else here
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    caps = {}
    trees = build_trees(COPY[args.lang])
    # nodes.json = figma REST 的响应形状(GET /v1/files/<key>/nodes?ids=…)。
    # 它是 figma_capture.py 与 flow_from_figma.py **共同的**输入,所以照着它就能把
    # README「Real Figma input」那几步在没有 figma 账号的情况下原样跑一遍。
    # 只在写回 demo 自己那个目录时产 —— 各后端 tests/fixtures 只吃 .ui.json,不需要它。
    if args.bundle or outdir == here:
        nodes = dict((t["id"], {"document": t}) for t in trees.values())
        with open(os.path.join(outdir, "nodes.json"), "w", encoding="utf-8", newline="") as f:
            json.dump({"nodes": nodes}, f, ensure_ascii=False, indent=1)
        print("wrote nodes.json (%d frames)" % len(nodes))

    for stem, tree in trees.items():
        cap, missing = figma_capture.capture(tree, os.path.join(here, "_no_assets"), "assets")
        assert not missing, ("合成树不该有缺失素材", stem, missing)
        caps[stem + ".ui.json"] = cap
        # newline="" 是必须的:不写就跟着平台走(Windows 出 CRLF、Linux 出 LF),
        # 产物不再逐字节可复现,而 .gitattributes 又强制 LF —— 两边永远对不上。
        with open(os.path.join(outdir, stem + ".ui.json"), "w", encoding="utf-8", newline="") as f:
            json.dump(cap, f, ensure_ascii=False, indent=1)
        print("wrote %s (%d els, %dx%d)" % (stem + ".ui.json", len(cap["els"]), cap["w"], cap["h"]))

    # fixtures.js 是 **demo 专用**的内联夹具(让 app.html 在 file:// 下可跑)。
    # 各后端 tests/fixtures 目录里也有 flow.json,但那儿只喂离线转换器测试,
    # 不该多出一个要维护新鲜度的生成物 —— 所以只在写回 demo 自己那个目录时产。
    flow_path = os.path.join(outdir, "flow.json")
    if (args.bundle or outdir == here) and os.path.exists(flow_path):
        with open(flow_path, encoding="utf-8") as f:
            bundle = {"flow.json": json.load(f)}
        bundle.update(caps)
        body = json.dumps(bundle, ensure_ascii=False, indent=1, sort_keys=True)
        js = ("// fixtures.js — GENERATED by make_fixture.py, do not edit.\n"
              "// 把 flow.json + 三份 .ui.json 内联进来,好让 app.html 在 file://(双击打开)下也能跑:\n"
              "// 浏览器出于安全会拦掉 file:// 页面对本地文件的 XHR,内联是唯一免服务器的走法。\n"
              "window.__FIGKIT_FIXTURES = " + body + ";\n")
        with open(os.path.join(outdir, "fixtures.js"), "w", encoding="utf-8", newline="\n") as f:
            f.write(js)
        print("wrote fixtures.js (%d entries, %d bytes)" % (len(bundle), len(js)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

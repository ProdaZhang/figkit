# -*- coding: utf-8 -*-
"""合成 main 示例的三份 .ui.json(不需要 figma / token / 网络)。

与 `examples/login/make_fixture.py` 同一个原理:手工构造 figma 节点树 → 喂给
`scripts/figma_capture.py` 的 `capture()`,走的是与真 figma 完全同一条捕获管线。

**这个示例存在的理由**,和 login 不一样:

  login 演的是**管线本身**(捕获 → IR → 六个后端),界面刻意做得最小。
  main 演的是**这套 IR 撑不撑得住一个真正的游戏界面**:66 个元素、三屏、
  两种弹窗形态(网格 / 列表)、两个页签被 guard 拦着,以及 ——

  **引擎不会替你做的那部分。** 领奖时金币飞进顶栏、数字滚上去、胶囊闪一下,
  这三条 figkit **一条都不实现**:它不知道哪个元素是"钱包"。它们写在 `app.js` 的
  hook 里,方法与参数取自 `figkit-motion`。这就是那个 skill 存在的全部理由,
  与其读散文不如点开看。

用法:
    python3 make_fixture.py                       # 英文文案 → 本目录
    python3 make_fixture.py --lang zh --out DIR   # 中文文案 → DIR

产物:
    screen-main.ui.json / screen-bag.ui.json / screen-codex.ui.json
    nodes.json    —— figma REST 响应形状(两条 OVERLAY 连线在里面,给 flow_from_figma.py)
    fixtures.js   —— 上面三份 + flow.json + 动效令牌子集,内联给 file:// 用
    flow.json     —— **就地补上默认动效**(motion.apply_defaults,幂等)
"""
import sys, os, json, argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', '..', 'scripts'))
import figma_capture
import motion


# ── 文案(唯一区别所在;几何/结构两语言完全一致)────────────────────────────────
COPY = {
    "en": {
        "gem": "1,280", "coin": "42,500", "energy": "60/60",
        "pet_name": "Sample Pet", "pet_lv": "Lv.12   ·   EXP 65%",
        "claim": "CLAIM  x3",
        "hint": "Tap CLAIM — the coins fly into the top bar, then the number rolls up",
        "tab_shop": "Shop", "tab_bag": "Bag", "tab_home": "Home",
        "tab_codex": "Codex", "tab_friends": "Friends",
        "bag_title": "Bag", "codex_title": "Codex",
        "row_1": "Dawn Sprite", "row_2": "Dusk Sprite",
    },
    "zh": {
        "gem": "1,280", "coin": "42,500", "energy": "60/60",
        "pet_name": "示例宠物", "pet_lv": "Lv.12   ·   经验 65%",
        "claim": "领取  x3",
        "hint": "点「领取」——金币飞进顶栏,数字随后滚上去",
        "tab_shop": "商店", "tab_bag": "背包", "tab_home": "主页",
        "tab_codex": "图鉴", "tab_friends": "好友",
        "bag_title": "背包", "codex_title": "图鉴",
        "row_1": "晨曦精灵", "row_2": "薄暮精灵",
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
INK    = ({"r": 0.224, "g": 0.224, "b": 0.224}, 1)
PAPER  = ({"r": 1.0,   "g": 0.984, "b": 0.949}, 1)
DEEP   = ({"r": 0.078, "g": 0.196, "b": 0.231}, 1)      # 底色,与 login 同一支
PANEL  = ({"r": 1, "g": 1, "b": 1}, 0.08)               # 卡片/顶栏的浅色玻璃
PANEL2 = ({"r": 1, "g": 1, "b": 1}, 0.14)
TRACK  = ({"r": 1, "g": 1, "b": 1}, 0.16)
GOLD   = ({"r": 0.937, "g": 0.749, "b": 0.0},   1)
GOLDTX = ({"r": 1.0,   "g": 0.843, "b": 0.416}, 1)
WHITE  = ({"r": 1, "g": 1, "b": 1}, 1)
WHITE85= ({"r": 1, "g": 1, "b": 1}, 0.85)
WHITE55= ({"r": 1, "g": 1, "b": 1}, 0.55)
GREEN  = ({"r": 0.545, "g": 0.757, "b": 0.176}, 1)
CYAN   = ({"r": 0.4,   "g": 0.85,  "b": 0.9},   1)
LISTBG = ({"r": 0.945, "g": 0.914, "b": 0.847}, 1)
BTNINK = ({"r": 0.227, "g": 0.165, "b": 0.0},   1)
ORB    = ({"r": 0.16,  "g": 0.62,  "b": 0.62},  1)


def _ease(kind, bezier=None):
    e = {"type": kind}
    if bezier:
        e["easingFunctionCubicBezier"] = dict(zip(("x1", "y1", "x2", "y2"), bezier))
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

    # 设计师在 figma 里连的两条线:底栏页签 → 弹窗。**只有这两条是原稿画的**;
    # 领奖、guard、列表绑定都是应用语义,手写在 flow.json 里(README「Real Figma input」第 5 步)。
    open_bag = click(to_node("4:1", "OVERLAY", {
        "type": "MOVE_IN", "direction": "BOTTOM", "duration": 300,
        "easing": _ease("CUSTOM_CUBIC_BEZIER", bezier=(.32, .72, 0, 1))}))
    open_codex = click(to_node("5:1", "OVERLAY", {
        "type": "DISSOLVE", "duration": 260, "easing": _ease("EASE_OUT")}))

    # ── 顶栏:三个货币胶囊 + 设置 ────────────────────────────────────────────
    def purse(pid, x, dot_color, txt):
        return F(pid, "purse", x, 60, 280, 96, fill=PANEL2, radius=48, children=[
            R(pid + "1", "purse-dot", x + 24, 86, 44, 44, dot_color, radius=22),
            T(pid + "2", "purse-num", x + 88, 82, 170, 52, txt, WHITE, 38, 700, alignH="LEFT"),
        ])

    # ── 底栏页签 ────────────────────────────────────────────────────────────
    def tab(tid, i, label, on):
        x = i * 216
        return F(tid, "tab", x, 1700, 216, 220, children=[
            R(tid + "1", "tab-icon", x + 58, 1744, 100, 100,
              GOLD if on else PANEL2, radius=26),
            T(tid + "2", "tab-label", x, 1858, 216, 40, label,
              GOLDTX if on else WHITE55, 28, 700 if on else 400),
        ])

    base = F("1:1", "main-base", 0, 0, 1080, 1920, fill=DEEP, children=[
        purse("1:10", 40, CYAN, C["gem"]),
        purse("1:11", 336, GOLD, C["coin"]),           # ← 飞向目标的终点 + 数字滚动的宿主
        purse("1:12", 632, GREEN, C["energy"]),
        R("1:13", "gear", 950, 63, 90, 90, PANEL2, radius=24),

        F("1:20", "pet-card", 90, 300, 900, 900, fill=PANEL, radius=32, children=[
            R("1:21", "pet-orb", 340, 420, 400, 400, ORB, radius=200),
            T("1:22", "pet-name", 90, 900, 900, 62, C["pet_name"], WHITE, 48, 700),
            T("1:23", "pet-lv", 90, 976, 900, 44, C["pet_lv"], GOLDTX, 30, 500),
            R("1:24", "xp-track", 240, 1060, 600, 24, TRACK, radius=12),
            R("1:25", "xp-fill", 240, 1060, 390, 24, GREEN, radius=12),
        ]),

        F("1:30", "claim-btn", 300, 1290, 480, 120, fill=GOLD, radius=60, children=[
            T("1:31", "claim-txt", 300, 1322, 480, 56, C["claim"], BTNINK, 44, 800),
        ]),
        T("1:32", "hint", 60, 1450, 960, 44, C["hint"], WHITE55, 26, 400),

        R("1:49", "bottom-bar", 0, 1700, 1080, 220, PANEL),
        wire(tab("1:50", 0, C["tab_shop"], False)),          # guard 拦着 —— 手写在 flow.json
        wire(tab("1:52", 1, C["tab_bag"], False), open_bag),
        tab("1:54", 2, C["tab_home"], True),
        wire(tab("1:56", 3, C["tab_codex"], False), open_codex),
        wire(tab("1:58", 4, C["tab_friends"], False)),
    ])

    # ── 背包弹窗:4×3 网格 ───────────────────────────────────────────────────
    # **网格没走 flow.list**:list 的模板行克隆按"前两行的 y 差"定行距,而网格的前两格
    # y 相同 → 步长 0 → 全叠在一起。它是一维机制,别硬套二维。
    # 所以格子在这儿就画满 12 个,由 app hook 填内容、并**自己做逐项入场**
    # (顺序是先行后列还是先列后行,只有做这个界面的人知道)。
    cells = []
    for k in range(12):
        cx, cy = 168 + (k % 4) * 192, 704 + (k // 4) * 192
        cells.append(F("4:%d" % (30 + k), "cell", cx, cy, 168, 168, fill=PAPER, radius=20, children=[
            R("4:%d" % (50 + k), "cell-dot", cx + 48, cy + 48, 72, 72, LISTBG, radius=36),
        ]))

    bag = F("4:1", "bag-screen", 0, 0, 1080, 1920, fill=DEEP, children=[
        F("4:10", "bag-panel", 90, 520, 900, 1080, fill=PAPER, radius=28, children=[
            T("4:11", "bag-title", 90, 570, 900, 60, C["bag_title"], INK, 44, 700),
            F("4:20", "bag-grid", 150, 680, 780, 840, fill=LISTBG, radius=20, children=cells),
        ]),
    ])

    # ── 图鉴弹窗:竖排列表(这条**走 flow.list**,逐项入场由引擎内置)───────────
    def row(rid, y, name_txt):
        return F(rid, "codex-row", 180, y, 720, 96, children=[
            R(rid + "1", "pill", 180, y, 720, 96, PAPER, radius=12),
            R(rid + "2", "dot", 204, y + 28, 40, 40, CYAN, radius=20),
            T(rid + "3", "row-name", 268, y + 26, 420, 44, name_txt, INK, 34, 500, alignH="LEFT"),
        ])

    codex = F("5:1", "codex-screen", 0, 0, 1080, 1920, fill=DEEP, children=[
        F("5:10", "codex-panel", 110, 460, 860, 1000, fill=PAPER, radius=24, children=[
            T("5:11", "codex-title", 110, 505, 860, 60, C["codex_title"], INK, 44, 700),
            F("5:20", "codex-list", 160, 600, 760, 800, fill=LISTBG, radius=16, children=[
                row("5:30", 620, C["row_1"]),
                row("5:31", 732, C["row_2"]),
            ]),
        ]),
    ])
    return {"screen-main": base, "screen-bag": bag, "screen-codex": codex}


# 内联给 app.js 用的令牌子集。**app.js 里一个动效数字都不许硬编** —— 硬编的那份
# 不会跟着 figkit-motion 改。名字就是目录里的令牌名,查得回去。
MOTION_TOKENS = ["fly-dur", "fly-hold", "fly-arc", "fly-stagger",
                 "tween-num", "flash", "stagger", "dur-popup", "slide-from", "ease-out"]


def motion_subset():
    p = os.path.join(_HERE, "..", "..", "..", "figkit-motion", "tokens.json")
    with open(p, encoding="utf-8") as f:
        all_tokens = json.load(f)
    return dict((k, all_tokens[k]["value"]) for k in MOTION_TOKENS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="合成 main 示例的 .ui.json(+ file:// 用的 fixtures.js)。")
    ap.add_argument("--lang", choices=sorted(COPY), default="en")
    ap.add_argument("--out", default=None)
    ap.add_argument("--bundle", action="store_true")
    args = ap.parse_args(argv)

    outdir = os.path.abspath(args.out) if args.out else _HERE
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    caps = {}
    trees = build_trees(COPY[args.lang])
    if args.bundle or outdir == _HERE:
        nodes = dict((t["id"], {"document": t}) for t in trees.values())
        with open(os.path.join(outdir, "nodes.json"), "w", encoding="utf-8", newline="") as f:
            json.dump({"nodes": nodes}, f, ensure_ascii=False, indent=1)
        print("wrote nodes.json (%d frames)" % len(nodes))

    for stem, tree in trees.items():
        cap, missing = figma_capture.capture(tree, os.path.join(_HERE, "_no_assets"), "assets")
        assert not missing, ("合成树不该有缺失素材", stem, missing)
        caps[stem + ".ui.json"] = cap
        with open(os.path.join(outdir, stem + ".ui.json"), "w", encoding="utf-8", newline="") as f:
            json.dump(cap, f, ensure_ascii=False, indent=1)
        print("wrote %s (%d els, %dx%d)" % (stem + ".ui.json", len(cap["els"]), cap["w"], cap["h"]))

    flow_path = os.path.join(outdir, "flow.json")
    if (args.bundle or outdir == _HERE) and os.path.exists(flow_path):
        with open(flow_path, encoding="utf-8") as f:
            flow = json.load(f)
        # **默认动效在这儿补,不手抄。** apply_defaults 幂等:已经有的一条不碰,
        # 补出来的每条带 source:"preset:base"。手抄的话,PRESET 改了这份不会跟着改。
        flow, added = motion.apply_defaults(flow)
        with open(flow_path, "w", encoding="utf-8", newline="") as f:
            json.dump(flow, f, ensure_ascii=False, indent=1)
        for a in added:
            print("  motion + " + a)
        bundle = {"flow.json": flow, "motion-tokens": motion_subset()}
        bundle.update(caps)
        body = json.dumps(bundle, ensure_ascii=False, indent=1, sort_keys=True)
        js = ("// fixtures.js — GENERATED by make_fixture.py, do not edit.\n"
              "// flow.json + 三份 .ui.json + 动效令牌子集,内联给 file://(双击打开)用。\n"
              "window.__FIGKIT_FIXTURES = " + body + ";\n")
        with open(os.path.join(outdir, "fixtures.js"), "w", encoding="utf-8", newline="\n") as f:
            f.write(js)
        print("wrote fixtures.js (%d entries, %d bytes)" % (len(bundle), len(js)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

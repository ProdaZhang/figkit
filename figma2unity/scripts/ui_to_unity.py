# -*- coding: utf-8 -*-
"""ui_to_unity.py — figma2html 的 .ui.json(IR)→ Unity UI Toolkit 资产(UXML + USS)。

用法:
    python3 ui_to_unity.py <cap.ui.json> <outdir>
产物:
    <outdir>/<stem>.uxml + <outdir>/<stem>.uss
    (stem = 输入文件名去掉 .ui.json / .json 后缀,如 screen-login)

映射规则(全表见 ../references/mapping.md):
- 每个 IR 元素 → 一个 VisualElement(TEXT → Label),UXML name = figma id 把 ':' 换 '_'
  (UXML name 属性不允许冒号;USS 选择器用 .el-<name> 类,因为名字可能以数字开头,
   而 CSS/USS 的 #id 选择器不能以数字开头)。
- 几何:position:absolute + left/top/width/height,父相对(算法同 render.js pass2:
  child.left = child.x - parent.x)。
- z 序:按文档序生成 UXML 兄弟节点(同父下按 z 稳定排序);UI Toolkit 无 z-index,
  后出现的兄弟绘制在上层,与 render.js 的 zIndex 视觉一致。
- 诚实降级(known-loss):shadow / blur / text.stroke USS 不支持 → 跳过并记录在
  生成的 .uss 文件头注释;gradient 填充 → 取第一停靠色纯色回退,同样记录。

约束:纯标准库、确定性输出(无时间戳/随机),同一输入永远得到逐字节相同的产物。
"""
import hashlib
import json
import math
import os
import re
import sys

# motion.py 是 figma2html/scripts/motion.py 的**逐字节镜像**(skill 必须自足、可单独安装,
# 跨目录 import 装成插件就断)。两份漂了由 tools/conformance 的 byte-parity 用例当场红。
# 显式把本文件所在目录入 path:当本模块**被测试 import**(而不是当脚本跑)时,
# sys.path[0] 是测试目录,裸 `import motion` 会 ModuleNotFoundError。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import motion

INDENT = "  "


# ── 小工具 ──────────────────────────────────────────────────────────────

def fmt_num(v):
    """数值 → 最短确定性字符串(2.0 → '2',26.5 → '26.5')。"""
    f = float(v)
    if f == int(f):
        return str(int(f))
    return ("%g" % f)


# USS 选择器 = CSS 类名,合法字符只有 [A-Za-z0-9_-](首字符另有讲究,这里靠 `.el-` 前缀兜住)。
# **黑名单换字符是不够的**:只换冒号会把 figma 的另外两类 id 原样带进选择器 ——
#   · 组件实例:`I25:4109;206:12513` → `.el-I25_4109;206_12513`,分号在 CSS 里是语句终止符;
#   · 遮罩包裹层:`25:1615~mask` → `.el-I25_1615~mask`,波浪线是 CSS 的兄弟选择符。
# 后者 Unity 的 USS 导入器会直接报 "Invalid complex selector delimiter",**而且一条错就把
# 整张样式表废掉** —— 实测:三条 `~mask` 让 129 条规则一条都没生效,播放器里
# 每个元素都是 1080×0 的透明盒子,整屏全黑。前者更阴:导入器一声不吭,规则照样丢。
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def safe_name(figma_id):
    """figma id → UXML name / USS 类名。**白名单**,不是黑名单(见上方注释)。"""
    return _UNSAFE.sub("_", str(figma_id))


def xml_escape(s):
    """XML 属性值转义;换行转 &#10;(Label 多行文本)。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("\r", "").replace("\n", "&#10;"))


def split_top_level(s, sep=","):
    """按顶层 sep 切分(忽略括号内的 sep,rgba(…) 里的逗号不切)。"""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


# ── CSS 风格字符串解析 ──────────────────────────────────────────────────

def parse_radius(radius):
    """'45px' / 'a b' / 'a b c' / 'a b c d' → [TL, TR, BR, BL](CSS 简写展开规则)。"""
    toks = radius.split()
    if not toks:
        return None
    if len(toks) == 1:
        a = toks[0]
        return [a, a, a, a]
    if len(toks) == 2:
        a, b = toks
        return [a, b, a, b]
    if len(toks) == 3:
        a, b, c = toks
        return [a, b, c, b]
    return toks[:4]


_PX_ONLY = re.compile(r"^([\d.]+)px$")


def clamp_radius(vals, w, h):
    """按 **CSS 的等比收缩规则**夹紧四角半径(CSS Backgrounds §5.5)。

    半径之和超过边长时,CSS 是把**四个角按同一个比例**一起缩;
    Unity 是**逐轴**夹的(水平夹到 w/2、垂直夹到 h/2,各夹各的)。
    于是 235×42 的盒子配 57px 圆角:CSS 缩成 21px = 标准胶囊,Unity 留成
    57×21 的椭圆角 = 一颗被拉长的橄榄。真稿里的胶囊标签就是这么变形的。
    在这儿先按 CSS 的口径夹好,Unity 那套逐轴夹紧就再也轮不上了。

    百分比不动:`50%` 在非正方形盒子上本来就该是椭圆角(捕获层给 ELLIPSE 发的就是它)。
    """
    nums = []
    for v in vals:
        m = _PX_ONLY.match(str(v).strip())
        if not m:
            return vals
        nums.append(float(m.group(1)))
    tl, tr, br, bl = nums
    f = 1.0
    for total, edge in ((tl + tr, w), (br + bl, w), (tr + br, h), (bl + tl, h)):
        if total > 0 and edge > 0:
            f = min(f, float(edge) / total)
    if f >= 1.0:
        return vals
    return [fmt_num(round(n * f, 2)) + "px" for n in nums]


BORDER_RE = re.compile(r"^\s*([\d.]+)px\s+([A-Za-z]+)\s+(.+?)\s*$")


def parse_border(border):
    """'2.0px solid rgba(...)' → (width_px_str, style, color);解析失败返回 None。"""
    m = BORDER_RE.match(border)
    if not m:
        return None
    return fmt_num(m.group(1)), m.group(2), m.group(3)


COLOR_TOKEN_RE = re.compile(r"(rgba?\([^)]*\)|hsla?\([^)]*\)|#[0-9a-fA-F]{3,8})")


def first_gradient_color(fill):
    """渐变 css('linear-gradient(180deg, rgba(a) 0%, …)')→ 第一停靠色;找不到返回 None。"""
    lp = fill.find("(")
    rp = fill.rfind(")")
    if lp < 0 or rp < 0 or rp <= lp:
        return None
    for part in split_top_level(fill[lp + 1:rp]):
        m = COLOR_TOKEN_RE.search(part)
        if m:
            return m.group(1)
    return None


FONT_DIR = "fonts"     # 设计字体目录(相对 uss);FigCJK-Regular.ttf / -Bold.ttf
GRAD_TEX = 64          # 渐变纹理边长;双线性放大后 172px 的奖励底已看不出色阶


def parse_gradient(fill):
    """'linear-gradient(0deg, rgba(..) 0%, rgba(..) 100%)' → (角度, [(位置, (r,g,b,a)), …])。

    认不出(径向渐变、缺停靠位)返回 None,调用方退回首色。
    """
    m = re.match(r"^\s*linear-gradient\((.*)\)\s*$", fill, re.S)
    if not m:
        return None
    parts = split_top_level(m.group(1))
    if len(parts) < 3:
        return None
    a = re.match(r"^\s*(-?[\d.]+)deg\s*$", parts[0])
    if not a:
        return None
    stops = []
    for p in parts[1:]:
        cm = COLOR_TOKEN_RE.search(p)
        pm = re.search(r"(-?[\d.]+)\s*%", p[cm.end():] if cm else "")
        if not cm or not pm:
            return None
        nums = re.findall(r"-?[\d.]+", cm.group(1))
        if len(nums) < 3:
            return None
        alpha = float(nums[3]) if len(nums) > 3 else 1.0
        stops.append((float(pm.group(1)) / 100.0,
                      (int(round(float(nums[0]))), int(round(float(nums[1]))),
                       int(round(float(nums[2]))), alpha)))
    if len(stops) < 2:
        return None
    stops.sort(key=lambda s: s[0])
    return float(a.group(1)), stops


def _png(w, h, rgba):
    """裸 RGBA → PNG 字节。自己写是为了**不引 Pillow** —— figkit 全仓零第三方依赖。"""
    import struct
    import zlib
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def gradient_asset(fill, w, h, asset_dir, losses, eid):
    """线性渐变 → 烘一张 PNG,返回相对 uss 的 url;烘不了返回 None(调用方退首色)。

    USS 没有渐变属性,以前这里是"取第一停靠色"的 known-loss —— 奖励底那种上下双色的
    红块整块变成单色。改成**编译期**烘图:每个纹素按元素真实 w/h 投影到渐变轴再插值,
    所以任意角度都准,不是只处理 0/90° 的特例。编译期做而不是运行时,是为了不给
    集成方多加一段运行时代码,也让产物保持确定性(同输入同字节)。
    """
    if not asset_dir:
        return None
    g = parse_gradient(fill)
    if not g:
        return None
    ang, stops = g
    n = GRAD_TEX
    rad = math.radians(ang)
    dx, dy = math.sin(rad), -math.cos(rad)          # CSS:0deg 指向上方,顺时针增大
    ln = abs(w * dx) + abs(h * dy)                  # 渐变线长度(CSS Images §3.3)
    buf = bytearray(n * n * 4)
    for j in range(n):
        for i in range(n):
            px = ((i + 0.5) / n - 0.5) * w
            py = ((j + 0.5) / n - 0.5) * h
            t = 0.5 if ln <= 0 else 0.5 + (px * dx + py * dy) / ln
            t = min(1.0, max(0.0, t))
            lo, hi = stops[0], stops[-1]
            for k in range(len(stops) - 1):
                if stops[k][0] <= t <= stops[k + 1][0]:
                    lo, hi = stops[k], stops[k + 1]
                    break
            f = 0.0 if hi[0] <= lo[0] else (t - lo[0]) / (hi[0] - lo[0])
            o = (j * n + i) * 4
            for ch in range(3):
                buf[o + ch] = int(round(lo[1][ch] + (hi[1][ch] - lo[1][ch]) * f))
            buf[o + 3] = int(round((lo[1][3] + (hi[1][3] - lo[1][3]) * f) * 255))
    name = "grad-%s.png" % hashlib.sha1(
        ("%s|%.3f|%.3f" % (fill, w, h)).encode("utf-8")).hexdigest()[:16]
    sub = os.path.join(asset_dir, "assets")
    os.makedirs(sub, exist_ok=True)
    with open(os.path.join(sub, name), "wb") as f:
        f.write(_png(n, n, bytes(buf)))
    losses.append("%s: gradient '%s' 烘成 assets/%s(USS 无渐变属性,编译期出图)" % (eid, fill, name))
    return "assets/" + name


TEXT_ALIGN_V = {"flex-start": "upper", "center": "middle", "flex-end": "lower"}
TEXT_ALIGN_H = {"left": "left", "center": "center", "right": "right"}

# `0 0 0 Npx <色>` = capture 给 OUTSIDE/CENTER 描边塞在 shadow 头部的**描边环**,不是阴影
# (CSS 里 box-shadow 跟随 border-radius,outline 不跟,所以借了 shadow 这个位置)。
# 零值三段按 CSS 规矩可以不带单位,别只认一种写法。
RING_RE = re.compile(r"^\s*0(?:px)?\s+0(?:px)?\s+0(?:px)?\s+([\d.]+)px\s+(rgba?\([^)]*\))\s*$")
# 硬阴影 = blur 为 0:CSS 的语义是"整个形状按位移复制一份、填成阴影色",
# 用一个垫在下面的同圆角盒子就能精确还原;带模糊的才是 USS 真表达不了的。
HARD_SHADOW_RE = re.compile(
    r"^\s*(-?[\d.]+)(?:px)?\s+(-?[\d.]+)(?:px)?\s+0(?:px)?\s*(?:0(?:px)?\s*)?(rgba?\([^)]*\))\s*$")


def split_ring(shadow, align):
    """把描边环从 shadow 串里拆出来 → ((宽, 色) | None, 剩下的 shadow 串)。"""
    if not shadow or align not in ("outside", "center"):
        return None, shadow
    parts = split_top_level(shadow, ",")
    m = RING_RE.match(parts[0]) if parts else None
    if not m:
        return None, shadow
    return (float(m.group(1)), m.group(2)), ",".join(parts[1:])


def underlays(el):
    """本元素需要**垫在下面**的额外盒子 → [(后缀, 几何偏移 dict, 属性列表), ...]。

    USS 没有 box-shadow,但"多画一个盒子"是它完全表达得了的 —— 而硬阴影与描边环
    本来就是"同形状的另一个盒子"。这么做比记 known-loss 诚实得多:
      · 硬阴影 `2px 6px 0px c` → 同尺寸同圆角、按 (2,6) 位移、填阴影色;
      · OUTSIDE 描边环 `0 0 0 Npx c` → 四边各外扩 N、圆角 +N、填描边色。
    两者都排在本体**之前**(UI Toolkit 无 z-index,先出现的在下面)。
    """
    out = []
    align = (el.get("borderAlign") or "").lower()
    ring, rest = split_ring(el.get("shadow") or "", align)
    radius = el.get("radius") or ""
    if ring:
        n, color = ring
        r = parse_radius(radius)
        props = [("position", "absolute"),
                 ("left", fmt_num(-n) + "px"), ("top", fmt_num(-n) + "px"),
                 ("width", fmt_num((el.get("w") or 0) + 2 * n) + "px"),
                 ("height", fmt_num((el.get("h") or 0) + 2 * n) + "px"),
                 ("background-color", color)]
        if r:
            grown = clamp_radius([_grow_radius(v, n) for v in r],
                                 (el.get("w") or 0) + 2 * n, (el.get("h") or 0) + 2 * n)
            for k, v in zip(("top-left", "top-right", "bottom-right", "bottom-left"), grown):
                props.append(("border-%s-radius" % k, v))
        out.append(("ring", props))
    for part in split_top_level(rest, ","):
        m = HARD_SHADOW_RE.match(part.strip())
        if not m:
            continue
        dx, dy, color = fmt_num(m.group(1)), fmt_num(m.group(2)), m.group(3)
        props = [("position", "absolute"), ("left", dx + "px"), ("top", dy + "px"),
                 ("width", fmt_num(el.get("w") or 0) + "px"),
                 ("height", fmt_num(el.get("h") or 0) + "px"),
                 ("background-color", color)]
        r = parse_radius(radius)
        if r:
            r = clamp_radius(r, el.get("w") or 0, el.get("h") or 0)
            for k, v in zip(("top-left", "top-right", "bottom-right", "bottom-left"), r):
                props.append(("border-%s-radius" % k, v))
        out.append(("shadow", props))
    return out


def _rebase(props, el, parent):
    """垫层的几何是相对本体写的,而它实际挂在本体的**父级**里 —— 转成父相对。"""
    px = parent.get("x", 0) if parent else 0
    py = parent.get("y", 0) if parent else 0
    base_x, base_y = (el.get("x", 0) - px), (el.get("y", 0) - py)
    out = []
    for k, v in props:
        if k == "left":
            v = fmt_num(base_x + float(str(v)[:-2])) + "px"
        elif k == "top":
            v = fmt_num(base_y + float(str(v)[:-2])) + "px"
        out.append((k, v))
    return out


def encode_paths(paths):
    """paths → FigVector 的 `paths` 属性串。分隔符挑的是路径串里不会出现的字符:
    条目之间 `;;`,字段之间 `|`(SVG 的 d 只有字母/数字/点/负号/逗号/空格)。"""
    return ";;".join("%s|%s|%s|%s" % (p.get("d", ""), p.get("fill", ""),
                                      p.get("rule", "nonzero"), p.get("clip", "") or "")
                     for p in paths or [])


def _grow_radius(v, n):
    """描边环比本体大 N,圆角也要跟着大 N,不然外圈会比内圈方。"""
    s = str(v).strip()
    if s.endswith("px"):
        return fmt_num(float(s[:-2]) + n) + "px"
    if s.endswith("%"):
        return s
    try:
        return fmt_num(float(s) + n) + "px"
    except ValueError:
        return s


# ── 转换主体 ────────────────────────────────────────────────────────────

def build_uss_props(el, parent, losses, asset_dir=None):
    """单个 IR 元素 → USS 属性列表(有序、确定性)。losses 收集丢弃/降级项。"""
    props = []
    eid = el.get("id", "?")
    # 几何:父相对(render.js pass2 同款算法)
    px = parent.get("x", 0) if parent else 0
    py = parent.get("y", 0) if parent else 0
    props.append(("position", "absolute"))
    props.append(("left", fmt_num(el.get("x", 0) - px) + "px"))
    props.append(("top", fmt_num(el.get("y", 0) - py) + "px"))
    props.append(("width", fmt_num(el.get("w", 0)) + "px"))
    props.append(("height", fmt_num(el.get("h", 0)) + "px"))

    rot = el.get("rot", 0)
    if rot:
        props.append(("rotate", fmt_num(rot) + "deg"))  # transform-origin 默认即 center
    opacity = el.get("opacity", 1)
    if opacity != 1:
        props.append(("opacity", fmt_num(opacity)))

    radius = el.get("radius") or ""
    if radius:
        r = parse_radius(radius)
        if r:
            r = clamp_radius(r, el.get("w") or 0, el.get("h") or 0)
            props.append(("border-top-left-radius", r[0]))
            props.append(("border-top-right-radius", r[1]))
            props.append(("border-bottom-right-radius", r[2]))
            props.append(("border-bottom-left-radius", r[3]))

    border = el.get("border") or ""
    if border:
        b = parse_border(border)
        if b:
            width, style, color = b
            props.append(("border-width", width + "px"))
            props.append(("border-color", color))
            if style.lower() != "solid":
                losses.append("%s: border-style '%s' 降级为 solid(USS 边框恒为实线)" % (eid, style))
        else:
            losses.append("%s: border '%s' 无法解析,已跳过" % (eid, border))

    # shadow 里可能混着两样东西:真阴影,和 borderAlign=outside/center 塞在头部的**描边环**。
    # 两者都由 `underlays()` 变成垫在本体下面的额外元素(USS 没有 box-shadow,但多画一个
    # 盒子是完全表达得了的),这里只把**剩下画不出来的**记成 known-loss。
    _ring, rest = split_ring(el.get("shadow") or "", (el.get("borderAlign") or "").lower())
    soft = [p for p in split_top_level(rest, ",") if p.strip() and not HARD_SHADOW_RE.match(p.strip())]
    if soft:
        losses.append("%s: 带模糊的阴影 '%s' 丢弃(USS 无 box-shadow;硬阴影已用垫层还原)"
                      % (eid, ", ".join(s.strip() for s in soft)))
    if el.get("blur"):
        losses.append("%s: blur '%s' 丢弃(USS 无 filter)" % (eid, el["blur"]))

    # ── v1.1 的裁剪:UI Toolkit 的 overflow:hidden **跟随 border-radius**,
    #    所以圆角裁剪这里是天然对的(Godot 那边得靠 clip_children 才做得到)。
    if el.get("clip"):
        props.append(("overflow", "hidden"))

    # ── v1.2 矢量:交给 FigVector(Painter2D)真画。**INSIDE 描边带只能全宽画** ——
    #    Painter2D 没有布尔裁剪,OUTSIDE 那半可以靠"带子在下、填充盖上"精确做掉,
    #    INSIDE 那半没有等价技巧(html 用 clipPath,godot 交给 SVG 导入器)。
    inside = [q for q in (el.get("paths") or []) if (q.get("clip") or "") in ("inside", "center")]
    if inside:
        losses.append("%s: %d 条 INSIDE/CENTER 描边带按全宽(2w)绘制 —— Painter2D 无布尔裁剪,"
                      "描边会比设计稿粗一倍" % (eid, len(inside)))

    text = el.get("text")
    if text:
        props.append(("margin", "0"))    # Label 内建样式带 padding,压平以保几何
        props.append(("padding", "0"))
        props.append(("color", text.get("color", "rgba(0,0,0,1)")))
        props.append(("font-size", fmt_num(text.get("size", 14)) + "px"))
        weight = text.get("weight", 400)
        # **接了设计字体就不能再写 `-unity-font-style: bold`** —— 那会在已经是 Bold 的
        # 字面上再合成一次粗体,笔画明显肿一圈(实测标题的墨水像素 1930 → 2613)。
        # 只有回退到系统字体时才需要它来近似字重。
        props.append(("-unity-font-style", "normal"))
        if weight not in (400, 700):
            losses.append("%s: font-weight %s 近似为 %s(设计字体只出 Regular/Bold 两档)"
                          % (eid, weight, "Bold" if weight >= 600 else "Regular"))
        av = TEXT_ALIGN_V.get(text.get("alignV", "center"), "middle")
        ah = TEXT_ALIGN_H.get(text.get("textAlign", "center"), "center")
        props.append(("-unity-text-align", av + "-" + ah))
        ls = text.get("ls", 0)
        if ls:
            props.append(("letter-spacing", fmt_num(ls) + "px"))
        # 该不该折行由 IR 的 `text.wrap` 说了算(v1.3,读的是 figma 的 textAutoResize),
        # 不是"内容里有没有 \n"。只看 \n 的后果:定宽正文一行冲出面板(邮件正文就是这样),
        # 而 html 与 godot 都已经按 wrap 走 —— 同一份 IR 三端折出三个样。
        # wrap 缺失 = v1.3 之前的老产物,退回旧口径。
        multi = bool(text.get("wrap")) or "\n" in str(text.get("content", ""))
        props.append(("white-space", "normal" if multi else "nowrap"))
        props.append(("overflow", "visible"))
        # 单行文本的盒子在捕获层已经归一成行盒(h == lh),行距无处可丢;
        # 只有装得下两行以上的框才真的少了行距。
        lh = text.get("lh") or 0
        if lh and (el.get("h") or 0) > lh * 1.5:
            losses.append("%s: 多行的 line-height %spx 丢弃(USS 无 line-height,行距按字体默认)"
                          % (eid, lh))
        if text.get("stroke"):
            losses.append("%s: text-stroke '%s' 丢弃(USS 无字形描边)" % (eid, text["stroke"]))
        # 设计字体:约定 `<FONT_DIR>/FigCJK-Regular.ttf` / `-Bold.ttf` 与 uss 同级。
        # 四端共用同一份字形 —— 否则每端各拿系统默认字体,连**换行位置**都对不上
        # (同一段定宽正文,html 断在第 12 字、unity 断在第 14 字),像素比剩下的全是字形噪声。
        face = "Bold" if (text.get("weight") or 400) >= 600 else "Regular"
        props.append(("-unity-font-definition",
                      'url("%s/FigCJK-%s.ttf")' % (FONT_DIR, face)))
        fam = text.get("family", "")
        if fam and fam not in ("Source Han Sans SC", "Noto Sans SC"):
            losses.append("%s: font-family '%s' 与内置的 FigCJK 子集不同,已用 FigCJK 顶替" % (eid, fam))
    elif el.get("img"):
        props.append(("background-image", 'url("%s")' % el["img"]))
        props.append(("background-size", el.get("imgSize") or "cover"))
        props.append(("background-position", "center"))
        props.append(("background-repeat", "no-repeat"))
    elif el.get("fill"):
        fill = el["fill"]
        if "gradient(" in fill:
            url = gradient_asset(fill, el.get("w") or 0, el.get("h") or 0, asset_dir, losses, eid)
            if url:
                props.append(("background-image", 'url("%s")' % url))
                props.append(("background-size",
                              fmt_num(el.get("w") or 0) + "px " + fmt_num(el.get("h") or 0) + "px"))
                props.append(("background-repeat", "no-repeat"))
            else:
                c = first_gradient_color(fill)
                if c:
                    props.append(("background-color", c))
                    losses.append("%s: gradient '%s' 回退为第一停靠色 %s(烘图失败)" % (eid, fill, c))
                else:
                    losses.append("%s: gradient '%s' 无法解析停靠色,已跳过" % (eid, fill))
        else:
            props.append(("background-color", fill))
    return props


def build_root_props(cap, losses):
    """帧根(.screen-root)的 USS 属性:尺寸 + stageBg。"""
    props = [("position", "absolute"), ("left", "0"), ("top", "0"),
             ("width", fmt_num(cap.get("w", 0)) + "px"),
             ("height", fmt_num(cap.get("h", 0)) + "px"),
             ("overflow", "hidden")]
    bg = cap.get("stageBg") or ""
    if bg:
        m = re.search(r"url\(([^)]+)\)", bg)
        if m:
            props.append(("background-image", 'url("%s")' % m.group(1).strip("'\"")))
            props.append(("background-size", "cover"))
            props.append(("background-position", "center"))
            props.append(("background-repeat", "no-repeat"))
        elif "gradient(" in bg:
            c = first_gradient_color(bg)
            if c:
                props.append(("background-color", c))
                losses.append("stageBg: gradient '%s' 回退为第一停靠色 %s" % (bg, c))
        else:
            props.append(("background-color", bg))
    return props


def convert(cap, stem, asset_dir=None):
    """cap(dict,.ui.json 内容)→ (uxml_str, uss_str, losses)。纯函数、确定性。"""
    els = cap.get("els")
    if not isinstance(els, list):
        raise ValueError("cap.els 缺失或不是数组 —— 这不是 figma2html 的 .ui.json?")

    rec_by_id = {}
    for el in els:
        if "id" not in el:
            raise ValueError("存在缺 id 的元素记录")
        rec_by_id[el["id"]] = el

    # 父 → 子(保输入序),之后同父下按 z 稳定排序(文档序 = 绘制序,USS 无 z-index)
    children = {}
    roots = []
    for i, el in enumerate(els):
        pid = el.get("parent") or ""
        if pid and pid in rec_by_id:
            children.setdefault(pid, []).append((i, el))
        else:
            roots.append((i, el))

    def sort_key(pair):
        return (pair[1].get("z", 0), pair[0])

    losses = []
    uss_rules = []   # (selector, props)
    uxml_lines = []
    visited = set()

    uss_rules.append((".screen-root", build_root_props(cap, losses)))

    def emit(el, parent, depth):
        if el["id"] in visited:   # parent 成环兜底时防重复/防无限递归
            return
        visited.add(el["id"])
        name = safe_name(el["id"])
        cls = "el-" + name
        uss_rules.append(("." + cls, build_uss_props(el, parent, losses, asset_dir)))
        kids = sorted(children.get(el["id"], []), key=sort_key)
        text = el.get("text")
        pad = INDENT * depth
        # 垫层(硬阴影 / OUTSIDE 描边环)排在本体**之前**:UI Toolkit 无 z-index,
        # 先出现的兄弟画在下面。几何是相对本体的,所以挂在本体的父级里、用绝对定位。
        for suffix, props in underlays(el):
            ucls = "%s-%s" % (cls, suffix)
            uss_rules.append(("." + ucls, _rebase(props, el, parent)))
            uxml_lines.append('%s<ui:VisualElement name="%s-%s" class="%s" />'
                              % (pad, name, suffix, ucls))
        if el.get("paths"):
            # 矢量:交给 runtime/FigVector.cs 用 Painter2D 真画(不产任何图片资产)
            tag = "figkit:FigVector"
            attrs = ('name="%s" class="%s" view-box="%s" paths="%s"'
                     % (name, cls, xml_escape(el.get("viewBox") or ""),
                        xml_escape(encode_paths(el["paths"]))))
        else:
            tag = "ui:Label" if text else "ui:VisualElement"
            attrs = 'name="%s" class="%s"' % (name, cls)
        if text and not el.get("paths"):
            attrs += ' text="%s"' % xml_escape(text.get("content", ""))
        if kids:
            uxml_lines.append('%s<%s %s>' % (pad, tag, attrs))
            for _, kid in kids:
                emit(kid, el, depth + 1)
            uxml_lines.append('%s</%s>' % (pad, tag))
        else:
            uxml_lines.append('%s<%s %s />' % (pad, tag, attrs))

    for _, el in sorted(roots, key=sort_key):
        emit(el, None, 2)

    # 兜底:parent 成环等异常导致没走到的元素,平挂帧根下(几何仍按其 parent 记录换算)
    for el in els:
        if el["id"] not in visited:
            sys.stderr.write("[ui_to_unity] 警告: 元素 %s 的 parent 链异常,平挂帧根\n" % el["id"])
            emit(el, rec_by_id.get(el.get("parent") or ""), 2)

    # ── UXML ──
    frame = cap.get("frame", "?")
    uxml = []
    uxml.append('<?xml version="1.0" encoding="utf-8"?>')
    uxml.append('<!-- %s.uxml — ui_to_unity.py 生成(源 frame %s,%sx%s)。' % (
        stem, frame, fmt_num(cap.get("w", 0)), fmt_num(cap.get("h", 0))))
    uxml.append('     name = figma id(\':\' 换 \'_\');兄弟顺序 = 绘制顺序(按 z 排,USS 无 z-index)。')
    uxml.append('     丢弃/降级项(known-loss)见同名 .uss 文件头注释。 -->')
    # figkit 命名空间 = runtime/FigVector.cs 所在的 C# namespace。**只在真有矢量时才声明**:
    # 声明了却没把 runtime 拷进工程,整份 UXML 会因为解析不出该类型而加载失败。
    ns = ' xmlns:figkit="Figkit"' if any(e.get("paths") for e in els) else ""
    uxml.append('<ui:UXML xmlns:ui="UnityEngine.UIElements"%s>' % ns)
    uxml.append('%s<ui:VisualElement name="screen-root" class="screen-root">' % INDENT)
    uxml.append('%s<Style src="%s.uss" />' % (INDENT * 2, stem))
    uxml.extend(uxml_lines)
    uxml.append('%s</ui:VisualElement>' % INDENT)
    uxml.append('</ui:UXML>')
    uxml_str = "\n".join(uxml) + "\n"

    # ── USS ──
    uss = []
    uss.append("/* %s.uss — ui_to_unity.py 生成(源 frame %s,%sx%s,确定性输出无时间戳)。" % (
        stem, frame, fmt_num(cap.get("w", 0)), fmt_num(cap.get("h", 0))))
    uss.append(" * 选择器 = .el-<name> 类(name 可能以数字开头,#id 选择器会非法)。")
    uss.append(" * known-loss —— 本文件相对 IR 丢弃/降级的项(诚实降级,勿静默):")
    if losses:
        for item in losses:
            uss.append(" *   - " + item.replace("*/", "* /"))
    else:
        uss.append(" *   - (无)")
    uss.append(" */")
    for selector, props in uss_rules:
        uss.append("")
        uss.append(selector + " {")
        for k, v in props:
            uss.append("%s%s: %s;" % (INDENT, k, v))
        uss.append("}")
    uss_str = "\n".join(uss) + "\n"

    return uxml_str, uss_str, losses


def convert_file(in_path, outdir):
    """读 .ui.json、写 <stem>.uxml/<stem>.uss(UTF-8 无 BOM、\\n 换行)。返回 (uxml路径, uss路径)。"""
    stem = os.path.basename(in_path)
    for suf in (".ui.json", ".json"):
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
            break
    with open(in_path, "r", encoding="utf-8") as f:
        cap = json.load(f)
    guard_or_die(cap, sys, in_path)   # 畸形 IR → 说清哪儿不对再退,别抛 traceback
    uxml_str, uss_str, _ = convert(cap, stem, outdir)
    os.makedirs(outdir, exist_ok=True)
    uxml_path = os.path.join(outdir, stem + ".uxml")
    uss_path = os.path.join(outdir, stem + ".uss")
    with open(uxml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(uxml_str)
    with open(uss_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(uss_str)
    return uxml_path, uss_path


IR_SPEC_SUPPORTED = '1.3'

# 本后端**认识**的 els 字段。少于输入文件里实际出现的键 = 有东西被静默跳过。
IR_FIELDS_KNOWN = frozenset((
    'id', 'name', 'type', 'parent', 'x', 'y', 'w', 'h', 'z', 'rot', 'opacity',
    'radius', 'border', 'shadow', 'blur', 'fill', 'img', 'imgSize',
    'clip', 'paths', 'viewBox', 'borderAlign', 'vec', 'text',
))


def spec_warnings(cap, supported, known):
    """IR 版本闸门。**只比大版本是不够的** —— 冻结纪律说小版本是"只增字段",

    于是 1.0 的编译器读 1.2 的文件照样放行,新字段被当不认识的键跳过,不报错不吭声:
    v1.2 的 paths/clip/borderAlign 就是这么在四个后端里集体消失的,而所有测试全绿。
    现在小版本落后也要说话,并且**把真正出现在数据里的陌生键逐个点名** ——
    "我按旧规矩读的"必须是一句听得见的话。
    """
    out = []
    got = str(cap.get('spec') or supported)             # 缺失 = 冻结前的老产物
    gmaj, smaj = got.split('.')[0], supported.split('.')[0]
    if gmaj != smaj:
        # 前缀是**给机器看的 ASCII 标记**:测试拿中文当判据会在管道里栽 ——
        # 子进程按 cp936 写中文、父进程按 utf-8 解,整句乱码,断言静默失配(踩过)。
        out.append('[major] 输入声称 IR v%s,本后端按 v%s 实现 —— 主版本不同,'
                   '新语义会被按旧规矩解释' % (got, supported))
    seen = set()
    for e in (cap.get('els') or []):
        if isinstance(e, dict):
            seen.update(e.keys())
    unknown = sorted(seen - set(known))
    if unknown:
        out.append('[unknown-fields] %s | 输入(IR v%s)里有本后端不认识的字段,**会被静默跳过** ——'
                   '本后端按 v%s 实现,该字段要么去实现、要么在 mapping.md 的 known-loss 表里表态'
                   % (', '.join(unknown), got, supported))
    return out



def check_ir(cap):
    """输入 .ui.json 的守门:→ (errors, warnings)。errors 非空 = 别往下跑。

    为什么每个后端各带一份而不抽公共模块:skill 文件夹必须自足、可单独安装
    (CONTRIBUTING「Conventions」),跨目录 import 会在装成插件时直接断。
    重复由 tools/conformance 的"各后端必须一致地拒绝同一批畸形 IR"兜住。
    """
    errors, warns = [], []
    if not isinstance(cap, dict):
        return ['.ui.json 顶层不是对象(读到 %s)' % type(cap).__name__], warns

    warns.extend(spec_warnings(cap, IR_SPEC_SUPPORTED, IR_FIELDS_KNOWN))

    els = cap.get('els')
    if not isinstance(els, list):
        errors.append("缺 'els' 数组(它是 IR 的主体,见 spec/ui.json-schema.md)")
        return errors, warns
    for k in ('w', 'h'):
        if not isinstance(cap.get(k), (int, float)):
            errors.append("顶层 '%s' 不是数字(读到 %r)" % (k, cap.get(k)))

    ids = set()
    for i, e in enumerate(els):
        if not isinstance(e, dict):
            errors.append('els[%d] 不是对象' % i)
            continue
        eid = e.get('id')
        if not isinstance(eid, str) or not eid:
            errors.append('els[%d] 缺 id(元素靠 figma node id 与 flow.json 对账)' % i)
            continue
        if eid in ids:
            errors.append('els[%d] 的 id %r 重复' % (i, eid))
        ids.add(eid)
        for k in ('x', 'y', 'w', 'h'):
            if not isinstance(e.get(k), (int, float)):
                errors.append('元素 %s 的 %r 不是数字(读到 %r)' % (eid, k, e.get(k)))
    for e in els:
        if isinstance(e, dict):
            p = e.get('parent') or ''
            if p and p not in ids:
                errors.append('元素 %s 的 parent %r 不在本屏内' % (e.get('id'), p))
    return errors, warns


def guard_or_die(cap, sys_mod, src=''):
    """守门 + 打印 + 退出码。errors → 写 stderr 并 SystemExit(2)。"""
    errors, warns = check_ir(cap)
    for w in warns:
        sys_mod.stderr.write('[ir-spec] %s\n' % w)
    if errors:
        sys_mod.stderr.write('[ir-check] %s 不是合法的 .ui.json:\n' % (src or '输入'))
        for e in errors[:20]:
            sys_mod.stderr.write('  - %s\n' % e)
        if len(errors) > 20:
            sys_mod.stderr.write('  ...(还有 %d 条)\n' % (len(errors) - 20))
        raise SystemExit(2)


def bake_motion(flow_path, outdir, sys_mod):
    """flow.json → outdir/motion.json(转场缓动的采样曲线表)。

    **为什么是采样点而不是 USS 的缓动关键字**:figma 给的是一条具体曲线,USS 的
    `ease-in-out` 之流给的是另一套同名不同形的曲线 —— 各家各挑"最像的",同一份 IR
    在六个引擎里就是六种手感,而所有测试照样绿。采样点没有这个自由度,
    tools/conformance 还会拿它跟别家逐点对账。UI Toolkit 侧可直接喂 AnimationCurve。

    2026-07-29 起 `FlowBinder.cs` **真在读**(Unity 6 里读成 AnimationCurve,取值与 python /
    Godot 三方一致到 6 位小数);曲线怎么贴到画面上见 references/mapping.md。
    """
    try:
        with open(flow_path, "r", encoding="utf-8") as f:
            flow = json.load(f)
    except Exception as e:                                       # noqa: BLE001
        sys_mod.stderr.write("[motion] 读不了 %s: %s\n" % (flow_path, e))
        return None
    data, notes = motion.bake_flow(flow, "figma2unity/scripts/ui_to_unity.py")
    out = os.path.join(outdir, "motion.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    for n in notes:
        sys_mod.stderr.write("[known-loss] motion: " + n + "\n")
    if data["curves"]:
        sys_mod.stderr.write("[motion] 烘出 %d 条曲线 —— 把本文件拖成 FlowBinder 的 motionJson\n"
                             % len(data["curves"]))
    return out


def main(argv):
    if len(argv) not in (3, 4):
        sys.stderr.write("用法: python3 ui_to_unity.py <cap.ui.json> <outdir> [flow.json]\n"
                         "  给了 flow.json 就顺带烘 motion.json(转场缓动的采样曲线)\n")
        return 2
    in_path, outdir = argv[1], argv[2]
    if not os.path.isfile(in_path):
        sys.stderr.write("[ui_to_unity] 输入文件不存在: %s\n" % in_path)
        return 1
    try:
        uxml_path, uss_path = convert_file(in_path, outdir)
    except (ValueError, json.JSONDecodeError) as e:
        sys.stderr.write("[ui_to_unity] 转换失败: %s\n" % e)
        return 1
    if len(argv) == 4:
        bake_motion(argv[3], outdir, sys)
    print("OK %s + %s" % (uxml_path, uss_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

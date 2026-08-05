#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ui_to_tscn.py — figma2html 全保真 .ui.json → Godot 4 文本场景(.tscn, format=3)

用法:
    python3 ui_to_tscn.py <cap.ui.json> <outdir>
产出:
    <outdir>/<stem>.tscn    (stem = 输入文件名去掉 .ui.json / .json 后缀)

设计:
- 纯标准库、argv 驱动、确定性:同输入必产同字节输出(golden 测试逐字节比对),
  统一 LF 换行、UTF-8 无 BOM。
- 几何:照 figma2html/runtime/render.js pass2 —— IR 里元素几何是"相对帧的绝对 px",
  嵌套时转父相对;这里写成 anchors 全 0(左上,默认值不落盘)+ offset_left/top/right/bottom。
- 同级顺序 = 按 z 排序(Godot Control 绘制顺序 = 树序,对应 CSS 同级 z-index)。
- IR→Godot 映射全表与 known-loss 清单见 ../references/mapping.md。
"""
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

# tscn 节点名不允许的字符(. : @ / " %)→ 统一换下划线;figma id "1:40" → 节点名 "1_40"
_FORBID = re.compile(r'[.:@/"%]')
# **sub_resource 的 id 规矩比节点名严得多**:Godot 只收 [A-Za-z0-9_](core/io/resource.cpp
# set_scene_unique_id:"The scene unique ID must contain only letters, numbers, and underscores")。
# 节点名那套黑名单漏掉的字符里,**分号是真会撞上的那个** —— figma 组件实例的 id 形如
# `I25:4109;206:12513;202:12604`(实例链用 ; 连接),换完冒号仍带 ;,于是 StyleBoxFlat /
# Gradient 全部注册失败,那些元素在引擎里**一律裸奔无样式**。
# 合成夹具撞不出来:手搓节点树里的 id 都是干净的 "1:40",没有组件实例。
_FORBID_ID = re.compile(r'[^A-Za-z0-9_]')

ALIGN = {  # CSS flex 对齐 → Godot 对齐枚举(0=BEGIN 1=CENTER 2=END)
    'flex-start': 0, 'left': 0, 'start': 0,
    'center': 1,
    'flex-end': 2, 'right': 2, 'end': 2,
}


def node_name(s):
    return _FORBID.sub('_', s)


def sub_id(s):
    """sub_resource 的 scene unique id。比 node_name 严:白名单,不是黑名单。"""
    return _FORBID_ID.sub('_', s)


def esc(s):
    """tscn 双引号字符串转义:反斜杠/引号/换行/制表。"""
    return (s.replace('\\', '\\\\').replace('"', '\\"')
             .replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r'))


def fnum(v, nd=3):
    """float 属性(offset/rotation):整数值写成 Godot 风格 "260.0"。"""
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return '%d.0' % round(f)
    s = ('%.' + str(nd) + 'f') % f
    s = s.rstrip('0')
    if s.endswith('.'):
        s += '0'
    return s


def cnum(v):
    """Color/Vector2 分量:整数裸写(1 不写 1.0),小数保留 4 位有效。"""
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    s = '%.4f' % f
    s = s.rstrip('0')
    if s.endswith('.'):
        s += '0'
    return s


def parse_rgba(s):
    """'rgba(255,255,255,0.2)' / 'rgb(1,2,3)' → (r,g,b,a) 0..1;解析失败 None。"""
    if not s:
        return None
    m = re.match(r'\s*rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*'
                 r'(?:,\s*([0-9.eE+-]+)\s*)?\)\s*$', s)
    if not m:
        return None
    r, g, b = (float(m.group(i)) / 255.0 for i in (1, 2, 3))
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return (r, g, b, a)


def color_str(c):
    return 'Color(%s, %s, %s, %s)' % tuple(cnum(x) for x in c)


def parse_radius(s, w=0, h=0):
    """CSS border-radius 简写('45px' / 'a b c d' / '50%')→ (TL, TR, BR, BL) 四角 int。

    百分比不是边角料:capture 对**每个 figma ELLIPSE** 都产 `radius: "50%"`
    (见 figma_capture.py 的 ELLIPSE 分支),头像/圆点/徽章/胶囊按钮全走这条。
    早先 float('50%') 抛 ValueError → 返回 None → 圆角整个丢掉、椭圆渲染成方块,
    而且不打日志。口径:百分比取 min(w,h) 的比例(Godot 的
    corner_radius 是标量,非正方形元素上是近似,已记在 mapping.md known-loss)。"""
    if not s:
        return None
    base = min(w, h) if (w and h) else 0
    vals = []
    for tok in s.split():
        try:
            if tok.endswith('%'):
                vals.append(base * float(tok[:-1]) / 100.0)
            else:
                vals.append(float(tok.replace('px', '')))
        except ValueError:
            return None
    if not vals:
        return None
    if len(vals) == 1:
        tl = tr = br = bl = vals[0]
    elif len(vals) == 2:
        tl = br = vals[0]; tr = bl = vals[1]
    elif len(vals) == 3:
        tl = vals[0]; tr = bl = vals[1]; br = vals[2]
    else:
        tl, tr, br, bl = vals[:4]
    return tuple(int(round(v)) for v in (tl, tr, br, bl))


def parse_border(s):
    """'2.0px solid rgba(...)' → (width:int, color);失败 None。"""
    if not s:
        return None
    m = re.match(r'\s*([0-9.]+)px\s+\w+\s+(rgba?\([^)]*\))', s)
    if not m:
        return None
    c = parse_rgba(m.group(2))
    if c is None:
        return None
    return (max(1, int(round(float(m.group(1))))), c)


def parse_shadow(s):
    """CSS box-shadow 'ox oy blur [spread] color' → (ox, oy, size:int, color)。
    inset 不支持(known-loss)。Godot StyleBoxFlat 的 shadow_size 是外扩像素,
    近似取 blur+spread、最小 1(blur=0 的硬阴影在 Godot 里 size=0 不绘制)。"""
    if not s or 'inset' in s:
        return None
    m = re.match(r'\s*(-?[0-9.]+)px\s+(-?[0-9.]+)px\s+(-?[0-9.]+)px'
                 r'(?:\s+(-?[0-9.]+)px)?\s+(rgba?\([^)]*\))', s)
    if not m:
        return None
    c = parse_rgba(m.group(5))
    if c is None:
        return None
    ox, oy = float(m.group(1)), float(m.group(2))
    blur = float(m.group(3))
    spread = float(m.group(4)) if m.group(4) is not None else 0.0
    size = max(1, int(round(blur + spread)))
    return (ox, oy, size, c)


def _split_top(s):
    """按顶层逗号切分(括号内逗号不切)。"""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(''.join(cur).strip()); cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append(''.join(cur).strip())
    return parts


_KW_ANGLE = {'to top': 0.0, 'to right': 90.0, 'to bottom': 180.0, 'to left': 270.0,
             'to top right': 45.0, 'to right top': 45.0,
             'to bottom right': 135.0, 'to right bottom': 135.0,
             'to bottom left': 225.0, 'to left bottom': 225.0,
             'to top left': 315.0, 'to left top': 315.0}


def _parse_stops(parts):
    """['rgba(..) 0%', 'rgba(..)'] → [(offset0..1, color)];色标缺位置按 CSS 规则插值。"""
    stops = []
    for p in parts:
        m = re.match(r'\s*(rgba?\([^)]*\))\s*(-?[0-9.]+)?%?\s*$', p)
        if not m:
            continue
        c = parse_rgba(m.group(1))
        if c is None:
            continue
        pos = float(m.group(2)) / 100.0 if m.group(2) is not None else None
        stops.append([pos, c])
    if len(stops) < 2:
        return None
    if stops[0][0] is None:
        stops[0][0] = 0.0
    if stops[-1][0] is None:
        stops[-1][0] = 1.0
    i = 0
    while i < len(stops):        # 内部缺位置的段:在已知邻居间线性插值
        if stops[i][0] is None:
            j = i
            while stops[j][0] is None:
                j += 1
            lo, hi = stops[i - 1][0], stops[j][0]
            n = j - i + 1
            for k in range(i, j):
                stops[k][0] = lo + (hi - lo) * (k - i + 1) / n
            i = j
        i += 1
    return [(round(p, 4), c) for p, c in stops]


def parse_linear_gradient(s):
    """'linear-gradient(90deg, rgba(..) 0%, rgba(..) 100%)' → (angle_deg, stops)。"""
    lo, hi = s.find('('), s.rfind(')')
    if lo < 0 or hi <= lo:
        return None
    parts = _split_top(s[lo + 1:hi])
    if not parts:
        return None
    angle = 180.0                 # CSS 缺省 to bottom
    m = re.match(r'\s*(-?[0-9.]+)deg\s*$', parts[0])
    if m:
        angle = float(m.group(1)); parts = parts[1:]
    elif parts[0].strip() in _KW_ANGLE:
        angle = _KW_ANGLE[parts[0].strip()]; parts = parts[1:]
    stops = _parse_stops(parts)
    if stops is None:
        return None
    return (angle, stops)


def parse_radial_gradient(s):
    """'radial-gradient(rgba(..) 0%, rgba(..) 100%)' → stops;不是径向就 None。

    捕获层对 figma 的 GRADIENT_RADIAL 只写色标(handle 位置没带出来),所以这里按
    **CSS 的缺省**理解:`ellipse at center`,终止形状取 `farthest-corner`。
    """
    if not s.startswith('radial-gradient'):
        return None
    lo, hi = s.find('('), s.rfind(')')
    if lo < 0 or hi <= lo:
        return None
    return _parse_stops(_split_top(s[lo + 1:hi]))


def gradient_uv(angle_deg):
    """CSS 角度(0=向上,90=向右)→ GradientTexture2D 的 fill_from/fill_to(UV)。"""
    rad = math.radians(angle_deg % 360.0)
    dx, dy = math.sin(rad), -math.cos(rad)
    f = (round(0.5 - dx / 2, 4) + 0.0, round(0.5 - dy / 2, 4) + 0.0)  # +0.0 消 -0.0
    t = (round(0.5 + dx / 2, 4) + 0.0, round(0.5 + dy / 2, 4) + 0.0)
    return f, t


def fallback_avg_color(fill):
    """radial/conic 等不支持的渐变 → 色标平均色(known-loss,见 mapping.md)。"""
    lo, hi = fill.find('('), fill.rfind(')')
    if lo < 0 or hi <= lo:
        return None
    stops = _parse_stops([p for p in _split_top(fill[lo + 1:hi])])
    if not stops:
        return None
    n = len(stops)
    return tuple(round(sum(c[i] for _, c in stops) / n, 4) for i in range(4))


class Emitter(object):
    """收集 ext_resource / sub_resource / node 三段,最后拼 tscn 文本。"""

    def __init__(self, res_prefix='res://scenes'):
        self.exts = []          # (id, path)
        self.ext_by_path = {}
        self.subs = []          # 每项 = 一个 sub_resource 文本块
        self.nodes = []         # 每项 = 一个 node 文本块
        self.svgs = {}          # v1.2 矢量:相对 outdir 的文件名 -> svg 文本
        self.res_prefix = res_prefix.rstrip('/')

    def add_svg(self, rel, text):
        """收下一份 .svg(由 main 落盘),返回它的 res:// 路径。"""
        self.svgs[rel] = text
        return self.add_ext('%s/%s' % (self.res_prefix, rel.replace('\\', '/')))

    def add_font(self, rel):
        """设计字体(.ttf)→ ext_resource id。路径**固定在 `res://fonts/`**,不跟 `res_prefix` 走。

        svg 是转换器自己产的、落在 outdir,所以跟 res_prefix;字体不是 —— 它是集成方
        放进工程的资源,路径必须稳定。跟着 res_prefix 会把**输出目录名**写进 res:// 路径
        (golden 用临时目录一跑就现形:`res://tmpvf57e9rc/fonts/...`),换个输出目录产物就变。
        Godot 4 会自己给 .ttf 生成 `.import`(FontFile);文件不在时导入期报缺资源 ——
        那正是要的,比静默退回系统字体强。
        """
        return self.add_ext('res://fonts/%s' % os.path.basename(rel.replace('\\', '/')))

    def add_ext(self, path):
        if path in self.ext_by_path:
            return self.ext_by_path[path]
        eid = 'tex_%d' % (len(self.exts) + 1)
        self.exts.append((eid, path))
        self.ext_by_path[path] = eid
        return eid

    def add_sub(self, block):
        self.subs.append(block)

    def add_node(self, lines):
        self.nodes.append('\n'.join(lines))

    def text(self):
        total = len(self.exts) + len(self.subs)
        if total:
            head = '[gd_scene load_steps=%d format=3]' % (total + 1)
        else:
            head = '[gd_scene format=3]'
        blocks = [head]
        for eid, path in self.exts:
            kind = 'FontFile' if str(path).lower().endswith(('.ttf', '.otf')) else 'Texture2D'
            blocks.append('[ext_resource type="%s" path="%s" id="%s"]' % (kind, esc(path), eid))
        blocks.extend(self.subs)
        blocks.extend(self.nodes)
        return '\n\n'.join(blocks) + '\n'


_RING = re.compile(r'\s*0(?:px)?\s+0(?:px)?\s+0(?:px)?\s+([0-9.]+)px\s+(rgba?\([^)]*\))\s*$')


def split_ring(shadow, align):
    """v1.2:把「描边环」从 shadow 串里拆出来 → (ring | None, 剩下的 shadow 串)。

    capture 对 OUTSIDE/CENTER 描边的做法是往 shadow 头部塞一条 `0 0 0 Npx <色>`
    (CSS 里 box-shadow 跟随 border-radius,outline 不跟)。它**不是阴影**,
    照阴影画会得到一圈模糊光晕;`borderAlign` 就是用来区分这两者的判据。
    零值那三段 CSS 允许不带单位,所以 `px` 在这里是可选的 —— 别只认一种写法。
    """
    if not shadow or align not in ('outside', 'center'):
        return None, shadow
    parts = _split_top(shadow)
    m = _RING.match(parts[0]) if parts else None
    if not m:
        return None, shadow
    c = parse_rgba(m.group(2))
    if c is None:
        return None, shadow
    return (float(m.group(1)), c), ', '.join(parts[1:])


def _stylebox(sid, e, fill_c):
    """Panel 用 StyleBoxFlat:填充/圆角(四角)/描边/阴影(Godot 原生支持,别丢)。"""
    L = ['[sub_resource type="StyleBoxFlat" id="%s"]' % sid]
    if fill_c is not None:
        L.append('bg_color = ' + color_str(fill_c))
    elif e.get('clip') and (e.get('radius') or ''):
        # 圆角裁剪容器:它**必须画出实心形状**才能当 clip_children 的模子。
        # 颜色无所谓 —— CLIP_CHILDREN_ONLY 下它自己不显形,只贡献形状。
        # 若沿用下面那条 draw_center=false,模子是空的,子节点会被裁得一干二净。
        L.append('bg_color = Color(1, 1, 1, 1)')
    else:
        L.append('bg_color = Color(0, 0, 0, 0)')
        L.append('draw_center = false')
    rad = parse_radius(e.get('radius') or '', e.get('w') or 0, e.get('h') or 0)
    if rad and any(rad):
        for key, v in zip(('top_left', 'top_right', 'bottom_right', 'bottom_left'), rad):
            L.append('corner_radius_%s = %d' % (key, v))
    align = (e.get('borderAlign') or '').lower()
    ring, rest = split_ring(e.get('shadow') or '', align)
    bd = parse_border(e.get('border') or '')
    if bd or ring:
        # **Godot 的 border 只往内画**(与 CSS 同病)。往外的那半靠 expand_margin:
        # 它把 StyleBox 的绘制范围整体外扩,扩出来的那圈正好由 border 占掉,
        # 原来的填充区一寸不让 —— 这才是 OUTSIDE;CENTER 则外扩一半。
        out = ring[0] if ring else 0.0
        w = (bd[0] if bd else 0) + int(round(out))
        c = bd[1] if bd else ring[1]
        for key in ('left', 'top', 'right', 'bottom'):
            L.append('border_width_%s = %d' % (key, max(1, w)))
        L.append('border_color = ' + color_str(c))
        if out:
            for key in ('left', 'top', 'right', 'bottom'):
                L.append('expand_margin_%s = %s' % (key, cnum(out)))
    sh = parse_shadow(rest)
    if sh and not is_hard_shadow(rest):
        ox, oy, size, c = sh
        L.append('shadow_color = ' + color_str(c))
        L.append('shadow_size = %d' % size)
        if ox or oy:
            L.append('shadow_offset = Vector2(%s, %s)' % (cnum(ox), cnum(oy)))
    return '\n'.join(L)


def is_hard_shadow(shadow):
    """blur=0 且有位移 = **硬阴影**(这套设计里到处都是:`2px 6px 0px rgba(0,0,0,1)`)。

    StyleBoxFlat 的 `shadow_size` 是「往外扩多少像素」,不是「位移一个实心副本」:
    硬阴影按它画,size 会被 `max(1, blur+spread)` 夹成 1,于是一圈 1px 的边 ——
    设计稿上那块厚实的投影就没了。硬阴影的忠实画法是**在下面垫一个同形状的实心副本**,
    见 _shadow_panel。
    """
    sh = parse_shadow(shadow)
    if not sh:
        return False
    ox, oy, _size, _c = sh
    return ('0px ' in shadow or ' 0 ' in shadow) and (ox or oy) and _blur_of(shadow) == 0


def _blur_of(shadow):
    m = re.match(r'\s*(-?[0-9.]+)px\s+(-?[0-9.]+)px\s+(-?[0-9.]+)px', shadow or '')
    return float(m.group(3)) if m else None


# CSS 的 `farthest-corner`:终止椭圆过最远的那个角。中心在 (0.5,0.5) 的 UV 里,
# 那个角的距离是 √2/2;GradientTexture2D 的径向填充在 UV 里是**正圆**,贴到非正方形
# 元素上被拉成椭圆 —— 正好就是 CSS 缺省的 `ellipse` 形状,不用另外补偿。
_FARTHEST_CORNER_UV = 0.7071


def _gradient_subs(name, angle, stops, radial=False):
    gid, tid = 'grad_' + sub_id(name), 'gt_' + sub_id(name)
    offs = ', '.join(cnum(p) for p, _ in stops)
    cols = ', '.join(', '.join(cnum(x) for x in c) for _, c in stops)
    g = ['[sub_resource type="Gradient" id="%s"]' % gid,
         'offsets = PackedFloat32Array(%s)' % offs,
         'colors = PackedColorArray(%s)' % cols]
    if radial:
        f = (0.5, 0.5)
        t = (0.5 + _FARTHEST_CORNER_UV, 0.5)
    else:
        f, t = gradient_uv(angle)
    gt = ['[sub_resource type="GradientTexture2D" id="%s"]' % tid,
          'gradient = SubResource("%s")' % gid]
    if radial:
        gt.append('fill = 1')                 # GradientTexture2D.FILL_RADIAL
    gt += ['fill_from = Vector2(%s, %s)' % (cnum(f[0]), cnum(f[1])),
           'fill_to = Vector2(%s, %s)' % (cnum(t[0]), cnum(t[1]))]
    return '\n'.join(g), '\n'.join(gt), tid


def _xml_esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


def svg_fill_attr(css):
    """CSS 颜色 → SVG 的 fill 属性串。

    **SVG 1.1 的 `fill` 不认 `rgba()`** —— 那是 CSS Color 4。Godot 的 SVG 解析器
    (ThorVG)解不动就退回默认值**黑色**:实机第一次跑出来整屏矢量全黑,就是这个。
    合法写法是 `fill="#rrggbb" fill-opacity="a"`,两段分开给。
    """
    c = parse_rgba(css or '')
    if c is None:
        return 'fill="%s"' % _xml_esc(css or 'none')      # 解不动就原样交出去,别悄悄改成黑
    r, g, b, a = c
    out = 'fill="#%02x%02x%02x"' % (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))
    if a < 0.999:
        out += ' fill-opacity="%s"' % cnum(a)
    return out


def radius_axes(s, w, h):
    """CSS border-radius → 四角**各自的** `(rx, ry)`;解析不动返回 None。

    与 `parse_radius` 的分工:那个把四角折成**标量**喂 StyleBoxFlat,这个保留两轴。
    CSS 说百分比是**逐轴**算的(水平按 w、垂直按 h),所以非正方形上的 `50%` 是
    **椭圆角**,折成 `min(w,h)` 就成了胶囊 —— 面板底部那道 2143×680 的横扫,
    胶囊比椭圆低了 38px,一眼能看出来。

    末尾按 CSS Backgrounds §5.5 等比收缩:同一条边上两角之和超过边长时,
    **四角按同一个比例**一起缩(不是各夹各的)。
    """
    if not s:
        return None
    toks = s.split()
    if len(toks) == 1:
        toks = toks * 4
    elif len(toks) == 2:
        toks = [toks[0], toks[1], toks[0], toks[1]]
    elif len(toks) == 3:
        toks = [toks[0], toks[1], toks[2], toks[1]]
    else:
        toks = toks[:4]
    cs = []
    for tok in toks:
        try:
            if tok.endswith('%'):
                p = float(tok[:-1]) / 100.0
                cs.append([w * p, h * p])
            else:
                v = float(tok.replace('px', ''))
                cs.append([v, v])
        except ValueError:
            return None
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = cs
    f = 1.0
    for total, edge in ((tlx + trx, w), (blx + brx, w), (tly + bly, h), (try_ + bry, h)):
        if total > 0 and edge > 0:
            f = min(f, edge / float(total))
    if f < 1.0:
        cs = [[rx * f, ry * f] for rx, ry in cs]
    return tuple((rx, ry) for rx, ry in cs)


def elliptical_corners(e):
    """这个元素是不是「StyleBoxFlat 画不出来」的椭圆角 → 四角 (rx,ry);不是就 None。

    Godot 的 `corner_radius_*` 是**标量**,画不了 rx≠ry。这类元素改走 .svg
    (与 v1.2 矢量同一条路:编译期吐 svg、导入期由 ThorVG 栅格化),
    而不是把它折成胶囊了事。

    只接**纯实色填充**的:带渐变/图片/文字/描边/阴影/裁剪的还得靠 StyleBoxFlat
    或纹理那几条路,那些仍按原样走并照旧记 known-loss。
    """
    if e.get('paths') or e.get('text') or e.get('img') or e.get('clip'):
        return None
    if e.get('border') or e.get('shadow'):
        return None
    fill = e.get('fill') or ''
    if not fill or '-gradient(' in fill:
        return None
    cs = radius_axes(e.get('radius') or '', e.get('w') or 0, e.get('h') or 0)
    if not cs or all(abs(rx - ry) < 0.5 for rx, ry in cs):
        return None
    return cs


def rounded_rect_d(w, h, corners):
    """四角各带 (rx,ry) 的圆角矩形 → SVG path 的 `d`。四角顺序 TL/TR/BR/BL,与 CSS 一致。"""
    (tlx, tly), (trx, try_), (brx, bry), (blx, bly) = corners
    n = cnum
    return ('M %s,0 H %s A %s %s 0 0 1 %s,%s V %s A %s %s 0 0 1 %s,%s '
            'H %s A %s %s 0 0 1 0,%s V %s A %s %s 0 0 1 %s,0 Z' % (
                n(tlx), n(w - trx), n(trx), n(try_), n(w), n(try_),
                n(h - bry), n(brx), n(bry), n(w - brx), n(h),
                n(blx), n(blx), n(bly), n(h - bly), n(tly), n(tlx), n(tly), n(tlx)))


def svg_shape_doc(e, corners):
    """椭圆角实色块 → 一份独立 .svg(同 svg_doc 的写法,只是形状是我们自己算的)。"""
    w, h = float(e.get('w') or 1), float(e.get('h') or 1)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.2f %.2f" '
            'width="%.2f" height="%.2f"><path d="%s" %s/></svg>\n'
            % (max(w, 1.0), max(h, 1.0), max(w, 1.0), max(h, 1.0),
               _xml_esc(rounded_rect_d(w, h, corners)), svg_fill_attr(e.get('fill'))))


def svg_doc(e):
    """IR 的 paths → 一份独立 .svg 文本(v1.2)。

    **为什么是 svg 文件而不是三角化成 Polygon2D。** Godot 没有原生的 SVG path 节点,
    自己把贝塞尔采样+耳切三角化,既要重写 winding rule(NONZERO/EVENODD)又要处理
    多子路径与洞,还得跟 html 侧逐像素对齐 —— 而 Godot **自带 SVG 导入**(ThorVG),
    这些它全都已经做了。编译期吐 .svg、导入期由引擎栅格化:
    确定性(同输入同字节)、可读、可版本控制、**不下载任何位图**。

    与 figma_capture.svg_markup / render.js 的 buildSvg 是同一套写法,改一处必同步另两处。
    差异只有一处**有意**:这里是独立文档,要 xmlns 与 width/height,不是内联片段。
    """
    vb = e.get('viewBox') or ('0 0 %.1f %.1f' % (e.get('w') or 1, e.get('h') or 1))
    v = [float(x) for x in vb.split()]
    uid = _FORBID_ID.sub('_', str(e.get('id', '')))
    ps = e.get('paths') or []
    shape = ' '.join(q['d'] for q in ps if not q.get('clip'))   # 填充形状 = 描边的裁剪依据
    need = {q.get('clip') for q in ps} - {'', None}
    defs = ''
    if 'inside' in need:
        defs += '<clipPath id="cin_%s"><path d="%s"/></clipPath>' % (uid, _xml_esc(shape))
    if 'outside' in need:
        # 「形状之外」用蒙版:整面涂白 → 可见,形状涂黑 → 挖掉
        defs += ('<mask id="cout_%s"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#fff"/>'
                 '<path d="%s" fill="#000"/></mask>'
                 % (uid, v[0] - 64, v[1] - 64, v[2] + 128, v[3] + 128, _xml_esc(shape)))
    body = ''
    for q in ps:
        att = ''
        if q.get('clip') == 'inside':
            att = ' clip-path="url(#cin_%s)"' % uid
        elif q.get('clip') == 'outside':
            att = ' mask="url(#cout_%s)"' % uid
        body += '<path d="%s" %s fill-rule="%s"%s/>' % (
            _xml_esc(q['d']), svg_fill_attr(q.get('fill')), q['rule'], att)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s" width="%.2f" height="%.2f">'
            '%s%s</svg>\n' % (vb, max(v[2], 1.0), max(v[3], 1.0),
                              ('<defs>%s</defs>' % defs) if defs else '', body))


def _classify(e):
    if e.get('paths'):
        return 'VectorRect'               # v1.2:矢量按路径画,编译期落成 .svg
    if elliptical_corners(e):
        return 'ShapeRect'                # 椭圆角实色块:corner_radius 是标量,画不出来
    if e.get('text'):
        return 'Label'
    if e.get('img'):
        return 'TextureRect'
    fill = e.get('fill') or ''
    if fill.startswith('linear-gradient'):
        return 'GradientRect'
    if fill.startswith('radial-gradient') and parse_radial_gradient(fill):
        return 'RadialRect'           # GradientTexture2D 的 FILL_RADIAL,不再取平均色
    if '-gradient(' in fill:
        return 'FallbackPanel'        # conic 等仍是平均色回退
    if fill or e.get('border') or e.get('shadow'):
        return 'Panel'
    return 'Control'                  # 无任何可见样式的容器(空 Panel 会画默认灰皮)


_STRETCH = {'cover': 6, 'contain': 5}  # KEEP_ASPECT_COVERED / KEEP_ASPECT_CENTERED


def pick_rounded_clips(els, kids):
    """哪些「圆角裁剪」容器可以用 clip_children —— **每条链上最外层的那个**。

    Godot 的 clip_children **不支持嵌套**:一条祖先链上只能有一个,多了里外都坏。
    所以嵌套时必须挑一个,问题只是挑哪头。

    挑**最外层**:外层裁的是这块 UI 压在背景上的**外轮廓**,圆角丢了就是四个方角
    直接怼在底色上,一眼就看见(实测:邮件面板 1008×1614 的 80px 圆角退成矩形剪刀,
    底部两个角变成硬直角)。内层裁的多半是纹理/渐变/装饰,而且它们本来就压在
    一块同色的不透明父容器里 —— 退成矩形剪刀只是圆角处多出一点点同色方角,基本看不出。
    换句话说:**外层的圆角是轮廓,内层的圆角是细节**,只能留一个就留轮廓。

    (曾经挑最内层。那版之所以看着"外层不能用",是因为外层这类只负责裁的容器在 IR 里
     没有填充、被判成不画东西的 Control —— 空模子会把子节点裁得一干二净,整条头栏消失。
     真正的毛病是模子空,不是"外层不行";_stylebox 补上实心底之后外层就正常了。)
    """
    by = {e['id']: e for e in els}

    def rounded(i):
        e = by.get(i) or {}
        return bool(e.get('clip')) and bool((e.get('radius') or '').strip())

    def has_rounded_ancestor(i):
        p = (by.get(i) or {}).get('parent') or ''
        while p in by:
            if rounded(p):
                return True
            p = by[p].get('parent') or ''
        return False

    del kids                    # 现在只看祖先链,子树不参与判定
    return {e['id'] for e in els
            if rounded(e['id']) and not has_rounded_ancestor(e['id'])}


def _emit_el(em, e, parent_path, parent_rec, used, rounded_clips=frozenset()):
    name = node_name(e.get('id', ''))
    while name in used:                # 消毒后撞名兜底(极罕见)
        name += '_'
    used.add(name)

    px = parent_rec['x'] if parent_rec else 0
    py = parent_rec['y'] if parent_rec else 0
    left = e.get('x', 0) - px
    top = e.get('y', 0) - py
    w, h = e.get('w', 0), e.get('h', 0)

    kind = _classify(e)
    # 圆角裁剪的容器必须**自己画得出那个圆角形状**,才能拿它当子节点的模子(clip_children)。
    # 这类容器在 IR 里通常没有填充(它只负责裁),`_classify` 会把它判成不画东西的 Control。
    clip_rad = (parse_radius(e.get('radius') or '', w, h)
                if (e.get('clip') and e.get('id') in rounded_clips) else None)
    if clip_rad and any(clip_rad) and kind == 'Control':
        kind = 'Panel'
    gtype = {'Label': 'Label', 'TextureRect': 'TextureRect', 'GradientRect': 'TextureRect',
             'VectorRect': 'TextureRect', 'ShapeRect': 'TextureRect',
             'RadialRect': 'TextureRect',
             'Panel': 'Panel', 'FallbackPanel': 'Panel', 'Control': 'Control'}[kind]

    # **硬阴影垫一层实心副本**:CSS 的 `2px 6px 0px` 是把整个形状按位移复制一份填成阴影色,
    # 而 StyleBoxFlat 的 shadow_size 只是往外扩边。垫层排在本体之前 = 画在下面。
    hard = parse_shadow(split_ring(e.get('shadow') or '', (e.get('borderAlign') or '').lower())[1])
    if hard and is_hard_shadow(split_ring(e.get('shadow') or '',
                                          (e.get('borderAlign') or '').lower())[1]):
        ox, oy, _s, col = hard
        sid = 'sh_' + sub_id(name)
        rad = parse_radius(e.get('radius') or '', w, h)
        blk = ['[sub_resource type="StyleBoxFlat" id="%s"]' % sid, 'bg_color = ' + color_str(col)]
        if rad and any(rad):
            for key, v in zip(('top_left', 'top_right', 'bottom_right', 'bottom_left'), rad):
                blk.append('corner_radius_%s = %d' % (key, v))
        em.add_sub('\n'.join(blk))
        em.add_node(['[node name="%s_shadow" type="Panel" parent="%s"]' % (name, parent_path or '.'),
                     'offset_left = ' + fnum(left + ox), 'offset_top = ' + fnum(top + oy),
                     'offset_right = ' + fnum(left + ox + w), 'offset_bottom = ' + fnum(top + oy + h),
                     'mouse_filter = 2',
                     'theme_override_styles/panel = SubResource("%s")' % sid])

    L = ['[node name="%s" type="%s" parent="%s"]' % (name, gtype, parent_path or '.')]
    L.append('offset_left = ' + fnum(left))
    L.append('offset_top = ' + fnum(top))
    L.append('offset_right = ' + fnum(left + w))
    L.append('offset_bottom = ' + fnum(top + h))
    rot = e.get('rot') or 0
    if rot:
        L.append('rotation = ' + fnum(math.radians(rot), 6))          # 弧度
        L.append('pivot_offset = Vector2(%s, %s)' % (cnum(w / 2.0), cnum(h / 2.0)))  # 绕中心,对齐 CSS transform-origin:center
    op = e.get('opacity', 1)
    if op != 1:
        L.append('modulate = Color(1, 1, 1, %s)' % cnum(op))          # 连带子节点,对齐 CSS opacity
    if e.get('clip'):
        if clip_rad and any(clip_rad):
            # **圆角裁剪不能用 clip_contents** —— 那是个矩形剪刀,不认 corner_radius。
            # Godot 的正解是 CanvasItem.clip_children:拿本节点**画出来的形状**当子节点的
            # 蒙版。所以把这类容器变成一个画着圆角 StyleBoxFlat 的 Panel:
            #   1 = CLIP_CHILDREN_ONLY(自己不显形,只当模子);2 = 连自己一起画。
            # 不这么做的后果实测两处:道具卡的品质渐变裁成方块;按钮里 275×170 的纹理
            # 只被裁到矩形边,胶囊左边露出一块方形点阵。
            L.append('clip_children = %d' % (2 if (e.get('fill') or e.get('img')) else 1))
        else:
            L.append('clip_contents = true')                          # v1.1:figma isMask / clipsContent

    if kind == 'Label':
        t = e.get('text') or {}
        content = t.get('content', '')
        L.append('text = "%s"' % esc(content))
        if t.get('wrap') or '\n' in content:
            L.append('autowrap_mode = 3')                             # WORD_SMART,对齐 CSS pre-wrap
            L.append('clip_text = false')
        ah = ALIGN.get(t.get('alignH') or t.get('textAlign') or '', 0)
        if ah:
            L.append('horizontal_alignment = %d' % ah)
        av = ALIGN.get(t.get('alignV') or '', 0)
        if av:
            L.append('vertical_alignment = %d' % av)
        col = parse_rgba(t.get('color') or '')
        if col:
            L.append('theme_override_colors/font_color = ' + color_str(col))
        stroke = t.get('stroke') or ''
        sm = re.match(r'\s*([0-9.]+)px\s+(rgba?\([^)]*\))', stroke)
        if sm and parse_rgba(sm.group(2)):
            L.append('theme_override_colors/font_outline_color = ' + color_str(parse_rgba(sm.group(2))))
            # webkit-text-stroke 骑线(内外各半)+ paint-order:stroke → 可见≈外侧一半
            L.append('theme_override_constants/outline_size = %d' % max(1, int(round(float(sm.group(1)) / 2))))
        lh, size = t.get('lh') or 0, t.get('size') or 0
        if lh and size:
            L.append('theme_override_constants/line_spacing = %d' % int(round(lh - size)))
        if size:
            L.append('theme_override_font_sizes/font_size = %d' % int(round(size)))
        # 设计字体:四端共用同一份子集,否则各端各拿系统默认字体,连**换行位置**都对不上,
        # 逐像素比出来的差异全是字形噪声。Godot 没有"合成粗体"这回事 ——
        # 字重只能靠**两个字面文件**,所以按 weight 选 Bold/Regular。
        face = 'Bold' if (t.get('weight') or 400) >= 600 else 'Regular'
        L.append('theme_override_fonts/font = ExtResource("%s")'
                 % em.add_font('fonts/FigCJK-%s.ttf' % face))
    elif kind == 'ShapeRect':
        eid = em.add_svg('%s.svg' % sub_id(name), svg_shape_doc(e, elliptical_corners(e)))
        L.append('texture = ExtResource("%s")' % eid)
        L.append('expand_mode = 1')                                   # IGNORE_SIZE:贴满节点矩形
        L.append('stretch_mode = 0')                                  # SCALE:非等比拉满
    elif kind == 'VectorRect':
        eid = em.add_svg('%s.svg' % sub_id(name), svg_doc(e))
        L.append('texture = ExtResource("%s")' % eid)
        L.append('expand_mode = 1')                                   # IGNORE_SIZE:贴满节点矩形
        L.append('stretch_mode = 0')                                  # SCALE:非等比拉满,对齐 preserveAspectRatio="none"
    elif kind == 'TextureRect':
        eid = em.add_ext('res://' + e['img'])
        L.append('texture = ExtResource("%s")' % eid)
        L.append('expand_mode = 1')                                   # IGNORE_SIZE:贴满节点矩形
        L.append('stretch_mode = %d' % _STRETCH.get(e.get('imgSize') or 'cover', 0))
    elif kind == 'RadialRect':
        gb, tb, tid = _gradient_subs(name, 0, parse_radial_gradient(e['fill']), radial=True)
        em.add_sub(gb)
        em.add_sub(tb)
        L.append('texture = SubResource("%s")' % tid)
        L.append('expand_mode = 1')
    elif kind == 'GradientRect':
        g = parse_linear_gradient(e['fill'])
        if g is not None:
            gb, tb, tid = _gradient_subs(name, g[0], g[1])
            em.add_sub(gb)
            em.add_sub(tb)
            L.append('texture = SubResource("%s")' % tid)
            L.append('expand_mode = 1')
        else:                                                          # 解析不动→平均色回退
            avg = fallback_avg_color(e['fill'])
            L[0] = L[0].replace('type="TextureRect"', 'type="Panel"')
            sid = 'sb_' + sub_id(name)
            em.add_sub(_stylebox(sid, e, avg))
            L.append('theme_override_styles/panel = SubResource("%s")' % sid)
    elif kind == 'FallbackPanel':
        avg = fallback_avg_color(e.get('fill') or '')
        sid = 'sb_' + sub_id(name)
        em.add_sub(_stylebox(sid, e, avg))
        L.append('theme_override_styles/panel = SubResource("%s")' % sid)
    elif kind == 'Panel':
        sid = 'sb_' + sub_id(name)
        em.add_sub(_stylebox(sid, e, parse_rgba(e.get('fill') or '')))
        L.append('theme_override_styles/panel = SubResource("%s")' % sid)

    em.add_node(L)
    return name


def collect_losses(cap):
    """扫一遍 IR,列出本后端**表达不了或降级**的项 → ["<元素id>: 说明", ...]。

    仓库原则(README「Honest degradation」/ CONTRIBUTING #4):不能表达的特性必须既进
    mapping.md 的 known-loss 表,又在**生成时或运行时留痕**,不许静默丢失。
    figma2unity 是把清单写进 .uss 头注释;.tscn 这边不塞注释(没有引擎可验证 Godot 的
    文本资源解析器怎么吃它,弄坏场景比丢个模糊更糟),改为生成时写 stderr。

    与 mapping.md 的 known-loss 表一一对应,tools/conformance 会核对两边不脱节。"""
    els = cap.get('els') or []
    rec = {e['id']: e for e in els}
    kids = {}
    for i, e in enumerate(els):
        pp = e.get('parent') or ''
        if pp and pp in rec:
            kids.setdefault(pp, []).append((e.get('z', 0), i, e))
    rounded_ok = pick_rounded_clips(els, kids)

    out = []
    for e in els:
        eid = e.get('id', '?')
        if e.get('blur'):
            out.append("%s: blur '%s' 丢弃(Godot 无逐控件模糊;需要的话自建 "
                       "BackBufferCopy + 着色器)" % (eid, e['blur']))
        if e.get('shadow'):
            out.append("%s: 阴影用 shadow_size 近似 CSS 的 blur+spread(且最小 1,"
                       "Godot size=0 不绘制,硬阴影会消失)" % eid)
        fill = e.get('fill') or ''
        if '-gradient(' in fill and not fill.startswith(('linear-gradient', 'radial-gradient')):
            out.append("%s: 这种渐变(conic 等)降级为色标平均色" % eid)
        elif fill.startswith('radial-gradient') and not parse_radial_gradient(fill):
            out.append("%s: 径向渐变的色标解析不动,降级为色标平均色" % eid)
        if e.get('clip') and (e.get('radius') or '') and e.get('id') not in rounded_ok:
            out.append("%s: 圆角裁剪退回矩形 —— 祖先链上已经有一个圆角裁剪,而 Godot 的 "
                       "clip_children 不能嵌套;外层留给轮廓(丢了就是方角怼底色),"
                       "这一层只裁矩形,圆角处会露出同色方角" % eid)
        rad = e.get('radius') or ''
        if '%' in rad and e.get('w') != e.get('h') and not elliptical_corners(e):
            # 纯实色的椭圆角已经改走 .svg 画真椭圆(见 elliptical_corners);
            # 还会落到这里的,是带渐变/图片/描边/阴影/裁剪的那些 —— 它们仍靠
            # StyleBoxFlat 或纹理,标量 corner_radius 只能折成胶囊。
            out.append("%s: 百分比圆角在非正方形元素上取 min(w,h) 近似"
                       "(带渐变/描边/裁剪,画不成 .svg;Godot corner_radius 是标量)" % eid)
    bg = (cap.get('stageBg') or '')
    if '-gradient(' in bg and not bg.startswith(('linear-gradient', 'radial-gradient')):
        out.append("stageBg: 这种渐变(conic 等)降级为色标平均色")
    return out


def convert(cap, stem, res_prefix='res://scenes'):
    """cap → tscn 文本。**矢量的 .svg 会被丢弃** —— 只要文本时用它。"""
    return convert_all(cap, stem, res_prefix)[0]


def convert_all(cap, stem, res_prefix='res://scenes'):
    """cap(.ui.json dict)→ (tscn 文本, {svg 文件名: svg 文本})。stem = 场景/根节点名。

    res_prefix = .tscn 所在目录的 res:// 路径;矢量的 .svg 与场景同目录,
    ext_resource 按 `<res_prefix>/<name>.svg` 引用。
    """
    els = cap.get('els') or []
    rec = {e['id']: e for e in els}
    kids, roots = {}, []
    for i, e in enumerate(els):
        p = e.get('parent') or ''
        if p and p in rec:
            kids.setdefault(p, []).append((e.get('z', 0), i, e))
        else:
            roots.append((e.get('z', 0), i, e))       # 父不在集合内(子树抽取)→ 当根
    for lst in kids.values():
        lst.sort(key=lambda t: (t[0], t[1]))          # 同级按 z(平局按原序)= 绘制序
    roots.sort(key=lambda t: (t[0], t[1]))

    em = Emitter(res_prefix)
    w, h = cap.get('w', 1080), cap.get('h', 1920)
    root_name = node_name(stem)
    em.add_node(['[node name="%s" type="Control"]' % root_name,
                 'offset_right = ' + fnum(w),
                 'offset_bottom = ' + fnum(h)])

    used = {'StageBg'}
    bg = (cap.get('stageBg') or '').strip()
    if bg:
        _emit_stage_bg(em, bg, w, h)

    rounded_clips = pick_rounded_clips(els, kids)

    def walk(entry, parent_path, parent_rec, sib_used):
        e = entry[2]
        name = _emit_el(em, e, parent_path, parent_rec, sib_used, rounded_clips)
        child_path = (parent_path + '/' + name) if parent_path else name
        cu = set()
        for c in kids.get(e['id'], []):
            walk(c, child_path, e, cu)

    for r in roots:
        walk(r, '', None, used)
    return em.text(), em.svgs


def _emit_stage_bg(em, bg, w, h):
    """帧底(stageBg):纯色→ColorRect;url(...)→TextureRect(cover);线性渐变→渐变贴图。"""
    geo = ['offset_right = ' + fnum(w), 'offset_bottom = ' + fnum(h), 'mouse_filter = 2']
    if bg.startswith('url('):
        m = re.match(r'url\(([^)]+)\)', bg)
        path = m.group(1).strip('\'" ') if m else ''
        if path:
            eid = em.add_ext('res://' + path)
            em.add_node(['[node name="StageBg" type="TextureRect" parent="."]'] + geo +
                        ['texture = ExtResource("%s")' % eid,
                         'expand_mode = 1', 'stretch_mode = 6'])
        return
    if bg.startswith('linear-gradient'):
        g = parse_linear_gradient(bg)
        if g is not None:
            gb, tb, tid = _gradient_subs('StageBg', g[0], g[1])
            em.add_sub(gb)
            em.add_sub(tb)
            em.add_node(['[node name="StageBg" type="TextureRect" parent="."]'] + geo +
                        ['texture = SubResource("%s")' % tid, 'expand_mode = 1'])
            return
    if bg.startswith('radial-gradient'):
        stops = parse_radial_gradient(bg)
        if stops:
            gb, tb, tid = _gradient_subs('StageBg', 0, stops, radial=True)
            em.add_sub(gb)
            em.add_sub(tb)
            em.add_node(['[node name="StageBg" type="TextureRect" parent="."]'] + geo +
                        ['texture = SubResource("%s")' % tid, 'expand_mode = 1'])
            return
    c = parse_rgba(bg)
    if c is None and '-gradient(' in bg:
        c = fallback_avg_color(bg)
    if c is not None:
        em.add_node(['[node name="StageBg" type="ColorRect" parent="."]'] + geo +
                    ['color = ' + color_str(c)])


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

    **为什么是采样点而不是引擎的缓动枚举**:figma 给的是一条具体曲线,`Tween.EASE_*`
    给的是另一套同名不同形的曲线 —— 各家各挑"最像的枚举",同一份 IR 在六个引擎里就是
    六种手感,而所有测试照样绿。采样点没有这个自由度,tools/conformance 还会逐点对账。

    2026-07-29 起 `flow_binder.gd` **真在播**(Godot 4.3 实机截图核过中途帧),
    本文件只负责烘,曲线怎么贴到画面上见 references/mapping.md。
    """
    try:
        with open(flow_path, 'r', encoding='utf-8') as f:
            flow = json.load(f)
    except Exception as e:                                       # noqa: BLE001
        sys_mod.stderr.write('[motion] 读不了 %s: %s\n' % (flow_path, e))
        return None
    data, notes = motion.bake_flow(flow, 'figma2godot/scripts/ui_to_tscn.py')
    out = os.path.join(outdir, 'motion.json')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    for n in notes:
        sys_mod.stderr.write('[known-loss] motion: ' + n + '\n')
    if data['curves']:
        sys_mod.stderr.write('[motion] 烘出 %d 条曲线 —— 与 .tscn 放在一起,'
                             'flow_binder.gd 的 motion_path 默认就读它\n'
                             % len(data['curves']))
    return out


def res_prefix_for(outdir, sys_mod):
    """outdir 的 `res://` 路径 —— 往上找 project.godot 得到工程根,再取相对路径。

    找不到工程根(比如编到临时目录里)不是错:退回 `res://<outdir 目录名>`
    并**说一声**,让人知道这个前缀是猜的、拷进工程时要对一眼。
    """
    d = os.path.abspath(outdir)
    cur = d
    while True:
        if os.path.exists(os.path.join(cur, 'project.godot')):
            rel = os.path.relpath(d, cur).replace('\\', '/')
            return 'res://' if rel == '.' else 'res://' + rel
        up = os.path.dirname(cur)
        if up == cur:
            break
        cur = up
    guess = 'res://' + os.path.basename(d.rstrip('/\\'))
    sys_mod.stderr.write('[vector] 往上没找到 project.godot,矢量 .svg 的 res:// 前缀'
                         '按目录名猜成 %s —— 拷进工程后核一眼\n' % guess)
    return guess


def main(argv):
    if len(argv) not in (3, 4):
        sys.stderr.write('用法: python3 ui_to_tscn.py <cap.ui.json> <outdir> [flow.json]\n'
                         '  给了 flow.json 就顺带烘 motion.json(转场缓动的采样曲线)\n')
        return 2
    src, outdir = argv[1], argv[2]
    with open(src, 'r', encoding='utf-8') as f:
        cap = json.load(f)
    guard_or_die(cap, sys, src)          # 畸形 IR → 说清哪儿不对再退,别抛 traceback
    base = os.path.basename(src)
    if base.endswith('.ui.json'):
        stem = base[:-len('.ui.json')]
    else:
        stem = os.path.splitext(base)[0]
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, stem + '.tscn')
    text, svgs = convert_all(cap, stem, res_prefix_for(outdir, sys))
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    for rel, doc in sorted(svgs.items()):     # v1.2 矢量:与场景同目录的 .svg
        with open(os.path.join(outdir, rel), 'w', encoding='utf-8', newline='\n') as f:
            f.write(doc)
    if svgs:
        sys.stderr.write('[vector] 画出 %d 个矢量为 .svg(Godot 导入期栅格化,'
                         '**没有下载任何位图**)\n' % len(svgs))
    for line in collect_losses(cap):          # 诚实降级:丢什么必须说,不许静默
        sys.stderr.write('[known-loss] ' + line + '\n')
    if len(argv) == 4:
        bake_motion(argv[3], outdir, sys)
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))

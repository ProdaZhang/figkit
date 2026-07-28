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

# tscn 节点名不允许的字符(. : @ / " %)→ 统一换下划线;figma id "1:40" → 节点名 "1_40"
_FORBID = re.compile(r'[.:@/"%]')

ALIGN = {  # CSS flex 对齐 → Godot 对齐枚举(0=BEGIN 1=CENTER 2=END)
    'flex-start': 0, 'left': 0, 'start': 0,
    'center': 1,
    'flex-end': 2, 'right': 2, 'end': 2,
}


def node_name(s):
    return _FORBID.sub('_', s)


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
    而且不打日志。口径与 figma2unreal 对齐:百分比取 min(w,h) 的比例(Godot 的
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

    def __init__(self):
        self.exts = []          # (id, path)
        self.ext_by_path = {}
        self.subs = []          # 每项 = 一个 sub_resource 文本块
        self.nodes = []         # 每项 = 一个 node 文本块

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
            blocks.append('[ext_resource type="Texture2D" path="%s" id="%s"]' % (esc(path), eid))
        blocks.extend(self.subs)
        blocks.extend(self.nodes)
        return '\n\n'.join(blocks) + '\n'


def _stylebox(sid, e, fill_c):
    """Panel 用 StyleBoxFlat:填充/圆角(四角)/描边/阴影(Godot 原生支持,别丢)。"""
    L = ['[sub_resource type="StyleBoxFlat" id="%s"]' % sid]
    if fill_c is not None:
        L.append('bg_color = ' + color_str(fill_c))
    else:
        L.append('bg_color = Color(0, 0, 0, 0)')
        L.append('draw_center = false')
    rad = parse_radius(e.get('radius') or '', e.get('w') or 0, e.get('h') or 0)
    if rad and any(rad):
        for key, v in zip(('top_left', 'top_right', 'bottom_right', 'bottom_left'), rad):
            L.append('corner_radius_%s = %d' % (key, v))
    bd = parse_border(e.get('border') or '')
    if bd:
        w, c = bd
        for key in ('left', 'top', 'right', 'bottom'):
            L.append('border_width_%s = %d' % (key, w))
        L.append('border_color = ' + color_str(c))
    sh = parse_shadow(e.get('shadow') or '')
    if sh:
        ox, oy, size, c = sh
        L.append('shadow_color = ' + color_str(c))
        L.append('shadow_size = %d' % size)
        if ox or oy:
            L.append('shadow_offset = Vector2(%s, %s)' % (cnum(ox), cnum(oy)))
    return '\n'.join(L)


def _gradient_subs(name, angle, stops):
    gid, tid = 'grad_' + name, 'gt_' + name
    offs = ', '.join(cnum(p) for p, _ in stops)
    cols = ', '.join(', '.join(cnum(x) for x in c) for _, c in stops)
    g = ['[sub_resource type="Gradient" id="%s"]' % gid,
         'offsets = PackedFloat32Array(%s)' % offs,
         'colors = PackedColorArray(%s)' % cols]
    f, t = gradient_uv(angle)
    gt = ['[sub_resource type="GradientTexture2D" id="%s"]' % tid,
          'gradient = SubResource("%s")' % gid,
          'fill_from = Vector2(%s, %s)' % (cnum(f[0]), cnum(f[1])),
          'fill_to = Vector2(%s, %s)' % (cnum(t[0]), cnum(t[1]))]
    return '\n'.join(g), '\n'.join(gt), tid


def _classify(e):
    if e.get('text'):
        return 'Label'
    if e.get('img'):
        return 'TextureRect'
    fill = e.get('fill') or ''
    if fill.startswith('linear-gradient'):
        return 'GradientRect'
    if '-gradient(' in fill:
        return 'FallbackPanel'        # radial/conic → 平均色回退
    if fill or e.get('border') or e.get('shadow'):
        return 'Panel'
    return 'Control'                  # 无任何可见样式的容器(空 Panel 会画默认灰皮)


_STRETCH = {'cover': 6, 'contain': 5}  # KEEP_ASPECT_COVERED / KEEP_ASPECT_CENTERED


def _emit_el(em, e, parent_path, parent_rec, used):
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
    gtype = {'Label': 'Label', 'TextureRect': 'TextureRect', 'GradientRect': 'TextureRect',
             'Panel': 'Panel', 'FallbackPanel': 'Panel', 'Control': 'Control'}[kind]

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

    if kind == 'Label':
        t = e.get('text') or {}
        content = t.get('content', '')
        L.append('text = "%s"' % esc(content))
        if '\n' in content:
            L.append('autowrap_mode = 3')                             # 多行→WORD_SMART,对齐 pre-wrap
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
    elif kind == 'TextureRect':
        eid = em.add_ext('res://' + e['img'])
        L.append('texture = ExtResource("%s")' % eid)
        L.append('expand_mode = 1')                                   # IGNORE_SIZE:贴满节点矩形
        L.append('stretch_mode = %d' % _STRETCH.get(e.get('imgSize') or 'cover', 0))
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
            sid = 'sb_' + name
            em.add_sub(_stylebox(sid, e, avg))
            L.append('theme_override_styles/panel = SubResource("%s")' % sid)
    elif kind == 'FallbackPanel':
        avg = fallback_avg_color(e.get('fill') or '')
        sid = 'sb_' + name
        em.add_sub(_stylebox(sid, e, avg))
        L.append('theme_override_styles/panel = SubResource("%s")' % sid)
    elif kind == 'Panel':
        sid = 'sb_' + name
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
    out = []
    for e in cap.get('els') or []:
        eid = e.get('id', '?')
        if e.get('blur'):
            out.append("%s: blur '%s' 丢弃(Godot 无逐控件模糊;需要的话自建 "
                       "BackBufferCopy + 着色器)" % (eid, e['blur']))
        if e.get('shadow'):
            out.append("%s: 阴影用 shadow_size 近似 CSS 的 blur+spread(且最小 1,"
                       "Godot size=0 不绘制,硬阴影会消失)" % eid)
        fill = e.get('fill') or ''
        if fill.startswith('radial-gradient'):
            out.append("%s: 径向渐变降级为色标平均色(Godot GradientTexture1D 只做线性)" % eid)
        rad = e.get('radius') or ''
        if '%' in rad and e.get('w') != e.get('h'):
            out.append("%s: 百分比圆角在非正方形元素上取 min(w,h) 近似"
                       "(Godot corner_radius 是标量,画不出椭圆角)" % eid)
    bg = (cap.get('stageBg') or '')
    if bg.startswith('radial-gradient'):
        out.append("stageBg: 径向渐变降级为色标平均色(同上)")
    return out


def convert(cap, stem):
    """cap(.ui.json dict)→ tscn 文本(str)。stem = 场景/根节点名。"""
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

    em = Emitter()
    w, h = cap.get('w', 1080), cap.get('h', 1920)
    root_name = node_name(stem)
    em.add_node(['[node name="%s" type="Control"]' % root_name,
                 'offset_right = ' + fnum(w),
                 'offset_bottom = ' + fnum(h)])

    used = {'StageBg'}
    bg = (cap.get('stageBg') or '').strip()
    if bg:
        _emit_stage_bg(em, bg, w, h)

    def walk(entry, parent_path, parent_rec, sib_used):
        e = entry[2]
        name = _emit_el(em, e, parent_path, parent_rec, sib_used)
        child_path = (parent_path + '/' + name) if parent_path else name
        cu = set()
        for c in kids.get(e['id'], []):
            walk(c, child_path, e, cu)

    for r in roots:
        walk(r, '', None, used)
    return em.text()


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
    c = parse_rgba(bg)
    if c is None and '-gradient(' in bg:
        c = fallback_avg_color(bg)
    if c is not None:
        em.add_node(['[node name="StageBg" type="ColorRect" parent="."]'] + geo +
                    ['color = ' + color_str(c)])


IR_SPEC_SUPPORTED = '1.0'


def check_ir(cap):
    """输入 .ui.json 的守门:→ (errors, warnings)。errors 非空 = 别往下跑。

    为什么每个后端各带一份而不抽公共模块:skill 文件夹必须自足、可单独安装
    (CONTRIBUTING「Conventions」),跨目录 import 会在装成插件时直接断。
    重复由 tools/conformance 的"各后端必须一致地拒绝同一批畸形 IR"兜住。
    """
    errors, warns = [], []
    if not isinstance(cap, dict):
        return ['.ui.json 顶层不是对象(读到 %s)' % type(cap).__name__], warns

    got = str(cap.get('spec') or IR_SPEC_SUPPORTED)     # 缺失 = 冻结前的老产物
    if got.split('.')[0] != IR_SPEC_SUPPORTED.split('.')[0]:
        warns.append('输入声称 IR v%s,本后端按 v%s 实现 —— 主版本不同,'
                     '新语义会被按旧规矩解释' % (got, IR_SPEC_SUPPORTED))

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


def main(argv):
    if len(argv) != 3:
        sys.stderr.write('用法: python3 ui_to_tscn.py <cap.ui.json> <outdir>\n')
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
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(convert(cap, stem))
    for line in collect_losses(cap):          # 诚实降级:丢什么必须说,不许静默
        sys.stderr.write('[known-loss] ' + line + '\n')
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))

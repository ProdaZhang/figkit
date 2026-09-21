# -*- coding: utf-8 -*-
"""Figma 节点树 -> 全保真捕获(records)-> 两序列化器:.ui.json(渲染真源)+ .tree.html(静态预览)。

设计要点(全保真,不走 DSL):
- 保留每个可见节点,扁平绝对定位(相对帧原点),z 按文档序。不折叠容器/实例。
- 逐节点真样式:几何 / 旋转 / 不透明度 / 圆角 / 描边 / 阴影 / 模糊 /
  填充(纯色含透明度、线性/径向渐变、图片填充)/ 文字(字号/字重/行高/字距/对齐/字形描边)。
- 矢量簇(无文字、含 VECTOR/BOOLEAN/STAR/LINE/REGULAR_POLYGON)整簇折叠成一张透明 PNG,
  **按真实 AABB 放置**;PNG 缺失时回退**透明**(不平涂黑,杜绝"方块黑")。
- DSL(figma_to_dsl.py)是派生的语义视图,渲染**不依赖**它。

用法:
  python3 figma_capture.py <nodes.json> <frameId> <sNN> <assetDir> <assetRelPrefix> <out_basepath>
产物:
  <out_basepath>.ui.json   全保真节点记录(render.js / aigd 消费)
  <out_basepath>.tree.html 高保真静态预览(等价旧 tree.html)
"""
import sys, json, io, os, math, html, re, copy, hashlib

# 产物写进 .ui.json 顶层的 `spec` 字段 = 本次捕获遵循的 IR 契约版本(见 spec/)。
# 为什么要写:契约是 v1.0 FROZEN、只允许 additive,但产物里若不带版本,
# 将来 v1.1 的 capture 产物喂给旧后端时**两边都无从察觉** —— 消费者连"我看不懂这个"
# 都说不出口。带上之后,后端至少能在主版本对不上时告警(而不是静默按旧规矩解释)。
# 缺失该字段的旧产物一律按 "1.0" 处理,向后兼容。
IR_SPEC = '1.5'

VEC = {'VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'LINE', 'REGULAR_POLYGON'}


def col(c, opacity=1.0):
    a = round(c.get('a', 1) * opacity, 3)
    return 'rgba(%d,%d,%d,%s)' % (round(c['r'] * 255), round(c['g'] * 255), round(c['b'] * 255), a)


def solid(fills):
    for f in fills or []:
        if f.get('visible', True) and f.get('type') == 'SOLID':
            return col(f['color'], f.get('opacity', 1))
    return None


def solid_paint(paints):
    for f in paints or []:
        if f.get('visible', True) and f.get('type') == 'SOLID':
            return f
    return None


# figma 的画笔可以带**混合模式**,而 CSS 的 border/background 没有逐画笔的混合。
# 按钮那圈深边就是这么来的:黑色 30% + **OVERLAY**,压在按钮自己的填充上。
# 只读颜色和不透明度、按 NORMAL 合成的话会明显偏暗 —— 实测金色按钮
# 描边 figma 是 (255,189,0),按 NORMAL 算出来是 (178,142,0)。
# 背景色在捕获期是已知的(自己的填充 / 上一个铺满的兄弟 / 祖先),所以这里
# **把混合直接压平成一个不透明色** —— 精确,而且下游任何引擎都能直接用,
# 不需要它们各自实现混合模式。
_SEP_BLEND = {
    'NORMAL':      lambda b, s: s,
    'MULTIPLY':    lambda b, s: b * s,
    'SCREEN':      lambda b, s: 1 - (1 - b) * (1 - s),
    'DARKEN':      lambda b, s: min(b, s),
    'LIGHTEN':     lambda b, s: max(b, s),
    'OVERLAY':     lambda b, s: 2 * b * s if b < .5 else 1 - 2 * (1 - b) * (1 - s),
    'HARD_LIGHT':  lambda b, s: 2 * b * s if s < .5 else 1 - 2 * (1 - b) * (1 - s),
    'DIFFERENCE':  lambda b, s: abs(b - s),
    'EXCLUSION':   lambda b, s: b + s - 2 * b * s,
    # b==1 / s 的边界不是可有可无的修饰:金色按钮的 R 通道正是靠 COLOR_BURN 的
    # `b==1 → 1` 才保持 255 的,少了它整条边会连红色一起压暗。
    'COLOR_BURN':  lambda b, s: 1.0 if b >= 1 else (0.0 if s <= 0 else 1 - min(1, (1 - b) / s)),
    'COLOR_DODGE': lambda b, s: 0.0 if b <= 0 else (1.0 if s >= 1 else min(1, b / (1 - s))),
}


def paint_css(paint, backdrop, lost=None, nid='', name=''):
    """一个 SOLID 画笔 → CSS 颜色。带混合模式且知道背景色时,压平成不透明结果色。

    backdrop = (r,g,b) 0..1 或 None。不知道背景就没法压平 —— 那时**吭声**并退回
    NORMAL,别假装还原了。
    """
    c = paint['color']
    a = c.get('a', 1) * paint.get('opacity', 1)
    mode = (paint.get('blendMode') or 'NORMAL').upper()
    if mode in ('NORMAL', 'PASS_THROUGH'):
        return col(c, paint.get('opacity', 1))
    fn = _SEP_BLEND.get(mode)
    if fn is None or backdrop is None:
        if lost is not None:
            lost.append((nid, name, 'BLEND-' + mode))
        return col(c, paint.get('opacity', 1))
    src = (c['r'], c['g'], c['b'])
    out = tuple(max(0.0, min(1.0, (1 - a) * backdrop[i] + a * fn(backdrop[i], src[i])))
                for i in range(3))
    return 'rgba(%d,%d,%d,1.0)' % tuple(round(v * 255) for v in out)


def opaque_rgb(paints):
    """节点的不透明纯色填充 → (r,g,b) 0..1;不是不透明纯色就 None(不能当背景色用)。"""
    p = solid_paint(paints)
    if not p:
        return None
    if (p.get('blendMode') or 'NORMAL').upper() not in ('NORMAL', 'PASS_THROUGH'):
        return None
    if p['color'].get('a', 1) * p.get('opacity', 1) < 0.999:
        return None
    return (p['color']['r'], p['color']['g'], p['color']['b'])


def gradient_css(f):
    stops = f.get('gradientStops') or []
    cs = ', '.join('%s %.1f%%' % (col(s['color'], f.get('opacity', 1)), s['position'] * 100) for s in stops)
    h = f.get('gradientHandlePositions') or []
    if f['type'] == 'GRADIENT_RADIAL':
        return 'radial-gradient(%s)' % cs
    if len(h) >= 2:
        dx = h[1]['x'] - h[0]['x']; dy = h[1]['y'] - h[0]['y']
        ang = (math.degrees(math.atan2(dx, -dy))) % 360   # CSS:0deg=向上,y朝下
    else:
        ang = 180
    return 'linear-gradient(%.1fdeg, %s)' % (ang, cs)


def crop_css(f, w, h, lost=None, nid='', name=''):
    """figma 的 `scaleMode: STRETCH` 其实是**裁剪(crop)**模式,真正的几何在 `imageTransform`
    里:那是一个 2×3 矩阵,把**节点归一化坐标**映射到**图片归一化坐标** ——

        img_u = a·u + b·v + tx        img_v = c·u + d·v + ty

    于是图片自己占的那块节点区域是 u ∈ [-tx/a, (1-tx)/a]:宽 w/a、左边距 -tx/a·w。
    不读这个矩阵、一律按 `100% 100%` 拉满的话,小图标会被撑满整格 —— 实测一个
    35×45 的闪电图标(a=1.85 / d=1.44,设计上只占 33×43)被拉成 62×62,溢出它所在的价格药丸。

    带旋转/斜切(b 或 c 非 0)的裁剪,CSS 背景表达不了。那时**吭声**并退回拉满,
    别假装还原了 —— 猜错的图和对的图长得一样,只有量过才知道。
    """
    m = f.get('imageTransform')
    if not m or w <= 0 or h <= 0:
        return '100% 100%', ''
    (a, b, tx), (c, d, ty) = m[0], m[1]
    if abs(b) > 1e-6 or abs(c) > 1e-6:
        if lost is not None:
            lost.append((nid, name, 'IMG-CROP-SKEW'))
        return '100% 100%', ''
    if abs(a) < 1e-6 or abs(d) < 1e-6:
        return '100% 100%', ''
    iw, ih = w / a, h / d
    left, top = -tx / a * w, -ty / d * h
    if abs(iw - w) < 0.05 and abs(ih - h) < 0.05 and abs(left) < 0.05 and abs(top) < 0.05:
        return '100% 100%', ''          # 单位矩阵 = 就是拉满,别写一串等价的 px
    return '%.2fpx %.2fpx' % (iw, ih), '%.2fpx %.2fpx' % (left, top)


def img_fill(node, asset_dir, asset_rel, missing):
    for f in node.get('fills') or []:
        if f.get('visible', True) and f.get('type', '').startswith('IMAGE'):
            sm = f.get('scaleMode', 'FILL')
            size = {'FILL': 'cover', 'FIT': 'contain', 'STRETCH': '100% 100%', 'TILE': 'auto'}.get(sm, 'cover')
            pos = ''
            if sm == 'STRETCH':
                sz = node.get('size') or {}
                bb = node.get('absoluteBoundingBox') or {}
                size, pos = crop_css(f, sz.get('x', bb.get('width', 0)), sz.get('y', bb.get('height', 0)),
                                     missing, node['id'], node.get('name', ''))
            # 候选名:优先 <imageRef>.png(图片填充天然键,跨屏可复用、可直接喂 figma 导出),
            # 回退节点 id 名 n<id>.png(向后兼容旧素材)
            cands = []
            ref = f.get('imageRef')
            if ref:
                cands.append(ref + '.png')
            cands.append('n' + node['id'].replace(':', '_').replace(';', '__') + '.png')
            for fn in cands:
                if os.path.exists(os.path.join(asset_dir, fn)):
                    return '%s/%s' % (asset_rel, fn), size, pos
            missing.append((node['id'], node.get('name', ''), 'IMG'))
            return None, None, None
    return None, None, None


def vec_asset(node, asset_dir, asset_rel, missing):
    fn = 'n' + node['id'].replace(':', '_').replace(';', '__') + '.png'
    if os.path.exists(os.path.join(asset_dir, fn)):
        return '%s/%s' % (asset_rel, fn)
    missing.append((node['id'], node.get('name', ''), node.get('type')))
    return None


# 下面三个判断各自**重扫整棵子树**,而 emit 对每个节点都要问一遍 —— 看着就是 O(n·depth),
# 很像该加个缓存的地方。**加过,量过,退回来了**(2026-07-31):按节点身份记忆之后,
# 29524 节点的合成树上,无矢量簇时 0.100s→0.084s(1.19x),而**矢量簇密集时 0.010s→0.024s,
# 慢了 2.4 倍** —— 折叠一旦发生,emit 直接 return、根本不往下走,缓存于是只写不读,纯是开销。
# 而真实 figma 文件恰恰满是会折叠的图标簇。绝对量级也不支持:3280 节点约 9ms,不是"秒级"。
# 想再来一次的话,先量,别照着复杂度估。
def scan(n):
    """返回 (有文字, 有矢量, 有可直接绘制的矢量几何)。

    第三位是 2026-08-04 加的。figma REST 加 `geometry=paths` 之后会给出每个矢量的
    SVG 路径(fillGeometry / strokeGeometry),那意味着**这些东西根本不必是图片** ——
    可以照着路径画出来:不吃 /v1/images 的渲染配额(真会被打爆)、分辨率无关、
    改色不用重导,下游引擎拿到的也是路径而不是位图。
    有几何就别折叠成 PNG,让 emit 递归下去逐个画。"""
    ht = (n.get('type') == 'TEXT' and (n.get('characters', '') or '').strip() != '')
    hv = n.get('type') in VEC
    hg = bool(n.get('fillGeometry') or n.get('strokeGeometry'))
    for c in n.get('children') or []:
        a, b, g = scan(c); ht = ht or a; hv = hv or b; hg = hg or g
    return ht, hv, hg


def needs_image(n):
    """整簇折叠成一张图的条件:含真矢量、无文字、**且簇内没有能直接写出来的形状**。

    第三条是 2026-08-04 补的。此前只看前两条,于是一个 1012×1618 的邮件面板
    ——4 个带圆角的实色矩形 + 1 条线性渐变 + 几个椭圆,**零张图片填充**——
    只因角落里有几个矢量装饰,整块被烤成一张 PNG。产物于是退化成"截图 + 热区":
    改个颜色要重导素材、位置尺寸只能靠位图对齐(位图还带阴影外溢,天生错半格),
    下游 unity/godot/cocos 拿到的也全是位图 —— 而 figma 里它们本来就不是图。
    含可渲染形状就下沉递归,只有**纯矢量簇**才折叠;那才是真写不出来的东西。
    """
    ht, hv, hg = scan(n)
    return hv and not ht and not has_renderable_shape(n) and not hg


def has_renderable_shape(n):
    """簇内是否含可用 div 渲染的形状/文字(矩形/椭圆带可见填充、或文字)。
    有则缺图时值得展开(渲染这些形状),无则是纯矢量、保持折叠。"""
    if n.get('type') == 'TEXT':
        return True
    if n.get('type') not in VEC and n.get('type') not in ('GROUP', 'FRAME', 'COMPONENT', 'INSTANCE', 'SECTION'):
        if any(f.get('visible', True) for f in (n.get('fills') or [])):
            return True
    return any(has_renderable_shape(c) for c in (n.get('children') or []))


_PATH_TOK = re.compile(r'[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?')
_NARG = {'M': 2, 'L': 2, 'C': 6, 'Q': 4, 'Z': 0}


def _path_cmds(d):
    """SVG 路径串 → [(命令, [数值...])]。只认 figma 真会发的**绝对** M/L/C/Q/Z。

    认不出的命令(相对命令、圆弧 A、简写 S/T)一律返回 None —— 宁可让调用方
    退回保守路径,也不要按错的语义解释几何。
    """
    toks = _PATH_TOK.findall(d or '')
    out, i, cmd = [], 0, None
    while i < len(toks):
        if toks[i][0].isalpha():
            cmd = toks[i]
            if cmd not in _NARG:
                return None
            i += 1
            if cmd == 'Z':
                out.append(('Z', []))
                cmd = None
                continue
        if cmd is None or i + _NARG[cmd] > len(toks):
            return None
        out.append((cmd, [float(x) for x in toks[i:i + _NARG[cmd]]]))
        i += _NARG[cmd]
        if cmd == 'M':
            cmd = 'L'           # M 之后重复的数值组按 L 解释(SVG 规矩)
    return out


def _path_points(d):
    """路径上的**落点**(不含控制点)→ (xs, ys)。给校验与自测量范围用。"""
    xs, ys = [], []
    for _c, a in (_path_cmds(d) or []):
        if a:
            xs.append(a[-2]); ys.append(a[-1])
    return xs, ys


def _end(c):
    return (c[1][-2], c[1][-1])


def _bez(p0, c, t):
    """命令 c 从 p0 出发,在参数 t 处的点(L 取线性,C/Q 取真曲线)。"""
    if c[0] == 'C':
        a = c[1]
        p1, p2, p3 = (a[0], a[1]), (a[2], a[3]), (a[4], a[5])
        u = 1 - t
        return tuple(u ** 3 * p0[k] + 3 * u * u * t * p1[k] + 3 * u * t * t * p2[k] + t ** 3 * p3[k]
                     for k in (0, 1))
    if c[0] == 'Q':
        a = c[1]
        p1, p2 = (a[0], a[1]), (a[2], a[3])
        u = 1 - t
        return tuple(u * u * p0[k] + 2 * u * t * p1[k] + t * t * p2[k] for k in (0, 1))
    e = _end(c)
    return (p0[0] + (e[0] - p0[0]) * t, p0[1] + (e[1] - p0[1]) * t)


def _flatten(d, steps=8):
    """路径 → 折线轮廓 [[(x,y)...]],给点包含测试用。"""
    cmds = _path_cmds(d)
    if not cmds:
        return None
    contours, cur, p = [], [], (0.0, 0.0)
    for c in cmds:
        if c[0] == 'M':
            if len(cur) > 2:
                contours.append(cur)
            p = _end(c); cur = [p]
        elif c[0] == 'Z':
            if len(cur) > 2:
                contours.append(cur)
            cur = []
        else:
            for k in range(1, steps + 1):
                cur.append(_bez(p, c, k / float(steps)))
            p = _end(c)
    if len(cur) > 2:
        contours.append(cur)
    return contours or None


def _inside(pt, contours):
    """奇偶规则的射线法点包含测试。"""
    x, y = pt
    hit = False
    for ct in contours:
        for i in range(len(ct)):
            ax, ay = ct[i]
            bx, by = ct[(i + 1) % len(ct)]
            if (ay > y) != (by > y) and x < ax + (y - ay) / (by - ay) * (bx - ax):
                hit = not hit
    return hit


def _fmt_path(start, body):
    def num(v):
        return ('%.4f' % v).rstrip('0').rstrip('.') or '0'
    s = 'M%s %s' % (num(start[0]), num(start[1]))
    for c, a in body:
        s += c + ' '.join(num(v) for v in a)
    return s + 'Z'


def split_stroke_band(band_d, shape_d, weight, keep):
    """figma 的 ±w 预裁带 → 一条**能直接填的环**(看不懂就返回 None)。

    **为什么要在捕获层做**:原样发整条带子 + 一个 `clip:inside/outside` 提示,等于
    把布尔裁剪当成了后端的入场券 —— 拿得到 clipPath/mask 的(html、godot 的 svg)
    才裁得动,Unity 的 Painter2D 没有布尔裁剪,只能整条照画,描边粗一倍。

    带子的结构是恒定的:每条子路径包一段边,恒为 [中线起点 → 一侧偏移 → 该侧几何 →
    中线终点 → 另一侧偏移 → 另一侧几何 → 闭合],内外两条链命令数相同,正中间劈得开。

    **但劈完不能直接拿半条当形状**:半条的两端是中线上的点,闭合时那根直弦会
    横切拐角 —— 直边看不出来(弦正好压在中线上),圆角处就填出一整块扇形肉。
    正解是把各段的偏移链首尾接起来还原成一条**闭合的内缩/外扩轮廓**,
    再和原形状凑成两个轮廓、按 evenodd 填 —— 落在两者之间的那圈就是描边,
    既不用布尔裁剪,也没有弦。

    偏移链能首尾相接是因为相邻段在拐角处共用同一个偏移点。接不上、命令数不成对、
    跨到偏移侧那一步的长度对不上 w、或者两半都判在里/都判在外 —— 统统当作"不认识",
    返回 None 让调用方退回"原样 + clip 提示"的老路子。
    """
    cmds = _path_cmds(band_d)
    shape = _flatten(shape_d or '')
    if not cmds or not shape or weight <= 0:
        return None
    tol = max(weight * 0.25, 0.5)
    want = (keep == 'inside')
    subs, cur_start, body = [], None, []
    for c in cmds:
        if c[0] == 'M':
            if body:
                subs.append((cur_start, body))
            cur_start, body = _end(c), []
        elif c[0] == 'Z':
            if body:
                subs.append((cur_start, body))
            cur_start, body = None, []
        else:
            if cur_start is None:
                return None
            body.append(c)
    if body:
        subs.append((cur_start, body))
    chains = []             # [(要的那半是内侧吗, 贴着轮廓的那几条命令)]
    for start, body in subs:
        n = len(body)
        if n < 4:
            # 退化子路径(`M a L b L a Z` 这种零面积的薄片,figma 在极短线段/端点上会发)
            # 画出来本来就是空的,丢掉即可;别为它把整条带子判成"看不懂"。
            pts = [start] + [_end(c) for c in body]
            area = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] -
                           pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))))
            if area < 1e-3:
                continue
            return None
        if n % 2:
            return None
        mid = n // 2
        halves = ((start, body[:mid]), (_end(body[mid - 1]), body[mid:]))
        for s, half in halves:
            # 第一步是从中线跨到偏移侧:直边上正好 w,尖角的斜接会拉长到 √2·w 上下。
            # 放宽到 [0.5w, 2.5w] —— 真正兜底的是下面"偏移链首尾接得上、闭得拢"。
            step = math.dist(s, _end(half[0]))
            if not (weight * 0.5 <= step <= weight * 2.5 + tol):
                return None
        marks = []
        for _s, half in halves:
            p, pts = _end(half[0]), []
            for c in half[1:-1]:          # 掐掉两端的径向跳步,只留贴着轮廓的那几段
                pts.append(_bez(p, c, 0.5))
                p = _end(c)
            if not pts:
                return None
            marks.append(sum(1 for q in pts if _inside(q, shape)) * 2 > len(pts))
        if marks[0] == marks[1]:
            return None          # 两半判在同一侧 = 没看懂这条带子
        idx = 0 if marks[0] == want else 1
        chains.append((idx, halves[idx]))
    if not chains:
        return None
    # 偏移链接成一条闭合轮廓。内侧那半按子路径正序接;外侧那半在带子里是**倒着走**的
    # (从段末回到段首),所以要倒序接。
    order = list(chains) if chains[0][0] == 0 else list(reversed(chains))
    ring, pen = [], None
    for _idx, (_s, half) in order:
        head = _end(half[0])
        if pen is None:
            ring.append(('M', list(head)))
        elif math.dist(pen, head) > 0.05:
            return None                   # 接不上 = 这条带子不是"逐段包边"那种结构
        ring.extend(half[1:-1])
        pen = _end(half[-2])
    if pen is None or math.dist(pen, (ring[0][1][0], ring[0][1][1])) > 0.05:
        return None                       # 没闭合
    loop = _fmt_path((ring[0][1][0], ring[0][1][1]), ring[1:])
    return (shape_d + loop) if want else (loop + shape_d)


def vector_paths(node, lost, backdrop=None):
    """figma 的 fillGeometry / strokeGeometry → 可直接绘制的路径列表。

    要 REST 请求带上 `geometry=paths` 才有这两个字段(默认不给)。有了它,
    矢量就**不必再是图片**:照路径画即可 —— 不吃 /v1/images 的渲染配额、
    分辨率无关、改色不用重导素材,下游引擎拿到的是路径而不是位图。

    坐标系是节点自身的包围盒(左上角 0,0),所以配 viewBox="0 0 w h" 直接就位。
    strokeGeometry 是 figma 已经把描边**转成可填充轮廓**后的路径,所以它也按
    「填充」画,填的是描边色 —— 不需要再算 stroke-width,天生对齐 strokeAlign。
    """
    out = []
    grad = next((f for f in (node.get('fills') or [])
                 if f.get('visible', True) and f.get('type', '').startswith('GRADIENT')), None)
    if grad and node.get('fillGeometry'):
        # 渐变要 <defs><linearGradient>,这里还没做。**吭声**,别悄悄按纯色画。
        lost.append((node['id'], node.get('name', ''), 'VECTOR-GRADIENT'))
    fp = solid_paint(node.get('fills'))
    fc = paint_css(fp, backdrop, lost, node['id'], node.get('name', '')) if fp else None
    has_fill_geom = False
    for g in (node.get('fillGeometry') or []):
        if fc and g.get('path'):
            has_fill_geom = True
            out.append(dict(d=g['path'], rule=(g.get('windingRule') or 'NONZERO').lower(),
                            fill=fc, clip=''))
    # 描边压在自己的填充上;没有填充就压在背景上
    sbase = opaque_rgb(node.get('fills')) or backdrop
    sp = solid_paint(node.get('strokes'))
    sc = paint_css(sp, sbase, lost, node['id'], node.get('name', '')) if sp else None
    # **figma 的 strokeGeometry 是「预裁带」,不是最终描边。** 实测:一个 8px INSIDE 描边,
    # 给出来的带子是 **±8**(骑在形状边线上、总宽 2w),指望消费方按 strokeAlign 去裁 ——
    # INSIDE 裁进形状内、OUTSIDE 裁到形状外,裁完各剩 w,正好。CENTER 则本来就对(实测
    # 12px CENTER 给的是 ±6 = w),不裁。
    # 整条照画的后果:描边两边各多一倍 —— 系统页签的青边粗了一倍,而左上角信封那圈
    # 5px 白描边的内半边直接盖住了绿色本体,看着就是"白色很宽"。
    # v1.3:能劈就**在这儿劈**,只发要的那半、clip 清空 —— 后端"照着填"就精确,
    # 布尔裁剪不再是入场券(Painter2D 这类没有裁剪的后端以前只能整条照画,粗一倍)。
    # 劈不开才退回"原样 + clip 提示"的老路子,由拿得到 clipPath/mask 的后端自己裁。
    align = (node.get('strokeAlign') or 'CENTER').upper()
    shape_d = ' '.join(g['path'] for g in (node.get('fillGeometry') or []) if g.get('path'))
    # 裁/劈这条带子要的是**填充几何**(当参照形状),不是填充**涂装**。
    # 以前这里的闸门错挂在"有没有画出来的填充"上,于是**只有描边、没有填充色**的矢量
    # 一律整条照画 —— 实测那七个空槽位的八边形环粗了一倍(2.9px 画成 5.8px),
    # 而它们恰恰是最典型的"只有一圈边"的图标。
    mode = {'INSIDE': 'inside', 'OUTSIDE': 'outside'}.get(align, '') if shape_d else ''
    clip_src = False
    for g in (node.get('strokeGeometry') or []):
        if sc and g.get('path'):
            d, clip = g['path'], mode
            rule = (g.get('windingRule') or 'NONZERO').lower()
            if mode:
                ring = split_stroke_band(d, shape_d, float(node.get('strokeWeight') or 0), mode)
                if ring:
                    # 环 = 形状 + 内缩/外扩轮廓两条,靠 evenodd 把中间那圈留出来
                    d, clip, rule = ring, '', 'evenodd'
                elif not has_fill_geom:
                    # 劈不开 → 退回"原样 + clip 提示",由后端自己裁。但裁的**参照形状**
                    # 是"所有不带 clip 的路径"合起来 —— 本节点没有填充涂装,那份形状是空的,
                    # 提示就成了"裁到什么都不剩",环会**整个消失**(比粗一倍更糟)。
                    # 所以补一条**透明的形状路径**当参照:画出来什么都没有,裁剪却有据可依。
                    if not clip_src:
                        out.append(dict(d=shape_d, rule='nonzero', fill='rgba(0,0,0,0)', clip=''))
                        clip_src = True
            out.append(dict(d=d, rule=rule, fill=sc, clip=clip))
    return out


def radius(node):
    rc = node.get('rectangleCornerRadii')
    if rc:
        # 全零 = 没有圆角。别返回 '0px 0px 0px 0px' —— 它是**真值**,会把后面
        # "本节点没圆角就用别处的圆角"那类回退(遮罩形状 / 阴影跟随子矩形)全挡掉。
        if not any(round(v) for v in rc):
            return None
        return ' '.join('%dpx' % round(v) for v in rc)
    cr = node.get('cornerRadius')
    if cr:
        return '%dpx' % round(cr)
    return None


def border_inset(rec):
    """rec 的 INSIDE 描边宽度(px)。

    为什么要单独取它:CSS 里绝对定位的子元素是从父级的**内边距盒**起算的,而
    `border` 恰恰把内边距盒往里推了一整个描边宽。于是父级只要带描边,**整棵子树
    就被顶偏**一个描边宽 —— 实测返回按钮那圈 8px 描边把里面的箭头右下各推了 8px,
    而按钮本身分毫不差(所以肉眼只会觉得"图标没对齐",不会想到是描边)。
    子级定位时把这段减回去。OUTSIDE / CENTER 的外扩部分走 box-shadow,不占布局,
    不在此列。"""
    m = re.match(r'\s*([\d.]+)px', rec.get('border') or '')
    return float(m.group(1)) if m else 0.0


def relocate_container_shadows(records):
    """把「自己什么都不画的容器」的投影挪到**真正被投影的那个圆角子**身上。

    figma 的 DROP_SHADOW 投的是节点**渲染出来的内容**;CSS 的 box-shadow 投的是**盒子**。
    两者在按钮这种结构上会分道扬镳:按钮实例自身无填充无描边,形状在里面那个圆角矩形上,
    于是 CSS 照着实例的方框投出一条**直角黑杠**。实测底部主按钮下方多出一条 361px 宽、
    左右各支棱出来 4~7px 的黑边,而设计稿里是贴着圆角药丸的一圈厚边。

    旧办法是把子的圆角**借**给父级(`child_radius_for_shadow`),只在子恰好铺满父级时成立;
    这里的按钮子比父窄 11px,借完仍然左右露馅。改成直接**挪走**:父级不画东西,谁被投影
    就挂到谁身上,形状与位置一次对齐。子恰好铺满的老情形是它的特例,行为不变。

    只在父级确实"什么都不画"时才挪(无填充/图片/文字/矢量/描边/圆角),否则那阴影
    本来就是投给父级自己的形状的,不能动。
    """
    by_parent = {}
    for r in records:
        by_parent.setdefault(r['parent'], []).append(r)
    for r in records:
        if not r['shadow'] or r['radius'] or r['border'] or r['borderAlign'] or \
                r['fill'] or r['img'] or r['text'] or r['paths']:
            continue
        area = r['w'] * r['h']
        if area <= 0:
            continue
        best = None
        for c in by_parent.get(r['id'], []):
            if not c['radius'] or c['rot']:
                continue
            if c['x'] < r['x'] - 1 or c['y'] < r['y'] - 1 or \
                    c['x'] + c['w'] > r['x'] + r['w'] + 1 or c['y'] + c['h'] > r['y'] + r['h'] + 1:
                continue
            if c['w'] * c['h'] < area * 0.85:
                continue
            if best is None or c['w'] * c['h'] > best['w'] * best['h']:
                best = c
        if best is not None:
            best['shadow'] = ', '.join(x for x in (best['shadow'], r['shadow']) if x)
            r['shadow'] = ''
    return records


def text_styles(node):
    """Resolve UTF-16 character overrides; keep uniform text replaceable by app hooks."""
    base = dict(node.get('style') or {})
    base['fills'] = node.get('fills') or []
    overrides = node.get('characterStyleOverrides') or []
    table = node.get('styleOverrideTable') or {}
    runs, offset = [], 0
    for char in node.get('characters', ''):
        key = str(overrides[offset]) if offset < len(overrides) else '0'
        style = dict(base)
        style.update(table.get(key) or {})
        if runs and runs[-1][1] == style:
            runs[-1][0] += char
        else:
            runs.append([char, style])
        offset += len(char.encode('utf-16-le')) // 2
    return (runs[0][1], []) if len(runs) == 1 else (base, runs)


def decoration(style):
    return {'STRIKETHROUGH': 'line-through', 'UNDERLINE': 'underline'}.get(style.get('textDecoration'), 'none')


def matrix_mul(a, b):
    """CSS/SVG order [a,b,c,d,e,f], local points to frame coordinates."""
    return [a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5]]


def matrix_inverse(m):
    det = m[0]*m[3]-m[1]*m[2]
    if abs(det) < 1e-10:
        return None
    a,b,c,d = m[3]/det, -m[1]/det, -m[2]/det, m[0]/det
    return [a,b,c,d,-a*m[4]-c*m[5],-b*m[4]-d*m[5]]


def rec_matrix(rec):
    return rec.get('matrix') or [1, 0, 0, 1, rec['x'], rec['y']]


def resolve_geometry(root, records, losses):
    """Preserve absolute affine matrices on transformed branches, not double rotations.

    Matrix maps the record's local box to the frame, so extracting a subtree is safe.
    Missing transforms in transformed branches degrade explicitly to absolute boxes.
    """
    source, world, affected = {}, {}, set()
    fx, fy = root['absoluteBoundingBox']['x'], root['absoluteBoundingBox']['y']
    def visit(n, parent_matrix, active=False, is_root=False):
        source[n['id']] = n
        rt = n.get('relativeTransform')
        if is_root:
            m = [1,0,0,1,0,0]
        elif rt:
            m = matrix_mul(parent_matrix, [rt[0][0],rt[1][0],rt[0][1],rt[1][1],rt[0][2],rt[1][2]])
        else:
            bb = n.get('absoluteBoundingBox') or {}
            m = [1,0,0,1,bb.get('x',fx)-fx,bb.get('y',fy)-fy]
            if active:
                losses.append(dict(nodeId=n['id'], property='relativeTransform', code='MISSING-TRANSFORM',
                                   disposition='approximate', message='Missing transform under a transformed ancestor; using absolute box.'))
        nonidentity = any(abs(m[i]-[1,0,0,1][i]) > 1e-6 for i in range(4))
        if active or nonidentity:
            affected.add(n['id'])
        world[n['id']] = m
        for c in n.get('children') or []:
            visit(c, m, active or nonidentity)
    visit(root, [1,0,0,1,0,0], is_root=True)
    for r in records:
        n = source.get(r['id'])
        if not n or r['id'] not in affected:
            continue
        if r.get('img') and r.get('vec') and not r.get('paths'):
            r['matrix'] = [1,0,0,1,r['x'],r['y']]  # exported bitmaps are already oriented
            continue
        m = world[r['id']][:]
        if not matrix_inverse(m):
            losses.append(dict(nodeId=r['id'], property='relativeTransform', code='SINGULAR-TRANSFORM',
                               disposition='approximate', message='Singular transform; using legacy geometry.'))
            continue
        size = n.get('size') or {}
        w, h = size.get('x',r['w']), size.get('y',r['h'])
        if r.get('text'):
            lh = r['text'].get('lh')
            if lh and h > 0 and int(round(h/lh)) <= 1:
                align = (n.get('style') or {}).get('textAlignVertical','TOP')
                dy = (h-lh)/2 if lh > h else {'TOP':0,'CENTER':(h-lh)/2,'BOTTOM':h-lh}.get(align,0)
                m[4] += m[2]*dy; m[5] += m[3]*dy
                h = lh
        r['w'], r['h'] = round(w,4), round(h,4)
        r['matrix'] = [round(v,8) for v in m]
        if r.get('paths'):
            r['viewBox'] = '0 0 %.2f %.2f' % (w or 1,h or 1)
    return source, world


def expand_repeats(records, source, world, losses, limit=20000):
    """Bake bounded one-seed RELATIVE LINEAR repeats into normal records, inside out."""
    used = {r['id'] for r in records}
    for group in list(reversed(records)):
        n = source.get(group['id'], {})
        mods = n.get('transformModifiers') or []
        if not mods:
            continue
        m = mods[0]; children = n.get('children') or []
        count = m.get('count',0)
        valid = (len(mods)==1 and m.get('type')=='REPEAT' and m.get('repeatType')=='LINEAR'
                 and m.get('axis') in ('HORIZONTAL','VERTICAL') and m.get('unitType')=='RELATIVE'
                 and isinstance(count,int) and not isinstance(count,bool) and 1 <= count <= 1024
                 and len(children)==1)
        if valid:
            seed = children[0]; axis = 0 if m['axis']=='HORIZONTAL' else 1
            extent = (seed.get('size') or {}).get('x' if axis==0 else 'y')
            valid = (isinstance(extent,(int,float)) and isinstance(m.get('offset'),(int,float))
                     and math.isfinite(extent) and math.isfinite(m['offset']))
        branch = {group['id']}; descendants = []
        for r in records:
            if r['parent'] in branch:
                branch.add(r['id']); descendants.append(r)
        if not valid or not descendants or len(records)+len(descendants)*(count-1)>limit:
            losses.append(dict(nodeId=group['id'], property='transformModifiers', code='UNSUPPORTED-REPEAT',
                               disposition='drop', message='Only bounded one-seed RELATIVE LINEAR horizontal/vertical repeats are supported.'))
            continue
        step = extent*m['offset']; gm = world[group['id']]
        dx,dy = (gm[0]*step,gm[1]*step) if axis==0 else (gm[2]*step,gm[3]*step)
        copies = []
        for index in range(1,count):
            ids = {}
            for r in descendants:
                cid = '%s::repeat:%s:%d' % (r['id'],group['id'],index)
                while cid in used:
                    cid += '_'
                used.add(cid); ids[r['id']] = cid
            for r in descendants:
                c = copy.deepcopy(r); c['id'] = ids[r['id']]
                c['parent'] = ids.get(r['parent'],r['parent'])
                c['x'] = round(c['x']+dx*index,4); c['y'] = round(c['y']+dy*index,4)
                if c.get('matrix'):
                    c['matrix'][4] += dx*index; c['matrix'][5] += dy*index
                copies.append(c)
        at = max(records.index(r) for r in descendants)+1
        records[at:at] = copies
    for index,r in enumerate(records,1):
        r['z'] = index


def capture(root, asset_dir, asset_rel):
    """root = d['nodes'][frame_id]['document'];返回 (cap_dict, missing[])。"""
    FB = root['absoluteBoundingBox']
    FX, FY = FB['x'], FB['y']
    SW, SH = round(FB['width']), round(FB['height'])
    missing = []
    losses = []
    records = []
    order = [0]
    mask_done = set()      # 遮罩节点本身:只提供形状,任何情况下都不画成一层
    mask_pending = {}      # 遮罩 id -> 它的盒子;等子循环走到它那一步再造包裹层(z 序)

    def geom(node):
        bb = node.get('absoluteBoundingBox') or {}
        bx, by = bb.get('x', 0) - FX, bb.get('y', 0) - FY
        bw, bh = bb.get('width', 0), bb.get('height', 0)
        rt = node.get('relativeTransform'); rot = 0.0
        if rt:
            a, b = rt[0][0], rt[1][0]
            rot = math.degrees(math.atan2(b, a))
        if abs(rot) > 0.5:
            sz = node.get('size') or {}
            w = sz.get('x', bw); h = sz.get('y', bh)
            cx, cy = bx + bw / 2, by + bh / 2
            return cx - w / 2, cy - h / 2, w, h, rot
        return bx, by, bw, bh, 0.0

    def emit(node, parent_id, backdrop=None):
        if not node.get('visible', True):
            return
        paints = [p for p in node.get('fills') or [] if p.get('visible',True)]
        for paint in paints:
            if paint.get('type') == 'CUSTOM':
                losses.append(dict(nodeId=node['id'], property='fills', code='CUSTOM-FILL', disposition='drop',
                                   message='No adapter for custom effect: '+str(paint.get('customEffectId','unknown'))))
        if len(paints)>1:
            losses.append(dict(nodeId=node['id'], property='fills', code='MULTIPLE-FILLS', disposition='approximate',
                               message='Only one paint is rendered; layered paints are not composited.'))
        bb = node.get('absoluteBoundingBox') or {}
        if not bb or bb.get('width', 0) <= 0 or bb.get('height', 0) <= 0:
            # **一条水平线的 absoluteBoundingBox 高度就是 0** —— 它是零厚度的几何,
            # 看得见的那 6px 全在描边里,只出现在 absoluteRenderBounds。
            # 这个空盒守卫本来是拿来跳过真正空的容器的,却把 figma 里所有用
            # 描边线画的分隔线/下划线一并静默吃掉(附件上方那两条 6px 分隔线就是这么没的:
            # bb=879×0、render=885×6、strokeGeometry 有 1 条,画得出来却根本没进 IR)。
            # 有渲染边界又有可画几何的,按渲染边界收下;其余照旧只递归子节点。
            # 只是**放行**,不改 bb:路径坐标是相对原始包围盒算的,下面矢量分支里那段
            # "renderBounds 比 bb 大就按 renderBounds 定框、viewBox 反向平移"正好接手。
            # 改了 bb 反而会让那段判断失效,viewBox 停在 `0 0 w h`,线的上半截被切掉。
            rb0 = node.get('absoluteRenderBounds') or {}
            drawable = bool(node.get('strokeGeometry') or node.get('fillGeometry'))
            if not (drawable and rb0.get('width', 0) > 0 and rb0.get('height', 0) > 0):
                for ch in node.get('children') or []:
                    emit(ch, parent_id, backdrop)
                return
        typ = node.get('type')
        x, y, w, h, rot = geom(node)
        # 矢量簇 → 资产感知折叠:有导出 PNG 才整簇折叠成一张图;
        # 缺 PNG 则**不折叠**、继续递归——让簇内可渲染形状子(矩形/椭圆/文字)照常渲染,
        # 仅纯矢量叶子各自缺图→透明。杜绝"含可渲染子的簇因缺一张图而整体消失"(勾选框白盒/变更图圆)。
        if needs_image(node):
            u = vec_asset(node, asset_dir, asset_rel, missing)
            if u:
                order[0] += 1
                ax, ay = bb.get('x', 0) - FX, bb.get('y', 0) - FY
                records.append(dict(
                    id=node['id'], name=node.get('name', ''), type=typ, parent=parent_id,
                    x=round(ax, 1), y=round(ay, 1), w=round(bb.get('width', 0), 1), h=round(bb.get('height', 0), 1),
                    z=order[0], rot=0, opacity=round(node.get('opacity', 1), 3),
                    radius='', border='', shadow='', blur='',
                    fill='', img=u, imgSize='contain', imgPos='', text=None, clip=False, paths=[], viewBox='', borderAlign='', vec=True))
                return
            # 缺图:能走到这儿的一定是**纯矢量簇**(needs_image 已经保证簇内没有可渲染形状),
            # 留个透明占位等图,别递归出几百个空 div。
            # 含可渲染形状的簇根本到不了这儿 —— needs_image 上游就判给递归了。
            # (那正是"勾选框白盒/图标缺一张图就整体消失"那类 bug 的根治点:以前靠这里
            #  `has_renderable_shape and vector_leaf_count<=4` 兜底,只兜得住小簇;
            #  大簇仍然只有"整块变图"或"整块消失"两条路,没有第三条。)
            order[0] += 1
            ax, ay = bb.get('x', 0) - FX, bb.get('y', 0) - FY
            records.append(dict(
                id=node['id'], name=node.get('name', ''), type=typ, parent=parent_id,
                x=round(ax, 1), y=round(ay, 1), w=round(bb.get('width', 0), 1), h=round(bb.get('height', 0), 1),
                z=order[0], rot=0, opacity=round(node.get('opacity', 1), 3),
                radius='', border='', shadow='', blur='',
                fill='', img='', imgSize='', imgPos='', text=None, clip=False, paths=[], viewBox='', borderAlign='', vec=True))
            return
        order[0] += 1
        rec = dict(
            id=node['id'], name=node.get('name', ''), type=typ, parent=parent_id,
            x=round(x, 1), y=round(y, 1), w=round(w, 1), h=round(h, 1),
            z=order[0], rot=(round(rot, 2) if abs(rot) > 0.5 else 0),
            opacity=round(node.get('opacity', 1), 3),
            radius='', border='', shadow='', blur='', fill='', img='', imgSize='', imgPos='', text=None,
            clip=False, paths=[], viewBox='', borderAlign='', vec=False)
        rad = radius(node)
        if rad:
            rec['radius'] = rad
        if typ == 'ELLIPSE':
            rec['radius'] = '50%'
        rings = []          # OUTSIDE/CENTER 描边的外扩环,与真投影一起挂 box-shadow
        st = node.get('strokes') or []
        has_stroke = bool(st and st[0].get('visible', True) and node.get('strokeWeight') and st[0].get('color'))
        if has_stroke and typ != 'TEXT':
            # **描边对齐方向不能不管。** figma 有 INSIDE / OUTSIDE / CENTER 三种,
            # 而 CSS 的 border 只有"向内"一种。以前一律按 border 画,于是所有 OUTSIDE
            # 描边都画反了方向:本该外扩 N px,变成了往里吃掉 N px 填充 —— 一个 10px
            # 描边的装饰因此差了 20px,肉眼可见。
            #   INSIDE  → border(CSS 原生就是它)
            #   OUTSIDE → box-shadow 0 0 0 N(外扩、不占布局、**跟随圆角**;
            #             outline 不跟圆角,所以不用它)
            #   CENTER  → 各一半
            bw = float(node['strokeWeight'])
            bc = paint_css(st[0], opaque_rgb(node.get('fills')) or backdrop,
                           missing, node['id'], node.get('name', ''))
            align = (node.get('strokeAlign') or 'INSIDE').upper()
            rec['borderAlign'] = align.lower()
            inner = bw if align == 'INSIDE' else (bw / 2 if align == 'CENTER' else 0)
            outer = bw if align == 'OUTSIDE' else (bw / 2 if align == 'CENTER' else 0)
            if inner:
                rec['border'] = '%.1fpx solid %s' % (inner, bc)
            if outer:
                rings.append('0 0 0 %.1fpx %s' % (outer, bc))
        shadows = []
        for ef in node.get('effects') or []:
            if not ef.get('visible', True):
                continue
            o = ef.get('offset', {'x': 0, 'y': 0}); r = ef.get('radius', 0)
            if ef['type'] == 'DROP_SHADOW':
                spread = (' %gpx' % ef['spread']) if ef.get('spread') else ''
                shadows.append('%gpx %gpx %gpx%s %s' % (
                    o.get('x', 0), o.get('y', 0), r, spread, col(ef.get('color', {'r': 0, 'g': 0, 'b': 0, 'a': .3}))))
            elif ef['type'] == 'LAYER_BLUR':
                # **figma 的模糊半径不是 CSS 的 σ。** CSS `filter: blur(L)` 里 L 就是标准差,
                # 而 figma 的 Layer blur 半径约等于 2σ —— 一比一照抄会糊出**两倍**的范围:
                # 实测本项目那五团光晕(figma 半径 60.6),照抄时光晕区平均差 5.80/255,
                # 折半后 1.84/255(好 3.1 倍)。
                # 诚实交代:同一组实测扫下来最优比例落在 **≈0.42**(1.57/255),不是整 0.5;
                # 但本帧五个元素**只有 60.6 这一个半径**,分不开"σ=kR"与"σ=R/2 再加个常数修正",
                # 拿一个样本去拟合常数是过拟合。所以取有据可循的 R/2,并把这段测量留在这里 ——
                # 将来有第二个半径的样本再定夺。
                rec['blur'] = 'blur(%.0fpx)' % (r / 2.0)
            else:
                losses.append(dict(nodeId=node['id'], property='effects', code='UNSUPPORTED-EFFECT',
                                   disposition='drop', message='Unsupported effect: '+ef['type']))
        if rings or shadows:
            rec['shadow'] = ', '.join(rings + shadows)   # 环在前:更靠近元素,不被投影盖住
        # 阴影方框修正见 relocate_container_shadows():记录全部产出后再统一挪,
        # 那时才知道每个容器下面到底挂了些什么(emit 期只看得见 figma 节点,看不见
        # 折叠/下沉之后真正留下来的那批记录)。
        if typ == 'TEXT':
            s, runs = text_styles(node)
            lh = s.get('lineHeightPx')
            ah = {'LEFT': 'flex-start', 'CENTER': 'center', 'RIGHT': 'flex-end',
                  'JUSTIFIED': 'space-between'}.get(s.get('textAlignHorizontal', 'LEFT'), 'flex-start')
            av = {'TOP': 'flex-start', 'CENTER': 'center', 'BOTTOM': 'flex-end'}.get(s.get('textAlignVertical', 'TOP'), 'flex-start')
            t = dict(content=node.get('characters', ''),
                     color=(solid(s.get('fills')) or '#000'),
                     size=round(s.get('fontSize', 14), 1),
                     family=s.get('fontFamily', 'sans-serif'),
                     weight=s.get('fontWeight', 400),
                     lh=(round(lh) if lh else 0),
                     ls=round(s.get('letterSpacing', 0), 2),
                     alignH=ah, alignV=av,
                     textAlign=s.get('textAlignHorizontal', 'LEFT').lower(),
                     # v1.3:**这段文字该不该折行**,由 figma 的 textAutoResize 说了算。
                     # 不读它的后果:定宽正文只能一律 nowrap,一行冲出文本框 ——
                     # html 那侧靠 app.js 的 hook 硬绕,而引擎侧没有等价 hook,只能眼睁睁溢出。
                     # 语义:NONE(定宽定高)与 HEIGHT(定宽自动高)= 宽度固定 → **折行**;
                     # WIDTH_AND_HEIGHT(随字撑宽)= 不折;TRUNCATE = 定宽但溢出截断,仍折。
                     wrap=(s.get('textAutoResize', 'NONE') or 'NONE').upper()
                     != 'WIDTH_AND_HEIGHT',
                     stroke='')
            if decoration(s) != 'none':
                t['decoration'] = decoration(s)
            if runs:
                t['runs'] = [dict(content=content, decoration=decoration(rs),
                                 color=solid(rs.get('fills')) or t['color'],
                                 size=rs.get('fontSize',t['size']), family=rs.get('fontFamily',t['family']),
                                 weight=rs.get('fontWeight',t['weight']), ls=rs.get('letterSpacing',t['ls']))
                             for content,rs in runs]
            if has_stroke:
                # -webkit-text-stroke 是**居中**描边:一半在字外、一半吃进字面。
                # figma 的文字描边默认 OUTSIDE(全在字外),所以宽度要 ×2 才等效,
                # 否则每个带描边的标题都会瘦一圈 —— 中文标题尤其明显。
                tw = float(node['strokeWeight'])
                if (node.get('strokeAlign') or 'OUTSIDE').upper() == 'OUTSIDE':
                    tw *= 2
                t['stroke'] = '%.1fpx %s' % (tw, paint_css(st[0], backdrop, missing,
                                                          node['id'], node.get('name', '')))
            # v1.3:**单行文本的竖直位置在这里算完**,盒子归一成「行盒」。
            # 「行高 + 竖直锚点」是 CSS 语汇,引擎侧没有等价物 —— godot 的 Label 和
            # Unity 的 UI Toolkit 都没有 line-height。同一份 IR:html 靠 line-height 对上了,
            # godot 低 12px、unity 吃不到半行距(half-leading)整体高 8.5px。
            # 归一之后三端只要"在盒子里居中"就精确一致,谁也不用 line-height。
            #
            # 竖直规则取自实测(拿 absoluteRenderBounds 当墨迹真值,5 个样本全中):
            # 行块高 = lineHeight,按 textAlignVertical 放进文本框;**行块比框高时
            # 不是顶对齐、而是居中溢出**(样本:框高 31 / 行高 50.4 / TOP,墨迹中心
            # 落在框心而不是行块顶对齐处,差 10px)。
            # 装得下两行以上的框不动 —— 那时候顶对齐是对的,归一反而会把正文拽到中间。
            if lh and rec['h'] > 0 and int(round(rec['h'] / lh)) <= 1:
                top = ((rec['h'] - lh) / 2 if lh > rec['h'] else
                       {'flex-start': 0.0, 'center': (rec['h'] - lh) / 2,
                        'flex-end': rec['h'] - lh}[av])
                rec['y'] = round(rec['y'] + top, 1)
                rec['h'] = round(lh, 1)
                t['alignV'] = 'center'
            rec['text'] = t
            records.append(rec)
            return  # 文本不递归

        # ── figma 遮罩(isMask)──
        # 带 isMask 的子层**不是一层画面**,是拿自己的形状去裁它后面的兄弟。
        # 以前不认这个字段,于是遮罩被当普通图层照着画:一个本该只提供圆角轮廓的
        # 渐变矩形直接盖成了一块色板(黄面板渲成了绿的),而被它裁的装饰(一个
        # 2143×680 的大椭圆)失去约束、糊满整屏。
        # 常见形状(矩形/椭圆,且铺满父盒)→ 转成父级的 overflow:hidden + 圆角,精确等价。
        # 形状兜不住的 → 不画遮罩、不裁,**吭声**(honest degradation,别装作还原了)。
        # figma 的 clipsContent(帧「裁剪内容」)= 直接的裁剪意图,跟遮罩共用一个字段。
        # 不认它的后果:滚动区里最后一行整条漏在容器外面 —— 看着像层级错了,
        # 其实是少了 overflow:hidden。
        if node.get('clipsContent'):
            rec['clip'] = True

        mask = next((c for c in (node.get('children') or [])
                     if c.get('visible', True) and c.get('isMask')), None)
        if mask is not None:
            mb = mask.get('absoluteBoundingBox') or {}
            covers = (abs(mb.get('width', 0) - w) <= 2 and abs(mb.get('height', 0) - h) <= 2
                      and abs((mb.get('x', 0) - FX) - x) <= 2 and abs((mb.get('y', 0) - FY) - y) <= 2)
            mr = ('50%' if mask.get('type') == 'ELLIPSE' else radius(mask))
            if mask.get('type') in ('RECTANGLE', 'ELLIPSE'):
                mask_done.add(mask['id'])       # 遮罩只提供形状,任何情况下都不许画出来
                if covers:
                    rec['clip'] = True          # 铺满父盒:让父级裁,省一层 div
                    if mr and not rec['radius']:
                        rec['radius'] = mr
                else:
                    # **不铺满父盒**:figma 的遮罩只影响它**之后**的兄弟,而父级是整块卡片。
                    # 拿父级去裁会连不该裁的一起裁,所以造一层「裁剪包裹」,几何 = 遮罩盒,
                    # 把遮罩之后的兄弟挂进去。
                    # 踩过:邮件行里 152×152 的图标遮罩挂在 925×186 的卡片下 —— 判定不铺满
                    # 就放弃了,于是遮罩自己(一块青色)被当普通图层画出来盖住底色,而它本该
                    # 裁住的深绿波浪则方角溢出圆角图标框。两处错都出自同一个"放弃"。
                    # **包裹层的 z 必须等到子循环走到遮罩那一步才发号**(见下面 make_wrap):
                    # 在这里发的话它比父节点自己还小,于是连同里面的东西一起被后画的
                    # 兄弟盖死 —— 波浪就是这么整块消失的。
                    mask_pending[mask['id']] = mb
            else:
                sys.stderr.write(
                    '[capture][known-loss] 遮罩 %s 是 %s,不是矩形/椭圆,转不成 CSS 裁剪;'
                    '该组不裁剪 —— 父 %s\n'
                    % (mask['id'], mask.get('type'), node['id']))

        # 矢量:能照路径画就画,别下图(见 vector_paths 的说明)
        if typ in VEC:
            ps = vector_paths(node, missing, backdrop)
            if ps:
                rec['paths'] = ps
                rec['vec'] = True
                # **描边几何会超出 absoluteBoundingBox。** 圆头端点、外描边都会甩到盒子外面:
                # 一条 38×1 的箭头杆配 12px 圆头描边,真实可视范围是 50×12。
                # 按包围盒开视口就会把端点切掉 —— 返回箭头因此渲成了一根方棍。
                # figma 的 absoluteRenderBounds 给的正是含描边的可视范围,拿它当盒子,
                # viewBox 反向平移回去,路径坐标(相对包围盒原点)就仍然对得上。
                rb = node.get('absoluteRenderBounds') or {}
                if (not rot) and rb.get('width') and (rb['width'] > bb.get('width', 0) + .5
                                                      or rb['height'] > bb.get('height', 0) + .5):
                    dx, dy = bb['x'] - rb['x'], bb['y'] - rb['y']
                    rec['x'] = round(rb['x'] - FX, 1); rec['y'] = round(rb['y'] - FY, 1)
                    rec['w'] = round(rb['width'], 1); rec['h'] = round(rb['height'], 1)
                    rec['viewBox'] = '%.2f %.2f %.2f %.2f' % (-dx, -dy, rb['width'], rb['height'])
                else:
                    # **用 rec 自己的 w/h,不是包围盒。** 节点旋转时 geom() 已经把 w/h
                    # 换成了本地 size,而路径坐标正是在那个未旋转的本地空间里 ——
                    # 拿旋转后的轴对齐包围盒当 viewBox,图形会被压扁:那个倾斜的礼物
                    # 字形因此缩到了 0.8 倍。
                    rec['viewBox'] = '0 0 %.2f %.2f' % (rec['w'] or 1, rec['h'] or 1)
                # 形状和描边都已经在路径里了(strokeGeometry 就是 figma 把描边转成的
                # 可填充轮廓),再留 border / 外扩环 / 圆角就会**沿着矩形盒子画第二遍**。
                # 踩过:一根 38×1 的箭头杆带 12px 居中描边,环画成了 6px 白色方框,
                # 整个返回箭头被糊成一坨白块 —— 图形本身其实一直是对的。
                rec['border'] = ''
                rec['radius'] = ''
                rec['borderAlign'] = ''
                rec['shadow'] = ', '.join(shadows)   # 只留真投影,丢掉描边环
                if shadows:
                    rec['vectorShadows'] = [dict(x=e.get('offset',{}).get('x',0), y=e.get('offset',{}).get('y',0),
                                                blur=e.get('radius',0)/2, spread=e.get('spread',0),
                                                color=col(e.get('color',{'r':0,'g':0,'b':0,'a':.3})))
                                            for e in node.get('effects') or []
                                            if e.get('visible',True) and e['type']=='DROP_SHADOW']
                records.append(rec)
                return
        iu, isize, ipos = img_fill(node, asset_dir, asset_rel, missing)
        if iu:
            rec['img'] = iu; rec['imgSize'] = isize; rec['imgPos'] = ipos
        else:
            grad = next((f for f in (node.get('fills') or [])
                         if f.get('visible', True) and f.get('type', '').startswith('GRADIENT')), None)
            if grad:
                rec['fill'] = gradient_css(grad)
            else:
                fp2 = solid_paint(node.get('fills'))
                if fp2:
                    rec['fill'] = paint_css(fp2, backdrop, missing,
                                            node['id'], node.get('name', ''))
        records.append(rec)
        holder = node['id']
        sib_bg = opaque_rgb(node.get('fills')) or backdrop
        for ch in node.get('children') or []:
            if ch.get('id') in mask_done:
                # 遮罩本身不画;它**之后**的兄弟改挂进裁剪包裹层 —— 这正是 figma
                # 遮罩的作用范围(只影响其后的兄弟,不影响它前面的)。
                mb2 = mask_pending.pop(ch['id'], None)
                if mb2 is not None:
                    order[0] += 1          # 在文档序里就地发号,包裹层才叠在它该在的层
                    holder = ch['id'] + '~mask'
                    mr2 = ('50%' if ch.get('type') == 'ELLIPSE' else radius(ch))
                    records.append(dict(
                        id=holder, name=(ch.get('name', '') + ' (遮罩裁剪)'), type='GROUP',
                        parent=node['id'],
                        x=round(mb2.get('x', 0) - FX, 1), y=round(mb2.get('y', 0) - FY, 1),
                        w=round(mb2.get('width', 0), 1), h=round(mb2.get('height', 0), 1),
                        z=order[0], rot=0, opacity=1,
                        radius=(mr2 or ''), border='', shadow='', blur='', fill='',
                        img='', imgSize='', imgPos='', text=None, clip=True, paths=[], viewBox='',
                        borderAlign='', vec=False))
                continue
            emit(ch, holder, sib_bg)
            # 铺满本容器的不透明纯色兄弟 = 之后兄弟的背景色(按钮就是这么给纹理垫底的)
            cb = ch.get('absoluteBoundingBox') or {}
            if abs(cb.get('width', 0) - w) <= 2 and abs(cb.get('height', 0) - h) <= 2:
                rgb = opaque_rgb(ch.get('fills'))
                if rgb:
                    sib_bg = rgb

    # 帧背景(自身 fill)
    stage_bg = ''
    if any(f.get('type', '').startswith('IMAGE') for f in (root.get('fills') or [])) and \
            os.path.exists(os.path.join(asset_dir, 'bg.png')):
        stage_bg = 'url(%s/bg.png) center/cover no-repeat' % asset_rel
    else:
        iu, isize, ipos = img_fill(root, asset_dir, asset_rel, missing)
        if iu:
            stage_bg = 'url(%s) %s/%s no-repeat' % (iu, ipos or 'center', isize)
        elif solid(root.get('fills')):
            stage_bg = solid(root.get('fills'))
        else:
            grad = next((f for f in (root.get('fills') or []) if f.get('type', '').startswith('GRADIENT')), None)
            if grad:
                stage_bg = gradient_css(grad)

    root_bg = opaque_rgb(root.get('fills'))
    for ch in root.get('children') or []:
        emit(ch, '', root_bg)
    relocate_container_shadows(records)
    source, world = resolve_geometry(root, records, losses)
    expand_repeats(records, source, world, losses)
    cap = dict(spec=IR_SPEC, frame=root.get('id'), w=SW, h=SH, stageBg=stage_bg, els=records)
    if losses:
        cap['losses'] = losses
    return cap, missing


# ---- 序列化器 ----

# 注意:本函数(出 .tree.html 静态预览)与 runtime/render.js 的 applyRecStyle(出运行时 DOM)
# 是**同一套贴样式映射**。改任一处样式逻辑务必同步另一处,否则"预览 ≠ 运行时"会悄悄漂移。
# 已知**有意**差异(别对齐):图片 url 这里用裸路径(tree.html 与素材同级),render.js 补 '../../'
# (app.html 在 client 目录、深两层)。其余(white-space 单行 nowrap/多行 pre-wrap 等)必须一致。
def svg_markup(rec):
    """路径 → 内联 SVG。与 render.js 的 buildSvg 是同一套写法,改一处必同步另一处。

    preserveAspectRatio="none":路径坐标就是节点自身包围盒,viewBox 与 div 尺寸
    天生一致,不许它再自作主张地等比缩放居中(那正是位图时代"错半格"的老毛病)。
    """
    uid = hashlib.sha256(rec['id'].encode('utf-8')).hexdigest()[:24]
    shape = ' '.join(q['d'] for q in rec['paths'] if not q.get('clip'))   # 填充形状 = 描边的裁剪依据
    need = {q.get('clip') for q in rec['paths']} - {''}
    defs = ''
    if 'inside' in need:
        defs += '<clipPath id="cin_%s"><path d="%s"/></clipPath>' % (uid, html.escape(shape))
    if 'outside' in need:
        # 「形状之外」用蒙版:整面涂白 → 可见,形状涂黑 → 挖掉
        vb = [float(v) for v in (rec.get('viewBox') or '0 0 1 1').split()]
        defs += ('<mask id="cout_%s"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#fff"/>'
                 '<path d="%s" fill="#000"/></mask>'
                 % (uid, vb[0] - 64, vb[1] - 64, vb[2] + 128, vb[3] + 128, html.escape(shape)))
    ps = ''
    for q in rec['paths']:
        att = ''
        if q.get('clip') == 'inside':
            att = ' clip-path="url(#cin_%s)"' % uid
        elif q.get('clip') == 'outside':
            att = ' mask="url(#cout_%s)"' % uid
        ps += '<path d="%s" fill="%s" fill-rule="%s"%s/>' % (
            html.escape(q['d']), q['fill'], q['rule'], att)
    if rec.get('vectorShadows'):
        vb = [float(v) for v in (rec.get('viewBox') or '0 0 %g %g' % (rec['w'],rec['h'])).split()]
        shadows = rec['vectorShadows']
        pad = max([1]+[max(abs(e['x']),abs(e['y']))+abs(e['spread'])+4*e['blur'] for e in shadows])
        flt = '<filter id="shadow_%s" filterUnits="userSpaceOnUse" x="%g" y="%g" width="%g" height="%g" color-interpolation-filters="sRGB">' % (uid,vb[0]-pad,vb[1]-pad,vb[2]+2*pad,vb[3]+2*pad)
        for i,e in enumerate(shadows):
            inp = 'SourceAlpha'
            if e['spread']:
                flt += '<feMorphology in="SourceAlpha" operator="%s" radius="%g" result="spread%d"/>' % ('dilate' if e['spread']>0 else 'erode',abs(e['spread']),i)
                inp = 'spread%d' % i
            flt += ('<feGaussianBlur in="%s" stdDeviation="%g" result="blur%d"/>'
                    '<feOffset in="blur%d" dx="%g" dy="%g" result="offset%d"/>'
                    '<feFlood flood-color="%s" result="color%d"/>'
                    '<feComposite in="color%d" in2="offset%d" operator="in" result="shadow%d"/>'
                    % (inp,e['blur'],i,i,e['x'],e['y'],i,html.escape(e['color']),i,i,i,i))
        flt += '<feMerge>'+''.join('<feMergeNode in="shadow%d"/>' % i for i in reversed(range(len(shadows))))+'<feMergeNode in="SourceGraphic"/></feMerge></filter>'
        defs += flt
        ps = '<g filter="url(#shadow_%s)">%s</g>' % (uid,ps)
    return ('<svg viewBox="%s" preserveAspectRatio="none" '
            'style="width:100%%;height:100%%;display:block;overflow:visible">%s%s</svg>'
            % (rec.get('viewBox') or ('0 0 %.1f %.1f' % (rec['w'] or 1, rec['h'] or 1)),
               ('<defs>%s</defs>' % defs) if defs else '', ps))


def rec_to_css(rec, parent=None):
    # 父级带 INSIDE 描边时,绝对定位的子元素从内边距盒起算 → 整棵子树被顶偏一个描边宽。
    # 见 border_inset()。render.js 的 pass2 有同一段补偿,改一处必同步。
    bi = border_inset(parent) if parent else 0.0
    px = (parent['x'] + bi) if parent else 0
    py = (parent['y'] + bi) if parent else 0
    sty = ['position:absolute', 'left:%.1fpx' % (rec['x'] - px), 'top:%.1fpx' % (rec['y'] - py),
           'width:%.1fpx' % rec['w'], 'height:%.1fpx' % rec['h'], 'z-index:%d' % rec['z']]
    if rec.get('matrix') or (parent and parent.get('matrix')):
        matrix = matrix_mul(matrix_inverse(rec_matrix(parent)),rec_matrix(rec)) if parent else rec_matrix(rec)[:]
        matrix[4] -= bi; matrix[5] -= bi
        sty.append('left:0;top:0;transform:matrix(%s);transform-origin:0 0' % ','.join('%g' % (0 if abs(v)<1e-10 else v) for v in matrix))
    elif rec['rot']:
        sty.append('transform:rotate(%.2fdeg);transform-origin:center center' % rec['rot'])
    if rec['opacity'] != 1:
        sty.append('opacity:%.3f' % rec['opacity'])
    if rec['radius']:
        sty.append('border-radius:' + rec['radius'])
    if rec.get('clip'):
        sty.append('overflow:hidden')
    if rec['border']:
        sty.append('box-sizing:border-box;border:' + rec['border'])
    if rec['shadow'] and not (rec.get('paths') and rec.get('vectorShadows')):
        sty.append('box-shadow:' + rec['shadow'])
    if rec['blur']:
        sty.append('filter:' + rec['blur'])
    inner = ''
    t = rec['text']
    if t:
        # 与 render.js 一致:figma 说这段定宽(textAutoResize ≠ WIDTH_AND_HEIGHT)就折行,
        # 否则 nowrap —— 随字撑宽的文本框折了行反而是错的(字体回退偏宽会逼出假换行)。
        ws = 'pre-wrap' if t.get('wrap') or '\n' in (t['content'] or '') else 'nowrap'
        sty.append("display:flex;justify-content:%s;align-items:%s;color:%s;font-size:%.1fpx;"
                   "font-family:'FigCJK','%s','Source Han Sans SC','Noto Sans SC',sans-serif;"
                   "font-weight:%s;line-height:%s;letter-spacing:%.2fpx;"
                   "text-align:%s;white-space:%s;overflow:visible" % (
                       t['alignH'], t['alignV'], t['color'], t['size'], t['family'], t['weight'],
                       (str(t['lh']) + 'px' if t['lh'] else 'normal'), t['ls'], t['textAlign'], ws))
        if t['stroke']:
            sty.append('-webkit-text-stroke:%s;paint-order:stroke fill' % t['stroke'])
        inner = html.escape(t['content'])
        if t.get('decoration') and not t.get('runs'):
            sty.append('text-decoration-line:'+t['decoration'])
        if t.get('runs'):
            inner = '<span style="min-width:0;max-width:100%">'+''.join(
                '<span style="text-decoration-line:%s;color:%s;font-size:%gpx;font-weight:%s;letter-spacing:%gpx;font-family:FigCJK,%s,sans-serif">%s</span>'
                % (r['decoration'],html.escape(r['color']),r['size'],r['weight'],r['ls'],html.escape(r['family']),html.escape(r['content']))
                for r in t['runs'])+'</span>'
    elif rec.get('paths'):
        inner = svg_markup(rec)
    elif rec['img']:
        sty.append('background:url(%s) %s/%s no-repeat' % (html.escape(rec['img']),
                                                            rec.get('imgPos') or 'center', rec['imgSize'] or 'cover'))
    elif rec['fill']:
        sty.append('background:' + rec['fill'])
    return '<div data-id="%s" title="%s" style="%s">%s' % (
        html.escape(str(rec['id'])),
        html.escape(rec['name'] + ' <' + str(rec['type']) + '>'), ';'.join(sty), inner)


def to_html(cap, sNN):
    """静态预览。**按 parent 嵌套**,几何转成父级相对 —— 与 render.js 同构。

    这里曾经是扁平的(所有节点平铺成兄弟 div、用帧内绝对坐标定位)。样式贴得一模一样,
    唯独容器关系不一致,于是任何**依赖父子**的效果在预览里一律看不出来:
    `clip`(overflow:hidden)首当其冲 —— 遮罩不生效,被裁的装饰照样糊到外面。
    代价不是"预览糙一点",是**它会说谎**:拿它排查裁剪问题,会把一个早就修好的
    功能判成坏的(2026-08-04 就这么误诊过一次,绕了一大圈)。
    预览和运行时同构之后,tree.html 才配当"不开服务器也能看的那一份"。"""
    by = {r['id']: r for r in cap['els']}
    kids = {}
    for r in cap['els']:
        kids.setdefault(r['parent'] if r['parent'] in by else '', []).append(r)

    def render(pid, parent):
        return ''.join(rec_to_css(r, parent) + render(r['id'], r) + '</div>'
                       for r in kids.get(pid, []))

    divs = render('', None)
    bg = ('background:' + cap['stageBg']) if cap['stageBg'] else ''
    # 设计字体:同级 `fonts/FigCJK-*.woff2` 在就用,不在就退系统字体(浏览器自己回退,不报错)。
    # 这份预览是**像素比对的基准**,基准用什么字体、其它端就得用什么字体 —— 各端各拿
    # 系统默认字体时连换行位置都不一样,比出来的差异全是字形噪声。
    # 子集由 scripts/subset_font.py 产;两个字重要**两个文件**,别指望合成粗体。
    font = ("@font-face{font-family:'FigCJK';src:url('fonts/FigCJK-Regular.woff2') format('woff2');"
            "font-weight:400;font-display:block}\n"
            "@font-face{font-family:'FigCJK';src:url('fonts/FigCJK-Bold.woff2') format('woff2');"
            "font-weight:700;font-display:block}\n")
    return ('<!doctype html><html><head><meta charset="utf-8"><title>%s·Figma树高保真还原</title>\n'
            '<style>%sbody{margin:0;background:#2b2b33;display:flex;justify-content:center;padding:14px}\n'
            ' .stage{position:relative;width:%dpx;height:%dpx;%s;box-shadow:0 4px 24px #000;overflow:hidden}\n'
            ' .stage div{box-sizing:border-box}</style></head>\n'
            '<body><div class="stage">%s</div></body></html>'
            % (sNN, font, cap['w'], cap['h'], bg, divs))


USAGE = """用法: python3 figma_capture.py <nodes.json> <frameId> <sNN> <assetDir> <assetRel> <outBase>

  nodes.json  figma REST 的响应: GET /v1/files/<key>/nodes?ids=<frameId>
  frameId     要抓的帧 node id(如 "1:2"),必须是 nodes.json 里的键
  sNN         屏编号前缀(如 s01),只用于产物里的标识
  assetDir    本地素材目录(png 从这里找;缺图会被列进 missing 而不是静默)
  assetRel    素材在产物里的相对前缀(如 assets)
  outBase     产物前缀,产 <outBase>.ui.json 与 <outBase>.tree.html

不需要 token:本脚本只读已经落地的 nodes.json。拉取那步见 README「Real Figma input」。
想先看看跑起来什么样、又没有 figma 文件:examples/login/make_fixture.py 会合成三屏喂给本管线。"""


if __name__ == '__main__':
    if len(sys.argv) < 7:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    nodes_json, frame_id, sNN, asset_dir, asset_rel, out_base = sys.argv[1:7]
    d = json.load(open(nodes_json, encoding='utf-8'))
    root = d['nodes'][frame_id]['document']
    cap, missing = capture(root, asset_dir, asset_rel)
    json.dump(cap, open(out_base + '.ui.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    io.open(out_base + '.tree.html', 'w', encoding='utf-8').write(to_html(cap, sNN))
    print('captured %d els -> %s.ui.json + .tree.html (%dx%d) missing-asset %d'
          % (len(cap['els']), out_base, cap['w'], cap['h'], len(missing)))
    for mid, mn, mt in missing[:40]:
        print('  miss:', mid, mt, (mn or '')[:16])
    for loss in cap.get('losses',[]):
        print('[capture][known-loss] '+json.dumps(loss,ensure_ascii=True), file=sys.stderr)
    if '--strict' in sys.argv[7:] and (missing or cap.get('losses')):
        sys.exit(1)

# -*- coding: utf-8 -*-
"""Figma 节点树 -> 界面DSL(.md)  确定性转换器(项目无关)
用法: python figma_to_dsl.py <nodes.json> <frameId> <NN> <屏名> <outdir>
                             [--prefix screen] [--brand figma] [--file-key KEY] [--meta meta.json]
  --prefix    产物文件名/标题前缀(默认 screen → screen-<NN>.md)
  --brand     来源品牌串(默认 figma;写进标题与来源行)
  --file-key  figma file key(默认取环境变量 FIGMA_FILE_KEY,再缺省写 <fileKey> 占位)
  --meta      屏位元数据 json(键=NN,值={u:用途,l:布局,t:标签,p:[设计点评…]});项目私有数据放项目里,不进本 skill
纯函数接口: build_dsl(doc, frame_id, NN, screen_name, meta=None, brand='figma',
                      file_key='', capture_date='', prefix='screen') -> (md_text, sidecar_dict)
"""
import json, io, re, os, datetime

FILE_KEY = os.environ.get("FIGMA_FILE_KEY", "")

META = {}  # 屏位元数据默认为空;项目私有条目经 --meta meta.json 注入,不进本 skill

# ---- 模块级常量 ----
CONT = {'GROUP', 'FRAME', 'INSTANCE', 'COMPONENT', 'BOOLEAN_OPERATION'}
VEC = {'VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'LINE', 'REGULAR_POLYGON'}
GENERIC = re.compile(r'^(Group|Rectangle|Vector|Union|Subtract|Intersect|Ellipse|Frame|Component|矩形|形状|组|图层|椭圆|Line|Star|Polygon)\b', re.I)
CJK = re.compile(r'[一-鿿]')
BTN = re.compile(r'(返回|确定|取消|确认|开始|领取|前往|关闭|按钮|btn|back|确认|继续|挑战|购买|升级|晋升)', re.I)


# ---- 辅助函数(无状态,可在模块级定义) ----

def hexfill(n):
    for f in n.get('fills') or []:
        if not f.get('visible', True): continue
        t = f.get('type', '')
        if t == 'SOLID':
            c = f['color']; r, g, b = [int(round(c[k] * 255)) for k in 'rgb']
            return '#%02x%02x%02x' % (r, g, b)
        if t.startswith('IMAGE'): return 'IMG'
        if t.startswith('GRADIENT'):
            st = f.get('gradientStops') or []
            if st:
                n2 = len(st)
                r = int(round(sum(s['color']['r'] for s in st) / n2 * 255))
                g = int(round(sum(s['color']['g'] for s in st) / n2 * 255))
                b = int(round(sum(s['color']['b'] for s in st) / n2 * 255))
                return '#%02x%02x%02x' % (r, g, b)
            return 'GRAD'
    return None


def _desc(n):
    yield n
    for c in n.get('children') or []: yield from _desc(c)


def texts_of(n):
    return [d['characters'].strip() for d in _desc(n)
            if d.get('type') == 'TEXT' and d.get('characters', '').strip() and d.get('visible', True)]


def has_img(n):
    return any(hexfill(x) == 'IMG' for x in _desc(n))


def vis_children(n):
    return [c for c in (n.get('children') or []) if c.get('visible', True)
            and (c.get('absoluteBoundingBox') or {}).get('width', 0) > 0.5]


def child_conts(n):
    return sum(1 for c in vis_children(n) if c.get('type') in CONT and len(vis_children(c)) >= 2)


def cluster_fill(n):
    best = None; ba = -1
    for x in _desc(n):
        f = hexfill(x); bb = x.get('absoluteBoundingBox')
        if f and f.startswith('#') and bb:
            a = bb['width'] * bb['height']
            if a > ba: ba = a; best = f
    return best


def cluster_tcolor(n):
    for x in _desc(n):
        if x.get('type') == 'TEXT':
            c = hexfill(x)
            if c and c.startswith('#'): return c
    return None


def leaf_type(n, x, y, w, h):
    t = n.get('type')
    if t == 'TEXT': return '文本'
    f = hexfill(n)
    img = (f == 'IMG') or has_img(n)
    if t == 'RECTANGLE' and f and f.startswith('#') and h <= 2.6 and w >= 22:
        return '数值条'
    if img:
        if w >= 85 and h >= 85: return '背景槽'
        if h >= 35 and h > w: return '立绘槽'
        return '图标槽'
    if w >= 85 and h >= 85: return '背景槽'
    if t in ('RECTANGLE', 'FRAME') and f and f.startswith('#') and w >= 35 and h >= 6:
        return '面板'
    if w <= 18 and h <= 18: return '图标槽'
    return '装饰'


def dispname(name, typ, txts):
    if CJK.search(name) and not GENERIC.match(name): return name[:12]
    if txts: return txts[0][:10]
    return {'背景槽': '背景', '图标槽': '图标', '立绘槽': '立绘', '装饰': '装饰',
            '面板': '面板', '按钮': '按钮', '文本': '文本', '数值条': '条',
            '容器': '容器'}.get(typ, '元素')


def is_vec_cluster(n):
    """纯矢量簇:有矢量后代、无有内容的文字后代 → 整簇折叠成一张图,不递归内部"""
    has_vec = any(x.get('type') in VEC for x in _desc(n))
    has_txt = any(x.get('type') == 'TEXT' and (x.get('characters') or '').strip()
                  for x in _desc(n))
    return has_vec and not has_txt


def _lum(hexc):
    """颜色亮度(0-255),用于判断对比/取对比字色"""
    try:
        h = hexc.lstrip('#'); r = int(h[0:2], 16); g = int(h[2:4], 16); b = int(h[4:6], 16)
        return 0.299 * r + 0.587 * g + 0.114 * b
    except Exception:
        return 128


def _low_contrast(a, b):
    return abs(_lum(a) - _lum(b)) < 40


def _contrast_ink(fill):
    """给定底色 → 取可见的字色(深底白字 / 浅底深字)"""
    return '#ffffff' if _lum(fill) < 140 else '#222222'


def _rgba(c, op=1.0):
    """figma 颜色 {r,g,b,a}(0-1)→ CSS rgba()。保留透明度(描边/阴影常用半透明)。"""
    r, g, b = [int(round((c.get(k, 0)) * 255)) for k in 'rgb']
    a = round(c.get('a', 1) * op, 3)
    return 'rgba(%d,%d,%d,%s)' % (r, g, b, a)


def style_of(n):
    """提取 figma 节点的形状/描边/阴影/字体样式 → sidecar 字段(全可选,缺省空)。
    与 figma_to_html.py 同源,确保 harness(render.js)与氛围稿(tree.html)样式一致。
    返回 dict(radius, border, shadow, font)。font 仅 TEXT 有(dict),否则 None。
    旋转(relativeTransform)暂不导出:本批 figma 无需旋转的元素,且旋转需配合非 AABB 几何,留作后续。"""
    typ = n.get('type')
    out = dict(radius='', border='', shadow='', font=None)
    # ── 圆角 ──
    rc = n.get('rectangleCornerRadii')
    if rc:
        out['radius'] = ' '.join('%dpx' % round(v) for v in rc)
    else:
        cr = n.get('cornerRadius')
        if cr:
            out['radius'] = '%dpx' % round(cr)
    if typ == 'ELLIPSE':
        out['radius'] = '50%'
    # ── 描边 / 阴影 ──
    st = n.get('strokes') or []
    sw = n.get('strokeWeight')
    has_stroke = bool(st and st[0].get('visible', True) and sw and st[0].get('color'))
    shadows = []
    for ef in n.get('effects') or []:
        if not ef.get('visible', True):
            continue
        if ef.get('type') == 'DROP_SHADOW':
            o = ef.get('offset', {'x': 0, 'y': 0}); r = ef.get('radius', 0)
            shadows.append('%.0fpx %.0fpx %.0fpx %s' % (
                o.get('x', 0), o.get('y', 0), r,
                _rgba(ef.get('color', {'r': 0, 'g': 0, 'b': 0, 'a': .3}))))
    if shadows:
        out['shadow'] = ', '.join(shadows)
    # ── 字体(仅 TEXT)──
    if typ == 'TEXT':
        s = n.get('style', {})
        lh = s.get('lineHeightPx')
        out['font'] = dict(
            size=round(s.get('fontSize', 14), 1),
            weight=s.get('fontWeight', 400),
            lh=(round(lh) if lh else 0),
            align=s.get('textAlignHorizontal', 'LEFT').lower(),
            valign=s.get('textAlignVertical', 'TOP').lower(),
            ls=round(s.get('letterSpacing', 0), 2),
        )
        # 文本描边 → 字形轮廓(text-stroke),不画矩形 border
        if has_stroke:
            out['font']['stroke'] = '%.1fpx %s' % (sw, _rgba(st[0]['color'], st[0].get('opacity', 1)))
    elif has_stroke:
        out['border'] = '%.1fpx solid %s' % (sw, _rgba(st[0]['color'], st[0].get('opacity', 1)))
    return out


# ---- 核心纯函数 ----

def build_dsl(doc, frame_id, NN, screen_name, asset_prefix=None,
              meta=None, brand='figma', file_key='', capture_date='', prefix='screen'):
    """Figma document 节点树 -> (md_text, sidecar_dict)，不做任何文件 IO。

    参数:
        doc         nodes.json 里 d['nodes'][frame_id]['document'] 那棵树
        frame_id    帧节点 ID(写入 sidecar)
        NN          两位序号字符串,如 '15'
        screen_name 屏名,如 '登录主界面'
        asset_prefix 原图路径前缀,默认 '_assets/s<NN>'
    返回:
        (md_text, sidecar_dict)
        sidecar_dict = {"frame": frame_id, "fw": int, "fh": int,
                        "els": [{id,node,ty,x,y,w,h,z,container,parent,img,shape,text,skin,ink,
                                 radius,border,shadow,font}, ...]}
          radius 圆角(CSS, 如 '37px' / '8px 8px 0 0' / '50%')  border 描边('4.0px solid rgba(..)')
          shadow 阴影(box-shadow 值)  font TEXT 字体 dict{size,weight,lh,align,valign,ls[,stroke]} 否则 None
    """
    if asset_prefix is None:
        asset_prefix = '_assets/s%s' % NN
    # ---- 每次调用独立的可变状态 ----
    used = set()
    lines = []
    skins = []
    NMETA = []
    yuantu = []

    FB = doc['absoluteBoundingBox']
    FX, FY, FW, FH = FB['x'], FB['y'], FB['width'], FB['height']

    def rel(bb):
        return ((bb['x'] - FX) / FW * 100, (bb['y'] - FY) / FH * 100,
                bb['width'] / FW * 100, bb['height'] / FH * 100)

    def clamp(x, y, w, h):
        x2 = min(x + w, 100.0); y2 = min(y + h, 100.0)
        x = max(x, 0.0); y = max(y, 0.0)
        return round(x, 1), round(y, 1), round(max(0, x2 - x), 1), round(max(0, y2 - y), 1)

    def rel_px(bb, pax, pay):
        return (round(bb['x'] - pax, 1), round(bb['y'] - pay, 1),
                round(bb['width'], 1), round(bb['height'], 1))

    def mkid(name, typ, txts):
        cand = ''
        if CJK.search(name) and not GENERIC.match(name): cand = name
        elif txts: cand = txts[0]
        else: cand = typ
        cand = re.sub(r'[^0-9A-Za-z一-鿿]+', '', cand)[:8] or 'n'
        out = cand; k = 1
        while out in used: k += 1; out = cand + str(k)
        used.add(out)
        return out

    def emit(n, depth, pax, pay, parent_id=""):
        if not n.get('visible', True): return
        if (n.get('opacity', 1) or 1) <= 0.01: return
        bb = n.get('absoluteBoundingBox')
        if not bb or bb['width'] <= 0.5 or bb['height'] <= 0.5: return
        if depth == 0:
            ff = hexfill(n)
            if ff:
                bgw = float(round(FW)); bgh = float(round(FH))
                lines.append((0, '背景', 'bg', '背景槽', 0.0, 0.0, bgw, bgh, 1, None, ''))
                used.add('bg')
                bg_skin = (ff if (ff and str(ff).startswith('#')) else '')
                bg_img = ''
                if ff == 'IMG':
                    bg_img = '%s/bg.png' % asset_prefix
                    yuantu.append(('bg', bg_img))
                NMETA.append(dict(id='bg', node='', ty='背景槽', x=0.0, y=0.0, w=bgw, h=bgh, z=1, container=False, parent="",
                                  img=bg_img, shape='', text='', skin=bg_skin, ink='',
                                  radius='', border='', shadow='', font=None))
                if ff.startswith('#'): skins.append(('bg', ff, None))
            for c in n.get('children') or []: emit(c, 1, FX, FY, "")
            return
        typ = n.get('type'); txts = texts_of(n)
        x, y, w, h = clamp(*rel(bb))          # 百分比，给启发式用
        if w <= 0.15 or h <= 0.15: return
        pxx, pxy, pxw, pxh = rel_px(bb, pax, pay)  # 父相对像素，给输出用
        # INSTANCE = 设计好的组件:整体渲成一张图(纹理/文字已烘进导出 PNG),不拆解内部
        if typ == 'INSTANCE':
            nm = n.get('name', '')
            if w >= 85 and h >= 85: lt = '背景槽'
            elif h >= 35 and h > w: lt = '立绘槽'
            else: lt = '图标槽'
            idv = mkid(nm, lt, txts)
            base = n['id'][1:].split(';')[0] if (n['id'].startswith('I') and ';' in n['id']) else n['id']
            nm_img = '%s/n%s.png' % (asset_prefix, base.replace(':', '_'))
            yuantu.append((idv, nm_img))
            z = min(3 + depth, 8)
            text = re.sub(r'\s+', ' ', ' '.join(txts))[:48].replace('"', "'")
            lines.append((depth - 1, dispname(nm, lt, txts), idv, lt, pxx, pxy, pxw, pxh, z, None, text))
            NMETA.append(dict(id=idv, node=n['id'], ty=lt, x=pxx, y=pxy, w=pxw, h=pxh, z=z, container=False,
                              parent=parent_id, img=nm_img, shape='', text=(text or ''), skin='', ink='',
                              **style_of(n)))
            return  # 不递归实例内部
        is_container = (typ in CONT) and (len(vis_children(n)) >= 1) and (not is_vec_cluster(n))
        if is_container:
            lt = '面板' if (w >= 45 and h >= 20) else '容器'  # 仍用百分比 w/h
            idv = mkid(n.get('name', ''), lt, txts)
            z = min(3 + depth, 8)
            lines.append((depth - 1, dispname(n.get('name', ''), lt, txts), idv, lt, pxx, pxy, pxw, pxh, z, None, ''))
            f = cluster_fill(n); tc = cluster_tcolor(n)
            cont_skin = (f if (f and f.startswith('#')) else '')
            cont_ink = (tc or '')
            NMETA.append(dict(id=idv, node=n['id'], ty=lt, x=pxx, y=pxy, w=pxw, h=pxh, z=z, container=True, parent=parent_id,
                              img='', shape='', text='', skin=cont_skin, ink=cont_ink,
                              **style_of(n)))
            if f and f.startswith('#'): skins.append((idv, f, tc))
            for c in n.get('children') or []: emit(c, depth + 1, bb['x'], bb['y'], idv)
        else:
            lt = leaf_type(n, x, y, w, h)     # 传百分比 x/y/w/h，启发式不变
            nm = n.get('name', '')
            if w >= 85 and h >= 85 and lt in ('装饰', '面板', '背景槽'): lt = '背景槽'  # 仍用百分比
            if BTN.search(nm + ' ' + ' '.join(txts)) and lt in ('装饰', '文本', '图标槽', '面板'):
                lt = '按钮'
            idv = mkid(nm, lt, txts)
            is_bg = (lt == '背景槽')
            z = 1 if is_bg else min(3 + depth, 8)
            if lt == '装饰' and w * h >= 2500: z = 2   # 仍用百分比 w/h
            if lt == '按钮': z = max(z, 6)
            shape = '圆' if (typ == 'ELLIPSE' or re.search(r'圆|circle|头像|avatar', nm, re.I)) else None
            text = re.sub(r'\s+', ' ', ' '.join(txts))[:48].replace('"', "'")
            lines.append((depth - 1, dispname(nm, lt, txts), idv, lt, pxx, pxy, pxw, pxh, z, shape, text))
            # 原图：美术槽或图片填充节点
            is_art = lt in ('图标槽', '立绘槽', '背景槽')
            has_image = (hexfill(n) == 'IMG') or has_img(n)
            if is_art or has_image:
                # 实例复合 id(I<实例>;<组件内部>)→ 取基础实例 id,对齐已导出素材命名(figma_to_html 用基础 id)
                _nid = n['id']
                if _nid.startswith('I') and ';' in _nid:
                    _nid = _nid[1:].split(';')[0]
                nm_img = '%s/n%s.png' % (asset_prefix, _nid.replace(':', '_').replace(';', '__'))
                yuantu.append((idv, nm_img))
            else:
                nm_img = ''
            # 皮肤填充
            el_fill, el_ink = '', ''
            if lt == '文本':
                # 文本元素:无底色,只取文字色(避免 skin==ink 渲成同色块、字看不见)
                tc = cluster_tcolor(n) or (hexfill(n) if typ == 'TEXT' else None)
                if tc and tc.startswith('#'): el_ink = tc
                # 不进 fill-skins:文本不画底色
            elif lt not in ('图标槽', '立绘槽', '装饰', '背景槽'):
                f = hexfill(n) if typ != 'TEXT' else None
                if not (f and f.startswith('#')): f = cluster_fill(n)
                tc = cluster_tcolor(n) or (hexfill(n) if typ == 'TEXT' else None)
                if f and f.startswith('#'):
                    el_fill = f; el_ink = tc or ''
                    # 按钮:字色缺失/与底色同色或低对比 → 取对比字色,保证文字可见
                    if lt == '按钮' and (not el_ink or _low_contrast(el_fill, el_ink)):
                        el_ink = _contrast_ink(el_fill)
                    skins.append((idv, el_fill, el_ink))
            NMETA.append(dict(id=idv, node=n['id'], ty=lt, x=pxx, y=pxy, w=pxw, h=pxh, z=z, container=False, parent=parent_id,
                              img=nm_img, shape=(shape or ''), text=(text or ''), skin=el_fill, ink=el_ink,
                              **style_of(n)))

    emit(doc, 0, 0, 0, "")

    # ---- 组装 DSL 文本 ----
    m = (meta if meta is not None else META).get(NN, {})
    o = io.StringIO()
    o.write('# %s-%s · %s · %s\n\n' % (prefix, NN, brand, screen_name))
    o.write('> 用途: %s\n' % m.get('u', '(待补充)'))
    o.write('> 布局模式: %s\n' % m.get('l', '(待补充)'))
    o.write('> 标签: %s\n' % m.get('t', '(待补充)'))
    o.write('> 来源: %s / %s / Figma:%s#%s (节点树自动转写)\n'
            % (brand, capture_date or datetime.date.today().isoformat(),
               file_key or FILE_KEY or '<fileKey>', frame_id))
    o.write('> 类型: 屏\n')
    o.write('> 尺寸: %d×%d (竖版;几何=父相对像素,原点左上)\n' % (round(FW), round(FH)))
    o.write('> 坐标系: 父相对px\n\n')
    o.write('## Layout (元素 :id [类型] @{x y w h, px} z=层 形= [态] "文本")\n\n```\n')
    for depth, name, idv, lt, x, y, w, h, z, shape, text in lines:
        ind = '  ' * depth
        seg = '%-12s :%-9s [%s] @{%s %s %s %s} z=%d' % (name, idv, lt, x, y, w, h, z)
        if shape: seg += ' 形=%s' % shape
        if text: seg += ' "%s"' % text
        o.write(ind + seg + '\n')
    o.write('```\n\n')
    o.write('## 皮肤\n\n')
    seen = set()
    for idv, f, tc in skins:
        if idv in seen: continue
        seen.add(idv)
        o.write('%s  %s%s\n' % (idv, f, ' / ' + tc if tc else ''))
    if yuantu:
        o.write('\n## 原图\n\n')
        seen2 = set()
        for idv2, pth in yuantu:
            if idv2 in seen2: continue
            seen2.add(idv2)
            o.write('%s  %s\n' % (idv2, pth))
    pts = m.get('p')
    if pts:
        o.write('\n## 设计点评 (检索面)\n\n')
        for x in pts: o.write('- %s\n' % x)

    md_text = o.getvalue()
    sidecar_dict = dict(frame=frame_id, fw=round(FW), fh=round(FH), els=NMETA)
    return md_text, sidecar_dict


# ---- CLI 入口(薄壳,调 build_dsl) ----

if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    args = sys.argv[1:]
    opts = {'prefix': 'screen', 'brand': 'figma', 'file-key': '', 'meta': ''}
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith('--'):
            k = a[2:]
            if k not in opts:
                raise SystemExit('未知选项: %s' % a)
            opts[k] = args[i + 1]; i += 2
        else:
            pos.append(a); i += 1
    if len(pos) < 5:
        raise SystemExit(__doc__)
    nodes_json, frame_id, NN, screen_name, outdir = pos[:5]
    meta = None
    if opts['meta']:
        meta = {k: v for k, v in json.load(open(opts['meta'], encoding='utf-8')).items()
                if not k.startswith('_')}
    d = json.load(open(nodes_json, encoding='utf-8'))
    doc = d['nodes'][frame_id]['document']
    md_text, sidecar_dict = build_dsl(doc, frame_id, NN, screen_name,
                                      meta=meta, brand=opts['brand'],
                                      file_key=opts['file-key'], prefix=opts['prefix'])
    stem = '%s/%s-%s' % (outdir, opts['prefix'], NN)
    open(stem + '.md', 'w', encoding='utf-8').write(md_text)
    json.dump(sidecar_dict, open(stem + '.nodes.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    n_lines = sum(1 for ln in md_text.splitlines() if '@{' in ln)
    n_skins = len(set(e['id'] for e in sidecar_dict['els']))
    print('wrote %s elements, %s skins -> %s.md (+nodes.json)' % (n_lines, n_skins, stem))

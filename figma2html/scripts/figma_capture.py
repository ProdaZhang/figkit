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
  python figma_capture.py <nodes.json> <frameId> <sNN> <assetDir> <assetRelPrefix> <out_basepath>
产物:
  <out_basepath>.ui.json   全保真节点记录(render.js / aigd 消费)
  <out_basepath>.tree.html 高保真静态预览(等价旧 tree.html)
"""
import sys, json, io, os, math, html

VEC = {'VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'LINE', 'REGULAR_POLYGON'}


def col(c, opacity=1.0):
    a = round(c.get('a', 1) * opacity, 3)
    return 'rgba(%d,%d,%d,%s)' % (round(c['r'] * 255), round(c['g'] * 255), round(c['b'] * 255), a)


def solid(fills):
    for f in fills or []:
        if f.get('visible', True) and f.get('type') == 'SOLID':
            return col(f['color'], f.get('opacity', 1))
    return None


def gradient_css(f):
    stops = f.get('gradientStops') or []
    cs = ', '.join('%s %.1f%%' % (col(s['color']), s['position'] * 100) for s in stops)
    h = f.get('gradientHandlePositions') or []
    if f['type'] == 'GRADIENT_RADIAL':
        return 'radial-gradient(%s)' % cs
    if len(h) >= 2:
        dx = h[1]['x'] - h[0]['x']; dy = h[1]['y'] - h[0]['y']
        ang = (math.degrees(math.atan2(dx, -dy))) % 360   # CSS:0deg=向上,y朝下
    else:
        ang = 180
    return 'linear-gradient(%.1fdeg, %s)' % (ang, cs)


def img_fill(node, asset_dir, asset_rel, missing):
    for f in node.get('fills') or []:
        if f.get('visible', True) and f.get('type', '').startswith('IMAGE'):
            sm = f.get('scaleMode', 'FILL')
            size = {'FILL': 'cover', 'FIT': 'contain', 'STRETCH': '100% 100%', 'TILE': 'auto'}.get(sm, 'cover')
            # 候选名:优先 <imageRef>.png(图片填充天然键,跨屏可复用、可直接喂 figma 导出),
            # 回退节点 id 名 n<id>.png(向后兼容旧素材)
            cands = []
            ref = f.get('imageRef')
            if ref:
                cands.append(ref + '.png')
            cands.append('n' + node['id'].replace(':', '_').replace(';', '__') + '.png')
            for fn in cands:
                if os.path.exists(os.path.join(asset_dir, fn)):
                    return '%s/%s' % (asset_rel, fn), size
            missing.append((node['id'], node.get('name', ''), 'IMG'))
            return None, None
    return None, None


def vec_asset(node, asset_dir, asset_rel, missing):
    fn = 'n' + node['id'].replace(':', '_').replace(';', '__') + '.png'
    if os.path.exists(os.path.join(asset_dir, fn)):
        return '%s/%s' % (asset_rel, fn)
    missing.append((node['id'], node.get('name', ''), node.get('type')))
    return None


def scan(n):
    ht = (n.get('type') == 'TEXT' and (n.get('characters', '') or '').strip() != '')
    hv = n.get('type') in VEC
    for c in n.get('children') or []:
        a, b = scan(c); ht = ht or a; hv = hv or b
    return ht, hv


def needs_image(n):
    ht, hv = scan(n)
    return hv and not ht        # 含真矢量且无文字 -> 整簇折叠成一张图


def vector_leaf_count(n):
    """簇内纯矢量叶子数量(判断是否密集装饰,密集的缺图也不展开以免爆炸)。"""
    kids = [c for c in (n.get('children') or []) if c.get('visible', True)]
    if not kids:
        return 1 if n.get('type') in VEC else 0
    return sum(vector_leaf_count(c) for c in kids)


def has_renderable_shape(n):
    """簇内是否含可用 div 渲染的形状/文字(矩形/椭圆带可见填充、或文字)。
    有则缺图时值得展开(渲染这些形状),无则是纯矢量、保持折叠。"""
    if n.get('type') == 'TEXT':
        return True
    if n.get('type') not in VEC and n.get('type') not in ('GROUP', 'FRAME', 'COMPONENT', 'INSTANCE', 'SECTION'):
        if any(f.get('visible', True) for f in (n.get('fills') or [])):
            return True
    return any(has_renderable_shape(c) for c in (n.get('children') or []))


def radius(node):
    rc = node.get('rectangleCornerRadii')
    if rc:
        return ' '.join('%dpx' % round(v) for v in rc)
    cr = node.get('cornerRadius')
    if cr:
        return '%dpx' % round(cr)
    return None


def child_radius_for_shadow(node):
    """节点自身无圆角但带 DROP_SHADOW 时(如按钮实例,圆角在子矩形上)，
    取铺满它的圆角子矩形的圆角,让 box-shadow 跟随圆角形状而非方框。"""
    bb = node.get('absoluteBoundingBox') or {}
    nw, nh = bb.get('width', 0), bb.get('height', 0)
    if nw <= 0 or nh <= 0:
        return None
    for c in node.get('children') or []:
        cb = c.get('absoluteBoundingBox') or {}
        if abs(cb.get('width', 0) - nw) <= 2 and abs(cb.get('height', 0) - nh) <= 2:
            r = radius(c)
            if r:
                return r
    return None


def capture(root, asset_dir, asset_rel):
    """root = d['nodes'][frame_id]['document'];返回 (cap_dict, missing[])。"""
    FB = root['absoluteBoundingBox']
    FX, FY = FB['x'], FB['y']
    SW, SH = round(FB['width']), round(FB['height'])
    missing = []
    records = []
    order = [0]

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

    def emit(node, parent_id):
        if not node.get('visible', True):
            return
        bb = node.get('absoluteBoundingBox') or {}
        if not bb or bb.get('width', 0) <= 0 or bb.get('height', 0) <= 0:
            for ch in node.get('children') or []:
                emit(ch, parent_id)
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
                    fill='', img=u, imgSize='contain', text=None, vec=True))
                return
            # 缺图:仅当簇内有可渲染形状且矢量叶子少(≤4)才展开渲染形状子;
            # 密集纯矢量装饰(如按钮点状纹理)保持单个透明占位,避免爆几百个 div。
            if not (has_renderable_shape(node) and vector_leaf_count(node) <= 4):
                order[0] += 1
                ax, ay = bb.get('x', 0) - FX, bb.get('y', 0) - FY
                records.append(dict(
                    id=node['id'], name=node.get('name', ''), type=typ, parent=parent_id,
                    x=round(ax, 1), y=round(ay, 1), w=round(bb.get('width', 0), 1), h=round(bb.get('height', 0), 1),
                    z=order[0], rot=0, opacity=round(node.get('opacity', 1), 3),
                    radius='', border='', shadow='', blur='',
                    fill='', img='', imgSize='', text=None, vec=True))
                return
            # else: 展开 → 落到下方普通容器/叶子逻辑(递归子节点)
        order[0] += 1
        rec = dict(
            id=node['id'], name=node.get('name', ''), type=typ, parent=parent_id,
            x=round(x, 1), y=round(y, 1), w=round(w, 1), h=round(h, 1),
            z=order[0], rot=(round(rot, 2) if abs(rot) > 0.5 else 0),
            opacity=round(node.get('opacity', 1), 3),
            radius='', border='', shadow='', blur='', fill='', img='', imgSize='', text=None, vec=False)
        rad = radius(node)
        if rad:
            rec['radius'] = rad
        if typ == 'ELLIPSE':
            rec['radius'] = '50%'
        st = node.get('strokes') or []
        has_stroke = bool(st and st[0].get('visible', True) and node.get('strokeWeight') and st[0].get('color'))
        if has_stroke and typ != 'TEXT':
            rec['border'] = '%.1fpx solid %s' % (node['strokeWeight'], col(st[0]['color'], st[0].get('opacity', 1)))
        shadows = []
        for ef in node.get('effects') or []:
            if not ef.get('visible', True):
                continue
            o = ef.get('offset', {'x': 0, 'y': 0}); r = ef.get('radius', 0)
            if ef['type'] == 'DROP_SHADOW':
                shadows.append('%.0fpx %.0fpx %.0fpx %s' % (
                    o.get('x', 0), o.get('y', 0), r, col(ef.get('color', {'r': 0, 'g': 0, 'b': 0, 'a': .3}))))
            elif ef['type'] == 'LAYER_BLUR':
                rec['blur'] = 'blur(%.0fpx)' % r
        if shadows:
            rec['shadow'] = ', '.join(shadows)
        # 阴影方框修正:自身无圆角但有阴影 → 继承铺满圆角子的圆角(阴影跟随圆角形状)
        if rec['shadow'] and not rec['radius']:
            r2 = child_radius_for_shadow(node)
            if r2:
                rec['radius'] = r2
        if typ == 'TEXT':
            s = node.get('style', {})
            lh = s.get('lineHeightPx')
            ah = {'LEFT': 'flex-start', 'CENTER': 'center', 'RIGHT': 'flex-end',
                  'JUSTIFIED': 'space-between'}.get(s.get('textAlignHorizontal', 'LEFT'), 'flex-start')
            av = {'TOP': 'flex-start', 'CENTER': 'center', 'BOTTOM': 'flex-end'}.get(s.get('textAlignVertical', 'TOP'), 'flex-start')
            t = dict(content=node.get('characters', ''),
                     color=(solid(node.get('fills')) or '#000'),
                     size=round(s.get('fontSize', 14), 1),
                     family=s.get('fontFamily', 'sans-serif'),
                     weight=s.get('fontWeight', 400),
                     lh=(round(lh) if lh else 0),
                     ls=round(s.get('letterSpacing', 0), 2),
                     alignH=ah, alignV=av,
                     textAlign=s.get('textAlignHorizontal', 'LEFT').lower(),
                     stroke='')
            if has_stroke:
                t['stroke'] = '%.1fpx %s' % (node['strokeWeight'], col(st[0]['color'], st[0].get('opacity', 1)))
            rec['text'] = t
            records.append(rec)
            return  # 文本不递归
        iu, isize = img_fill(node, asset_dir, asset_rel, missing)
        if iu:
            rec['img'] = iu; rec['imgSize'] = isize
        else:
            grad = next((f for f in (node.get('fills') or [])
                         if f.get('visible', True) and f.get('type', '').startswith('GRADIENT')), None)
            if grad:
                rec['fill'] = gradient_css(grad)
            elif solid(node.get('fills')):
                rec['fill'] = solid(node.get('fills'))
        records.append(rec)
        for ch in node.get('children') or []:
            emit(ch, node['id'])

    # 帧背景(自身 fill)
    stage_bg = ''
    if any(f.get('type', '').startswith('IMAGE') for f in (root.get('fills') or [])) and \
            os.path.exists(os.path.join(asset_dir, 'bg.png')):
        stage_bg = 'url(%s/bg.png) center/cover no-repeat' % asset_rel
    else:
        iu, isize = img_fill(root, asset_dir, asset_rel, missing)
        if iu:
            stage_bg = 'url(%s) center/%s no-repeat' % (iu, isize)
        elif solid(root.get('fills')):
            stage_bg = solid(root.get('fills'))
        else:
            grad = next((f for f in (root.get('fills') or []) if f.get('type', '').startswith('GRADIENT')), None)
            if grad:
                stage_bg = gradient_css(grad)

    for ch in root.get('children') or []:
        emit(ch, '')
    return dict(frame=root.get('id'), w=SW, h=SH, stageBg=stage_bg, els=records), missing


# ---- 序列化器 ----

# 注意:本函数(出 .tree.html 静态预览)与 runtime/render.js 的 applyRecStyle(出运行时 DOM)
# 是**同一套贴样式映射**。改任一处样式逻辑务必同步另一处,否则"预览 ≠ 运行时"会悄悄漂移。
# 已知**有意**差异(别对齐):图片 url 这里用裸路径(tree.html 与素材同级),render.js 补 '../../'
# (app.html 在 client 目录、深两层)。其余(white-space 单行 nowrap/多行 pre-wrap 等)必须一致。
def rec_to_css(rec):
    sty = ['position:absolute', 'left:%.1fpx' % rec['x'], 'top:%.1fpx' % rec['y'],
           'width:%.1fpx' % rec['w'], 'height:%.1fpx' % rec['h'], 'z-index:%d' % rec['z']]
    if rec['rot']:
        sty.append('transform:rotate(%.2fdeg);transform-origin:center center' % rec['rot'])
    if rec['opacity'] != 1:
        sty.append('opacity:%.3f' % rec['opacity'])
    if rec['radius']:
        sty.append('border-radius:' + rec['radius'])
    if rec['border']:
        sty.append('box-sizing:border-box;border:' + rec['border'])
    if rec['shadow']:
        sty.append('box-shadow:' + rec['shadow'])
    if rec['blur']:
        sty.append('filter:' + rec['blur'])
    inner = ''
    t = rec['text']
    if t:
        # 与 render.js 一致:含 \n 多行用 pre-wrap 保留换行;单行用 nowrap,避免字体回退偏宽撑出文本框被迫折行。
        ws = 'pre-wrap' if '\n' in (t['content'] or '') else 'nowrap'
        sty.append("display:flex;justify-content:%s;align-items:%s;color:%s;font-size:%.1fpx;"
                   "font-family:'%s',sans-serif;font-weight:%s;line-height:%s;letter-spacing:%.2fpx;"
                   "text-align:%s;white-space:%s;overflow:visible" % (
                       t['alignH'], t['alignV'], t['color'], t['size'], t['family'], t['weight'],
                       (str(t['lh']) + 'px' if t['lh'] else 'normal'), t['ls'], t['textAlign'], ws))
        if t['stroke']:
            sty.append('-webkit-text-stroke:%s;paint-order:stroke fill' % t['stroke'])
        inner = html.escape(t['content'])
    elif rec['img']:
        sty.append('background:url(%s) center/%s no-repeat' % (html.escape(rec['img']), rec['imgSize'] or 'cover'))
    elif rec['fill']:
        sty.append('background:' + rec['fill'])
    return '<div title="%s" style="%s">%s</div>' % (
        html.escape(rec['name'] + ' <' + str(rec['type']) + '>'), ';'.join(sty), inner)


def to_html(cap, sNN):
    divs = ''.join(rec_to_css(r) for r in cap['els'])
    bg = ('background:' + cap['stageBg']) if cap['stageBg'] else ''
    return ('<!doctype html><html><head><meta charset="utf-8"><title>%s·Figma树高保真还原</title>\n'
            '<style>body{margin:0;background:#2b2b33;display:flex;justify-content:center;padding:14px}\n'
            ' .stage{position:relative;width:%dpx;height:%dpx;%s;box-shadow:0 4px 24px #000;overflow:hidden}\n'
            ' .stage div{box-sizing:border-box}</style></head>\n'
            '<body><div class="stage">%s</div></body></html>' % (sNN, cap['w'], cap['h'], bg, divs))


if __name__ == '__main__':
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

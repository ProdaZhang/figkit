# -*- coding: utf-8 -*-
"""ui_to_uespec.py — figma2html IR(.ui.json / flow.json)→ Unreal 强类型 uespec.json 预处理器。

用法:
    python3 ui_to_uespec.py <cap.ui.json> <outdir>
    python3 ui_to_uespec.py <cap.ui.json> <flow.json> <outdir>

产物:
    <stem>.uespec.json          — 单屏强类型规格(stem = ui.json 文件名去掉 .ui.json)
    flow.uespec.json            — 给了 flow.json 时;同时把 flow.caps 引用的**所有**屏一并转出
                                  (UE 侧要整套 uespec,顺手全转,免得逐屏跑;确定性输出)

职责边界(架构约定):**所有 CSS 风格字符串在这里解析成数值/结构**;C++ 运行时零解析,
只按 uespec 建 Widget。几何照 render.js pass2 语义:localX/localY = 相对父元素(px),
absX/absY 保留(弹窗抽子树时根用 abs 摆放)。

校验:flow 里引用的 figma node id(events.el / modals.roots / modals.panel /
list.container / bindings.checkbox.el)必须存在于对应/任一 cap,坏引用打印错误并 exit 2。

纯标准库、确定性输出(UTF-8 无 BOM、\n 换行、固定键序)。
"""
import json
import os
import re
import sys

# motion.py 是 figma2html/scripts/motion.py 的**逐字节镜像**(skill 必须自足、可单独安装,
# 跨目录 import 装成插件就断)。两份漂了由 tools/conformance 的 byte-parity 用例当场红。
# 显式把本文件所在目录入 path:当本模块**被测试 import**(而不是当脚本跑)时,
# sys.path[0] 是测试目录,裸 `import motion` 会 ModuleNotFoundError。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import motion


# ── 数值/颜色 ────────────────────────────────────────────────────────────────

def _num(v):
    """浮点归一:整数值退成 int,其余保留 float(输出确定性)。"""
    f = float(v)
    return int(f) if f.is_integer() else f


def parse_color(s):
    """'rgba(219,208,184,1)' / 'rgb(1,2,3)' / '#000' / '#a1b2c3' → [r,g,b,a](0-255,a 0-1)。"""
    s = s.strip()
    m = re.match(r'rgba?\(([^)]*)\)$', s)
    if m:
        parts = [p.strip() for p in m.group(1).split(',')]
        if len(parts) < 3:
            raise ValueError('颜色分量不足: %r' % s)
        r, g, b = (_num(p) for p in parts[:3])
        a = _num(parts[3]) if len(parts) > 3 else 1
        return [r, g, b, a]
    m = re.match(r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$', s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1]
    raise ValueError('无法解析颜色: %r' % s)


def _split_top(s):
    """按顶层逗号切分(忽略括号内逗号,rgba(...) 安全)。"""
    out, depth, cur = [], 0, ''
    for ch in s:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# ── 填充(纯色/线性/径向渐变)─────────────────────────────────────────────────

def _stops(parts):
    """['rgba(..) 0.0%', 'rgba(..) 100.0%'] → [{'rgba':[...],'pos':0.0}, ...];缺 pos 均匀分布。"""
    stops = []
    n = len(parts)
    for i, p in enumerate(parts):
        m = re.match(r'(rgba?\([^)]*\)|#[0-9a-fA-F]+)(?:\s+(-?[\d.]+)%)?\s*$', p)
        if not m:
            raise ValueError('无法解析渐变停靠: %r' % p)
        if m.group(2) is not None:
            pos = _num(round(float(m.group(2)) / 100.0, 4))
        else:
            pos = _num(round(i / (n - 1), 4)) if n > 1 else 0
        stops.append({'rgba': parse_color(m.group(1)), 'pos': pos})
    return stops


def parse_fill(s):
    """fill 字符串 → None | {'type':'solid'|'linear'|'radial', ...}。"""
    if not s:
        return None
    s = s.strip()
    if s.startswith('linear-gradient(') and s.endswith(')'):
        parts = _split_top(s[len('linear-gradient('):-1])
        ang = 180
        if parts and parts[0].endswith('deg'):
            ang = _num(parts[0][:-3])
            parts = parts[1:]
        return {'type': 'linear', 'angleDeg': ang, 'stops': _stops(parts)}
    if s.startswith('radial-gradient(') and s.endswith(')'):
        parts = _split_top(s[len('radial-gradient('):-1])
        # 防御:形状前缀(circle at ..)不含颜色则丢弃(capture 不产,兼容手工 IR)
        if parts and 'rgb' not in parts[0] and '#' not in parts[0]:
            parts = parts[1:]
        return {'type': 'radial', 'stops': _stops(parts)}
    return {'type': 'solid', 'rgba': parse_color(s)}


# ── 圆角/描边/阴影/模糊/文字描边 ─────────────────────────────────────────────

def parse_radius(s, w, h):
    """radius 字符串 → None | [tl,tr,br,bl](px 浮点)。
    支持 CSS 缩写(1/2/3/4 值)与 '50%'(椭圆:取 min(w,h)/2,UE RoundedBox 圆角是标量,近似)。"""
    if not s:
        return None
    toks = s.split()
    vals = []
    for t in toks:
        if t.endswith('%'):
            vals.append(_num(round(min(w, h) * float(t[:-1]) / 100.0, 2)))
        elif t.endswith('px'):
            vals.append(_num(t[:-2]))
        else:
            vals.append(_num(t))
    if len(vals) == 1:
        vals = vals * 4
    elif len(vals) == 2:
        vals = [vals[0], vals[1], vals[0], vals[1]]
    elif len(vals) == 3:
        vals = [vals[0], vals[1], vals[2], vals[1]]
    return vals[:4]


def parse_border(s):
    """'4.0px solid rgba(...)' → None | {'width':4,'rgba':[...]}。"""
    if not s:
        return None
    m = re.match(r'(-?[\d.]+)px\s+solid\s+(.+)$', s.strip())
    if not m:
        raise ValueError('无法解析 border: %r' % s)
    return {'width': _num(m.group(1)), 'rgba': parse_color(m.group(2))}


def parse_shadow(s):
    """'0px 4px 0px rgba(..)[, ...]' → [{'dx','dy','blur','rgba'}, ...](无阴影 → [])。
    capture 产 3 长度(dx dy blur、无 spread);防御性接受 2-4 长度,spread 丢弃。"""
    if not s:
        return []
    out = []
    for part in _split_top(s):
        m = re.match(
            r'(-?[\d.]+)px\s+(-?[\d.]+)px(?:\s+(-?[\d.]+)px)?(?:\s+(-?[\d.]+)px)?\s+'
            r'(rgba?\([^)]*\)|#[0-9a-fA-F]+)\s*$', part)
        if not m:
            raise ValueError('无法解析 shadow: %r' % part)
        out.append({'dx': _num(m.group(1)), 'dy': _num(m.group(2)),
                    'blur': _num(m.group(3)) if m.group(3) else 0,
                    'rgba': parse_color(m.group(5))})
    return out


def parse_blur(s):
    """'blur(4px)' → None | {'radius':4}。"""
    if not s:
        return None
    m = re.match(r'blur\((-?[\d.]+)px\)$', s.strip())
    if not m:
        raise ValueError('无法解析 blur: %r' % s)
    return {'radius': _num(m.group(1))}


def parse_text_stroke(s):
    """webkitTextStroke 格式 '2.0px rgba(...)' → None | {'width':2,'rgba':[...]}。"""
    if not s:
        return None
    m = re.match(r'(-?[\d.]+)px\s+(.+)$', s.strip())
    if not m:
        raise ValueError('无法解析 text stroke: %r' % s)
    return {'width': _num(m.group(1)), 'rgba': parse_color(m.group(2))}


# ── 图片 / 帧背景 ────────────────────────────────────────────────────────────

_IMG_MODE = {'': 'cover', 'cover': 'cover', 'contain': 'contain',
             '100% 100%': 'stretch', 'auto': 'tile'}


def parse_img(img, img_size):
    if not img:
        return None
    return {'path': img, 'mode': _IMG_MODE.get(img_size, 'stretch')}


def parse_stage_bg(s):
    """stageBg:'' | 'rgba(..)' | 渐变 css | 'url(path) center/cover no-repeat'。"""
    if not s:
        return None
    s = s.strip()
    m = re.match(r'url\(([^)]+)\)', s)
    if m:
        mode = 'contain' if 'contain' in s else 'cover'
        return {'type': 'image', 'path': m.group(1).strip('\'"'), 'mode': mode}
    return parse_fill(s)


# ── 文字 ─────────────────────────────────────────────────────────────────────

_ALIGN = {'flex-start': 'start', 'center': 'center', 'flex-end': 'end',
          'space-between': 'start'}


def parse_text(t):
    if not t:
        return None
    return {
        'content': t.get('content', ''),
        'rgba': parse_color(t.get('color') or '#000'),
        'size': _num(t.get('size', 14)),
        'weight': int(t.get('weight', 400)),
        'family': t.get('family', 'sans-serif'),
        'lh': _num(t.get('lh', 0)),
        'ls': _num(t.get('ls', 0)),
        'alignH': _ALIGN.get(t.get('alignH', 'flex-start'), 'start'),
        'alignV': _ALIGN.get(t.get('alignV', 'flex-start'), 'start'),
        'textAlign': t.get('textAlign', 'left'),
        'stroke': parse_text_stroke(t.get('stroke', '')),
    }


# ── 单屏转换 ─────────────────────────────────────────────────────────────────

def convert_cap(cap):
    """cap dict(.ui.json)→ uespec dict。几何:localX/localY 照 render.js pass2
    (父存在则减父绝对坐标,否则等于 abs);absX/absY 保留供子树抽取摆放。"""
    els = cap.get('els') or []
    by_id = {e['id']: e for e in els}
    out_els = []
    for e in els:
        p = by_id.get(e.get('parent') or '')
        px = p['x'] if p else 0
        py = p['y'] if p else 0
        w = _num(e.get('w', 0))
        h = _num(e.get('h', 0))
        out_els.append({
            'id': e['id'],
            'name': e.get('name', ''),
            'type': e.get('type', ''),
            'parent': e.get('parent', '') if p else '',
            'absX': _num(e.get('x', 0)),
            'absY': _num(e.get('y', 0)),
            'localX': _num(round(e.get('x', 0) - px, 2)),
            'localY': _num(round(e.get('y', 0) - py, 2)),
            'w': w,
            'h': h,
            'z': int(e.get('z', 0)),
            'rot': _num(e.get('rot', 0)),
            'opacity': _num(e.get('opacity', 1)),
            'radius': parse_radius(e.get('radius', ''), w, h),
            'border': parse_border(e.get('border', '')),
            'shadow': parse_shadow(e.get('shadow', '')),
            'blur': parse_blur(e.get('blur', '')),
            'fill': parse_fill(e.get('fill', '')),
            'img': parse_img(e.get('img', ''), e.get('imgSize', '')),
            'text': parse_text(e.get('text')),
            'vec': bool(e.get('vec', False)),
        })
    return {
        'version': 1,
        'frame': cap.get('frame', ''),
        'w': _num(cap.get('w', 0)),
        'h': _num(cap.get('h', 0)),
        'stageBg': parse_stage_bg(cap.get('stageBg', '')),
        'els': out_els,
    }


# ── flow 转换 + 校验 ─────────────────────────────────────────────────────────

_SPECIAL = re.compile(r'^@(\w+):(\w+)$')


def _norm_target(sel, errors, modals, id_universe):
    m = _SPECIAL.match(str(sel))
    if m:
        kind, modal = m.group(1), m.group(2)
        if kind not in ('any', 'panelOutside'):
            errors.append('未知特殊选择器种类: %r' % sel)
        if modal not in modals:
            errors.append('特殊选择器引用了不存在的 modal: %r' % sel)
        return {'kind': kind, 'modal': modal}
    if sel not in id_universe:
        errors.append('事件引用的 el 不在任何 cap 里: %r' % sel)
    return {'kind': 'node', 'id': str(sel)}


def convert_flow(flow, cap_specs, cap_files):
    """flow dict → (flow_uespec, errors)。cap_specs: 名→uespec dict;cap_files: 名→uespec 文件名。
    校验所有 el 引用;errors 非空时调用方应退出非 0。"""
    errors = []
    id_by_cap = {name: {e['id'] for e in spec['els']} for name, spec in cap_specs.items()}
    id_universe = set().union(*id_by_cap.values()) if id_by_cap else set()

    base = flow.get('base', '')
    if base not in cap_specs:
        errors.append('base 指向不存在的 cap: %r' % base)

    modals = {}
    for name, m in (flow.get('modals') or {}).items():
        cap_name = m.get('cap', '')
        if cap_name not in cap_specs:
            errors.append('modal %r 指向不存在的 cap: %r' % (name, cap_name))
        ids = id_by_cap.get(cap_name, set())
        roots = list(m.get('roots') or [])
        for r in roots:
            if r not in ids:
                errors.append('modal %r 的 root %r 不在 cap %r 里' % (name, r, cap_name))
        panel = m.get('panel')
        if panel is not None and panel not in ids:
            errors.append('modal %r 的 panel %r 不在 cap %r 里' % (name, panel, cap_name))
        modals[name] = {'cap': cap_name, 'roots': roots, 'panel': panel}

    events = []
    for ev in (flow.get('events') or []):
        sels = ev.get('el')
        sels = sels if isinstance(sels, list) else [sels]
        events.append({
            'on': ev.get('on', 'click'),
            'targets': [_norm_target(s, errors, modals, id_universe) for s in sels],
            'guard': list(ev.get('guard') or []),
            'do': ev.get('do', ''),
            'arg': ev.get('arg') if 'arg' in ev else None,
        })

    lst = flow.get('list')
    out_list = None
    if lst:
        modal = lst.get('modal', '')
        if modal not in modals:
            errors.append('list.modal 指向不存在的 modal: %r' % modal)
        container = lst.get('container', '')
        cap_of_modal = modals.get(modal, {}).get('cap', '')
        if container not in id_by_cap.get(cap_of_modal, set()):
            errors.append('list.container %r 不在 modal %r 的 cap 里' % (container, modal))
        out_list = {'modal': modal, 'container': container,
                    'onRowClick': lst.get('onRowClick', '')}

    bindings = {}
    cb = (flow.get('bindings') or {}).get('checkbox')
    if cb:
        el = cb.get('el', '')
        if el not in id_by_cap.get(base, set()):
            errors.append('bindings.checkbox.el %r 不在 base cap 里' % el)
        bindings['checkbox'] = {
            'el': el,
            'flag': cb.get('flag', ''),
            'checkedRgba': parse_color(cb.get('checkedBg', 'rgba(255,255,255,1)')),
            'uncheckedRgba': parse_color(cb.get('uncheckedBg', 'rgba(255,255,255,0.2)')),
            'mark': cb.get('mark', '✓'),
            'markRgba': parse_color(cb.get('markColor', 'rgba(27,76,87,1)')),
        }

    stage = flow.get('stage') or {}
    out = {
        'version': 1,
        'stage': {'w': _num(stage.get('w', 1080)), 'h': _num(stage.get('h', 1920))},
        'caps': {name: cap_files[name] for name in sorted(cap_files)},
        'base': base,
        'modals': modals,
        'state': flow.get('state') or {},
        'events': events,
        'list': out_list,
        'bindings': bindings,
    }
    return out, errors


# ── IO / 主流程 ──────────────────────────────────────────────────────────────

def _load(path):
    with open(path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def _dump(obj, path):
    data = json.dumps(obj, ensure_ascii=False, indent=1) + '\n'
    with open(path, 'wb') as f:
        f.write(data.encode('utf-8'))   # UTF-8 无 BOM、\n 换行 → 逐字节确定


def _stem(p):
    b = os.path.basename(p)
    for suf in ('.ui.json', '.json'):
        if b.endswith(suf):
            return b[:-len(suf)]
    return b


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
    args = argv[1:]
    if len(args) == 2:
        cap_path, flow_path, outdir = args[0], None, args[1]
    elif len(args) == 3:
        cap_path, flow_path, outdir = args
    else:
        print('用法: python3 ui_to_uespec.py <cap.ui.json> [flow.json] <outdir>', file=sys.stderr)
        return 2
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    cap_raw = _load(cap_path)
    guard_or_die(cap_raw, sys, cap_path)  # 畸形 IR → 说清哪儿不对再退,别抛 traceback
    cap_spec = convert_cap(cap_raw)
    _dump(cap_spec, os.path.join(outdir, _stem(cap_path) + '.uespec.json'))

    if not flow_path:
        return 0

    flow = _load(flow_path)
    flow_dir = os.path.dirname(os.path.abspath(flow_path))
    cap_specs, cap_files = {}, {}
    for name, rel in (flow.get('caps') or {}).items():
        p = os.path.join(flow_dir, rel.lstrip('/'))
        if not os.path.exists(p):
            print('[ui_to_uespec] 错误: flow.caps[%r] 文件不存在: %s' % (name, p), file=sys.stderr)
            return 2
        spec = convert_cap(_load(p))
        cap_specs[name] = spec
        cap_files[name] = _stem(p) + '.uespec.json'
        _dump(spec, os.path.join(outdir, cap_files[name]))   # 顺手全转(UE 侧要整套)

    flow_spec, errors = convert_flow(flow, cap_specs, cap_files)
    if errors:
        for e in errors:
            print('[ui_to_uespec] 校验错误: ' + e, file=sys.stderr)
        return 2
    _dump(flow_spec, os.path.join(outdir, 'flow.uespec.json'))

    # 转场缓动 → 采样曲线表。**采样点而不是引擎缓动枚举**:figma 给的是一条具体曲线,
    # UE 的 EEasingFunc 给的是另一套同名不同形的曲线 —— 各家各挑"最像的",同一份 IR
    # 在六个引擎里就是六种手感,而所有测试照样绿。UMG 侧喂 FRichCurve 即可。
    # ⚠️ FigmaFlowComponent 尚未接线,转场目前**不播** —— 已登记在 references/mapping.md。
    data, notes = motion.bake_flow(flow, 'figma2unreal/scripts/ui_to_uespec.py')
    _dump(data, os.path.join(outdir, 'motion.json'))
    for n in notes:
        print('[known-loss] motion: ' + n, file=sys.stderr)
    if data['curves']:
        print('[known-loss] motion: 烘出 %d 条曲线,但 FigmaFlowComponent 还没接线 '
              '—— 转场目前**不播**' % len(data['curves']), file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

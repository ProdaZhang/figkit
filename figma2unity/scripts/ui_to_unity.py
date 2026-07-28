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
import json
import os
import re
import sys

INDENT = "  "


# ── 小工具 ──────────────────────────────────────────────────────────────

def fmt_num(v):
    """数值 → 最短确定性字符串(2.0 → '2',26.5 → '26.5')。"""
    f = float(v)
    if f == int(f):
        return str(int(f))
    return ("%g" % f)


def safe_name(figma_id):
    """UXML name 属性不允许冒号:figma id 的 ':' 统一换 '_'(约定见 mapping.md)。"""
    return str(figma_id).replace(":", "_")


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


TEXT_ALIGN_V = {"flex-start": "upper", "center": "middle", "flex-end": "lower"}
TEXT_ALIGN_H = {"left": "left", "center": "center", "right": "right"}


# ── 转换主体 ────────────────────────────────────────────────────────────

def build_uss_props(el, parent, losses):
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

    if el.get("shadow"):
        losses.append("%s: shadow '%s' 丢弃(USS 无 box-shadow)" % (eid, el["shadow"]))
    if el.get("blur"):
        losses.append("%s: blur '%s' 丢弃(USS 无 filter)" % (eid, el["blur"]))

    text = el.get("text")
    if text:
        props.append(("margin", "0"))    # Label 内建样式带 padding,压平以保几何
        props.append(("padding", "0"))
        props.append(("color", text.get("color", "rgba(0,0,0,1)")))
        props.append(("font-size", fmt_num(text.get("size", 14)) + "px"))
        weight = text.get("weight", 400)
        props.append(("-unity-font-style", "bold" if weight >= 600 else "normal"))
        if weight not in (400, 700):
            losses.append("%s: font-weight %s 近似为 %s(USS 只有 normal/bold)"
                          % (eid, weight, "bold" if weight >= 600 else "normal"))
        av = TEXT_ALIGN_V.get(text.get("alignV", "center"), "middle")
        ah = TEXT_ALIGN_H.get(text.get("textAlign", "center"), "center")
        props.append(("-unity-text-align", av + "-" + ah))
        ls = text.get("ls", 0)
        if ls:
            props.append(("letter-spacing", fmt_num(ls) + "px"))
        # 多行保留换行(normal),单行 nowrap 防字体回退偏宽被迫折行(同 render.js)
        multi = "\n" in str(text.get("content", ""))
        props.append(("white-space", "normal" if multi else "nowrap"))
        props.append(("overflow", "visible"))
        if text.get("lh"):
            losses.append("%s: line-height %spx 丢弃(USS 无 line-height)" % (eid, text["lh"]))
        if text.get("stroke"):
            losses.append("%s: text-stroke '%s' 丢弃(USS 无字形描边)" % (eid, text["stroke"]))
        fam = text.get("family", "")
        if fam:
            losses.append("%s: font-family '%s' 未映射(Unity 需 FontAsset,见 mapping.md)" % (eid, fam))
    elif el.get("img"):
        props.append(("background-image", 'url("%s")' % el["img"]))
        props.append(("background-size", el.get("imgSize") or "cover"))
        props.append(("background-position", "center"))
        props.append(("background-repeat", "no-repeat"))
    elif el.get("fill"):
        fill = el["fill"]
        if "gradient(" in fill:
            c = first_gradient_color(fill)
            if c:
                props.append(("background-color", c))
                losses.append("%s: gradient '%s' 回退为第一停靠色 %s(USS 无渐变)" % (eid, fill, c))
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


def convert(cap, stem):
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
        uss_rules.append(("." + cls, build_uss_props(el, parent, losses)))
        kids = sorted(children.get(el["id"], []), key=sort_key)
        text = el.get("text")
        tag = "ui:Label" if text else "ui:VisualElement"
        attrs = 'name="%s" class="%s"' % (name, cls)
        if text:
            attrs += ' text="%s"' % xml_escape(text.get("content", ""))
        pad = INDENT * depth
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
    uxml.append('<ui:UXML xmlns:ui="UnityEngine.UIElements">')
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
    uxml_str, uss_str, _ = convert(cap, stem)
    os.makedirs(outdir, exist_ok=True)
    uxml_path = os.path.join(outdir, stem + ".uxml")
    uss_path = os.path.join(outdir, stem + ".uss")
    with open(uxml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(uxml_str)
    with open(uss_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(uss_str)
    return uxml_path, uss_path


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
        sys.stderr.write("用法: python3 ui_to_unity.py <cap.ui.json> <outdir>\n")
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
    print("OK %s + %s" % (uxml_path, uss_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

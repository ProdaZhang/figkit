# -*- coding: utf-8 -*-
"""flow_check.py — figma2html 的离线 flow 校验器(纯标准库)。

用法:
    python3 flow_check.py <flow.json> [capDir]      # capDir 缺省 = flow.json 所在目录

**为什么需要它**:README 让人**手写** flow.json,而它整篇是靠 figma node id 互相引用的。
写错一个 id,`assemble.js` 只会在**浏览器 console** 里 warn 一句 —— 得先起服务、打开
devtools、点到那个元素,才发现"点了没反应"。同一类错误在 figma2cocos
是**离线就 exit 2** 当场说清的。这条路是首选入口和 live demo 走的路,反馈却最差,
所以把那份判定搬过来,在打开浏览器之前就拦下。

校验什么(与 figma2cocos/scripts/ui_check.py 同语义):
  1. flow.caps 里每个 .ui.json 存在且能载入;
  2. base → 已声明的 cap;
  3. modals[*].cap 存在;roots / panel 的 id 在该 modal 的 cap 里;
  4. events[].el → base cap;@any:<modal> / @panelOutside:<modal> 只查 modal 名;
     @in:<modal>:<nodeId> 既查 modal 名,也查该节点确实在这个弹窗**抬起来的子树**里;
  5. list.modal 已声明、list.container 在其 cap 里、容器下有 ≥1 个模板行;
  6. bindings.checkbox.el → base cap。

判定逻辑各后端各带一份(skill 必须自足、可单独安装,跨目录 import 装成插件就断),
"各家判定一致"由 tools/conformance 的跨后端用例兜底。

坏引用 → 逐条列明并 exit 2;全绿 → exit 0。
"""
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):      # Windows 老代码页打中文不炸
    sys.stdout.reconfigure(errors="replace")

SEL_RE = re.compile(r"^@(\w+):(\w+)$")      # @any:modal / @panelOutside:modal
# @in:<modal>:<nodeId> —— 弹窗**内部**的元素(v1.1)。节点 id 自带冒号("4:99"),
# 所以 @in: 之后只有第一段是弹窗名,其余整段都是 id。
IN_RE = re.compile(r"^@in:([^:]+):(.+)$")


def load_caps(flow, cap_dir):
    """按 flow.caps 载入各屏 .ui.json → (caps: name->cap, errors)。"""
    caps, errors = {}, []
    for name, rel in (flow.get("caps") or {}).items():
        p = os.path.join(cap_dir, str(rel).lstrip("/\\"))
        if not os.path.isfile(p):
            errors.append("caps[%s]: 文件不存在: %s" % (name, p))
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                caps[name] = json.load(f)
        except Exception as e:
            errors.append("caps[%s]: 载入失败 %s (%s)" % (name, p, e))
    return caps, errors


def ids_of(cap):
    return set(e.get("id") for e in (cap.get("els") or []))


def subtree_ids(cap, roots):
    """roots 及其全部后代的 id —— 与 render.js 的 `subtreeOf` 同一语义。

    `@in:` 只查"在这一屏里"是不够的:cap 是**整帧**,而弹窗只把 roots 那几棵子树抬出来叠加。
    落在 roots 之外的节点,校验能过、运行时却根本不在那一层里 —— 正是最难查的那一类。
    """
    keep = set(roots or [])
    els = cap.get("els") or []
    changed = True
    while changed:
        changed = False
        for e in els:
            if e.get("id") not in keep and e.get("parent") and e.get("parent") in keep:
                keep.add(e.get("id"))
                changed = True
    return keep


def check_flow(flow, caps):
    """校验 flow 对 caps 的全部 id 引用 → 错误列表(空 = 通过)。纯函数,便于内存构造坏 flow 做测试。"""
    errors = []
    modals = flow.get("modals") or {}

    base_name = flow.get("base")
    if base_name not in caps:
        errors.append("base: cap '%s' 未载入/未声明" % base_name)
    base_ids = ids_of(caps.get(base_name, {}))

    modal_ids = {}          # 弹窗名 -> 该弹窗那一屏的全部 id(@in: 选择器要查它)
    for mname, m in modals.items():
        cname = (m or {}).get("cap")
        if cname not in caps:
            errors.append("modals[%s]: cap '%s' 未载入/未声明" % (mname, cname))
            continue
        cid = ids_of(caps[cname])
        modal_ids[mname] = subtree_ids(caps[cname], m.get("roots"))
        for r in (m.get("roots") or []):
            if r not in cid:
                errors.append("modals[%s]: root '%s' 不在 cap '%s' 里" % (mname, r, cname))
        panel = m.get("panel")
        if panel and panel not in cid:
            errors.append("modals[%s]: panel '%s' 不在 cap '%s' 里" % (mname, panel, cname))

    for i, ev in enumerate(flow.get("events") or []):
        sels = ev.get("el")
        sels = sels if isinstance(sels, list) else [sels]
        for sel in sels:
            mi = IN_RE.match(str(sel))
            if mi:
                mname, nid = mi.group(1), mi.group(2)
                if mname not in modals:
                    errors.append("events[%d]: 选择器 '%s' 指向不存在的 modal" % (i, sel))
                elif mname in modal_ids and nid not in modal_ids[mname]:
                    errors.append("events[%d]: '%s' 的 '%s' 不在弹窗 '%s' 抬起来的子树里"
                                  % (i, sel, nid, mname))
                continue
            m2 = SEL_RE.match(str(sel))
            if m2:
                if m2.group(2) not in modals:
                    errors.append("events[%d]: 选择器 '%s' 指向不存在的 modal" % (i, sel))
            elif sel not in base_ids:
                errors.append("events[%d]: el '%s' 不在 base cap 里" % (i, sel))

    L = flow.get("list")
    if L:
        lmodal = L.get("modal")
        if lmodal not in modals:
            errors.append("list: modal '%s' 未在 flow.modals 声明" % lmodal)
        else:
            cname = modals[lmodal].get("cap")
            cap = caps.get(cname)
            if cap is not None:
                container = L.get("container")
                if container not in ids_of(cap):
                    errors.append("list: container '%s' 不在 cap '%s' 里" % (container, cname))
                else:
                    rows = [e for e in cap.get("els") or [] if e.get("parent") == container]
                    if not rows:
                        errors.append("list: 容器 '%s' 下没有模板行"
                                      "(需 ≥1 个 parent==container 的 el)" % container)

    b = (flow.get("bindings") or {}).get("checkbox")
    if b and b.get("el") not in base_ids:
        errors.append("bindings.checkbox: el '%s' 不在 base cap 里" % b.get("el"))

    return errors


def main(argv):
    if len(argv) not in (2, 3):
        sys.stderr.write("用法: python3 flow_check.py <flow.json> [capDir]\n"
                         "  capDir 缺省 = flow.json 所在目录(与 app.html 的相对加载一致)\n")
        return 2
    flow_path = argv[1]
    cap_dir = argv[2] if len(argv) == 3 else os.path.dirname(os.path.abspath(flow_path))
    try:
        with open(flow_path, "r", encoding="utf-8") as f:
            flow = json.load(f)
    except Exception as e:
        sys.stderr.write("[flow-check] 读不了 %s: %s\n" % (flow_path, e))
        return 2

    caps, errors = load_caps(flow, cap_dir)
    errors += check_flow(flow, caps)
    if errors:
        sys.stderr.write("[flow-check] %s 有 %d 处坏引用:\n" % (flow_path, len(errors)))
        for e in errors:
            sys.stderr.write("  - %s\n" % e)
        return 2
    print("[flow-check] OK: %d 屏 / %d 事件,引用全部命中"
          % (len(caps), len(flow.get("events") or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

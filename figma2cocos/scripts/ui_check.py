# -*- coding: utf-8 -*-
"""ui_check.py — figma2cocos 离线校验器(纯标准库)。

用法:
    python3 ui_check.py <flow.json> [capDir]     # capDir 缺省 = flow.json 所在目录

做什么(本机可测的部分,不需要 Cocos):
  1. flow.caps 里每个 .ui.json 文件存在且能 json 载入;
  2. flow 各处引用的 figma node id 在对应 cap 里存在:
     - events[].el      → base cap(assemble.js 的 baseEl 语义:事件元素在底屏上找);
       特殊选择器 @any:<modal> / @panelOutside:<modal> → 只查 modal 名存在;
     - modals[*].roots / panel → 该 modal 的 cap;
     - list.container   → list.modal 对应 cap,且容器下有 ≥1 个模板行(parent==container 的 el);
     - bindings.checkbox.el → base cap;
  3. 输出 assets-manifest.json(全部 img + stageBg url 去重清单,写在 capDir 下),
     供 Cocos 侧照单把图片放进 assets/resources/。

坏引用 → exit 非 0 并逐条列明;全绿 → exit 0。
"""
import json
import os
import re
import sys

# Windows 老代码页控制台打中文/箭头不炸(输出乱码只是显示问题,exit code 不受影响)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

SEL_RE = re.compile(r"^@(\w+):(\w+)$")   # @any:modal / @panelOutside:modal
# @in:<modal>:<nodeId> —— 弹窗**内部**的元素(v1.1)。节点 id 自带冒号("4:99"),
# 所以 @in: 之后只有第一段是弹窗名,其余整段都是 id。
IN_RE = re.compile(r"^@in:([^:]+):(.+)$")
URL_RE = re.compile(r"url\(([^)]+)\)")


# ── 载入 ────────────────────────────────────────────────────────────────

def load_flow(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_caps(flow, cap_dir):
    """按 flow.caps 载入各屏 .ui.json。返回 (caps: name->cap, errors)。"""
    caps, errors = {}, []
    for name, rel in (flow.get("caps") or {}).items():
        p = os.path.join(cap_dir, str(rel).lstrip("/\\"))
        if not os.path.isfile(p):
            errors.append("caps[%s]: 文件不存在: %s" % (name, p))
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                caps[name] = json.load(f)
        except Exception as e:  # json 坏/编码坏
            errors.append("caps[%s]: 载入失败 %s (%s)" % (name, p, e))
    return caps, errors


def ids_of(cap):
    return set(e.get("id") for e in (cap.get("els") or []))


# ── 引用完整性(纯函数,便于测试内存构造坏 flow)────────────────────────

def subtree_ids(cap, roots):
    """roots 及其全部后代的 id —— 与 render.js 的 `subtreeOf` 同一语义。

    `@in:` 只查"在这一屏里"是不够的:cap 是**整帧**,而弹窗只把 roots 那几棵子树抬出来叠加。
    落在 roots 之外的节点,校验能过、运行时却根本不在那一层里。
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
    """校验 flow 对 caps 的全部 id 引用。返回错误列表(空=通过)。"""
    errors = []
    modals = flow.get("modals") or {}

    # base
    base_name = flow.get("base")
    if base_name not in caps:
        errors.append("base: cap '%s' 未载入/未声明" % base_name)
        base_ids = set()
    else:
        base_ids = ids_of(caps[base_name])

    # modals[*].cap / roots / panel
    modal_ids = {}          # 弹窗名 -> 该弹窗抬起来的子树里的全部 id(@in: 要查它)
    for mname, m in modals.items():
        cname = m.get("cap")
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

    # events[].el → base cap;@选择器 → modal 名存在
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

    # list:modal 存在、container 在其 cap、容器下 ≥1 模板行
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
                        errors.append("list: 容器 '%s' 下没有模板行(需 ≥1 个 parent==container 的 el)" % container)

    # bindings.checkbox.el → base cap
    b = (flow.get("bindings") or {}).get("checkbox")
    if b:
        if b.get("el") not in base_ids:
            errors.append("bindings.checkbox: el '%s' 不在 base cap 里" % b.get("el"))

    return errors


# ── 资产清单 ────────────────────────────────────────────────────────────

def collect_assets(caps):
    """全部图片引用去重排序:els[].img + stageBg 里的 url(...)。"""
    assets = set()
    for cap in caps.values():
        for m in URL_RE.finditer(cap.get("stageBg") or ""):
            assets.add(m.group(1).strip("'\""))
        for e in cap.get("els") or []:
            if e.get("img"):
                assets.add(e["img"])
    return sorted(assets)


# ── CLI ─────────────────────────────────────────────────────────────────

def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    flow_path = argv[1]
    # capDir 缺省 = **flow.json 所在目录**,和 flow.caps 里的相对路径同一个基准 ——
    # html 运行时(assemble.js 相对 flow.json 加载)和 figma2html/flow_check.py 都这么解。
    # 以前这里强制从命令行收 capDir,于是同一份 flow:flow_check 全绿、ui_check 却报一堆
    # 坏引用(真实邮件工程里 caps 写的是 `../../screen-*.ui.json`,拿工程根去 join 就全找不到)。
    # 一个校验器和它要守的运行时对不上基准,报的错就是噪音。
    cap_dir = argv[2] if len(argv) == 3 else os.path.dirname(os.path.abspath(flow_path))
    try:
        flow = load_flow(flow_path)
    except Exception as e:
        print("[ui_check] flow 载入失败: %s (%s)" % (flow_path, e))
        return 1

    caps, errors = load_caps(flow, cap_dir)
    errors += check_flow(flow, caps)

    manifest = collect_assets(caps)
    out = os.path.join(cap_dir, "assets-manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print("[ui_check] assets-manifest.json → %s(%d 项)" % (out, len(manifest)))

    if errors:
        print("[ui_check] FAIL,%d 个坏引用:" % len(errors))
        for e in errors:
            print("  -", e)
        return 1
    print("[ui_check] OK:caps=%d,引用完整。" % len(caps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

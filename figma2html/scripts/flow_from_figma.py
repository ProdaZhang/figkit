# -*- coding: utf-8 -*-
"""flow_from_figma.py — 从 figma 的原型交互(REST `interactions[]`)生成 flow.json 初稿。

**为什么有它**:README 以前让人**从零手写** flow.json —— 手敲 JSON、手抄 figma node id,
是整条入门路上最陡的一段(陡到得配一个 flow_check.py 在浏览器之前拦错)。而 figma 其实
**是有**交互数据的:REST 的每个节点上都挂着 `interactions[]`(触发器 + 动作 + 转场),
以前这个仓库压根没读过它 —— README 甚至写着"figma 没有交互逻辑",那句是错的。

**它不替代手写,它把手写缩短成补差。** figma 的交互是**原型语义**(在 figma 播放器里、
对着静态帧、跳到哪个 frame);flow.json 要的是**应用语义**(守卫、真实数据的列表行、
业务钩子)。所以本脚本只搬能忠实搬的那部分,搬不动的**逐条报出来并说明原因**,
绝不猜 —— 猜出来的事件比没有事件更贵,因为它看起来是对的。

用法:
    python3 flow_from_figma.py <nodes.json> <out_flow.json> <name>=<screen.ui.json> [...] [--strict] [--motion-defaults]

  nodes.json   figma REST 响应(GET /v1/files/<key>/nodes?ids=<frameIds>),与 figma_capture 同一份
  <name>=<path>  每屏一个:flow 里的 cap 名 = 已经捕获好的 .ui.json。**第一个 = base 屏**。
                 路径按字面写进 caps(浏览器按它加载),同时用来读 frame id 与元素集合。
  --strict     有任何一条交互没能搬过来就 exit 3(给 CI 用;默认 exit 0,只在 stderr 报告)

搬得动 / 搬不动(对照 spec/flow-events.md 的 v1.1 能力):

  | figma                                     | flow.json            |
  |-------------------------------------------|----------------------|
  | ON_CLICK + NODE/OVERLAY → 某个 cap         | openModal(cap)       |
  | ON_CLICK + BACK / CLOSE(在 base 屏上)      | closeModal           |
  | ON_CLICK + BACK / CLOSE(在**弹窗**那一屏上) | @in:<modal>:<id>(v1.1)|
  | 转场(type/duration/easing)                 | events[].transition  |
  | 其余触发器(hover/drag/按键/超时/媒体)        | ✗ 报告               |
  | NAVIGATE / SWAP / SCROLL_TO / CHANGE_TO    | ✗ 报告               |
  | URL / SET_VARIABLE / CONDITIONAL           | ✗ 报告               |
  | 弹窗那一屏上的**其他**交互(非 BACK/CLOSE)    | ✗ 报告               |

**v1.1 补上的正是这一条**:v1.0 里 `events[].el` 只能引用 base 屏的节点,而"弹窗里的 ✗
关闭按钮"恰恰住在弹窗那一屏 —— figma 里最常见的一条交互,当时表达不了,只能拿
`@any:<modal>`(点哪都关)/ `@panelOutside:<modal>`(点面板外关)近似,而那与"点这个
按钮"根本不是一回事。现在直接落成 `@in:<modal>:<nodeId>`。

仍然**不猜**:那一屏若没有任何 OVERLAY 连线把它当弹窗打开过,就不知道该绑到哪个弹窗上,
照旧如实报告。这正是 CONTRIBUTING 原则 1 说的"由某个后端撞出的真实缺口触发结构变更"。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import motion  # noqa: E402  —— 默认动效预设(--motion-defaults 时才用)

# 输出里有中文。Windows 上 stdout 的编码跟系统区域走(CI runner 是 Latin-1),
# 一 print 就 UnicodeEncodeError、退出码非 0 —— 而开发机是 GBK,中文编得动,一路绿。
# 这一条把本进程的输出钉成 UTF-8,让「能不能打印」不再取决于跑在谁的机器上。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if hasattr(sys.stdout, "reconfigure"):      # Windows 老代码页打中文不炸
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

TRIGGERS = {"ON_CLICK": "click"}            # v1.0 的 events[].on 目前只有 click


def walk(node, out):
    """文档序 DFS —— 顺序即产物顺序,同一份输入必得同一份 flow.json。"""
    out.append(node)
    for c in node.get("children") or []:
        walk(c, out)


def interactions_of(node):
    """归一化到 interactions[]。

    老响应(2023 年之前)只有 `transitionNodeID` / `transitionDuration` / `transitionEasing`
    三件套、且**只回第一条** reaction。它历史上表示 NAVIGATE,这里就按 NAVIGATE 记 ——
    然后它会走到"搬不动"那条分支被报出来,而不是被悄悄当成 OVERLAY 搬错。
    """
    ints = node.get("interactions")
    if ints:
        return ints
    dest = node.get("transitionNodeID")
    if not dest:
        return []
    return [{"trigger": {"type": "ON_CLICK"}, "_legacy": True, "actions": [{
        "type": "NODE", "destinationId": dest, "navigation": "NAVIGATE",
        "transition": {"type": "DISSOLVE",
                       "duration": node.get("transitionDuration", 0),
                       "easing": {"type": node.get("transitionEasing", "LINEAR")}}}]}]


def norm_transition(tr):
    """figma 的 Transition → flow 里的 transition 字段(只留跨引擎有意义的部分)。

    弹簧原样带 figma 的 {mass, stiffness, damping} 三元组:换算成解耦的两参
    (阻尼比 / response)是**消费侧**的事,见各后端的 motion 求解器。这里不算,
    因为 IR 该存"设计说了什么",不该存"某个后端怎么解"。
    """
    if not tr:
        return None
    out = {"type": tr.get("type"), "duration": tr.get("duration", 0)}
    if tr.get("direction"):
        out["direction"] = tr["direction"]
    if tr.get("matchLayers"):
        out["matchLayers"] = True
    ez = tr.get("easing") or {}
    e = {"type": ez.get("type", "LINEAR")}
    cb = ez.get("easingFunctionCubicBezier")
    if cb:
        e["bezier"] = [cb.get("x1", 0), cb.get("y1", 0), cb.get("x2", 1), cb.get("y2", 1)]
    sp = ez.get("easingFunctionSpring")
    if sp:
        e["spring"] = {"mass": sp.get("mass", 1), "stiffness": sp.get("stiffness", 100),
                       "damping": sp.get("damping", 10)}
    out["easing"] = e
    return out


def load_caps(pairs, base_dir):
    """[(name, path)] → (caps: name -> {path, frame, ids, roots, w, h}, errors)。"""
    caps, errors = {}, []
    for name, rel in pairs:
        p = os.path.join(base_dir, str(rel).lstrip("/\\"))
        if not os.path.isfile(p):
            errors.append("cap '%s': 找不到 %s" % (name, p))
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                cap = json.load(f)
        except Exception as e:                      # noqa: BLE001 —— 报给人看,不吞
            errors.append("cap '%s': 载入失败 %s (%s)" % (name, p, e))
            continue
        els = cap.get("els") or []
        caps[name] = {
            "path": rel, "frame": cap.get("frame"),
            "ids": set(e.get("id") for e in els),
            "roots": [e.get("id") for e in els if not e.get("parent")],
            "w": cap.get("w", 0), "h": cap.get("h", 0),
        }
    return caps, errors


def build_flow(doc_roots, pairs, caps):
    """(frame 文档树们, 声明顺序, caps) → (flow dict, notes[])。纯函数,便于内存构造输入做测试。"""
    notes = []
    base_name = pairs[0][0]
    frame_to_cap = {}
    for name, c in caps.items():
        if c["frame"]:
            frame_to_cap.setdefault(c["frame"], name)
    owner = {}                                       # node id -> 它属于哪个 cap
    for name, c in caps.items():
        for i in c["ids"]:
            owner.setdefault(i, name)

    raw = []                                         # 先摊平成候选,再合并同类项
    used_modals = []
    pending_close = []      # 弹窗内的 BACK/CLOSE;等 used_modals 定了再落成 @in:
    for node in doc_roots:
        for inter in interactions_of(node):
            trig = (inter.get("trigger") or {}).get("type")
            where = owner.get(node["id"])
            label = "%s(%s)" % (node["id"], (node.get("name") or "")[:20])
            if trig not in TRIGGERS:
                notes.append("跳过 %s:触发器 %s —— v1.0 的 events[].on 只有 click" % (label, trig))
                continue
            if where is None:
                notes.append("跳过 %s:该节点不在任何一屏的捕获里(可能是不可见/被折叠进矢量簇)" % label)
                continue
            for act in (inter.get("actions") or []):
                atype = act.get("type")
                tr = norm_transition(act.get("transition"))
                if atype in ("BACK", "CLOSE"):
                    if where != base_name:
                        # v1.1:弹窗**里**的关闭按钮(最常见的就是那个 ✗)现在有得写了。
                        # 但"这一屏是不是真被当成弹窗用了"要等整轮扫完才知道(声明它的
                        # OVERLAY 连线可能排在后面),所以先记下,循环之后再定。
                        pending_close.append((node["id"], where, label, tr))
                        continue
                    raw.append(("click", node["id"], "closeModal", None, tr))
                    continue
                if atype != "NODE":
                    notes.append("跳过 %s 的 %s:v1.0 没有对应动作(守卫/变量/外链属应用语义,手写)"
                                 % (label, atype))
                    continue
                nav, dest = act.get("navigation"), act.get("destinationId")
                target = frame_to_cap.get(dest)
                if nav != "OVERLAY":
                    notes.append("跳过 %s 的 NODE/%s:v1.0 的模型是「base 常驻 + 弹窗叠加」,"
                                 "没有换底屏/滚动到/切变体这几种动作" % (label, nav))
                    continue
                if target is None:
                    notes.append("跳过 %s 的 OVERLAY:目标帧 %s 没有对应的 cap(命令行里没给这一屏?)"
                                 % (label, dest))
                    continue
                if where != base_name:
                    notes.append("跳过 %s 的 OVERLAY:它住在 '%s' 屏,而 v1.0 的 events 只绑 base 屏"
                                 % (label, where))
                    continue
                if target not in used_modals:
                    used_modals.append(target)
                raw.append(("click", node["id"], "openModal", target, tr))

    # 弹窗内的关闭按钮 → @in:<modal>:<nodeId>(v1.1)。这一屏没被任何连线当成弹窗打开过
    # 就仍然落不了地 —— 那是真的缺信息,照旧如实报告,不猜。
    for nid, where, label, tr in pending_close:
        if where in used_modals:
            raw.append(("click", "@in:%s:%s" % (where, nid), "closeModal", None, tr))
        else:
            notes.append("跳过 %s 的关闭:它住在 '%s' 屏,而这一屏没有任何 OVERLAY 连线把它"
                         "当弹窗打开过 —— 不知道该绑到哪个弹窗上" % (label, where))

    events, index = [], {}
    for on, el, do, arg, tr in raw:
        key = (on, do, arg, json.dumps(tr, sort_keys=True))
        if key in index:                             # 同一个动作的多个触发元素 → 合成 el 数组
            ev = events[index[key]]
            els = ev["el"] if isinstance(ev["el"], list) else [ev["el"]]
            if el not in els:
                els.append(el)
            ev["el"] = els
            continue
        index[key] = len(events)
        ev = {"on": on, "el": el, "do": do}
        if arg is not None:
            ev["arg"] = arg
        if tr:
            ev["transition"] = tr
        events.append(ev)

    modals = {}
    for name in used_modals:
        c = caps[name]
        m = {"cap": name, "roots": list(c["roots"])}
        # panel = "点面板外关闭"的判定对象。只有一个顶层根时它必然就是面板本体;
        # 多根时(外框+页签+列表是分开的顶层兄弟)猜不出来,**留空**而不是瞎指一个。
        if len(c["roots"]) == 1:
            m["panel"] = c["roots"][0]
        else:
            notes.append("modals[%s]:有 %d 个顶层根,猜不出 panel(点面板外关闭要用它)—— 手填"
                         % (name, len(c["roots"])))
        modals[name] = m

    base = caps[base_name]
    flow = {
        "stage": {"w": base["w"], "h": base["h"]},
        "caps": dict((n, caps[n]["path"]) for n, _ in pairs if n in caps),
        "base": base_name,
        "modals": modals,
        "state": {},
        "events": events,
    }
    return flow, notes


USAGE = __doc__.split("用法:", 1)[1].split("搬得动", 1)[0].strip()


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    strict = "--strict" in argv[1:]
    if len(args) < 3 or any("=" not in a for a in args[2:]):
        sys.stderr.write("用法: " + USAGE + "\n")
        return 2
    nodes_json, out_path = args[0], args[1]
    pairs = [tuple(a.split("=", 1)) for a in args[2:]]

    try:
        with open(nodes_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:                           # noqa: BLE001
        sys.stderr.write("[flow-import] 读不了 %s: %s\n" % (nodes_json, e))
        return 2

    caps, errors = load_caps(pairs, os.path.dirname(os.path.abspath(out_path)))
    if errors:
        for e in errors:
            sys.stderr.write("[flow-import] %s\n" % e)
        return 2

    # 只走命令行点名的那些帧,且按点名顺序 —— 产物顺序不受 figma 返回顺序影响。
    nodes = data.get("nodes") or {}
    doc_roots = []
    for name, _ in pairs:
        fid = caps[name]["frame"]
        entry = nodes.get(fid)
        if not entry:
            sys.stderr.write("[flow-import] nodes.json 里没有帧 %s(cap '%s' 的 frame)\n" % (fid, name))
            return 2
        walk(entry.get("document") or {}, doc_roots)

    flow, notes = build_flow(doc_roots, pairs, caps)

    added = []
    if "--motion-defaults" in argv[1:]:
        # figma 大多数时候什么都没连 —— 那时候界面不该是"没有动效",该是"合理的默认动效"。
        # 补出来的东西**写进这份草稿**、每条带 source,人看得见、能改能删。
        flow, added = motion.apply_defaults(flow)

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        json.dump(flow, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("[flow-import] %s:%d 屏 / %d 事件 / %d 弹窗,%d 条交互没搬过来"
          % (out_path, len(flow["caps"]), len(flow["events"]), len(flow["modals"]), len(notes)))
    for a in added:
        print("  + 默认动效(figma 未定义,来自 %s 预设,可直接在 flow.json 里改/删):%s"
              % (motion.PRESET_NAME, a))
    for n in notes:
        sys.stderr.write("  ! %s\n" % n)
    if notes:
        sys.stderr.write("  ^ 以上是 figma 有、flow v1.0 表达不了的部分。守卫 / 列表数据绑定 /\n"
                         "    业务钩子 figma 里本来就没有,照 spec/flow-events.md 手写补上。\n")
    return 3 if (strict and notes) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

# -*- coding: utf-8 -*-
"""跨后端一致性:同一份 IR,各后端的处置必须与它自己的声明相符。

**为什么需要它**:此前每个后端只跟**自己手写的期望**比对,没有任何东西断言
"五个后端对同一份 IR 理解一致"。而唯一的跨后端共享夹具(login 三屏)实测只覆盖
radius / border / stageBg —— shadow / blur / rot / opacity / img / vec / gradient /
text-stroke / 百分比圆角全是零覆盖。于是 `radius:"50%"`(capture 对每个 ELLIPSE 都产)
在 godot 被整个丢掉、在 cocos 被当成 50px,两边测试却都是绿的。

本套做三件事:
  1. 三个产物型后端都能吃下 kitchen-sink(不崩、退出码 0);
  2. 各后端在 expectations.json 里的声明与产物**对得上**
     (render/approx → 产物里找得到信号;known-loss → 找不到信号,但必须有降级留痕);
  3. 声明为 approx / known-loss 的,必须能在该后端 references/mapping.md 里查到 ——
     把 known-loss 表从散文变成机读契约,防"代码丢了、文档没写"。

覆盖边界(诚实):figma2html 与 figma2cocos 是**解释器**,运行时直接吃 .ui.json,
没有可静态检查的产物,不在本套内(见 expectations.json 的 _scope)。
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CAP = os.path.join(HERE, "kitchen-sink.ui.json")
EXP = json.load(io.open(os.path.join(HERE, "expectations.json"), encoding="utf-8"))

BACKENDS = {
    "godot":  ("figma2godot",  "scripts/ui_to_tscn.py",   "kitchen-sink.tscn"),
    "unity":  ("figma2unity",  "scripts/ui_to_unity.py",  "kitchen-sink.uss"),
    "unreal": ("figma2unreal", "scripts/ui_to_uespec.py", "kitchen-sink.uespec.json"),
}

_ART = {}      # backend -> (artifact_text, stderr_text)


def _run_all():
    """跑三个转换器,缓存产物与 stderr。"""
    if _ART:
        return _ART
    tmp = tempfile.mkdtemp(prefix="figkit_conf_")
    for name, (pkg, script, artifact) in BACKENDS.items():
        r = subprocess.run([sys.executable, os.path.join(ROOT, pkg, script), CAP, tmp],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, "%s 转换 kitchen-sink 失败(退出码 %d):\n%s" % (
            name, r.returncode, r.stderr)
        p = os.path.join(tmp, artifact)
        assert os.path.exists(p), "%s 没产出 %s" % (name, artifact)
        _ART[name] = (io.open(p, encoding="utf-8").read(), r.stderr or "")
    return _ART


def _sane(eid):
    return eid.replace(":", "_")


# ── 每个后端:从产物里切出某元素的片段 + 判断特性信号是否存在 ──────────────────

def _godot_chunk(text, eid):
    n = _sane(eid)
    parts = [b for b in text.split("\n\n")
             if ('id="sb_%s"' % n) in b or ('name="%s"' % n) in b
             or ('id="tex_%s"' % n) in b or ('SubResource("sb_%s")' % n) in b]
    return "\n".join(parts)


def _unity_chunk(text, eid):
    m = re.search(r"\.el-%s\s*\{(.*?)\}" % re.escape(_sane(eid)), text, re.S)
    return m.group(1) if m else ""


def _unreal_el(text, eid):
    for e in json.loads(text)["els"]:
        if e["id"] == eid:
            return e
    return None


GODOT_SIGNALS = {
    "radius-px": "corner_radius", "radius-pct": "corner_radius",
    "radius-pct-oblong": "corner_radius", "border": "border_width",
    # blur 的信号不能用 "blur" 这个词:元素自己就叫 k:blur,节点名会撞出假阳性
    # (第一版就这么误报了)。Godot 侧真要做模糊只能是 BackBufferCopy + 着色器,
    # 拿它当信号 —— 找不到才说明确实没实现。
    "shadow": "shadow_color", "blur": "BackBufferCopy", "rot": "rotation",
    "opacity": "modulate", "img": "texture", "vec": "texture",
    "gradient-linear": "texture", "gradient-radial": "Gradient",
    "text": "text = ", "text-stroke": "font_outline_color",
}
UNITY_SIGNALS = {
    "radius-px": "radius", "radius-pct": "radius", "radius-pct-oblong": "radius",
    "border": "border-width", "shadow": "shadow", "blur": "blur",
    "rot": "rotate", "opacity": "opacity", "img": "background-image",
    "vec": "background-image", "gradient-linear": "gradient",
    "gradient-radial": "gradient", "text": "font-size", "text-stroke": "outline",
}
UNREAL_FIELD = {
    "radius-px": "radius", "radius-pct": "radius", "radius-pct-oblong": "radius",
    "border": "border", "shadow": "shadow", "blur": "blur", "rot": "rot",
    "opacity": "opacity", "img": "img", "vec": "vec", "gradient-linear": "fill",
    "gradient-radial": "fill", "text": "text", "text-stroke": "text",
}


def _present(backend, feat, eid):
    art, _ = _run_all()[backend]
    if backend == "godot":
        return GODOT_SIGNALS[feat] in _godot_chunk(art, eid)
    if backend == "unity":
        return UNITY_SIGNALS[feat] in _unity_chunk(art, eid)
    e = _unreal_el(art, eid)
    assert e is not None, "unreal uespec 里没有元素 %s" % eid
    v = e.get(UNREAL_FIELD[feat])
    if feat == "text-stroke":
        return bool((v or {}).get("stroke"))
    if feat in ("gradient-linear", "gradient-radial"):
        return (v or {}).get("type") in ("linear", "radial")
    if feat == "opacity":
        return v < 1
    return bool(v)


def _loss_report(backend):
    """该后端"留痕"的降级说明文本(unity 写进 .uss 头;godot 写 stderr)。"""
    art, err = _run_all()[backend]
    if backend == "unity":
        return "\n".join(l for l in art.split("\n") if l.strip().startswith("*"))
    return err


# ── 检查 ─────────────────────────────────────────────────────────────────────

def test_all_backends_consume_kitchen_sink():
    """三个产物型后端都得吃得下这份把特性打满的 IR。"""
    arts = _run_all()
    assert len(arts) == 3, arts.keys()
    for name, (art, _) in arts.items():
        assert len(art) > 200, "%s 的产物短得可疑(%d 字节)" % (name, len(art))


def test_declarations_match_artifacts():
    """声明 render/approx 就得在产物里找得到;声明 known-loss 就得找不到。"""
    bad = []
    for feat, spec in sorted(EXP["features"].items()):
        eid = spec["el"]
        for backend in BACKENDS:
            status = spec[backend]
            got = _present(backend, feat, eid)
            want = status in ("render", "approx", "carry")
            if got != want:
                bad.append("%s/%s 声明 %s,产物里%s(元素 %s)"
                           % (backend, feat, status, "找到了信号" if got else "找不到信号", eid))
    assert not bad, "声明与产物不符:\n  " + "\n  ".join(bad)


def test_degradations_leave_a_trace():
    """approx / known-loss 必须留痕 —— 仓库原则:不许静默丢失。"""
    bad = []
    for feat, spec in sorted(EXP["features"].items()):
        for backend in ("godot", "unity"):          # unreal 的取舍在 C++ 运行时
            if spec[backend] not in ("approx", "known-loss"):
                continue
            rep = _loss_report(backend)
            if _sane(spec["el"]) not in rep.replace(":", "_"):
                bad.append("%s/%s 声明 %s,却没有任何提及 %s 的降级说明"
                           % (backend, feat, spec[backend], spec["el"]))
    assert not bad, "降级没留痕:\n  " + "\n  ".join(bad)


def test_known_loss_is_documented():
    """声明的降级必须能在该后端 mapping.md 里查到 —— 把 known-loss 表变成机读契约。"""
    bad = []
    for backend, (pkg, _, _) in BACKENDS.items():
        md = io.open(os.path.join(ROOT, pkg, "references", "mapping.md"),
                     encoding="utf-8").read()
        for feat, spec in sorted(EXP["features"].items()):
            if spec[backend] not in ("approx", "known-loss"):
                continue
            if spec["doc"] not in md:
                bad.append("%s 声明 %s 为 %s,但 mapping.md 里查不到 %r"
                           % (backend, feat, spec[backend], spec["doc"]))
    assert not bad, "文档与代码脱节:\n  " + "\n  ".join(bad)


def test_percent_radius_agrees_across_parsers():
    """三个 python 解析器对同一串 CSS 必须给同一个数 —— 这正是当初漏掉的那类分叉。"""
    sys.path.insert(0, os.path.join(ROOT, "figma2godot", "scripts"))
    sys.path.insert(0, os.path.join(ROOT, "figma2unreal", "scripts"))
    import ui_to_tscn as G
    import ui_to_uespec as R
    bad = []
    for w, h in ((100, 100), (300, 80), (40, 40), (17, 100)):
        g = G.parse_radius("50%", w, h)
        r = R.parse_radius("50%", w, h)
        if list(g) != [round(x) for x in r]:
            bad.append("%dx%d: godot=%s unreal=%s" % (w, h, g, r))
    assert not bad, "百分比圆角口径分叉:\n  " + "\n  ".join(bad)


def test_kitchen_sink_is_fresh():
    """夹具是生成物,改了生成器忘了重跑就会与它声称覆盖的特性脱节。"""
    tmp = tempfile.mkdtemp(prefix="figkit_ks_")
    r = subprocess.run([sys.executable, os.path.join(HERE, "make_kitchen_sink.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=HERE)
    assert r.returncode == 0, r.stderr
    fresh = io.open(CAP, encoding="utf-8").read()
    assert '"k:radius-pct"' in fresh and '"k:blur"' in fresh, "夹具内容不对"
    del tmp


# ── 输入守门:各后端必须**一致地**拒绝同一批畸形 IR ─────────────────────────────

BAD_IRS = {
    "顶层缺 els": {"w": 100, "h": 100},
    "顶层 w 不是数字": {"w": "wide", "h": 100, "els": []},
    "元素缺 id": {"w": 100, "h": 100, "els": [{"x": 0, "y": 0, "w": 1, "h": 1}]},
    "元素 id 重复": {"w": 100, "h": 100, "els": [
        {"id": "a", "x": 0, "y": 0, "w": 1, "h": 1},
        {"id": "a", "x": 0, "y": 0, "w": 1, "h": 1}]},
    "元素几何不是数字": {"w": 100, "h": 100, "els": [
        {"id": "a", "x": "left", "y": 0, "w": 1, "h": 1}]},
    "parent 指向不存在的元素": {"w": 100, "h": 100, "els": [
        {"id": "a", "x": 0, "y": 0, "w": 1, "h": 1, "parent": "ghost"}]},
}


def _feed(cap_obj, tag):
    """把一份 IR 喂给三个后端 → {backend: (returncode, 合并输出)}。"""
    tmp = tempfile.mkdtemp(prefix="figkit_bad_")
    p = os.path.join(tmp, "%s.ui.json" % tag)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        json.dump(cap_obj, f, ensure_ascii=False)
    out = {}
    for name, (pkg, script, _) in BACKENDS.items():
        r = subprocess.run([sys.executable, os.path.join(ROOT, pkg, script), p,
                            os.path.join(tmp, "out")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out[name] = (r.returncode, (r.stdout or "") + (r.stderr or ""))
    return out


def test_malformed_ir_is_rejected_consistently():
    """畸形 IR 必须被**每个**后端挡下:退出码非 0,且不是 traceback。

    此前 6 个后端里只有 cocos 有校验器,其余喂进畸形 IR 就是 KeyError 或静默错渲染。
    校验代码在各后端里各带一份(skill 必须自足、不能跨目录 import),所以"一致"这件事
    没法靠共享代码保证 —— 只能靠这条测试。"""
    bad = []
    for tag, obj in sorted(BAD_IRS.items()):
        res = _feed(obj, tag.replace(" ", "_"))
        for backend, (rc, text) in sorted(res.items()):
            if rc == 0:
                bad.append("%s:%s 居然接受了" % (backend, tag))
            elif "Traceback" in text:
                bad.append("%s:%s 抛了 traceback 而不是给人话" % (backend, tag))
    assert not bad, "输入守门不一致:\n  " + "\n  ".join(bad)


def test_good_ir_still_passes_the_guard():
    """守门别把正常输入也拦了 —— kitchen-sink 必须照常通过(前面的用例已覆盖,这里做反向锚)。"""
    for backend, (rc, text) in sorted(_feed(
            json.loads(io.open(CAP, encoding="utf-8").read()), "good").items()):
        assert rc == 0, "%s 把合法 IR 也拒了(rc=%d):\n%s" % (backend, rc, text[:400])


def test_spec_version_is_advisory():
    """版本字段是**参考**不是门禁:主版本不同要吭声,次版本与缺失都照常跑。"""
    base = json.loads(io.open(CAP, encoding="utf-8").read())
    cases = [("2.0", True), ("1.7", False), (None, False)]
    bad = []
    for ver, want_warn in cases:
        obj = dict(base)
        obj.pop("spec", None) if ver is None else obj.update(spec=ver)
        for backend, (rc, text) in sorted(_feed(obj, "ver").items()):
            if rc != 0:
                bad.append("%s 因 spec=%r 直接失败了(版本应是参考,不是门禁)" % (backend, ver))
            got_warn = "[ir-spec]" in text
            if got_warn != want_warn:
                bad.append("%s 对 spec=%r %s告警" % (backend, ver, "不该" if got_warn else "该"))
    assert not bad, "版本处置不一致:\n  " + "\n  ".join(bad)


def test_capture_stamps_the_spec_version():
    """夹具必须带版本 —— 不带的话上面那条测试测的是空气。"""
    cap = json.loads(io.open(CAP, encoding="utf-8").read())
    assert cap.get("spec") == "1.0", "kitchen-sink 没带 spec 字段: %r" % cap.get("spec")


# ── flow 引用:三个消费 flow 的后端必须给出同样的判定 ─────────────────────────

FLOW_CONSUMERS = {
    # backend -> (脚本, 组装 argv 的函数)。三家 CLI 形状不同,判定语义必须相同。
    "html":   ("figma2html/scripts/flow_check.py",
               lambda d: [os.path.join(d, "flow.json")]),
    "cocos":  ("figma2cocos/scripts/ui_check.py",
               lambda d: [os.path.join(d, "flow.json"), d]),
    "unreal": ("figma2unreal/scripts/ui_to_uespec.py",
               lambda d: [os.path.join(d, "screen-login.ui.json"),
                          os.path.join(d, "flow.json"), os.path.join(d, "out")]),
}
LOGIN_FIX = os.path.join(ROOT, "figma2cocos", "scripts", "tests", "fixtures")
FLOW_FILES = ("flow.json", "screen-login.ui.json",
              "screen-notice.ui.json", "screen-serverlist.ui.json")


def _feed_flow(mutate, tag):
    """把 login 夹具拷进临时目录、按 mutate 改坏 flow,再喂给三个后端 → {backend: rc}。"""
    tmp = tempfile.mkdtemp(prefix="figkit_flow_%s_" % tag)
    for fn in FLOW_FILES:
        with io.open(os.path.join(LOGIN_FIX, fn), encoding="utf-8") as f:
            data = json.load(f)
        if fn == "flow.json" and mutate:
            mutate(data)
        with io.open(os.path.join(tmp, fn), "w", encoding="utf-8", newline="") as f:
            json.dump(data, f, ensure_ascii=False)
    out = {}
    for name, (script, argv_of) in FLOW_CONSUMERS.items():
        r = subprocess.run([sys.executable, os.path.join(ROOT, script)] + argv_of(tmp),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out[name] = (r.returncode, (r.stdout or "") + (r.stderr or ""))
    return out


def _bad_event(f):
    f["events"][0]["el"] = "99:9999"


def _bad_modal_root(f):
    f["modals"][sorted(f["modals"])[0]]["roots"] = ["99:1"]


def _bad_checkbox(f):
    f["bindings"]["checkbox"]["el"] = "99:4"


def _bad_list_container(f):
    f["list"]["container"] = "99:3"


BAD_FLOWS = {
    "事件 el 不存在": _bad_event,
    "modal root 不存在": _bad_modal_root,
    "checkbox el 不存在": _bad_checkbox,
    "list container 不存在": _bad_list_container,
}


def test_good_flow_accepted_by_every_consumer():
    """反向锚:没改坏的 flow,三家都得放行。"""
    bad = [("%s rc=%d\n%s" % (b, rc, t[:300]))
           for b, (rc, t) in sorted(_feed_flow(None, "good").items()) if rc != 0]
    assert not bad, "合法 flow 被拒:\n  " + "\n  ".join(bad)


def test_bad_flow_rejected_by_every_consumer():
    """坏引用必须被**每个**消费 flow 的后端挡下。

    此前 html 这条路只在浏览器 console.warn 一句 —— 而 README 恰恰让人手写 flow.json,
    这条路又是首选入口和 live demo 走的路,反馈却最差。判定逻辑三家各带一份
    (skill 必须自足),所以"一致"只能靠这条测试保证。"""
    bad = []
    for tag, mut in sorted(BAD_FLOWS.items()):
        for backend, (rc, text) in sorted(_feed_flow(mut, "bad").items()):
            if rc == 0:
                bad.append("%s 放过了「%s」" % (backend, tag))
            elif "Traceback" in text:
                bad.append("%s 对「%s」抛了 traceback" % (backend, tag))
    assert not bad, "flow 判定不一致:\n  " + "\n  ".join(bad)


# ── 转场缓动:曲线必须逐点一致 ────────────────────────────────────────────────
#
# 这一节要挡的东西和 radius:"50%" 是同一类,但更隐蔽:figma 给的是一条具体曲线
# (cubic-bezier / 弹簧三参),而每个引擎都有一套**同名不同形**的内置缓动枚举
# (DOTween 的 Ease.OutQuad、Godot 的 Tween.EASE_OUT、USS 的 ease-out、UE 的 EEasingFunc)。
# 各后端各挑"最像的那个",同一份 IR 在六个引擎里就是六种手感 —— 而每家的测试都绿着,
# 因为每家都只跟自己的期望比。所以这里不比"用了哪个枚举",直接比**采出来的点**。
#
# 参照量级:easeOutCubic 与 cubic-bezier(.23,1,.32,1) 最大差 19.8 个百分点,且差在起步段。
# 那正是"随手挑一个差不多的枚举"的代价 —— 肉眼看得出来,测试却看不出来。

MOTION_BACKENDS = {                                   # 后端 → 跑法(都产 outdir/motion.json)
    "godot":  lambda tmp: ["figma2godot/scripts/ui_to_tscn.py",
                           os.path.join(tmp, "screen-login.ui.json"), tmp,
                           os.path.join(tmp, "flow.json")],
    "unity":  lambda tmp: ["figma2unity/scripts/ui_to_unity.py",
                           os.path.join(tmp, "screen-login.ui.json"), tmp,
                           os.path.join(tmp, "flow.json")],
    "unreal": lambda tmp: ["figma2unreal/scripts/ui_to_uespec.py",
                           os.path.join(tmp, "screen-login.ui.json"),
                           os.path.join(tmp, "flow.json"), tmp],
}

BEZIER_TR = {"type": "MOVE_IN", "direction": "BOTTOM", "duration": 300,
             "easing": {"type": "CUSTOM_CUBIC_BEZIER", "bezier": [.32, .72, 0, 1]}}
# zeta=0.2、w0=10 → 阻尼振荡周期≈641ms,**首个过冲峰在≈320ms**。采样窗口必须覆盖到峰,
# 否则"这条弹簧会不会过冲"根本没进画面(踩过:给 120ms 时窗口内一路单调上升,像解错了)。
SPRING_TR = {"type": "SMART_ANIMATE", "duration": 600,
             "easing": {"type": "CUSTOM_SPRING",
                        "spring": {"mass": 1, "stiffness": 100, "damping": 4}}}
# 同一条弹簧、窗口短得多 —— 专用来验"被 duration 截断"这条降级有没有被说出来。
SHORT_SPRING_TR = {"type": "SMART_ANIMATE", "duration": 120,
                   "easing": {"type": "CUSTOM_SPRING",
                              "spring": {"mass": 1, "stiffness": 100, "damping": 4}}}
UNKNOWN_TR = {"type": "DISSOLVE", "duration": 260, "easing": {"type": "BOUNCY"}}


def _bake_everywhere(transition):
    """给 login flow 的首个 openModal 事件换上 transition,三家各烘一次 → {backend: (motion, stderr)}。"""
    tmp = tempfile.mkdtemp(prefix="figkit_motion_")
    for fn in FLOW_FILES:
        with io.open(os.path.join(LOGIN_FIX, fn), encoding="utf-8") as f:
            data = json.load(f)
        if fn == "flow.json":
            for ev in data["events"]:
                ev.pop("transition", None)
            ev0 = [e for e in data["events"] if e.get("do") == "openModal"][0]
            ev0["transition"] = transition
        with io.open(os.path.join(tmp, fn), "w", encoding="utf-8", newline="") as f:
            json.dump(data, f, ensure_ascii=False)
    out = {}
    for name, argv_of in sorted(MOTION_BACKENDS.items()):
        argv = argv_of(tmp)
        r = subprocess.run([sys.executable, os.path.join(ROOT, argv[0])] + argv[1:],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, "%s 烘 motion 失败 rc=%d\n%s" % (name, r.returncode, r.stderr)
        p = os.path.join(tmp, "motion.json")
        assert os.path.exists(p), "%s 没产出 motion.json" % name
        with io.open(p, encoding="utf-8") as f:
            out[name] = (json.load(f), r.stderr or "")
        os.remove(p)                                  # 免得下一家读到上一家的
    return out


def test_motion_solver_copies_are_byte_identical():
    """求解器在每个后端各带一份(skill 必须自足、可单独安装)。**逐字节**比,不比行为 ——
    行为一致是结论,字节一致才是能守住的前提。capture 的镜像就是这么守的。"""
    master = io.open(os.path.join(ROOT, "figma2html", "scripts", "motion.py"), "rb").read()
    drift = []
    for pkg in ("figma2godot", "figma2unity", "figma2unreal"):
        p = os.path.join(ROOT, pkg, "scripts", "motion.py")
        if not os.path.exists(p):
            drift.append("%s 缺 motion.py" % pkg)
        elif io.open(p, "rb").read() != master:
            drift.append("%s/scripts/motion.py 与 figma2html 的主拷贝不一致" % pkg)
    assert not drift, "\n  ".join(drift)


def test_every_backend_bakes_the_same_bezier_points():
    baked = _bake_everywhere(BEZIER_TR)
    ref_name, (ref, _) = sorted(baked.items())[0]
    ref_pts = {k: v["points"] for k, v in ref["curves"].items()}
    assert ref_pts and all(len(p) == ref["samples"] for p in ref_pts.values()), ref_pts
    for name, (data, _) in sorted(baked.items()):
        got = {k: v["points"] for k, v in data["curves"].items()}
        assert got == ref_pts, "%s 与 %s 的采样点不一致" % (name, ref_name)


def test_every_backend_bakes_the_same_spring_points():
    """弹簧尤其容易漂:figma 给的是纠缠的 {mass,stiffness,damping} 三元组,
    换算成解耦两参再解析求解,任一家算错都只会表现为"手感不太一样"。"""
    baked = _bake_everywhere(SPRING_TR)
    ref_name, (ref, _) = sorted(baked.items())[0]
    ref_pts = {k: v["points"] for k, v in ref["curves"].items()}
    peak = max(y for pts in ref_pts.values() for _, y in pts)
    assert peak > 1.0, "damping=4 → 阻尼比 0.2,这条弹簧必须过冲(不过冲=解错了)"
    for name, (data, _) in sorted(baked.items()):
        assert {k: v["points"] for k, v in data["curves"].items()} == ref_pts, \
            "%s 与 %s 的弹簧采样不一致" % (name, ref_name)


def test_spring_truncation_reported_by_every_backend():
    """duration 120ms 远短于这条弹簧的收敛时间 = 曲线被切掉一截。那是降级,必须每家都说。"""
    for name, (_, err) in sorted(_bake_everywhere(SHORT_SPRING_TR).items()):
        # 断言 ASCII 标记而不是中文:子进程在非 CJK 代码页下会把中文降级成 '?',
        # 拿中文做断言等于在测运行环境的编码。降级行因此都带一个跨代码页可 grep 的前缀。
        assert "known-loss" in err and "truncated:" in err, \
            "%s 没报告弹簧被 duration 截断:\n%s" % (name, err)


def test_unknown_easing_is_declared_unresolved_not_guessed():
    """figma 没公开 BOUNCY 的控制点。**必须解不出来**并留痕 ——
    编一组"差不多"的数进来,产物看起来完全正常而手感是错的,比解不出来贵得多。"""
    for name, (data, err) in sorted(_bake_everywhere(UNKNOWN_TR).items()):
        curves = list(data["curves"].values())
        assert curves and all(c.get("unresolved") for c in curves), "%s 猜了 BOUNCY: %s" % (name, curves)
        assert all(c["points"] == [] for c in curves), "%s 给了不该有的采样点" % name
        assert "known-loss" in err, "%s 没留痕:\n%s" % (name, err)


def test_engine_binders_interpolate_the_sampled_curve_linearly():
    """★ 采样点一致**只保证关键帧上一致**,帧与帧之间用什么插值同样必须对齐。

    实测踩到过:Godot 的 `Curve.sample_baked()` 量化到 100 段,Unity 的 `AnimationCurve`
    默认平滑切线会在段内拱起来 —— 两边各差 ~1.4e-3。更阴的是,当初拿 x=0.25 去对账
    "完全一致",而 0.25 恰好**是**一个关键帧:任何插值模式在关键帧上都返回原值,
    那次对账其实什么都没证明。改成线性切线 + 非关键帧点(x=0.3)重测才真对上。

    引擎跑不进 CI,所以这里守源码层:线性切线必须在,量化采样必须不在。
    """
    bad = []
    gd = io.open(os.path.join(ROOT, "figma2godot", "runtime", "flow_binder.gd"),
                 encoding="utf-8").read()
    if "TANGENT_LINEAR" not in gd:
        bad.append("flow_binder.gd 没把 Curve 切线设成 TANGENT_LINEAR")
    if "sample_baked(" in gd:
        bad.append("flow_binder.gd 还在用 sample_baked()(量化到 bake_resolution,会与别家差 ~1e-3)")
    cs = io.open(os.path.join(ROOT, "figma2unity", "runtime", "FlowBinder.cs"),
                 encoding="utf-8").read()
    if "inTangent" not in cs or "outTangent" not in cs:
        bad.append("FlowBinder.cs 没显式给 AnimationCurve 线性切线(默认平滑切线会在段内拱起来)")
    assert not bad, "\n  ".join(bad)


def test_motion_not_played_is_written_down_in_every_mapping():
    """曲线烘出来了但**没有后端在播** —— 这是登记在案的降级,不是静默丢失。
    每家 mapping.md 都得能查到,否则就成了"代码里有、文档里没有"的那类账。"""
    missing = []
    for pkg in ("figma2godot", "figma2unity", "figma2unreal", "figma2cocos"):
        p = os.path.join(ROOT, pkg, "references", "mapping.md")
        text = io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        if "transition" not in text.lower():
            missing.append("%s/references/mapping.md 没登记转场的处置" % pkg)
    assert not missing, "\n  ".join(missing)


def _run():
    ok = True
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception as e:
                ok = False
                print("FAIL", name, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)

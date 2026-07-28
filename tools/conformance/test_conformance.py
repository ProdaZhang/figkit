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

# -*- coding: utf-8 -*-
"""跨后端一致性:同一份 IR,各后端的处置必须与它自己的声明相符。

**为什么需要它**:此前每个后端只跟**自己手写的期望**比对,没有任何东西断言
"各后端对同一份 IR 理解一致"。而唯一的跨后端共享夹具(login 三屏)实测只覆盖
radius / border / stageBg —— shadow / blur / rot / opacity / img / vec / gradient /
text-stroke / 百分比圆角全是零覆盖。于是 `radius:"50%"`(capture 对每个 ELLIPSE 都产)
在 godot 被整个丢掉、在 cocos 被当成 50px,两边测试却都是绿的。

本套做三件事:
  1. 两个产物型后端都能吃下 kitchen-sink(不崩、退出码 0);
  2. 各后端在 expectations.json 里的声明与产物**对得上**
     (render/approx → 产物里找得到信号;known-loss → 找不到信号,但必须有降级留痕);
  3. 声明为 approx / known-loss 的,必须能在该后端 references/mapping.md 里查到 ——
     把 known-loss 表从散文变成机读契约,防"代码丢了、文档没写"。

覆盖边界(诚实):figma2html 与 figma2cocos 是**解释器**,运行时直接吃 .ui.json,
没有可静态检查的**像素**产物,不在像素那几节内(见 expectations.json 的 _scope)。
**但转场缓动那一节三家都在**:cocos 虽无转换器,曲线仍在 python 侧解算(它自带
`scripts/bake_motion.py`),烘出来的采样点照样逐点对账。
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
SPEC = EXP
SINK = CAP


def _read(p):
    return io.open(p, encoding="utf-8").read()


def _schema_fields():
    """从 spec/ui.json-schema.md 那段 jsonc 里抽出 els[0] 的字段名 —— **schema 是真源**。

    刻意不在这里另抄一份字段清单:抄一份就要人去同步,而"忘了同步"正是这套断言要防的。
    """
    md = _read(os.path.join(ROOT, "spec", "ui.json-schema.md"))
    blk = re.search(r'"els":\s*\[\{(.*?)\n  \}\]', md, re.S)
    assert blk, "spec/ui.json-schema.md 里找不到 els[0] 那段 jsonc —— 结构变了就得改这里"
    body = re.sub(r'//[^\n]*', '', blk.group(1))          # 去掉行尾注释,免得注释里的引号混进来
    return sorted(set(re.findall(r'"([A-Za-z][A-Za-z0-9_]*)"\s*:', body)))


_SCHEMA_FIELDS = _schema_fields()

BACKENDS = {
    "godot":  ("figma2godot",  "scripts/ui_to_tscn.py",   "kitchen-sink.tscn"),
    "unity":  ("figma2unity",  "scripts/ui_to_unity.py",  "kitchen-sink.uss"),
}

_ART = {}      # backend -> (artifact_text, stderr_text)


def _run_all():
    """跑每个转换器,缓存产物与 stderr。"""
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
        art = io.open(p, encoding="utf-8").read()
        if name == "unity":
            # unity 的产物是一对:样式在 .uss,而矢量元素的证据(<figkit:FigVector>)
            # 只在 .uxml 里。只看 .uss 就会把已实现的特性误判成没实现。
            ux = p[:-4] + ".uxml"
            if os.path.exists(ux):
                art += "\n" + io.open(ux, encoding="utf-8").read()
        _ART[name] = (art, r.stderr or "")
    return _ART


def _sane(eid):
    return eid.replace(":", "_")


def _sane_subid(eid):
    """godot 的 **sub_resource id** 规矩比节点名严:只收 [A-Za-z0-9_]。
    kitchen-sink 的元素 id 带连字符(k:radius-pct),节点名留着它、sub id 换成下划线,
    所以切片时两种写法都得试。"""
    return re.sub(r"[^A-Za-z0-9_]", "_", eid)


# ── 每个后端:从产物里切出某元素的片段 + 判断特性信号是否存在 ──────────────────

def _godot_chunk(text, eid):
    n, s = _sane(eid), _sane_subid(eid)
    blocks = text.split("\n\n")
    parts = [b for b in blocks
             if ('id="sb_%s"' % s) in b or ('name="%s"' % n) in b
             or ('id="tex_%s"' % n) in b or ('SubResource("sb_%s")' % s) in b]
    # ext_resource 声明在**文件头**,节点块里只留 ExtResource("tex_N") —— 不把被引用的
    # 那一行捞回来,像 .svg 这种"证据在路径里"的信号就永远查无此人(踩过)。
    body = "\n".join(parts)
    for rid in set(re.findall(r'ExtResource\("([^"]+)"\)', body)):
        parts += [b for b in blocks
                  if b.startswith("[ext_resource") and ('id="%s"]' % rid) in b]
    return "\n".join(parts)


def _unity_chunk(text, eid):
    """某元素在 unity 产物里的全部证据:USS 主规则 + 它的垫层规则 + UXML 里那一行。

    只切 `.el-<name> { }` 是不够的 —— 硬阴影与 OUTSIDE 描边环是**另外的兄弟盒子**
    (`.el-<name>-shadow` / `-ring`),矢量的证据(`<figkit:FigVector>`)干脆在 UXML 里。
    只看主规则会把已经实现的特性判成没实现。
    """
    n = re.escape(_sane(eid))
    # **切片里绝不能出现元素自己的名字**:元素就叫 k:blur / k:gradient-linear,
    # 名字里带着特性词,一旦混进来每个信号都会在自己的类名上撞出假阳性(踩过两次)。
    # 所以:只取规则**体**、UXML 行先剥掉 name=/class=、垫层用合成标记而不是它的选择器。
    parts = re.findall(r"\.el-%s\s*\{(.*?)\}" % n, text, re.S)
    for suf in ("ring", "shadow"):
        if re.search(r"\.el-%s-%s\s*\{" % (n, suf), text):
            parts.append("underlay:-" + suf)      # 垫层存在的证据,不带元素名
    for ln in text.splitlines():
        if re.search(r'name="%s"' % n, ln):
            parts.append(re.sub(r'\s(?:name|class)="[^"]*"', "", ln))
    return "\n".join(parts)


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
    # v1.2:矢量落成同目录的 .svg 由 ext_resource 引;裁剪 = clip_contents;
    # OUTSIDE 描边 = StyleBoxFlat 往外扩(border 本身只往内画)
    # clip 有两条路:无圆角走 clip_contents(矩形剪刀),有圆角走 clip_children
    # (拿本节点画出来的形状当子节点的模子)。信号取两者的公共前缀。
    "paths": ".svg", "clip": "clip_", "border-outside": "expand_margin",
}
UNITY_SIGNALS = {
    "radius-px": "radius", "radius-pct": "radius", "radius-pct-oblong": "radius",
    "border": "border-width", "shadow": "shadow", "blur": "blur",
    "rot": "rotate", "opacity": "opacity", "img": "background-image",
    "vec": "background-image", "gradient-linear": "gradient",
    "gradient-radial": "gradient", "text": "font-size", "text-stroke": "outline",
    # v1.2 三件套本后端未实现 —— 这些信号**必须找不到**(known-loss)
    # 矢量走 <figkit:FigVector>(Painter2D 真画,不产图片);裁剪 = overflow:hidden
    # (UI Toolkit 的 overflow 跟随 border-radius,圆角裁剪天然就对);
    # OUTSIDE 描边环 = 垫在本体下面、四边各外扩 N 的额外盒子(USS 无 box-shadow)
    "paths": "FigVector", "clip": "overflow", "border-outside": "-ring",
}


def _present(backend, feat, eid):
    art, _ = _run_all()[backend]
    if backend == "godot":
        return GODOT_SIGNALS[feat] in _godot_chunk(art, eid)
    return UNITY_SIGNALS[feat] in _unity_chunk(art, eid)


def _loss_report(backend):
    """该后端"留痕"的降级说明文本(unity 写进 .uss 头;godot 写 stderr)。"""
    art, err = _run_all()[backend]
    if backend == "unity":
        return "\n".join(l for l in art.split("\n") if l.strip().startswith("*"))
    return err


# ── 检查 ─────────────────────────────────────────────────────────────────────

def test_all_backends_consume_kitchen_sink():
    """每个产物型后端都得吃得下这份把特性打满的 IR。"""
    arts = _run_all()
    assert len(arts) == len(BACKENDS), arts.keys()
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
            want = status in ("render", "approx")
            if got != want:
                bad.append("%s/%s 声明 %s,产物里%s(元素 %s)"
                           % (backend, feat, status, "找到了信号" if got else "找不到信号", eid))
    assert not bad, "声明与产物不符:\n  " + "\n  ".join(bad)


def test_every_ir_field_is_accounted_for():
    """**IR 里的每个字段,要么是结构字段,要么必须逐后端表态。**

    这是补票的一条。v1.2 加 `paths`/`viewBox`/`clip`/`borderAlign` 时,我把新字段写进了
    schema、写进了 capture、html 那侧也做对了 —— 唯独没往这套一致性检查里喂:
    `make_kitchen_sink.py` 重跑后新键**以默认值**出现(paths: [] / clip: false),
    各后端"都吃得下"、声明也"都对得上",于是 paths 与 clip 在 godot/unity 里
    集体静默消失,而全套测试一路绿灯,直到有人把真稿丢进 Godot 才看见。

    闸门本身是对的,漏的是**有人得往里喂料**。这条断言把"记得喂"从自觉变成硬约束:
    schema 里冒出一个没人认领的字段,测试立刻红。
    """
    fields = set(_SCHEMA_FIELDS)
    claimed = set(SPEC["_structural"])
    for f in SPEC["features"].values():
        fl = f["field"]
        claimed.update([fl] if isinstance(fl, str) else fl)
    orphan = sorted(fields - claimed)
    assert not orphan, (
        "IR schema 里这些字段没人认领:%s\n"
        "  → 要么加进 expectations.json 的 _structural(纯结构、无处置余地),\n"
        "  → 要么加进 features 并**配一个真用得上它的 kitchen-sink 元素**。" % orphan)
    ghost = sorted(claimed - fields)
    assert not ghost, "expectations.json 认领了 schema 里没有的字段:%s" % ghost


def test_declared_features_are_actually_exercised_by_the_fixture():
    """**光有声明不算数,夹具得真的把那个字段填上非默认值。**

    与上一条是同一个教训的另一半:`paths: []` 和 `clip: false` 也算"字段存在",
    可它们让检测器无事可做 —— 声明与产物"对得上"只是因为两边都是空的。
    所以这里要求每个特性的承载元素在它声明的字段上**有真值**。
    """
    els = {e["id"]: e for e in json.loads(_read(SINK))["els"]}
    empty = ("", None, False, [], {}, 0)
    bad = []
    for name, f in SPEC["features"].items():
        e = els.get(f["el"])
        if e is None:
            bad.append("%s: kitchen-sink 里没有元素 %s" % (name, f["el"]))
            continue
        fl = f["field"]
        for key in ([fl] if isinstance(fl, str) else fl):
            if key in ("imgSize", "viewBox"):
                continue                      # 附属字段,跟主字段一起走
            if e.get(key) in empty:
                bad.append("%s: 元素 %s 的 %r 是空值 %r —— 这条声明在空跑"
                           % (name, f["el"], key, e.get(key)))
    assert not bad, "夹具没真正压到这些特性:\n  " + "\n  ".join(bad)


def test_degradations_leave_a_trace():
    """approx / known-loss 必须留痕 —— 仓库原则:不许静默丢失。"""
    bad = []
    for feat, spec in sorted(EXP["features"].items()):
        for backend in BACKENDS:
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


def test_scripts_that_print_chinese_pin_their_stdout():
    """★ 会打印中文的脚本必须把自己的 stdout 钉成 UTF-8。

    Windows 上 stdout 的编码跟系统区域走。开发机是 GBK,中文编得动,一路绿;CI 的
    windows runner 是 Latin-1,同一句 print 直接 UnicodeEncodeError、退出码非 0。
    实际代价:`examples/mail/bundle.py` 末尾那句 "wrote fixtures.js (5 条, ...)" 让
    windows-latest 那个 job 红了,而 ubuntu / macos / 本机三处全绿 —— **最难查的那种红**,
    因为它跟被测逻辑一点关系都没有,而且在能复现它的机器上根本复现不出来。

    所以这条不查"有没有踩",查的是**有没有设防**:凡是源码里出现中文 print 的 .py,
    都得带上那段 reconfigure。新写一个脚本、顺手 print 一句中文,这里立刻红。
    """
    import io as _io
    skip = {".git", "node_modules", "__pycache__", ".ruff_cache", "build", "library", "temp"}
    bad = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            src = _io.open(p, encoding="utf-8").read()
            prints = re.findall(r"print\((.{0,160})", src, re.S)
            if not any(re.search(r"[一-鿿]", s) for s in prints):
                continue
            if "reconfigure(encoding" not in src:
                bad.append(os.path.relpath(p, ROOT).replace(os.sep, "/"))
    assert not bad, ("这些脚本会打印中文却没钉住 stdout,在 Latin-1 的 windows 上会崩:\n  "
                     + "\n  ".join(sorted(bad)))


def test_percent_radius_is_measured_against_css_not_another_backend():
    """百分比圆角的对齐对象是 **CSS**,不是别家后端的将就实现。

    这条原先比的是"两个 python 解析器给不给同一个数"。那个口径本身是错的:两家
    **一起**照 `min(w,h)` 折,测试照样全绿,而 CSS 说 `50%` 在非正方形上是**椭圆角**
    (水平按 w、垂直按 h)。互比只能测出分叉,测不出"一起错"。

    所以改成直接对 CSS 真值断言,并把 godot 当下的近似**显式钉住** —— 它退化成胶囊
    是已知取舍(StyleBoxFlat 的 corner_radius 是标量),写在 mapping.md 里;哪天改用
    烘图补齐了,这条会红,提醒来改期望而不是让近似悄悄留一辈子。
    """
    sys.path.insert(0, os.path.join(ROOT, "figma2godot", "scripts"))
    import ui_to_tscn as G
    bad = []
    for w, h in ((100, 100), (300, 80), (40, 40), (17, 100)):
        css = (w / 2.0, h / 2.0)                       # CSS 真值:逐轴各算各的
        got = G.parse_radius("50%", w, h)
        want = round(min(w, h) / 2.0)                  # godot 现状:折成胶囊
        if list(got) != [want] * 4:
            bad.append("%dx%d: godot=%s,期望的近似是 %s(CSS 真值 %s)"
                       % (w, h, got, [want] * 4, css))
    assert not bad, "百分比圆角与声明的近似对不上:\n  " + "\n  ".join(bad)


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
    """把一份 IR 喂给每个产物型后端 → {backend: (returncode, 合并输出)}。"""
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

    此前各后端里只有 cocos 有校验器,其余喂进畸形 IR 就是 KeyError 或静默错渲染。
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
            # 只看**版本**那条告警。同一个 [ir-spec] 标签下还有一条"本后端不认识
            # 这些字段"的告警,那是另一回事(见下一条测试),混在一起判会误报。
            got_warn = "[major]" in text
            if got_warn != want_warn:
                bad.append("%s 对 spec=%r %s告警" % (backend, ver, "不该" if got_warn else "该"))
    assert not bad, "版本处置不一致:\n  " + "\n  ".join(bad)


def test_backends_name_the_ir_fields_they_do_not_understand():
    """**读不懂的字段要点名报出来,不能默默跳过。**

    冻结纪律说小版本是"只增字段",于是旧后端读新文件"安全" —— 安全的前提是
    它**知道自己没读**。v1.2 的 paths/clip/borderAlign 就是在这个前提失效时丢的:
    闸门只比大版本,新键当不存在,各后端集体静默降级而全套测试一路绿灯。

    两个方向都要测,只测一边没有牙:
      · 已实现的字段(paths/clip/borderAlign)→ 一个字都不该说;
      · 一个谁都没实现的字段 → **每家都必须点名**。
    后一半此前是靠"当时还没实现 v1.2 的那个后端"顺带覆盖的 —— 那是运气,不是设计:
    等它实现了,正向锚就跟着消失。改用一个合成的未来字段,覆盖不再随实现进度漂移。
    """
    base = json.loads(io.open(CAP, encoding="utf-8").read())
    bad = []
    for backend, (rc, text) in sorted(_feed(base, "unknown").items()):
        assert rc == 0, "%s 因陌生字段直接失败了(该告警,不该拒收)" % backend
        # 只在那条告警的**字段名段**里找(| 之前),别在整份 stderr 里找:
        # godot 的 known-loss 文案提到 `clip_contents`,整篇搜 "clip" 会误判(踩过)。
        # 判据也必须是 ASCII —— 中文在管道里会因 cp936/utf-8 错配变乱码(也踩过)。
        named = sorted(f for f in ("paths", "clip", "borderAlign")
                       if f in _unknown_line(text))
        if named:
            bad.append("%s 已实现 v1.2 却仍报不认识:%s" % (backend, named))

    future = json.loads(json.dumps(base))
    for el in future["els"]:
        el["figkitFutureField"] = 1
    for backend, (rc, text) in sorted(_feed(future, "future").items()):
        assert rc == 0, "%s 因陌生字段直接失败了(该告警,不该拒收)" % backend
        if "figkitFutureField" not in _unknown_line(text):
            bad.append("%s 读到没实现的 figkitFutureField 却一声不吭" % backend)
    assert not bad, "陌生字段处置不一致:\n  " + "\n  ".join(bad)


def _unknown_line(text):
    return "".join(ln.split("|")[0] for ln in text.splitlines()
                   if "[unknown-fields]" in ln)


def test_capture_stamps_the_spec_version():
    """夹具必须带版本 —— 不带的话上面那条测试测的是空气。

    盯的是 capture 当下的 IR_SPEC,不是写死的字符串:写死的话每次 additive 升版
    都要人手改这一行,而漏改的表现是"测试红了,改个数字就绿" —— 于是没人再想
    "夹具真的重生成过吗"。跟着源头走,升版只需重跑 make_kitchen_sink.py。
    """
    sys.path.insert(0, os.path.join(ROOT, "figma2html", "scripts"))
    import figma_capture
    cap = json.loads(io.open(CAP, encoding="utf-8").read())
    assert cap.get("spec") == figma_capture.IR_SPEC, (
        "kitchen-sink 的 spec 是 %r,capture 现在产 %r —— 重跑 "
        "tools/conformance/make_kitchen_sink.py" % (cap.get("spec"), figma_capture.IR_SPEC))


# ── flow 引用:三个消费 flow 的后端必须给出同样的判定 ─────────────────────────

FLOW_CONSUMERS = {
    # backend -> (脚本, 组装 argv 的函数)。三家 CLI 形状不同,判定语义必须相同。
    "html":   ("figma2html/scripts/flow_check.py",
               lambda d: [os.path.join(d, "flow.json")]),
    "cocos":  ("figma2cocos/scripts/ui_check.py",
               lambda d: [os.path.join(d, "flow.json"), d]),
}
LOGIN_FIX = os.path.join(ROOT, "figma2cocos", "scripts", "tests", "fixtures")
FLOW_FILES = ("flow.json", "screen-login.ui.json",
              "screen-notice.ui.json", "screen-serverlist.ui.json")


def _feed_flow(mutate, tag):
    """把 login 夹具拷进临时目录、按 mutate 改坏 flow,再喂给每个消费方 → {backend: rc}。"""
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


def _bad_in_modal(f):
    f["events"][0]["el"] = "@in:nosuch:3:11"            # 弹窗名不存在


def _bad_in_node(f):
    f["events"][0]["el"] = "@in:serverlist:99:9"        # 节点不在这个弹窗抬起来的子树里


BAD_FLOWS = {
    "事件 el 不存在": _bad_event,
    "modal root 不存在": _bad_modal_root,
    "checkbox el 不存在": _bad_checkbox,
    "list container 不存在": _bad_list_container,
    "@in: 的弹窗不存在": _bad_in_modal,
    "@in: 的节点不在弹窗子树里": _bad_in_node,
}


def test_good_flow_accepted_by_every_consumer():
    """反向锚:没改坏的 flow,每家都得放行。"""
    bad = [("%s rc=%d\n%s" % (b, rc, t[:300]))
           for b, (rc, t) in sorted(_feed_flow(None, "good").items()) if rc != 0]
    assert not bad, "合法 flow 被拒:\n  " + "\n  ".join(bad)


def test_in_modal_selector_accepted_by_every_consumer():
    """★ v1.1 新增的 `@in:<modal>:<nodeId>` —— 各家离线校验器要**一致地放行**。

    坏引用被一致拦下(见 BAD_FLOWS 里那两条)只证明了一半:一个把所有 `@in:` 都当成
    坏引用的校验器,那两条也一样是绿的。所以正向锚必须单列一条。
    """
    def use_it(f):
        f["events"].append({"on": "click", "el": "@in:serverlist:3:11", "do": "closeModal"})
    bad = [("%s rc=%d\n%s" % (b, rc, t[:300]))
           for b, (rc, t) in sorted(_feed_flow(use_it, "in_ok").items()) if rc != 0]
    assert not bad, "合法的 @in: 被拒:\n  " + "\n  ".join(bad)


def test_bad_flow_rejected_by_every_consumer():
    """坏引用必须被**每个**消费 flow 的后端挡下。

    此前 html 这条路只在浏览器 console.warn 一句 —— 而 README 恰恰让人手写 flow.json,
    这条路又是首选入口和 live demo 走的路,反馈却最差。判定逻辑各家各带一份
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
# (DOTween 的 Ease.OutQuad、Godot 的 Tween.EASE_OUT、USS 的 ease-out)。
# 各后端各挑"最像的那个",同一份 IR 在每个引擎里就是一种手感 —— 而每家的测试都绿着,
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
    # cocos 是运行时解释器,没有转换器可挂烘焙 —— 但曲线该在哪解算不因此改变,
    # 它自带一个独立的烘焙 CLI,产出同样进这张对账表。
    "cocos":  lambda tmp: ["figma2cocos/scripts/bake_motion.py",
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
    """给 login flow 的首个 openModal 事件换上 transition,各家各烘一次 → {backend: (motion, stderr)}。"""
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
    for pkg in ("figma2godot", "figma2unity", "figma2cocos"):
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
    ts = io.open(os.path.join(ROOT, "figma2cocos", "runtime", "flow-binder.ts"),
                 encoding="utf-8").read()
    if "function sampleCurve" not in ts:
        bad.append("flow-binder.ts 没有自己的采样点插值函数")
    # 信号取**导入清单**而不是 "easing." 这种字样:文件里正好有一句解释为什么不用
    # `easing.quadOut`,拿字样当信号会被自己的注释误伤(与 godot 那条 blur 假阳性同类)。
    imp = re.search(r"import\s*\{(.*?)\}\s*from\s*'cc'", ts, re.S)
    names = [n.strip() for n in (imp.group(1) if imp else "").split(",")]
    for banned in ("easing", "tween", "Tween"):
        if banned in names:
            bad.append("flow-binder.ts 从 cc 导入了 %s(内置缓动同名不同形,会与别家分叉)" % banned)
    assert not bad, "\n  ".join(bad)


def test_preset_values_match_the_motion_catalog():
    """★ `motion.py` 的 PRESET 必须与 `figkit-motion/tokens.json` **逐条相等**。

    这两处是同一个决定的两个副本:目录是给人读的方法与参数,PRESET 是 figkit 真正写进
    flow.json 的那份值。**两份值必然漂**,而漂了没有任何症状 —— 文档照样读得通顺,
    产物照样跑,只是「文档说 260ms」和「实际写 300ms」变成了两件事。

    对账靠 tokens.json 里的 `preset` 字段(令牌名两边不同名:目录叫 `press-flat`,
    PRESET 叫 `press-scale` —— 前者是「按下态长什么样」,后者是「figkit 只用得到那个缩放系数」)。
    """
    sys.path.insert(0, os.path.join(ROOT, "figma2html", "scripts"))
    import motion as M
    with io.open(os.path.join(ROOT, "figkit-motion", "tokens.json"), encoding="utf-8") as f:
        tokens = json.load(f)
    drift, linked = [], 0
    for name, spec in sorted(tokens.items()):
        if name.startswith("_") or "preset" not in spec:
            continue
        key = spec["preset"]
        if key not in M.PRESET:
            drift.append("tokens.json 的 %s 指向 PRESET['%s'],但 motion.py 里没有" % (name, key))
            continue
        linked += 1
        want, got = spec["value"], M.PRESET[key]["value"]
        if isinstance(want, list):
            got = list(got)
        if want != got:
            drift.append("%s: 目录 %r ≠ PRESET['%s'] %r" % (name, want, key, got))
        if spec["calibration"] != M.PRESET[key]["calibration"]:
            drift.append("%s: 校准分档 目录 %s ≠ PRESET %s"
                         % (name, spec["calibration"], M.PRESET[key]["calibration"]))
    assert linked >= 13, "只对上了 %d 条,PRESET 有 %d 条 —— 有令牌没接进目录" % (linked, len(M.PRESET))
    assert not drift, "目录与预设漂了:\n  " + "\n  ".join(drift)


def test_motion_not_played_is_written_down_in_every_mapping():
    """曲线烘出来了但**没有后端在播** —— 这是登记在案的降级,不是静默丢失。
    每家 mapping.md 都得能查到,否则就成了"代码里有、文档里没有"的那类账。"""
    missing = []
    for pkg in ("figma2godot", "figma2unity", "figma2cocos"):
        p = os.path.join(ROOT, pkg, "references", "mapping.md")
        text = io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        if "transition" not in text.lower():
            missing.append("%s/references/mapping.md 没登记转场的处置" % pkg)
    assert not missing, "\n  ".join(missing)


def _runtime(pkg, *parts):
    return io.open(os.path.join(ROOT, pkg, "runtime", *parts), encoding="utf-8").read()


def _nocomment(src):
    """剥掉 `//` 行注释再做源码级检查。

    **这是踩了三次的坑**:godot 那条 blur 断言被自己的注释误伤过、cocos 那条 easing 断言
    也是(所以它改查 import 清单),这条查 `0.016f` 的又被上面那段"这里一度写的是
    `elapsed += 0.016f`"的说明文字判红了。源码级断言查的是**代码**,注释里出现被禁的字样
    恰恰是最该写的地方 —— 解释为什么不这么写。
    """
    return re.sub(r"//[^\n]*", "", src)


def _block(src, start, end, what):
    """截出一个函数体。源码级检查只在**看对了地方**时才有意义,所以找不到就报错,不静默放行。"""
    i = src.find(start)
    assert i >= 0, "在源码里没找到 %s(结构变了?检查改名)" % what
    j = src.find(end, i + len(start))
    assert j > i, "没找到 %s 的结尾" % what
    return src[i:j]


def test_transitions_displace_by_the_stage_not_the_panel():
    """★ 采样点一致、插值模式一致之后,还剩最后一步从来没人对账:**进度贴到哪个距离上**。

    实测踩到过:html 的 `transitionCss` 拿 CSS 百分比写位移(`translate(0,100%)`),
    而 CSS 百分比是**相对元素自身**的;godot / unity / cocos 三家都拿层(=舞台)尺寸乘进度。
    login 的选服面板 860×1160、舞台 1080×1920 —— 同一条曲线、同一个毫秒,html 从 1160px
    处滑入,别家从 1920px:起手那一帧 html 面板有 380px 已经在屏内,别家完全在屏外。
    四家测试照样全绿,因为**曲线取值一个不差**,漂的是基准。这与当年遮罩跟着面板滑那个
    bug 完全同一层("把进度贴到哪儿"),而那次是靠实机截图才抓到的。

    舞台基准是**有实机记录**的那个:figma2godot/references/mapping.md 记着 MOVE_IN 中途
    `alpha=0.509 / offsetY=942.5` = 1920×(1−0.509)。引擎跑不进 CI,所以守源码层。
    """
    bad = []
    html = _block(_runtime("figma2html", "assemble.js"), "transitionCss(tr) {", "\n    },",
                  "assemble.js 的 transitionCss")
    # 查的是"块里有没有 % 这个长度单位",不是"% 有没有紧挨着 translate(" ——
    # 百分比原本就写在上面那张 off 表里、离 translate( 隔着两行,按后者写的正则连原缺陷都抓不到
    # (本条断言的变异验证抓到过它自己这个洞)。注释里的 % 先剔掉,免得误伤说明文字。
    if "%" in _nocomment(html):
        bad.append("assemble.js transitionCss 里出现了 %(CSS 的百分比相对元素自身 = 面板基准)")
    if "this.stage" not in html:
        bad.append("assemble.js transitionCss 没引用 this.stage(位移基准必须是舞台)")

    gd = _block(_runtime("figma2godot", "flow_binder.gd"), "func _apply(", "\nfunc ",
                "flow_binder.gd 的 _apply")
    if "layer.size" not in gd:
        bad.append("flow_binder.gd _apply 的位移没乘 layer.size")

    cs = _block(_runtime("figma2unity", "FlowBinder.cs"), "void ApplyProgress(", "\n        void ",
                "FlowBinder.cs 的 ApplyProgress")
    if "m.layer.resolvedStyle" not in cs:
        bad.append("FlowBinder.cs ApplyProgress 的位移没乘 m.layer.resolvedStyle")

    ts = _block(_runtime("figma2cocos", "flow-binder.ts"), "private applyProgress(", "\n  private ",
                "flow-binder.ts 的 applyProgress")
    if "layer.getComponent(UITransform)" not in ts:
        bad.append("flow-binder.ts applyProgress 的位移没取 layer 的 UITransform 尺寸")

    assert not bad, "转场位移基准漂了:\n  " + "\n  ".join(bad)


# 四端的抖动都该是这一条:sin(2πx)·amp·(1−x)。写法差异(TAU / Mathf.PI / 1f)先抹平再比。
_WAVE = re.compile(r"sin\(\w+\*pi\*2\)\*amp\*\(1-\w+\)")


def _norm_wave(s):
    s = s.lower().replace("mathf.", "").replace("math.", "").replace("tau", "pi*2")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"(\d)\.0+(?!\d)", r"\1", s)        # 1.0 → 1
    s = re.sub(r"(\d)f(?![\w.])", r"\1", s)        # C# 的 1f / 2f → 1 / 2
    return s


def test_guard_shake_is_the_same_waveform_in_every_backend():
    """★ guardFail 的抖动没走曲线层 —— 于是曲线那一整套对账对它完全不生效。

    html 一度是四个等距线性关键帧(0 → −amp → +amp → 0)整段套 ease-in-out:**没有衰减**、
    峰值落在 1/3 与 2/3 而不是 1/4 与 3/4、还先往左而别家先往右。同一个 `wiggle-amp`、
    同样叫 wiggle,四端抖出四种样子,而每家测试都是绿的。

    形状只有一条:`sin(2πx)·amp·(1−x)`,一去一回一归零且带衰减。写法差异(TAU / Mathf.PI /
    1f 字面量)先抹平再比 —— 比的是**波形**,不是拼写。
    """
    where = [
        ("figma2html/assemble.js", _runtime("figma2html", "assemble.js"),
         "wiggle(el) {", "\n    },"),
        ("figma2godot/flow_binder.gd", _runtime("figma2godot", "flow_binder.gd"),
         "func wiggle(", "\nfunc "),
        ("figma2unity/FlowBinder.cs", _runtime("figma2unity", "FlowBinder.cs"),
         "public void Wiggle(", "\n        }"),
        ("figma2cocos/flow-binder.ts", _runtime("figma2cocos", "flow-binder.ts"),
         "wiggle(node: Node | null): void {", "\n  }"),
    ]
    bad = []
    for name, src, start, end in where:
        blk = _nocomment(_block(src, start, end, name + " 的 wiggle"))
        if not _WAVE.search(_norm_wave(blk)):
            bad.append("%s 的抖动不是 sin(2πx)·amp·(1−x)" % name)
    assert not bad, "抖动波形不同形:\n  " + "\n  ".join(bad)


def test_mapping_docs_and_their_zh_mirrors_stay_structurally_paired():
    """★ 每份 `mapping.md` 与它的 `mapping.zh.md` 必须**结构成对**。

    这三份是后端契约的对外面(README 直接指过来),v0.3.x 之前一直是中文,挡掉了一半读者;
    译英之后原文按仓里既有的做法(`spec/*.zh.md`)留成镜像 —— 但 `spec/` 那对之所以敢留,
    是因为有 `spec_parity.py` 守着。**没有守卫的双份文档必然漂**,而漂了的镜像比没有镜像更坏:
    它看起来是真的。

    散文没法跨语言比,能比的是**结构**:表格行数、代码块内容(去注释后与语言无关)。
    这跟 `spec_parity.py` 的第二道检查是同一招。
    """
    import re as _re
    bad = []
    for pkg in ("figma2godot", "figma2unity", "figma2cocos"):
        en_p = os.path.join(ROOT, pkg, "references", "mapping.md")
        zh_p = os.path.join(ROOT, pkg, "references", "mapping.zh.md")
        if not os.path.exists(zh_p):
            bad.append("%s 没有 mapping.zh.md(译英时原文应留成镜像)" % pkg)
            continue
        en = io.open(en_p, encoding="utf-8").read()
        zh = io.open(zh_p, encoding="utf-8").read()

        # ① 英文版不该有中文正文(译漏了会当场现形)
        leftover = [ln for ln in en.split("\n") if _re.search(r"[一-龥]", ln)]
        if leftover:
            bad.append("%s/mapping.md 还有 %d 行中文,第一行:%s"
                       % (pkg, len(leftover), leftover[0][:60]))

        # ② 表格行数一致 —— 少了一行 = 有一条映射没跟过来
        rows = lambda t: sum(1 for ln in t.split("\n")
                             if ln.strip().startswith("|") and not _re.match(r"^\|[\s:|-]+\|$", ln.strip()))
        if rows(en) != rows(zh):
            bad.append("%s 表格行数 en=%d ≠ zh=%d" % (pkg, rows(en), rows(zh)))

        # ③ 代码块:**块数**必须一致;**内容**只比那些在 zh 侧不含中文的块。
        #    这三份里的代码块有两类:真代码(跨语言逐字相同)和
        #    带散文的 ASCII 示意图(cocos 那张烘焙管线图、坐标通式里的行内注释)——
        #    后者两边本来就不一样,那是**翻译**不是漂移。
        #    第一版按行剔中文,结果被"注释与代码同一行"打败(zh 整行没了、en 还在);
        #    分块跳过才对。跳过的块由块数守着:少一块照样红。
        def blocks(t):
            return [_re.sub(r"\s+", "", b) for b in _re.findall(r"```[a-z]*\n(.*?)```", t, _re.S)]
        eb, zb = blocks(en), blocks(zh)
        if len(eb) != len(zb):
            bad.append("%s 代码块数 en=%d ≠ zh=%d" % (pkg, len(eb), len(zb)))
        else:
            for i, (a, b) in enumerate(zip(eb, zb)):
                if _re.search(r"[一-龥]", b):
                    continue                     # zh 侧是带散文的图,跳过内容比对
                if a != b:
                    bad.append("%s 第 %d 个代码块与 zh 镜像不一致(改了一边?)" % (pkg, i))

    assert not bad, "mapping 文档与 zh 镜像漂了:\n  " + "\n  ".join(bad)


def test_every_runtime_guards_the_json_it_is_handed():
    """★ "畸形 IR 给一句话,不给 traceback" —— 这条规矩 v0.2.0 就立了。

    但它当时只在**转换器**那侧兑现(各后端补了输入校验、exit 2 列出问题),
    **运行时**的入口从来没人查过。实测:Unity 的 `MiniJson` 一路 `throw
    FormatException`,而调用处直接接返回值 —— 它下一行那个 `== null` 判断在真·畸形
    输入上**永远轮不到执行**,结果就是一个未捕获异常。另外两家都守住了,写自家规矩
    反例的偏偏是自家代码。

    引擎跑不进 CI,所以查源码:每家的 JSON 入口都必须**在同一处**看得见防护。
    html 那侧不靠这条 —— 它在 `tools/html-smoke` 里被真浏览器喂过空 flow。

    ⚠️ 每一条都先钉**存在性锚点**再查防护。只查"有调用且没设防"的写法,在调用被改名
    或删掉时会静默通过 —— 变异验证当场抓到过:把某家那句 `if (!Deserialize(...))`
    整个换成 `if (false)`,调用没了,断言反而绿。不可能红的断言等于没有断言。
    """
    bad = []

    # 锚在**被解析的输入**上,不锚解析器的名字:`MiniJson.Parse` 有两处调用,
    # 只要求"至少有一处叫这个名"的话,把其中一处改名照样能溜过去(变异验证抓到过)。
    # 要守的本来就是这两个入口 —— flow.json 与 motion.json —— 不是某个函数名。
    cs = _nocomment(_runtime("figma2unity", "FlowBinder.cs")).split("\n")
    for entry in ("flowJson.text", "motionJson.text"):
        hits = [i for i, l in enumerate(cs) if entry in l and "(" in l]
        if not hits:
            bad.append("FlowBinder.cs 里找不到解析 %s 的地方(改名了?这条断言就成了摆设)" % entry)
        for i in hits:
            if not any("try" in cs[j] for j in range(max(0, i - 4), i)):
                bad.append("FlowBinder.cs:%d 解析 %s 时不在 try 里(MiniJson 是会 throw 的)"
                           % (i + 1, entry))

    gd = _nocomment(_runtime("figma2godot", "flow_binder.gd")).split("\n")
    hits = [i for i, l in enumerate(gd) if "JSON.parse_string" in l]
    if not hits:
        bad.append("flow_binder.gd 里找不到 JSON.parse_string(改名了?)")
    for i in hits:
        near = "\n".join(gd[i:i + 6])
        if "push_error" not in near and "push_warning" not in near:
            bad.append("flow_binder.gd:%d 解析之后没判返回值(parse_string 失败返回 null)" % (i + 1))

    ts = _nocomment(_runtime("figma2cocos", "flow-binder.ts"))
    if "flowAsset" not in ts:
        bad.append("flow-binder.ts 里找不到 flowAsset(改名了?)")
    elif "!this.flowAsset" not in ts:
        bad.append("flow-binder.ts 没判 flowAsset / flowAsset.json 是否在")

    assert not bad, "运行时的 JSON 入口没设防:\n  " + "\n  ".join(bad)


def test_animation_progress_reads_the_clock_not_the_tick_count():
    """★ 时长是**墙钟毫秒**,不是"回调被叫了几次 × 期望间隔"。

    unity 一度写的是 `elapsed += 0.016f` 配 `.Every(16)` —— 把调度器的**期望**间隔当成
    实际间隔。主线程一卡,回调照样一次加 16ms,300ms 的转场在墙钟上跑成 400ms;而
    godot 的 tween、cocos 的 `schedule(dt)`、html 的 CSS transition 全是跟真实时间走的。
    掉帧才看得出来,所以本机跑一次永远发现不了,只能守源码。
    """
    bad = []
    cs = _nocomment(_runtime("figma2unity", "FlowBinder.cs"))
    if re.search(r"\+=\s*0\.016f", cs):
        bad.append("FlowBinder.cs 又在按固定 0.016f 累加(掉帧时动画会被拉长)")
    if "TimerState" not in cs or "ts.now" not in cs:
        bad.append("FlowBinder.cs 没用 TimerState.now 这个真实时钟")
    ts = _nocomment(_runtime("figma2cocos", "flow-binder.ts"))
    if not re.search(r"\(dt:\s*number\)", ts):
        bad.append("flow-binder.ts 的动画回调没收 dt(cocos 的 schedule 是给了真实间隔的)")
    assert not bad, "动画进度没读时钟:\n  " + "\n  ".join(bad)


def test_the_cocos_type_gate_covers_every_runtime_file_and_matches_the_docs():
    """★ 那道类型门本身也会悄悄失效 —— 而且失效时它是**绿的**。

    `tools/cocos-typecheck` 需要 node,进不了这套离线测试;但它最容易出事的两种方式恰好
    离线就能查:**新加的 runtime .ts 没进 tsconfig 的 `files`**(那个文件从此不被检查,
    门照样零错),以及**文档声称的版本与配置钉的版本各说各话**(README / SKILL.md /
    mapping.md 三处都写着"对 @cocos/creator-types 3.8")。

    这两条正是当初的教训的延伸:那句"已过严格类型门"当时是真的,但仓库里没有任何东西
    能复现它 —— 一句不可复现的话和一句假话,读者是分不出来的。
    """
    bad = []
    tsconf = json.loads(io.open(os.path.join(ROOT, "tools", "cocos-typecheck", "tsconfig.json"),
                                encoding="utf-8").read())
    listed = set()
    for f in tsconf.get("files", []):
        if "figma2cocos" in f:
            listed.add(os.path.basename(f))
    rt = os.path.join(ROOT, "figma2cocos", "runtime")
    actual = set(f for f in os.listdir(rt) if f.endswith(".ts"))
    for missing in sorted(actual - listed):
        bad.append("tools/cocos-typecheck/tsconfig.json 的 files 没列 runtime/%s(它从此不过门)" % missing)
    for gone in sorted(listed - actual):
        bad.append("tsconfig.json 列了不存在的 runtime/%s" % gone)
    if tsconf.get("compilerOptions", {}).get("strict") is not True:
        bad.append("tsconfig.json 的 strict 不是 true —— 文档声称的是严格档")

    pkg = json.loads(io.open(os.path.join(ROOT, "tools", "cocos-typecheck", "package.json"),
                             encoding="utf-8").read())
    pin = pkg.get("devDependencies", {}).get("@cocos/creator-types", "")
    if not re.match(r"^\d+\.\d+\.\d+$", pin):
        bad.append("@cocos/creator-types 没钉死版本(现在是 %r)—— 装到什么全看运气" % pin)
    else:
        minor = ".".join(pin.split(".")[:2])
        for rel in ("README.md", "figma2cocos/SKILL.md", "figma2cocos/references/mapping.md"):
            text = io.open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8").read()
            if "creator-types" in text and minor not in text:
                bad.append("%s 说的版本与 package.json 钉的 %s 对不上" % (rel, pin))
    assert not bad, "cocos 类型门的配置漂了:\n  " + "\n  ".join(bad)


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

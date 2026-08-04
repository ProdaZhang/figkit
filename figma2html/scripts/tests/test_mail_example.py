# -*- coding: utf-8 -*-
"""examples/mail(邮箱示例)的生成物与声明必须自洽。

login 那个示例演的是**管线**(捕获 → IR → 各后端),界面刻意做到最小,而且它是
`make_fixture.py` 合成出来的 —— 手工搭的节点树,永远只长成作者想到的样子。

mail 演的是另一件事:**一份真的 figma 稿**。它不是合成的,所以这里守不了
"重跑生成器逐字节一致"那条(要重跑就得有 figma 文件和 token)。换来的是合成夹具
**够不着**的几类账,而它们恰恰是真稿翻车的地方:

  1. `fixtures.js` 新鲜 —— 它是 file:// 下唯一的数据来源,过期了页面照样渲染,
     只是渲染的是旧内容(最阴的一种坏)。这条能守,因为 bundle.py 的输入就在仓里。
  2. flow.json 的引用全都解析得开(直接跑 flow_check.py,与用户手上是同一条路径)。
  3. **素材齐**:四屏引用的每张图都在 assets/ 里,且 assets/ 里没有没人引用的图。
     合成夹具没有真图片,这条只有真稿能测 —— 而漏一张的表现是"那块儿是透明的",
     截图里看着像设计如此。
  4. **字体齐**:app.html 里 @font-face 指到的 woff2 真的在 fonts/ 里。同上,
     缺了就是整屏回退到系统字体,看起来只是"字有点不一样"。
  5. 默认动效是 apply_defaults 补出来的(带 source)、且幂等。
  6. 生成物 LF、无 BOM。
"""
import io
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.abspath(os.path.join(_HERE, "..", "..", "examples", "mail"))
ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
SCREENS = ["screen-list.ui.json", "screen-read.ui.json",
           "screen-readclaimed.ui.json", "screen-readplain.ui.json"]


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def _json(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def test_bundle_is_fresh():
    """fixtures.js = bundle.py(flow.json + 四屏)。改了 json 忘了重跑就会过期。

    不写临时目录:bundle.py 就往示例目录里写。所以先记住原文、跑一遍、比对、再原样写回 ——
    测试**不能**留下副作用,不然"跑了测试"本身就成了让它变绿的手段。
    """
    p = os.path.join(EX, "fixtures.js")
    before = _read(p)
    try:
        r = subprocess.run([sys.executable, os.path.join(EX, "bundle.py")], cwd=EX,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, "bundle.py 退出码 %d\n%s" % (r.returncode, r.stderr)
        assert _read(p) == before, ("fixtures.js 与 flow.json/四屏 ui.json 不同步 —— "
                                    "在 examples/mail/ 里跑 `python3 bundle.py` 并提交结果")
    finally:
        with open(p, "wb") as f:
            f.write(before)


def test_flow_references_resolve():
    """跑真正的 flow_check.py,而不是在这里另写一份判定 —— 另写的那份会和它漂。"""
    r = subprocess.run([sys.executable,
                        os.path.join(ROOT, "figma2html", "scripts", "flow_check.py"),
                        os.path.join(EX, "flow.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, "flow_check 不放行:\n%s" % ((r.stdout or "") + (r.stderr or ""))


def test_every_referenced_asset_ships_and_nothing_extra_does():
    used = set()
    for fn in SCREENS:
        for el in _json(os.path.join(EX, fn))["els"]:
            if el.get("img"):
                used.add(el["img"])
    have = {"assets/" + n for n in sorted(os.listdir(os.path.join(EX, "assets")))}
    missing = sorted(used - have)
    orphan = sorted(have - used)
    assert not missing, "四屏引用了仓里没有的素材:%s" % missing
    assert not orphan, "assets/ 里有没人引用的素材(删掉或找出该引它的那屏):%s" % orphan


def test_every_font_face_ships():
    html = io.open(os.path.join(EX, "app.html"), encoding="utf-8").read()
    faces = re.findall(r"url\('([^']+\.woff2)'\)", html)
    assert faces, "app.html 里没有 @font-face —— 示例会整屏回退到系统字体"
    for rel in faces:
        assert os.path.exists(os.path.join(EX, rel)), "app.html 指到的 %s 不在仓里" % rel


def test_preset_motion_is_generated_and_idempotent():
    """默认动效必须是 apply_defaults 补出来的(带 source),且再跑一遍不多出东西。"""
    sys.path.insert(0, os.path.join(ROOT, "figma2html", "scripts"))
    import motion

    flow = _json(os.path.join(EX, "flow.json"))
    assert flow["motion"]["press"]["source"] == "preset:base", \
        "按压动效应当由预设补出来并留下 source"
    _, added = motion.apply_defaults(json.loads(json.dumps(flow)))
    assert not added, "apply_defaults 不幂等,又补出了:%s" % added


def test_generated_files_are_lf_and_bom_free():
    for fn in SCREENS + ["fixtures.js", "flow.json"]:
        b = _read(os.path.join(EX, fn))
        assert b"\r\n" not in b, "%s 含 CRLF" % fn
        assert not b.startswith(b"\xef\xbb\xbf"), "%s 有 BOM" % fn


def _run():
    ok = True
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception as e:                              # noqa: BLE001
                ok = False
                print("FAIL", name, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)

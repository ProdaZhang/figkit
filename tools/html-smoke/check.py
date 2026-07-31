# -*- coding: utf-8 -*-
"""html-smoke — 在真浏览器里跑 `figma2html/runtime` 的行为冒烟。

    python3 tools/html-smoke/check.py            # 需要 Edge/Chromium(找不到就设 EDGE_PATH)

**为什么要它。** `assemble.js` / `render.js` 是六个后端里唯一**实跑过**的参照实现,
另外五家的 binder 都按它写 —— 而它自己一条自动化测试都没有(figma2html 那 70 条全在
python 侧:capture / flow_check / flow_from_figma / motion / 夹具新鲜度)。README 里
它那一栏写的是"Edge headless screenshot",也就是**人眼看过**。

代价是明摆着的:转场位移基准漂了、抖动波形和三个引擎不同形,都在这个洞里活了下来,
直到有人把四份 binder 并排读了一遍才发现。所以这里断言的是**行为的数**,不是像素:
面板滑了多远、遮罩动没动、guard 拦没拦、勾出现没出现 —— 数字能进 assert,截图不能。

不需要 Pillow:纯标准库 + `--dump-dom` 把 driver 量到的 JSON 读回来。
和 `tools/docs-assets`、`tools/cocos-typecheck` 同理,它要浏览器,所以在 `tools/` 里、
不进 `run_all_tests.py`(那套必须离线纯标准库),由 CI 单开一个 windows job 跑。
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXAMPLE = os.path.join(ROOT, "figma2html", "examples", "login")

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/microsoft-edge",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]

STAGE_H = 1920          # flow.stage.h —— 位移基准就该是它
PANEL = {"x": 110, "y": 380, "w": 860, "h": 1160}       # screen-serverlist.ui.json 里的 3:10


def find_browser():
    env = os.environ.get("EDGE_PATH")
    if env and os.path.exists(env):
        return env
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Edge/Chromium(可设 EDGE_PATH)")


def run_case(browser, page, n):
    tmp = tempfile.mkdtemp(prefix="figkit_smoke_")
    try:
        r = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                            "--hide-scrollbars", "--window-size=540,996",
                            "--virtual-time-budget=3000",
                            "--user-data-dir=%s" % tmp, "--dump-dom",
                            "file:///%s?case=%d" % (page.replace("\\", "/"), n)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        m = re.search(r"FIGKIT-SMOKE (\{.*?\})</title>", r.stdout or "")
        if not m:
            raise SystemExit("case %d 没量到(页面没跑起来?)\n%s" % (n, (r.stdout or "")[:600]))
        return json.loads(m.group(1))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


@check("modal_overlays_at_ir_coordinates_with_rows_cloned")
def _c0(m):
    """弹窗子树被抽出来叠加后,几何仍是相对帧的绝对 px —— 这是 subtreeOf 的全部语义。"""
    bad = []
    for k, want in PANEL.items():
        if abs(m["panel"][k] - want) > 1:
            bad.append("面板 %s=%s,IR 里是 %s" % (k, m["panel"][k], want))
    if m["rows"] != 4:
        bad.append("列表克隆出 %d 行(夹具是 4 条)" % m["rows"])
    # 四行必须**各不相同**。行是克隆首行来的、模板自带文字,所以"每行非空"这种断言
    # 在 rowFn 根本没被调用时照样是绿的 —— 变异验证就是这么抓到它的。
    texts = [t for t in m["rowTexts"] if t]
    if len(texts) != m["rows"] or len(set(texts)) != m["rows"]:
        bad.append("四行的文字不是四个互不相同的值(%r)—— rowFn 没把每行的数据填进去" % m["rowTexts"])
    if m["backdrops"] != 1:
        bad.append("遮罩有 %d 个" % m["backdrops"])
    return bad


@check("move_in_starts_a_full_stage_away_and_the_backdrop_stays_put")
def _c1(m):
    """★ 这条就是那个真漂过的缺陷。

    停在 **0ms** 时进度必然是 0,位移必然等于**基准本身** —— 不掺缓动,断言干净:
    舞台基准 → 1920;面板基准(CSS 百分比)→ 1160。差 760px,而两边曲线取值一个不差。
    顺带钉住遮罩:transform 只许贴面板本体,遮罩跟着淡、不跟着滑。
    """
    bad = []
    if abs(m["panelOffsetY"] - STAGE_H) > 2:
        extra = "(=面板自己的高,说明又按元素百分比算了)" if abs(m["panelOffsetY"] - PANEL["h"]) <= 2 else ""
        bad.append("MOVE_IN 起点偏移 %spx,应当是舞台高 %d%s" % (m["panelOffsetY"], STAGE_H, extra))
    if abs(m["backdropOffsetY"]) > 2:
        bad.append("遮罩跟着面板滑了 %spx —— transform 贴到层上了" % m["backdropOffsetY"])
    if abs(m["backdropH"] - STAGE_H) > 2:
        bad.append("遮罩没铺满舞台(高 %s)" % m["backdropH"])
    return bad


@check("guard_blocks_and_says_so")
def _c2(m):
    bad = []
    if m["sentWhileBlocked"] != 0:
        bad.append("guard 没拦住,send 被调了 %d 次" % m["sentWhileBlocked"])
    if m["agreedBefore"]:
        bad.append("初始 state.agreed 就是 true,这条用例没意义")
    if m["shakeAnimations"] < 1:
        bad.append("被拦下时一个动画都没有 —— 对玩家又是彻底的沉默")
    return bad


@check("checkbox_binding_toggles_both_ways")
def _c3(m):
    bad = []
    if m["markAfterCheck"] != "✓":
        bad.append("勾上之后没出现 ✓(是 %r)" % m["markAfterCheck"])
    if m["markAfterUncheck"] != "":
        bad.append("取消之后 ✓ 还在(是 %r)" % m["markAfterUncheck"])
    if m["flag"] is not False:
        bad.append("点两次之后 flag 是 %r,应当回到 False" % m["flag"])
    return bad


def main():
    browser = find_browser()
    src = io.open(os.path.join(EXAMPLE, "app.html"), encoding="utf-8").read()
    page = os.path.join(EXAMPLE, "_smoke.html")
    io.open(page, "w", encoding="utf-8", newline="").write(
        src.replace("</body>", '  <script src="_smoke.js"></script>\n</body>'))
    shutil.copy(os.path.join(HERE, "driver.js"), os.path.join(EXAMPLE, "_smoke.js"))
    failed = []
    try:
        for i, (name, fn) in enumerate(CHECKS):
            bad = fn(run_case(browser, page, i))
            if bad:
                failed.append(name)
                print("FAIL " + name)
                for b in bad:
                    print("     " + b)
            else:
                print("PASS " + name)
    finally:
        for f in (page, os.path.join(EXAMPLE, "_smoke.js")):
            if os.path.exists(f):
                os.remove(f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

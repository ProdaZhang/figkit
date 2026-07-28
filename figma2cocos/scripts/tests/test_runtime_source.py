# -*- coding: utf-8 -*-
"""runtime/*.ts 的**源码级**守卫。

诚实边界:这不是行为验证 —— TS 运行时要 Creator 或 tsc + @cocos/creator-types 才跑得起来,
本套是纯标准库,跑不了。这里只钉住几条曾经出过事、且能在源码层确定性检出的规约。
真行为验证见 README 状态矩阵里 cocos 那格(TS 严格类型检查),以及将来在 Creator 里的实跑。

守的第一条 = 百分比圆角:capture 对**每个 figma ELLIPSE** 都产 `radius: "50%"`
(figma_capture.py 的 ELLIPSE 分支),而 JS 的 `parseFloat("50%")` 返回 **50** 不报错,
于是百分比会被静默当成 50px —— 错得还随元素尺寸变。修法是按 min(w,h) 折算,
口径与 figma2godot / figma2unreal 一致。
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(os.path.dirname(os.path.dirname(HERE)), "runtime")


def _src(name):
    with open(os.path.join(RUNTIME, name), encoding="utf-8") as f:
        return f.read()


def test_parse_radius_takes_element_size():
    """签名必须能拿到 w/h,否则百分比无从折算。"""
    m = re.search(r"export function parseRadius\(([^)]*)\)", _src("parse-css.ts"))
    assert m, "parse-css.ts 里找不到 parseRadius 的导出签名"
    args = m.group(1)
    assert "w" in args and "h" in args, "parseRadius 没有接收元素尺寸: %r" % args


def test_parse_radius_handles_percent():
    """必须有显式的百分比分支;只靠 parseFloat 会把 '50%' 静默读成 50。"""
    body = _src("parse-css.ts")
    m = re.search(r"export function parseRadius\(.*?\n\}", body, re.S)
    assert m, "抓不到 parseRadius 函数体"
    fn = m.group(0)
    assert "%" in fn and "endsWith" in fn, "parseRadius 没有处理百分比的分支"
    assert "Math.min" in fn, "百分比应按 min(w,h) 折算(与 godot/unreal 同口径)"


def test_call_site_passes_size():
    """改了签名却没改调用点,等于没修。"""
    calls = re.findall(r"parseRadius\(([^)]*)\)", _src("figma-ui.ts"))
    assert calls, "figma-ui.ts 里没有 parseRadius 调用"
    for c in calls:
        assert c.count(",") >= 2, "调用点没把尺寸传进去: parseRadius(%s)" % c


def test_known_loss_paths_still_log():
    """known-loss 必须留痕,不许静默丢失(仓库通用原则)。"""
    body = _src("figma-ui.ts")
    assert "console.warn" in body, "figma-ui.ts 里一条 known-loss 告警都没有"


def _run():
    ok = True
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:
                ok = False; print("FAIL", n, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)

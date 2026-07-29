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


def test_motion_is_interpolated_not_re_solved():
    """引擎侧只做**线性**插值,一条曲线都不许自己算。

    Creator 的 `easing.quadOut` 之流与 figma 给的曲线**同名不同形**;各后端各挑"最像的",
    同一份 IR 就是六种手感,而每家测试照样绿(实测 easeOutCubic 与 cubic-bezier(.23,1,.32,1)
    最大差 19.8 个百分点)。曲线在 scripts/bake_motion.py 里解算,这里只插值。
    另:采样点一致只保证**关键帧上**一致,帧间插值模式必须也是线性 —— godot/unity 都在这儿栽过。
    """
    body = _src("flow-binder.ts")
    assert "function sampleCurve" in body, "flow-binder.ts 没有采样点插值函数"
    m = re.search(r"function sampleCurve\(.*?\n\}", body, re.S)
    assert m and "/" in m.group(0) and "-" in m.group(0), "sampleCurve 看着不像在做线性插值"
    imported = re.search(r"import\s*\{(.*?)\}\s*from\s*'cc'", body, re.S)
    names = [n.strip() for n in (imported.group(1) if imported else "").split(",")]
    for banned in ("easing", "tween", "Tween"):
        assert banned not in names, "从 cc 导入了 %s —— 内置缓动会与别家分叉" % banned


def test_transform_goes_on_the_panel_not_the_layer():
    """★ 位移/缩放只贴面板本体,遮罩只跟着淡。

    早先 html/godot/unity 三端同构同病:transform 贴在弹窗**层**上,而 backdrop 是层的子节点,
    于是遮罩跟着面板一起滑/缩 —— 顶部不变暗、四边缩进露出底屏。曲线取值一个不差,
    是实机截图才抓到的。这条守着 cocos 别再犯一遍。
    """
    body = _src("flow-binder.ts")
    m = re.search(r"private applyProgress\(.*?\n  \}", body, re.S)
    assert m, "抓不到 applyProgress 函数体"
    fn = m.group(0)
    assert "setOpacity(layer" in fn, "层上没有做整体淡入淡出"
    for bad in ("setScale(layer", "layer.setPosition"):
        assert bad not in fn, "%s:位移/缩放贴到层上了,遮罩会跟着动" % bad
    assert "scaleAboutCenter(panel" in fn and "panel.setPosition" in fn, \
        "面板本体没有承接位移/缩放"


def test_scaling_compensates_for_the_top_left_anchor():
    """锚点是 (0,1),node.scale 以左上角为基准 —— 不补位置,面板会往右下角坍缩。"""
    body = _src("flow-binder.ts")
    m = re.search(r"private scaleAboutCenter\(.*?\n  \}", body, re.S)
    assert m, "抓不到 scaleAboutCenter 函数体"
    fn = m.group(0)
    assert "setScale" in fn and "setPosition" in fn, "只设了 scale 没补位置"
    assert "(1 - s) / 2" in fn, "位置补偿不是 (1−s)/2 的形状"


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

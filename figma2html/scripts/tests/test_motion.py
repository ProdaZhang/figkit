# -*- coding: utf-8 -*-
"""motion.py 的测试。曲线是**数值**代码 —— 错了不会崩,只会手感不对,所以每条都钉住数。

三类断言:
  1. 与**独立求法**对照(牛顿解 vs 纯二分解)—— 同一条曲线两种解法必须重合,
     这是唯一不靠"我算的等于我算的"的自证。
  2. 与**外部实测值**对照 —— 两条取自动效规范里量过的数(easeOutCubic 的最大偏差、
     easeOutBack 的过冲峰值)。它们是本文件之外的事实,能钉住"整条曲线的形状"。
  3. 物理性质 —— 阻尼比 <1 必过冲、=1 必不过冲、>1 必单调,这是数学不是口味。
"""
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import motion as M  # noqa: E402


def _bisect_solver(x1, y1, x2, y2):
    """同一条 cubic-bezier 的**纯二分**解法 —— 与被测的牛顿解法完全独立。"""
    def bez(a, b, t):
        return 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t * t * b + t ** 3

    def f(x):
        lo, hi = 0.0, 1.0
        for _ in range(80):
            t = (lo + hi) / 2
            if bez(x1, x2, t) < x:
                lo = t
            else:
                hi = t
        return bez(y1, y2, (lo + hi) / 2)
    return f


# ── 1. 两种解法必须重合 ──────────────────────────────────────────────────────
def test_newton_agrees_with_independent_bisection():
    for curve in [(.23, 1, .32, 1), (.42, 0, .58, 1), (.32, .72, 0, 1), (.34, 1.56, .64, 1)]:
        a, b = M.bezier_solver(*curve), _bisect_solver(*curve)
        worst = max(abs(a(i / 200.0) - b(i / 200.0)) for i in range(201))
        assert worst < 1e-9, (curve, worst)


def test_linear_is_identity_and_endpoints_are_exact():
    f = M.bezier_solver(0, 0, 1, 1)
    for i in range(101):
        assert abs(f(i / 100.0) - i / 100.0) < 1e-9
    for curve in [(.42, 0, .58, 1), (.34, 1.56, .64, 1)]:
        g = M.bezier_solver(*curve)
        assert g(0.0) == 0.0 and g(1.0) == 1.0
        assert g(-5.0) == 0.0 and g(9.0) == 1.0        # 越界钳住,不外推


# ── 2. 与外部实测值对照 ──────────────────────────────────────────────────────
def test_reproduces_measured_gap_against_ease_out_cubic():
    """"拿差不多的近似式凑合"到底差多少:easeOutCubic vs cubic-bezier(.23,1,.32,1)
    最大差 19.8 个百分点,出现在 x≈0.23 —— 起步、也就是最显眼的那一段。"""
    f = M.bezier_solver(.23, 1, .32, 1)
    worst, at = max((abs(f(i / 1000.0) - (1 - (1 - i / 1000.0) ** 3)), i / 1000.0)
                    for i in range(1001))
    assert abs(worst - 0.198) < 0.002, worst
    assert abs(at - 0.234) < 0.01, at


def test_reproduces_measured_overshoot_peak():
    """easeOutBack cubic-bezier(.34,1.56,.64,1) 的进度峰值 = 1.0978(超出终点 9.78%)。
    过冲是**行程的比例**:.95 起步只弹出 0.49%(看不见),.8 起步才有 1.96%。"""
    f = M.bezier_solver(.34, 1.56, .64, 1)
    peak = max(f(i / 2000.0) for i in range(2001))
    assert abs(peak - 1.0978) < 0.0005, peak
    assert abs((peak - 1) * 0.05 - 0.00489) < 1e-4      # .95 起步 → 0.49%
    assert abs((peak - 1) * 0.20 - 0.01956) < 1e-4      # .80 起步 → 1.96%


# ── 3. 弹簧的物理性质 ────────────────────────────────────────────────────────
def test_spring_param_conversion_hand_computed():
    """m=1,k=100,c=10 → w0=sqrt(100/1)=10;zeta=10/(2·sqrt(100·1))=0.5;response=2π/10。"""
    zeta, w0, response = M.spring_params(1, 100, 10)
    assert abs(w0 - 10.0) < 1e-12
    assert abs(zeta - 0.5) < 1e-12
    assert abs(response - 2 * math.pi / 10) < 1e-12


def test_underdamped_overshoots_critical_does_not_overdamped_is_monotonic():
    under = M.spring_solver(1, 100, 10)        # zeta 0.5
    crit = M.spring_solver(1, 100, 20)         # zeta 1.0
    over = M.spring_solver(1, 100, 40)         # zeta 2.0
    ts = [i / 500.0 for i in range(1001)]      # 0..2s
    assert max(under(t) for t in ts) > 1.05, "zeta<1 必须过冲"
    assert max(crit(t) for t in ts) <= 1.0 + 1e-9, "zeta=1 是临界阻尼,数学上不过冲"
    assert max(over(t) for t in ts) <= 1.0 + 1e-9, "zeta>1 过阻尼,更不可能过冲"
    vals = [over(t) for t in ts]
    assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:])), "过阻尼必须单调爬向目标"


def test_every_spring_starts_at_zero_and_converges_to_one():
    for c in (5, 20, 40):
        f = M.spring_solver(1, 100, c)
        assert f(0.0) == 0.0
        assert abs(f(20.0) - 1.0) < 1e-6


def test_settle_time_matches_the_envelope():
    """包络 e^(-zeta·w0·t) 降到 eps 的时刻:t = -ln(eps)/(zeta·w0)。"""
    assert abs(M.settle_time(1, 100, 10, eps=0.001) - (-math.log(0.001) / 5.0)) < 1e-12
    assert M.settle_time(1, 100, 0) == float("inf")      # 无阻尼永不停


# ── 解析:名字 → 曲线 ────────────────────────────────────────────────────────
def test_explicit_bezier_wins_over_the_name():
    kind, payload = M.resolve_easing({"type": "EASE_OUT", "bezier": [.32, .72, 0, 1]})
    assert (kind, payload) == (M.BEZIER, (.32, .72, 0, 1))


def test_css_equivalent_names_resolve():
    assert M.resolve_easing({"type": "EASE_IN_AND_OUT"}) == (M.BEZIER, (.42, 0.0, .58, 1.0))


def test_unknown_names_stay_unresolved_instead_of_being_guessed():
    """*_BACK / GENTLE / BOUNCY 这些 figma 没公开控制点 —— 必须解不出来。
    编一组"差不多"的数进来,产物看起来完全正常而手感是错的,比解不出来贵得多。"""
    for name in ("EASE_OUT_BACK", "GENTLE", "QUICK", "BOUNCY", "SLOW", "WAT"):
        kind, payload = M.resolve_easing({"type": name})
        assert kind == M.UNRESOLVED and payload == name
    pts, notes = M.sample_curve({"type": "BOUNCY"}, 300)
    assert pts == [] and notes and "不采样" in notes[0]


# ── 采样:后端的唯一入口 ─────────────────────────────────────────────────────
def test_samples_are_deterministic_rounded_and_span_zero_to_one():
    a, _ = M.sample_curve({"type": "EASE_OUT"}, 260)
    b, _ = M.sample_curve({"type": "EASE_OUT"}, 260)
    assert a == b and len(a) == M.SAMPLES
    assert a[0] == (0.0, 0.0) and a[-1] == (1.0, 1.0)
    for x, y in a:
        assert round(x, 6) == x and round(y, 6) == y      # 已四舍五入 → 跨平台可复现


def test_spring_sampling_reports_truncation_rather_than_hiding_it():
    """duration 短于收敛时间 = 曲线被切掉一段。那是降级,必须留痕。"""
    _, notes = M.sample_curve(
        {"type": "CUSTOM_SPRING", "spring": {"mass": 1, "stiffness": 100, "damping": 4}}, 100)
    assert any("截断" in n for n in notes), notes
    _, ok = M.sample_curve(
        {"type": "CUSTOM_SPRING", "spring": {"mass": 1, "stiffness": 400, "damping": 40}}, 3000)
    assert not any("截断" in n for n in ok), ok


def test_critical_damping_is_called_out_as_never_bouncing():
    _, notes = M.sample_curve(
        {"type": "CUSTOM_SPRING", "spring": {"mass": 1, "stiffness": 100, "damping": 20}}, 5000)
    assert any("不会过冲" in n for n in notes), notes


def test_bake_flow_keys_by_event_index_and_skips_transitionless_events():
    flow = {"events": [
        {"on": "click", "el": "1:1", "do": "closeModal"},                      # 无转场 → 不出现
        {"on": "click", "el": ["1:2", "1:3"], "do": "openModal", "arg": "m",
         "transition": {"type": "MOVE_IN", "direction": "BOTTOM", "duration": 300,
                        "easing": {"type": "EASE_OUT"}}},
    ]}
    data, notes = M.bake_flow(flow, "unit-test")
    assert list(data["curves"]) == ["ev1"], data["curves"]
    c = data["curves"]["ev1"]
    assert c["el"] == ["1:2", "1:3"] and c["direction"] == "BOTTOM"
    assert len(c["points"]) == M.SAMPLES and c["points"][0] == [0.0, 0.0]
    assert not notes


def test_bake_flow_marks_unresolved_curves_and_reports_them():
    flow = {"events": [{"on": "click", "el": "1:1", "do": "openModal", "arg": "m",
                        "transition": {"type": "DISSOLVE", "duration": 300,
                                       "easing": {"type": "BOUNCY"}}}]}
    data, notes = M.bake_flow(flow, "unit-test")
    assert data["curves"]["ev0"]["unresolved"] is True
    assert data["curves"]["ev0"]["points"] == []
    assert notes and "unresolved" in notes[0]


def test_describe_is_one_line_per_kind():
    assert "cubic-bezier(0.32,0.72,0,1)" in M.describe({"bezier": [.32, .72, 0, 1]}, 300)
    assert "damping=0.50" in M.describe({"spring": {"mass": 1, "stiffness": 100, "damping": 10}}, 400)
    assert "unresolved" in M.describe({"type": "BOUNCY"}, 300)


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

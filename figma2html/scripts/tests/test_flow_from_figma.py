# -*- coding: utf-8 -*-
"""flow_from_figma.py 的测试:搬得动的必须搬对,搬不动的必须**逐条报出来**。

后一半才是重点。一个只把能搬的搬过来、其余静默丢掉的导入器是**危险**的:
使用者拿到一份看起来完整的 flow.json,却不知道 figma 里还连着四条线没过来。
所以每一条"搬不动"的分支都单独钉一个用例 —— 报告消失了要当场红。

样本大多在内存里构造(figma REST 的 `interactions[]` 形状),只有端到端那两条
走真 demo 的 nodes.json,顺带证明产物能过 flow_check。
"""
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(_HERE)
sys.path.insert(0, SCRIPTS)
import flow_check as FC        # noqa: E402
import flow_from_figma as FF   # noqa: E402

EX = os.path.abspath(os.path.join(SCRIPTS, "..", "examples", "login"))
PAIRS = [("base", "screen-login.ui.json"),
         ("notice", "screen-notice.ui.json"),
         ("serverlist", "screen-serverlist.ui.json")]


# ── 内存夹具:两屏,base 有一个按钮,modal 有一个面板 ──────────────────────────
def _caps():
    return {
        "base": {"path": "b.ui.json", "frame": "1:1", "ids": {"1:1", "1:9", "1:8"},
                 "roots": ["1:9"], "w": 100, "h": 200},
        "pop": {"path": "p.ui.json", "frame": "2:1", "ids": {"2:1", "2:9"},
                "roots": ["2:9"], "w": 100, "h": 200},
    }


def _node(nid, name="n", **kw):
    d = {"id": nid, "name": name}
    d.update(kw)
    return d


def _build(nodes, caps=None, pairs=None):
    return FF.build_flow(nodes, pairs or [("base", "b.ui.json"), ("pop", "p.ui.json")],
                         caps or _caps())


def _click(*actions):
    return {"trigger": {"type": "ON_CLICK"}, "actions": list(actions)}


def _overlay(dest, transition=None):
    return {"type": "NODE", "destinationId": dest, "navigation": "OVERLAY",
            "transition": transition}


# ── 搬得动的 ────────────────────────────────────────────────────────────────
def test_overlay_becomes_open_modal():
    flow, notes = _build([_node("1:9", interactions=[_click(_overlay("2:1"))])])
    assert flow["events"] == [{"on": "click", "el": "1:9", "do": "openModal", "arg": "pop"}], flow
    assert not notes, notes


def test_two_elements_same_action_merge_into_array():
    """figma 里两个元素连到同一个弹窗,是 flow 里的一条事件 + el 数组(与手写 demo 同形)。"""
    flow, _ = _build([_node("1:9", interactions=[_click(_overlay("2:1"))]),
                      _node("1:8", interactions=[_click(_overlay("2:1"))])])
    assert len(flow["events"]) == 1, flow["events"]
    assert flow["events"][0]["el"] == ["1:9", "1:8"]


def test_modal_roots_and_panel_inferred_from_cap():
    flow, _ = _build([_node("1:9", interactions=[_click(_overlay("2:1"))])])
    assert flow["modals"] == {"pop": {"cap": "pop", "roots": ["2:9"], "panel": "2:9"}}


def test_multi_root_modal_leaves_panel_unset_and_says_so():
    """多个顶层根时猜不出面板本体 —— 必须留空并点名,而不是瞎指第一个。"""
    caps = _caps()
    caps["pop"]["roots"] = ["2:9", "2:8"]
    caps["pop"]["ids"] |= {"2:8"}
    flow, notes = _build([_node("1:9", interactions=[_click(_overlay("2:1"))])], caps)
    assert "panel" not in flow["modals"]["pop"]
    assert any("panel" in n for n in notes), notes


def test_bezier_transition_carried():
    tr = {"type": "MOVE_IN", "direction": "BOTTOM", "duration": 300,
          "easing": {"type": "CUSTOM_CUBIC_BEZIER",
                     "easingFunctionCubicBezier": {"x1": .32, "y1": .72, "x2": 0, "y2": 1}}}
    flow, _ = _build([_node("1:9", interactions=[_click(_overlay("2:1", tr))])])
    got = flow["events"][0]["transition"]
    assert got["type"] == "MOVE_IN" and got["direction"] == "BOTTOM" and got["duration"] == 300
    assert got["easing"]["bezier"] == [.32, .72, 0, 1], got


def test_spring_transition_carried_as_figma_three_params():
    """弹簧原样带 {mass,stiffness,damping} —— 换算成解耦两参是消费侧的事,IR 只记设计说了什么。"""
    tr = {"type": "SMART_ANIMATE", "duration": 400,
          "easing": {"type": "CUSTOM_SPRING",
                     "easingFunctionSpring": {"mass": 1, "stiffness": 100, "damping": 15}}}
    flow, _ = _build([_node("1:9", interactions=[_click(_overlay("2:1", tr))])])
    assert flow["events"][0]["transition"]["easing"]["spring"] == \
        {"mass": 1, "stiffness": 100, "damping": 15}


def test_legacy_transition_node_id_is_normalized_not_ignored():
    """2023 年前的响应只有 transitionNodeID 三件套;按它的历史含义(NAVIGATE)归一化。"""
    ints = FF.interactions_of(_node("1:9", transitionNodeID="2:1",
                                    transitionDuration=200, transitionEasing="EASE_IN"))
    assert len(ints) == 1 and ints[0]["trigger"]["type"] == "ON_CLICK"
    a = ints[0]["actions"][0]
    assert a["navigation"] == "NAVIGATE" and a["destinationId"] == "2:1"
    assert a["transition"]["duration"] == 200


# ── 搬不动的:每条都必须留下报告 ──────────────────────────────────────────────
def _one_note(nodes, needle, caps=None):
    flow, notes = _build(nodes, caps)
    assert flow["events"] == [], flow["events"]
    assert any(needle in n for n in notes), (needle, notes)


def test_navigate_is_reported_not_silently_turned_into_a_modal():
    """NAVIGATE 换底屏 ≠ OVERLAY 叠弹窗。搬错比不搬贵得多,所以只报告。"""
    _one_note([_node("1:9", interactions=[_click(
        {"type": "NODE", "destinationId": "2:1", "navigation": "NAVIGATE"})])], "NAVIGATE")


def test_non_click_trigger_is_reported():
    _one_note([_node("1:9", interactions=[
        {"trigger": {"type": "ON_HOVER"}, "actions": [_overlay("2:1")]}])], "ON_HOVER")


def test_set_variable_is_reported():
    _one_note([_node("1:9", interactions=[_click({"type": "SET_VARIABLE",
                                                  "variableId": "V:1"})])], "SET_VARIABLE")


def test_conditional_is_reported():
    _one_note([_node("1:9", interactions=[_click({"type": "CONDITIONAL",
                                                  "conditionalBlocks": []})])], "CONDITIONAL")


def test_back_inside_a_modal_screen_is_reported_with_the_handwritten_workaround():
    """v1.0 的 events 只绑 base 屏 —— 弹窗里的关闭按钮搬不动,但要告诉人手写哪一条。"""
    flow, notes = _build([_node("2:9", interactions=[_click({"type": "BACK"})])])
    assert flow["events"] == []
    assert any("BACK" in n and "@panelOutside" in n for n in notes), notes


def test_back_on_the_base_screen_does_become_close_modal():
    flow, notes = _build([_node("1:9", interactions=[_click({"type": "CLOSE"})])])
    assert flow["events"] == [{"on": "click", "el": "1:9", "do": "closeModal"}], flow
    assert not notes, notes


def test_overlay_to_an_uncaptured_frame_is_reported():
    _one_note([_node("1:9", interactions=[_click(_overlay("9:9"))])], "没有对应的 cap")


def test_interaction_on_a_node_outside_every_cap_is_reported():
    _one_note([_node("7:7", interactions=[_click(_overlay("2:1"))])], "不在任何一屏")


# ── 端到端:真 demo 的 nodes.json ────────────────────────────────────────────
def _run_cli(outdir, extra=()):
    out = os.path.join(outdir, "flow.json")
    for name, rel in PAIRS:                       # caps 按 flow.json 所在目录解析 → 拷进来
        with open(os.path.join(EX, rel), encoding="utf-8") as f:
            src = f.read()
        with open(os.path.join(outdir, rel), "w", encoding="utf-8", newline="") as f:
            f.write(src)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "flow_from_figma.py"),
                        os.path.join(EX, "nodes.json"), out] +
                       ["%s=%s" % p for p in PAIRS] + list(extra),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r, out


def test_demo_import_matches_the_handwritten_skeleton_and_passes_flow_check():
    """导入的骨架必须与手写 flow.json 的 stage/caps/base/modals **完全一致** ——
    这正是"figma 有的那半"。手写版多出来的 list/bindings/guard 是应用语义,figma 里没有。"""
    tmp = tempfile.mkdtemp(prefix="figkit_import_")
    r, out = _run_cli(tmp)
    assert r.returncode == 0, r.stderr
    with open(out, encoding="utf-8") as f:
        got = json.load(f)
    with open(os.path.join(EX, "flow.json"), encoding="utf-8") as f:
        hand = json.load(f)
    for k in ("stage", "caps", "base", "modals"):
        assert got[k] == hand[k], (k, got[k], hand[k])
    # 不开 --motion-defaults 时,连默认动效都不该有 —— 补默认是**显式动作**,不是副作用。
    assert set(hand) - set(got) == {"list", "bindings", "motion"}


def test_import_with_motion_defaults_leaves_only_hand_authored_blocks():
    """开了 --motion-defaults 之后,导入版与手写版的差就只剩 list / bindings ——
    也就是**只有 figma 和预设都给不了的那部分**才真需要人写。这是整条管线的目标状态。"""
    tmp = tempfile.mkdtemp(prefix="figkit_motion_")
    r, out = _run_cli(tmp, extra=["--motion-defaults"])
    assert r.returncode == 0, r.stderr
    with open(out, encoding="utf-8") as f:
        got = json.load(f)
    with open(os.path.join(EX, "flow.json"), encoding="utf-8") as f:
        hand = json.load(f)
    assert set(hand) - set(got) == {"list", "bindings"}, set(hand) - set(got)
    # figma 声明过的两条转场原样保留,没被预设顶替
    figma_declared = [e["transition"] for e in got["events"] if e.get("do") == "openModal"]
    assert all("source" not in t for t in figma_declared), figma_declared
    assert {t["type"] for t in figma_declared} == {"DISSOLVE", "MOVE_IN"}
    # 预设补的那条(按压)带来源,人看得出是谁加的
    assert got["motion"]["press"]["source"] == "preset:base"

    caps, errs = FC.load_caps(got, tmp)
    assert not errs, errs
    assert not FC.check_flow(got, caps), FC.check_flow(got, caps)


def test_demo_import_is_deterministic():
    a = _run_cli(tempfile.mkdtemp(prefix="figkit_det_a"))[1]
    b = _run_cli(tempfile.mkdtemp(prefix="figkit_det_b"))[1]
    assert open(a, encoding="utf-8").read() == open(b, encoding="utf-8").read()


def test_strict_flag_exits_3_when_anything_was_dropped():
    """默认 exit 0(草稿本来就该有缺口);--strict 给 CI 用,漏一条就红。"""
    tmp = tempfile.mkdtemp(prefix="figkit_strict_")
    r, _ = _run_cli(tmp, extra=["--strict"])
    assert r.returncode == 3, (r.returncode, r.stderr)
    assert "! " in r.stderr and "Traceback" not in (r.stdout + r.stderr)


def test_bad_args_exit_2_with_usage():
    """断言 usage 的 ASCII 实质(参数形状),不断言中文标签 ——
    子进程的中文会被控制台代码页降级成 '?',拿中文做断言等于在测运行环境的编码。"""
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "flow_from_figma.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "flow_from_figma.py <nodes.json> <out_flow.json>" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr


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

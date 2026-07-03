# -*- coding: utf-8 -*-
"""ui_to_uespec 单元测试:解析器手算断言 + 夹具几何 + flow 校验(坏引用退非 0)。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import ui_to_uespec as U  # noqa: E402

FIX = os.path.join(_HERE, "fixtures")
SCRIPT = os.path.join(os.path.dirname(_HERE), "ui_to_uespec.py")


def _login_spec():
    with open(os.path.join(FIX, "screen-login.ui.json"), encoding="utf-8") as f:
        return U.convert_cap(json.load(f))


def _el(spec, eid):
    return next(e for e in spec["els"] if e["id"] == eid)


def test_rgba_parse_hand_computed():
    # 手算:夹具 1:30 的 border 色 rgba(255,255,255,1) → [255,255,255,1]
    assert U.parse_color("rgba(219,208,184,1)") == [219, 208, 184, 1]
    assert U.parse_color("rgba(0,0,0,0.6)") == [0, 0, 0, 0.6]
    assert U.parse_color("#000") == [0, 0, 0, 1]          # capture 文字色回退格式
    assert U.parse_color("#a1B2c3") == [161, 178, 195, 1]


def test_radius_four_corner_expand():
    assert U.parse_radius("37px", 100, 100) == [37, 37, 37, 37]
    assert U.parse_radius("10px 20px 30px 40px", 0, 0) == [10, 20, 30, 40]
    assert U.parse_radius("10px 20px", 0, 0) == [10, 20, 10, 20]
    assert U.parse_radius("50%", 46, 46) == [23, 23, 23, 23]   # ELLIPSE:min(w,h)/2
    assert U.parse_radius("", 10, 10) is None


def test_linear_gradient_angle_and_stops():
    f = U.parse_fill("linear-gradient(135.5deg, rgba(255,0,0,1) 0.0%, rgba(0,0,255,0.5) 100.0%)")
    assert f["type"] == "linear" and f["angleDeg"] == 135.5
    assert f["stops"] == [{"rgba": [255, 0, 0, 1], "pos": 0},
                          {"rgba": [0, 0, 255, 0.5], "pos": 1}]
    r = U.parse_fill("radial-gradient(rgba(1,2,3,1) 0.0%, rgba(4,5,6,1) 50.0%)")
    assert r["type"] == "radial" and r["stops"][1]["pos"] == 0.5
    assert U.parse_fill("rgba(255,251,242,1)") == {"type": "solid", "rgba": [255, 251, 242, 1]}


def test_parent_relative_geometry_hand_computed():
    spec = _login_spec()
    gem = _el(spec, "1:12")   # x=286,y=1302;父 1:10 x=260,y=1280
    assert gem["localX"] == 26 and gem["localY"] == 22, (gem["localX"], gem["localY"])
    assert gem["absX"] == 286 and gem["absY"] == 1302
    root = _el(spec, "1:10")  # 无父 → local == abs
    assert root["localX"] == 260 and root["localY"] == 1280


def test_shadow_parse():
    s = U.parse_shadow("0px 4px 0px rgba(0,0,0,0.6)")
    assert s == [{"dx": 0, "dy": 4, "blur": 0, "rgba": [0, 0, 0, 0.6]}]
    multi = U.parse_shadow("0px 4px 12px rgba(0,0,0,0.6), 0px -1px 2px rgba(255,255,255,1)")
    assert len(multi) == 2 and multi[1]["dy"] == -1 and multi[1]["blur"] == 2
    assert U.parse_shadow("") == []


def test_text_fields_complete():
    spec = _login_spec()
    t = _el(spec, "1:21")["text"]   # 开始游戏按钮文字
    assert t["content"] == "开始游戏"
    assert t["rgba"] == [58, 42, 0, 1]
    assert t["size"] == 48 and t["weight"] == 800
    assert t["family"] == "Source Han Sans SC"
    assert t["alignH"] == "center" and t["alignV"] == "center" and t["textAlign"] == "center"
    assert t["lh"] == 0 and t["ls"] == 0 and t["stroke"] is None
    assert U.parse_text_stroke("2.0px rgba(27,76,87,1)") == {"width": 2, "rgba": [27, 76, 87, 1]}


def test_border_and_blur_parse():
    assert U.parse_border("4.0px solid rgba(219,208,184,1)") == \
        {"width": 4, "rgba": [219, 208, 184, 1]}
    assert U.parse_blur("blur(6px)") == {"radius": 6}
    assert U.parse_blur("") is None


def test_flow_bad_ref_exits_nonzero():
    tmp = tempfile.mkdtemp(prefix="uespec_badref_")
    try:
        for fn in os.listdir(FIX):
            shutil.copy(os.path.join(FIX, fn), tmp)
        bad_flow = os.path.join(tmp, "flow.json")
        with open(bad_flow, encoding="utf-8") as f:
            flow = json.load(f)
        flow["events"].append({"on": "click", "el": "9:99", "do": "closeModal"})  # 不存在的 el
        with open(bad_flow, "w", encoding="utf-8") as f:
            json.dump(flow, f, ensure_ascii=False)
        out = os.path.join(tmp, "out")
        r = subprocess.run([sys.executable, SCRIPT,
                            os.path.join(tmp, "screen-login.ui.json"), bad_flow, out],
                           capture_output=True, text=True)
        assert r.returncode != 0, "坏引用必须退非 0"
        assert "9:99" in r.stderr, r.stderr
        assert not os.path.exists(os.path.join(out, "flow.uespec.json")), "坏 flow 不该产出"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_flow_good_produces_normalized_events():
    tmp = tempfile.mkdtemp(prefix="uespec_good_")
    try:
        out = os.path.join(tmp, "out")
        r = subprocess.run([sys.executable, SCRIPT,
                            os.path.join(FIX, "screen-login.ui.json"),
                            os.path.join(FIX, "flow.json"), out],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        with open(os.path.join(out, "flow.uespec.json"), encoding="utf-8") as f:
            fs = json.load(f)
        # el 数组展开成 targets;特殊选择器结构化
        ev_multi = next(e for e in fs["events"] if e["do"] == "openModal" and e["arg"] == "serverlist")
        assert ev_multi["targets"] == [{"kind": "node", "id": "1:10"}, {"kind": "node", "id": "1:13"}]
        ev_out = next(e for e in fs["events"] if e["targets"][0]["kind"] == "panelOutside")
        assert ev_out["targets"][0]["modal"] == "serverlist"
        guard_ev = next(e for e in fs["events"] if e["do"] == "send")
        assert guard_ev["guard"] == ["agreed", "selected"]
        # checkbox 颜色已强类型化
        assert fs["bindings"]["checkbox"]["markRgba"] == [27, 76, 87, 1]
        # 三屏 uespec 全部产出
        for fn in ("screen-login.uespec.json", "screen-notice.uespec.json",
                   "screen-serverlist.uespec.json"):
            assert os.path.exists(os.path.join(out, fn)), fn
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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

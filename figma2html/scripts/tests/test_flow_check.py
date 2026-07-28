# -*- coding: utf-8 -*-
"""flow_check.py 的测试:真 demo 必须放行,每一类坏引用必须被抓。

坏引用样本用内存构造(不落文件),这样每条错误路径都能单独钉住 —— 一个只会对
"完全正确的输入"说 OK 的校验器等于没有校验器。
"""
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(_HERE)
sys.path.insert(0, SCRIPTS)
import flow_check as F  # noqa: E402

EX = os.path.abspath(os.path.join(SCRIPTS, "..", "examples", "login"))


def _load_real():
    with open(os.path.join(EX, "flow.json"), encoding="utf-8") as f:
        flow = json.load(f)
    caps, errs = F.load_caps(flow, EX)
    assert not errs, errs
    return flow, caps


def test_real_demo_passes():
    flow, caps = _load_real()
    assert not F.check_flow(flow, caps), F.check_flow(flow, caps)


def test_cli_exit_codes():
    """好 flow → 0;坏 flow → 2(不是 1、不是 traceback)。"""
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "flow_check.py"),
                        os.path.join(EX, "flow.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr

    tmp = tempfile.mkdtemp(prefix="figkit_flow_")
    bad = os.path.join(tmp, "flow.json")
    with open(bad, "w", encoding="utf-8") as f:
        json.dump({"caps": {"base": "nope.ui.json"}, "base": "base"}, f)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "flow_check.py"), bad],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "Traceback" not in (r.stdout + r.stderr)


def _mutate(fn):
    flow, caps = _load_real()
    flow = json.loads(json.dumps(flow))          # 深拷贝,别污染别的用例
    fn(flow)
    return F.check_flow(flow, caps)


def test_catches_bad_event_el():
    errs = _mutate(lambda f: f["events"][0].update(el="99:9999"))
    assert any("events[0]" in e and "99:9999" in e for e in errs), errs


def test_catches_bad_special_selector():
    errs = _mutate(lambda f: f["events"][-1].update(el="@any:ghostModal"))
    assert any("不存在的 modal" in e for e in errs), errs


def test_catches_bad_modal_root():
    def m(f):
        name = sorted(f["modals"])[0]
        f["modals"][name]["roots"] = ["99:1"]
    assert any("root" in e for e in _mutate(m)), _mutate(m)


def test_catches_bad_modal_panel():
    def m(f):
        for name, mm in f["modals"].items():
            if mm.get("panel"):
                mm["panel"] = "99:2"
                return
        f["modals"][sorted(f["modals"])[0]]["panel"] = "99:2"
    assert any("panel" in e for e in _mutate(m)), _mutate(m)


def test_catches_bad_list_container():
    errs = _mutate(lambda f: f["list"].update(container="99:3"))
    assert any("container" in e for e in errs), errs


def test_catches_bad_checkbox_el():
    errs = _mutate(lambda f: f["bindings"]["checkbox"].update(el="99:4"))
    assert any("checkbox" in e for e in errs), errs


def test_catches_unknown_base():
    errs = _mutate(lambda f: f.update(base="ghost"))
    assert any("base" in e for e in errs), errs


def test_catches_missing_template_row():
    """list.container 存在但下面没有模板行 —— 引擎会克隆个寂寞。"""
    flow, caps = _load_real()
    cname = flow["modals"][flow["list"]["modal"]]["cap"]
    cap = json.loads(json.dumps(caps[cname]))
    cont = flow["list"]["container"]
    cap["els"] = [e for e in cap["els"] if e.get("parent") != cont]
    caps2 = dict(caps, **{cname: cap})
    assert any("模板行" in e for e in F.check_flow(flow, caps2))


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

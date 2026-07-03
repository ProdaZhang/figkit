# -*- coding: utf-8 -*-
# ui_check.py 冒烟:夹具全绿 / 内存构造坏 flow 抓坏引用 / 资产清单 / 模板行 / 缺 cap 文件。
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ui_check as U  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
FLOW = os.path.join(FIX, "flow.json")


def _load():
    flow = U.load_flow(FLOW)
    caps, errs = U.load_caps(flow, FIX)
    assert not errs, errs
    return flow, caps


def test_fixtures_pass_exit0():
    # 真跑 CLI:登录三屏夹具应全绿 exit 0
    ui_check = os.path.join(os.path.dirname(HERE), "ui_check.py")
    r = subprocess.run([sys.executable, ui_check, FLOW, FIX],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout, r.stdout
    # CLI 顺手落了 manifest;内容应与 collect_assets 一致(夹具无图 → 空清单)
    mpath = os.path.join(FIX, "assets-manifest.json")
    assert os.path.isfile(mpath)
    with open(mpath, encoding="utf-8") as f:
        manifest = json.load(f)
    flow, caps = _load()
    assert manifest == U.collect_assets(caps) == []
    os.remove(mpath)  # 夹具目录保持干净


def test_bad_event_ref_caught():
    # 内存篡改:事件指向不存在的 el → 必须被抓且报文点名
    flow, caps = _load()
    bad = copy.deepcopy(flow)
    bad["events"][0]["el"] = "9:999"
    errs = U.check_flow(bad, caps)
    assert any("9:999" in e and "events[0]" in e for e in errs), errs
    # 数组 el 里混一个坏 id 也要抓
    bad2 = copy.deepcopy(flow)
    bad2["events"][1]["el"] = ["1:10", "8:888"]
    errs2 = U.check_flow(bad2, caps)
    assert any("8:888" in e for e in errs2), errs2


def test_modal_root_and_panel_refs():
    flow, caps = _load()
    bad = copy.deepcopy(flow)
    bad["modals"]["notice"]["roots"] = ["2:10", "7:777"]
    bad["modals"]["serverlist"]["panel"] = "6:666"
    errs = U.check_flow(bad, caps)
    assert any("7:777" in e and "modals[notice]" in e for e in errs), errs
    assert any("6:666" in e and "modals[serverlist]" in e for e in errs), errs
    # @选择器指向不存在的 modal 也要抓
    bad2 = copy.deepcopy(flow)
    bad2["events"][4]["el"] = "@panelOutside:nope"
    errs2 = U.check_flow(bad2, caps)
    assert any("nope" in e for e in errs2), errs2


def test_assets_manifest_dedup():
    # 内存构造带图的 caps:img 跨屏重复 + stageBg url → 去重排序
    caps = {
        "a": {"stageBg": "url(_assets/s1/bg.png) center/cover no-repeat",
              "els": [{"id": "1:1", "img": "_assets/s1/n1.png"},
                      {"id": "1:2", "img": ""}]},
        "b": {"stageBg": "rgba(20,50,59,1)",
              "els": [{"id": "2:1", "img": "_assets/s1/n1.png"},   # 跨屏复用同 imageRef
                      {"id": "2:2", "img": "_assets/s2/n2.png"}]},
    }
    assert U.collect_assets(caps) == [
        "_assets/s1/bg.png", "_assets/s1/n1.png", "_assets/s2/n2.png"]


def test_list_template_rows_detected():
    flow, caps = _load()
    # 夹具本身:serverlist 容器 3:20 下有 2 个模板行 → 通过
    assert U.check_flow(flow, caps) == []
    # 抽掉容器下所有行 → 报"没有模板行"
    bad_caps = copy.deepcopy(caps)
    cap = bad_caps[flow["modals"]["serverlist"]["cap"]]
    row_ids = {e["id"] for e in cap["els"] if e["parent"] == "3:20"}
    keep = set()
    grow = True
    while grow:  # 行子树整棵剔除
        grow = False
        for e in cap["els"]:
            if e["id"] not in row_ids and e["parent"] in row_ids | keep and e["id"] not in keep:
                keep.add(e["id"]); grow = True
    cap["els"] = [e for e in cap["els"] if e["id"] not in row_ids | keep]
    errs = U.check_flow(flow, bad_caps)
    assert any("模板行" in e for e in errs), errs
    # 容器 id 本身坏 → 也要抓
    bad_flow = copy.deepcopy(flow)
    bad_flow["list"]["container"] = "5:555"
    errs2 = U.check_flow(bad_flow, caps)
    assert any("5:555" in e for e in errs2), errs2


def test_missing_cap_file_reported():
    flow = U.load_flow(FLOW)
    bad = copy.deepcopy(flow)
    bad["caps"]["notice"] = "screen-不存在.ui.json"
    caps, errs = U.load_caps(bad, FIX)
    assert any("文件不存在" in e and "notice" in e for e in errs), errs
    # 缺屏连带:notice modal 的引用也应报(cap 未载入)
    errs2 = U.check_flow(bad, caps)
    assert any("modals[notice]" in e for e in errs2), errs2


def test_checkbox_binding_ref():
    flow, caps = _load()
    bad = copy.deepcopy(flow)
    bad["bindings"]["checkbox"]["el"] = "4:444"
    errs = U.check_flow(bad, caps)
    assert any("checkbox" in e and "4:444" in e for e in errs), errs


def _run():
    ok = True
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:
                ok = False; print("FAIL", n, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)

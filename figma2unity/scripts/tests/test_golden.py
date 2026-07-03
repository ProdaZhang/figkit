# -*- coding: utf-8 -*-
"""test_golden.py — golden 回归:fixtures/screen-login 的转换产物必须与
tests/golden/ 提交版逐字节一致(守确定性 + 防映射漂移;有意改映射时重生成 golden)。"""
import importlib.util
import os
import shutil
import tempfile

D = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(D)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "ui_to_unity", os.path.join(SCRIPTS, "ui_to_unity.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run():
    mod = _load_module()
    fix = os.path.join(D, "fixtures", "screen-login.ui.json")
    out = tempfile.mkdtemp(prefix="f2u_golden_")
    ok = True
    try:
        mod.convert_file(fix, out)
        for fn in ("screen-login.uxml", "screen-login.uss"):
            with open(os.path.join(out, fn), "rb") as f:
                got = f.read()
            gp = os.path.join(D, "golden", fn)
            if not os.path.isfile(gp):
                print("  FAIL  golden 缺失: " + fn)
                ok = False
                continue
            with open(gp, "rb") as f:
                want = f.read()
            same = got == want
            print(("  PASS  " if same else "  FAIL  ") + "逐字节一致: " + fn)
            if not same:
                ok = False
            # 顺手守 UTF-8 无 BOM
            if got[:3] == b"\xef\xbb\xbf":
                print("  FAIL  产物带 BOM: " + fn)
                ok = False
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return ok

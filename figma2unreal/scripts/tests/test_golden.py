# -*- coding: utf-8 -*-
"""金样测试:screen-login 的 uespec(+flow.uespec)与 tests/golden/ 逐字节一致。
输出必须确定性(UTF-8 无 BOM、\\n、固定键序)——任何有意变更需重生成金样并说明。"""
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(_HERE, "fixtures")
GOLD = os.path.join(_HERE, "golden")
SCRIPT = os.path.join(os.path.dirname(_HERE), "ui_to_uespec.py")


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def test_golden_byte_identical():
    tmp = tempfile.mkdtemp(prefix="uespec_gold_")
    try:
        out = os.path.join(tmp, "out")
        r = subprocess.run([sys.executable, SCRIPT,
                            os.path.join(FIX, "screen-login.ui.json"),
                            os.path.join(FIX, "flow.json"), out],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        for fn in ("screen-login.uespec.json", "flow.uespec.json"):
            got = _read(os.path.join(out, fn))
            want = _read(os.path.join(GOLD, fn))
            assert got == want, "%s 与金样不一致(%d vs %d 字节)" % (fn, len(got), len(want))
        assert not _read(os.path.join(out, "screen-login.uespec.json")).startswith(b"\xef\xbb\xbf"), "不许 BOM"
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

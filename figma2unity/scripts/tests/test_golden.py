# -*- coding: utf-8 -*-
"""test_golden.py — golden 回归:fixtures/screen-login 的转换产物必须与
tests/golden/ 提交版逐字节一致(守确定性 + 防映射漂移;有意改映射时重生成 golden)。"""
import importlib.util
import os
import shutil
import tempfile
import sys

# 输出里有中文。Windows 上 stdout 的编码跟系统区域走(CI runner 是 Latin-1),
# 一 print 就 UnicodeEncodeError、退出码非 0 —— 而开发机是 GBK,中文编得动,一路绿。
# 这一条把本进程的输出钉成 UTF-8,让「能不能打印」不再取决于跑在谁的机器上。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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

        # CLI 契约:第三个参数(flow.json)可选。不给 → 一个文件都不该多产;
        # 给了 → 多一个 motion.json(转场缓动采样曲线,跨后端一致性由 tools/conformance 守)。
        import subprocess
        import sys as _sys
        cli = os.path.join(SCRIPTS, "ui_to_unity.py")
        bare = tempfile.mkdtemp(prefix="f2u_bare_")
        withflow = tempfile.mkdtemp(prefix="f2u_flow_")
        try:
            subprocess.run([_sys.executable, cli, fix, bare],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            no_extra = not os.path.exists(os.path.join(bare, "motion.json"))
            print(("  PASS  " if no_extra else "  FAIL  ") +
                  "没给 flow.json 时不产 motion.json(CLI 向后兼容)")
            ok = ok and no_extra

            r = subprocess.run([_sys.executable, cli, fix, withflow,
                                os.path.join(D, "fixtures", "flow.json")],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            baked = r.returncode == 0 and os.path.exists(os.path.join(withflow, "motion.json"))
            print(("  PASS  " if baked else "  FAIL  ") + "给了 flow.json 就烘出 motion.json")
            ok = ok and baked
        finally:
            shutil.rmtree(bare, ignore_errors=True)
            shutil.rmtree(withflow, ignore_errors=True)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return ok

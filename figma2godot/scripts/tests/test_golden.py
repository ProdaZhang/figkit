# -*- coding: utf-8 -*-
"""golden 回归:screen-login 走 CLI 真跑一遍,输出与 golden/ 逐字节一致(确定性守卫)。"""
import os
import subprocess
import sys
import tempfile

D = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(D), 'ui_to_tscn.py')


def _run():
    results = []

    def check(cond, msg):
        results.append(bool(cond))
        print(('  PASS  ' if cond else '  FAIL  ') + msg)

    src = os.path.join(D, 'fixtures', 'screen-login.ui.json')
    golden = os.path.join(D, 'golden', 'screen-login.tscn')
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([sys.executable, SCRIPT, src, tmp],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        check(p.returncode == 0, 'CLI 退出码 0(argv 驱动真跑)')
        out = os.path.join(tmp, 'screen-login.tscn')
        check(os.path.isfile(out), '产出 <stem>.tscn 文件名正确')
        if os.path.isfile(out):
            with open(out, 'rb') as f:
                got = f.read()
            with open(golden, 'rb') as f:
                want = f.read()
            check(got == want, 'screen-login.tscn 与 golden 逐字节一致(%d bytes)' % len(want))
            check(not got.startswith(b'\xef\xbb\xbf') and b'\r\n' not in got,
                  'UTF-8 无 BOM + LF 换行')
        # 向后兼容:第三个参数(flow.json)是可选的,不给就**一个文件都不该多产**。
        check(not os.path.exists(os.path.join(tmp, 'motion.json')),
              '没给 flow.json 时不产 motion.json(CLI 向后兼容)')

    ok = all(results)
    print('  %d/%d 通过' % (sum(results), len(results)))
    return ok


if __name__ == '__main__':
    raise SystemExit(0 if _run() else 1)

# -*- coding: utf-8 -*-
"""capture 双副本守卫:figma_capture.py 主拷贝在同级 skill figma2html/scripts/,
本 skill 的是镜像。两份必须逐字节一致(改动先落 figma2html,再 cp 过来)。
兄弟目录不存在(单独分发本 skill)时跳过——守卫只在同仓工作区生效。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MINE = os.path.join(HERE, "..", "figma_capture.py")
MASTER = os.path.join(HERE, "..", "..", "..", "figma2html", "scripts", "figma_capture.py")


def test_capture_mirror_matches_master():
    if not os.path.exists(MASTER):
        print("SKIP(单独分发,无兄弟 figma2html)")
        return
    a = open(MINE, "rb").read()
    b = open(MASTER, "rb").read()
    assert a == b, "figma_capture.py 镜像与 figma2html 主拷贝不一致:改动请先落 figma2html 再同步"


def _run():
    ok = True
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn(); print("PASS", name)
            except Exception as e:
                ok = False; print("FAIL", name, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)

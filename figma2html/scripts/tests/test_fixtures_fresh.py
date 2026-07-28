# -*- coding: utf-8 -*-
"""examples/login 的生成物必须与 make_fixture.py 保持同步。

守两件事:
  1. 三份 `screen-*.ui.json` 与 `fixtures.js` 都是**生成物**;改了 make_fixture.py 或
     capture 逻辑却忘了重跑,demo 就会悄悄过期(fixtures.js 尤其阴——它是 file:// 下
     唯一的数据来源,过期了页面照样渲染,只是渲染的是旧内容)。
  2. 产物必须**逐字节跨平台可复现**:LF 换行、UTF-8 无 BOM、固定键序。
     踩过的坑:`open(..., "w")` 不写 newline="" 就跟着平台走,Windows 出 CRLF、
     Linux 出 LF,`.gitattributes` 又强制 LF —— 两边永远对不上。
"""
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.abspath(os.path.join(_HERE, "..", "..", "examples", "login"))
GEN = ["screen-login.ui.json", "screen-notice.ui.json", "screen-serverlist.ui.json"]


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def _regen(lang, outdir):
    r = subprocess.run([sys.executable, os.path.join(EX, "make_fixture.py"),
                        "--lang", lang, "--out", outdir],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, "make_fixture.py 退出码 %d\n%s" % (r.returncode, r.stderr)


def test_committed_fixtures_are_fresh():
    tmp = tempfile.mkdtemp(prefix="figkit_fresh_")
    try:
        _regen("en", tmp)
        for fn in GEN:
            got, want = _read(os.path.join(tmp, fn)), _read(os.path.join(EX, fn))
            assert got == want, ("%s 与 make_fixture.py 的产物不一致 —— "
                                 "在 examples/login/ 里跑 `python3 make_fixture.py` 并提交结果" % fn)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_fixtures_js_matches_the_ui_json():
    """fixtures.js 是 file:// 下唯一数据源,必须与同目录 .ui.json/flow.json 同批生成。"""
    tmp = tempfile.mkdtemp(prefix="figkit_fresh_js_")
    try:
        for fn in GEN + ["flow.json"]:
            shutil.copy(os.path.join(EX, fn), os.path.join(tmp, fn))
        _regen("en", tmp)
        got, want = _read(os.path.join(tmp, "fixtures.js")), _read(os.path.join(EX, "fixtures.js"))
        assert got == want, ("fixtures.js 已过期 —— 在 examples/login/ 里跑 "
                             "`python3 make_fixture.py` 并提交结果")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_generated_files_are_lf_and_bom_free():
    for fn in GEN + ["fixtures.js"]:
        b = _read(os.path.join(EX, fn))
        assert b"\r\n" not in b, "%s 含 CRLF —— 生成时要写 newline=\"\"" % fn
        assert not b.startswith(b"\xef\xbb\xbf"), "%s 有 BOM" % fn


def test_zh_variant_still_matches_backend_fixtures():
    """各后端 tests/fixtures 是同一生成器的 zh 产物(故意留着做 CJK 覆盖)。
    几何一改两边都得重生成,这里盯住"没人只改了一半"。"""
    root = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
    backends = [d for d in ("figma2godot", "figma2unity", "figma2unreal", "figma2cocos")
                if os.path.isdir(os.path.join(root, d, "scripts", "tests", "fixtures"))]
    if not backends:
        # skill 文件夹要能单独安装(装成 Claude Code 插件时只拷本目录),
        # 兄弟后端不在场是**正常**情形,不是失败。
        print("    (skip: 同级没有其它后端,单装场景)")
        return
    tmp = tempfile.mkdtemp(prefix="figkit_fresh_zh_")
    try:
        _regen("zh", tmp)
        for d in backends:
            for fn in GEN:
                p = os.path.join(root, d, "scripts", "tests", "fixtures", fn)
                if not os.path.exists(p):
                    continue
                got, want = _read(os.path.join(tmp, fn)), _read(p)
                # 工作副本可能被历史遗留的 CRLF 污染,比对时按行归一化再看内容
                assert got.replace(b"\r\n", b"\n") == want.replace(b"\r\n", b"\n"), (
                    "%s/%s 与 make_fixture.py --lang zh 的产物不一致 —— "
                    "两套夹具必须同批重生成" % (d, fn))
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

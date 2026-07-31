# -*- coding: utf-8 -*-
"""examples/main(主界面示例)的生成物与声明必须自洽。

login 那个示例演的是**管线**(捕获 → IR → 六个后端),界面刻意做到最小。
main 演的是另一件事:**这套 IR 撑不撑得住一个真正的游戏界面**,以及
**引擎不做、只能由 app hook 做的那半边**(飞向目标 / 数字滚动 / 高亮闪)。

守四件事:
  1. 生成物新鲜(同 login);
  2. flow.json 里 figma 原稿导进来的那两条,与 nodes.json 的 interactions[] 对得上 ——
     这条最容易腐烂:改了 fixture 里的连线,flow.json 不会自己跟着变;
  3. 默认动效是 apply_defaults 补出来的、且**幂等**(再跑一遍不该多出东西);
  4. app.js 里**没有硬编的动效数值** —— 值必须来自 fixtures.js 内联的令牌。
     硬编的那份不会跟着 figkit-motion 改,而它看起来和正确的一模一样。
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.abspath(os.path.join(_HERE, "..", "..", "examples", "main"))
ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
GEN = ["screen-main.ui.json", "screen-bag.ui.json", "screen-codex.ui.json"]


def _read(p):
    with open(p, "rb") as f:
        return f.read()


def _json(p):
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def test_committed_fixtures_are_fresh():
    tmp = tempfile.mkdtemp(prefix="figkit_main_fresh_")
    try:
        r = subprocess.run([sys.executable, os.path.join(EX, "make_fixture.py"),
                            "--lang", "en", "--out", tmp],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        for fn in GEN:
            assert _read(os.path.join(tmp, fn)) == _read(os.path.join(EX, fn)), (
                "%s 与 make_fixture.py 的产物不一致 —— 在 examples/main/ 里跑 "
                "`python3 make_fixture.py` 并提交结果" % fn)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_generated_files_are_lf_and_bom_free():
    for fn in GEN + ["fixtures.js", "nodes.json", "flow.json"]:
        b = _read(os.path.join(EX, fn))
        assert b"\r\n" not in b, "%s 含 CRLF" % fn
        assert not b.startswith(b"\xef\xbb\xbf"), "%s 有 BOM" % fn


def test_figma_authored_events_match_the_node_tree():
    """flow.json 里**没有 source 字段**的那些 transition = figma 原稿画的线。
    它们必须能在 nodes.json 的 interactions[] 里逐个找到出处。"""
    flow = _json(os.path.join(EX, "flow.json"))
    nodes = _json(os.path.join(EX, "nodes.json"))

    drawn = {}                                    # 触发元素 id -> 目标屏 id
    def walk(n):
        for it in (n.get("interactions") or []):
            for act in (it.get("actions") or []):
                if act.get("type") == "NODE" and act.get("navigation") == "OVERLAY":
                    drawn[n["id"]] = act["destinationId"]
        for c in (n.get("children") or []):
            walk(c)
    for v in nodes["nodes"].values():
        walk(v["document"])

    # v1.1:原稿还画了第三条线 —— 背包弹窗里的 ✗(CLOSE)。它住在**弹窗那一屏**上,
    # v1.0 的 events 只绑 base 屏,所以当时搬不过来;现在落成 @in:bag:<id>。
    closes = set()
    def walk_close(n, screen):
        for it in (n.get("interactions") or []):
            for act in (it.get("actions") or []):
                if act.get("type") in ("CLOSE", "BACK"):
                    closes.add((screen, n["id"]))
        for c in (n.get("children") or []):
            walk_close(c, screen)
    for v in nodes["nodes"].values():
        walk_close(v["document"], v["document"]["id"])
    assert closes, "夹具里应当有一条弹窗内的 CLOSE 连线"
    for _, nid in closes:
        assert any(str(e["el"]).endswith(":" + nid) and str(e["el"]).startswith("@in:")
                   for e in flow["events"]), \
            "nodes.json 里 %s 上画了 CLOSE,flow.json 里却没有对应的 @in: 事件" % nid

    assert len(drawn) == 2, "夹具里应当正好有两条 OVERLAY 连线,实际 %d" % len(drawn)
    imported = [e for e in flow["events"]
                if e.get("transition") and "source" not in e["transition"]]
    assert len(imported) == 2, "flow.json 里 figma 原稿来的转场应当有两条,实际 %d" % len(imported)
    for e in imported:
        assert e["el"] in drawn, "flow 事件绑在 %s 上,但 nodes.json 里这个元素没连线" % e["el"]


def test_preset_motion_is_generated_and_idempotent():
    """默认动效必须是 apply_defaults 补出来的(每条带 source),且再跑一遍不多出东西。"""
    sys.path.insert(0, os.path.join(ROOT, "figma2html", "scripts"))
    import motion

    flow = _json(os.path.join(EX, "flow.json"))
    filled = [e for e in flow["events"]
              if (e.get("transition") or {}).get("source") == "preset:base"]
    # 三条 closeModal:两条 @panelOutside,加上 v1.1 之后弹窗里那个 ✗(@in:bag:4:12)。
    # 它是 figma 原稿画的线,但原稿没给转场 —— 出场同样由预设补上,所以也带 source。
    assert len(filled) == 3, "三个 closeModal 都该被补上出场,实际 %d" % len(filled)
    for key in ("press", "stagger", "guardFail"):
        assert flow["motion"][key]["source"] == "preset:base", key

    _, added = motion.apply_defaults(json.loads(json.dumps(flow)))
    assert not added, "apply_defaults 不幂等,又补出了:%s" % added


def test_hook_reads_tokens_instead_of_hardcoding_numbers():
    """app.js 里的动效数值必须来自令牌。裸数字看起来和正确的一模一样,却不会跟着目录改。"""
    src = io.open(os.path.join(EX, "app.js"), encoding="utf-8").read()
    used = set(re.findall(r"TOK\['([a-z0-9-]+)'\]", src))
    assert used, "app.js 一个令牌都没用"

    bundle = io.open(os.path.join(EX, "fixtures.js"), encoding="utf-8").read()
    inlined = json.loads(bundle[bundle.index("{"):bundle.rindex(";")])["motion-tokens"]
    missing = sorted(used - set(inlined))
    assert not missing, "app.js 用了没内联进 fixtures.js 的令牌:%s" % missing

    # 令牌名必须真的在目录里(打错一个字母就会静默走 fallback 值)
    catalog = os.path.join(ROOT, "figkit-motion", "tokens.json")
    if os.path.exists(catalog):
        known = set(_json(catalog))
        unknown = sorted(set(inlined) - known)
        assert not unknown, "fixtures.js 内联了目录里没有的令牌:%s" % unknown


def _run():
    ok = True
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception as e:                              # noqa: BLE001
                ok = False
                print("FAIL", name, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)

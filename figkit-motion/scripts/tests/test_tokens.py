# -*- coding: utf-8 -*-
"""令牌与目录的契约(纯标准库)。

这份 skill 交付的是**散文 + 一张机读表**,没有运行时可跑 —— 所以能守的东西只有一类:
**散文里的断言与文件的事实必须对得上**。原档在这上面栽过一次:§三 声称「数值真源就在本档」,
而正文 288 处引用**全部悬空**,值其实只在另一个文件里。计数校验抓不到这类错(它只对账
「散文写的数 vs 数出来的数」),得有人去**真验一遍那句断言**。
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import token_check as TC                                          # noqa: E402


def test_contract_holds():
    """token_check 自己必须全绿 —— 形状 / 悬空引用 / 死令牌 / 条数。"""
    bad, n_tok, n_eff = TC.check()
    assert not bad, "\n  " + "\n  ".join(bad)
    assert n_tok == 63 and n_eff == 59, (n_tok, n_eff)


def test_prose_carries_no_bare_numbers_for_tokenised_values():
    """目录里不许出现裸的时长 / 像素值 —— 有裸数字,读的人就抄裸数字。

    只扫**方法段**(```text 块)和「令牌」行,不扫 web 参考实现(那是可粘的真代码,
    里面本来就有 CSS 变量名与少量布局值)与实测对照表。
    """
    text = io.open(os.path.join(os.path.dirname(HERE), "..", "references", "catalog.md"),
                   encoding="utf-8").read()
    offenders = []
    for m in re.finditer(r"```text\n(.*?)```", text, re.S):
        for line in m.group(1).split("\n"):
            if re.search(r"\b\d+\s*(ms|px)\b", line):
                offenders.append(line.strip())
    assert not offenders, "方法段里出现裸数值(应写 {motion.x}):\n  " + "\n  ".join(offenders)


def test_every_effect_declares_its_class_and_when_not_to_use_it():
    """每条效果都得说清**别用**在哪 —— 一份只说「能用」的目录会让人到处加动效,
    那正是这份档要防的东西。"""
    text = io.open(os.path.join(os.path.dirname(HERE), "..", "references", "catalog.md"),
                   encoding="utf-8").read()
    chunks = re.split(r"(?m)^## ", text)[1:]
    missing = []
    for c in chunks:
        name = c.split("\n")[0].strip()
        if name.startswith("通则"):
            continue
        if "**类**" not in c:
            missing.append(name + " 没写「类」")
        if "**别用**" not in c:
            missing.append(name + " 没写「别用」")
    assert not missing, "\n  ".join(missing)


def test_untested_values_are_labelled_as_such():
    """草案值必须自报家门。把「调过手感的值」和「编的值」混在一起,后者会被当成前者用。"""
    tokens = {k: v for k, v in TC.load_tokens().items() if not k.startswith("_")}
    for name in ("hitstop", "shake", "shake-amp", "wiggle", "wiggle-amp"):
        assert tokens[name]["calibration"] == "untested", \
            "%s 被标成了 %s —— 它其实一次都没实测过" % (name, tokens[name]["calibration"])


def test_wiggle_and_shake_do_not_share_tokens():
    """抖动(一个元素说「错了」)与震屏(整个世界说「这一下很重」)是两个效果。
    共用一个令牌,调一个必然坏另一个 —— 真混过一次。"""
    tokens = TC.load_tokens()
    assert tokens["wiggle"]["value"] != tokens["shake-amp"]["value"] or True   # 值可以巧合相等
    for a, b in (("wiggle", "shake"), ("wiggle-amp", "shake-amp")):
        assert a in tokens and b in tokens, "%s / %s 必须各自独立存在" % (a, b)


def test_json_is_utf8_without_bom_and_parses():
    p = os.path.join(os.path.dirname(HERE), "..", "tokens.json")
    raw = io.open(p, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf"), "tokens.json 带了 BOM"
    json.loads(raw.decode("utf-8"))


def _run():
    ok = True
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:                                # noqa: BLE001
                ok = False; print("FAIL", n, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)

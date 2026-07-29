# -*- coding: utf-8 -*-
"""token_check.py — 令牌契约校验器(纯标准库)。

用法:
    python3 token_check.py            # 跑本 skill 自己的契约

**为什么需要它。** 这份目录的数值真源是 `tokens.json`,散文里只许写 `{motion.x}` 引用。
散文和数值一旦各写一份,两份必然漂;而漂了**没有任何症状** —— 文档照样读得通顺,
只是里面的数字是错的。所以三条都得机器验:

  1. **每条令牌的形状合法** —— `value` / `use` / `calibration` 齐全,校准分档只有三种。
     `calibration` 是最容易被跳过、也最重要的一栏:它把「我们决定过这个值」和
     「我们还没管这个值」分开。没有它,两者在表里长得一模一样,而后者是坑。
  2. **散文里的每个 `{motion.x}` 都有定义** —— 悬空引用 = 读者查不到值。
     (原档真出过一次:正文 288 处引用全部悬空,因为「真源」那一节根本不存在。)
  3. **没有死令牌** —— 定义了却没有任何效果引用 = 它多半是想当然加的。
     反向检查抓到过一个「备用」令牌,59 条效果里没有一条用它。

另外顺带数一遍效果条数,免得散文里的「59 条」和实际条数对不上。
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOKENS = os.path.join(ROOT, "tokens.json")
REFS = os.path.join(ROOT, "references")

CALIBRATIONS = ("tuned", "inherited", "untested")
REF_RE = re.compile(r"\{motion\.([a-z0-9-]+)\}")
EFFECT_RE = re.compile(r"(?m)^## (?!通则)(.+)$")
EXPECTED_EFFECTS = 59


def load_tokens():
    with io.open(TOKENS, encoding="utf-8") as f:
        return json.load(f)


def read_refs():
    out = {}
    for fn in sorted(os.listdir(REFS)):
        if fn.endswith(".md"):
            with io.open(os.path.join(REFS, fn), encoding="utf-8") as f:
                out[fn] = f.read()
    return out


def check():
    bad = []
    data = load_tokens()
    tokens = {k: v for k, v in data.items() if not k.startswith("_")}

    for name, spec in sorted(tokens.items()):
        if not isinstance(spec, dict):
            bad.append("令牌 %s 不是一个对象" % name)
            continue
        for field in ("value", "use", "calibration"):
            if field not in spec:
                bad.append("令牌 %s 缺 %s" % (name, field))
        cal = spec.get("calibration")
        if cal is not None and cal not in CALIBRATIONS:
            bad.append("令牌 %s 的 calibration=%r 不在 %s 里" % (name, cal, list(CALIBRATIONS)))

    refs = read_refs()
    used = set()
    for fn, text in refs.items():
        for m in REF_RE.finditer(text):
            used.add(m.group(1))
            if m.group(1) not in tokens:
                bad.append("%s 引用了不存在的令牌 {motion.%s}" % (fn, m.group(1)))

    for name in sorted(tokens):
        if name not in used:
            bad.append("令牌 %s 定义了却没有任何地方引用(死令牌)" % name)

    catalog = refs.get("catalog.md", "")
    n = len(EFFECT_RE.findall(catalog))
    if n != EXPECTED_EFFECTS:
        bad.append("catalog.md 数出 %d 条效果,期望 %d 条" % (n, EXPECTED_EFFECTS))

    return bad, len(tokens), n


def main():
    bad, n_tok, n_eff = check()
    if bad:
        sys.stderr.write("令牌契约不成立:\n")
        for b in bad:
            sys.stderr.write("  - %s\n" % b)
        return 1
    print("OK: %d tokens, %d effects" % (n_tok, n_eff))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

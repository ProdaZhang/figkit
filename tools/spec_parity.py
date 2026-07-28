# -*- coding: utf-8 -*-
"""spec parity — spec/ 权威版 vs figma2html/references/ 随包副本 一致性守卫。

spec/<name>.md = 版本头(连续的 "> " 引用行 + 一个空行) + 副本原文。
本脚本剥掉版本头后与 figma2html/references/<name>.md 逐字节比对。
用法: python3 tools/spec_parity.py   (仓库根执行;exit 0=一致, 1=漂移)
改法: 内容改动先落 figma2html/references/(随 skill 分发),再同步进 spec/(保留版本头,
      结构性变更须按冻结纪律升版本号并更新头部变更史)。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("ui.json-schema.md", "flow-events.md")


def strip_header(text):
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith(">"):
        i += 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return "\n".join(lines[i:])


def main():
    bad = []
    for name in FILES:
        spec = open(os.path.join(ROOT, "spec", name), encoding="utf-8").read()
        ref = open(os.path.join(ROOT, "figma2html", "references", name), encoding="utf-8").read()
        if strip_header(spec) != ref:
            bad.append(name)
            print("DRIFT:", name, "(spec 剥头后 != figma2html/references 副本)")
        else:
            print("OK:", name)
    if bad:
        print("FAIL: spec 与随包副本漂移 —— 改动先落 references/ 再同步 spec/(保留版本头)。")
        return 1
    print("spec parity holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

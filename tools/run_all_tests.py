# -*- coding: utf-8 -*-
"""run_all_tests.py — 仓库唯一的测试入口(跨平台,纯标准库)。

用法:
    python3 tools/run_all_tests.py            # 全部:spec parity + 六套 skill 测试
    python3 tools/run_all_tests.py godot dsl  # 只跑指定后端(前缀匹配 figma2*)
    python3 tools/run_all_tests.py --list     # 看有哪些套件

**为什么要它**:此前文档给的是一段 bash for-loop,Windows 贡献者跑不了;
CI 里另抄了一份同样的循环 —— 同一件事三处真源,迟早对不上。现在文档和 CI 都调这个。

退出码 0 = 全绿。任何一套失败都会在末尾汇总,并以非 0 退出。
"""
import os
import subprocess
import sys

# 测试输出含中文;Windows 控制台默认代码页(CI 上是非 CJK)会让 print 抛 UnicodeEncodeError,
# 整套测试因此在 windows-latest 上红 —— 与被测逻辑毫无关系。各套 run_all.py 里也有同样一段。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
BACKENDS = ["figma2dsl", "figma2html", "figma2unity",
            "figma2godot", "figma2unreal", "figma2cocos"]


def _run(title, argv, cwd):
    print("\n== %s ==" % title, flush=True)
    r = subprocess.run([sys.executable] + argv, cwd=cwd)
    return r.returncode == 0


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if "--list" in argv[1:]:
        print("spec-parity")
        for b in BACKENDS:
            print(b)
        return 0

    picked = BACKENDS if not args else [
        b for b in BACKENDS if any(a.lower().lstrip("figma2") in b.lower() for a in args)]
    if not picked:
        print("没有匹配的套件: %s(可选: %s)" % (", ".join(args), ", ".join(BACKENDS)),
              file=sys.stderr)
        return 2

    failed = []
    if picked == BACKENDS:      # 只在跑全量时校验 spec 一致性与跨后端一致性
        if not _run("spec parity", [os.path.join("tools", "spec_parity.py")], ROOT):
            failed.append("spec-parity")
        if not _run("conformance (cross-backend)", ["run_all.py"],
                    os.path.join(ROOT, "tools", "conformance")):
            failed.append("conformance")

    for b in picked:
        d = os.path.join(ROOT, b, "scripts", "tests")
        if not os.path.isdir(d):
            print("跳过 %s(没有 scripts/tests)" % b)
            continue
        if not _run(b, ["run_all.py"], d):
            failed.append(b)

    print("\n" + "-" * 56)
    if failed:
        print("FAILED: " + ", ".join(failed), file=sys.stderr)
        return 1
    print("ALL GREEN (%d 套)" % (len(picked) + (2 if picked == BACKENDS else 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

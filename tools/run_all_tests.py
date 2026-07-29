# -*- coding: utf-8 -*-
"""run_all_tests.py — 仓库唯一的测试入口(跨平台,纯标准库)。

用法:
    python3 tools/run_all_tests.py            # 全部:spec parity + 七套 skill 测试
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
# 七套 skill。前六个是后端(吃 IR、产东西);figkit-motion 是**查阅层** ——
# 它不产物、不吃 IR,但它的 tokens.json 是 motion.py 那份预设的出处,所以同样要跑测试。
SUITES = ["figma2dsl", "figma2html", "figma2unity",
          "figma2godot", "figma2unreal", "figma2cocos", "figkit-motion"]


_COUNTS = {}        # 套件名 -> 通过的检查条数(顺带数出来,不额外跑第二遍)


def _run(title, argv, cwd, key=None):
    print("\n== %s ==" % title, flush=True)
    # 捕获后原样转印:既保留实时可读的输出,又能顺手数 PASS 条数供 README 核对。
    r = subprocess.run([sys.executable] + argv, cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    sys.stdout.write(out)
    sys.stdout.flush()
    if key:
        _COUNTS[key] = sum(1 for ln in out.split("\n") if "PASS" in ln)
    return r.returncode == 0


def check_readme_counts():
    """README 状态矩阵里的用例数必须与真实跑出来的一致 → 不一致的说明列表。

    手写的数字一定会过期(实测过:godot 16→20、cocos 7→11 都悄悄错了,而那是
    访客最先看的一张表)。这里不额外跑测试,直接用上面顺手数到的条数比对。"""
    import re
    path = os.path.join(ROOT, "README.md")
    with open(path, encoding="utf-8") as f:
        readme = f.read()
    bad = []
    for name, got in sorted(_COUNTS.items()):
        if name == "conformance":
            # 一致性套件不在矩阵里,写在矩阵下面那句散文里("**N more live in ...**")
            m = re.search(r"\*\*(\d+) more live in \[`tools/conformance/`\]", readme)
            if not m:
                bad.append("README 里找不到 conformance 的条数(实际 %d 例)" % got)
            elif int(m.group(1)) != got:
                bad.append("README 说 conformance 有 %s 例,实际 %d 例" % (m.group(1), got))
            continue
        m = re.search(r"^\| %s \| ✅ (\d+) \|" % re.escape(name), readme, re.M)
        if not m:
            bad.append("README 矩阵里没有 %s 的用例数(应写成 `| %s | ✅ %d |`)" % (name, name, got))
        elif int(m.group(1)) != got:
            bad.append("README 说 %s 有 %s 例,实际 %d 例" % (name, m.group(1), got))
    return bad


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if "--list" in argv[1:]:
        print("spec-parity")
        for b in SUITES:
            print(b)
        return 0

    picked = SUITES if not args else [
        b for b in SUITES if any(a.lower().lstrip("figma2") in b.lower() for a in args)]
    if not picked:
        print("没有匹配的套件: %s(可选: %s)" % (", ".join(args), ", ".join(SUITES)),
              file=sys.stderr)
        return 2

    failed = []
    if picked == SUITES:      # 只在跑全量时校验 spec 一致性与跨后端一致性
        if not _run("spec parity", [os.path.join("tools", "spec_parity.py")], ROOT):
            failed.append("spec-parity")
        if not _run("conformance (cross-backend)", ["run_all.py"],
                    os.path.join(ROOT, "tools", "conformance"), key="conformance"):
            failed.append("conformance")

    for b in picked:
        d = os.path.join(ROOT, b, "scripts", "tests")
        if not os.path.isdir(d):
            print("跳过 %s(没有 scripts/tests)" % b)
            continue
        if not _run(b, ["run_all.py"], d, key=b):
            failed.append(b)

    if picked == SUITES and not failed:   # 全量且全绿时才核 README(局部跑数字必然对不上)
        stale = check_readme_counts()
        if stale:
            print("\n== README 矩阵 ==")
            for line in stale:
                print("  " + line, file=sys.stderr)
            failed.append("readme-counts")

    print("\n" + "-" * 56)
    if failed:
        print("FAILED: " + ", ".join(failed), file=sys.stderr)
        return 1
    print("ALL GREEN (%d 套)" % (len(picked) + (2 if picked == SUITES else 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

# -*- coding: utf-8 -*-
"""sync_shared.py — 把共享文件从主拷贝同步到各 skill 的镜像(纯标准库,跨平台)。

    python3 tools/sync_shared.py            # 只查,不改(默认;有漂移退出 1)
    python3 tools/sync_shared.py --sync     # 主拷贝 → 各镜像
    python3 tools/sync_shared.py --sync --force   # 明知镜像更新,仍然按主拷贝覆盖

**为什么会有镜像。** 七个 skill 必须能**单独安装**(CONTRIBUTING 原则 3),所以
`motion.py`(五份)与 `figma_capture.py`(两份)是有意重复的 —— 这一条不打算靠 DRY 消灭。

**为什么要这支工具。** 重复本身有测试守着(逐字节一致,漂了就红),但同步一直是手工 `cp`:
改完主拷贝要记得复制到另外四个地方,漏一个只有 CI 会告诉你。工具管这一步,
测试继续管"有没有漏"。

`--sync` 会先看一眼**镜像是不是比主拷贝新**。是的话多半是改错了地方 —— 把编辑落在了
镜像上,这时候同步等于把刚写的东西删掉。默认拒绝,`--force` 才继续。
"""
import filecmp
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 主拷贝 → 镜像。主拷贝是**唯一真源**,改动一律先落这里。
MIRRORS = {
    os.path.join("figma2html", "scripts", "motion.py"): [
        os.path.join("figma2godot", "scripts", "motion.py"),
        os.path.join("figma2unity", "scripts", "motion.py"),
        os.path.join("figma2unreal", "scripts", "motion.py"),
        os.path.join("figma2cocos", "scripts", "motion.py"),
    ],
    os.path.join("figma2html", "scripts", "figma_capture.py"): [
        os.path.join("figma2dsl", "scripts", "figma_capture.py"),
    ],
}


def same(a, b):
    return os.path.exists(b) and filecmp.cmp(a, b, shallow=False)


def main(argv):
    do_sync = "--sync" in argv
    force = "--force" in argv
    drift, newer = [], []

    for rel_master, rel_copies in sorted(MIRRORS.items()):
        master = os.path.join(ROOT, rel_master)
        if not os.path.exists(master):
            print("主拷贝不在:%s" % rel_master, file=sys.stderr)
            return 2
        for rel in rel_copies:
            copy = os.path.join(ROOT, rel)
            if same(master, copy):
                continue
            drift.append((rel_master, rel))
            if os.path.exists(copy) and os.path.getmtime(copy) > os.path.getmtime(master):
                newer.append(rel)

    if not drift:
        print("镜像与主拷贝一致(%d 份)" % sum(len(v) for v in MIRRORS.values()))
        return 0

    for rel_master, rel in drift:
        print("漂移:%s  ≠  %s" % (rel, rel_master))
    if not do_sync:
        print("\n改动先落主拷贝,再 `python3 tools/sync_shared.py --sync`", file=sys.stderr)
        return 1

    if newer and not force:
        print("\n以下镜像**比主拷贝新** —— 大概率是改错了地方(编辑落在镜像上):",
              file=sys.stderr)
        for rel in newer:
            print("  " + rel, file=sys.stderr)
        print("同步会把这些改动覆盖掉。确认无误就加 --force;\n"
              "若确实该保留,先把它们挪回主拷贝再同步。", file=sys.stderr)
        return 1

    for rel_master, rel in drift:
        shutil.copyfile(os.path.join(ROOT, rel_master), os.path.join(ROOT, rel))
        print("已同步 %s ← %s" % (rel, rel_master))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

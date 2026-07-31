# -*- coding: utf-8 -*-
"""cocos 运行时的 TS 严格类型门 —— 跑一次,并证明它真的会拦。

    cd tools/cocos-typecheck && npm ci && python3 check.py

**为什么单独有这么一支。** README / SKILL.md / mapping.md 三处一直写着 cocos 的 TS
"已过 tsc --noEmit 对官方 @cocos/creator-types 3.8 的严格类型门,故意错用 API 会被抓"。
话是真的,但当时仓库里**没有 tsconfig、没有 package.json、没有任何依赖声明,CI 也不跑它** ——
门只存在于作者本机,clone 下来的人复现不了、CI 守不住。这支脚本把那句话变成可执行的。

它做两件事,缺一不可:

  1. `tsc -p tsconfig.json` 必须零错;
  2. **往真源码里种一个必然的类型错误,tsc 必须报出来。** 只跑第 1 步证明不了门有牙 ——
     配置写歪(比如 d.ts 根本没加载、或 files 是空的)时,它同样零错、同样"绿"。

跑完源码原样还原(`finally`)。

⚠️ 这里和 `tools/docs-assets/` 一样,是**不守"纯标准库/零依赖"那条规矩**的地方,所以它在
`tools/` 而不是 `figma2cocos/` 里 —— 七个 skill 必须能单独安装且零依赖,不该因为一道
开发期的门就给使用者塞一个 node 工具链。`tools/run_all_tests.py` 因此也不碰它。
"""
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PROBE = os.path.join(ROOT, "figma2cocos", "runtime", "flow-binder.ts")

# 种进去的错误要**同时**证明三件事:cc 的声明被加载了、成员类型是真的、赋值检查开着。
# `position.x` 是 number,接给 string 必然 TS2322 —— 若 d.ts 没加载,报的会是别的码。
TEETH = "\nconst _figkitTeeth: string = new Node('teeth').position.x;\n"
TEETH_CODE = "TS2322"


def tsc():
    npx = "npx.cmd" if os.name == "nt" else "npx"
    r = subprocess.run([npx, "tsc", "-p", "tsconfig.json"], cwd=HERE,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    if not os.path.isdir(os.path.join(HERE, "node_modules")):
        print("先装依赖:cd tools/cocos-typecheck && npm ci", file=sys.stderr)
        return 2

    code, out = tsc()
    if code != 0:
        print("类型门没过:\n" + out, file=sys.stderr)
        return 1
    print("PASS runtime_typechecks_clean")

    src = io.open(PROBE, encoding="utf-8", newline="").read()
    io.open(PROBE, "w", encoding="utf-8", newline="").write(src + TEETH)
    try:
        code, out = tsc()
    finally:
        io.open(PROBE, "w", encoding="utf-8", newline="").write(src)
    if code == 0 or TEETH_CODE not in out:
        print("门没牙:种了必然的类型错误,tsc 却没报 %s\n%s" % (TEETH_CODE, out), file=sys.stderr)
        return 1
    print("PASS gate_has_teeth")
    return 0


if __name__ == "__main__":
    sys.exit(main())

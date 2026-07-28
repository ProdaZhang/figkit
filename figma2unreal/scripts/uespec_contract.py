# -*- coding: utf-8 -*-
"""uespec_contract.py — uespec 契约对账门(python 产出字段 ↔ C++ 读取字段)。

用法:
    python3 uespec_contract.py          # 全绿 exit 0;有漂移打印明细并 exit 1

**为什么要这个门**:figma2unreal 是跨语言两段式 —— `ui_to_uespec.py` 产出 uespec.json,
C++ 运行时零解析地读它。两边字段名的一致性**没有任何编译器管**:python 加个字段而
C++ 不读 = 静默失效;C++ 读个 python 从不产的字段 = 永远吃默认值。两种都编得过、跑不炸,
只是界面悄悄不对。本门就是这条缝的守卫,不需要装引擎。

判据(两向):
  A. **读了但没人产** → 直接 FAIL,无豁免。运行时必然吃默认值。
  B. **产了但没人读** → 必须在 WAIVERS 里声明理由(known-loss 或元数据),否则 FAIL;
     反过来,WAIVERS 里若有已经被读了的键(陈旧豁免)也 FAIL —— 防止豁免表烂掉。

取值口径:
  - python 侧 = **静态**抽 `ui_to_uespec.py` 里函数体内 dict 字面量的键 + 下标赋值键。
    不跑 fixture:产出哪些键不该取决于样例数据覆盖到没有(如无渐变样例就抽不到 stops)。
    模块级常量表(_IMG_MODE/_ALIGN)是查表不是产出,跳过。
  - C++ 侧 = 平衡括号解析 JSON 取值调用(JNum/JStr/ColorFromField/(Try)GetXField)的
    **第 1-2 个实参**里的 TEXT("…") 字面量。只取实参位,避免把同语句里 UE_LOG 的
    格式串误当字段名。

已知边界(诚实降级):比对是**扁平名字级**,不是路径级。C++ 把嵌套对象读进局部变量再取字段,
拿不到可靠路径;因此同名不同层会互相遮蔽(如元素的 radius 会遮住 blur.radius)。
本门管的是"字段词汇表漂移",层级语义仍靠 golden 测试与 mapping.md 保证。
"""
import ast
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
PY_SRC = os.path.join(_HERE, "ui_to_uespec.py")
CPP_SRCS = [os.path.join(_ROOT, "runtime", n)
            for n in ("FigmaUiWidget.cpp", "FigmaFlowComponent.cpp")]

# 产了但 C++ 不读的键 → 每个都要有理由。理由须与 references/mapping.md 对得上。
WAIVERS = {
    # —— known-loss(mapping.md §4):uespec 里备着,运行时按已声明的损失不消费 ——
    "angleDeg": "known-loss 渐变:C++ 只取首停靠色回退,角度留给后续材质路线",
    "pos":      "known-loss 渐变:停靠位置同上,回退路径用不到",
    "dx":       "known-loss box-shadow:不渲染,只 UE_LOG",
    "dy":       "known-loss box-shadow:不渲染,只 UE_LOG",
    "family":   "known-loss 字体族:统一 DefaultFontObject,uespec 仅记录",
    # —— 元数据/上游产物,不参与建树 ——
    "version":  "uespec 版本号,给人和工具看",
    "frame":    "figma 帧 id,溯源用",
    "name":     "figma 图层名,调试/溯源用",
    "vec":      "矢量簇折叠标志:实际渲染走 img 通用路径,标志本身运行时不消费",
    "stage":    "flow.stage{w,h}:UE 侧分辨率适配由 Project Settings DPI 曲线负责"
                "(mapping.md §5-6),运行时不读",
}

_JSON_CALL = re.compile(
    r'\b(?:JNum|JStr|ColorFromField|'
    r'(?:Try)?Get(?:String|Number|Bool|Array|Object|Integer)Field)\s*\(')
_TEXT_LIT = re.compile(r'TEXT\("([^"]+)"\)\s*$')


def emitted_keys(src):
    """静态抽 python 产出的字段名集合(只看函数体内的 dict 字面量与下标赋值)。"""
    out = set()
    for node in ast.parse(src).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Dict):
                for k in sub.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        out.add(k.value)
            elif isinstance(sub, ast.Assign):
                for tgt in sub.targets:      # out['x'] = ... 也是产出
                    if (isinstance(tgt, ast.Subscript)
                            and isinstance(tgt.slice, ast.Constant)
                            and isinstance(tgt.slice.value, str)):
                        out.add(tgt.slice.value)
    return out


def _args(s, lparen):
    """从 '(' 位置起解析平衡括号实参表 → 顶层实参字符串列表。"""
    depth, cur, out, i = 0, "", [], lparen
    while i < len(s):
        ch = s[i]
        if ch == "(":
            depth += 1
            if depth == 1:
                i += 1
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                out.append(cur.strip())
                return out
        if ch == "," and depth == 1:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    return out                                   # 括号不闭合:交给编译器管,这里不报


def read_keys(src):
    """抽 C++ 从 uespec 读取的字段名集合。"""
    out = set()
    for m in _JSON_CALL.finditer(src):
        for cand in _args(src, m.end() - 1)[:2]:  # 字段名只可能在第 1 或第 2 实参
            lit = _TEXT_LIT.match(cand)
            if lit:
                out.add(lit.group(1))
                break
    return out


def check(emitted, read, waivers=WAIVERS):
    """→ 错误行列表(空 = 契约成立)。"""
    errors = []
    for k in sorted(read - emitted):
        errors.append('C++ 读了 uespec 字段 "%s",但 ui_to_uespec.py 从不产出它 '
                      '→ 运行时必然吃默认值' % k)
    for k in sorted(emitted - read - set(waivers)):
        errors.append('ui_to_uespec.py 产出字段 "%s",但 C++ 从不读它 '
                      '→ 要么接上,要么进 WAIVERS 写明理由' % k)
    for k in sorted(set(waivers) & read):
        errors.append('WAIVERS 里的 "%s" 其实已经被 C++ 读了 → 陈旧豁免,删掉它' % k)
    for k in sorted(set(waivers) - emitted):
        errors.append('WAIVERS 里的 "%s" 已经不再被产出 → 陈旧豁免,删掉它' % k)
    return errors


def _read_file(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()


def run():
    emitted = emitted_keys(_read_file(PY_SRC))
    read = set()
    for p in CPP_SRCS:
        read |= read_keys(_read_file(p))
    return emitted, read, check(emitted, read)


def main():
    emitted, read, errors = run()
    print("[uespec-contract] python 产出 %d 字段 / C++ 读取 %d 字段 / 已声明豁免 %d"
          % (len(emitted), len(read), len(WAIVERS)))
    if errors:
        for e in errors:
            print("[uespec-contract] 契约漂移: " + e, file=sys.stderr)
        return 1
    print("[uespec-contract] 契约成立:无未声明漂移。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

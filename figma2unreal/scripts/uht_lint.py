# -*- coding: utf-8 -*-
"""uht_lint.py — UE 反射规约静态检查门(无需安装引擎)。

用法:
    python3 uht_lint.py          # 全绿 exit 0;有违规打印明细并 exit 1

**为什么要这个门**:runtime/ 的 C++ 交付态是"源码 + 集成说明",没有引擎就没有 UHT、
没有编译器。但**首次集成最容易炸的那批错并不是普通 C++ 错**,而是 UHT 规约错:
.generated.h 没放最后、UCLASS 漏 GENERATED_BODY、UINTERFACE 没配 I 类、
BlueprintNativeEvent 被直呼而不是走 Execute_、UObject 指针成员漏 UPROPERTY 导致 GC 收走。
这些都能在**不装引擎**的前提下确定性地静态查出来。

诚实边界(这门**不是**编译):
  - 它查的是 UE 的**规约**,不是 API 真值。`FSlateFontInfo` 到底有没有 LetterSpacing 字段
    这类问题,只有真编译(或对官方头文件做符号核对)才能回答 —— 见 README 状态矩阵。
  - 规则来自 UE 5.x 的成文约定,由本文件的 fixture 反向证明"写错真会被抓";
    它不能证明"没被抓的就一定对"。

规则:
  R1  含反射宏的头必须 #include "<自身名>.generated.h",且它必须是**最后一个** include
  R2  每个 UCLASS/USTRUCT/UINTERFACE 的类体内必须有 GENERATED_BODY()
  R3  UINTERFACE 的 U<Name> 必须配一个 I<Name>,且 I 类也要有 GENERATED_BODY()
  R4  BlueprintNativeEvent 函数只能经 Execute_<Name> 调用,禁止 ->Name(/.Name( 直呼
      (直呼会绕过蓝图实现:编得过、跑起来什么都不发生)
  R5  UCLASS 内持有 UObject 指针的成员必须有 UPROPERTY(否则 GC 看不见 → 悬垂);
      确有理由的例外用 `// GC-OK: 理由` 就近标注
  R6  每个 include 必须登记所属模块,且所需模块 ⊆ references/mapping.md §5 Build.cs 里
      声明的模块(把文档和代码钉在一起,防"文档说依赖 A、代码其实要 B")
"""
import io
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
RUNTIME = os.path.join(_ROOT, "runtime")
MAPPING_MD = os.path.join(_ROOT, "references", "mapping.md")

# include → 所属模块。新增 include 必须在这里登记(R6 的"登记纪律",不是 API 真值表)。
INCLUDE_MODULE = {
    "CoreMinimal.h": "Core",
    "Misc/FileHelper.h": "Core",
    "Misc/Paths.h": "Core",
    "UObject/Interface.h": "CoreUObject",
    "Dom/JsonObject.h": "Json",
    "Serialization/JsonReader.h": "Json",
    "Serialization/JsonSerializer.h": "Json",
    "Components/ActorComponent.h": "Engine",
    "Engine/Texture2D.h": "Engine",
    "GameFramework/PlayerController.h": "Engine",
    "Blueprint/UserWidget.h": "UMG",
    "Blueprint/WidgetTree.h": "UMG",
    "Components/Border.h": "UMG",
    "Components/Button.h": "UMG",
    "Components/CanvasPanel.h": "UMG",
    "Components/CanvasPanelSlot.h": "UMG",
    "Components/Image.h": "UMG",
    "Components/TextBlock.h": "UMG",
    "Styling/SlateBrush.h": "SlateCore",
    "Styling/SlateTypes.h": "SlateCore",
}

_REFLECT_MACRO = re.compile(r'^\s*(UCLASS|USTRUCT|UINTERFACE|UENUM)\s*\(', re.M)
_INCLUDE = re.compile(r'^\s*#include\s+"([^"]+)"', re.M)
_UOBJ_MEMBER = re.compile(
    r'\b(TObjectPtr\s*<|TScriptInterface\s*<|TSubclassOf\s*<|TWeakObjectPtr\s*<'
    r'|(?<![:\w])[AU][A-Z]\w*\s*\*)')
_GC_OK = re.compile(r'//\s*GC-OK\s*:')


def _read(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()


def _strip_block_comments(s):
    """去掉 /* */ 块注释(保留行数无关紧要,本门按内容而非行号报错)。"""
    return re.sub(r'/\*.*?\*/', ' ', s, flags=re.S)


def _normalize_macros(src):
    """把 UCLASS(ClassGroup = (FigmaUi), meta = (…)) 这类**含嵌套括号**的反射宏压成
    `UCLASS()`,好让后面的类体正则不被内层括号截断(踩过:嵌套括号让整个类漏检)。"""
    out, i = [], 0
    pat = re.compile(r'\b(UCLASS|USTRUCT|UINTERFACE|UENUM)\s*\(')
    while True:
        m = pat.search(src, i)
        if not m:
            out.append(src[i:])
            return "".join(out)
        out.append(src[i:m.start()])
        depth, j = 0, m.end() - 1
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(m.group(1) + "()")
        i = j + 1


def _class_bodies(src):
    """→ [(kind, class_name, body_src)];kind ∈ UCLASS/USTRUCT/UINTERFACE/plain。
    plain = 没有反射宏的裸 class/struct(R5 的传递判定要用到)。"""
    out = []
    src = _normalize_macros(src)
    for m in re.finditer(r'^[ \t]*(?:(UCLASS|USTRUCT|UINTERFACE)\s*\([^)]*\)\s*\n)?'
                         r'[ \t]*(?:class|struct)\s+(?:\w+_API\s+)?(\w+)'
                         r'(?:\s*:\s*[^{;]+)?\s*\{',
                         src, re.M):
        kind, name = m.group(1) or "plain", m.group(2)
        depth, i = 0, m.end() - 1
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out.append((kind, name, src[m.end():i]))
    return out


def _member_lines(body):
    """类体里"看着像成员变量"的行:顶层(不在嵌套括号里)、无 '('(排除函数)、以 ; 结尾。"""
    lines, depth = [], 0
    for raw in body.split("\n"):
        line = raw.split("//")[0]
        stripped = line.strip()
        if depth == 0 and stripped.endswith(";") and "(" not in stripped \
                and not stripped.startswith(("using", "typedef", "friend", "return")):
            lines.append(raw)
        depth += line.count("{") - line.count("}")
    return lines


def _gc_ok_above(body_lines, idx):
    """成员上方**紧邻的注释块**里有 // GC-OK: 即视为已声明例外(允许多行说明)。"""
    j = idx - 1
    while j >= 0:
        s = body_lines[j].strip()
        if not s:
            j -= 1
            continue
        if not s.startswith("//"):
            return False
        if _GC_OK.search(s):
            return True
        j -= 1
    return False


def _prev_meaningful(body_lines, idx):
    """往上找最近一条非空、非注释行(UPROPERTY 判定用)。"""
    j = idx - 1
    while j >= 0:
        s = body_lines[j].strip()
        if s and not s.startswith("//") and not s.startswith("*") and not s.startswith("/*"):
            return s
        j -= 1
    return ""


# ── 规则 ─────────────────────────────────────────────────────────────────────

def check_headers(headers):
    """R1/R2/R3 —— 只查 .h。headers: {文件名: 源码}"""
    errors = []
    for fname, raw in sorted(headers.items()):
        src = _strip_block_comments(raw)
        stem = fname[:-2] if fname.endswith(".h") else fname
        includes = _INCLUDE.findall(src)
        has_reflection = bool(_REFLECT_MACRO.search(src))

        # R1
        gen = stem + ".generated.h"
        if has_reflection:
            if gen not in includes:
                errors.append('R1 %s 有反射宏但没 #include "%s"' % (fname, gen))
            elif includes[-1] != gen:
                errors.append('R1 %s 的 "%s" 不是最后一个 include(最后是 "%s")'
                              '——UHT 硬性要求放最后' % (fname, gen, includes[-1]))
        elif gen in includes:
            errors.append('R1 %s 没有任何反射宏,却 include 了 "%s"' % (fname, gen))

        bodies = _class_bodies(src)
        names = {n for _, n, _ in bodies}
        for kind, name, body in bodies:
            # R2
            if kind in ("UCLASS", "USTRUCT", "UINTERFACE") and "GENERATED_BODY()" not in body:
                errors.append("R2 %s 的 %s %s 类体里没有 GENERATED_BODY()" % (fname, kind, name))
            # R3
            if kind == "UINTERFACE":
                if not name.startswith("U"):
                    errors.append("R3 %s 的 UINTERFACE %s 未以 U 开头" % (fname, name))
                    continue
                iname = "I" + name[1:]
                if iname not in names:
                    errors.append("R3 %s 的 UINTERFACE %s 缺配对的 %s 类" % (fname, name, iname))
                else:
                    ibody = [b for k, n, b in bodies if n == iname][0]
                    if "GENERATED_BODY()" not in ibody:
                        errors.append("R3 %s 的 %s 类体里没有 GENERATED_BODY()" % (fname, iname))
    return errors


def check_native_event_calls(headers, sources):
    """R4 —— BlueprintNativeEvent 必须经 Execute_ 调用。"""
    errors = []
    events = set()
    for raw in headers.values():
        src = _strip_block_comments(raw)
        for m in re.finditer(r'UFUNCTION\s*\([^)]*BlueprintNativeEvent[^)]*\)\s*\n'
                             r'\s*[\w:<>,\s\*&]+?\b(\w+)\s*\(', src):
            events.add(m.group(1))
    for fname, raw in sorted(sources.items()):
        src = _strip_block_comments(raw)
        for ev in sorted(events):
            for m in re.finditer(r'(->|\.)\s*(%s)\s*\(' % re.escape(ev), src):
                errors.append('R4 %s 直呼了 BlueprintNativeEvent %s%s(…) —— 必须走 '
                              'Execute_%s(Obj, …),直呼会绕过蓝图实现' %
                              (fname, m.group(1), ev, ev))
    return errors, events


def check_gc_properties(headers):
    """R5 —— UCLASS 里持有 UObject 指针的成员必须 UPROPERTY(或 // GC-OK: 标注)。"""
    errors = []
    for fname, raw in sorted(headers.items()):
        src = _strip_block_comments(raw)
        bodies = _class_bodies(src)
        # 先找出"裸 struct 里藏了 UObject 指针"的类型名,供传递判定
        tainted = {n for k, n, b in bodies
                   if k != "UCLASS" and any(_UOBJ_MEMBER.search(l) for l in _member_lines(b))}
        for kind, name, body in bodies:
            if kind != "UCLASS":
                continue
            blines = body.split("\n")
            for i, line in enumerate(blines):
                if line not in _member_lines(body):
                    continue
                code = line.split("//")[0]
                holds = bool(_UOBJ_MEMBER.search(code)) or any(
                    re.search(r'\b%s\b' % re.escape(t), code) for t in tainted)
                if not holds:
                    continue
                if _GC_OK.search(line) or _gc_ok_above(blines, i):
                    continue
                if not _prev_meaningful(blines, i).startswith("UPROPERTY"):
                    errors.append('R5 %s::%s 的成员 `%s` 持有 UObject 指针却没有 UPROPERTY '
                                  '—— GC 看不见它;确有理由请就近写 `// GC-OK: 理由`'
                                  % (fname, name, code.strip()))
    return errors


def check_modules(headers, sources, declared):
    """R6 —— include 登记 + 所需模块 ⊆ mapping.md 声明的模块。"""
    errors, needed = [], set()
    own = {f[:-2] for f in headers}
    for fname, raw in sorted(dict(headers, **sources).items()):
        for inc in _INCLUDE.findall(_strip_block_comments(raw)):
            base = inc[:-len(".generated.h")] if inc.endswith(".generated.h") else inc[:-2]
            if base in own:
                continue                       # 自己人
            if inc not in INCLUDE_MODULE:
                errors.append('R6 %s 的 #include "%s" 未登记所属模块 '
                              '—— 请在 uht_lint.INCLUDE_MODULE 里登记并核对 Build.cs' % (fname, inc))
                continue
            needed.add(INCLUDE_MODULE[inc])
    for mod in sorted(needed - declared):
        errors.append('R6 代码需要模块 "%s",但 references/mapping.md §5 的 Build.cs 里没声明它'
                      % mod)
    return errors, needed


def declared_modules(md_src):
    """从 mapping.md §5 的 Build.cs 代码块里抽 PublicDependencyModuleNames。"""
    m = re.search(r'PublicDependencyModuleNames\.AddRange\s*\(\s*new\s+string\s*\[\]\s*\{(.*?)\}',
                  md_src, re.S)
    return set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()


# ── 汇总 ─────────────────────────────────────────────────────────────────────

def lint(headers, sources, md_src):
    errors = []
    errors += check_headers(headers)
    errors += check_native_event_calls(headers, sources)[0]
    errors += check_gc_properties(headers)
    errors += check_modules(headers, sources, declared_modules(md_src))[0]
    return errors


def run():
    headers, sources = {}, {}
    for fn in sorted(os.listdir(RUNTIME)):
        if fn.endswith(".h"):
            headers[fn] = _read(os.path.join(RUNTIME, fn))
        elif fn.endswith(".cpp"):
            sources[fn] = _read(os.path.join(RUNTIME, fn))
    return headers, sources, lint(headers, sources, _read(MAPPING_MD))


def main():
    headers, sources, errors = run()
    print("[uht-lint] 检查 %d 个头 / %d 个源" % (len(headers), len(sources)))
    if errors:
        for e in errors:
            print("[uht-lint] 违规: " + e, file=sys.stderr)
        return 1
    print("[uht-lint] R1-R6 全过(注意:这是规约门,不等于编译通过)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

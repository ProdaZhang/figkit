# -*- coding: utf-8 -*-
"""UE 反射规约门的测试。

同 test_contract.py 的思路:先对**真代码**断言全过,再对**故意写坏的合成头/源**
逐条断言"写错真会被抓"。没有牙口证明的静态门等于没有门。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import uht_lint as L   # noqa: E402

_MD = 'PublicDependencyModuleNames.AddRange(new string[] { "Core", "UMG" });'

_GOOD_H = '''#pragma once
#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "Good.generated.h"

UINTERFACE(MinimalAPI, Blueprintable)
class UMyHook : public UInterface
{
	GENERATED_BODY()
};

class IMyHook
{
	GENERATED_BODY()
public:
	UFUNCTION(BlueprintNativeEvent, Category = "X")
	void OnSend(const FString& Action);
};

UCLASS(ClassGroup = (FigmaUi), meta = (BlueprintSpawnableComponent))
class UMyWidget : public UUserWidget
{
	GENERATED_BODY()
public:
	UPROPERTY(Transient)
	TObjectPtr<UUserWidget> Child = nullptr;
};
'''
_GOOD_CPP = '''#include "Good.h"
void F(UObject* O) { IMyHook::Execute_OnSend(O, TEXT("Enter")); }
'''


def _headers(**kw):
    return kw


def _lint(headers, sources=None, md=_MD):
    return L.lint(headers, sources or {}, md)


# ── 真代码 ───────────────────────────────────────────────────────────────────

def test_real_runtime_passes():
    _, _, errors = L.run()
    assert not errors, "runtime/ 违反 UE 反射规约:\n  " + "\n  ".join(errors)


def test_real_runtime_is_actually_scanned():
    """防"全过"是因为什么都没扫到:类、事件、模块都得真抽出来。"""
    headers, sources, _ = L.run()
    kinds = [k for src in headers.values()
             for k, _, _ in L._class_bodies(L._strip_block_comments(src))]
    assert kinds.count("UCLASS") >= 3, kinds
    assert "UINTERFACE" in kinds, kinds
    events = L.check_native_event_calls(headers, sources)[1]
    assert len(events) >= 6, events
    needed = L.check_modules(headers, sources,
                             L.declared_modules(L._read(L.MAPPING_MD)))[1]
    assert {"UMG", "Json", "SlateCore"} <= needed, needed


def test_baseline_synthetic_is_clean():
    assert not _lint(_headers(**{"Good.h": _GOOD_H}), {"Good.cpp": _GOOD_CPP})


# ── R1 generated.h ───────────────────────────────────────────────────────────

def test_r1_missing_generated_include():
    bad = _GOOD_H.replace('#include "Good.generated.h"\n', "")
    assert any(e.startswith("R1") and "没 #include" in e
               for e in _lint({"Good.h": bad})), _lint({"Good.h": bad})


def test_r1_generated_include_not_last():
    bad = _GOOD_H.replace('#include "Blueprint/UserWidget.h"\n#include "Good.generated.h"\n',
                          '#include "Good.generated.h"\n#include "Blueprint/UserWidget.h"\n')
    assert any(e.startswith("R1") and "不是最后一个" in e for e in _lint({"Good.h": bad}))


def test_r1_generated_include_without_reflection():
    bad = '#pragma once\n#include "CoreMinimal.h"\n#include "Good.generated.h"\n'
    assert any(e.startswith("R1") and "却 include" in e for e in _lint({"Good.h": bad}))


# ── R2 / R3 ──────────────────────────────────────────────────────────────────

def test_r2_uclass_without_generated_body():
    bad = _GOOD_H.replace("\tGENERATED_BODY()\npublic:\n\tUPROPERTY(Transient)", "public:\n\tUPROPERTY(Transient)")
    errs = _lint({"Good.h": bad})
    assert any(e.startswith("R2") and "UMyWidget" in e for e in errs), errs


def test_r3_uinterface_without_i_class():
    bad = _GOOD_H.replace("class IMyHook\n{\n\tGENERATED_BODY()\npublic:",
                          "class ISomethingElse\n{\n\tGENERATED_BODY()\npublic:")
    errs = _lint({"Good.h": bad})
    assert any(e.startswith("R3") and "IMyHook" in e for e in errs), errs


def test_r3_i_class_without_generated_body():
    bad = _GOOD_H.replace("class IMyHook\n{\n\tGENERATED_BODY()\n", "class IMyHook\n{\n")
    errs = _lint({"Good.h": bad})
    assert any(e.startswith("R3") and "GENERATED_BODY" in e for e in errs), errs


# ── R4 BlueprintNativeEvent 必须走 Execute_ ─────────────────────────────────

def test_r4_direct_call_is_caught():
    cpp = '#include "Good.h"\nvoid F(IMyHook* H) { H->OnSend(TEXT("Enter")); }\n'
    errs = _lint({"Good.h": _GOOD_H}, {"Good.cpp": cpp})
    assert any(e.startswith("R4") and "OnSend" in e for e in errs), errs


def test_r4_execute_form_is_accepted():
    assert not [e for e in _lint({"Good.h": _GOOD_H}, {"Good.cpp": _GOOD_CPP})
                if e.startswith("R4")]


# ── R5 GC 可见性 ─────────────────────────────────────────────────────────────

def test_r5_raw_uobject_member_without_uproperty():
    bad = _GOOD_H.replace("\tUPROPERTY(Transient)\n\tTObjectPtr<UUserWidget> Child = nullptr;",
                          "\tUUserWidget* Child = nullptr;")
    errs = _lint({"Good.h": bad})
    assert any(e.startswith("R5") and "Child" in e for e in errs), errs


def test_r5_transitive_through_plain_struct():
    """裸 struct 里藏 UObject 指针,再被 UCLASS 以容器持有 —— 同样 GC 不可见。"""
    bad = _GOOD_H.replace("UCLASS(ClassGroup",
                          "struct FSlotInfo\n{\n\tUUserWidget* Panel = nullptr;\n};\n\nUCLASS(ClassGroup") \
                 .replace("\tUPROPERTY(Transient)\n\tTObjectPtr<UUserWidget> Child = nullptr;",
                          "\tTMap<FString, FSlotInfo> SlotById;")
    errs = _lint({"Good.h": bad})
    assert any(e.startswith("R5") and "SlotById" in e for e in errs), errs


def test_r5_gc_ok_comment_suppresses():
    ok = _GOOD_H.replace("\tUPROPERTY(Transient)\n\tTObjectPtr<UUserWidget> Child = nullptr;",
                         "\t// GC-OK: 索引不是持有,对象归 WidgetTree\n"
                         "\t// (多行说明也应生效)\n"
                         "\tUUserWidget* Child = nullptr;")
    assert not [e for e in _lint({"Good.h": ok}) if e.startswith("R5")]


# ── R6 模块登记 ─────────────────────────────────────────────────────────────

def test_r6_unregistered_include():
    bad = _GOOD_H.replace('#include "CoreMinimal.h"', '#include "Widgets/SOverlay.h"')
    errs = _lint({"Good.h": bad})
    assert any(e.startswith("R6") and "SOverlay.h" in e for e in errs), errs


def test_r6_module_missing_from_build_cs_doc():
    """代码要 SlateCore,但文档 Build.cs 只写了 Core/UMG → 必须报。"""
    bad = _GOOD_H.replace('#include "CoreMinimal.h"', '#include "Styling/SlateBrush.h"')
    errs = _lint({"Good.h": bad}, md=_MD)
    assert any(e.startswith("R6") and "SlateCore" in e for e in errs), errs


# ── 抽取器回归 ───────────────────────────────────────────────────────────────

def test_nested_paren_macro_still_sees_the_class():
    """UCLASS(ClassGroup = (X), meta = (Y)) 的嵌套括号曾让整个类漏检 —— 回归守卫。"""
    bodies = L._class_bodies(_GOOD_H)
    assert ("UCLASS", "UMyWidget") in [(k, n) for k, n, _ in bodies], bodies
    bad = _GOOD_H.replace("\tGENERATED_BODY()\npublic:\n\tUPROPERTY(Transient)", "public:\n\tUPROPERTY(Transient)")
    assert any(e.startswith("R2") for e in _lint({"Good.h": bad})), "嵌套括号类必须真被查"


def test_function_declarations_are_not_members():
    """`UWidget* MakeThing(...);` 是函数不是成员,别误报 R5。"""
    ok = _GOOD_H.replace("\tUPROPERTY(Transient)\n\tTObjectPtr<UUserWidget> Child = nullptr;",
                         "\tUUserWidget* MakeThing(const FString& Id) const;")
    assert not [e for e in _lint({"Good.h": ok}) if e.startswith("R5")]


def _run():
    ok = True
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception as e:
                ok = False
                print("FAIL", name, e)
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _run() else 1)

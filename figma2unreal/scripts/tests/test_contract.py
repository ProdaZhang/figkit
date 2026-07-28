# -*- coding: utf-8 -*-
"""uespec 契约对账门的测试。

两类:
  1. 对**真代码**跑,断言当前契约成立(没有未声明的跨语言漂移);
  2. 对**故意写坏的合成源码**跑,断言每种漂移都真的被抓 —— 证明这门有牙,
     而不是一个永远返回绿的摆设。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import uespec_contract as C   # noqa: E402


# ── 1. 真代码 ────────────────────────────────────────────────────────────────

def test_real_code_contract_holds():
    emitted, read, errors = C.run()
    assert not errors, "契约漂移:\n  " + "\n  ".join(errors)
    assert len(emitted) > 40 and len(read) > 40, \
        "抽取结果异常少(%d/%d),疑似正则失效而非真的没字段" % (len(emitted), len(read))


def test_real_code_reads_nothing_unemitted():
    """最危险的一向单独断言:C++ 读的每个字段 python 都产。"""
    emitted, read, _ = C.run()
    assert not (read - emitted), "C++ 读了没人产的字段: %s" % sorted(read - emitted)


def test_every_waiver_has_reason():
    for k, why in C.WAIVERS.items():
        assert isinstance(why, str) and len(why) >= 8, "豁免 %r 的理由太敷衍" % k


# ── 2. 牙口:故意漂移必须被抓 ────────────────────────────────────────────────

_PY_OK = '''
def convert_cap(cap):
    return {'version': 1, 'els': [{'id': 'a', 'w': 1}]}
'''
_CPP_OK = '''
void F() {
    Spec->TryGetArrayField(TEXT("els"), Els);
    JNum(El, TEXT("w"));
    El->TryGetStringField(TEXT("id"), Id);
}
'''
_WAIVE_OK = {"version": "元数据,不参与建树"}


def _errs(py, cpp, waivers):
    return C.check(C.emitted_keys(py), C.read_keys(cpp), waivers)


def test_baseline_synthetic_is_clean():
    """先证明这套合成样本本身是绿的,后面的红才说明问题出在注入的缺陷上。"""
    assert not _errs(_PY_OK, _CPP_OK, _WAIVE_OK)


def test_teeth_cpp_reads_field_nobody_emits():
    cpp = _CPP_OK + '\nvoid G() { JStr(El, TEXT("hitArea")); }\n'
    errs = _errs(_PY_OK, cpp, _WAIVE_OK)
    assert any("hitArea" in e and "从不产出" in e for e in errs), errs


def test_teeth_python_emits_field_nobody_reads():
    py = _PY_OK.replace("'w': 1", "'w': 1, 'skewX': 0")
    errs = _errs(py, _CPP_OK, _WAIVE_OK)
    assert any("skewX" in e and "从不读" in e for e in errs), errs


def test_teeth_stale_waiver_now_read():
    """字段后来接上了,豁免却没删 → 必须报,否则豁免表会烂成免死金牌。"""
    cpp = _CPP_OK + '\nvoid G() { JNum(Spec, TEXT("version")); }\n'
    errs = _errs(_PY_OK, cpp, _WAIVE_OK)
    assert any("version" in e and "陈旧豁免" in e for e in errs), errs


def test_teeth_stale_waiver_no_longer_emitted():
    waivers = dict(_WAIVE_OK, ghostField="早就删了的字段")
    errs = _errs(_PY_OK, _CPP_OK, waivers)
    assert any("ghostField" in e and "陈旧豁免" in e for e in errs), errs


# ── 3. 抽取器本身的陷阱 ─────────────────────────────────────────────────────

def test_log_format_string_is_not_a_field_name():
    """UE_LOG 的 TEXT 格式串与取值调用同语句时,不能被当成字段名(实际踩过的坑)。"""
    cpp = ('void F() { UE_LOG(LogFigmaUi, Verbose, TEXT("[known-loss] shadow: %s"), '
           '*JStr(El, TEXT("id"))); }')
    assert C.read_keys(cpp) == {"id"}


def test_module_level_lookup_tables_are_not_emissions():
    """_IMG_MODE / _ALIGN 这类模块级查表的键不是产出字段。"""
    py = "_ALIGN = {'flex-start': 'start'}\n" + _PY_OK
    assert "flex-start" not in C.emitted_keys(py)


def test_subscript_assignment_counts_as_emission():
    """out['checkbox'] = {...} 这种下标赋值也是产出,不能漏。"""
    py = "def f():\n    out = {}\n    out['checkbox'] = {'flag': ''}\n    return out\n"
    assert {"checkbox", "flag"} <= C.emitted_keys(py)


def test_subscript_read_is_not_an_emission():
    """读入参的 e['x'] 不是产出,别把上游 IR 的键算进来。"""
    py = "def f(e):\n    return {'absX': e['x']}\n"
    keys = C.emitted_keys(py)
    assert "absX" in keys and "x" not in keys


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
